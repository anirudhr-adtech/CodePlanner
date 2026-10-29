# Micro-architecture: `debounce_edge`

## 1. Overview

`debounce_edge` takes `NUM_BTN` asynchronous, active-low, bouncing push-button inputs and,
for each one, produces:
- a clean, debounced, active-high level `btn_level` (1 = pressed),
- a single-cycle `btn_rise` pulse when a press is confirmed,
- a single-cycle `btn_fall` pulse when a release is confirmed.

Each channel has the same pipeline: a 2-flop synchronizer, a stability counter (an integrator
that restarts on any change), a debounced state register, and an edge detector. The debounce
time is set from `CLK_HZ` and `DEBOUNCE_MS` at elaboration, so retargeting from 50 MHz to
100 MHz only needs a parameter change.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | System clock (`CLK_HZ`). |
| `rst_n` | in | 1 | Active-low reset, async assert, sync de-assert (from the reset controller). |
| **Buttons** | | | |
| `btn_n_raw` | in | `NUM_BTN` | Raw, asynchronous, active-low button pins (pressed = 0). |
| **Outputs** | | | |
| `btn_level` | out | `NUM_BTN` | Debounced level, active-high (1 = pressed). |
| `btn_rise` | out | `NUM_BTN` | 1-cycle pulse when a press is confirmed. |
| `btn_fall` | out | `NUM_BTN` | 1-cycle pulse when a release is confirmed. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `NUM_BTN` | 4 | 1–64 | Number of independent button channels. |
| `CLK_HZ` | 50_000_000 | 1_000–1_000_000_000 | Clock frequency in Hz. |
| `DEBOUNCE_MS` | 10 | 1–1000 | Required stable time in milliseconds. |
| `SYNC_STAGES` | 2 | 2–4 | Synchronizer depth. |
| `CNT_MAX` | `CLK_HZ/1000*DEBOUNCE_MS - 1` | derived (localparam) | Terminal count; e.g. 499_999 at 50 MHz / 10 ms. |
| `CNT_W` | `$clog2(CNT_MAX+1)` | derived (localparam) | Counter width; 19 bits at 50 MHz, 20 bits at 100 MHz. |

`CLK_HZ/1000` is computed first to avoid 32-bit overflow in `CLK_HZ*DEBOUNCE_MS`. If the
result rounds to 0, an elaboration check (`generate` + `$error`) stops the build.

## 4. Block Diagram

One channel (replicated `NUM_BTN` times with a `generate for` loop):

```
 btn_n_raw[i]                          +---------------------+
 (async) --->[~]--->[FF]--->[FF]--> s  |  stability counter  |
           invert   sync1   sync2   |  |  cnt_q[CNT_W]       |
                    (ASYNC_REG)     |  |  clear when s==lvl  |
                                    +->|  inc when s!=lvl    |
                                    |  +---------------------+
                                    |            | cnt_done
                                    |            v
                                    |   +-----------------+     +----------------+
                                    +-->| level_q (state) |---->| edge detect    |--> btn_rise[i]
                                        | toggles on done |  |  | lvl_d1_q       |--> btn_fall[i]
                                        +-----------------+  |  +----------------+
                                                             +---------------------> btn_level[i]
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `g_ch[i].u_sync` | `sync_2ff` | `SYNC_STAGES`-flop synchronizer with `ASYNC_REG`/don't-touch attributes. |
| `g_ch[i]` (inline) | debounce counter | Stability counter and level register. |
| `g_ch[i]` (inline) | edge detect | Rise/fall pulses from `level_q` vs. its delayed copy. |

## 5. Datapath

**Registers (per channel)**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `sync_q` | `SYNC_STAGES` | all 0 (= released, after inversion) | Synchronizer chain for the inverted input. |
| `cnt_q` | `CNT_W` | 0 | Counts consecutive cycles where the synced input differs from `level_q`. |
| `level_q` | 1 | 0 | Debounced level; drives `btn_level[i]`. |
| `level_d1_q` | 1 | 0 | `level_q` delayed one cycle, for edge detection. |

The input is inverted before the synchronizer (`~btn_n_raw[i]`), so all internal logic is
active-high. The inverter has no state, so placing it before the first flop does not affect
metastability behaviour.

**Counter behaviour (per channel)**

```verilog
wire s        = sync_q[SYNC_STAGES-1];     // synchronized, active-high
wire diff     = (s != level_q);
wire cnt_done = diff && (cnt_q == CNT_MAX);

