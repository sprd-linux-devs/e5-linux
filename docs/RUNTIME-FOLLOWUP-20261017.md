# Shared runtime follow-up (2026-10-17)

Source: `kanoqwq/e5-linux` `e1ab3dfba15f79058cde6a426312b71c8adf3fd2`, covering runtime changes after the `cf51e30d67a044cea5c30cb3af44f006fbc429d8` baseline of upstream PR #5. Target: the current split `sprd-linux-devs/e5-linux` tree at `bb8775e60ee5615b5820b0e79cccbf9694c35caf`.

## Scope

- Linux common: stock power/suspend sequencing, charger capability checks, retained fuel-gauge state and diagnostics, removable SD transitions without sacrificing UHS, and associated-station membership.
- Linux E5/M8/T551M: invoke those common adapters from the existing board preparation paths, retaining the board-specific display/charger/USB ordering.
- Debian common: indexed hangup behavior, ECIND SIM events, all 16 SIM/CID data port mappings, actual non-udev SIPA matcher compatibility, and persistent per-SIM RF permission.
- OpenWrt common: APN/QoS/live-port dashboard readings, read-only public APN status, per-SIM RF jobs and manual-off preservation, event-driven registration recovery, charge controls/plug-in boot, Wi-Fi cipher capability UI and association fallback.
- Infoscreen: asynchronous SIM/RF jobs, per-bank traffic, confirmed SIM absence, configured navigation ordering, minimal dark-screen DOM work and coalesced wake refresh that preserves drafts.
- Parent integration: package source fingerprints; updated ModemManager revision, patches, package assets and tests; runtime service/package registration; shared kernel hooks and stock PSCI idle/camera-domain configuration.

Desktop GUI/sidecars, installation/flashing/partition changes, misc switch APK/plugin updates, installer-only kernel switches, release artifacts and release workflows are excluded. No cancelled FM_U20 support is restored.

## Split-tree compatibility

The migration uses three-way adaptation rather than restoring the former `devices/` layout. It preserves upstream staged `radio-defaults.json`, operator localization, feature gates and screen input/lifecycle handling. The network staging hook resolves common overlay assets relative to its source location; the deployed `/opt/e5` hook can still run without assuming the host repository's directory depth.

Tests use the split paths. The profile-default fixture loads each actual board policy, the charging browser fixture includes the new fourth `power_on` argument, and the screen test checks the existing dark-screen dial-key guard. No production guard is relaxed to satisfy a fixture.

The new Debian udev helper and executable OpenWrt runtime entry points have explicit executable modes. The parent also normalizes unchanged OpenWrt board pins to their already-merged upstream commits.

## Validation

All validation uses isolated files, fake transports, or existing cached source trees. No real ADB/SSH/AT, device configuration, NV writes, network changes or releases were performed.

- 136 Python runtime tests pass in the migrated tree, covering APN, progressive publication, counters, radio restart, data switching, charge mode, lock control, AT routing, UI adapter and boot replay. Tests requiring ucode/jsonfilter use the real OpenWrt ARM64 tools in a temporary container with read-only source mounts.
- 15 netifd startup cases pass against the cached original modemmanager.sh/modemmanager.js. The production shell fragments are executed with simulated commands, including cancellation and radio/data-off preservation.
- 12 persistent RF policy tests, 8 charging backend tests, registration recovery and RPC action fixtures pass.
- Actual ucode/UCI APN suite: 97 checks. Actual jsonfilter/BusyBox APN/CID fixture: 20 checks, including same-port reconnect and absent connection age. Hostapd association, per-SIM screen band and screen SIM projection contracts pass. API template compilation succeeds with its shipped runtime dependencies mounted.
- Reconstruct the Unisoc plugin from its added source files and apply the full 20-patch sequence. Five native GLib C harnesses pass for hangup, SIM events, port selection, the actual MM string matcher and RF policy parsing. This is source-level testing, not a rebuilt ModemManager package.
- Seven native source/C harnesses pass against the cached pinned E5 kernel: suspend callbacks, power domains, SD power, charger capability contract, stock charger policy, station membership and fuel-gauge state. No board kernel rebuild was performed.
- Node control/lock/progressive-rendering checks pass. Chrome charging interactions pass on mobile/desktop, light/dark and Chinese/English/Turkish. The shared RF widget, full screen gestures/navigation/settings/appearance/wake/power-menu/dial-key cases, and delayed wake races pass with no JavaScript errors.
- Python and JavaScript syntax, conflict-marker checks, changed shell syntax and diff whitespace checks pass. Stored patch context is excluded from generic whitespace-only-line checks.

No complete kernel, APK, root filesystem or installer build was repeated; real carrier, charging, SD and suspend endurance behavior still requires device-specific validation.

## Dependencies

Merge the component PRs before the parent pin update. If a component is squash-merged, replace its submitted head pin with the resulting upstream commit. The parent stays a draft while those dependencies are pending.

| Component | PR | Submitted head |
| --- | --- | --- |
| `device/linux_device_common` | https://github.com/sprd-linux-devs/linux_device_common/pull/2 | `90d418efe480` |
| `device/linux_device_e5` | https://github.com/sprd-linux-devs/linux_device_e5/pull/2 | `51ca6713980d` |
| `device/linux_device_m8` | https://github.com/sprd-linux-devs/linux_device_m8/pull/2 | `f7fde1e5e764` |
| `device/linux_device_t551m` | https://github.com/sprd-linux-devs/linux_device_t551m/pull/2 | `f0c1049acaa5` |
| `device/debian_device_common` | https://github.com/sprd-linux-devs/debian_device_common/pull/2 | `784f547cc4ce` |
| `device/openwrt_device_common` | https://github.com/sprd-linux-devs/openwrt_device_common/pull/2 | `a2c99c8a4453` |
| `ci/infoscreen` | https://github.com/Enceka/infoscreen/pull/4 | `3dd1de38d6e7` |
