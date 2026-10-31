# MA plan: 02_debounce_edge_detect

## S1. Frame the 4-channel button conditioner: sync -> invert -> debounce -> edge-detect

**Goal:** Write the Overview: a per-button pipeline that turns raw active-low, asynchronous, bouncing pins into a synchronized active-high debounced level plus one-clock press and release pulses. State that the block replaces software debouncing for the kiosk control panel.

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P2] "push buttons wired straight to FPGA pins"
- [P2] "the firmware sees multiple presses every"
- [P3] "for each button, a clean level signal that only changes after the button has"
- [P4] "it would be great to get a one-clock pulse for each of those events."

**Decisions:**
- D1 Channel count: hard-wired 4 vs parameterized N: **Parameter NUM_BUTTONS with default 4. Each channel is an identical, independent instance of the per-button logic.** (default, low impact, high confidence)
  - options: Fixed 4 channels / Parameter NUM_BUTTONS, default 4
  - The spec says four buttons. A width parameter costs nothing and lets the same block serve later panel revisions.

**Done when:**
- The Overview names the four stages in order: synchronizer, polarity inversion, debounce filter, edge detector.
- The Overview states the three outputs per button: level, press pulse, release pulse.
- The Overview states the scope: no interrupt or bus interface, and outputs are consumed in the same clock domain.

## S2. Build-time parameters for clock frequency and debounce time, and the derived count

**Goal:** Define the parameters that let the user retarget from 50 MHz to 100 MHz and change the ~10 ms window without editing RTL. Define the derived terminal count and counter width.

**Feeds:** Parameters · **Depends on:** S1

**Spec evidence:**
- [P3] "around 10 ms is what our hardware guy suggests"
- [P3] "able to change that when we build the bitstream"
- [P3] "The board clock is 50 MHz today, but the next"
- [P3] "revision will be 100 MHz, so please don't hard-code it."

**Decisions:**
- D2 How debounce time is configured: **Two Verilog parameters: clock frequency in Hz and debounce time. The terminal count is CLK_FREQ_HZ*time/scale, computed at elaboration, with counter width from $clog2. Defaults are 50_000_000 Hz and 10 ms.** (decided)
  - options: CLK_FREQ_HZ + DEBOUNCE_MS parameters, count derived / CLK_FREQ_HZ + DEBOUNCE_US parameters, count derived / Single DEBOUNCE_CYCLES parameter computed by the integrator
  - The spec explicitly asks for a build-time debounce time and for the clock not to be hard-coded.
- D3 Unit of the debounce-time parameter: **Microseconds (DEBOUNCE_US, default 10000). This gives sub-ms tuning while the derived count stays an exact integer at 50 and 100 MHz.** (default, low impact, medium confidence)
  - options: Milliseconds (integer) / Microseconds (integer)
  - The spec only says 'around 10 ms'. Microseconds allow values like 5.5 ms without fractional parameters.

**Done when:**
- The parameter table lists name, default, unit, and legal range for clock frequency, debounce time, and button count.
- The derived terminal-count formula is written out, with worked values for 50 MHz and 100 MHz at 10 ms (500000 and 1000000).
- Counter width is derived with $clog2 and is shown to be 19 or 20 bits for those cases.
- Integer-overflow risk in the elaboration-time multiply is addressed, e.g. by ordering the division or using 64-bit localparam math.

## S3. Port list with active-low raw inputs and active-high conditioned outputs

**Goal:** Define the external interface. Inputs are the clock, the active-low reset, and the NUM_BUTTONS-wide raw active-low pin vector. Outputs are the debounced level, press pulse, and release pulse vectors.

**Feeds:** Interface · **Depends on:** S2

**Spec evidence:**
- [P5] "The buttons are active-low on the board (pressed = 0), but we'd prefer the block's output to be"
- [P5] "There's a global reset coming from our reset controller, active-low."
- [P4] "the moment a button is pressed and the moment it's"

