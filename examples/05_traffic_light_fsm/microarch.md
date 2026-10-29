# Micro-architecture: `traffic_ctrl`

## 1. Overview

`traffic_ctrl` controls a two-phase, 4-way intersection: north-south (NS) and east-west
(EW). A six-state main FSM sequences GREEN → YELLOW → ALL-RED for each road. A small
pedestrian sub-FSM runs WALK → FLASHING DON'T WALK on the crossing parallel to the green road.

Key features:
- Actuated control: the green is held for at least `GREEN_MIN`, extended while vehicles keep arriving (gap-out after `EXT_GAP`), and capped at `GREEN_MAX`.
- Rest-in-green: with no demand on the cross road, the current green is held indefinitely.
- Latched pedestrian requests. Walk and clearance are never truncated.
- All timing runs on a 100 ms tick derived from the 50 MHz clock; durations are parameters in ticks.
- Registered one-hot lamp outputs. A safe all-red state on reset.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | 50 MHz system clock. |
| `rst_n` | in | 1 | Active-low reset, async assert, sync de-assert. |
| **Field inputs (asynchronous)** | | | |
| `car_ns_raw` | in | 1 | Vehicle present on an NS approach (loop detector, active-high). |
| `car_ew_raw` | in | 1 | Vehicle present on an EW approach. |
| `ped_btn_ns_raw` | in | 1 | Pedestrian button for walking parallel to NS (crossing EW road). Pre-debounced. |
| `ped_btn_ew_raw` | in | 1 | Pedestrian button for walking parallel to EW. Pre-debounced. |
| **Lamps** | | | |
| `ns_lamp` | out | 3 | One-hot `{red, yellow, green}` for NS signal heads. |
| `ew_lamp` | out | 3 | One-hot `{red, yellow, green}` for EW signal heads. |
| `ns_walk` | out | 1 | NS pedestrian WALK lamp. |
| `ns_dont_walk` | out | 1 | NS pedestrian DON'T WALK lamp (flashes during clearance). |
| `ew_walk` | out | 1 | EW pedestrian WALK lamp. |
| `ew_dont_walk` | out | 1 | EW pedestrian DON'T WALK lamp. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `CLK_HZ` | 50_000_000 | ≥ 1_000 | Clock frequency. |
| `TICK_HZ` | 10 | 1–1000 | Timer tick rate (100 ms resolution). |
| `GREEN_MIN` | 100 | ≥ 1 | Minimum green, in ticks (10 s). |
| `GREEN_MAX` | 450 | > `GREEN_MIN` | Maximum green with vehicle extension (45 s). |
| `EXT_GAP` | 30 | ≥ 1 | Gap-out time without a vehicle (3 s). |
| `YELLOW_T` | 40 | ≥ 1 | Yellow time (4 s). |
| `ALLRED_T` | 20 | ≥ 1 | All-red clearance (2 s). |
| `WALK_T` | 70 | ≥ 1 | WALK time (7 s). |
| `PED_CLR_T` | 100 | ≥ 1 | Flashing DON'T WALK time (10 s). |
| `TICK_DIV` | `CLK_HZ/TICK_HZ` | derived | Prescaler terminal count + 1 (5_000_000). |
| `T_W` | 9 | derived: `$clog2(max(all times)+1)` | Timer width (9 bits for the 450-tick maximum). |

Elaboration check: `GREEN_MIN < GREEN_MAX`, and `WALK_T + PED_CLR_T` must be a sane value
(warning if it is greater than `GREEN_MAX`).

## 4. Block Diagram

```
 car_*_raw, ped_btn_*_raw
        |
        v
 +--------------+  car_ns, car_ew   +--------------------+
 | sync_2ff x4  |------------------>|  demand / gap      |
 +--------------+  ped_ns, ped_ew   |  ped_req_*_q latch |
                         |          |  gap_cnt_q         |
                         +--------->+--------------------+
                                       | cross_demand, gapped, ped_req
 +--------------+  tick                v
 | tick_gen     |------------->+--------------------+   state_q   +-----------+
 | div_cnt_q    |              |  main FSM          |------------>| lamp      |--> ns_lamp, ew_lamp
 +--------------+              |  phase_cnt_q       |             | decode    |
        | flash (1 Hz)         +--------------------+             | (regs)    |--> walk / dont_walk
        |                              ^   | green entry          +-----------+
        |                              |   v                           ^
        |                      +--------------------+                  |
        +--------------------->|  ped sub-FSM       |------------------+
                               |  ped_state_q,      | ped_hold
                               |  ped_cnt_q         |
                               +--------------------+
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_sync[3:0]` | `sync_2ff` | Synchronize the 4 field inputs. |
| `u_tick` | `tick_gen` | 100 ms tick plus a 1 Hz flash toggle. |
| `u_fsm` | `tl_main_fsm` | Main phase FSM, phase timer, gap timer, request latches. |
| `u_ped` | `tl_ped_fsm` | Walk / clearance sequencing for the green direction. |
| `u_out` | `tl_lamp_dec` | Registered lamp decode. |

