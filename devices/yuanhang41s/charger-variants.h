/* SPDX-License-Identifier: GPL-2.0-only */
/* P720S11 stock sqc_bq2560x.ko ba6dde2a: PN dispatch 0xf4c,
 * ICHG 0x2b1c/0x43a8, ITERM 0x3074. Do not import P720S20-only PNs. */
static const char *yh41s_charger_name(unsigned int id)
{
    switch ((id >> 3) & 15) {
    case 0: return "SGM41513";
    case 1: return "SGM41513A";
    case 2: return id & 4 ? "SGM41511" : "BQ25601";
    case 9: return "SY6974";
    default: return 0;
    }
}

static unsigned int yh41s_variant_charge_code(unsigned int addr, unsigned int ma)
{
    return addr == 0x1a ? yh41s_charge_code(ma) :
        (ma > 3000 ? 3000 : ma) / 60;
}

static unsigned int yh41s_variant_charge_ma(unsigned int addr, unsigned int code)
{
    return addr == 0x1a ? yh41s_charge_ma(code) : (code & 63) * 60;
}

static unsigned int yh41s_linear_term_code(unsigned int ma)
{
    return ma <= 60 ? 0 : ma > 959 ? 15 : (ma - 60) / 60;
}
