# MA plan: 03_pwm_generator

## S1. Scope the 8-channel PWM controller and fix the NUM_CH parameterisation

**Goal:** Write the Overview and Parameters sections. Describe up to 8 independent channels, each with edge or center alignment, shadowed PERIOD/DUTY/CENTER, a shared prescaler and registered outputs. State how NUM_CH maps onto the fixed 0x10-stride register map.

**Feeds:** Overview, Parameters · **Depends on:** none

**Spec evidence:**
- [P2] "Up to 8 independent PWM channels for motor/LED control."
- [P2] "Changes written by software must never produce a truncated or runt pulse"
- [P10] "Outputs: `pwm_out[NUM_CH-1:0]`, must be"
- [P6] "0x10 + 0x10*n"

**Decisions:**
- D1 NUM_CH parameter and accesses to unimplemented channel slots: **NUM_CH is a synthesis parameter (1..8). Register slots for channels n >= NUM_CH, and any unmapped offset, read as 0 and ignore writes.** (default, low impact, high confidence)
  - options: NUM_CH parameter 1..8; offsets for channels >= NUM_CH read 0 and ignore writes / Always build 8 channels and leave unused outputs unconnected
  - The spec uses NUM_CH in the port list and says 'up to 8'. The bus has no error response, so read-as-zero is the only consistent behaviour.

**Done when:**
- Overview lists every feature in P2, P6, P9 and P10, including the no-runt guarantee for value updates and the agreed immediate-stop exception for EN/GEN clears.
- Parameters table defines NUM_CH (legal range 1..8, default 8) and states that counter width is fixed at 16 bits.
- Address-to-channel decoding is stated for all of 0x00 through 0x8C.

## S2. Register bus decode, register file and one-cycle read path

**Goal:** Define the Interface and the register file: word-aligned decode of reg_addr[7:0], write strobes into the software-visible (preload) CTRL and CHn_* registers, and a registered reg_rdata returned one cycle after reg_rd. Also define which value each readback returns (software-written preload vs active shadow value).

**Feeds:** Interface, Datapath · **Depends on:** S1

**Spec evidence:**
- [P4] "Simple synchronous register bus, 32-bit, word-aligned:"
- [P4] "Read data is returned one cycle after `reg_rd`. No wait states, no error response."
- [P7] "Reserved bits read as 0. All registers reset to 0."
- [P6] "Current counter value."

**Decisions:**
- D8 Readback value of shadowed registers (PERIOD, DUTY, CENTER): **Reads return the last value written by software (the preload), not the value currently in use by the counter.** (default, medium impact, medium confidence)
  - options: Return the last software-written (preload) value / Return the currently active (shadow) value
  - This is the common read-what-you-wrote convention and lets software verify its writes. The active value can be inferred from period boundaries.
- D9 reg_rdata behaviour and read/write collision: **reg_rdata is a flop loaded when reg_rd=1 and otherwise holds its value. A same-cycle write to the same address returns the pre-write value.** (default, low impact, medium confidence)
  - options: Registered rdata captured on reg_rd; holds the last value otherwise / Registered rdata forced to 0 when no read is in progress
  - Meets the one-cycle latency with minimal logic. The spec does not define a collision case.

**Done when:**
- Port table lists clk, rst_n, reg_wr, reg_rd, reg_addr[7:0], reg_wdata[31:0], reg_rdata[31:0] and pwm_out[NUM_CH-1:0], with direction, width and description.
- Every register field has defined write behaviour, and reserved bits are masked to 0 on read.
- Writes to the RO COUNT register are explicitly ignored.
- The handling of reg_addr[1:0] (ignored) is stated.

## S3. Shared prescaler tick generator driven by CTRL.PRESC

**Goal:** Specify a single prescaler counter that produces a one-cycle tick every PRESC+1 clocks. Define how a PRESC change mid-count is handled and whether the prescaler runs while GEN=0.