**Decisions:**
- D4 Where polarity inversion happens: **Invert immediately after the synchronizer. All internal state and every output use 1 = pressed.** (decided)
  - options: Invert after the synchronizer, so all internal state is 1 = pressed / Keep internal state active-low and invert only at the outputs
  - The spec requires outputs where 1 = pressed. Inverting early keeps the debounce and edge logic in one polarity and puts no logic between the pin and the first sync flop.
- D5 Output bundle shape: **Three separate NUM_BUTTONS-wide output vectors: debounced level, press pulse, release pulse.** (default, low impact, high confidence)
  - options: Three NUM_BUTTONS-wide vectors (level, pressed pulse, released pulse) / Single level vector plus combined event vector with type bit
  - The spec asks for a level plus a pulse on press and a pulse on release. Separate vectors map directly onto those requests and onto firmware register bits.

**Done when:**
- The port table gives name, direction, width, polarity, and clock domain for every port.
- The raw inputs are explicitly marked asynchronous and active-low.
- All outputs are stated as synchronous to clk and active-high, with each output's registered or combinational status stated.

## S4. Metastability-safe input synchronizer per button

**Goal:** Specify the multi-flop synchronizer on each raw pin and its MTBF rationale. Rule out any logic before the first flop and any fan-out from the first stage.

**Feeds:** Datapath, Block Diagram · **Depends on:** S3

**Spec evidence:**
- [P6] "these pins are obviously not synchronized to anything"
- [P6] "Our last vendor's design had metastability problems."

**Decisions:**
- D6 Synchronizer depth: **Parameter SYNC_STAGES with default 2 and minimum 2. The flops carry ASYNC_REG/keep attributes so they are placed adjacent.** (default, low impact, high confidence)
  - options: 2-flop / 3-flop / Parameter SYNC_STAGES default 2
  - Two flops are standard at 50-100 MHz, and slow mechanical inputs give a large MTBF. The parameter lets the user add a third stage, given the vendor's previous metastability history.

**Done when:**
- The synchronizer chain is drawn with no combinational logic before stage 1.
- The MA notes the synthesis attributes (ASYNC_REG or equivalent) and a timing-constraint note (false path or set_max_delay on pin-to-first-flop).
- The MA states that only the last sync stage feeds the inverter and the debouncer.
- The synchronizer reset value corresponds to 'not pressed' (raw = 1).

## S5. Debounce filter: stability counter and debounced state register

**Goal:** Define the per-channel algorithm. The debounced level changes only after the synchronized, inverted input has differed from the current level continuously for the configured time. Decide the counter organization.

**Feeds:** Datapath, Control Logic, Block Diagram · **Depends on:** S2, S4

**Spec evidence:**
- [P3] "for each button, a clean level signal that only changes after the button has"
- [P3] "been stable for a while, around 10 ms is what our hardware guy suggests"

**Decisions:**
- D7 Debounce algorithm: **Continuous stable-window. While the synced input equals the current debounced state the counter is held at 0. While they differ the counter increments. On reaching the terminal count the state flips and the counter clears.** (default, medium impact, high confidence)
  - options: Restart counter on any mismatch; flip state when counter hits terminal count (continuous stable-window) / Periodic sampling at debounce interval (sample-and-compare) / Saturating up/down integrator
  - This matches 'only changes after the button has been stable for a while' exactly. It is deterministic, and its latency bound is easy to verify.
- D8 Counter organization across channels: **Independent full-width counter per button, counting clock cycles.** (default, medium impact, medium confidence)
  - options: Independent full-width counter per button / Shared prescaler tick (e.g. 1 kHz or 1 MHz) plus small per-button counters
  - This gives exact timing and the simplest verification. At 4 channels × ~20 bits the area is trivial. A shared prescaler adds up to one tick of timing jitter and couples the channels.

**Done when:**
- The per-channel datapath is drawn: sync output -> inverter -> comparator vs state -> counter -> terminal-count compare -> state register.
- The counter update rules are given as a truth table (match, mismatch, terminal).
- The MA states the counter never wraps and its width covers the terminal count.
- The block diagram shows NUM_BUTTONS replicated channels sharing only clk and reset.

