# MA plan: 05_traffic_light_fsm

## S1. Frame the two-road, two-signal-group intersection and its phase model

**Goal:** Write an Overview that fixes the controller's scope. It has two vehicle signal groups (NS, EW) that alternate through green, yellow, red and all-red clearance. It has demand-driven green extension and two concurrent pedestrian groups, each showing WALK then flashing DON'T WALK alongside the parallel green. It runs from a 50 MHz FPGA clock.

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P1] "Traffic light controller for a 4-way intersection (north-south road crossing east-west road)."
- [P2] "Cycle NS and EW: green, yellow, then red, with the usual safety gap where both are red."
- [P3] "The FPGA board runs at 50 MHz."

**Done when:**
- Overview names the vehicle signal groups (NS, EW), the two pedestrian groups (NS-parallel, EW-parallel), and the phase cycle including all-red clearance.
- Overview states the core safety invariants: NS and EW are never simultaneously non-red; ns_walk shows only during NS green; ew_walk shows only during EW green.
- Overview lists the behaviours detailed later: green extension, skip-if-no-demand, and concurrent pedestrian service with no exclusive pedestrian phase.

## S2. Define the 2-sensor / 2-button / 2-ped-head port set and condition the raw field inputs

**Goal:** Specify every port: clock, reset, car_ns_raw, car_ew_raw, ped_btn_ns_raw, ped_btn_ew_raw, the NS/EW R/Y/G lamps and ns_walk/ns_dont_walk, ew_walk/ew_dont_walk. Define the synchronizer, debounce and latching chain that turns the raw field signals into clean demand bits.

**Feeds:** Interface, Clocking & Reset · **Depends on:** S1

**Spec evidence:**
- [P2] "Have car sensors on both roads."
- [P2] "Pedestrian push buttons for each crossing."
- [P3] "Sensors and buttons come from the field wiring."

**Decisions:**
- D2 Conditioning of field inputs (sensors and buttons): **Every sensor and button gets a 2-flop synchronizer and a counter-based debounce/glitch filter. Button presses are then latched into a pending pedestrian request that clears only when served.** (default, medium impact, high confidence)
  - options: 2-flop synchronizer only / 2-flop synchronizer + counter-based debounce (~10-20 ms) on every input / Synchronizer + debounce on buttons only, sensors synchronized and sampled raw
  - Field wiring is asynchronous, noisy and bouncy, and the '_raw' input names suggest unconditioned signals. Unconditioned inputs risk metastability and spurious calls. Latching ensures a brief press is never lost.
- D3 Number and grouping of pedestrian buttons, pedestrian signals and car sensors: **There is one of each per road. Button inputs are ped_btn_ns_raw (walking parallel to NS, served with NS green) and ped_btn_ew_raw (walking parallel to EW, served with EW green). Output pairs are ns_walk/ns_dont_walk and ew_walk/ew_dont_walk. Car sensors are car_ns_raw and car_ew_raw, each meaning a vehicle is present on any approach of that road.** (decided)
  - options: 2 buttons, 2 WALK/DON'T WALK pairs, 2 car sensors (one per road) / 4 crosswalk buttons OR-ed into 2 pedestrian groups; 2 signal pairs; 1 sensor per road / 4 independent crosswalks each with its own button and WALK/DON'T WALK output
  - Settled by the user's answer to Q1.

**Done when:**
- Port table lists direction, width, active level and meaning for clk, reset, car_ns_raw, car_ew_raw, ped_btn_ns_raw, ped_btn_ew_raw, the NS/EW R/Y/G lamps, ns_walk/ns_dont_walk and ew_walk/ew_dont_walk.
- The conditioning chain (sync -> debounce -> edge/latch) is specified per input class, with the debounce window given as a parameter.
- States that a latched pedestrian request clears at the WALK start of its group, and that a press during that group's clearance (flashing DON'T WALK) re-latches for the next green of that road.

## S3. Derive the 50 MHz-to-seconds timebase and the timing parameter set

**Goal:** Choose how seconds-scale intervals (4 s yellow, 10 s minimum green, etc.) are generated from 50 MHz. Fill in the TBD values: all-red, max green, gap/extension, WALK, flashing DON'T WALK and flash rate.

**Feeds:** Parameters, Timing & Pipeline, Clocking & Reset · **Depends on:** S1

**Spec evidence:**
- [P2] "Yellow about 4 seconds. Green at least 10 seconds."
- [P3] "The FPGA board runs at 50 MHz."
- [P4] "Exact timing and what to do on power-up TBD"