## 5. Datapath

**Registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `div_cnt_q` | 23 | 0 | Clock prescaler (0..TICK_DIV−1). |
| `flash_cnt_q` | 3 | 0 | Counts ticks to toggle `flash_q` every 5 ticks (1 Hz flash). |
| `flash_q` | 1 | 0 | Flashing DON'T WALK phase. |
| `state_q` | 3 | `AR_EW` | Main FSM state. |
| `phase_cnt_q` | `T_W` | 0 | Ticks spent in the current main state (saturates). |
| `gap_cnt_q` | `T_W` | 0 | Ticks since the last vehicle on the green road (saturates at `EXT_GAP`). |
| `ped_req_ns_q` | 1 | 0 | Latched NS pedestrian request. |
| `ped_req_ew_q` | 1 | 0 | Latched EW pedestrian request. |
| `ped_state_q` | 2 | `P_IDLE` | Pedestrian sub-FSM state. |
| `ped_cnt_q` | `T_W` | 0 | Ticks in the current pedestrian state. |
| `ns_lamp_q`, `ew_lamp_q` | 3 each | `3'b100` (red) | Registered lamp outputs. |
| `*_walk_q`, `*_dont_walk_q` | 1 each | walk=0, dont_walk=1 | Registered pedestrian outputs. |

**Derived signals** (for the road that is currently green: `g` = green road, `x` = cross road)

```verilog
car_g        = (state_q==NS_G) ? car_ns : car_ew;
cross_demand = (state_q==NS_G) ? (car_ew | ped_req_ew_q) : (car_ns | ped_req_ns_q);
min_done     = phase_cnt_q >= GREEN_MIN;
max_done     = phase_cnt_q >= GREEN_MAX;
gapped       = gap_cnt_q   >= EXT_GAP;
ped_hold     = (ped_state_q != P_IDLE);
end_green    = cross_demand && min_done && (gapped || max_done) && !ped_hold;
```

**Timers:** on every `tick`, `phase_cnt_q` increments (saturating) and clears on any state
change. `gap_cnt_q` clears whenever `car_g` is 1 or on entry to green, and otherwise increments
on `tick` (saturating).

## 6. Control Logic

**Main FSM** (`state_q`, 3-bit binary)

| State | Enc | NS lamp | EW lamp | Exit condition | Next |
|-------|-----|---------|---------|----------------|------|
| `NS_G` | 0 | G | R | `end_green` | `NS_Y` |
| `NS_Y` | 1 | Y | R | `tick && phase_cnt_q == YELLOW_T-1` | `AR_NS` |
| `AR_NS` | 2 | R | R | `tick && phase_cnt_q == ALLRED_T-1` | `EW_G` |
| `EW_G` | 3 | R | G | `end_green` | `EW_Y` |
| `EW_Y` | 4 | R | Y | `tick && phase_cnt_q == YELLOW_T-1` | `AR_EW` |
| `AR_EW` | 5 | R | R | `tick && phase_cnt_q == ALLRED_T-1` | `NS_G` |
| others | 6, 7 | R | R | always | `AR_EW` (safe recovery) |

Reset enters `AR_EW`, so the first green is NS after a full all-red period.

**Pedestrian sub-FSM** (`ped_state_q`; serves the crossing parallel to the green road)

| State | Enc | Walk lamp (green road) | Don't-walk lamp | Transition |
|-------|-----|------------------------|-----------------|------------|
| `P_IDLE` | 0 | 0 | 1 (steady) | → `P_WALK` when in a green state, `ped_req_g_q`=1, and (green entry OR `!cross_demand`) |
| `P_WALK` | 1 | 1 | 0 | → `P_CLR` on `tick && ped_cnt_q == WALK_T-1` |
| `P_CLR` | 2 | 0 | `flash_q` | → `P_IDLE` on `tick && ped_cnt_q == PED_CLR_T-1` |

The cross-road pedestrian lamps always show steady DON'T WALK.

**Request latches:** `ped_req_ns_q` is set on the synced button. It clears when `P_WALK` is
entered for NS. A press while the NS walk is already in `P_WALK` is ignored; a press during
`P_CLR` latches for the next NS green. EW works the same way.

## 7. Timing & Pipeline

- **Tick:** 1 cycle pulse every 5,000,000 clocks (100 ms). All FSM timing has 100 ms resolution.
- **Input latency:** 2 clocks (synchronizer). Negligible compared to the tick.
- **Output latency:** lamps are registered, 1 clock after the state change.
- **Cycle length (both roads saturated, no pedestrians):** 2 × (45 + 4 + 2) s = 102 s.

Phase example (in ticks; NS green, EW car arrives at t=50, NS cars keep coming until t=120):

