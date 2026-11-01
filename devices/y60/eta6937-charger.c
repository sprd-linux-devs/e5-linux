// SPDX-License-Identifier: GPL-2.0-only
/* Y60 (CP23NV3) ETA6937 port.
 * Register definitions/encodings derived from Jinfeng.Lin1's Unisoc GPLv2
 * driver at Enceka/kernel_sprd_ums9158, commit 63b8011056a5060e274fc1dcc9051c94d9a7bab8.
 * Board differences checked against both Y60 stock modules; see README.md.
 * Keep battery/JEITA policy in the original DT and charger-manager. In
 * particular, feeding the watchdog must not overwrite their voltage/current.
 */
#include <linux/alarmtimer.h>
#include <linux/extcon.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/power/charger-manager.h>
#include <linux/power/sprd_battery_info.h>
#include <linux/power_supply.h>
#include <linux/regmap.h>
#include <linux/regulator/driver.h>
#include <linux/workqueue.h>
#include "power-probe.h"

#define ETA_NCE BIT(2)
#define ETA_HIZ BIT(1)
#define ETA_OPA BIT(0)
#define ETA_BC_DISABLE BIT(0)
#define ETA_WDT_RESET BIT(7)

static const u32 eta_iin[] = {
	300000, 500000, 800000, 1200000, 1500000, 2000000, 3000000, 5000000,
};
static const u32 eta_safety_current[] = {
	550000, 750000, 950000, 1150000, 1350000, 1550000, 1750000,
	1950000, 2150000, 2350000, 2550000, 2750000, 2950000, 3050000,
};

struct eta6937 {
	struct device *dev;
	struct i2c_client *client;
	struct power_supply *psy;
	struct regmap *pmic;
	struct gpio_desc *enable_gpio;
	struct extcon_dev *edev;
	/* Control operations may synchronously cancel work. Workers only take io. */
	struct mutex control;
	struct mutex io;
	struct delayed_work watchdog;
	struct delayed_work otg_check;
	struct alarm alarm;
	u32 detect_reg, pd_reg, pd_mask;
	u32 battery_max_mv;
	bool ready, charging, online, boost, stopping, suspended;
};

static int eta_read(struct eta6937 *eta, u8 reg, u8 *value)
{
	int ret = i2c_smbus_read_byte_data(eta->client, reg);
	if (ret < 0)
		return ret;
	*value = ret;
	return 0;
}

static int eta_update(struct eta6937 *eta, u8 reg, u8 mask, u8 value)
{
	u8 old;
	int ret = eta_read(eta, reg, &old);
	if (ret)
		return ret;
	return i2c_smbus_write_byte_data(eta->client, reg,
				       (old & ~mask) | (value & mask));
}

static u8 eta_floor(const u32 *table, size_t count, u32 value)
{
	size_t i;
	for (i = 1; i < count; i++)
		if (value < table[i])
			break;
	return i - 1;
}

static u8 eta_safety_code(u32 requested)
{
	/* CC has 100 mA steps, the safety ceiling has mostly 200 mA steps.
	 * Flooring both independently caps a 2.5 A request at 2.35 A. Choose
	 * the first safety step covering the actual 2.45 A CC code instead.
	 * This ceiling does not replace CM's requested CC or thermal limits.
	 */
	u32 actual = 550000 + (clamp_val(requested, 550000, 3050000) - 550000) / 100000 * 100000;
	u8 code = eta_floor(eta_safety_current, ARRAY_SIZE(eta_safety_current), actual);

	if (eta_safety_current[code] < actual && (size_t)code + 1 < ARRAY_SIZE(eta_safety_current))
		code++;
	return code;
}

static int eta_set_input(struct eta6937 *eta, u32 ua)
{
	return eta_update(eta, 7, 7, eta_floor(eta_iin, ARRAY_SIZE(eta_iin), ua));
}

