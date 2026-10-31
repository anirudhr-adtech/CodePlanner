# MA plan: 11_interrupt_controller

## S1. Frame the controller: 32 mixed edge/level sources merged into one nesting-aware irq for an RV32 core

**Goal:** Write the Overview. Cover the controller's role: a per-source gateway, priority/threshold arbitration, a claim/complete handshake with 7-level nesting, and a level irq to the core. State what is out of scope (vectoring, multiple targets).

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P2] "The core has a single external interrupt input."
- [P2] "We need a controller that merges 32 peripheral"
- [P6] "While an ISR runs, only strictly higher-priority interrupts may preempt it."
- [P8] "The output to the core is a level `irq` that stays high while there is a claimable interrupt."

**Done when:**
- The Overview names the four functional blocks: source gateway, arbiter, claim/complete with in-service tracker, and register file.
- The Overview states a single target/context, no hardware vectoring, and that software reads {VALID, ID} via CLAIM.
- The Overview lists the external guarantees: priority 0 never interrupts, ties go to the lower ID, only strictly higher priority preempts, and COMPLETE is matched by the stored ID per level.

## S2. Pin down the 'simple bus' slave port, top-level ports and parameters

**Goal:** Define every port: clk, reset, src[31:0], irq and the bus slave signals. Fix the read/write handshake so that the CLAIM read side effect and the 1-cycle registered read are unambiguous.

**Feeds:** Interface, Parameters · **Depends on:** S1

**Spec evidence:**
- [P7] "32-bit simple bus, word-aligned, 1-cycle registered read"
- [P3] "32 inputs, `src[31:0]`."
- [P8] "Clock is 100 MHz"

**Decisions:**
- D1 Bus slave protocol: **Single-cycle request (sel, we, addr[word], wdata) with no byte enables. Writes take effect at the clock edge. rdata is registered and valid one cycle after a read request. No wait states and no error response.** (default, medium impact, medium confidence)
  - options: Single-cycle request (sel, we, addr, wdata) with rdata valid exactly one cycle after a read request, no wait states, no error response / APB-style psel/penable two-phase with pready/pslverr / Request/valid handshake with backpressure
  - This fits 'simple bus' and '1-cycle registered read'. Byte enables add no value for these registers. A fixed-latency read makes the CLAIM side effect happen on exactly one known cycle.

**Done when:**
- The port table lists name, direction, width and description for every signal, including irq as a registered output.
- Read timing is drawn: request in cycle N, rdata in N+1, and the CLAIM side effect committed at the end of cycle N.
- Behaviour for unmapped addresses (read 0, write ignored) and for partial/unaligned accesses (not supported) is stated.
- Parameters are listed: NUM_SRC=32 (fixed), PRIO_BITS=3, SYNC_STAGES=2, plus a per-source async mask if D2 changes.

## S3. Design the per-source gateway: CDC synchronizer, rising-edge detector, edge/level pending

**Goal:** Specify how each src bit becomes a pending bit. Async GPIO pins must be synchronized, single-cycle pulses must be latched in edge mode, and level-mode pending must track the synchronized line.

**Feeds:** Datapath, Clocking & Reset · **Depends on:** S2

**Spec evidence:**
- [P3] "so they are not synchronous to our clock."
- [P3] "Some peripherals (timers, GPIO) produce single-cycle"
- [P3] "edge-triggered (rising edge) or level-triggered (active high)"
- [P5] "Edge interrupts should be cleared by the claim; level interrupts"
- [P5] "stay pending as long as the line is high."

**Decisions:**
- D2 Which sources get a synchronizer: **A 2-flop synchronizer on all 32 sources. Async pin pulses must be at least about 1.5 clock periods wide to be detected.** (default, medium impact, medium confidence)
  - options: 2-flop synchronizer on all 32 sources / Synchronizer only on sources selected by a parameter mask, so synchronous sources save 2 cycles / Async edge-capture flop for pin sources plus synchronizer
  - We do not know which source indices are pins, so synchronizing all of them is safe. The 2-cycle cost still fits 'a few cycles'. Pin pulses narrower than a clock would need async capture, which complicates CDC and reset.
- D3 Does an edge latch pending while the source is disabled: **Pending captures edges regardless of enable. Enable only gates arbitration and irq.** (default, low impact, medium confidence)
  - options: Pending captures edges regardless of enable; enable only gates arbitration / Edges are ignored while disabled
  - This matches the PLIC-style gateway and lets software poll pending for masked sources. Stale edges can be dropped with the pending-clear mechanism.

**Done when:**
- The per-source gateway is described: sync flops, delayed copy for edge detect, pending flop, and the mux by trigger type.
- Edge-mode pending set/clear priority is defined for the same cycle: a new edge vs a claim clear vs a software clear (set wins).
- Level-mode pending is defined as the synchronized line and is not latched.
- Behaviour when the trigger type changes at runtime is specified, including clearing the stale edge pending.

