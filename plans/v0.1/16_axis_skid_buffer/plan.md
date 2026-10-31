# MA plan: 16_axis_skid_buffer

## S1. Capture purpose and hard requirements of the packet-engine to egress-shaper AXI-S register slice

**Goal:** Write the Overview: state that the block is a fully registered AXI4-Stream slice placed between the packet engine (upstream master) and the egress shaper (downstream slave). It exists to close timing on the forward path (tvalid/tdata) and the backward path (tready). List the three non-negotiables: no combinational path from input to output, 1 beat/clock sustained throughput, and minimal area.

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P1] "need an axi-stream register slice to break timing between the packet engine and the"
- [P1] "we're failing timing on both tvalid/tdata and on tready going back up."
- [P2] "must register everything in both directions, no comb path in -> out"
- [P2] "must not lose throughput, 1 beat per clock when nobody stalls"
- [P3] "that's it, keep it small."

**Decisions:**
- D1 Slice architecture that registers both forward and backward paths at full throughput: **Two-register skid buffer: a main register drives m_axis_* outputs, and a single skid register catches the in-flight beat when downstream stalls. s_tready is driven from a flop.** (default, high impact, high confidence)
  - options: Two-register skid buffer (main output register + skid register, registered s_tready) / 2-entry FIFO with pointers / Cascade of a forward-only slice and a backward-only slice
  - This is the minimum storage that registers tvalid/tdata and tready together while sustaining 1 beat/clock: two beat-sized registers, with no pointer logic. It fits 'keep it small'.

**Done when:**
- Overview names upstream (packet engine) and downstream (egress shaper) roles.
- Overview lists the three requirements: fully registered, 1 beat/clk, small.
- Overview states the chosen architecture (skid buffer) in one sentence and gives its storage cost (2 beats).

## S2. Define slave/master AXI-Stream ports with tdata, tkeep, tlast and an optional tuser hook

**Goal:** Specify the complete port list: clock, reset, s_axis_{tvalid,tready,tdata,tkeep,tlast[,tuser]} and m_axis_{tvalid,tready,tdata,tkeep,tlast[,tuser]}. Give direction, width expression and which outputs are flop-driven.

**Feeds:** Interface · **Depends on:** S1

**Spec evidence:**
- [P2] "data is 64 bit, with tkeep and tlast. maybe tuser later"
- [P2] "must register everything in both directions, no comb path in -> out"

**Decisions:**
- D2 tuser support: **Include s/m_axis_tuser ports sized by USER_WIDTH, with a USER_EN parameter (default 0). When disabled, the tuser storage is not generated and the output is tied to 0.** (default, medium impact, medium confidence)
  - options: Omit tuser entirely now / Include tuser with USER_WIDTH parameter, gated by a USER_EN/width>0 option / Always include tuser, minimum width 1
  - 'maybe tuser later' suggests adding the port now, so the interface does not change at a later integration. Gating keeps area at zero when tuser is unused.
- D3 Other AXI-Stream sideband signals (tstrb, tid, tdest, twakeup): **Omit tstrb/tid/tdest. Only tdata, tkeep, tlast and the optional tuser are carried.** (default, low impact, high confidence)
  - options: Omit / Include as optional parameters
  - The spec names only tkeep and tlast (and maybe tuser), and asks to keep it small.
- D4 Output driving: all m_axis_* and s_axis_tready directly from flops: **m_axis_tvalid, m_axis_tdata/tkeep/tlast/tuser and s_axis_tready are each driven directly by a flop Q, with no logic after the register. All muxing sits on the register D inputs.** (decided)
  - options: All outputs straight from flops (mux only in front of registers) / Output mux selecting between main and skid registers
  - The spec requires 'no comb path in -> out' and asks to fix timing on both directions. An output mux would put logic after the flops on the timing-critical edge.

**Done when:**
- Port table lists every signal with direction, width formula and description.
- Every output is marked as flop-driven.
- Default tkeep width is shown as DATA_WIDTH/8 = 8 for 64-bit data.
- tuser presence and tie-off behaviour are documented.

## S3. Parameterize data width and derive tkeep/tuser widths