static int eta_set_current(struct eta6937 *eta, u32 ua)
{
	u8 code = (clamp_val(ua, 550000, 3050000) - 550000) / 100000;
	int ret = eta_update(eta, 4, 0x70, (code & 7) << 4);
	if (ret)
		return ret;
	return eta_update(eta, 5, 0xc0, (code & 0x18) << 3);
}

static int eta_get_current(struct eta6937 *eta, int *ua)
{
	u8 low, high, code;
	int ret = eta_read(eta, 4, &low);
	if (ret)
		return ret;
	ret = eta_read(eta, 5, &high);
	if (ret)
		return ret;
	code = ((low >> 4) & 7) | ((high >> 3) & 0x18);
	*ua = 550000 + min_t(u8, code, 25) * 100000;
	return 0;
}

static int eta_set_voltage(struct eta6937 *eta, u32 mv)
{
	/* The silicon range ends at 4440 mV; the selected battery DT owns
	 * its lower board ceiling, including requests from userspace. */
	u32 top = min(eta->battery_max_mv, 4440U);
	u8 code = (clamp_val(mv, 3500, top) - 3500) / 20;
	return eta_update(eta, 2, 0xfc, code << 2);
}

static int eta_charge(struct eta6937 *eta, bool enable)
{
	int ret;
	if (eta->enable_gpio) {
		gpiod_set_value_cansleep(eta->enable_gpio, !enable);
	} else {
		ret = regmap_update_bits(eta->pmic, eta->pd_reg, eta->pd_mask,
					 enable ? 0 : eta->pd_mask);
		if (ret)
			return ret;
	}
	/* Y60 stock adds this gate after the GPIO/PMIC operation. Unlike
	 * the old module, return a failed I2C write instead of reporting success. */
	ret = eta_update(eta, 1, ETA_NCE, enable ? 0 : ETA_NCE);
	if (!ret)
		eta->charging = enable;
	return ret;
}

static int eta_feed(struct eta6937 *eta)
{
	return eta_update(eta, 0, ETA_WDT_RESET, ETA_WDT_RESET);
}

static bool eta_watching(struct eta6937 *eta)
{
	return !eta->stopping && !eta->suspended && (eta->online || eta->boost);
}

static void eta_watchdog_work(struct work_struct *work)
{
	struct eta6937 *eta = container_of(to_delayed_work(work), struct eta6937, watchdog);
	int ret;
	mutex_lock(&eta->io);
	if (eta_watching(eta)) {
		ret = eta_feed(eta);
		if (ret)
			dev_err_ratelimited(eta->dev, "watchdog feed failed: %d\n", ret);
		schedule_delayed_work(&eta->watchdog, (ret ? 5 : 15) * HZ);
	}
	mutex_unlock(&eta->io);
}

static void eta_otg_work(struct work_struct *work)
{
	struct eta6937 *eta = container_of(to_delayed_work(work), struct eta6937, otg_check);
	int ret;
	mutex_lock(&eta->io);
	if (!eta->stopping && !eta->suspended && eta->boost) {
		/* The stock Y60 DT has no charger extcon. A NULL extcon in the
		 * vendor worker returns -EINVAL, so it does not retry OPA there.
		 * Preserve that behavior without inventing a second USB owner. */
		if (eta->edev && extcon_get_state(eta->edev, EXTCON_USB) == 0) {
			ret = eta_update(eta, 1, ETA_HIZ | ETA_OPA, ETA_OPA);
			if (ret)
				dev_err_ratelimited(eta->dev, "OTG check failed: %d\n", ret);
		}
		schedule_delayed_work(&eta->otg_check, msecs_to_jiffies(500));
	}
	mutex_unlock(&eta->io);
}