| t (ticks) | state | phase_cnt | car_ns | car_ew | gap_cnt | end_green | Note |
|-----------|-------|-----------|--------|--------|---------|-----------|------|
| 0 | NS_G | 0 | 1 | 0 | 0 | 0 | green start |
| 50 | NS_G | 50 | 1 | 1 | 0 | 0 | cross demand, min not met |
| 100 | NS_G | 100 | 1 | 1 | 0 | 0 | min met, NS still busy |
| 120 | NS_G | 120 | 0 | 1 | 0 | 0 | last NS car |
| 150 | NS_G | 150 | 0 | 1 | 30 | 1 | gap-out |
| 151 | NS_Y | 0 | 0 | 1 | - | - | yellow 4 s |
| 191 | AR_NS | 0 | 0 | 1 | - | - | all red 2 s |
| 211 | EW_G | 0 | 0 | 1 | 0 | - | EW green |

## 8. Clocking & Reset

- **Single clock domain `clk` (50 MHz).** The four field inputs are asynchronous and each goes through a 2-flop synchronizer (`ASYNC_REG`). They are independent single-bit signals, so per-bit synchronizers are safe.
- **Reset:** `rst_n` is active-low, asserted asynchronously and released synchronously. Reset forces every lamp to red and every pedestrian lamp to steady DON'T WALK, and puts the FSM in `AR_EW` with all counters at 0.
- **Illegal states** (encodings 6–7, e.g. from an SEU) recover to `AR_EW`; the lamp decode drives all red for them.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| No demand anywhere | Rest in current green indefinitely. |
| Cross demand only from a pedestrian | Switches after `GREEN_MIN` plus gap-out, like a car. |
| Continuous traffic on the green road | Green capped at `GREEN_MAX`. |
| Pedestrian button pressed while resting in green | Walk starts immediately (no cross demand), then green may end after clearance. |
| Cross demand arrives during walk/clearance | Green held until `P_IDLE` (`ped_hold`); clearance is never cut short, even past `GREEN_MAX`. |
| Sensor stuck at 1 on the green road | Green capped by `GREEN_MAX`; the cycle continues. |
| Sensor stuck at 1 on the cross road | Normal cycling (every green ends at min/gap/max). |
| Both lamps green | Impossible by construction (one-hot decode from one state); asserted in verification. |
| Corrupted state | Recovers to all-red `AR_EW`. |

## 10. Verification Plan

**Testbench:** the simulation uses `TICK_DIV=10` to compress time. A scoreboard checks lamp
sequences and dwell times against the parameters.

**Directed tests**
1. Reset: all red, then NS green after `ALLRED_T`.
2. Rest in green: no demand for 10× `GREEN_MAX` → no change.
3. Gap-out: cross demand plus a short burst of NS cars → green ends at `max(GREEN_MIN, last_car + EXT_GAP)`.
4. Max-out: continuous NS cars → green ends at `GREEN_MAX`.
5. Pedestrian at green entry; pedestrian while resting; pedestrian request during clearance (latched for the next cycle).
6. Pedestrian walk overlapping `GREEN_MAX`: clearance completes before yellow.
7. Illegal state injection (force `state_q=7`) → recovers to all red.

**Random:** random car arrivals (Poisson) and button presses over 10^5 ticks.

**Assertions (SVA)**

```systemverilog
a_no_conflict: assert property (@(posedge clk) ns_lamp == 3'b100 || ew_lamp == 3'b100); // one road always red
a_onehot:      assert property (@(posedge clk) $onehot(ns_lamp) && $onehot(ew_lamp));
a_y_before_r:  // green -> yellow -> red order: green never directly followed by red
a_walk_safe:   assert property (@(posedge clk) ns_walk |-> ns_lamp == 3'b001);
a_min_green:   // green duration >= GREEN_MIN ticks
```

**Coverage:** each exit reason (gap-out, max-out, pedestrian-held); pedestrian service on
both roads; rest-in-green; recovery from an illegal state.

## 11. Assumptions & Open Questions

The spec left timing and power-up behaviour open. Decisions taken:

1. **Timing values:** green min 10 s and yellow 4 s (from the spec); green max 45 s, gap 3 s, all-red 2 s, walk 7 s, pedestrian clearance 10 s (typical traffic-engineering values). All are parameters; real values must come from a traffic engineer.
2. **Power-up:** all red for `ALLRED_T`, then NS green. NS is treated as the main road. Many real controllers start in flashing red; that can be added as a `FLASH` state if required.
3. **The pedestrian walk** is concurrent with the parallel vehicle green (no exclusive pedestrian phase).
4. **Pedestrian clearance has priority over `GREEN_MAX`** for safety.
5. **The buttons are assumed debounced** externally (e.g. with `debounce_edge`). Bounce on a latch-set input is harmless anyway.
6. **Sensor inputs are presence-type and active-high.** No sensor-fault detection; a stuck sensor is bounded by `GREEN_MAX`.
7. **No emergency pre-emption, night flash or conflict monitor.** These are out of scope, but a safety-critical deployment needs an independent hardware conflict monitor.
8. **Lamp outputs are logic-level;** lamp drivers and failed-lamp detection are external.