**Goal:** Define the parameter set: DATA_WIDTH (default 64), the derived KEEP_WIDTH, USER_EN and USER_WIDTH. State the legal values and how the packed payload width (data+keep+last+user) is computed, so the datapath stores one vector.

**Feeds:** Parameters · **Depends on:** S2

**Spec evidence:**
- [P2] "should be reusable so make the width a parameter"
- [P2] "data is 64 bit, with tkeep and tlast. maybe tuser later"

**Decisions:**
- D5 tkeep width derivation and DATA_WIDTH constraint: **KEEP_WIDTH = DATA_WIDTH/8 as a localparam, with an elaboration-time check that DATA_WIDTH % 8 == 0.** (default, low impact, high confidence)
  - options: KEEP_WIDTH derived as DATA_WIDTH/8, DATA_WIDTH must be a multiple of 8 / KEEP_WIDTH as an independent parameter
  - This matches AXI-Stream byte-qualifier semantics and removes a way to misconfigure the block.
- D6 Configurable slice modes (bypass / forward-only / backward-only): **Single fixed fully-registered mode with no mode parameter.** (default, low impact, medium confidence)
  - options: Single fixed full-registered mode / REG_MODE parameter selecting bypass/forward/backward/full
  - The spec says 'keep it small' and asks only for full registration. Extra modes add verification surface.

**Done when:**
- Parameter table lists name, default, legal range and derived localparams.
- Packed payload width formula is written out.
- Elaboration checks are listed (DATA_WIDTH%8, USER_WIDTH>=1 when enabled).

## S4. Draw the skid-buffer block diagram: main register, skid register, load mux and ready flop

**Goal:** Produce the block diagram. Show input payload going to both the skid register and the main-register input mux, the mux selecting skid vs. input, the main register driving m_axis_*, and the control block owning m_tvalid, skid_valid and the s_tready flop.

**Feeds:** Block Diagram · **Depends on:** S1, S3

**Spec evidence:**
- [P2] "must register everything in both directions, no comb path in -> out"
- [P1] "we're failing timing on both tvalid/tdata and on tready going back up."

**Done when:**
- Diagram shows exactly two payload registers and one 2:1 mux in front of the main register.
- Diagram shows that no wire runs from any s_axis_* input to any m_axis_* output, or from m_axis_tready to s_axis_tready, without passing through a flop.
- Each block is labelled with the signals it owns.

## S5. Specify main/skid payload register load and select conditions

**Goal:** Define the datapath enables. The main register loads when it is empty or being drained (m_tready & m_tvalid); it takes the skid contents if skid is valid, otherwise the input beat. The skid register loads the input beat when an input handshake occurs while the main register is held. tdata, tkeep, tlast and tuser are stored as one packed vector.

**Feeds:** Datapath · **Depends on:** S4

**Spec evidence:**
- [P2] "must not lose throughput, 1 beat per clock when nobody stalls"
- [P2] "data is 64 bit, with tkeep and tlast. maybe tuser later"

**Decisions:**
- D7 Payload register reset policy: **Only the control flops (m_tvalid, skid_valid, s_tready) are reset. Payload registers have no reset.** (default, low impact, medium confidence)
  - options: Reset only valid/ready control flops; payload flops unreset / Reset all payload flops too
  - This saves area and reset fanout on 64+ bit registers, which fits 'keep it small'. The payload is don't-care while tvalid is low.

**Done when:**
- Load-enable equations are given for the main and skid registers.
- Mux select equation is given.
- The writeup explains why the packed vector keeps tkeep/tlast/tuser aligned with tdata.

## S6. Define control state (EMPTY / ONE / FULL) and registered s_tready generation

**Goal:** Specify the control logic as a 3-state occupancy machine derived from {m_tvalid, skid_valid}. Give next-state transitions for each combination of input handshake and output handshake. Derive s_tready_next = !skid_valid_next, so s_tready is registered and asserts whenever the skid register will be free next cycle.

**Feeds:** Control Logic · **Depends on:** S5

**Spec evidence:**
- [P1] "we're failing timing on both tvalid/tdata and on tready going back up."
- [P2] "must register everything in both directions, no comb path in -> out"