static int eta_get(struct power_supply *psy, enum power_supply_property prop,
		   union power_supply_propval *value)
{
	struct eta6937 *eta = power_supply_get_drvdata(psy);
	u8 raw;
	int ret = 0;
	mutex_lock(&eta->io);
	if (!eta->ready || eta->stopping) {
		ret = -EAGAIN;
		goto out;
	}
	switch (prop) {
	case POWER_SUPPLY_PROP_STATUS:
		value->intval = eta->charging ? POWER_SUPPLY_STATUS_CHARGING :
			POWER_SUPPLY_STATUS_NOT_CHARGING;
		break;
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT:
		value->intval = 0;
		if (eta->charging)
			ret = eta_get_current(eta, &value->intval);
		break;
	case POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT:
		value->intval = 0;
		if (eta->charging) {
			ret = eta_read(eta, 7, &raw);
			if (!ret)
				value->intval = eta_iin[raw & 7];
		}
		break;
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX:
		ret = eta_read(eta, 2, &raw);
		if (!ret)
			value->intval = (3500 + (raw >> 2) * 20) * 1000;
		break;
	case POWER_SUPPLY_PROP_HEALTH:
		/* Keep the vendor contract; no unverified ETA fault-code mapping. */
		value->intval = eta->charging ? POWER_SUPPLY_HEALTH_UNKNOWN : POWER_SUPPLY_HEALTH_GOOD;
		break;
	case POWER_SUPPLY_PROP_PRESENT:
		value->intval = eta->online;
		break;
	default:
		ret = -EINVAL;
	}
out:
	mutex_unlock(&eta->io);
	return ret;
}

static int eta_set(struct power_supply *psy, enum power_supply_property prop,
		   const union power_supply_propval *value)
{
	struct eta6937 *eta = power_supply_get_drvdata(psy);
	bool cancel = false;
	int ret = 0;
	mutex_lock(&eta->control);
	mutex_lock(&eta->io);
	if (!eta->ready || eta->stopping) {
		ret = -EAGAIN;
		goto out;
	}
	if (value->intval < 0) {
		ret = -EINVAL;
		goto out;
	}
	switch (prop) {
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT:
		ret = eta_set_current(eta, value->intval);
		break;
	case POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT:
		ret = eta_set_input(eta, value->intval);
		break;
	case POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX:
		ret = eta_set_voltage(eta, value->intval / 1000);
		break;
	case POWER_SUPPLY_PROP_STATUS:
		/* Preserve the vendor's distinct fast-charge control command range. */
		if (value->intval <= CM_FAST_CHARGE_NORMAL_CMD &&
		    !!value->intval != eta->charging)
			ret = eta_charge(eta, !!value->intval);
		break;
	case POWER_SUPPLY_PROP_PRESENT:
		eta->online = !!value->intval;
		if (eta_watching(eta))
			mod_delayed_work(system_wq, &eta->watchdog, 0);
		else
			cancel = true;
		break;
	default:
		ret = -EINVAL;
	}
out:
	mutex_unlock(&eta->io);
	/* Workers take io, never control: cancel outside io to avoid deadlock.
	 * Keep control held so a later PRESENT=1 cannot be cancelled by this call. */
	if (cancel)
		cancel_delayed_work_sync(&eta->watchdog);
	mutex_unlock(&eta->control);
	return ret;
}

static int eta_writeable(struct power_supply *psy, enum power_supply_property prop)
{
	return prop == POWER_SUPPLY_PROP_STATUS || prop == POWER_SUPPLY_PROP_PRESENT ||
		prop == POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT ||
		prop == POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT ||
		prop == POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX;
}

static enum power_supply_property eta_props[] = {
	POWER_SUPPLY_PROP_STATUS, POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,
	POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT, POWER_SUPPLY_PROP_HEALTH,
	POWER_SUPPLY_PROP_PRESENT, POWER_SUPPLY_PROP_CONSTANT_CHARGE_VOLTAGE_MAX,
};
static const struct power_supply_desc eta_desc = {
	.name = "eta6937_charger", .type = POWER_SUPPLY_TYPE_UNKNOWN,
	.properties = eta_props, .num_properties = ARRAY_SIZE(eta_props),
	.get_property = eta_get, .set_property = eta_set,
	.property_is_writeable = eta_writeable,
};

