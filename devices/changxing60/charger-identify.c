/* Included after bq2560x_read(). Identify before any register writes.
 * SQC retries a failed ID read twice at 5 ms, then tries its 0x1a alias.
 * Reserve that address with an I2C client; never steal another driver's IC.
 */
static int cx60_read_id(struct bq2560x_charger_info *info, u8 *id)
{
	int ret, attempt;
	for (attempt = 0; attempt < 3; attempt++) {
		ret = bq2560x_read(info, BQ2560X_REG_B, id);
		if (ret != -ENXIO && ret != -EREMOTEIO && ret != -EIO)
			return ret;
		if (attempt < 2)
			usleep_range(5000, 5500);
	}
	return ret;
}

static int cx60_identify(struct bq2560x_charger_info *info)
{
	struct i2c_client *original = info->client, *alternate;
	const char *name;
	u8 id = 0, extra;
	int ret;

	if (original->addr != 0x6b && original->addr != 0x1a)
		return dev_err_probe(info->dev, -ENODEV, "unsupported P720S20 charger address\n");
	ret = cx60_read_id(info, &id);
	if (original->addr == 0x6b &&
	    (ret == -ENXIO || ret == -EREMOTEIO || ret == -EIO)) {
		alternate = devm_i2c_new_dummy_device(info->dev, original->adapter, 0x1a);
		if (IS_ERR(alternate))
			return dev_err_probe(info->dev, PTR_ERR(alternate), "P720S20 charger 0x1a unavailable\n");
		info->client = alternate;
		ret = cx60_read_id(info, &id);
	}
	name = ret < 0 ? NULL : cx60_charger_name(id);
	if (!name) {
		info->client = original;
		return dev_err_probe(info->dev, ret < 0 ? ret : -ENODEV,
				     "P720S20 charger identification failed: %#x\n", id);
	}
	info->stock_pn = (id >> 3) & 15;
	info->chip_type = info->stock_pn == 12 || info->stock_pn == 13 ? CHIP_SGM41542 : CHIP_SGM41511;
	/* Stock distinguishes the UPM clone with a read-only extra ID. */
	if (info->stock_pn == 2 && (id & 4) &&
	    !bq2560x_read(info, 0xa7, &extra) && extra == 5)
		name = "UPM6910H";
	strscpy(info->charge_ic_vendor_name, name, sizeof(info->charge_ic_vendor_name));
	dev_info(info->dev, "P720S20 charger %s at %#x, REG0B=%#x\n", name, info->client->addr, id);
	return 0;
}
