# CPU frequency support

> 2026-11-01 现行规则：下列原厂哈希继续作为取证记录及快速白名单；
> 未命中时使用共享只读算法匹配，不再只按版本/签名判定，也不要求两槽镜像相同。
> 本文保留此前适配和实测时的历史检查条件。现行实现及边界见
> [公共调压说明](../../../docs/CPU-CONTROL.zh-CN.md)。

The four GPL source files originate from
[`Enceka/kernel_sprd_ums9158`, commit `63b8011056a5060e274fc1dcc9051c94d9a7bab8`](https://github.com/Enceka/kernel_sprd_ums9158/tree/63b8011056a5060e274fc1dcc9051c94d9a7bab8):

- `drivers/cpufreq/sprd-cpufreq-v2-driver.c`
- `drivers/cpufreq/sprd-cpufreq-v2.h`
- `drivers/firmware/sprd_sip_svc.c`
- `include/linux/sprd_sip_svc.h`

The MU300 port was reviewed as the integration reference. Its older CPU driver
uses `cpufreq-data-v1` and topology cluster IDs, whereas this device's factory DT
uses `sprd,freq-domain`, three firmware domain IDs and separate named bin cells.
This port retains the matching newer vendor DT/firmware ABI, factory binning,
firmware voltage tables and temperature-dependent OPP updates.

Changes for Linux 6.18:

- native policy exit/platform remove signatures and DT domain CPU masks;
- let the CPUFreq core create its frequency-list attribute (no duplicate);
- accept the factory's short efuse version string, padded into the SIP word;
- validated domain indices, domain count and bounded firmware table responses;
- no 60-second boost that silently ignores governor/thermal requests;
- cancel temperature work before taking its mutex, and serialize table changes
  with the policy lock using trylock to avoid offline/suspend deadlocks;
- free all cached temperature tables on policy exit;
- resume does not invoke suspend again;
- `scaling_voltage_table` exposes firmware pairs as `kHz uV` (read-only);
- `scaling_requested_min_freq` / `scaling_requested_max_freq` expose the
  userspace QoS requests in kHz, clamped to hardware bounds. These read-only
  attributes keep the saved user limits separate from effective thermal caps.

The SIP DVFS interface has no setter for an arbitrary frequency/voltage pair.
The verified UMS9621 secure monitor does support signed per-domain offsets in
`DVFS_INIT` bits 8..31. The module's read-only `voltage_offset_uv` boot parameter
uses this native path. Firmware updates CPU and SRAM selector tables together,
including temperature-specific tables and transition delays. Runtime reinitialization
would mutate tables repeatedly, so module unloading and sysfs rebinding are disabled.
The backend loads the module once, at S13, before the charger-only boot gate.

Verified SML images (both slots must match; 1 MiB partition hashes unless noted):

- T551M: `c3ab5b763cbcfd09d1a4e8f598ed703c739a2081682f8278276dba4581cd1c44`.
- E5: `51ab807ce7c13795e134031b81f6f6b904da38a771c166ce4e279f93dac72890`.
- LYM-10K-V32 uses its complete 157224-byte signed DHTB image, with its own
  length-bound identity check instead of hashing unused partition padding.
  See [the LYM CPU/SMC evidence](../../lym10k/CPU-POWER.zh-CN.md).
- T512N/PB8: `b0beb84a18b4d823bf62ec1ea36a46b960b5ea0a54433d449d8a007968879075`.
  Its own decoder, paired CPU/SRAM tables and identical selector arithmetic
  are documented in [the T512N CPU/power notes](../../t512n/CPU-POWER.zh-CN.md).

The userspace gate checks the SoC and both firmware images before accepting any
nonzero offset. Unknown firmware falls back to factory voltage. Nothing writes
SML, NV, DTBO or boot partitions when a user saves voltage settings.

Firmware analysis: `sprd_dvfs_init` at `0xb0007328` calls the flag decoder at
`0xb0006270`. Each upper byte carries a sign bit and a 7-bit mV magnitude.
`0xb0004090` adjusts each selector by `ceil(mV * 1000 / 3125)`. Linux accepts
exact 3125 uV multiples within -50000..25000 uV and encodes `floor(abs(uV)/1000)`
to invert that rounding. The low byte remains reserved for existing debug flags.
The DCDC `margin_set` value is **transition timing**, not a voltage offset.
There is no added overclock state or direct PMIC write.

The E5 equivalents are `0xb0007300` (DVFS init), `0xb0006248` (flag decoder)
and `0xb0004068` (selector adjustment). The selector function is byte-identical;
the decoder only relocates its domain state from `0xb0024df0` to `0xb0028068`.
The three CPU/SRAM table paths retain paired selector adjustment and temperature
table tracking. Comparing the DVFS code from T551M `0xb0004090..0xb000757b`
with E5 at -0x28 finds only relocated address loads and branch targets.
E5 hardware verification at -3125 uV confirms all 31 OPPs and five maximum-
frequency PMIC samples for each domain. The domain-to-rail map is unchanged:
0/1/2 -> vddcpu1/2/0. SRAM readback remains subject to firmware floors.
The versioned capability cache refreshes a previous unsupported result on update;
unknown or mixed-slot firmware stays disabled.

`scaling_voltage_offset` and `scaling_voltage_domain` report the boot request
and firmware domain. The existing voltage table reports the resulting firmware
values, separately verified against PMIC regulator readback on hardware.
See [the user and recovery documentation](../../../docs/CPU-CONTROL.zh-CN.md).

`../cpufreq.py` installs these files into the pinned kernel checkout. The build
script merges `config`; the default governor is `schedutil`. Users can choose
another built-in governor or limit each domain to supported frequencies.