static int eta_enable_otg(struct regulator_dev *rdev)
{
	struct eta6937 *eta = rdev_get_drvdata(rdev);
	int ret;
	mutex_lock(&eta->control);
	mutex_lock(&eta->io);
	if (!eta->ready || eta->stopping) {
		ret = -EAGAIN;
		goto out;
	}
	ret = regmap_update_bits(eta->pmic, eta->detect_reg, ETA_BC_DISABLE, ETA_BC_DISABLE);
	if (ret)
		goto out;
	ret = eta_update(eta, 1, ETA_HIZ | ETA_OPA, ETA_OPA);
	if (ret) {
		regmap_update_bits(eta->pmic, eta->detect_reg, ETA_BC_DISABLE, 0);
		goto out;
	}
	eta->boost = true;
	mod_delayed_work(system_wq, &eta->watchdog, msecs_to_jiffies(50));
	mod_delayed_work(system_wq, &eta->otg_check, msecs_to_jiffies(500));
out:
	mutex_unlock(&eta->io);
	mutex_unlock(&eta->control);
	return ret;
}

static int eta_disable_otg(struct regulator_dev *rdev)
{
	struct eta6937 *eta = rdev_get_drvdata(rdev);
	bool cancel = false, cancel_wd = false;
	int ret;
	mutex_lock(&eta->control);
	mutex_lock(&eta->io);
	ret = eta_update(eta, 1, ETA_HIZ | ETA_OPA, 0);
	if (!ret) {
		eta->boost = false;
		cancel = true;
		cancel_wd = !eta->online;
		ret = regmap_update_bits(eta->pmic, eta->detect_reg, ETA_BC_DISABLE, 0);
	}
	mutex_unlock(&eta->io);
	if (cancel)
		cancel_delayed_work_sync(&eta->otg_check);
	if (cancel_wd)
		cancel_delayed_work_sync(&eta->watchdog);
	mutex_unlock(&eta->control);
	return ret;
}

static int eta_otg_enabled(struct regulator_dev *rdev)
{
	struct eta6937 *eta = rdev_get_drvdata(rdev);
	u8 value;
	int ret;
	mutex_lock(&eta->io);
	ret = eta_read(eta, 1, &value);
	mutex_unlock(&eta->io);
	return ret ? ret : !!(value & ETA_OPA);
}

static const struct regulator_ops eta_vbus_ops = {
	.enable = eta_enable_otg, .disable = eta_disable_otg, .is_enabled = eta_otg_enabled,
};
static const struct regulator_desc eta_vbus_desc = {
	.name = "otg-vbus", .of_match = "otg-vbus", .type = REGULATOR_VOLTAGE,
	.owner = THIS_MODULE, .ops = &eta_vbus_ops, .fixed_uV = 5000000, .n_voltages = 1,
};

static void eta_stop(void *data);

static int eta_hw_init(struct eta6937 *eta)
{
	struct sprd_battery_info battery = {};
	u32 unknown, dcp;
	bool invalid_current;
	int ret;
	ret = sprd_battery_get_battery_info(eta->psy, &battery);
	if (ret)
		return dev_err_probe(eta->dev, ret, "battery information unavailable\n");
	eta->battery_max_mv = battery.constant_charge_voltage_max_uv / 1000;
	unknown = battery.cur.unknown_cur;
	dcp = battery.cur.dcp_cur;
	invalid_current = battery.cur.unknown_cur <= 0 || battery.cur.dcp_cur <= 0;
	sprd_battery_put_battery_info(eta->psy, &battery);
	if (eta->battery_max_mv < 4200 || eta->battery_max_mv > 4440 || invalid_current)
		return dev_err_probe(eta->dev, -EINVAL, "invalid ETA battery description\n");
	ret = eta_update(eta, 4, BIT(7), BIT(7));
	if (ret)
		return ret;
	ret = eta_update(eta, 6, 0x0f, (eta->battery_max_mv - 4200) / 20);
	if (ret)
		return ret;
	ret = eta_update(eta, 6, 0xf0,
		eta_safety_code(dcp) << 4);
	if (ret)
		return ret;
	ret = eta_update(eta, 5, BIT(5), 0); /* release forced 550 mA mode */
	if (ret)
		return ret;
	ret = eta_update(eta, 1, 0x30, 0); /* stock weak-battery threshold */
	if (ret)
		return ret;
	ret = eta_update(eta, 4, BIT(3), 0); /* no 100 mA current offset */
	if (ret)
		return ret;
	ret = eta_set_voltage(eta, eta->battery_max_mv);
	if (ret)
		return ret;
	ret = eta_update(eta, 1, BIT(3), 0); /* stock CM controls termination */
	if (ret)
		return ret;
	ret = eta_feed(eta);
	if (ret)
		return ret;
	ret = eta_update(eta, 7, BIT(3), BIT(3)); /* select second input-limit table */
	if (ret)
		return ret;
	return eta_set_input(eta, unknown);
}

