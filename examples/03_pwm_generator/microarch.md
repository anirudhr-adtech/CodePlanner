# Micro-architecture: `pwm_ctrl`

## 1. Overview

`pwm_ctrl` is a register-programmable PWM controller with `NUM_CH` independent channels.
A shared prescaler produces a tick enable. Each channel has its own counter, comparator,
direction flag (for center-aligned mode) and a double-buffered set of PERIOD/DUTY/CENTER
values.

Key features:
- Software-visible "preload" registers plus internal "active" (shadow) registers, copied at the period boundary, so a period is never truncated or produced as a runt.
- Edge-aligned mode: counter 0 → PERIOD−1, output active while `cnt < DUTY`.
- Center-aligned mode: counter counts up 0 → PERIOD−1 then down PERIOD−1 → 0 (2×PERIOD ticks). Output active while `cnt >= PERIOD − DUTY`, which centres the pulse at the top of the count.
- Registered, polarity-adjusted outputs (glitch-free).
- Simple register bus with 1-cycle read latency.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | System clock (100 MHz). |
| `rst_n` | in | 1 | Active-low reset, async assert, sync de-assert. |
| **Register bus** | | | |
| `reg_wr` | in | 1 | Write strobe (single cycle). |
| `reg_rd` | in | 1 | Read strobe (single cycle). |
| `reg_addr` | in | 8 | Byte address; bits [1:0] ignored. |
| `reg_wdata` | in | 32 | Write data. |
| `reg_rdata` | out | 32 | Read data, valid the cycle after `reg_rd`. |
| **PWM** | | | |
| `pwm_out` | out | `NUM_CH` | Registered PWM outputs, polarity applied. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `NUM_CH` | 8 | 1–8 | Number of channels (fits the 8-bit address map). |
| `CNT_W` | 16 | 2–16 | Counter, PERIOD and DUTY width. |
| `PRESC_W` | 16 | 1–16 | Prescaler width. |

Channel `n` decodes at `0x10 + 0x10*n`. An elaboration check rejects `NUM_CH > 8`.

## 4. Block Diagram

```
                +-----------------------------+
 reg_* -------->|  reg_if: decode, preload    |---- reg_rdata
                |  regs, read mux (1-cyc)     |
                +-----------------------------+
                   | gen, presc    | per-ch cfg/period/duty (preload)
                   v               v
            +-------------+   +-------------------------------------------+
            | prescaler   |   |  pwm_chan [0..NUM_CH-1]                   |
            | presc_cnt_q |-->|  shadow: per_act_q, duty_act_q, ctr_act_q |
            +-------------+   |  cnt_q, dir_q                             |
                 tick         |  compare -> out_q (POL applied)           |---> pwm_out[n]
                              +-------------------------------------------+
                                     | cnt_q (to CHn_COUNT readback)
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_reg` | `pwm_reg_if` | Address decode, preload registers, read mux. |
| `u_presc` | `pwm_presc` | Prescaler; 1-cycle `tick` every PRESC+1 clocks. |
| `g_ch[n].u_ch` | `pwm_chan` | One channel: shadow registers, counter, comparator, output flop. |

## 5. Datapath

**Global registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `gen_q` | 1 | 0 | CTRL.GEN. |
| `presc_q` | `PRESC_W` | 0 | CTRL.PRESC. |
| `presc_cnt_q` | `PRESC_W` | 0 | Prescaler counter. |
| `rdata_q` | 32 | 0 | Registered read data. |

**Per-channel preload registers (software-visible)**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `en_q[n]` | 1 | 0 | CHn_CFG.EN (takes effect immediately). |
| `pol_q[n]` | 1 | 0 | CHn_CFG.POL (takes effect immediately; see §11). |
| `ctr_pre_q[n]` | 1 | 0 | CHn_CFG.CENTER preload. |
| `per_pre_q[n]` | `CNT_W` | 0 | CHn_PERIOD preload. |
| `duty_pre_q[n]` | `CNT_W` | 0 | CHn_DUTY preload. |

**Per-channel working registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `per_act_q` | `CNT_W` | 0 | Active PERIOD. |
| `duty_act_q` | `CNT_W` | 0 | Active DUTY. |
| `ctr_act_q` | 1 | 0 | Active CENTER mode. |
| `cnt_q` | `CNT_W` | 0 | Channel counter. |
| `dir_q` | 1 | 0 | Center mode: 0 = counting up, 1 = counting down. |
| `out_q` | 1 | 0 | Registered output (after polarity). |