## S4. Lay out the register map, including the CLAIM {VALID, ID} format and COMPLETE semantics

**Goal:** Produce a word-aligned register map covering priority, enable, trigger, pending, pending-clear, threshold, CLAIM/COMPLETE and in-service debug. Give each register's access type, reset value and side effects.

**Feeds:** Interface, Datapath · **Depends on:** S2, S3

**Spec evidence:**
- [P7] "Priority of each source (3 bits per source; pack them as you see fit)"
- [P7] "Pending status (read-only), plus a way for software to clear a stuck edge pending bit"
- [P7] "Claim (read) / Complete (write)"
- [P7] "Something to let firmware see which levels are currently in service, for debug"
- [P5] "Software reads a CLAIM register to get the ID of the highest-priority pending"

**Decisions:**
- D4 Priority register packing: **8 sources per word as 4-bit nibbles with bit 3 reserved (reads 0), giving 4 words.** (default, low impact, high confidence)
  - options: 8 sources per word, 4-bit nibble each (bit 3 reserved), 4 words / One word per source, 32 words / 10 sources per word, 3-bit packed
  - Nibble alignment makes the software index math trivial and avoids fields that straddle words, at a cost of only 4 registers.
- D5 CLAIM value when nothing is claimable: **CLAIM returns [31] VALID and [4:0] ID, and source IDs stay 0..31. When nothing is claimable the read returns 0 (VALID=0) and changes no state. Software must check VALID, because ID 0 is a real source. COMPLETE takes the ID from wdata[4:0].** (decided)
  - options: Return 32 (0x20), since IDs 0..31 are all valid sources / Bit 31 = valid flag, bits[4:0] = ID / Renumber sources 1..32 and return 0 for none (PLIC style)
  - User answer Q2.
- D6 Software clear of stuck edge pending: **A separate W1C PENDING_CLR register. Clearing has no lasting effect on a level source whose line is high.** (default, low impact, medium confidence)
  - options: Separate write-1-to-clear PENDING_CLR register (PENDING stays read-only) / PENDING itself is W1C
  - This keeps PENDING strictly read-only as the spec states while still giving the requested clear mechanism.

**Done when:**
- A table lists offset, name, access type, field layout and reset value for every register.
- The CLAIM field layout is given: [31] VALID, [30:5] reserved 0, [4:0] ID. An empty read returns 0x0 with no side effect.
- CLAIM read side effects are listed for a valid claim: edge pending cleared, in-service level set, and ID stored.
- COMPLETE write semantics are specified: the ID is taken from wdata[4:0], other bits are ignored, and behaviour follows S6.
- The IN_SERVICE debug register (7 bits, one per level 1..7) is defined, plus optional read-only fields for running priority and per-level stored IDs.

## S5. Build the 32-way priority/threshold arbiter with lowest-ID tie-break

**Goal:** Define the eligibility filter and the max-finding structure, and show they close timing at 100 MHz. Eligibility is pending & enable & prio>threshold & prio>running level.

**Feeds:** Datapath, Timing & Pipeline · **Depends on:** S3, S4

**Spec evidence:**
- [P4] "A global threshold lets software ignore everything at or below a given"
- [P4] "If two sources have the same priority, the lower-numbered source wins."
- [P4] "Each source has a priority from 0 to 7, where 0 means "never interrupt" and 7 is"
- [P6] "While an ISR runs, only strictly higher-priority interrupts may preempt it."

**Decisions:**
- D7 Arbiter implementation: **A combinational 5-level compare tree feeding a registered winner {valid, id, prio}. A strict > compare keeps the lower ID on ties. The winner register drives both irq and the CLAIM read data.** (default, medium impact, high confidence)
  - options: Combinational binary compare tree (5 levels) with registered winner {valid, id, prio} / Two-stage pipelined tree / Per-priority-level one-hot pending vectors + priority encoder
  - Five levels of 3-bit compare-and-mux fit easily in 10 ns. One registered stage keeps latency low and gives CLAIM a stable value.
- D8 Threshold/nesting combination: **A source is eligible iff pending & enable & prio != 0 & prio > THRESHOLD & prio > running priority. Running priority is the highest level L with isr_v[L] set.** (decided)
  - options: Effective threshold = max(THRESHOLD, current running priority); eligible iff prio > effective / Threshold only applies when no ISR is active
  - This follows the 'at or below' threshold text, the strictly-higher preemption rule, and Q1 (the effective threshold stays at the highest remaining in-service level).

**Done when:**
- The eligibility equation is written explicitly.
- The tree structure and tie-break comparison are documented, with a critical-path estimate against the 10 ns period.
- Stale-winner handling is defined: the winner register is invalidated in the cycle after a claim, so back-to-back CLAIM reads never return the same claim twice and an empty CLAIM returns 0.