static int eta_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct power_supply_config cfg = {};
	struct regulator_config vbus_cfg = { .dev = dev, .of_node = dev->of_node };
	struct device_node *node;
	struct regulator_dev *vbus;
	struct eta6937 *eta;
	int ret;
	if (!i2c_check_functionality(client->adapter, I2C_FUNC_SMBUS_BYTE_DATA))
		return -EOPNOTSUPP;
	eta = devm_kzalloc(dev, sizeof(*eta), GFP_KERNEL);
	if (!eta)
		return -ENOMEM;
	eta->dev = dev;
	eta->client = client;
	mutex_init(&eta->control);
	mutex_init(&eta->io);
	INIT_DELAYED_WORK(&eta->watchdog, eta_watchdog_work);
	INIT_DELAYED_WORK(&eta->otg_check, eta_otg_work);
	alarm_init(&eta->alarm, ALARM_BOOTTIME, NULL);
	i2c_set_clientdata(client, eta);
	/* Y60's selected tree describes UMP962x, not the donor SC27xx PMIC. */
	node = of_find_compatible_node(NULL, NULL, "sprd,ump962x-syscon");
	if (!node)
		return dev_err_probe(dev, -ENODEV, "UMP962x syscon missing\n");
	ret = of_property_read_u32_index(node, "reg", 1, &eta->detect_reg);
	if (!ret)
		ret = of_property_read_u32_index(node, "reg", 2, &eta->pd_reg);
	if (!ret) {
		eta->pmic = sprd_charger_pmic_regmap(dev, node);
		if (IS_ERR(eta->pmic))
			ret = PTR_ERR(eta->pmic);
	}
	of_node_put(node);
	if (ret)
		return ret;
	eta->pd_mask = BIT(0); /* stock UMP962x branch */
	eta->enable_gpio = devm_gpiod_get_optional(dev, "chg-enable", GPIOD_ASIS);
	if (IS_ERR(eta->enable_gpio))
		return dev_err_probe(dev, PTR_ERR(eta->enable_gpio), "enable GPIO unavailable\n");
	if (of_find_property(dev->of_node, "extcon", NULL)) {
		eta->edev = extcon_get_edev_by_phandle(dev, 0);
		if (IS_ERR(eta->edev))
			return dev_err_probe(dev, PTR_ERR(eta->edev), "extcon unavailable\n");
	}
	/* Also covers failed probe/defer after the power supply becomes visible.
	 * Never leave work holding a freed devm allocation during unwind. */
	ret = devm_add_action_or_reset(dev, eta_stop, eta);
	if (ret)
		return ret;
	cfg.drv_data = eta;
	cfg.fwnode = dev_fwnode(dev);
	eta->psy = devm_power_supply_register(dev, &eta_desc, &cfg);
	if (IS_ERR(eta->psy))
		return dev_err_probe(dev, PTR_ERR(eta->psy), "charger registration failed\n");
	mutex_lock(&eta->io);
	ret = eta_hw_init(eta);
	if (!ret)
		ret = eta_charge(eta, false);
	if (!ret)
		eta->ready = true;
	mutex_unlock(&eta->io);
	if (ret)
		return ret;
	vbus_cfg.driver_data = eta;
	vbus = devm_regulator_register(dev, &eta_vbus_desc, &vbus_cfg);
	if (IS_ERR(vbus))
		return dev_err_probe(dev, PTR_ERR(vbus), "OTG regulator registration failed\n");
	device_init_wakeup(dev, true);
	power_supply_changed(eta->psy);
	return 0;
}

