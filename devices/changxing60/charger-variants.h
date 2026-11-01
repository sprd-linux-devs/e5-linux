/* SPDX-License-Identifier: GPL-2.0-only */
/* P720S20 stock SQC: probe 0xdf8, ICHG 0x3fd0, ITERM 0x31f4.
 * PN and address select the codec; the handset DT still owns its limits.
 */
static const char *cx60_charger_name(unsigned int id)
{
	switch ((id >> 3) & 15) {
	case 0: return "SGM41513";
	case 1: return "SGM41513A";
	case 2: return id & 4 ? "SGM41511" : "BQ25601";
	case 9: return "SY6974";
	case 12: return "SGM41516";
	case 13: return "SGM41516D";
	default: return 0;
	}
}

static unsigned int cx60_charge_code(unsigned int addr, unsigned int pn,
				    unsigned int ma)
{
	unsigned int maximum = pn == 12 || pn == 13 ? 3780 : 3000;
	if (addr == 0x1a)
		return yh41s_charge_code(ma);
	return (ma > maximum ? maximum : ma) / 60;
}

static unsigned int cx60_charge_ma(unsigned int addr, unsigned int code)
{
	return addr == 0x1a ? yh41s_charge_ma(code) : (code & 63) * 60;
}

static unsigned int cx60_term_code(unsigned int addr, unsigned int ma)
{
	unsigned int code;
	if (addr != 0x1a)
		return ma <= 60 ? 0 : ma > 959 ? 15 : (ma - 60) / 60;
	if (ma > 240) {
		if (ma <= 360) code = 5 + (ma - 240) / 60;
		else if (ma < 480) code = 7;
		else if (ma <= 1200) code = 8 + (ma - 480) / 120;
		else code = 15;
	} else {
		if (ma < 5) code = 0;
		else if (ma <= 20) code = (ma - 5) / 5;
		else if (ma <= 60) code = 3 + (ma - 20) / 10;
		else if (ma < 80) code = 7;
		else code = 8 + (ma - 80) / 20;
	}
	return code > 15 ? 15 : code;
}
