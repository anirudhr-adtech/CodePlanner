# MA plan: 10_async_fifo

## S1. Frame the camera-pixel async FIFO and its no-loss/no-duplication contract

**Goal:** Write the Overview. State the purpose: bridge 26-bit pixel words from a 74.25 MHz sensor clock that can stop to a 200 MHz system clock. State the hard correctness contract: no loss and no duplication, with pessimistic full/empty allowed. Note the one exception: an agreed reset flush discards buffered pixels. Set the CDC-clean structure and the SDC timing constraints as first-class deliverables.

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P1] "ASYNC FIFO — camera pixel bridge"
- [P2] "sensor pixel clock, 74.25 MHz (can stop when sensor is off)"
- [P2] "rd side: system clock, 200 MHz"
- [P2] "no data loss / no duplication ever, full/empty may be pessimistic"
- [P2] "need the timing constraints too"

**Done when:**
- The Overview names both clock domains with their frequencies and states that the clocks are fully asynchronous.
- The no-loss/no-duplication guarantee and the meaning of 'pessimistic flags' are written as checkable statements.
- The reset-flush exception (either reset discards in-flight pixels) is stated explicitly.
- The deliverables are listed: RTL, a SpyGlass-clean CDC/RDC structure, and an SDC constraints file.

## S2. Define per-domain ports and the DATA_WIDTH/DEPTH/threshold parameter set

**Goal:** Write the Interface and Parameters sections. Group ports strictly by clock domain (wr_clk/wr_rst_n vs rd_clk/rd_rst_n) so that no port is ambiguous for CDC. Fix the parameters, their derived values and their legality checks.

**Feeds:** Interface, Parameters · **Depends on:** S1

**Spec evidence:**
- [P2] "data: 24-bit RGB + 1 bit SOF + 1 bit EOL = 26 bits (make width a parameter)"
- [P2] "depth: 32 (parameter, power of 2 OK)"
- [P2] "wr: wr_en, wr_data, wr_full, wr_almost_full (threshold = parameter)"
- [P2] "rd: rd_en, rd_data, rd_empty, rd_almost_empty (threshold = parameter)"

**Decisions:**
- D1 Supported DEPTH values: **Power-of-2 only, enforced by an elaboration-time assertion. ADDR_W = clog2(DEPTH) and the pointers are ADDR_W+1 bits.** (default, medium impact, high confidence)
  - options: Power-of-2 only, N+1-bit Gray pointers, elaboration-time check / Arbitrary depth using a non-power-of-2 Gray scheme
  - 'power of 2 OK' suggests the restriction is acceptable. A standard Gray wrap needs a power of 2, and arbitrary depths complicate the CDC.

**Done when:**
- The port table lists every signal with its direction, width, clock domain and reset domain.
- DATA_WIDTH (default 26), DEPTH (default 32), the AF and AE threshold parameters, and SYNC_STAGES (default 2) are defined with defaults and legal ranges.
- The derived parameters (ADDR_W, pointer width) are given.
- The parameter legality checks are listed.

## S3. Partition into write domain, read domain, storage array and synchronizer/reset cells

**Goal:** Write the Block Diagram. Show the write pointer/flag block, the read pointer/flag block, the dual-clock storage, the two Gray pointer synchronizers, and the coupled reset combiner feeding a reset synchronizer in each domain. Mark every clock-domain and reset-domain crossing explicitly.

**Feeds:** Block Diagram · **Depends on:** S2

**Spec evidence:**
- [P2] "Gray pointers + 2FF syncs, must be CDC-clean (we run SpyGlass CDC)"
- [P2] "clocks fully async, no phase relationship"

**Decisions:**
- D2 Storage implementation: **A generic flop array (DEPTH x DATA_WIDTH) written on wr_clk. The rd address reads it combinationally into a registered rd_data on rd_clk, and the array sits behind a wrapper so a RAM macro can be swapped in later.** (default, medium impact, medium confidence)
  - options: Flop array written on wr_clk, read through a mux into an rd_clk output register / Inferred/instantiated dual-clock SRAM macro or FPGA BRAM
  - At 32x26 the array is small. A flop array is technology-independent, and SpyGlass recognizes it as FIFO memory qualified by the pointer synchronizers.

