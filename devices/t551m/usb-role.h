/* SPDX-License-Identifier: GPL-2.0-only */
/* Probe the sink role for 500 ms before offering OTG power. */
enum { ROLE_IDLE, ROLE_TRY_SINK, ROLE_ALLOW_SOURCE };

static int sc27xx_typec_hw_mode(struct sc27xx_typec *sc, u32 mode)
{
	return regmap_update_bits(sc->regmap, sc->base + sc->var_data->mode,
				  SC27XX_MODE_MASK, mode);
}

/* An attached CC state can outlive a MODE write. As in the vendor Rp/Rd
 * restart and explicit policy switching, open CC before changing policy,
 * then return ownership to hardware. Only a deliberate automatic probe
 * transition uses this; ordinary detach/steady charging never pulses CC.
 */
static int sc27xx_typec_reprobe_mode(struct sc27xx_typec *sc, u32 mode)
{
	u32 mask = SC27XX_CC1_SW_SWITCH_MASK | SC27XX_CC2_SW_SWITCH_MASK;
	u32 open = SC27XX_CC1_SW_SWITCH(SC27XX_TYPEC_NC) |
		   SC27XX_CC2_SW_SWITCH(SC27XX_TYPEC_NC);
	int ret, restore;

	ret = regmap_update_bits(sc->regmap, sc->base + SC27XX_SW_CFG, mask, open);
	if (ret)
		return ret;
	ret = sc27xx_typec_hw_mode(sc, mode);
	if (!ret)
		msleep(20);
	restore = regmap_update_bits(sc->regmap, sc->base + SC27XX_SW_CFG, mask, 0);
	return ret ? ret : restore;
}

static void sc27xx_typec_role_finish(struct sc27xx_typec *sc)
{
	cancel_delayed_work(&sc->role_work);
	sc->role_phase = ROLE_IDLE;
}

static void sc27xx_typec_role_detach(struct sc27xx_typec *sc)
{
	sc27xx_typec_role_finish(sc);
	if (sc->mode == TYPEC_PORT_DRP && !IS_ENABLED(CONFIG_SPRD_TYPEC_TCPM))
		sc27xx_typec_hw_mode(sc, SC27XX_MODE_DRP);
}

static bool sc27xx_typec_prefer_sink(struct sc27xx_typec *sc)
{
	int ret;

	/* Ignore an attachment sampled before a userspace policy transition. */
	if ((sc->mode == TYPEC_PORT_UFP && sc->state == SC27XX_ATTACHED_SRC) ||
	    (sc->mode == TYPEC_PORT_DFP && (sc->state == SC27XX_ATTACHED_SNK ||
					 sc->state == SC27XX_DEBUG_CABLE)))
		return true;
	if (sc->mode != TYPEC_PORT_DRP || IS_ENABLED(CONFIG_SPRD_TYPEC_TCPM) ||
	    sc->state != SC27XX_ATTACHED_SRC || sc->partner_connected)
		return false;
	if (sc->role_phase == ROLE_ALLOW_SOURCE)
		return false;
	if (sc->role_phase == ROLE_TRY_SINK)
		return true;
	sc->role_phase = ROLE_TRY_SINK;
	ret = sc27xx_typec_reprobe_mode(sc, SC27XX_MODE_SNK);
	if (ret) {
		sc->role_phase = ROLE_IDLE;
		dev_warn(sc->dev, "cannot start sink probe: %d\n", ret);
		return true;
	}
	mod_delayed_work(system_wq, &sc->role_work, msecs_to_jiffies(500));
	dev_info(sc->dev, "trying sink before OTG host\n");
	return true;
}

static void sc27xx_typec_role_work(struct work_struct *work)
{
	struct sc27xx_typec *sc = container_of(to_delayed_work(work),
					struct sc27xx_typec, role_work);
	u32 state;
	int ret;

	mutex_lock(&sc->role_lock);
	if (sc->role_phase == ROLE_IDLE || sc->partner_connected)
		goto out;
	ret = regmap_read(sc->regmap, sc->base + SC27XX_STATUS, &state);
	if (ret) {
		sc->role_phase = ROLE_IDLE;
		sc27xx_typec_reprobe_mode(sc, SC27XX_MODE_DRP);
		goto out;
	}
	state &= sc->var_data->state_mask;
	if (state == SC27XX_ATTACHED_SNK || state == SC27XX_DEBUG_CABLE) {
		sc->state = state;
		sc->role_phase = ROLE_IDLE;
		sc27xx_typec_connect(sc, state);
		sc27xx_typec_connect_state = sc->partner_connected;
	} else if (sc->role_phase == ROLE_TRY_SINK) {
		sc->role_phase = ROLE_ALLOW_SOURCE;
		ret = sc27xx_typec_reprobe_mode(sc, SC27XX_MODE_DRP);
		if (ret)
			sc->role_phase = ROLE_IDLE;
		else
			/* Expire abandoned probes when an accessory was removed. */
			mod_delayed_work(system_wq, &sc->role_work, msecs_to_jiffies(1500));
	} else {
		/* Recover a source attachment even if its IRQ was coalesced. */
		if (state == SC27XX_ATTACHED_SRC) {
			sc->state = state;
			sc27xx_typec_connect(sc, state);
			sc27xx_typec_connect_state = sc->partner_connected;
		}
		sc->role_phase = ROLE_IDLE;
	}
out:
	mutex_unlock(&sc->role_lock);
}

static void sc27xx_typec_role_cleanup(void *data)
{
	struct sc27xx_typec *sc = data;
	if (sc->role_irq_requested) {
		disable_irq(sc->irq);
		sc->role_irq_requested = false;
	}
	cancel_delayed_work_sync(&sc->role_work);
}