## S6. Press/release one-clock pulse generation from debounced state

**Goal:** Derive the press and release pulses from transitions of the debounced state so each physical press yields exactly one press pulse and one release pulse, each exactly one clock wide.

**Feeds:** Datapath, Control Logic · **Depends on:** S5

**Spec evidence:**
- [P4] "The firmware also really only cares about the moment a button is pressed and the moment it's"
- [P4] "it would be great to get a one-clock pulse for each of those events."

**Decisions:**
- D9 Pulse timing relative to level change: **Registered pulses set in the same clock edge that flips the debounced level, i.e. press_q <= flip & ~state and release_q <= flip & state. This keeps level and pulses aligned and glitch-free.** (default, low impact, medium confidence)
  - options: Registered pulse asserted in the same cycle the debounced level register changes / Pulse from delayed-copy edge detect (one cycle after level changes) / Combinational pulse from the terminal-count condition
  - Firmware sees the level and the event coincide. All outputs come straight from flops.

**Done when:**
- The pulse equations are written in terms of the flip condition and the current state.
- The MA guarantees a pulse width of exactly 1 cycle and no back-to-back pulses on one channel within one debounce time.
- The MA states that press and release can never be asserted simultaneously on the same channel.

## S7. End-to-end latency and timing budget at 50/100 MHz

**Goal:** Document the cycle-accurate latency from a stable raw pin change to the level and pulse outputs, and the timing-critical path (counter increment and compare).

**Feeds:** Timing & Pipeline · **Depends on:** S4, S5, S6

**Spec evidence:**
- [P3] "revision will be 100 MHz, so please don't hard-code it."
- [P3] "been stable for a while, around 10 ms is what our hardware guy suggests"

**Done when:**
- Latency is expressed as SYNC_STAGES + terminal count + register stages, with numeric values at 50 and 100 MHz.
- A timing diagram shows a bouncing press, the counter restarts, the level change, and the press pulse.
- The MA confirms that the ~20-bit increment-and-compare closes at 100 MHz with margin and needs no pipelining.

## S8. Reset strategy for the active-low global reset and power-up state

**Goal:** Define how rst_n is applied to the sync flops, counters, state, and pulse registers, and what outputs look like coming out of reset.

**Feeds:** Clocking & Reset · **Depends on:** S3, S5

**Spec evidence:**
- [P5] "There's a global reset coming from our reset controller, active-low."

**Decisions:**
- D10 Reset style: **Asynchronous active-low reset on all flops. Deassertion is assumed to be already synchronized to clk by the external reset controller, and no internal reset synchronizer is added.** (default, medium impact, medium confidence)
  - options: Asynchronous assert, synchronous deassert assumed from reset controller / Fully synchronous reset / Asynchronous reset with internal reset synchronizer in this block
  - A dedicated reset controller usually provides synchronized release. Async assert guarantees defined outputs even without a running clock.
- D11 Debounced state after reset when a button is held: **Reset all debounced levels to 0 (released) and sync flops to the idle pin value. A button held through reset is reported as a normal press, with a pulse, one debounce time after reset release.** (default, low impact, medium confidence)
  - options: Reset to 'released'; a held button produces a press pulse after one debounce time / Initialize from the input after reset, with no pulse for buttons held at reset
  - This is simple and deterministic, and firmware learns of held buttons through the normal path. Suppressing the pulse would need extra startup logic.

**Done when:**
- The MA lists the reset value of every register class (sync, counter, state, pulse).
- The single clock domain is stated, with the raw pins as the only asynchronous inputs.
- The behaviour of a button held at reset is documented.
- The MA states that outputs are 0 during reset.

## S9. Corner cases: sub-threshold bounce, glitches, extreme parameter values

**Goal:** Enumerate the abnormal input and parameter conditions and the guaranteed behaviour for each.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S5, S6, S8