**Done when:**
- The diagram shows exactly two pointer crossings (wr Gray to the rd domain, rd Gray to the wr domain), plus the memory-to-rd_data path qualified by the pointers.
- The reset combiner (wr_rst_n & rd_rst_n) and both per-domain reset synchronizers are drawn.
- Every block is labelled with its clock and reset.
- No combinational logic sits between a source register and a synchronizer input.

## S4. Specify binary/Gray pointer datapath and registered read data path

**Goal:** Write the Datapath section. Cover the binary and Gray pointer registers in each domain, increment gating, the registered Gray outputs feeding the synchronizers, the memory write, and the rd_data register that updates one cycle after an accepted rd_en.

**Feeds:** Datapath · **Depends on:** S3

**Spec evidence:**
- [P2] "standard style: registered read data, 1 cycle after rd_en"
- [P2] "Gray pointers + 2FF syncs"

**Decisions:**
- D3 Read port semantics: **Standard mode. A read is accepted only when rd_en && !rd_empty. rd_data updates on the next rd_clk edge and holds its value otherwise.** (decided)
  - options: Standard mode: rd_data registered and valid 1 cycle after an accepted rd_en / First-word-fall-through
  - The spec explicitly requires registered read data 1 cycle after rd_en.

**Done when:**
- Pointer widths and the binary-to-Gray conversion are defined, and the Gray value is a flop output (not combinational) before the crossing.
- The memory write enable is wr_en && !wr_full, and the read advance is rd_en && !rd_empty.
- The rd_data hold behaviour on non-accepted cycles is stated, along with rd_data's reset value.

## S5. Derive full/empty and almost-full/almost-empty from synchronized Gray pointers

**Goal:** Write the flag logic in Control Logic. Compute full in the write domain against the synchronized rd pointer, and empty in the read domain against the synchronized wr pointer. Compute the almost flags from fill levels derived from the same synchronized pointers. Show that every flag can be pessimistic but never optimistic.

**Feeds:** Control Logic · **Depends on:** S4

**Spec evidence:**
- [P2] "wr: wr_en, wr_data, wr_full, wr_almost_full (threshold = parameter)"
- [P2] "rd: rd_en, rd_data, rd_empty, rd_almost_empty (threshold = parameter)"
- [P2] "no data loss / no duplication ever, full/empty may be pessimistic"

**Decisions:**
- D4 Flag generation style: **All four flags are registered. Each is computed from the next pointer value against the synchronized opposite pointer, so the flags are glitch-free and assert in the same cycle as the pointer update.** (default, low impact, high confidence)
  - options: Registered flags computed from next-pointer vs synchronized pointer (Cummings style) / Combinational flags from current pointers
  - This is the industry standard. It gives clean timing and avoids a flag that is optimistic for one cycle.
- D5 Almost-flag threshold semantics: **Occupancy level. wr_almost_full asserts when the write-side count >= AF_LEVEL, and rd_almost_empty asserts when the read-side count <= AE_LEVEL. Both thresholds are static parameters.** (default, low impact, medium confidence)
  - options: Threshold is an occupancy level: almost_full when count >= AF_LEVEL, almost_empty when count <= AE_LEVEL / Threshold is a margin from the boundary: almost_full when free slots <= AF_MARGIN
  - The spec only says 'threshold = parameter'. An occupancy level is the most common convention, but both readings are widespread.
- D6 Overflow/underflow handling: **Ignore writes when full and reads when empty, which protects pointer integrity. Add SVA in verification, but no extra error ports.** (default, medium impact, medium confidence)
  - options: Silently ignore wr_en when full and rd_en when empty, with no extra ports / Ignore, and also add sticky overflow/underflow error outputs / Treat as assertion-only (simulation) violations
  - The spec defines a fixed port list. Gating preserves no-duplication on the read side. Data dropped by a producer writing into a full FIFO is a protocol violation by the producer.