**Decisions:**
- D1 Timebase structure: **One free-running prescaler generates a single-cycle tick enable (100 ms resolution) in the 50 MHz domain. All phase timers and the flash generator count ticks. There is no derived clock.** (default, medium impact, high confidence)
  - options: Single prescaler producing a slow tick enable (e.g. 10 Hz / 100 ms) that all phase timers count / Each timer counts raw 50 MHz cycles with wide counters / Derived slow clock driving the FSM
  - This keeps a single clock domain and small timer counters. 100 ms is fine enough for gap timing and flashing, and the prescaler can be shrunk for simulation.
- D9 Timing programmability: **Use compile-time Verilog parameters in tick units. Suggested defaults: yellow 4 s, min green 10 s, all-red 2 s, gap 3 s, max green 40 s, WALK 7 s, flashing DON'T WALK 10 s, flash rate 1 Hz.** (default, medium impact, high confidence)
  - options: Compile-time Verilog parameters (in ticks) / Runtime-programmable registers via a host/config interface / Hard-coded constants
  - The spec defines no configuration interface and says to 'use sensible values'. Parameters let synthesis and simulation use different values.

**Done when:**
- Parameter table lists every interval with its default in seconds and in ticks, plus CLK_HZ and TICK_HZ.
- Shows the prescaler divide value for 50 MHz and the timer counter widths derived from the parameters.
- States the constraints: MAX_GREEN > MIN_GREEN. Notes that pedestrian clearance can extend green beyond MAX_GREEN, so the worst-case green is MAX_GREEN + WALK + FDW. Names the prescaler parameter used to scale time down in simulation.

## S4. Design the main phase FSM including all-red clearance and rest-in-green when unopposed

**Goal:** Define the state machine: NS_GREEN, NS_YELLOW, ALL_RED->EW, EW_GREEN, EW_YELLOW, ALL_RED->NS, plus startup states. Define the exit conditions of each state, the rule that green holds indefinitely when the other road has no demand, and the rule that yellow cannot start while the parallel pedestrian clearance is in progress.

**Feeds:** Control Logic, Block Diagram · **Depends on:** S2, S3

**Spec evidence:**
- [P2] "Cycle NS and EW: green, yellow, then red, with the usual safety gap where both are red."
- [P2] "If nobody is waiting on the other road there's no need to switch."

**Decisions:**
- D6 Behaviour with no opposing demand: **After minimum green, the current road rests in green indefinitely until an opposing call exists. An opposing call is the opposing sensor or the opposing latched pedestrian request. Max-green timing only applies while an opposing call is present.** (default, medium impact, medium confidence)
  - options: Rest in green of the currently served road until the opposing road has a vehicle or pedestrian call / Always return to and rest on a designated main road (e.g. NS) / Cycle anyway on a fixed recall
  - This follows directly from 'no need to switch'. It treats the roads symmetrically because the spec names no main road. It is consistent with the user's answer that a walk can start mid-green while resting.

**Done when:**
- State diagram and transition table give every state, its lamp outputs and exit conditions (timer expiry, gap-out, max-out, demand present, pedestrian clearance complete).
- Opposing demand is defined precisely: for NS green it is car_ew OR the EW ped request; for EW green it is car_ns OR the NS ped request.
- Shows that green-to-yellow is additionally gated by 'parallel pedestrian group idle', and that yellow and all-red are never skipped or shortened once entered.

## S5. Specify the green-extension (gap-out / max-out) logic driven by car_ns/car_ew

**Goal:** Turn 'keep it green longer, but not forever' into a concrete extension algorithm. Define its timers and the interaction of minimum green, extension and maximum green, including the pedestrian-clearance hold that can run past max green.

**Feeds:** Datapath, Control Logic, Timing & Pipeline · **Depends on:** S4

**Spec evidence:**
- [P2] "If cars keep coming on the road that's green, keep it green"
- [P2] "longer, but not forever."
- [P2] "Green at least 10 seconds."

**Decisions:**
- D5 Green extension algorithm: **Use the standard actuated scheme. Minimum green is always served. After that, green continues while detections on the green road keep restarting a gap timer (passage time). A termination request is raised on gap expiry (gap-out) or on max-green expiry (max-out); the max-green timer starts when an opposing call arrives. Either request requires an opposing call to exist. Yellow begins only once any parallel pedestrian clearance has also completed.** (default, medium impact, medium confidence)
  - options: Actuated gap-out: each detection on the green road restarts a gap timer; green ends on gap expiry or max-green, whichever first, after min green / Fixed extension blocks added per detection up to a cap / Sensor-level hold: green held while the sensor is asserted, up to max green
  - This is the industry-standard actuated control that matches 'keep it green longer, but not forever'. It works with simple presence sensors. The pedestrian hold past max green comes from the user's answer to Q2.

