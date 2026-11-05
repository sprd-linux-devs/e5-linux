/* SPDX-License-Identifier: GPL-2.0-only */
/* T551M 551MCM08 stock bq2560x-charger.ko: REG0B revision-specific
 * charge-current encodings. Both verified variants use I2C address 0x6b.
 */
#ifndef T551M_CHARGER_VARIANTS_H
#define T551M_CHARGER_VARIANTS_H

static bool t551m_charger_supported(unsigned int addr, unsigned int id)
{
	return addr == 0x6b && (id == 0x11 || id == 0x12);
}

static u8 t551m_charge_code(u8 id, u32 ma)
{
	if (id == 0x11) {
		ma = min(ma, 2875U);
		if (ma < 59)
			return 0;
		if (ma <= 815)
			return (ma - 59) / 63 + 1;
		return (ma * 2 - 1610) / 115 + 14;
	}
	if (id == 0x12) {
		ma = min(ma, 3047U);
		return ma <= 1170 ? ma / 90 : (ma - 805) / 57 + 14;
	}
	return 0; /* Probe rejects unknown silicon before any register writes. */
}

static u32 t551m_charge_ma(u8 id, u8 code)
{
	code &= 0x3f;
	if (id != 0x11 && id != 0x12)
		return 0;
	if (code > 13)
		return (code - 14) * 115 / 2 + 805;
	return id == 0x11 ? (code ? code * 63 - 4 : 0) : code * 90;
}

#endif
