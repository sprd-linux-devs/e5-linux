#!/usr/bin/env python3
"""Apply shared Unisoc networking fixes and explicit board defaults to a root.

The historical path is retained for installed update hooks. PDP retries apply
equally to E5, T551M and M8; only radio capability defaults are board-specific.
"""
import argparse
from pathlib import Path
import re


# Based on mu300-linux 47d9463d; fixed channel fallback, no bandwidth changes.
NO_DFS = '''// unisoc-driver-dfs-capabilities: fixed fallback preserving bandwidth.
function device_no_dfs(config) {
	if (config.band != '5g' || phy_features.radar_detect)
		return;
	let radar = {};
	for (let f in phy_capabilities.freqs) {
		let chan = (f.freq - 5000) / 5;
		if (f.radar)
			radar[chan] = true;
	}
	if (!config.channel) {
		config.acs_exclude_dfs = true;
		return;
	}
	if (!radar[config.channel])
		return;
	// Fixed fallback requested by the user: only replace the primary channel.
	// hostapd/nl80211 retain their normal width and regulatory validation.
	log(`driver lacks radar detection: using channel 36 instead of DFS channel ${config.channel}, preserving ${config.htmode}`);
	config.channel = 36;
}

'''


def patch_wifi_capabilities(root):
    path = root / 'usr/share/ucode/wifi/hostapd.uc'
    if not path.exists():
        return
    text = path.read_text()
    marker = '// unisoc-driver-dfs-capabilities:'
    if marker in text:
        # Upgrade roots carrying the earlier auto-shrink policy too. Keep
        # imports/capability collection/call site intact and replace only our
        # marked policy section, which immediately precedes generate().
        start = text.index(marker)
        end = text.index('function generate(config) {', start)
        if text[start:end] != NO_DFS:
            path.write_text(text[:start] + NO_DFS + text[end:])
        return
    replacements = [
        ('wiphy_info, wiphy_band\n', 'wiphy_info, wiphy_band, log\n'),
        # New wifi-scripts moved cipher flags to ap.uc. Collect DFS capability
        # beside the shared phy/band lookup, which exists in both generators.
        ("\tlet band = wiphy_band(phy, config.band);",
         "\tlet band = wiphy_band(phy, config.band);\n"
         "\tphy_features.radar_detect = length(filter(phy.interface_combinations ?? [], (c) => c.radar_detect_widths)) > 0;\n"
         "\tphy_capabilities.freqs = band?.freqs ?? [];"),
        ('function generate(config) {', NO_DFS + 'function generate(config) {'),
        ('\tset_device_defaults(config);\n', '\tset_device_defaults(config);\n\tdevice_no_dfs(config);\n'),
    ]
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError('Unexpected wifi-scripts hostapd.uc: ' + old[:70])
        text = text.replace(old, new)
    path.write_text(text)