**Feeds:** Datapath, Control Logic · **Depends on:** S2

**Spec evidence:**
- [P6] "Clock prescaler. Counters advance every PRESC+1 clocks."
- [P6] "Global enable. 0 = all channels stopped."

**Decisions:**
- D2 Prescaler structure and PRESC update timing: **Use one global 16-bit prescaler shared by all channels. It is held at 0 while GEN=0. A PRESC write takes effect immediately against the live PRESC (compare uses >= so lowering PRESC wraps at once); it is not double-buffered.** (default, medium impact, medium confidence)
  - options: One global prescaler; PRESC change takes effect immediately; prescaler held in reset while GEN=0 / Per-channel prescaler / PRESC shadowed and loaded at a boundary
  - PRESC lives in the global CTRL register and the spec does not list it as shadowed. Changing the tick rate stretches or compresses ticks but cannot create a runt pulse in tick units.

**Done when:**
- Tick generation is described so that PRESC=0 gives a tick every clock and PRESC=N gives a tick every N+1 clocks.
- Behaviour when PRESC is lowered below the current prescaler count is defined, with no lock-up.
- The tick is shown as a single shared signal fanned out to all channel counters.

## S4. Per-channel 16-bit counter for edge-aligned up-count and center-aligned up/down count

**Goal:** Define the counter sequence in both modes relative to the active PERIOD. Define where the period boundary is in each mode and what CHn_COUNT reports.

**Feeds:** Datapath, Timing & Pipeline · **Depends on:** S3

**Spec evidence:**
- [P9] "Edge-aligned: output active at start of period, inactive after DUTY ticks."
- [P9] "active pulse is centred in the period; period is twice as long as"
- [P9] "edge-aligned for the same PERIOD value (up/down counting)."
- [P6] "Period in counter ticks."

**Decisions:**
- D3 Edge-aligned period semantics and PERIOD=0: **The edge-aligned counter runs 0..PERIOD-1 and wraps, so the period is exactly PERIOD ticks. The boundary is the wrap to 0. With PERIOD=0 the counter holds at 0, every tick is a boundary, and the output follows the DUTY rules (DUTY=0 inactive, otherwise active).** (default, medium impact, medium confidence)
  - options: Count 0..PERIOD-1 (period = PERIOD ticks); PERIOD=0 holds counter at 0 / Count 0..PERIOD (period = PERIOD+1 ticks)
  - 'Period in counter ticks' reads most naturally as exactly PERIOD ticks. PERIOD=0 needs some defined behaviour.
- D4 Center-aligned counting sequence and boundary location: **The counter goes up from 0 to PERIOD, then down to 0, giving 2*PERIOD ticks. The period boundary, and therefore the shadow load, occurs only at the bottom (count 0). The output is active while count > PERIOD-DUTY, so the pulse is 2*DUTY ticks wide and centred on the top of the triangle.** (default, medium impact, medium confidence)
  - options: Triangle 0 up to PERIOD then down to 0 (2*PERIOD ticks); boundary at bottom (count 0); pulse centred at top / Boundary at top with pulse centred at bottom / Load shadows at both top and bottom
  - This gives exactly twice the edge-aligned period and a single boundary per period, matching 'load at the period boundary'. Centring on the top keeps the boundary in an inactive region, so loads cannot cause runts.

**Done when:**
- Cycle-level counter sequences are given for edge-aligned PERIOD=4 and center-aligned PERIOD=4.
- Direction-state storage for up/down counting is defined, along with its reset to 0 and its clear to 0 while the channel is stopped.
- CHn_COUNT readback is defined in both modes.
- The counter advances only on the prescaler tick while the channel runs.

## S5. Double-buffered PERIOD/DUTY/CENTER shadow load at the period boundary

**Goal:** Define the two-level storage (software preload plus active shadow) for PERIOD, DUTY and CENTER. Define the exact load condition so that no software write produces a truncated or runt pulse, with shadows tracking the preloads continuously while the channel is stopped.