**Done when:**
- Datapath lists min-green, gap and max-green timers with widths, load/restart/enable conditions and expiry flags.
- Timing diagram shows min green, several extensions, then gap-out. A second case shows continuous traffic hitting max-out. A third case shows max-out during an active WALK, with green held until flashing DON'T WALK ends.
- States explicitly that the max-green timer starts when the opposing call arrives.

## S6. Integrate concurrent pedestrian WALK/flashing DON'T WALK with the parallel vehicle green

**Goal:** Define the per-group pedestrian sub-FSM (NS group tied to NS green, EW group tied to EW green). Specify when a latched request starts WALK: at green onset, or mid-green while resting with no cross demand. Specify that green holds until clearance ends, the flash generator, and how a cross-road ped request forces a phase change.

**Feeds:** Control Logic, Datapath, Timing & Pipeline · **Depends on:** S4, S5

**Spec evidence:**
- [P2] "Pedestrians get a WALK light, then a flashing"
- [P2] "DON'T WALK before the lights change."
- [P2] "Pedestrian push buttons for each crossing."

**Decisions:**
- D4 Pedestrian phase structure: **Pedestrian service is concurrent with no exclusive pedestrian phase. A latched request is served with WALK then flashing DON'T WALK during the parallel green. Green is held until clearance completes, even past GREEN_MAX, and only then does yellow begin. A walk can also start mid-green while the road rests with no cross demand. A press during clearance is latched for the next green of that road. Without a request the head stays solid DON'T WALK.** (decided)
  - options: Concurrent: WALK runs with the parallel vehicle green, flashing DON'T WALK finishes before that green ends, then solid DON'T WALK / Exclusive all-pedestrian phase with all vehicles red / Concurrent, with WALK shown on every green regardless of button (ped recall)
  - Settled by the user's answer to Q2.