CONNECT_RETRY = r'''# unisoc-pdp-connect-retry: setup-owned recovery without disabling the radio.
# unisoc-ps-registration-recovery: leave offline recovery to registration events.
modemmanager_unisoc_wait_for_ps() {
	[ "$1" = unisoc-sipc ] || return 1
	case "$2" in
		*Error.MobileEquipment.NetworkTimeout:*|*Error.MobileEquipment.NoNetwork:*|\
		*Error.Connection.NoCarrier:*|*Error.Core.Timeout:*|*Error.Core.Retry:*|\
		*Error.Core.WrongState:*|*Error.Core.Cancelled:*) ;;
		*) return 1 ;;
	esac
	local status state packet
	status=$(mmcli --modem="$1" --output-keyvalue 2>/dev/null) || return 1
	state=$(modemmanager_get_field "$status" modem.generic.state)
	packet=$(modemmanager_get_field "$status" modem.3gpp.packet-service-state)
	case "$state:$packet" in
		searching:*|enabled:detached|registered:detached) return 0 ;;
		*) return 1 ;;
	esac
}

modemmanager_unisoc_block_restart() {
	if [ "$2" = unisoc-sipc ] && [ "${MODEMMANAGER_UNISOC_WAIT_PS:-0}" = 1 ]; then
		# Unlike block_restart, availability preserves the user's autostart
		# intent. The PS event subscriber makes it available after reattach.
		proto_set_available "$1" 0
	else
		proto_block_restart "$1"
	fi
}

modemmanager_unisoc_retryable() {
	case "$1" in
		*Error.Core.Cancelled:*|*Error.Core.WrongState:*)
			# Losing registration can cancel the bearer inside MM while the
			# setup request is still wanted. A user ifdown terminates this
			# shell through the TERM trap instead; do not revive a disabled
			# modem or turn a missing status into permission to reconnect.
			local status state
			status=$(mmcli --modem="$2" --output-keyvalue 2>/dev/null) || return 1
			state=$(modemmanager_get_field "$status" modem.generic.state)
			case "$state" in
				enabling|connecting|disconnecting) return 0 ;;
				enabled|searching|registered|connected)
					case "$1" in *Error.Core.Cancelled:*) return 0 ;; esac ;;
			esac
			return 1 ;;
		*Error.MobileEquipment.Sim*|*Error.MobileEquipment.IncorrectPassword:*|\
		*Error.MobileEquipment.NetworkNotAllowed:*|*Error.MobileEquipment.GprsAuthenticationFailure:*|\
		*Error.Core.InvalidArgs:*|*Error.Core.Unsupported:*) return 1 ;;
		*Error.MobileEquipment.NetworkTimeout:*|*Error.MobileEquipment.NoNetwork:*|\
		*Error.Connection.NoCarrier:*|*Error.Core.Timeout:*|*Error.Serial.ResponseTimeout:*|\
		*Error.Core.Retry:*|*Error.Core.InProgress:*|*"No IPv4 settings for PDP context "*) return 0 ;;
		*"Couldn't activate PDP context "*"Unknown mobile equipment error: 28'"*) return 0 ;;
		*) return 1 ;;
	esac
}

modemmanager_unisoc_retry() {
	local device="$1" operation="$2" argument="$3"
	local attempt=1 delay=1 result rc output retry_child saved_traps
	MODEMMANAGER_UNISOC_WAIT_PS=0
	# Leave other modem plugins on their original single-attempt behavior.
	if [ "$device" != unisoc-sipc ]; then
		case "$operation" in
			connect) mmcli --modem="$device" --timeout 120 --simple-connect="$argument" ;;
			register) mmcli --modem="$device" --timeout 120 --3gpp-register-in-operator="$argument" ;;
			*) return 2 ;;
		esac
		return $?
	fi
	output=$(mktemp /tmp/mm-unisoc-start.XXXXXX) || return 1
	saved_traps=$(trap)
	# netifd cancels setup with SIGTERM on ifdown/reload. Background children
	# plus an interruptible wait allow us to stop mmcli/sleep before exiting.
	trap '[ -z "$retry_child" ] || { kill "$retry_child" 2>/dev/null; wait "$retry_child" 2>/dev/null; }; rm -f "$output"; exit 143' TERM INT
	while :; do
		case "$operation" in
			connect) mmcli --modem="$device" --timeout 120 --simple-connect="$argument" >"$output" 2>&1 & ;;
			register) mmcli --modem="$device" --timeout 120 --3gpp-register-in-operator="$argument" >"$output" 2>&1 & ;;
			*) rc=2; break ;;
		esac
		retry_child=$!
		wait "$retry_child"; rc=$?
		retry_child=
		result=$(cat "$output")
		printf '%s\n' "$result"
		[ "$rc" -eq 0 ] && break
		if modemmanager_unisoc_wait_for_ps "$device" "$result"; then
			MODEMMANAGER_UNISOC_WAIT_PS=1
			echo 'Packet service unavailable; waiting for registration event'
			break
		fi
		modemmanager_unisoc_retryable "$result" "$device" || break
		echo "Unisoc $operation temporarily unavailable; retrying in ${delay}s (attempt $attempt)"
		sleep "$delay" & retry_child=$!
		wait "$retry_child"
		retry_child=
		attempt=$((attempt + 1))
		# Repeat the user-selected transient retry cadence without a cap.
		# Registration loss above still waits for the existing PS events.
		case "$delay" in
			1|3|5) delay=$((delay + 2)) ;;
			*) delay=1 ;;
		esac
	done
	rm -f "$output"
	trap - TERM INT
	# trap output is generated by this shell, never modem data or configuration.
	[ -z "$saved_traps" ] || eval "$saved_traps"
	return "$rc"
}

modemmanager_connect_retry() {
	modemmanager_unisoc_retry "$1" connect "$2"
}

modemmanager_register_retry() {
	modemmanager_unisoc_retry "$1" register "$2"
}

'''