**Feeds:** Datapath, Control Logic · **Depends on:** S4

**Spec evidence:**
- [P9] "PERIOD, DUTY and CENTER are double-buffered (shadow registers) and load at the period boundary."
- [P2] "values take effect at the next period boundary."

**Decisions:**
- D5 Shadow load behaviour when the channel is not running: **While the channel is stopped (EN=0 or GEN=0), the shadows continuously track the preloads. While running, they load only at the period boundary. Re-enabling starts a clean period at count 0 with the latest PERIOD, DUTY and CENTER. A CENTER change at a boundary restarts the counter at 0 (dir=0) in the new mode.** (decided)
  - options: Shadows transparent (load every cycle) while EN=0 or GEN=0; boundary-only loads while running / Shadows only ever load at a boundary, even when stopped
  - Settled by the user's answer to Q1: shadows track preloads while stopped so re-enable uses the latest values.

**Done when:**
- A load-enable equation is given for each shadow field: load = ~run | boundary.
- It is shown that a write landing in the same cycle as a boundary has a defined outcome: either the new value loads or it waits one more period.
- A mode switch between edge and center is shown to take effect only at a boundary while running.

## S6. Compare, polarity and registered glitch-free pwm_out stage

**Goal:** Define the per-channel compare logic, including the DUTY=0 and DUTY>=PERIOD overrides, the POL inversion and the disabled-level forcing. All of this is combined before a single output flop per channel.

**Feeds:** Datapath, Timing & Pipeline · **Depends on:** S4, S5

**Spec evidence:**
- [P9] "output always inactive. DUTY "
- [P9] "output always active."
- [P6] "Output polarity. 0 = active-high, 1 = active-low."
- [P9] "Disabled channel drives its inactive level."
- [P10] "glitch-free (registered)."

**Decisions:**
- D12 Output registration point: **Each pwm_out bit comes directly from a flop whose D input combines compare, DUTY overrides, enable gating and POL.** (decided)
  - options: Final flop after compare, override, polarity and enable gating / Register only the compare result and apply polarity combinationally
  - P10 requires registered, glitch-free outputs, so no logic may sit after the flop.

**Done when:**
- A truth table covers EN/GEN, DUTY=0, DUTY>=PERIOD, normal compare and POL.
- The output-flop reset value is stated, and its interaction with POL after reset is noted: with all registers 0, POL=0 and the output is low.
- One cycle of latency from counter state to pwm_out is documented.

## S7. Immediate-stop enable semantics and POL timing against the no-runt rule

**Goal:** Document how GEN and EN start and stop channels per the Q1 answer (immediate stop, counter and dir cleared, fresh period on re-enable), and decide when POL changes apply, since POL is not listed as shadowed but the spec forbids runt pulses from software changes.

**Feeds:** Control Logic, Corner Cases & Error Handling · **Depends on:** S5, S6

**Spec evidence:**
- [P6] "Global enable. 0 = all channels stopped."
- [P6] "Channel enable."
- [P2] "Changes written by software must never produce a truncated or runt pulse"

**Decisions:**
- D6 Enable/disable timing and counter state while stopped: **Clearing EN or GEN takes effect at once: pwm_out goes to its inactive level (the POL value) on the next cycle, possibly truncating the pulse. Counter and dir are cleared to 0 while stopped. Setting EN/GEN starts a clean new period at count 0 with the latest shadowed values.** (decided)
  - options: Immediate: disable forces inactive and resets counter to 0; enable starts a fresh period at count 0 / Disable deferred to the end of the current period (no truncation) / Stop holds counter value and resumes from it
  - Settled by the user's answer to Q1; the truncation on disable is an accepted exception to the P2 no-runt rule.
- D7 POL change timing while running: **POL is not double-buffered and applies on the next cycle, inverting the current output level.** (default, low impact, medium confidence)
  - options: POL applies immediately (next cycle) / POL shadowed and loaded at the period boundary
  - P9 lists only PERIOD, DUTY and CENTER as shadowed. Polarity is normally configured while the channel is stopped; a live change is a configuration change, not a duty update.
