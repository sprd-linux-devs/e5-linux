/* P720S11: stock PN/address selection before any charger register writes.
 * Keep the DT client intact; reserve the alternate address through I2C core.
 */
static int yh41s_read_id(struct bq2560x_charger_info *info, u8 *id)
{
    int ret, attempt;
    for (attempt = 0; attempt < 6; attempt++) {
        ret = bq2560x_read(info, BQ2560X_REG_B, id);
        if (ret != -ENXIO && ret != -EREMOTEIO && ret != -EIO)
            return ret;
        if (attempt < 5)
            usleep_range(5000, 5500);
    }
    return ret;
}

static int yh41s_identify(struct bq2560x_charger_info *info)
{
    struct i2c_client *original = info->client, *alternate;
    const char *name;
    u8 id = 0;
    int ret;

    if (original->addr != 0x6b && original->addr != 0x1a)
        return dev_err_probe(info->dev, -ENODEV, "unsupported P720S11 charger address\n");
    ret = yh41s_read_id(info, &id);
    if (original->addr == 0x6b &&
        (ret == -ENXIO || ret == -EREMOTEIO || ret == -EIO)) {
        alternate = devm_i2c_new_dummy_device(info->dev, original->adapter, 0x1a);
        if (IS_ERR(alternate))
            return dev_err_probe(info->dev, PTR_ERR(alternate), "P720S11 charger 0x1a unavailable\n");
        info->client = alternate;
        ret = yh41s_read_id(info, &id);
    }
    name = ret < 0 ? NULL : yh41s_charger_name(id);
    if (!name) {
        info->client = original;
        return dev_err_probe(info->dev, ret < 0 ? ret : -ENODEV,
                             "P720S11 charger identification failed: %#x\n", id);
    }
    strscpy(info->charge_ic_vendor_name, name, sizeof(info->charge_ic_vendor_name));
    dev_info(info->dev, "P720S11 charger %s at %#x, REG0B=%#x\n", name, info->client->addr, id);
    return 0;
}