cnt_n   = diff ? (cnt_done ? '0 : cnt_q + 1'b1) : '0;
level_n = cnt_done ? s : level_q;
```

The counter only runs while the input disagrees with the debounced state. Any bounce back
to the old level clears it, so the input has to stay continuously stable for `CNT_MAX+1`
cycles.

**Edge detect**

```verilog
assign btn_rise[i] =  level_q & ~level_d1_q;
assign btn_fall[i] = ~level_q &  level_d1_q;
```

These are decoded from two registers, so they are glitch-free single-cycle pulses.

## 6. Control Logic

Each channel is a two-state machine implied by `level_q`, plus a counter acting as a timer.

| State | `level_q` | Output `btn_level` | Transition |
|-------|-----------|--------------------|------------|
| RELEASED | 0 | 0 | → PRESSED when `s==1` for `CNT_MAX+1` consecutive cycles (`cnt_done`). |
| PRESSED | 1 | 1 | → RELEASED when `s==0` for `CNT_MAX+1` consecutive cycles (`cnt_done`). |

Counter sub-behaviour in either state:

| Condition | `cnt_q` next |
|-----------|--------------|
| `s == level_q` | 0 (input agrees; restart) |
| `s != level_q`, `cnt_q < CNT_MAX` | `cnt_q + 1` |
| `s != level_q`, `cnt_q == CNT_MAX` | 0, and `level_q` flips |

## 7. Timing & Pipeline

- **Synchronizer latency:** `SYNC_STAGES` cycles (2 by default), plus up to 1 cycle of sampling uncertainty.
- **Debounce latency:** `CNT_MAX + 1` cycles of stable input after the synchronizer; 10 ms at the defaults.
- **Edge pulse:** asserted in the first cycle `level_q` holds its new value; lasts 1 cycle.
- **Total press-to-pulse latency:** about `SYNC_STAGES + CNT_MAX + 2` cycles (500,004 cycles, about 10.0001 ms at 50 MHz).
- **Critical path:** the 19–20-bit incrementer and compare. Trivial at 100 MHz.

Cycle-by-cycle example (shrunk to `CNT_MAX=2` for illustration; `s` is the synchronized input):

| Cycle | s | diff | cnt_q (during) | cnt_done | level_q (during) | rise | fall | Note |
|-------|---|------|----------------|----------|------------------|------|------|------|
| 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | idle |
| 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | press starts |
| 2 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | bounce, counter restarts |
| 3 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | stable from here |
| 4 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | |
| 5 | 1 | 1 | 2 | 1 | 0 | 0 | 0 | 3rd stable cycle |
| 6 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | press confirmed |
| 7 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | |

## 8. Clocking & Reset

- **Single clock domain `clk`.** The only CDC is the raw button pins (fully asynchronous) into `clk`, handled by the `SYNC_STAGES`-flop synchronizer per bit.
- Each button bit is an independent 1-bit signal, so per-bit synchronizers are safe; there is no multi-bit coherence requirement.
- The synchronizer flops carry `(* ASYNC_REG = "TRUE" *)` (Xilinx) or an equivalent attribute and are placed in the same slice for the best MTBF. For ASIC, use the library's synchronizer cell.
- **Reset:** `rst_n` is active-low, asserted asynchronously and released synchronously. Reset sets `level_q=0`, `level_d1_q=0`, `cnt_q=0` and the synchronizer flops to 0 (released). No edge pulses fire coming out of reset.
- **Button held during reset:** after reset, `s=1` disagrees with `level_q=0`, so after the debounce time `level_q` goes to 1 and `btn_rise` fires once. This is reported as a press (§11).

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| Bounce shorter than the debounce time | Counter restarts on every bounce; no output change. |
| Glitch exactly `CNT_MAX` cycles long | Not accepted; `CNT_MAX+1` cycles are needed. |
| Press shorter than the debounce time | Ignored entirely (no rise and no fall pulse). |
| Button held through reset | One `btn_rise` after the debounce time (§8). |
| Metastable first flop | Resolved by the 2nd flop; at worst a 1-cycle delay in detection. |
| Very fast repeated presses (>50 Hz) | Some presses are filtered; this is inherent to a 10 ms debounce. |
| All channels pressed simultaneously | Channels are independent; all report on their own timing. |

## 10. Verification Plan

**Testbench:** a behavioural button model with configurable bounce (N random toggles of
random 10 µs–2 ms width before settling). The simulation uses small parameters
(`CLK_HZ=1_000_000`, `DEBOUNCE_MS=1` → `CNT_MAX=999`) to keep runtime low; one long run uses
the real 50 MHz / 10 ms values.

**Directed tests**
1. Clean press and release: exactly one rise and one fall, at the expected latencies.
2. Bouncy press: many bounces before settling still produce one rise.
3. Glitch of `CNT_MAX` cycles is rejected; `CNT_MAX+1` cycles is accepted.
4. Button held during reset gives one rise after reset.
5. Independent channels: different press patterns per channel.
6. Parameter sweep: `CLK_HZ ∈ {50 MHz, 100 MHz}`, check `CNT_W` and `CNT_MAX`.

**Assertions (SVA)**

```systemverilog
a_rise_1cyc: assert property (@(posedge clk) disable iff(!rst_n) btn_rise[i] |=> !btn_rise[i]);
a_no_both:   assert property (@(posedge clk) disable iff(!rst_n) !(btn_rise[i] && btn_fall[i]));
a_stable_lvl:assert property (@(posedge clk) disable iff(!rst_n)
               $changed(btn_level[i]) |-> $past(cnt_q == CNT_MAX));
a_alternate: // rise and fall pulses strictly alternate per channel (tracked with an aux flag)
```

**Coverage:** press and release on each channel; a bounce that restarts the counter at least
once at a high count (> `CNT_MAX/2`); the boundary glitch lengths; simultaneous edges on
multiple channels.

## 11. Assumptions & Open Questions

1. **The debounce algorithm** is "input must be continuously stable for `DEBOUNCE_MS`", applied to both press and release. The customer said "around 10 ms"; that is the default.
2. **The counter runs per channel.** A shared prescaler (1 kHz tick plus a small per-channel counter) would save about 15 flops per channel. With 4 channels the saving is not worth the extra quantization (±1 ms) in timing; reconsider if `NUM_BTN` grows past ~16.
3. **The reset value is "released".** A button held through reset is reported as a new press. Confirm with firmware that this is acceptable.
4. **Edge pulses are 1 `clk` cycle wide** and the firmware samples them in the same domain. If the firmware polls over a slower bus, add sticky event bits with write-1-to-clear.
5. **Polarity inversion happens inside the block,** so outputs are active-high as requested.
6. **Synchronizer depth is 2 by default.** For 100 MHz with a long MTBF requirement, `SYNC_STAGES=3` is available.