- D10 Lamp output structure and flash generation: **Each lamp, including ns_walk/ns_dont_walk/ew_walk/ew_dont_walk, gets an individual registered active-high output. Flashing DON'T WALK is generated inside the FPGA by gating the dont_walk output with an internal ~1 Hz, 50% duty flash signal derived from the tick.** (default, medium impact, medium confidence)
  - options: Registered one-hot lamp outputs (R/Y/G per road, WALK and DON'T WALK per ped group), with flashing applied inside the FPGA from a 1 Hz flash enable / Encoded state outputs decoded externally / Separate 'flash' control bit for an external flasher
  - Direct, glitch-free lamp drive is simplest for an FPGA board feeding lamp drivers. It keeps all safety logic internal, and the named walk/dont_walk output pairs suggest individual lamp drives.

**Done when:**
- Per-group sub-state sequence (DONT_WALK -> WALK -> FLASH_DW -> DONT_WALK) is tied to the parallel vehicle green, with entry conditions: request latched AND parallel green AND (green onset OR no cross demand while resting).
- The MA defines what happens to a press during the parallel green that arrives after cross demand already exists: whether it is served immediately (extending green) or deferred to the next green. This is recorded as an assumption.
- Shows how a pending cross-road ped request counts as opposing demand, and that the 'ped group busy' flag blocks green termination.
- Timing diagrams cover: a press during the opposing green; a mid-green press while resting; cross demand arriving during WALK; a press during flashing DON'T WALK (re-latched); and the flash waveform.

## S7. Define reset, power-up and start-up clearance sequence

**Goal:** Fill in the TBD power-up behaviour: reset style, the initial lamp state, a safe start-up sequence before the first green, and the handling of requests pending at reset.

**Feeds:** Clocking & Reset, Control Logic · **Depends on:** S3, S4

**Spec evidence:**
- [P4] "Exact timing and what to do on power-up TBD"
- [P3] "The FPGA board runs at 50 MHz."

**Decisions:**
- D7 Power-up / reset signal sequence: **While reset is asserted and immediately after, show all vehicle heads red and all pedestrian heads solid DON'T WALK. Hold for a parameterized start-up all-red (e.g. 5 s), then enter NS green with min green. Clear pedestrian latches and timers on reset.** (default, medium impact, medium confidence)
  - options: All-red (all pedestrian DON'T WALK) for a start-up clearance interval, then NS green / Flashing red on all approaches for N seconds, then all-red, then first green / Start directly in NS green
  - All-red start is the safe, conventional choice when the prior state is unknown. Flashing red is an alternative some agencies use.
- D8 Reset style: **Accept an external active-low reset, asserted asynchronously and released synchronously to the 50 MHz clock. Combine it with a small power-on reset counter so the design comes up in the safe start-up state after configuration.** (default, low impact, medium confidence)
  - options: External reset button, asynchronously asserted and synchronously deasserted, plus power-on reset from the FPGA configuration/initial values / Fully synchronous reset / No external reset, rely on FPGA init values only
  - Asynchronous assertion guarantees lamps go safe immediately. Synchronous release avoids recovery hazards. The power-on counter covers boards without a reset button.

**Done when:**
- Reset section states the polarity, the synchronizer and the reset value of every state-holding block (FSM, ped sub-FSMs, timers, latches, debounce, prescaler).
- Start-up sequence is drawn as states in the FSM, with the start-up interval as a parameter.
- Confirms a single 50 MHz clock domain with no derived clocks.

## S8. Add conflict monitoring and enumerate traffic/pedestrian corner cases

**Goal:** Make the safety invariants enforceable in hardware: no conflicting vehicle greens, and no WALK against conflicting traffic. List the edge cases the control logic must handle deterministically.

**Feeds:** Corner Cases & Error Handling, Block Diagram · **Depends on:** S4, S5, S6, S7

**Spec evidence:**
- [P2] "with the usual safety gap where both are red."
- [P2] "longer, but not forever."
- [P3] "Sensors and buttons come from the field wiring."

**Decisions:**
- D11 Hardware conflict monitor / fail-safe: **Add an independent conflict monitor on the registered lamp outputs. It checks for: NS and EW both non-red; ns_walk without NS green; ew_walk without EW green; yellow while a walk is active; and illegal states. Any of these latches a fault that overrides the outputs to flashing red on all vehicle heads and DON'T WALK on all pedestrian heads, until reset. The FSM default case also routes to all-red.** (default, medium impact, medium confidence)
  - options: Independent combinational/registered monitor that detects conflicting greens/yellows, illegal FSM states or WALK vs conflicting green, and latches a fail-safe flashing-red mode until reset / Rely on FSM correctness plus default-case recovery to all-red / No monitor
  - Real controllers have a conflict monitor. It is cheap in an FPGA and guards against SEUs or design bugs.

**Done when:**
- Fault conditions and the fail-safe output override are defined, along with any fault indicator output.
- Corner-case list covers: simultaneous calls on both roads; car sensor stuck high (handled by max-out); car sensor stuck low (pedestrian or other road still served); button held continuously; a press during flashing DON'T WALK (latched for next green); a ped request on both roads at once; cross demand arriving mid-WALK while resting; max-out during WALK (green held past GREEN_MAX); demand arriving during yellow or all-red; reset mid-phase.
- Each corner case states the expected deterministic behaviour.

## S9. Draw the block diagram and end-to-end timing diagrams

**Goal:** Assemble the blocks into one block diagram: input conditioning for the 4 raw inputs, prescaler/tick, flash generator, 2 ped request latches, phase timers, main FSM, 2 pedestrian sub-FSMs, output registers and conflict monitor. Produce timing diagrams for representative full cycles.

**Feeds:** Block Diagram, Timing & Pipeline, Datapath · **Depends on:** S2, S3, S4, S5, S6, S7, S8

**Spec evidence:**
- [P1] "Traffic light controller for a 4-way intersection (north-south road crossing east-west road)."
- [P2] "Cycle NS and EW: green, yellow, then red, with the usual safety gap where both are red."

**Done when:**
- Block diagram shows every block and named signal from car_*_raw/ped_btn_*_raw to the lamp outputs, with all flops in the 50 MHz domain.
- Input-to-lamp latency is stated in cycles: synchronizer + debounce + FSM + output register.
- At least three full-cycle timing diagrams: no-demand rest with a mid-green walk; actuated extension with max-out; and a pedestrian-served cycle where clearance holds green past GREEN_MAX.

## S10. Plan verification with time-scaled parameters, safety assertions and scenario tests

**Goal:** Define how to verify seconds-scale behaviour in simulation and what properties and scenarios prove the controller safe and correct.

**Feeds:** Verification Plan · **Depends on:** S9

**Spec evidence:**
- [P2] "Yellow about 4 seconds. Green at least 10 seconds."
- [P2] "If nobody is waiting on the other road there's no need to switch."
- [P2] "Pedestrians get a WALK light, then a flashing"

**Done when:**
- States that the testbench overrides prescaler/tick parameters so that one 'second' takes only a few cycles.
- Assertions cover:
- never both roads non-red;
- all-red of at least ALL_RED ticks between greens;
- yellow exactly YELLOW ticks;
- green at least MIN_GREEN;
- green at most MAX_GREEN + WALK + FDW when opposing demand exists;
- ns_walk only during NS green and ew_walk only during EW green;
- yellow never starts while that road's ped group is in WALK or FLASH_DW;
- every pedestrian request served within a bounded time;
- a press during clearance is served on the next green of that road.
- Scenario list includes rest-in-green, a mid-green walk while resting, continuous traffic max-out, gap-out, a pedestrian-only call on the cross road, max-out during WALK, button bounce/glitch, reset mid-cycle, a forced conflict that triggers the fail-safe, and randomized sensor/button stimulus.
- Coverage goals are listed for FSM states, transitions and pedestrian sub-states of both groups.

## S11. Record the filled-in TBDs and remaining open questions

**Goal:** Make every value and behaviour the spec left open explicit, with its default and the question still pending for the author. Record the answers already received.

**Feeds:** Assumptions & Open Questions · **Depends on:** S2, S3, S4, S5, S6, S7, S8

**Spec evidence:**
- [P4] "Exact timing and what to do on power-up TBD"
- [P2] "Yellow about 4 seconds. Green at least 10 seconds."

**Done when:**
- Lists every remaining defaulted decision (D1, D2, D5, D6, D7, D8, D9, D10, D11) with its default and open question. Records D3 and D4 as settled by the user's answers.
- Lists all invented timing values (all-red, max green, gap, WALK, flashing DON'T WALK, start-up, debounce, flash rate) as assumptions.
- Records the assumption chosen for a press during the parallel green when cross demand already exists.
- Notes the out-of-scope items: no protected left-turn phases, no exclusive pedestrian phase, no runtime configuration interface, no preemption (emergency/rail).

## Assumptions (defaults not confirmed by the user)

- D2 Conditioning of field inputs (sensors and buttons): Every sensor and button gets a 2-flop synchronizer and a counter-based debounce/glitch filter. Button presses are then latched into a pending pedestrian request that clears only when served. (medium impact, high confidence)
- D1 Timebase structure: One free-running prescaler generates a single-cycle tick enable (100 ms resolution) in the 50 MHz domain. All phase timers and the flash generator count ticks. There is no derived clock. (medium impact, high confidence)
- D9 Timing programmability: Use compile-time Verilog parameters in tick units. Suggested defaults: yellow 4 s, min green 10 s, all-red 2 s, gap 3 s, max green 40 s, WALK 7 s, flashing DON'T WALK 10 s, flash rate 1 Hz. (medium impact, high confidence)
- D6 Behaviour with no opposing demand: After minimum green, the current road rests in green indefinitely until an opposing call exists. An opposing call is the opposing sensor or the opposing latched pedestrian request. Max-green timing only applies while an opposing call is present. (medium impact, medium confidence)
- D5 Green extension algorithm: Use the standard actuated scheme. Minimum green is always served. After that, green continues while detections on the green road keep restarting a gap timer (passage time). A termination request is raised on gap expiry (gap-out) or on max-green expiry (max-out); the max-green timer starts when an opposing call arrives. Either request requires an opposing call to exist. Yellow begins only once any parallel pedestrian clearance has also completed. (medium impact, medium confidence)
- D10 Lamp output structure and flash generation: Each lamp, including ns_walk/ns_dont_walk/ew_walk/ew_dont_walk, gets an individual registered active-high output. Flashing DON'T WALK is generated inside the FPGA by gating the dont_walk output with an internal ~1 Hz, 50% duty flash signal derived from the tick. (medium impact, medium confidence)
- D7 Power-up / reset signal sequence: While reset is asserted and immediately after, show all vehicle heads red and all pedestrian heads solid DON'T WALK. Hold for a parameterized start-up all-red (e.g. 5 s), then enter NS green with min green. Clear pedestrian latches and timers on reset. (medium impact, medium confidence)
- D8 Reset style: Accept an external active-low reset, asserted asynchronously and released synchronously to the 50 MHz clock. Combine it with a small power-on reset counter so the design comes up in the safe start-up state after configuration. (low impact, medium confidence)
- D11 Hardware conflict monitor / fail-safe: Add an independent conflict monitor on the registered lamp outputs. It checks for: NS and EW both non-red; ns_walk without NS green; ew_walk without EW green; yellow while a walk is active; and illegal states. Any of these latches a fault that overrides the outputs to flashing red on all vehicle heads and DON'T WALK on all pedestrian heads, until reset. The FSM default case also routes to all-red. (medium impact, medium confidence)