**Done when:**
- Full is defined as a Gray comparison with the top two bits inverted, and empty as Gray equality.
- The fill-level computation (Gray-to-binary of the synchronized pointer) is specified for the almost flags.
- There is a written argument that every flag can only be late to deassert, never late to assert.
- The accept/ignore behaviour of wr_en at full and rd_en at empty is stated.

## S6. Define 2FF Gray synchronizer cells and SpyGlass CDC strategy

**Goal:** Specify the synchronizer structure so that SpyGlass CDC recognizes it with no waivers beyond the standard FIFO memory qualification. List the CDC rules and setup the design is meant to pass.

**Feeds:** Control Logic, Clocking & Reset · **Depends on:** S3

**Spec evidence:**
- [P2] "Gray pointers + 2FF syncs, must be CDC-clean (we run SpyGlass CDC)"
- [P2] "clocks fully async, no phase relationship"

**Decisions:**
- D7 Synchronizer implementation: **A dedicated sync module (generic flops, SYNC_STAGES parameter defaulting to 2) instantiated for both pointer crossings. It can be replaced by a library sync cell and is identifiable in the SpyGlass and SDC constraints.** (default, low impact, medium confidence)
  - options: Dedicated parameterized sync-cell module (SYNC_STAGES, default 2) instantiated per pointer bit, named for SpyGlass recognition / Inline 2FF flops in the FIFO RTL / Technology library synchronizer cell
  - A single recognizable cell makes the CDC setup, the constraints and any later swap to a hardened cell straightforward. A 2FF depth meets the spec.

**Done when:**
- The sync module is defined, with its attribute/naming conventions for CDC tools and P&R (e.g. ASYNC_REG/dont_touch).
- The expected SpyGlass setup is listed: clock definitions, reset domains, and recognition of the memory crossing as FIFO-qualified.
- It is shown that only Gray-coded, registered buses cross clock domains.

## S7. Implement coupled async-clear reset (wr_rst_n & rd_rst_n) with per-domain synchronous release

**Goal:** Write the Clocking & Reset section for the agreed policy. Either reset, asserted alone, asynchronously clears both pointer sets, all synchronizer flops and the flags, and in-flight pixels are discarded. Each domain releases reset synchronously to its own clock, only after both inputs are deasserted. Show that this policy never creates phantom or duplicated words and still works while wr_clk is stopped.

**Feeds:** Clocking & Reset · **Depends on:** S6

**Spec evidence:**
- [P2] "each side has its own reset, active low; resets can come at different times"
- [P2] "no data loss / no duplication ever"
- [P2] "sensor pixel clock, 74.25 MHz (can stop when sensor is off)"

**Decisions:**
- D8 Reset synchronization: **The combined async clear (wr_rst_n & rd_rst_n) drives an internal reset synchronizer in each domain: async assert, sync deassert on that domain's clock. Assertion therefore works even when wr_clk is stopped, and the write domain stays in reset until wr_clk runs again after release.** (decided)
  - options: Internal per-domain reset synchronizer: async assert, sync deassert / Assume resets arrive already synchronized to their clock / Fully synchronous resets
  - The user answer requires an asynchronous clear of both pointer sets and a synchronous exit per own clock, which needs an internal async-assert/sync-deassert synchronizer per domain.
- D9 Behaviour when only one side is reset: **Coupled flush. The effective async clear for both domains is wrst_n & rrst_n, so either reset alone asynchronously resets both pointer sets and in-flight pixels are discarded. Each side leaves reset synchronously to its own clock, and only after both resets are deasserted. The design must not assume the system resets both sides together.** (decided)
  - options: Coupled flush: either reset clears both sides; each side releases only after both resets deassert / Independent: each side resets only its own pointer; the system guarantees both are reset together / Write-only reset preserves read-side data (not safe with plain Gray pointers)
  - Settled by the user answer to Q1.

