"""Opt-in DWC3 host data with external 5V power on the UMS9620 topology.

Keep board CC policy and charger tables in each profile. The caller selects
its Type-C helper ABI; the controller/PHY implementation is shared.
"""
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def apply(kernel, *, api_prefix='sprd_dualpower', api_header='sprd-dwc3-host-sink.h'):
    if not re.fullmatch(r'[a-z][a-z0-9_]*', api_prefix) or not re.fullmatch(r'[a-z0-9-]+\.h', api_header):
        raise ValueError('Invalid DWC3 host/sink helper ABI')
    def names(text):
        return text.replace('yh41s_', api_prefix + '_').replace('yh41s-host-sink.h', api_header).replace('YH41S_HOST_SINK_H', api_prefix.upper() + '_HOST_SINK_H')
    kernel = Path(kernel)
    edits = {}

    def patch(name, old, new):
        old, new = names(old), names(new)
        path = kernel / name
        source = edits.get(path, path.read_text())
        if new in source:
            return
        if source.count(old) != 1:
            raise ValueError('DWC3 host-sink anchor: ' + name + ': ' + old[:70])
        edits[path] = source.replace(old, new)

    phy = 'drivers/usb/phy/phy-sprd-ums9620-ssphy.c'
    patch(phy, '#include <linux/usb/phy.h>',
          '#include <linux/usb/phy.h>\n#include <linux/usb/yh41s-host-sink.h>')
    patch(phy, '\tbool\t\t\tis_host;', '\tbool\t\t\tis_host;\n\tbool external_host;')
    patch(phy, 'static inline void sprd_ssphy_reset_core', '''void yh41s_ssphy_external_host(struct usb_phy *x, bool external)
{
\tstruct sprd_ssphy *phy = container_of(x, struct sprd_ssphy, phy);

\tWRITE_ONCE(phy->external_host, external);
}
EXPORT_SYMBOL_GPL(yh41s_ssphy_external_host);

static inline void sprd_ssphy_reset_core''')
    patch(phy, '''\t\tsprd_usb_changed(&phy->bc1p2_info, USB_CHARGER_ABSENT);
\t\tkthread_flush_work(&phy->bc1p2_info.usb_change_kwork.work);
\t\tkthread_flush_work(&phy->bc1p2_info.bc1p2_kwork.work);
\t\tflush_work(&phy->charger_work);''', '''\t\tif (!READ_ONCE(phy->external_host)) {
\t\t\tsprd_usb_changed(&phy->bc1p2_info, USB_CHARGER_ABSENT);
\t\t\tkthread_flush_work(&phy->bc1p2_info.usb_change_kwork.work);
\t\t\tkthread_flush_work(&phy->bc1p2_info.bc1p2_kwork.work);
\t\t\tflush_work(&phy->charger_work);
\t\t}''')
    patch(phy, '''\tif (phy->is_host)
\t\treturn NOTIFY_OK;
\t/* Return D+/D-''', '''\tif (phy->is_host && !READ_ONCE(phy->external_host))
\t\treturn NOTIFY_OK;
\t/* Return D+/D-''')
    for state in ('valid', 'invalid'):
        patch(phy, '\tif (phy->is_host)\n\t\treturn 0;\n\n\t/*hsphy vbus '+state+' */',
              '\tif (phy->is_host && !READ_ONCE(phy->external_host))\n\t\treturn 0;\n\n\t/*hsphy vbus '+state+' */')

    patch('drivers/usb/phy/sprd-bc1p2.c', '''\tcase CHG_STATE_RETRY_DETECTED:
\t\tif (x->chg_type == UNKNOWN_TYPE)
\t\t\treturn;
\t\tusb_phy_notify_charger(x);''', '''\tcase CHG_STATE_RETRY_DETECTED:
\t\t/* 41S: completion also releases the external-host data path.
\t\t * Keep UNKNOWN and its zero charging allowance; do not invent SDP/PD.
\t\t */
\t\tusb_phy_notify_charger(x);''')

    glue = 'drivers/usb/dwc3/dwc3-sprd-role.h'
    patch(glue, '#include "core.h"', '#include "core.h"\n#include <linux/usb/yh41s-host-sink.h>')
    patch(glue, '#include <linux/usb/yh41s-host-sink.h>',
          '#include <linux/usb/yh41s-host-sink.h>\n#include <linux/power/sprd-bc1p2.h>')
    patch(glue, '\tstruct extcon_dev *extcon;',
          '\tstruct extcon_dev *extcon;\n\tstruct extcon_dev *power_extcon;\n\tstruct device_node *typec_node;')
    patch(glue, '\tstruct notifier_block nb;',
          '\tstruct notifier_block nb;\n\tstruct notifier_block power_nb, charger_nb;')
    patch(glue, '\tbool enabled, registered, stopped;',
          '\tbool enabled, registered, stopped;\n\tbool external_host, power_registered, charger_registered;')
    patch(glue, '''\t/* Never source into a reported sink connection. */
\treturn extcon_get_state(r->extcon, EXTCON_USB_HOST) > 0 &&
\t       extcon_get_state(r->extcon, EXTCON_USB) == 0;''', '''\tif (yh41s_typec_host_sink(r->typec_node))
\t\treturn extcon_get_state(r->extcon, EXTCON_USB) > 0 &&
\t\t       extcon_get_state(r->power_extcon, EXTCON_USB) > 0 &&
\t\t       r->phy->chg_state == USB_CHARGER_PRESENT &&
\t\t       (READ_ONCE(r->phy->flags) & CHARGER_DETECT_DONE);
\t/* Normal OTG never sources into a reported sink connection. */
\treturn extcon_get_state(r->extcon, EXTCON_USB_HOST) > 0 &&
\t       extcon_get_state(r->extcon, EXTCON_USB) == 0;''')
    patch(glue, '\tbool host;\n', '\tbool host, external, boost;\n')
    patch(glue, '''\thost = sprd_dwc3_wants_host(r);
\tif (host == r->enabled && usb_role_switch_get_role(r->sw) ==''', '''\thost = sprd_dwc3_wants_host(r);
\texternal = host && yh41s_typec_host_sink(r->typec_node);
\tboost = host && !external;
\tif (boost == r->enabled && external == r->external_host &&
\t    usb_role_switch_get_role(r->sw) ==''')
    patch(glue, '\tif (!host && r->enabled) {', '\tif (!boost && r->enabled) {')
    # A lazily acquired regulator is needed only when sourcing our own VBUS.
    # The externally powered role must not fail on an unused boost provider.
    role_source = edits.get(kernel / glue, (kernel / glue).read_text())
    if '\tif (host && !r->vbus) {' in role_source:
        patch(glue, '\tif (host && !r->vbus) {', '\tif (boost && !r->vbus) {')
    patch(glue, '\tret = otg_set_vbus(r->phy->otg, host);', '''\t/* A real, externally powered connection is never a boost target. */
\tif (boost && !r->enabled &&
\t    extcon_get_state(r->power_extcon, EXTCON_USB) > 0) {
\t\tret = -EBUSY;
\t\tgoto fail;
\t}
\tyh41s_ssphy_external_host(r->phy, external);
\tret = otg_set_vbus(r->phy->otg, host);''')
    patch(glue, '''\t\tret = regulator_enable(r->vbus);
\t\tif (ret)
\t\t\tgoto fail;
\t\tr->enabled = true;''', '''\t\tif (boost && !r->enabled) {
\t\t\t/* Recheck external VBUS after the asynchronous controller work. */
\t\t\tif (extcon_get_state(r->power_extcon, EXTCON_USB) > 0) {
\t\t\t\tret = -EBUSY;
\t\t\t\tgoto fail;
\t\t\t}
\t\t\tret = regulator_enable(r->vbus);
\t\t\tif (ret)
\t\t\t\tgoto fail;
\t\t\tr->enabled = true;
\t\t}''')
    patch(glue, '\tdev_info(r->dev, "Type-C role=%s boost=%d\\n", host ? "host" : "device", r->enabled);',
          '''\tr->external_host = external;
\tyh41s_typec_data_role(r->typec_node, host);
\tdev_info(r->dev, "Type-C role=%s boost=%d external=%d\\n",
\t\t host ? "host" : "device", r->enabled, external);''')
    patch(glue, '''\tif (host && !r->enabled) {
\t\totg_set_vbus''', '''\tif (host && !r->enabled) {
\t\tr->external_host = false;
\t\tyh41s_ssphy_external_host(r->phy, false);
\t\totg_set_vbus''')
    patch(glue, 'static void sprd_dwc3_role_stop(void *data)', '''static int yh41s_power_notify(struct notifier_block *nb,
\t\t\t     unsigned long event, void *data)
{
\tstruct sprd_dwc3_role *r = container_of(nb, struct sprd_dwc3_role, power_nb);

\tif (!READ_ONCE(r->stopped))
\t\tmod_delayed_work(system_wq, &r->work, 0);
\treturn NOTIFY_OK;
}

static int yh41s_charger_notify(struct notifier_block *nb,
\t\t\t       unsigned long event, void *data)
{
\tstruct sprd_dwc3_role *r = container_of(nb, struct sprd_dwc3_role, charger_nb);

\tif (!READ_ONCE(r->stopped))
\t\tmod_delayed_work(system_wq, &r->work, 0);
\treturn NOTIFY_OK;
}

static void sprd_dwc3_role_stop(void *data)''')
    patch(glue, '\tWRITE_ONCE(r->stopped, true);', '''\tWRITE_ONCE(r->stopped, true);
\tif (r->charger_registered)
\t\tusb_unregister_notifier(r->phy, &r->charger_nb);
\tif (r->power_registered)
\t\textcon_unregister_notifier(r->power_extcon, EXTCON_USB, &r->power_nb);''')
    patch(glue, '''\t\tof_node_put(np);
\t\tif (typec)
\t\t\tbreak;''', '''\t\tif (typec) {
\t\t\tr->typec_node = np;
\t\t\tbreak;
\t\t}
\t\tof_node_put(np);''')
    # Keep the extra node as a managed reference even if preparation fails.
    patch(glue, 'static struct sprd_dwc3_role *sprd_dwc3_role_prepare(struct device *dev)', '''static void yh41s_typec_node_put(void *node)
{
\tof_node_put(node);
}

static struct sprd_dwc3_role *sprd_dwc3_role_prepare(struct device *dev)''')
    patch(glue, '\tr->extcon = extcon_get_edev_by_phandle(dev, index);', '''\tret = devm_add_action_or_reset(dev, yh41s_typec_node_put, r->typec_node);
\tif (ret)
\t\treturn ERR_PTR(ret);
\tr->power_extcon = extcon_get_edev_by_phandle(dev, 0);
\tif (IS_ERR(r->power_extcon))
\t\treturn ERR_CAST(r->power_extcon);
\tr->extcon = extcon_get_edev_by_phandle(dev, index);''')
    patch(glue, '''\tr->registered = true;
\tmod_delayed_work''', '''\tr->registered = true;
\tr->power_nb.notifier_call = yh41s_power_notify;
\tret = extcon_register_notifier(r->power_extcon, EXTCON_USB, &r->power_nb);
\tif (ret)
\t\treturn ret;
\tr->power_registered = true;
\tr->charger_nb.notifier_call = yh41s_charger_notify;
\tret = usb_register_notifier(r->phy, &r->charger_nb);
\tif (ret)
\t\treturn ret;
\tr->charger_registered = true;
\tmod_delayed_work''')

    for path, source in edits.items():
        path.write_text(source)
    (kernel / 'include/linux/usb' / api_header).write_text(names('''/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef YH41S_HOST_SINK_H
#define YH41S_HOST_SINK_H
struct device_node;
struct usb_phy;
bool yh41s_typec_host_sink(struct device_node *node);
void yh41s_typec_data_role(struct device_node *node, bool host);
void yh41s_ssphy_external_host(struct usb_phy *phy, bool external);
#endif
'''))


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