# Resolve private profile credentials into local netifd variables only. Do not
# eval JSON, rewrite global UCI during a SIM switch, or log usernames/passwords.
RADIO_POLICY = '''\t# unisoc-user-radio-policy: wait without retrying an explicitly disabled SIM.
\tif [ "$device" = unisoc-sipc ] && [ -e /etc/e5/sim-radio ] &&
\t   ! /usr/libexec/unisoc-modem/radio-allowed "$(cat /sys/module/sipc_wwan/parameters/card)"; then
\t\tproto_notify_error "$interface" SIM_RADIO_DISABLED
\t\tproto_set_available "$interface" 0
\t\treturn 1
\tfi
'''

APN_SELECTION = '''\t# unisoc-apn-selection: shared by E5, T551M and M8 on every dial.
\tif [ "$device" = unisoc-sipc ] && [ -x /usr/libexec/unisoc-modem/apn ]; then
\t\tlocal apn_selection apn_family apn_auth apn_source
\t\tapn_selection=$(/usr/libexec/unisoc-modem/apn resolve "$device")
\t\tif [ "$(printf '%s' "$apn_selection" | jsonfilter -e '@.ok')" != 1 ]; then
\t\t\tproto_notify_error "$interface" APN_PROFILE_INVALID
\t\t\treturn 1
\t\tfi
\t\tapn_source=$(printf '%s' "$apn_selection" | jsonfilter -e '@.source')
\t\tif [ "$interface" = "$(printf '%s' "$apn_selection" | jsonfilter -e '@.iface')" ] && [ "$apn_source" != network ]; then
\t\t\tapn=$(printf '%s' "$apn_selection" | jsonfilter -e '@.settings.apn')
\t\t\tusername=$(printf '%s' "$apn_selection" | jsonfilter -e '@.settings.username')
\t\t\tpassword=$(printf '%s' "$apn_selection" | jsonfilter -e '@.settings.password')
\t\t\tapn_family=$(printf '%s' "$apn_selection" | jsonfilter -e '@.settings.pdptype')
\t\t\tcase "$apn_family" in IP) iptype=ipv4 ;; IPV4V6) iptype=ipv4v6 ;; *) return 1 ;; esac
\t\t\tapn_auth=$(printf '%s' "$apn_selection" | jsonfilter -e '@.settings.auth')
\t\t\tcase "$apn_auth" in papchap) allowedauth='pap chap' ;; none|pap|chap) allowedauth=$apn_auth ;; *) return 1 ;; esac
\t\t\tinit_epsbearer=keep
\t\tfi
\t\tunset apn_selection
\tfi
'''


VENDOR_BOOT = '''
# e5-early-vendor: normal boots overlap CP loading with later init services.
# Charge-only boots still wait for S14 and the existing power-key policy.
boot() {
    touch /run/e5-vendor-deferred
    local policy
    policy=$(/usr/bin/python3 /usr/libexec/e5-charge-mode --radio-boot-policy) || return 1
    case "$policy" in
        early) rm -f /run/e5-vendor-deferred; start ;;
        defer) return 0 ;;
        *) logger -t e5-vendor 'Invalid charge-only boot policy'; return 1 ;;
    esac
}
'''