**Done when:**
- The reset combiner and both reset synchronizers are specified, including the requirement for a glitch-free AND, with no other logic on the reset path.
- Every flop is assigned to a reset: pointers, Gray registers, pointer synchronizer stages, flags, rd_data, and whether the memory array is reset.
- Flag values during reset and in the release window are tabulated per side, with the reset value of wr_full/wr_almost_full and of rd_empty/rd_almost_empty chosen so that no flag is optimistic. This includes the window where one domain has released and the other has not.
- It is shown that release on the two sides at different times cannot present a multi-bit pointer change to a synchronizer: both pointers are zero while either side is still in reset.
- The case where reset is asserted while wr_clk is stopped is covered: the async clear takes effect without a clock.
- RDC items are listed for SpyGlass: each reset input crosses into the other domain's async clear, and synchronized deassertion qualifies it.

## S8. Handle stopped sensor clock, wrap-around and boundary corner cases

**Goal:** Write the Corner Cases section. Cover wr_clk stopping with data still buffered, wr_clk stopped while either reset toggles, a one-sided reset during active traffic, near-full and near-empty pointer races, pointer wrap at 2*DEPTH, threshold edge values, and back-to-back accesses at the 200/74.25 MHz ratio.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S5, S7

**Spec evidence:**
- [P2] "sensor pixel clock, 74.25 MHz (can stop when sensor is off)"
- [P2] "resets can come at different times"
- [P2] "full/empty may be pessimistic"

**Decisions:**
- D10 Draining when wr_clk stops: **All words written before wr_clk stops remain visible and readable. The wr Gray pointer register holds its value and the rd-side synchronizer keeps sampling it on rd_clk, so rd_empty deasserts correctly. The write side's view of rd progress stays stale, so wr_full is pessimistic, which is allowed.** (decided)
  - options: Read side must drain every word written before the clock stopped (the wr Gray pointer is held stable and keeps being sampled on rd_clk) / Data written just before a clock stop may be stranded until the clock restarts
  - This follows from 'can stop' together with 'no data loss'. The architecture must not depend on wr_clk toggling after the last write.

**Done when:**
- Each corner case has its expected behaviour written down: clock stop with data buffered, clock stop during or after reset, a one-sided reset mid-frame (flush plus SOF resynchronization implications), wrap, full and empty in the same instant, and AF/AE at 0 or DEPTH.
- Legal threshold ranges are stated, with the behaviour at the extremes.
- It is confirmed that no flag path relies on wr_clk toggling after the last write.

## S9. Quantify flag latencies and write the SDC CDC constraint set

**Goal:** Write Timing & Pipeline. Give the rd-data latency, the write-to-empty-deassert latency in rd_clk cycles, the read-to-full-deassert latency in wr_clk cycles, the reset release latency per domain, and a throughput argument for 74.25 MHz into 200 MHz. Then specify the agreed SDC constraint set.

**Feeds:** Timing & Pipeline, Clocking & Reset · **Depends on:** S5, S6, S7

**Spec evidence:**
- [P2] "need the timing constraints too"
- [P2] "standard style: registered read data, 1 cycle after rd_en"
- [P2] "clocks fully async, no phase relationship"

**Decisions:**
- D11 Constraint style and target format: **SDC-style constraints. Both clocks are defined. Each Gray pointer bus and the memory-to-rd_data crossing get a set_max_delay -datapath_only bounded by the smaller clock period (5 ns) plus a bus-skew limit. No blanket false path is used, since that would let Gray bits skew more than one cycle.** (decided)
  - options: Generic SDC: create_clock for both, set_max_delay -datapath_only bounded by min period plus a bus-skew limit on Gray pointer and memory read crossings, no blanket async group / set_clock_groups -asynchronous / set_false_path between the clocks / Vendor-specific XDC or ASIC SDC
  - Settled by the user answer to Q2.

**Done when:**
- A latency table gives min/max cycles for: rd_en to rd_data, write to rd_empty deassert, read to wr_full deassert, the almost-flag updates, and reset release per domain.
- A throughput statement shows that a continuously reading consumer never lets the FIFO fill.
- The SDC listing contains: create_clock for wr_clk (13.468 ns) and rd_clk (5 ns), and set_max_delay -datapath_only at 5 ns on both Gray pointer buses and on the memory-array-to-rd_data path.
- The SDC listing also contains a bus-skew limit for each Gray bus, and constraints or false paths only on reset-synchronizer async inputs and the reset combiner.
- The listing confirms there is no blanket set_false_path or asynchronous clock group.
- Each constraint is mapped to the RTL crossing it covers.