## S6. Design claim/complete and the 7-level in-service tracker with per-level stored IDs

**Goal:** Define how CLAIM records a level and ID, how COMPLETE clears the matching level by stored ID (in or out of order, even after priority reprogramming), and how running priority returns to the highest remaining level.

**Feeds:** Control Logic, Datapath · **Depends on:** S4, S5

**Spec evidence:**
- [P5] "That also marks the interrupt as in service."
- [P5] "the ID to a COMPLETE register."
- [P6] "7 levels of nesting (one per priority level) must work, with each COMPLETE returning to the"
- [P6] "previous level."

**Decisions:**
- D9 In-service tracking structure and COMPLETE matching: **Use a 7-bit isr_v[7:1] plus a 5-bit isr_id[L] per level. CLAIM sets isr_v[prio] and stores isr_id[prio] using the priority captured at claim. COMPLETE clears isr_v[L] for the highest L where isr_v[L] is set and isr_id[L] equals the written ID. Out-of-order completes are allowed. The stored level is used even if the source's priority has since changed. If the same ID is in service at two levels, the higher level is cleared first. Running priority is the highest set isr_v bit.** (decided)
  - options: 7-bit per-level in-service vector plus a 5-bit claimed-ID register per level; COMPLETE matches the ID / 7-bit per-level vector only; COMPLETE clears the bit for the source's current priority / Per-source 32-bit in-service vector
  - User answer Q1.
- D10 COMPLETE with an ID that is not in service: **If no level matches, the write is ignored with no state change and no error flag.** (decided)
  - options: Ignore silently / Ignore and set a sticky error bit readable by software / Clear the top level regardless
  - User answer Q1.

**Done when:**
- The claim update is specified: set isr_v[winner.prio], write isr_id[winner.prio], and clear edge pending, all committed in the read-request cycle using the registered winner's prio.
- The complete update is specified as a 7-way ID compare, an AND with isr_v, and a highest-match priority select, with the result for running priority.
- Same-cycle interactions are resolved: a CLAIM read and a COMPLETE write cannot coincide on a single-port bus; claim vs a new edge on the same source is covered.
- Sequence examples trace three nested levels with in-order unwinding, one out-of-order complete, and one case where the same ID is claimed at two levels after priority reprogramming.

## S7. Assemble the block diagram and the source-to-irq latency budget

**Goal:** Draw the dataflow src -> sync -> edge -> pending -> eligibility -> tree -> winner register -> irq, plus the register file. Count cycles for 'a few cycles' and define irq timing after claim/complete.

**Feeds:** Block Diagram, Timing & Pipeline · **Depends on:** S3, S5, S6

**Spec evidence:**
- [P8] "Clock is 100 MHz; source-to-`irq` latency should be "a few cycles"."
- [P8] "The output to the core is a level `irq` that stays high while there is a claimable interrupt."

**Decisions:**
- D11 irq output timing: **irq is driven directly from the registered winner-valid flop. The documented latency from a synchronous edge to irq is about 4 cycles: 2 sync, 1 pending, 1 winner.** (default, medium impact, high confidence)
  - options: irq = registered winner valid (glitch-free, deasserts the cycle after claim) / irq combinational from the eligibility OR
  - This gives the core a glitch-free registered output within the 'few cycles' budget, and irq drops within 1-2 cycles of a claim.

**Done when:**
- The block diagram shows every register stage, the isr_v/isr_id tracker and the bus register file.
- A latency table covers: edge source, level source, irq deassert after claim, and re-assert after complete.
- A waveform-style description shows that irq may stay high briefly after a claim and that firmware must check VALID on a spurious CLAIM.

## S8. Define clock domain, reset style and reset values that keep the controller silent

**Goal:** Use a single 100 MHz domain apart from the src synchronizers. Choose the reset style and give reset values so that no interrupt fires out of reset.

**Feeds:** Clocking & Reset · **Depends on:** S2, S3

**Spec evidence:**
- [P8] "Clock is 100 MHz"
- [P3] "so they are not synchronous to our clock."

**Decisions:**
- D12 Reset style: **Active-low rst_n with async assert and sync deassert; the deassert synchronizer is assumed external. All priorities, enables, pending, isr_v and THRESHOLD reset to 0. isr_id contents are don't-care while isr_v is 0.** (default, low impact, medium confidence)
  - options: Active-low async assert, sync deassert rst_n / Synchronous active-high reset
  - This is common practice in RV32 microcontroller SoCs, and priority 0 out of reset guarantees irq is low.

**Done when:**
- Clock domain crossings are listed (src only), with synchronizer depth and SDC/CDC notes.
- The reset value of every register and state flop is listed.
- The synchronizer and edge-detect flops at reset are defined so that a line already high at reset release does not create a spurious edge.