**Prescaler**

```verilog
tick        = gen_q && (presc_cnt_q == presc_q);
presc_cnt_n = (!gen_q || tick || ctrl_wr) ? '0 : presc_cnt_q + 1'b1;   // ctrl_wr: write to CTRL
```

**Comparator (per channel, combinational from active registers)**

```verilog
wire full_on  = (duty_act_q >= per_act_q);
wire off      = (duty_act_q == 0) || (per_act_q == 0);
wire cmp_edge = (cnt_q <  duty_act_q);
wire cmp_ctr  = (cnt_q >= per_act_q - duty_act_q);  // only used when !full_on, so no underflow
wire active   = run && !off && (full_on || (ctr_act_q ? cmp_ctr : cmp_edge));
out_n = active ^ pol_q;                             // inactive level when !run is pol_q
```

`off` has priority over `full_on`, so PERIOD=0 or DUTY=0 always gives an inactive output.

## 6. Control Logic

**Channel run condition:** `run = gen_q && en_q[n]`.

**Counter / direction FSM (per channel).** It advances only on `tick`. States are encoded
by `{ctr_act_q, dir_q}`.

| State | Encoding `{ctr,dir}` | Condition (on `tick`) | `cnt_n` | Next state | `boundary` |
|-------|----------------------|-----------------------|---------|------------|------------|
| EDGE | 0x | `cnt_q == per_act_q-1` or `per_act_q == 0` | 0 | EDGE | 1 |
| EDGE | 0x | otherwise | `cnt_q+1` | EDGE | 0 |
| C_UP | 10 | `cnt_q == per_act_q-1` | `cnt_q` (hold) | C_DOWN | 0 |
| C_UP | 10 | otherwise | `cnt_q+1` | C_UP | 0 |
| C_DOWN | 11 | `cnt_q == 0` | 0 (hold) | C_UP | 1 |
| C_DOWN | 11 | otherwise | `cnt_q-1` | C_DOWN | 0 |

Holding at each turning point gives a symmetric `2×PERIOD`-tick sequence, e.g. PERIOD=3:
`0 1 2 2 1 0 | 0 1 2 2 1 0`.

**Shadow load**

| Event | Action |
|-------|--------|
| `tick && boundary && run` | `per_act_q ← per_pre_q`, `duty_act_q ← duty_pre_q`, `ctr_act_q ← ctr_pre_q`, `dir_q ← 0` |
| `!run` | Load the shadows continuously from the preloads, `cnt_q ← 0`, `dir_q ← 0`, so enabling starts a clean period with current values. |

**Register interface:** a write to an offset updates its preload register in the next cycle.
On a read, `rdata_q` is loaded from the read mux (unmapped or reserved bits read as 0;
COUNT returns `cnt_q`).

## 7. Timing & Pipeline

- **Output latency:** 1 cycle (`out_q`) from the counter value to the pin.
- **Register write → effect:** CFG.EN/POL take effect 1 cycle after the write. PERIOD/DUTY/CENTER take effect at the first boundary after the write (worst case one full period plus 1 cycle).
- **PWM frequency:** edge-aligned `f_clk / ((PRESC+1)·PERIOD)`; center-aligned `f_clk / ((PRESC+1)·2·PERIOD)`.
- **Critical path:** `per_act_q − duty_act_q` subtract → compare → XOR → `out_q`. A 16-bit path, easily met at 100 MHz. The subtraction can be pre-registered at shadow load if needed.

Edge-aligned example (`PRESC=0`, so `tick` every cycle; PERIOD=4, DUTY=1; software writes
DUTY=3 in cycle 2):

| Cycle | cnt_q | duty_act_q | duty_pre_q | boundary | active | out_q (next) | Note |
|-------|-------|------------|------------|----------|--------|--------------|------|
| 0 | 0 | 1 | 1 | 0 | 1 | 1 | |
| 1 | 1 | 1 | 1 | 0 | 0 | 0 | |
| 2 | 2 | 1 | 1 | 0 | 0 | 0 | DUTY write |
| 3 | 3 | 1 | 3 | 1 | 0 | 0 | shadow load at boundary |
| 4 | 0 | 3 | 3 | 0 | 1 | 1 | new duty applies |
| 5 | 1 | 3 | 3 | 0 | 1 | 1 | |
| 6 | 2 | 3 | 3 | 0 | 1 | 1 | |
| 7 | 3 | 3 | 3 | 1 | 0 | 0 | |

