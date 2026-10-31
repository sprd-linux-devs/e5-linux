/* SPDX-License-Identifier: GPL-2.0-only */
/* User-requested P720S20 DCP policy. This is not the stock SQC default.
 * Change only the verified battery's normal-temperature CC and input budget;
 * preserve cold/hot derating, hysteresis, stop regions and every voltage.
 */
static bool changxing60_dcp_profile(struct sprd_battery_info *info)
{
	static const struct sprd_battery_jeita_table original[] = {
		{ 0, 30, 0, 4400000 },
		{ 100, 130, 600000, 4400000 },
		{ 150, 180, 600000, 4400000 },
		{ 450, 420, 1000000, 4400000 },
		{ 550, 520, 900000, 4100000 },
	};
	struct sprd_battery_jeita_table *t = info->jeita_table[SPRD_BATTERY_JEITA_DCP];
	unsigned int i;

	if (info->charge_full_design_uah != 3000000 ||
	    info->constant_charge_voltage_max_uv != 4400000 ||
	    info->voltage_min_design_uv != 3450000 ||
	    info->constant_charge_current_max_ua != 1000000 ||
	    info->cur.dcp_cur != 1000000 || info->cur.dcp_limit != 1000000 ||
	    !t || info->sprd_battery_jeita_size[SPRD_BATTERY_JEITA_DCP] != ARRAY_SIZE(original))
		return false;
	for (i = 0; i < ARRAY_SIZE(original); i++)
		if (t[i].temp != original[i].temp || t[i].recovery_temp != original[i].recovery_temp ||
		    t[i].current_ua != original[i].current_ua || t[i].term_volt != original[i].term_volt)
			return false;

	info->cur.dcp_cur = 2500000;
	info->cur.dcp_limit = 2500000;
	info->constant_charge_current_max_ua = 2500000;
	t[3].current_ua = 2500000;
	info->max_current_jeita_index[SPRD_BATTERY_JEITA_DCP] = 3;
	return true;
}