## S9. Enumerate corner cases: races, reprogramming, empty claims, out-of-order and duplicate completes

**Goal:** Catalogue the hazardous scenarios and give the defined behaviour for each one.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S5, S6, S7

**Spec evidence:**
- [P7] "Trigger type (1 bit per source: 1 = edge, 0 = level)"
- [P7] "Enable mask (1 bit per source)"
- [P3] "others (UART, SPI) hold a level until serviced"

**Done when:**
- Covers: an edge arriving in the same cycle as its claim; back-to-back CLAIMs; CLAIM with nothing pending (returns 0, no state change); COMPLETE of a non-claimed ID (ignored); a double COMPLETE (second ignored).
- Covers: out-of-order COMPLETE (that level cleared, running priority = highest remaining); a priority changed while in service (stored level used); the same ID in service at two levels (highest cleared first).
- Covers: enable or trigger changed while pending or in service; threshold raised above running work; a level line dropping before claim (CLAIM returns the next winner or VALID=0).
- Covers: an async pulse narrower than the sync window, and an edge source re-firing during its own ISR.

## S10. Verification plan with a reference model of pending, priority and per-level-ID nesting

**Goal:** Define the testbench architecture, scoreboard model, directed tests, random tests and coverage for this controller.

**Feeds:** Verification Plan · **Depends on:** S6, S7, S9

**Spec evidence:**
- [P6] "Up to"
- [P5] "When the ISR is finished, software writes"

**Done when:**
- A cycle-tolerant reference model predicts the CLAIM {VALID, ID}, irq and isr_v/isr_id, including the highest-matching-level COMPLETE rule.
- Directed tests cover: tie-break, threshold boundary, prio 0, ID 0 claimed with VALID=1 vs empty claim, edge vs level clearing, full 7-level nesting and unwind, out-of-order completes, pending clear, and every S9 corner case.
- A constrained-random ISR-emulating driver includes async-jittered pin sources, random priority reprogramming and out-of-order completes.
- Coverage includes priority x trigger x enable, nesting depth 0..7, complete order (in/out of order/unmatched) and same-cycle races.
- Assertions check: irq implies a valid winner; CLAIM never returns an ineligible ID; an empty CLAIM changes no state; an unmatched COMPLETE changes no state; latency bound.

## S11. Record assumptions and open questions

**Goal:** Collect every remaining defaulted decision and implicit assumption so the spec author can confirm them, and record the resolved Q1/Q2 answers.

**Feeds:** Assumptions & Open Questions · **Depends on:** S1, S2, S3, S4, S5, S6, S7, S8, S9, S10

**Spec evidence:**
- [P7] "32-bit simple bus, word-aligned, 1-cycle registered read"
- [P8] "Clock is 100 MHz; source-to-`irq` latency should be "a few cycles"."

**Done when:**
- Each defaulted decision (D1, D2, D3, D4, D6, D7, D11, D12) appears with its chosen default and question.
- The decided items from user answers (D5 CLAIM format, D9/D10 COMPLETE matching) are recorded as resolved.
- Assumptions are stated: a single hart/context, the core masks globally via mstatus, no wake-from-sleep requirement, minimum async pulse width, and firmware checks VALID.

## Assumptions (defaults not confirmed by the user)

- D1 Bus slave protocol: Single-cycle request (sel, we, addr[word], wdata) with no byte enables. Writes take effect at the clock edge. rdata is registered and valid one cycle after a read request. No wait states and no error response. (medium impact, medium confidence)
- D2 Which sources get a synchronizer: A 2-flop synchronizer on all 32 sources. Async pin pulses must be at least about 1.5 clock periods wide to be detected. (medium impact, medium confidence)
- D3 Does an edge latch pending while the source is disabled: Pending captures edges regardless of enable. Enable only gates arbitration and irq. (low impact, medium confidence)
- D4 Priority register packing: 8 sources per word as 4-bit nibbles with bit 3 reserved (reads 0), giving 4 words. (low impact, high confidence)
- D6 Software clear of stuck edge pending: A separate W1C PENDING_CLR register. Clearing has no lasting effect on a level source whose line is high. (low impact, medium confidence)
- D7 Arbiter implementation: A combinational 5-level compare tree feeding a registered winner {valid, id, prio}. A strict > compare keeps the lower ID on ties. The winner register drives both irq and the CLAIM read data. (medium impact, high confidence)
- D11 irq output timing: irq is driven directly from the registered winner-valid flop. The documented latency from a synchronous edge to irq is about 4 cycles: 2 sync, 1 pending, 1 winner. (medium impact, high confidence)
- D12 Reset style: Active-low rst_n with async assert and sync deassert; the deassert synchronizer is assumed external. All priorities, enables, pending, isr_v and THRESHOLD reset to 0. isr_id contents are don't-care while isr_v is 0. (low impact, medium confidence)