- D11 Phase relationship between channels: **All channel counters are cleared while GEN=0, and the prescaler is held at 0, so channels already enabled start in phase when GEN rises. A channel enabled later starts its own period on its EN rise, aligned to the shared tick.** (default, low impact, medium confidence)
  - options: Channels with EN=1 all restart at count 0 when GEN rises (phase-aligned); individual EN rising starts that channel independently / Fully free-running and unsynchronised
  - This follows from the D6 clear-on-stop behaviour with the shared tick, and gives software a way to phase-align channels for free.

**Done when:**
- A run-state definition per channel (run = GEN & EN) and its effect on the counter, dir, shadows and output are written down.
- Behaviour for each of the four GEN/EN transitions is tabulated, including the one-cycle stop latency.
- The accepted truncation on EN/GEN clear is explicitly called out as the only exception to the P2 no-runt rule, citing the user answer.

## S8. Clocking and active-low reset strategy for a single 100 MHz domain

**Goal:** Document the single clock domain and the rst_n handling. Confirm that all registers, shadows, counters, the prescaler and the output flops reset to 0, and that the 16-bit compare paths close timing at 100 MHz.

**Feeds:** Clocking & Reset · **Depends on:** S2

**Spec evidence:**
- [P10] "Clock: `clk` (100 MHz). Reset: `rst_n`, active-low."
- [P7] "Reserved bits read as 0. All registers reset to 0."

**Decisions:**
- D10 Reset style: **Use asynchronous active-low reset on all flops. rst_n is assumed already synchronised for deassertion by the SoC.** (default, low impact, medium confidence)
  - options: Asynchronous assert, synchronous deassert (synchronizer external or internal) / Fully synchronous reset
  - This guarantees pwm_out reaches its inactive level immediately on reset even without a clock, which is common for motor/LED drivers.

**Done when:**
- The reset value is listed for every storage element, including preloads, shadows, the prescaler, counters, direction bits, the rdata flop and the output flops.
- The critical path is identified (16-bit compare plus output mux) and is feasible at 10 ns.
- The absence of CDC is confirmed.

## S9. Block diagram and end-to-end timing of write-to-effect and read latency

**Goal:** Assemble the block diagram: bus decode, register file, prescaler, per-channel shadow/counter/compare/output slices and the read mux. Provide the timing diagrams that show the observable latencies.

**Feeds:** Block Diagram, Timing & Pipeline · **Depends on:** S2, S3, S4, S5, S6, S7

**Spec evidence:**
- [P4] "Read data is returned one cycle after `reg_rd`."
- [P2] "values take effect at the next period boundary."

**Done when:**
- The block diagram shows one shared prescaler and NUM_CH replicated channel slices.
- Waveforms show a reg_rd to reg_rdata timing of one cycle.
- Waveforms show a DUTY write mid-period that takes effect at the next boundary, in both modes.
- Waveforms show the GEN rise to first pwm_out edge latency and the EN clear to inactive-output latency.

## S10. Corner cases specific to this PWM: degenerate PERIOD/DUTY, mode switch, PRESC change, mid-pulse stop

**Goal:** Enumerate and resolve the edge conditions. None of these return bus errors, because the bus has no error response.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S7, S8

**Spec evidence:**
- [P9] "output always inactive. DUTY "
- [P4] "No wait states, no error response."

**Done when:**
- Covers PERIOD=0, PERIOD=1, DUTY=PERIOD, DUTY=PERIOD-1 and PERIOD=0xFFFF in both modes.
- Covers a CENTER toggle while running, a PRESC change mid-period, a POL change while running, and a write in the same cycle as a boundary.
- Covers EN/GEN clear mid-pulse (truncation allowed) and re-enable with values written while stopped.
- Covers accesses to unimplemented channels or offsets, and writes to COUNT.
- Each case has a defined expected output behaviour.

