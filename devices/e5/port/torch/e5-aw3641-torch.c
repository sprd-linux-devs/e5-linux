// SPDX-License-Identifier: GPL-2.0-only
/*
 * RongYue E5 AW3641 torch, exposed through the standard LED class.
 * GPIO names and sequencing follow the device's stock flash_ic_aw3641.ko.
 * See SOURCES.json for the stock and UNISOC GPL reference provenance.
 */
#include <linux/gpio/consumer.h>
#include <linux/leds.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/property.h>

struct e5_aw3641 {
	struct gpio_desc *enable;
	struct gpio_desc *mode;
	struct led_classdev led;
	struct mutex lock;
};

static int e5_aw3641_brightness(struct led_classdev *led,
				enum led_brightness brightness)
{
	struct e5_aw3641 *torch = container_of(led, struct e5_aw3641, led);

	mutex_lock(&torch->lock);
	if (brightness != LED_OFF) {
		/* Stock torch mode: MODE low, then EN high. No flash pulses. */
		gpiod_set_value_cansleep(torch->mode, 0);
		gpiod_set_value_cansleep(torch->enable, 1);
	} else {
		/* Disable the output before returning MODE to its idle level. */
		gpiod_set_value_cansleep(torch->enable, 0);
		gpiod_set_value_cansleep(torch->mode, 0);
	}
	mutex_unlock(&torch->lock);
	return 0;
}

static void e5_aw3641_off(void *data)
{
	struct e5_aw3641 *torch = data;

	e5_aw3641_brightness(&torch->led, LED_OFF);
}

static int e5_aw3641_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct e5_aw3641 *torch;
	u32 chip, index = 1;
	int ret;

	ret = device_property_read_u32(dev, "flash-ic", &chip);
	if (ret || chip != 3641)
		return dev_err_probe(dev, -ENODEV, "Not the E5 AW3641 binding\n");
	device_property_read_u32(dev, "torch-led-idx", &index);
	if (index != 1)
		return dev_err_probe(dev, -ENODEV, "Unsupported torch output\n");

	torch = devm_kzalloc(dev, sizeof(*torch), GFP_KERNEL);
	if (!torch)
		return -ENOMEM;
	mutex_init(&torch->lock);
	/* Acquire MODE first so enabling the chip cannot select flash mode. */
	torch->mode = devm_gpiod_get(dev, "flash-torch-en", GPIOD_OUT_LOW);
	if (IS_ERR(torch->mode))
		return dev_err_probe(dev, PTR_ERR(torch->mode), "Cannot acquire torch MODE\n");
	torch->enable = devm_gpiod_get(dev, "flash-en", GPIOD_OUT_LOW);
	if (IS_ERR(torch->enable))
		return dev_err_probe(dev, PTR_ERR(torch->enable), "Cannot acquire torch EN\n");
	torch->led.name = "e5:white:torch";
	torch->led.max_brightness = 1;
	torch->led.brightness_set_blocking = e5_aw3641_brightness;
	platform_set_drvdata(pdev, torch);
	ret = devm_add_action_or_reset(dev, e5_aw3641_off, torch);
	if (ret)
		return ret;
	return devm_led_classdev_register(dev, &torch->led);
}

static void e5_aw3641_shutdown(struct platform_device *pdev)
{
	e5_aw3641_off(platform_get_drvdata(pdev));
}

static const struct of_device_id e5_aw3641_match[] = {
	{ .compatible = "sprd,flash-aw3641" },
	{ }
};
MODULE_DEVICE_TABLE(of, e5_aw3641_match);

static struct platform_driver e5_aw3641_driver = {
	.probe = e5_aw3641_probe,
	.shutdown = e5_aw3641_shutdown,
	.driver = {
		.name = "e5-aw3641-torch",
		.of_match_table = e5_aw3641_match,
	},
};
module_platform_driver(e5_aw3641_driver);

MODULE_DESCRIPTION("RongYue E5 AW3641 GPIO torch");
MODULE_LICENSE("GPL");