## S10. Plan dual-clock scoreboard, clock-stop/reset stress and CDC/RDC sign-off

**Goal:** Write the Verification Plan. Use an ordered scoreboard to prove no loss and no duplication across random clock ratios and jitter, sensor clock stop and restart, and independent reset assertion at random times with flush semantics. Add SVA on the flag invariants. Include SpyGlass CDC/RDC and constraint checks as sign-off items.

**Feeds:** Verification Plan · **Depends on:** S8, S9

**Spec evidence:**
- [P2] "no data loss / no duplication ever, full/empty may be pessimistic"
- [P2] "must be CDC-clean (we run SpyGlass CDC)"
- [P2] "resets can come at different times"

**Done when:**
- The scoreboard compares the exact ordered sequence, including the SOF/EOL bits.
- On any reset assertion the scoreboard flushes its expected queue and checks that no pre-reset word appears after reset release.
- The test list covers: nominal 74.25/200 MHz, extreme clock ratios, wr_clk stop/restart with data buffered, wr-only and rd-only resets at random times (including while wr_clk is stopped), staggered release, full and empty stress, and threshold boundaries.
- The SVA list includes: no write accepted when full, no read accepted when empty, Gray single-bit change per cycle, rd_data stable when not read, and pointers at zero while either reset is asserted.
- The sign-off checklist includes a clean SpyGlass CDC and RDC run and an SDC coverage check of every crossing.

## S11. Record assumptions, resolved answers and remaining open questions for the pixel bridge

**Goal:** Write the Assumptions & Open Questions section. Record the resolved decisions (D8, D9 and D11 from the user answers), list the remaining defaulted decisions with their questions, and state the system assumptions.

**Feeds:** Assumptions & Open Questions · **Depends on:** S10

**Spec evidence:**
- [P2] "no data loss / no duplication ever, full/empty may be pessimistic"
- [P2] "each side has its own reset, active low; resets can come at different times"

**Done when:**
- The resolved decisions D8, D9 and D11 are recorded with the user's answers.
- Each still-defaulted decision (D1, D2, D4, D5, D6, D7) appears with its choice and its open question.
- System-level assumptions are listed: the producer honours wr_full, either reset flushes all buffered pixels, and the downstream logic resynchronizes on the next SOF after a flush.
- Open items are ordered by impact.

## Assumptions (defaults not confirmed by the user)

- D1 Supported DEPTH values: Power-of-2 only, enforced by an elaboration-time assertion. ADDR_W = clog2(DEPTH) and the pointers are ADDR_W+1 bits. (medium impact, high confidence)
- D2 Storage implementation: A generic flop array (DEPTH x DATA_WIDTH) written on wr_clk. The rd address reads it combinationally into a registered rd_data on rd_clk, and the array sits behind a wrapper so a RAM macro can be swapped in later. (medium impact, medium confidence)
- D4 Flag generation style: All four flags are registered. Each is computed from the next pointer value against the synchronized opposite pointer, so the flags are glitch-free and assert in the same cycle as the pointer update. (low impact, high confidence)
- D5 Almost-flag threshold semantics: Occupancy level. wr_almost_full asserts when the write-side count >= AF_LEVEL, and rd_almost_empty asserts when the read-side count <= AE_LEVEL. Both thresholds are static parameters. (low impact, medium confidence)
- D6 Overflow/underflow handling: Ignore writes when full and reads when empty, which protects pointer integrity. Add SVA in verification, but no extra error ports. (medium impact, medium confidence)
- D7 Synchronizer implementation: A dedicated sync module (generic flops, SYNC_STAGES parameter defaulting to 2) instantiated for both pointer crossings. It can be replaced by a library sync cell and is identifiable in the SpyGlass and SDC constraints. (low impact, medium confidence)