**Spec evidence:**
- [P2] "the firmware sees multiple presses every"
- [P3] "able to change that when we build the bitstream"

**Done when:**
- The MA covers bounce shorter than the debounce time (no output change).
- The MA covers a press shorter than the debounce time (ignored).
- The MA covers continuous chatter, where the output never changes and the documented behaviour is accepted.
- The MA covers simultaneous presses on all channels, which are independent.
- The MA covers a debounce time that rounds to 0 or 1 cycle and a too-large count, with elaboration-time checks or $error.
- The MA states that no error outputs exist, with the reason.

## S10. Verification plan with bounce-model stimulus and scaled-down debounce time

**Goal:** Define the testbench strategy, checkers, and coverage. Use a small debounce-time parameter for simulation speed, plus one run at the real 50/100 MHz parameters.

**Feeds:** Verification Plan · **Depends on:** S7, S9

**Spec evidence:**
- [P3] "The board clock is 50 MHz today, but the next"
- [P6] "Our last vendor's design had metastability problems."
- [P4] "it would be great to get a one-clock pulse for each of those events."

**Done when:**
- The plan includes a randomized bounce generator (burst lengths below and above threshold, async to clk).
- A reference model or scoreboard predicts the level and the pulses.
- Assertions cover: pulse width = 1; press and release never coincide; level changes only after N stable cycles; one press pulse per level rise.
- Parameter sweeps cover both clock frequencies and multiple debounce times.
- A CDC/lint check of the synchronizer is listed.
- Reset-with-button-held tests are listed.

## S11. Record assumptions and open questions for Priya

**Goal:** Collect every defaulted decision and assumption, such as same-domain consumers, synchronized reset release, and no interrupt aggregation, into the open-questions section.

**Feeds:** Assumptions & Open Questions · **Depends on:** S2, S3, S4, S5, S6, S8

**Spec evidence:**
- [P3] "around 10 ms is what our hardware guy suggests"
- [P5] "There's a global reset coming from our reset controller, active-low."

**Done when:**
- Each defaulted decision (D1, D3, D5–D11) appears with its chosen default and the question text.
- The assumptions list states that the consumer logic is in the same clk domain.
- The assumptions list states that no pull-ups or analog filtering are expected in the block.

## Assumptions (defaults not confirmed by the user)

- D1 Channel count: hard-wired 4 vs parameterized N: Parameter NUM_BUTTONS with default 4. Each channel is an identical, independent instance of the per-button logic. (low impact, high confidence)
- D3 Unit of the debounce-time parameter: Microseconds (DEBOUNCE_US, default 10000). This gives sub-ms tuning while the derived count stays an exact integer at 50 and 100 MHz. (low impact, medium confidence)
- D5 Output bundle shape: Three separate NUM_BUTTONS-wide output vectors: debounced level, press pulse, release pulse. (low impact, high confidence)
- D6 Synchronizer depth: Parameter SYNC_STAGES with default 2 and minimum 2. The flops carry ASYNC_REG/keep attributes so they are placed adjacent. (low impact, high confidence)
- D7 Debounce algorithm: Continuous stable-window. While the synced input equals the current debounced state the counter is held at 0. While they differ the counter increments. On reaching the terminal count the state flips and the counter clears. (medium impact, high confidence)
- D8 Counter organization across channels: Independent full-width counter per button, counting clock cycles. (medium impact, medium confidence)
- D9 Pulse timing relative to level change: Registered pulses set in the same clock edge that flips the debounced level, i.e. press_q <= flip & ~state and release_q <= flip & state. This keeps level and pulses aligned and glitch-free. (low impact, medium confidence)
- D10 Reset style: Asynchronous active-low reset on all flops. Deassertion is assumed to be already synchronized to clk by the external reset controller, and no internal reset synchronizer is added. (medium impact, medium confidence)
- D11 Debounced state after reset when a button is held: Reset all debounced levels to 0 (released) and sync flops to the idle pin value. A button held through reset is reported as a normal press, with a pulse, one debounce time after reset release. (low impact, medium confidence)