static void eta_stop(void *data)
{
	struct eta6937 *eta = data;
	int ret;
	mutex_lock(&eta->control);
	mutex_lock(&eta->io);
	eta->stopping = true;
	eta->ready = false;
	if (eta->boost) {
		ret = eta_update(eta, 1, ETA_HIZ | ETA_OPA, 0);
		if (ret)
			dev_err(eta->dev, "disable boost failed: %d\n", ret);
		ret = regmap_update_bits(eta->pmic, eta->detect_reg, ETA_BC_DISABLE, 0);
		if (ret)
			dev_err(eta->dev, "restore BC1.2 failed: %d\n", ret);
		eta->boost = false;
	}
	mutex_unlock(&eta->io);
	cancel_delayed_work_sync(&eta->watchdog);
	cancel_delayed_work_sync(&eta->otg_check);
	alarm_cancel(&eta->alarm);
	mutex_unlock(&eta->control);
}

static void eta_shutdown(struct i2c_client *client)
{
	eta_stop(i2c_get_clientdata(client));
}

static void eta_remove(struct i2c_client *client)
{
	/* The managed stop action runs after consumers are unregistered. */
	device_init_wakeup(&client->dev, false);
}

static int __maybe_unused eta_suspend(struct device *dev)
{
	struct eta6937 *eta = dev_get_drvdata(dev);
	int ret = 0;
	mutex_lock(&eta->control);
	mutex_lock(&eta->io);
	if (eta->online || eta->boost)
		ret = eta_feed(eta);
	if (!ret) {
		eta->suspended = true;
		if (eta->boost)
			alarm_start_relative(&eta->alarm, ktime_set(15, 0));
	}
	mutex_unlock(&eta->io);
	if (!ret) {
		cancel_delayed_work_sync(&eta->watchdog);
		cancel_delayed_work_sync(&eta->otg_check);
	}
	mutex_unlock(&eta->control);
	return ret;
}

static int __maybe_unused eta_resume(struct device *dev)
{
	struct eta6937 *eta = dev_get_drvdata(dev);
	int ret = 0;
	mutex_lock(&eta->control);
	alarm_cancel(&eta->alarm);
	mutex_lock(&eta->io);
	eta->suspended = false;
	if (eta_watching(eta)) {
		ret = eta_feed(eta);
		mod_delayed_work(system_wq, &eta->watchdog, (ret ? 5 : 15) * HZ);
	}
	if (eta->boost && !eta->stopping)
		mod_delayed_work(system_wq, &eta->otg_check, msecs_to_jiffies(500));
	mutex_unlock(&eta->io);
	mutex_unlock(&eta->control);
	return ret;
}

static SIMPLE_DEV_PM_OPS(eta_pm, eta_suspend, eta_resume);
static const struct of_device_id eta_of_match[] = {
	{ .compatible = "eta,eta6937_chg" }, {}
};
MODULE_DEVICE_TABLE(of, eta_of_match);
static const struct i2c_device_id eta_ids[] = { { "eta6937_chg", 0 }, {} };
MODULE_DEVICE_TABLE(i2c, eta_ids);
static struct i2c_driver eta_driver = {
	.driver = { .name = "eta6937_chg", .of_match_table = eta_of_match, .pm = &eta_pm },
	.probe = eta_probe, .remove = eta_remove, .shutdown = eta_shutdown,
	.id_table = eta_ids,
};
module_i2c_driver(eta_driver);
MODULE_DESCRIPTION("Y60 ETA6937 charger (original DT battery policy)");
MODULE_LICENSE("GPL");