## S11. Verification plan centred on the no-runt guarantee and both alignment modes

**Goal:** Define a reference model, checkers and coverage that prove the period and duty for each mode, boundary-only shadow updates while running, shadow tracking while stopped, polarity and enable behaviour, and register-bus compliance.

**Feeds:** Verification Plan · **Depends on:** S9, S10

**Spec evidence:**
- [P2] "Changes written by software must never produce a truncated or runt pulse"
- [P9] "Center-aligned: active pulse is centred in the period"

**Done when:**
- A cycle-accurate reference model is specified for all NUM_CH channels.
- An assertion checks that no pulse width differs from the active DUTY unless EN or GEN fell during it.
- An assertion checks that pwm_out equals POL within one cycle of run going low, and that the counter and dir are 0 while stopped.
- Coverage bins are defined for mode x POL x DUTY class x PRESC (0 and >0) x write-phase relative to the boundary.
- A register reset and readback test covers reserved bits.

## S12. Record assumptions and open questions from the defaulted decisions

**Goal:** Collect every defaulted decision (D1-D4, D7-D11) with its question, and record the Q1 answer (D5, D6) as a settled assumption.

**Feeds:** Assumptions & Open Questions · **Depends on:** S11

**Spec evidence:**
- [P1] "Programmer's Model (rev 0.3)"

**Done when:**
- Each defaulted decision appears with its chosen default and a question for the spec author.
- The Q1 answer is recorded as a resolved item: immediate stop, counter/dir cleared, shadows track preloads while stopped.
- Spec revision 0.3 is noted as the baseline.

## Assumptions (defaults not confirmed by the user)

- D1 NUM_CH parameter and accesses to unimplemented channel slots: NUM_CH is a synthesis parameter (1..8). Register slots for channels n >= NUM_CH, and any unmapped offset, read as 0 and ignore writes. (low impact, high confidence)
- D8 Readback value of shadowed registers (PERIOD, DUTY, CENTER): Reads return the last value written by software (the preload), not the value currently in use by the counter. (medium impact, medium confidence)
- D9 reg_rdata behaviour and read/write collision: reg_rdata is a flop loaded when reg_rd=1 and otherwise holds its value. A same-cycle write to the same address returns the pre-write value. (low impact, medium confidence)
- D2 Prescaler structure and PRESC update timing: Use one global 16-bit prescaler shared by all channels. It is held at 0 while GEN=0. A PRESC write takes effect immediately against the live PRESC (compare uses >= so lowering PRESC wraps at once); it is not double-buffered. (medium impact, medium confidence)
- D3 Edge-aligned period semantics and PERIOD=0: The edge-aligned counter runs 0..PERIOD-1 and wraps, so the period is exactly PERIOD ticks. The boundary is the wrap to 0. With PERIOD=0 the counter holds at 0, every tick is a boundary, and the output follows the DUTY rules (DUTY=0 inactive, otherwise active). (medium impact, medium confidence)
- D4 Center-aligned counting sequence and boundary location: The counter goes up from 0 to PERIOD, then down to 0, giving 2*PERIOD ticks. The period boundary, and therefore the shadow load, occurs only at the bottom (count 0). The output is active while count > PERIOD-DUTY, so the pulse is 2*DUTY ticks wide and centred on the top of the triangle. (medium impact, medium confidence)
- D7 POL change timing while running: POL is not double-buffered and applies on the next cycle, inverting the current output level. (low impact, medium confidence)
- D11 Phase relationship between channels: All channel counters are cleared while GEN=0, and the prescaler is held at 0, so channels already enabled start in phase when GEN rises. A channel enabled later starts its own period on its EN rise, aligned to the shared tick. (low impact, medium confidence)
- D10 Reset style: Use asynchronous active-low reset on all flops. rst_n is assumed already synchronised for deassertion by the SoC. (low impact, medium confidence)
