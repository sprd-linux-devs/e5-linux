#!/usr/bin/env python3
"""SC2355 lifetime/log fixes for the pinned E5/T551M/M8 kernel.

Adapted from dikeckaan/mu300-linux bd1d471f, f34bf501 and 48a9c432.
Keep our SDIO implementation, reset work and existing TX fixes.
"""
from pathlib import Path
import re
import runpy


def stage(root):
    """Refresh recovery in existing offline roots as well as clean images."""
    root = Path(root).resolve()
    if root == Path('/').resolve():
        raise ValueError('Expected an offline root')
    for name in ('etc/hotplug.d/ieee80211/90-sc2355-recovery',
                 'etc/hotplug.d/ieee80211/20-e5-first-wireless',
                 'etc/init.d/e5-first-wireless', 'usr/libexec/e5-first-wireless'):
        source = Path(__file__).resolve().parents[1] / 'openwrt/overlay' / name
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o755)
    link = root / 'etc/rc.d/S92e5-first-wireless'
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.is_symlink():
        link.symlink_to('../init.d/e5-first-wireless')


def apply(kernel):
    base = Path(kernel) / 'drivers/unisoc_platform/sprd_wlan_combo'

    def edit(name, old, new):
        path = base / name
        text = path.read_text()
        if new in text:
            return
        if text.count(old) != 1:
            raise ValueError('Unexpected SC2355 source: ' + name + ': ' + old[:65])
        path.write_text(text.replace(old, new, 1))

    name = 'common/iface.c'
    path = base / name
    text = path.read_text()
    if 'Register reset last: failed probe must not leave callbacks into priv.' not in text:
        start = text.index('static int iface_notify_init(')
        end = text.index('\nstatic void iface_init_vif(', start)
        text = text[:start] + '''static int iface_notify_init(struct sprd_priv *priv)
{
	struct sprd_hif *hif = &priv->hif;
	int ret;

	/* Register reset last: failed probe must not leave callbacks into priv. */
	mutex_init(&hif->reset_lock);
	ret = misc_register(&wlan_misc_device);
	if (ret)
		goto err_lock;
	ret = register_inetaddr_notifier(&iface_inetaddr_cb);
	if (ret)
		goto err_misc;
	if (priv->fw_capa & SPRD_CAPA_NS_OFFLOAD) {
		ret = register_inet6addr_notifier(&iface_inet6addr_cb);
		if (ret)
			goto err_inet;
	}
	ret = atomic_notifier_chain_register(&wcn_reset_notifier_list,
					     &iface_host_reset_cb);
	if (!ret)
		return 0;
	if (priv->fw_capa & SPRD_CAPA_NS_OFFLOAD)
		unregister_inet6addr_notifier(&iface_inet6addr_cb);
err_inet:
	unregister_inetaddr_notifier(&iface_inetaddr_cb);
err_misc:
	misc_deregister(&wlan_misc_device);
err_lock:
	mutex_destroy(&hif->reset_lock);
	return ret;
}

static void iface_notify_deinit(struct sprd_priv *priv)
{
	struct sprd_hif *hif = &priv->hif;

	/* Stop the producer before its work, misc device and mutex disappear. */
	atomic_notifier_chain_unregister(&wcn_reset_notifier_list,
					 &iface_host_reset_cb);
	cancel_delayed_work_sync(&priv->reset_delay_work);
#ifdef DRV_RESET_SELF
	sprd_cancel_reset_work(priv);
#endif
	if (priv->fw_capa & SPRD_CAPA_NS_OFFLOAD)
		unregister_inet6addr_notifier(&iface_inet6addr_cb);
	unregister_inetaddr_notifier(&iface_inetaddr_cb);
	misc_deregister(&wlan_misc_device);
	mutex_destroy(&hif->reset_lock);
}
''' + text[end:]
        path.write_text(text)
    edit(name, 'static int iface_core_deinit(struct sprd_priv *priv)\n{\n',
         'static int iface_core_deinit(struct sprd_priv *priv)\n{\n'
         '\t/* No scan timeout may race vif destruction or rearm itself. */\n'
         '\ttimer_shutdown_sync(&priv->scan_timer);\n')
    edit(name, '\tsprd_debug_init(&priv->debug);\nout:\n\treturn ret;',
         '\tsprd_debug_init(&priv->debug);\nout:\n'
         '\tif (ret) {\n\t\tsprd_vendor_deinit(priv, wiphy);\n'
         '\t\tsprd_tcp_ack_deinit(priv);\n\t}\n\treturn ret;')
    edit(name, '\tret = sprd_iface_set_power(hif, true);\n\tif (ret)\n\t\treturn ret;\n\n\tiface_notify_deinit(priv);',
         '\tret = sprd_iface_set_power(hif, true);\n\tif (ret)\n'
         '\t\twl_err("WCN power-on failed (%d); continuing host teardown\\n", ret);\n\n'
         '\tiface_notify_deinit(priv);')
    edit(name, '\tiface_core_deinit(priv);\n\tsprd_iface_set_power(hif, false);',
         '\tiface_core_deinit(priv);\n\tif (!ret)\n\t\tsprd_iface_set_power(hif, false);')
    edit('common/cfg80211.c', '\tcfg80211_deinit_work(priv);',
         '\t/* Stop the timer before destroying the work it can queue. */\n'
         '\ttimer_shutdown_sync(&priv->scan_timer);\n\tcfg80211_deinit_work(priv);')
    path = base / 'sc2355/tcp_ack.c'
    text = path.read_text()
    start = text.index('void sc2355_tcp_ack_deinit(')
    if 'Wait outside the callback\'s seqlock' not in text[start:]:
        end = text.index('\n}', start)
        text = text[:end] + '''

	/* Wait outside the callback's seqlock, before priv/ack_m can be freed.
	 * Shutdown also rejects a late rearm from a producer already in flight.
	 */
	for (i = 0; i < SPRD_TCP_ACK_NUM; i++)
		timer_shutdown_sync(&ack_m->ack_info[i].timer);''' + text[end:]
        path.write_text(text)

    # Restrict demotion to known routine messages, leaving actual errors alone.
    for name, messages in {
        'sc2355/acs.c': ['Not AP mode, exit', '%s, idx %d', '%s, noise:', '%s, time %llu', '%s, survey_cnt'],
        'sc2355/defrag.c': ['defrag clear cache', '%s:msdu len'],
        'sc2355/mm.c': ['%s: data len is %d, skb need %d'],
        'sc2355/tcp_ack.c': ['before abnormal ack'],
        'sc2355/reorder.c': ['is less than win_start', '%s: kfree skb'],
        'sc2355/tx.c': ['send %s frame by CMD_TX_DATA'],
    }.items():
        path = base / name
        text = path.read_text()
        pattern = r'\b(netdev_err|wl_err|pr_err(?:_ratelimited)?)\((?:(?!;).)*?\);'
        def quiet(match):
            if not any(message in match[0] for message in messages):
                return match[0]
            # These messages are traces, never necessary for error diagnosis.
            fn = 'netdev_dbg' if match[1] == 'netdev_err' else 'pr_debug_ratelimited'
            return fn + match[0][len(match[1]):]
        text = re.sub(pattern, quiet, text, flags=re.S)
        path.write_text(text)

    # A departed AP client can leave a large download in the bridge backlog.
    # Printing three errors per discarded packet stalls the serial console in
    # softirq context and can prevent firmware command responses being handled.
    path = base / 'sc2355/cmdevt.c'
    text = path.read_text()
    start = text.index('unsigned char sc2355_find_lut_index(')
    end = text.index('\nstatic bool sc2355_is_valid_lut(', start)
    func = text[start:end].replace('wl_err(', 'wl_debug(')
    text = text[:start] + func + text[end:]
    text = text.replace('wl_err("%s, %d, sta disconn, no data tx!",',
                        'pr_debug_ratelimited("%s, %d, sta disconn, no data tx!",')
    path.write_text(text)
    edit('common/iface.c',
         '\t\tnetdev_err(ndev, "%s drop msg due to TX Err\\n", __func__);',
         '\t\tif (net_ratelimit())\n'
         '\t\t\tnetdev_err(ndev, "%s drop msg due to TX Err\\n", __func__);')

    # h_proto is network endian. Without htons(), IPv4/IPv6 fall into the
    # vendor's extra non-IP W2W copy as well as Linux bridge forwarding.
    edit('sc2355/rx.c',
         '\t\t\tif (eth->h_proto != ETH_P_IP &&\n'
         '\t\t\t    eth->h_proto != ETH_P_IPV6) {',
         '\t\t\t/* IP multicast is forwarded by the host network stack. */\n'
         '\t\t\tif (eth->h_proto != htons(ETH_P_IP) &&\n'
         '\t\t\t    eth->h_proto != htons(ETH_P_IPV6)) {')

    # Android consumes the vendor assert event; OpenWrt needs a uevent to tell
    # netifd to reopen the radio. Emit once per reset from sleepable work, never
    # from the atomic WCN notifier or for ordinary client disconnections.
    edit('common/cfg80211.c',
         '\t\twl_info("Try to report assert a %d time \\n", hif->report_try);',
         '\t\tif (hif->report_try == 1) {\n'
         '\t\t\tchar *env[] = { "SC2355_RECOVERY=1", NULL };\n\n'
         '\t\t\tkobject_uevent_env(&wiphy_dev(priv->wiphy)->kobj,\n'
         '\t\t\t\t\t   KOBJ_CHANGE, env);\n'
         '\t\t}\n'
         '\t\twl_info("Try to report assert a %d time \\n", hif->report_try);')

    runpy.run_path(str(Path(__file__).with_name('common') / 'wifi-tx.py'))['apply'](kernel)
    runpy.run_path(str(Path(__file__).with_name('common') / 'wifi-ba.py'))['apply'](kernel)
    runpy.run_path(str(Path(__file__).with_name('common') / 'wifi-completion.py'))['apply'](kernel)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
