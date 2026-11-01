/* SPDX-License-Identifier: GPL-2.0-only */
/* Y60 user-requested DCP policy, not the factory 1.15 A policy.
 * Match the selected battery profile from both available stock firmwares;
 * leave all other batteries, USB types, thermal regions and voltages alone.
 */
static bool y60_dcp_profile(struct sprd_battery_info *info)
{
	static const struct sprd_battery_jeita_table original[] = {
		{ 0, 30, 0, 4400000 },
		{ 150, 180, 700000, 4400000 },
		{ 450, 420, 1150000, 4400000 },
		{ 570, 550, 700000, 4100000 },
	};
	struct sprd_battery_jeita_table *t = info->jeita_table[SPRD_BATTERY_JEITA_DCP];
	unsigned int i;

	if (info->charge_full_design_uah != 3050000 ||
	    info->constant_charge_voltage_max_uv != 4340000 ||
	    info->voltage_min_design_uv != 3413000 ||
	    info->cur.dcp_cur != 11500000 || info->cur.dcp_limit != 1150000 ||
	    !t || info->sprd_battery_jeita_size[SPRD_BATTERY_JEITA_DCP] != ARRAY_SIZE(original))
		return false;
	for (i = 0; i < ARRAY_SIZE(original); i++)
		if (t[i].temp != original[i].temp || t[i].recovery_temp != original[i].recovery_temp ||
		    t[i].current_ua != original[i].current_ua || t[i].term_volt != original[i].term_volt)
			return false;

	info->cur.dcp_cur = 2500000;
	info->cur.dcp_limit = 2500000;
	info->constant_charge_current_max_ua = 2500000;
	t[2].current_ua = 2500000;
	info->max_current_jeita_index[SPRD_BATTERY_JEITA_DCP] = 2;
	return true;
}
