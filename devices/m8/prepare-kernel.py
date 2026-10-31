#!/usr/bin/env python3
"""Stage the M8 UMS9620 bring-up additions in a separate pinned kernel tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

BASE = '020b970e351e'
HERE = Path(__file__).resolve().parent


def prepare_charger(kernel, recipient, charger_adapter=None):
    if charger_adapter is not None:
        charger_adapter(kernel)
    else:
        runpy.run_path(str(HERE / 'charger.py'))['apply'](
            kernel, m8_revision_compat=recipient == 'm8')


def apply(kernel, *, charger_adapter=None, recipient='m8'):
    kernel = Path(kernel)
    if recipient != 'yuanhang41s' and (kernel / 'drivers/usb/typec/yh41s-usb-policy.h').exists():
        raise ValueError('41S-specific USB source cannot be reused for another board; use its clean platform source')
    head = subprocess.check_output(['git', '-c', 'safe.directory='+str(kernel.resolve()), '-C', str(kernel), 'rev-parse', 'HEAD'], text=True).strip()
    if not head.startswith(BASE):
        raise ValueError('Expected linux-lts-e5 ' + BASE)
    runpy.run_path(str(HERE.parent / 'common/display.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/usb-ncm.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/boot-optimization.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/power.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/charger-capabilities.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/emmc.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/sd-power.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/eic.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/thermal.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/sipa.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/fuel-gauge.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/wifi-sae.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/wifi-stations.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 'common/wcn-firmware.py'))['apply'](kernel)
    for name in ('drivers/power/supply/board-charge-profile.h',
                 'drivers/unisoc_platform/sprd_disp/t551m-backlight.h'):
        if (kernel / name).exists():
            raise ValueError('Use an independent clean M8 kernel tree: ' + name)
    source = HERE / 'port'
    for manifest_path in (source / 'sources.json', source / 'realme-sources.json', source / 'charger-sources.json'):
        manifest = json.loads(manifest_path.read_text())
        for name, digest in manifest['files'].items():
            data = (source / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Source integrity mismatch: ' + name)
            target = kernel / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def append(name, marker, addition):
        path = kernel / name
        text = path.read_text()
        if marker not in text:
            path.write_text(text + '\n' + addition + '\n')

    def replace(name, old, new):
        path = kernel / name
        text = path.read_text()
        if new in text:
            return
        if text.count(old) != 1:
            raise ValueError('Unexpected kernel anchor: ' + name)
        path.write_text(text.replace(old, new))

    append('drivers/clk/sprd/Makefile', 'ums9620-clk.o',
           'obj-$(CONFIG_SPRD_UMS9620_CLK) += ums9620-clk.o')
    append('drivers/clk/sprd/Kconfig', 'config SPRD_UMS9620_CLK',
           'config SPRD_UMS9620_CLK\n\tbool "Unisoc UMS9620 clocks"\n\tdepends on ARM64 && SPRD_COMMON_CLK')
    path = kernel / 'drivers/clk/sprd/ums9620-clk.c'
    text = path.read_text()
    # E5's clock core keeps legacy ibias tables and frequency tables distinct.
    text = text.replace('SPRD_PLL_HW(', 'SPRD_PLL_FTABLE_HW(')
    text = text.replace('SPRD_PLL_FW_NAME(', 'SPRD_PLL_FTABLE_FW_NAME(')
    # Vendor div.c subtracts its fixed offset; upstream div.c adds it.
    # Translate the sign as well as the extra API argument.
    text = runpy.run_path(str(HERE.parent / 'common/clock-offsets.py'))[
        'translate_legacy_offsets'](text)
    # The donor SC setters use regmap_update_bits, with offset zero here;
    # those operations are identical to this core's regular composite ops.
    text = text.replace('SPRD_SC_COMP_CLK_DATA(', 'SPRD_COMP_CLK_DATA(')
    path.write_text(text)
    # The shared 6.18 reset provider protects RMW with a lock, unlike the donor.
    runpy.run_path(str(HERE / 'clock-isolation.py'))['apply'](kernel)
    replace('drivers/clk/sprd/ums9620-clk.c',
            '\t\treset->rcdev.of_node = pdev->dev.of_node;',
            '\t\tspin_lock_init(&reset->lock);\n\t\treset->rcdev.of_node = pdev->dev.of_node;')
    append('drivers/pmdomain/Makefile', 'sprd/', 'obj-y += sprd/')
    append('drivers/pmdomain/Kconfig', 'config SPRD_UMS9620_IPA_PD',
           'config SPRD_UMS9620_IPA_PD\n\tbool "Unisoc UMS9620 IPA power domain"\n\tdepends on ARCH_SPRD && PM\n\tselect PM_GENERIC_DOMAINS\n\tselect MFD_SYSCON')
    append('drivers/usb/phy/Makefile', 'phy-sprd-ums9620-ssphy.o',
           'obj-$(CONFIG_USB_SPRD_UMS9620_SSPHY) += phy-sprd-ums9620-ssphy.o')
    append('drivers/usb/phy/Kconfig', 'config USB_SPRD_UMS9620_SSPHY',
           'config USB_SPRD_UMS9620_SSPHY\n\tbool "Unisoc UMS9620 USB PHY"\n\tdepends on ARCH_SPRD\n\tselect USB_PHY\n\tselect MFD_SYSCON')
    for name, old, new in (
        ('drivers/usb/dwc3/dwc3-of-simple.c',
         '\t{ .compatible = "sprd,sc9860-dwc3" },',
         '\t{ .compatible = "sprd,sc9860-dwc3" },\n\t{ .compatible = "sprd,qogirn6pro-dwc3" },'),
        ('drivers/usb/dwc3/core.c',
         '\t\t.compatible = "synopsys,dwc3"\n\t},',
         '\t\t.compatible = "synopsys,dwc3"\n\t},\n\t{ .compatible = "snps,sprd-dwc3" },'),
        ('drivers/usb/phy/phy-generic.c',
         '\t{ .compatible = "usb-nop-xceiv" },',
         '\t{ .compatible = "usb-nop-xceiv" },\n\t{ .compatible = "sprd,usb-dummy-phy" },'),
    ):
        replace(name, old, new)
    append('drivers/thermal/Makefile', 'sprd_thermal_r5p0.o',
           'obj-$(CONFIG_SPRD_THERMAL_R5P0) += sprd_thermal_r5p0.o')
    append('drivers/thermal/Kconfig', 'config SPRD_THERMAL_R5P0',
           'config SPRD_THERMAL_R5P0\n\ttristate "Unisoc thermal r5p0"\n\tdepends on ARCH_SPRD && HAS_IOMEM && NVMEM && THERMAL_OF')
    # The M8 vendor DT uses the family spelling used by the original driver.
    # The register layout is the same UMP9620 layout, not UMP9621's six rails.
    replace('drivers/regulator/ump9620-regulator.c',
            '\t{ .compatible = "sprd,ump9620-regulator" },',
            '\t{ .compatible = "sprd,ump9620-regulator" },\n'
            '\t{ .compatible = "sprd,ump962x-regulator" },')
    append('drivers/pinctrl/sprd/Kconfig', 'config PINCTRL_SPRD_QOGIRN6PRO',
           'config PINCTRL_SPRD_QOGIRN6PRO\n\ttristate "Unisoc QogirN6Pro pinctrl"\n\tdepends on OF && ARCH_SPRD\n\tselect PINCTRL_SPRD')
    append('drivers/pinctrl/sprd/Makefile', 'pinctrl-sprd-qogirn6pro.o',
           'obj-$(CONFIG_PINCTRL_SPRD_QOGIRN6PRO) += pinctrl-sprd-qogirn6pro.o')
    replace('drivers/pinctrl/sprd/pinctrl-sprd-qogirn6pro.c',
            'sprd_pinctrl_core_probe(pdev,', 'sprd_pinctrl_core_probe_ext(pdev,')
    replace('drivers/pinctrl/sprd/pinctrl-sprd-qogirn6pro.c',
            'PINCTRL_REG_MISC_OFFSET);', 'PINCTRL_REG_MISC_OFFSET, true);')
    replace('drivers/pwm/pwm-sprd.c',
            '\t{ .compatible = "sprd,ums9620-pwm", .data = &ums9620_pwm_data },',
            '\t{ .compatible = "sprd,ums9620-pwm", .data = &ums9620_pwm_data },\n'
            '\t{ .compatible = "sprd,qogirn6pro-pwm", .data = &ums9620_pwm_data },')
    prepare_charger(kernel, recipient, charger_adapter)
    runpy.run_path(str(HERE.parent / 't551m/cpufreq.py'))['apply'](kernel)
    # M8 uses the older three-cluster cpufreq-data-v1 binding, like UMS9620.
    for name in ('sprd-cpufreq-v2-driver.c', 'sprd-cpufreq-v2.h'):
        data = (source / 'drivers/cpufreq' / name).read_text()
        # M8 SML DVFS_INIT domain bytes verified separately; userspace checks
        # both complete firmware hashes before loading nonzero offsets.
        # See cpu-controls.md. Keep the donor's one-shot/range/SoC guards.
        if name.endswith('.c'):
            shared = (HERE.parent / 't551m/cpufreq' / name).read_text()
            start = shared.index('/* Keep userspace requests distinct')
            end = shared.index('static struct freq_attr *sprd_cpufreq_attr[]', start)
            data = data.replace('static struct freq_attr *sprd_cpufreq_attr[]',
                                shared[start:end] + 'static struct freq_attr *sprd_cpufreq_attr[]')
            data = data.replace('&scaling_voltage_domain, NULL,',
                                '&scaling_voltage_domain, &scaling_requested_min_freq,\n'
                                '\t&scaling_requested_max_freq, NULL,')
        (kernel / 'drivers/cpufreq' / name).write_text(data)
    (kernel / 'drivers/thermal/sprd_virtual_thermal.c').write_bytes(
        (HERE / 'sprd_virtual_thermal.c').read_bytes())
    append('drivers/thermal/Makefile', 'sprd_virtual_thermal.o',
           'obj-$(CONFIG_SPRD_THERMAL_R5P0) += sprd_virtual_thermal.o')
    replace('drivers/base/arch_topology.c',
            '\nDEFINE_PER_CPU(unsigned long, hw_pressure);',
            '\nEXPORT_SYMBOL_GPL(topology_set_freq_scale);\n\nDEFINE_PER_CPU(unsigned long, hw_pressure);')
    path = kernel / 'drivers/unisoc_platform/sprd_disp/sprd_drm.c'
    text = path.read_text()
    anchor = 'if (!of_device_is_available(port->parent)) {'
    replacement = ('if (!of_device_is_available(port->parent) ||\n'
                   '\t\t    (!IS_ENABLED(CONFIG_DRM_SPRD_DPU1) &&\n'
                   '\t\t     of_device_is_compatible(port->parent, "sprd,qogirn6pro-dpu1"))) {')
    if replacement not in text:
        if text.count(anchor) < 2:
            raise ValueError('Missing DRM port iteration anchors')
        path.write_text(text.replace(anchor, replacement, 2))
    runpy.run_path(str(HERE / 'usb.py'))['apply'](kernel)
    runpy.run_path(str(HERE / 'usb-role.py'))['apply'](kernel)
    # 41S supplies its own TCPM/board policy later. The legacy UMP9620 M8/K1
    # topology uses CC negotiation and the existing DWC3 automatic worker.
    if recipient != 'yuanhang41s':
        runpy.run_path(str(HERE / 'typec-policy.py'))['apply'](kernel)
    if recipient == 'm8':
        runpy.run_path(str(HERE.parent / 'common/dwc3-host-policy.py'))['apply'](kernel)
        runpy.run_path(str(HERE.parent / 'common/dwc3-host-sink.py'))['apply'](kernel)
    runpy.run_path(str(HERE / 'audio.py'))['apply'](kernel)
    runpy.run_path(str(HERE / 'gpu.py'))['apply'](kernel)
    runpy.run_path(str(HERE.parent / 't551m/wifi.py'))['apply'](kernel)
    runpy.run_path(str(HERE / 'wifi.py'))['apply'](kernel)
    # Legacy Marlin3lite DT omits newer optional GNSS dump metadata.
    # Returning here used to skip ALL GPIO/clock setup yet probe kept going.
    path = kernel / 'drivers/unisoc_platform/sprdwcn/platform/wcn_boot.c'
    text = path.read_text()
    if 'M8 legacy GNSS metadata' not in text:
        start = text.index('\tret = of_property_read_u32(np, "sprd,gnss-cp-start-addr"')
        end = text.index('\tmarlin_dev->wakeup_ap =', start)
        text = text[:start] + '''\t/* M8 legacy GNSS metadata: chip-specific defaults already exist. */
\tGNSS_CP_START_ADDR = get_gnss_cp_start_addr();
\tGNSS_FIRMWARE_MAX_SIZE = get_gnss_firmware_max_size();
\tGNSS_DUMP_PACKET_SIZE = PACKET_SIZE;
\t/* No vendor register dump layout advertised: omit that optional dump. */
\tGNSS_DUMP_REG_NUMBER = 0;
\tof_property_read_u32(np, "sprd,gnss-cp-start-addr", &GNSS_CP_START_ADDR);
\tof_property_read_u32(np, "sprd,gnss-firmware-max-size", &GNSS_FIRMWARE_MAX_SIZE);
\tof_property_read_u32(np, "sprd,gnss-dump-packet-size", &GNSS_DUMP_PACKET_SIZE);
\tof_property_read_u32(np, "sprd,gnss-dump-reg-number", &GNSS_DUMP_REG_NUMBER);

''' + text[end:]
        path.write_text(text)
    path = kernel / 'drivers/unisoc_platform/sprdwcn/platform/sysfs.c'
    text = path.read_text()
    marker = 'Default firmware debug log off'
    if marker not in text:
        anchor = '\t\tsysfs_info.armlog_status = 1;\n#endif'
        if text.count(anchor) != 1:
            raise ValueError('Unexpected WCN logging default')
        path.write_text(text.replace(anchor, anchor +
            '\n\t/* ' + marker + '; opt in through sysfs. */\n\tsysfs_info.armlog_status = 0;'))
    path = kernel / 'drivers/nvmem/sprd-efuse.c'
    text = path.read_text()
    if '"sprd,qogirn6pro-efuse"' not in text:
        replace('drivers/nvmem/sprd-efuse.c',
                'static const struct of_device_id sprd_efuse_of_match[] = {',
                'static const struct sprd_efuse_variant_data qogirn6pro_data = {\n'
                '\t.blk_nums = 51, .blk_offset = 53, .blk_double = true,\n};\n\n'
                'static const struct of_device_id sprd_efuse_of_match[] = {\n'
                '\t{ .compatible = "sprd,qogirn6pro-efuse", .data = &qogirn6pro_data },')
    # Never flash the E5 touch-controller firmware onto an M8.
    path = kernel / 'drivers/input/touchscreen/tlsc6x/tlsc6x_main.c'
    text = path.read_text().replace('\ttlsc6x_do_update_ifneed();',
                                   '\t/* Preserve the M8 factory touch firmware. */')
    path.write_text(text)
    runpy.run_path(str(HERE.parent / 'common/power-probe.py'))['apply'](kernel)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    apply(parser.parse_args().kernel)