VENDOR_PARTITION_READ = '''  [ -r "$u" ] || continue
  d=${u%/uevent}; d=${d##*/}
  n=
  while IFS='=' read -r k v; do [ "$k" != PARTNAME ] || n=$v; done < "$u"'''

VENDOR_LOG_WAIT = '''# e5-log-socket-ready: chroot setup overlaps logdw; wait on readiness.
i=0
until [ -S /dev/socket/logdw ]; do
    i=$((i + 1))
    [ "$i" -lt 100 ] || { echo "Android log socket unavailable" >&2; exit 4; }
    /opt/e5/bin/busybox usleep 10000
done
'''


def patch_vendor_startup(root):
    """Preserve each model's NV/slot setup, moving only the normal boot entry."""
    service = root / 'etc/init.d/e5-vendor'
    if not service.exists():
        return
    text = service.read_text()
    text, count = re.subn(r'^START=(?:20|09)$', 'START=09', text, flags=re.M)
    if count != 1:
        raise ValueError('Unexpected vendor startup priority')
    # The target's /bin/sleep rejects fractions. A failed sleep exhausted the
    # preparation gate instantly and made procd retry the NV daemon 5 s later.
    text = text.replace('sleep 0.1; done; exec /opt/e5/android-run cp_diskserver',
                        '/opt/e5/bin/busybox usleep 100000; done; exec /opt/e5/android-run cp_diskserver')
    if '# e5-early-vendor:' not in text:
        if re.search(r'^boot\(\)', text, flags=re.M):
            raise ValueError('Unexpected vendor boot gate')
        text += VENDOR_BOOT
    # Validate owned entries before changing the service or links.
    for name in ('S20e5-vendor', 'S09e5-vendor'):
        link = root / 'etc/rc.d' / name
        if link.is_symlink():
            if link.readlink().as_posix() != '../init.d/e5-vendor':
                raise ValueError('Foreign vendor startup link: ' + str(link))
        elif link.exists():
            raise ValueError('Occupied vendor startup link: ' + str(link))
    vendor = root / 'opt/e5/vendor-start.sh'
    if vendor.exists():
        body = vendor.read_text()
        old = '  d=$(basename "$(dirname "$u")"); n=$(sed -n \'s/^PARTNAME=//p\' "$u")'
        if old in body:
            body = body.replace(old, VENDOR_PARTITION_READ)
        elif VENDOR_PARTITION_READ not in body:
            raise ValueError('Unexpected vendor partition enumeration')
        if '# e5-log-socket-ready:' not in body:
            if body.count('  sleep 1\n') != 1:
                raise ValueError('Unexpected vendor log socket setup')
            body = body.replace('  sleep 1\n', '')
            anchor = ('touch /run/e5-vendor-prepared\n' if 'touch /run/e5-vendor-prepared\n' in body
                      else 'echo "stage=exec"\n')
            if body.count(anchor) != 1:
                raise ValueError('Unexpected vendor preparation boundary')
            body = body.replace(anchor, VENDOR_LOG_WAIT + anchor)
        body = body.replace('    sleep 0.01\n', '    /opt/e5/bin/busybox usleep 10000\n')
        vendor.write_text(body)
    service.write_text(text)
    old = root / 'etc/rc.d/S20e5-vendor'
    old.unlink(missing_ok=True)
    link = root / 'etc/rc.d/S09e5-vendor'
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.is_symlink():
        link.symlink_to('../init.d/e5-vendor')