## 8. Clocking & Reset

- Single clock domain `clk`; the bus is synchronous to `clk`; no CDC.
- `rst_n` is active-low, asserted asynchronously and released synchronously. Every register resets to 0, so after reset all outputs are low (POL=0, inactive).
- `pwm_out` comes straight from flops, so it is glitch-free.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| DUTY = 0 | Output always inactive. |
| DUTY ≥ PERIOD | Output always active (100%). |
| PERIOD = 0 | Channel treated as off (inactive); counter holds 0, and a boundary fires every tick so a new PERIOD loads immediately. |
| PERIOD = 1, edge | Counter stays at 0; boundary every tick; 0% or 100% only. |
| Write to PERIOD/DUTY mid-period | Takes effect at the next boundary; no runt pulse. |
| CENTER changed mid-period | Shadowed; applied at the boundary. |
| POL changed mid-period | Immediate (1 cycle); may create one edge. Documented. |
| EN or GEN cleared | Immediate stop; output goes to the inactive level next cycle; counter cleared. |
| PRESC changed while running | Any CTRL write clears `presc_cnt_q`, so the new PRESC applies from a clean count. Without this, a counter already above the new PRESC would run to 2^PRESC_W before wrapping (one very long tick). |
| Write to RO / unmapped address | Ignored. |
| Simultaneous `reg_wr` and `reg_rd` | Both performed; read returns the pre-write value. |

## 10. Verification Plan

**Testbench:** a bus driver task (`write(addr,data)`, `read(addr)`) and a per-channel monitor
that measures high/low time and period on `pwm_out`. These are compared with a reference
model built from the register state, with shadow-update semantics.

**Directed tests**
1. Reset values; all registers read 0; outputs low.
2. Edge-aligned: PERIOD=10, DUTY ∈ {0, 1, 5, 9, 10, 11}; check the duty ratio and period.
3. Center-aligned: same sweep; check symmetry (the pulse midpoint is at the period midpoint).
4. Shadow update: write DUTY mid-period; the current period is unaffected and the new value applies next.
5. Polarity inversion and the disabled-channel inactive level.
6. Prescaler: PRESC ∈ {0, 1, 99}; frequency scales by PRESC+1.
7. COUNT readback and reserved-bit read-as-zero.

**Random:** random register writes at random times on all channels for 1M cycles. The
monitor checks that each pulse width and period equals the values loaded at that period's
start.

**Assertions (SVA)**

```systemverilog
a_no_runt:   // each completed active pulse width == expected from the shadows of that period
a_cnt_range: assert property (@(posedge clk) disable iff(!rst_n)
               run && per_act_q != 0 |-> cnt_q < per_act_q);
a_off_level: assert property (@(posedge clk) disable iff(!rst_n) !run |=> out_q == $past(pol_q));
a_shadow:    assert property (@(posedge clk) disable iff(!rst_n)
               run && !(tick && boundary) |=> $stable(duty_act_q));
```

**Coverage:** both modes × {0%, mid, 100%}; shadow load with pending changes; every channel
enabled at least once; PRESC 0 and >0; POL both values.

## 11. Assumptions & Open Questions

1. **Center-aligned compare** uses `cnt >= PERIOD − DUTY` with turning-point hold. This gives exactly `2·DUTY` active ticks out of `2·PERIOD`, so the duty ratio is identical to edge-aligned mode.
2. **POL and EN are not shadowed.** The spec only lists PERIOD, DUTY and CENTER as double-buffered. POL changes can cause one edge immediately.
3. **Writing CTRL clears the prescaler counter** to avoid a long tick when PRESC shrinks. That restarts the current tick for all channels. Acceptable.
4. **While a channel is disabled, the shadows track the preloads,** so the first period after enabling uses the latest values without waiting for a boundary.
5. **PERIOD = 0 is treated as "off"** rather than as 2^16 ticks.
6. **The bus has no byte enables;** all writes are full-word.
7. **COUNT readback** returns the live counter and is not synchronized to the boundary; software may read a value that is 1 tick stale.