**Decisions:**
- D8 AXI-Stream protocol obligations on the master side: **Strict AXI4-Stream compliance. Once m_tvalid is asserted, it and the payload stay stable until m_tready is seen. m_tvalid never depends combinationally on m_tready.** (decided)
  - options: Strict AXI4-Stream: m_tvalid independent of m_tready, payload held stable until handshake / Relaxed
  - An 'axi-stream register slice' implies protocol compliance. The fully registered outputs make this automatic, but it must be stated as a design invariant.

**Done when:**
- The state transition table covers all 3 states x {in_hs, out_hs} combinations.
- An unreachable FULL+input-accept case is shown to be impossible because s_tready is 0 when FULL.
- The s_tready, m_tvalid and skid_valid next-value equations are written.

## S7. Document 1-cycle latency, sustained 1 beat/clk and stall/recovery cycle behaviour

**Goal:** Write the Timing & Pipeline section. Cover the forward latency of one clock, the steady-state throughput of 1 beat/clock with no stalls, and the timing of s_tready deassertion one cycle after a downstream stall begins (absorbed by the skid register). Include waveforms for streaming, downstream stall and release, and upstream bubbles.

**Feeds:** Timing & Pipeline · **Depends on:** S6

**Spec evidence:**
- [P2] "must not lose throughput, 1 beat per clock when nobody stalls"
- [P1] "we're failing timing on both tvalid/tdata and on tready going back up."

**Decisions:**
- D9 Forward latency: **1-cycle latency. The skid register is used only on stall, so the beat goes from input directly to the main register.** (default, low impact, high confidence)
  - options: 1 cycle (input beat appears on m_axis next clock when empty) / Always 2 cycles (beat always passes through both registers)
  - This is the minimum latency that meets the full-registration requirement. A fixed 2-stage pipe would add latency with no timing benefit.

**Done when:**
- Waveforms or cycle tables cover back-to-back streaming, a single-cycle downstream stall, a multi-cycle stall, and release.
- A statement shows that throughput returns to 1 beat/clk immediately after the stall releases.
- The critical paths on both sides of the slice are shown to start or end at a flop.

## S8. Define single-clock operation and AXI-style reset behaviour

**Goal:** Specify one clock (aclk) with no CDC. Specify the reset style and polarity, the values of m_tvalid and s_tready during and after reset, and the first cycle s_tready may assert.

**Feeds:** Clocking & Reset · **Depends on:** S6

**Spec evidence:**
- [P1] "to break timing between the packet engine and the"

**Decisions:**
- D10 Clock domains: **Single clock (aclk) shared by packet engine and egress shaper. No CDC.** (default, high impact, high confidence)
  - options: Single clock domain / Async CDC slice
  - The spec describes a timing-closure slice, not a domain crossing.
- D11 Reset style and polarity: **Synchronous active-low aresetn. During reset, m_tvalid=0 and s_tready=0. s_tready asserts the first cycle after reset deasserts.** (default, medium impact, medium confidence)
  - options: Synchronous active-low aresetn (AXI convention) / Asynchronous active-low / Synchronous active-high
  - This follows the AXI convention. Synchronous reset keeps the control flops simple and avoids reset-recovery timing issues on a timing-critical block.

**Done when:**
- The reset table lists the value of every control flop and output during reset.
- The cycle in which s_tready first asserts after reset release is stated.
- The single-clock assumption is stated explicitly.

## S9. Enumerate stall, bubble and reset corner cases for the skid buffer

**Goal:** List the corner cases and the required behaviour for each: simultaneous input and output handshakes while FULL→ONE; m_tready toggling every cycle; upstream tvalid bubbles; tlast on a stalled beat; a beat captured in skid at the same cycle the stall releases; reset asserted mid-packet (in-flight beats dropped); and m_tready asserted with nothing valid.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S6, S7, S8

**Spec evidence:**
- [P2] "must not lose throughput, 1 beat per clock when nobody stalls"
- [P2] "data is 64 bit, with tkeep and tlast. maybe tuser later"