def patch_root(root, profile='t551m'):
    if profile not in ('t551m', 'e5', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60', 'y60'):
        raise ValueError('Unknown device profile: ' + profile)
    patch_vendor_startup(root)
    # Also install through the on-device update hook, after package defaults.
    boot_wait = root / 'lib/preinit/01_e5_boot_wait'
    boot_wait.parent.mkdir(parents=True, exist_ok=True)
    boot_wait.write_text('# Keep keyboard/button failsafe available for one second.\n'
                         'fs_failsafe_wait_timeout=1\n')
    for asset in ('usr/libexec/e5-network-recovery', 'etc/init.d/e5-network-recovery'):
        source = Path(__file__).resolve().parents[2] / 'openwrt/overlay' / asset
        target = root / asset
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
            target.chmod(0o755)
    if (root / 'etc/init.d/e5-network-recovery').exists():
        for link in ('S96', 'K10'):
            target = root / ('etc/rc.d/' + link + 'e5-network-recovery')
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_symlink():
                target.symlink_to('../init.d/e5-network-recovery')
    discovery = root / 'usr/libexec/e5-mm-report-ports'
    discovery.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[2] / 'openwrt/overlay/usr/libexec/e5-mm-report-ports'
    if source.is_file():
        discovery.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
    elif not discovery.is_file():
        # On-device update hooks live in /opt/e5, outside the source tree.
        # The helper is installed by the common overlay before these run.
        raise ValueError('Missing shared SIPC port discovery helper')
    discovery.chmod(0o755)
    # The APK update path must replace the old CID-1-only hotplug handler too.
    hotplug = Path('etc/hotplug.d/wwan/26-e5-sipa-eth')
    source = Path(__file__).resolve().parents[2] / 'openwrt/overlay' / hotplug
    if source.is_file():
        target = root / hotplug
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o755)
    patch_wifi_capabilities(root)
    config = root / 'etc/config/unisoc_modem'
    if config.exists():
        text = config.read_text()
        anchor = "config core 'main'\n"
        additions = ''
        # Board-owned default and user override are separate. Never rewrite an
        # explicit 134/152 choice when assembling or updating a system.
        default = '152'
        if re.search(r'^\s*option auto_work_mode_default\s+', text, re.M):
            text = re.sub(r'^(\s*option auto_work_mode_default)\s+.*$',
                          lambda m: m[1] + " '" + default + "'", text, flags=re.M)
        else:
            additions += "\toption auto_work_mode_default '" + default + "'\n"
        if 'option auto_work_mode ' not in text:
            additions += "\toption auto_work_mode 'default'\n"
        # This firmware drops B38 from SPLBAND readback; the imported
        # dashboard's larger fallback list is not a capability query.
        if profile == 't551m' and 'option lte_supported_bands ' not in text:
            additions += "\toption lte_supported_bands '1,3,5,8,34,39,40,41'\n"
        if additions:
            if text.count(anchor) != 1:
                raise ValueError('Unexpected modem dashboard configuration')
            text = text.replace(anchor, anchor + additions)
        config.write_text(text)

    wrapper = root / 'usr/sbin/ModemManager-wrapper'
    if wrapper.exists():
        text = wrapper.read_text()
        if '# unisoc-pre-dial-replay' not in text:
            anchor = '\t/usr/sbin/ModemManager "$@" 1>/dev/null 2>/dev/null &'
            if text.count(anchor) != 1:
                raise ValueError('Unexpected ModemManager startup wrapper')
            text = text.replace(anchor, '''\t# unisoc-pre-dial-replay: finish saved AT settings before MM can enable/dial.
\tif [ -x /usr/libexec/unisoc-modem/boot-replay ]; then
\t\t/usr/libexec/unisoc-modem/boot-replay early ||
\t\t\tlogger -t unisoc-modem "pre-dial replay failed; continuing without a late radio cycle"
\tfi

''' + anchor)
        if '# unisoc-port-discovery:' not in text:
            anchor = '\tmm_report_events_from_cache\n'
            if text.count(anchor) != 1:
                raise ValueError('Unexpected ModemManager event replay location')
            text = text.replace(anchor, anchor + '''\t# unisoc-port-discovery: recover a port created before MM started.
\t[ ! -x /usr/libexec/e5-mm-report-ports ] || /usr/libexec/e5-mm-report-ports
''')
        wrapper.write_text(text)

    loader = root / 'etc/init.d/e5-sipc-wwan'
    if loader.exists():
        text = loader.read_text()
        # Migrate already patched roots as well as raw package loaders.
        text = re.sub(r' tx_gap_ms=\d+', '', text)
        old = 'insmod $M/sipc_wwan.ko card=$C'
        if text.count(old) != 1:
            raise ValueError('Unexpected SIPC loader')
        text = text.replace(old, old + ' tx_gap_ms=50')
        text = text.replace('insmod $M/sipc_wwan.ko;', 'insmod $M/sipc_wwan.ko tx_gap_ms=50;')
        if '# unisoc-port-discovery:' not in text:
            anchor = '\t\techo "sipc_wwan loaded, SIM card $C"'
            if text.count(anchor) != 1:
                raise ValueError('Unexpected SIPC port discovery location')
            text = text.replace(anchor, '''\t\t# unisoc-port-discovery: bypass the global hotplug queue after probe closes.
\t\t[ ! -x /usr/libexec/e5-mm-report-ports ] || /usr/libexec/e5-mm-report-ports
''' + anchor)
        loader.write_text(text)

    proto = root / 'lib/netifd/proto/modemmanager.sh'
    if proto.exists():
        text = proto.read_text()
        if '# unisoc-data-rf-independent:' not in text:
            old = '\tlocal disable="$(uci_get network "$interface" disable_modem "1")"'
            new = '''\t# unisoc-data-rf-independent: Android data-off leaves RF for calls/SMS.
\tlocal disable_default=1
\t[ "$device" != unisoc-sipc ] || disable_default=0
\tlocal disable="$(uci_get network "$interface" disable_modem "$disable_default")"'''
            if text.count(old) != 1:
                raise ValueError('Unexpected ModemManager data teardown location')
            text = text.replace(old, new)
            proto.write_text(text)
        if '# unisoc-user-radio-policy:' not in text:
            anchor = '\t# always cleanup before attempting a new connection, just in case\n'
            if text.count(anchor) != 1:
                raise ValueError('Unexpected ModemManager RF policy hook location')
            text = text.replace(anchor, RADIO_POLICY + anchor)
            proto.write_text(text)
        if '# unisoc-apn-selection:' not in text:
            anchor = '\t# set initial eps bearer settings\n'
            if text.count(anchor) != 1:
                raise ValueError('Unexpected ModemManager APN hook location')
            text = text.replace(anchor, APN_SELECTION + anchor)
            proto.write_text(text)
        if 'preserve AT-selected network mode' not in text:
            old = '\tif [ -z "${allowedmode}" ]; then\n\t\tmodemmanager_set_allowed_mode "$device" "$interface" "any"'
            if text.count(old) != 1:
                raise ValueError('Unexpected ModemManager default mode configuration')
            text = text.replace(old, '''\tif [ -z "${allowedmode}" ]; then
\t\t# preserve AT-selected network mode; Unisoc's MM mode setter is unsupported.
\t\t# Boot replay already applied the user's preference before radio activation.
\t\techo "Keeping current network mode (no WAN override configured)"''')
            proto.write_text(text)
        if 'T551M: preserve initial EPS' not in text:
            old = '\t\tcase "$init_epsbearer" in\n'
            if text.count(old) != 1:
                raise ValueError('Unexpected ModemManager initial EPS configuration')
            text = text.replace(old, old + '''\t\t\t"keep")
\t\t\t\t# T551M: preserve initial EPS; simple-connect still sets the APN.
\t\t\t\t# Rewriting it after registration forces CFUN=4/1 and a second search.
\t\t\t\techo "Keeping initial EPS bearer; applying connection APN at dial"
\t\t\t\t;;
''')
            proto.write_text(text)

        retry_marker = '# unisoc-pdp-connect-retry:'
        anchor = 'proto_modemmanager_setup() {'
        call = '\tmmcli --modem="${device}" --timeout 120 --simple-connect="${connectargs}" || {'
        if retry_marker in text:
            start = text.index(retry_marker)
            end = text.index(anchor, start)
            text = text[:start] + CONNECT_RETRY + text[end:]
        else:
            if text.count(anchor) != 1 or text.count(call) != 1:
                raise ValueError('Unexpected ModemManager connect configuration')
            text = text.replace(anchor, CONNECT_RETRY + anchor)
            text = text.replace(call, '\tmodemmanager_connect_retry "$device" "$connectargs" || {')
        register = ('\tmmcli --modem="${device}" \\\n'
                    '\t\t--timeout 120 \\\n'
                    '\t\t--3gpp-register-in-operator="${plmn}" || {')
        replacement = '\tmodemmanager_register_retry "$device" "$plmn" || {'
        if register in text:
            if text.count(register) != 1:
                raise ValueError('Unexpected ModemManager registration configuration')
            text = text.replace(register, replacement)
        elif text.count(replacement) != 1:
            raise ValueError('Unexpected ModemManager registration retry hook')
        # No SIM is an event wait, not a permanent user ifdown. Hot-swap
        # reprobes the same device and the existing recovery service resumes
        # it only after genuine registration, preserving autostart intent.
        missing = '\t\t\tproto_notify_error "${interface}" MM_FAILED_REASON_SIM_MISSING\n'
        original = missing + '\t\t\tproto_block_restart "${interface}"'
        replacement = missing + '''\t\t\tif [ "$device" = unisoc-sipc ]; then
\t\t\t\tproto_set_available "$interface" 0
\t\t\telse
\t\t\t\tproto_block_restart "${interface}"
\t\t\tfi'''
        # Older staging runs also rewrote the generic else branch below.
        # Normalize it before validating/updating this shared hook again.
        text = text.replace(replacement.replace('proto_block_restart "${interface}"',
                            'modemmanager_unisoc_block_restart "$interface" "$device"'), replacement)
        if original in text:
            text = text.replace(original, replacement)
        elif replacement not in text:
            raise ValueError('Unexpected ModemManager missing SIM handling')
        # Only registration/connection failure paths participate. PIN,
        # credentials, explicit modes and other modem plugins keep their rules.
        for start_marker, end_marker in (
                ('modemmanager_set_plmn() {', retry_marker),
                (anchor, 'proto_modemmanager_teardown() {')):
            start = text.index(start_marker)
            end = text.index(end_marker, start)
            body = text[start:end]
            body = body.replace(replacement, '# unisoc-missing-sim-guard-placeholder')
            body = body.replace('proto_block_restart "${interface}"',
                                'modemmanager_unisoc_block_restart "$interface" "$device"')
            body = body.replace('# unisoc-missing-sim-guard-placeholder', replacement)
            text = text[:start] + body + text[end:]
        proto.write_text(text)

    luci = root / 'www/luci-static/resources/protocol/modemmanager.js'
    if luci.exists():
        text = luci.read_text()
        if "o.value('keep'" not in text:
            # Works with the upstream readable source and APK's minified source.
            pattern = r"(o\.value\(\s*'custom'\s*,\s*'custom'\s*\);)"
            text, count = re.subn(pattern,
                r"\1o.value('keep', _('Keep existing initial EPS bearer'));", text)
            if count != 1:
                raise ValueError('Unexpected ModemManager LuCI options')
            luci.write_text(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--profile', choices=('t551m', 'e5', 'm8', 't512n', 'yuanhang41s', 'k1', 'lym10k', 'changxing60', 'y60'), default='t551m')
    args = parser.parse_args()
    patch_root(args.root, args.profile)
