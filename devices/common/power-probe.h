/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef E5_POWER_PROBE_H
#define E5_POWER_PROBE_H

#include <linux/device.h>
#include <linux/err.h>
#include <linux/errno.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>

/* Retry when a described PMIC supplier has not published its regmap yet.
 * Missing/disabled DT nodes remain errors; no startup delay or dummy supply. */
static inline struct regmap *sprd_power_regmap(struct device *consumer,
					     struct device *parent)
{
	struct regmap *map;

	if (!parent)
		return ERR_PTR(dev_err_probe(consumer, -ENODEV,
					    "PMIC parent missing\n"));
	map = dev_get_regmap(parent, NULL);
	if (!map)
		return ERR_PTR(dev_err_probe(consumer, -EPROBE_DEFER,
					    "PMIC regmap not ready\n"));
	return map;
}

static inline struct regmap *sprd_charger_pmic_regmap(struct device *consumer,
							   struct device_node *node)
{
	struct platform_device *supplier;
	struct regmap *map;

	if (!node || !of_device_is_available(node))
		return ERR_PTR(dev_err_probe(consumer, -ENODEV,
					    "PMIC syscon node unavailable\n"));
	supplier = of_find_device_by_node(node);
	if (!supplier)
		return ERR_PTR(dev_err_probe(consumer, -EPROBE_DEFER,
					    "PMIC syscon not ready\n"));
	map = sprd_power_regmap(consumer, supplier->dev.parent);
	platform_device_put(supplier);
	return map;
}

#endif