**Done when:**
- Each corner case has expected behaviour stated in terms of the state transitions.
- Ordering is stated to be preserved in every case, with no beat duplicated or dropped.
- Behaviour on mid-packet reset is documented (no error signalling; the block has no error outputs).

## S10. Plan verification for ordering, throughput, protocol compliance and no comb paths

**Goal:** Define the verification plan. Use a randomized stream testbench with random upstream valid and downstream ready, plus a scoreboard comparing tdata/tkeep/tlast/tuser in order. Add SVA covering AXI-S stability, no data loss and s_tready being registered. Add a throughput check showing 100% beats/clk when both sides are always ready, a structural or lint check for no comb input→output path, and parameter sweeps (e.g., 8, 64, 512 bits; tuser on and off).

**Feeds:** Verification Plan · **Depends on:** S9

**Spec evidence:**
- [P2] "must register everything in both directions, no comb path in -> out"
- [P2] "must not lose throughput, 1 beat per clock when nobody stalls"
- [P2] "should be reusable so make the width a parameter"

**Done when:**
- The scoreboard and stimulus profiles are listed (full-rate, random stalls, random bubbles, alternating ready).
- Assertions are listed: payload stable while m_tvalid & !m_tready; m_tvalid not dropped without a handshake; no overflow when s_tready=0.
- A throughput measurement criterion is given (N beats in N+1 cycles with no stalls).
- Coverage points are listed: all occupancy states and transitions, tlast in skid, reset during traffic.
- The method for proving no combinational in→out path is specified (timing report or formal/lint).

## S11. Record defaulted choices and open questions for the spec author

**Goal:** Collect every defaulted decision (architecture, tuser handling, sidebands, reset style, clocking, payload reset, modes, latency) into the Assumptions & Open Questions section, each with its question. Note that 'keep it small' was interpreted as 2 payload registers and no extra modes.

**Feeds:** Assumptions & Open Questions · **Depends on:** S2, S3, S5, S7, S8

**Spec evidence:**
- [P3] "that's it, keep it small."
- [P2] "data is 64 bit, with tkeep and tlast. maybe tuser later"

**Done when:**
- Every defaulted decision (D1-D3, D5-D7, D9-D11) appears with its chosen default and its question.
- The area estimate (flop count as a function of DATA_WIDTH/USER_WIDTH) is stated as an assumption to confirm against 'keep it small'.

## Assumptions (defaults not confirmed by the user)

- D1 Slice architecture that registers both forward and backward paths at full throughput: Two-register skid buffer: a main register drives m_axis_* outputs, and a single skid register catches the in-flight beat when downstream stalls. s_tready is driven from a flop. (high impact, high confidence)
- D2 tuser support: Include s/m_axis_tuser ports sized by USER_WIDTH, with a USER_EN parameter (default 0). When disabled, the tuser storage is not generated and the output is tied to 0. (medium impact, medium confidence)
- D3 Other AXI-Stream sideband signals (tstrb, tid, tdest, twakeup): Omit tstrb/tid/tdest. Only tdata, tkeep, tlast and the optional tuser are carried. (low impact, high confidence)
- D5 tkeep width derivation and DATA_WIDTH constraint: KEEP_WIDTH = DATA_WIDTH/8 as a localparam, with an elaboration-time check that DATA_WIDTH % 8 == 0. (low impact, high confidence)
- D6 Configurable slice modes (bypass / forward-only / backward-only): Single fixed fully-registered mode with no mode parameter. (low impact, medium confidence)
- D7 Payload register reset policy: Only the control flops (m_tvalid, skid_valid, s_tready) are reset. Payload registers have no reset. (low impact, medium confidence)
- D9 Forward latency: 1-cycle latency. The skid register is used only on stall, so the beat goes from input directly to the main register. (low impact, high confidence)
- D10 Clock domains: Single clock (aclk) shared by packet engine and egress shaper. No CDC. (high impact, high confidence)
- D11 Reset style and polarity: Synchronous active-low aresetn. During reset, m_tvalid=0 and s_tready=0. s_tready asserts the first cycle after reset deasserts. (medium impact, medium confidence)
