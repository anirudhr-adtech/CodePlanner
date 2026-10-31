# MA plan: 13_pipelined_mac

## S1. Fixed-point format analysis: Q1.15 x Q1.15 product, guard bits and output bit extraction

**Goal:** Work out the numeric format at every stage so later steps share one bit-position map. Q1.15 x Q1.15 gives a Q2.30 product (32 bits). Supporting 256 full-scale products needs 8 guard bits, so the minimum accumulator is 40 bits (Q10.30). The Q1.15 output is taken from accumulator bits [30:15], and every bit above bit 30 must be a sign extension for the output to be in range.

**Feeds:** Overview, Datapath · **Depends on:** none

**Spec evidence:**
- [P2] "signed fixed point, two operands a, b; defaults Q1.15 x Q1.15"
- [P2] "accumulator needs guard bits, at least 256 full-scale products without overflow"
- [P2] "output Q1.15, round to nearest, saturate (no wrap!) + flag when saturated"
- [P1] "MAC unit for the beamformer"

**Done when:**
- The Overview states the function: a running signed MAC with clear, valid and last, a rounded and saturated Q1.15 output, a saturation flag and a sticky overflow flag.
- A table gives width and Q-format for operand, product, accumulator and output, both at defaults and as formulas of the parameters.
- The guard-bit derivation is written out: ceil(log2(256)) = 8, plus the -1 x -1 = +1 product needing 2 integer bits.
- The output slice position and the saturation condition are expressed as functions of the parameters.

## S2. Width/fraction parameters and their DSP48E2 legality limits

**Goal:** Define the parameter set: A_W, B_W, ACC_W, OUT_W and the fractional-bit counts needed to place the output slice. Derive the legal ranges that keep the design inside a single DSP48E2, which has a 27x18 signed multiplier and a 48-bit P register.

**Feeds:** Parameters · **Depends on:** S1

**Spec evidence:**
- [P2] "widths must be parameters (a, b, accumulator, output)"
- [P2] "Must map onto one DSP48E2"

**Decisions:**
- D1 Parameter legality enforcement for single-DSP mapping: **Elaboration-time checks restrict widths so the design always fits one DSP48E2. The wider operand goes on the 27-bit port. Fractional-bit parameters set the output slice.** (default, medium impact, high confidence)
  - options: Elaboration-time assertions: A_W<=27, B_W<=18 (or swapped), A_W+B_W+guard<=48, OUT_W<=product width / Allow any widths and accept multi-DSP mapping silently
  - The spec says the design must map onto one DSP48E2. Silently spilling over to multiple DSPs would break that requirement and the 400 MHz target.

**Done when:**
- Every parameter has a name, a default (16/16/ACC/16) and a legal range, including the fractional-bit parameters.
- Derived localparams (product width, output slice LSB/MSB, guard bits, RND constant, pattern/mask) are listed with formulas.
- The elaboration checks and their error conditions are specified.

## S3. Port list including clear, last sideband, saturation flag and sticky overflow flag

**Goal:** Specify every port with its width and timing relation. The ports are: clk; rst (sync, active-high); a and b; valid_in; clear; last_in; y (Q1.15); valid_out; last_out; the sat flag; and the sticky accumulator-overflow flag. There is no ready signal.

**Feeds:** Interface · **Depends on:** S2

**Spec evidence:**
- [P2] "valid in, valid out, no back-pressure needed (stream is continuous or gapped by valid)"
- [P2] "pass a `last` sideband through with the same latency"
- [P2] "clear input: starts a new accumulation with the current product (no dead cycle)"
- [P2] "sticky flag if the accumulator itself overflows anyway"

**Done when:**
- The port table lists direction, parameterized width, sampling edge and the cycle each output aligns to.
- The doc states that clear and last_in are sampled with a and b on the same cycle.
- The doc states that sat is per-sample and aligned with y and valid_out, while the overflow flag is sticky.
- The behaviour of y and sat while valid_out is low is defined (e.g. hold the last value).

## S4. DSP48E2 mapping: AREG/BREG, MREG, PREG and the OPMODE/ALUMODE plan in inference-friendly RTL

**Goal:** Map the three spec stages onto DSP48E2 internal registers: input regs to A/B regs, multiply to MREG, accumulate to PREG. Write the behavioural RTL structure so that synthesis infers exactly this register arrangement. Draw the block diagram showing the DSP boundary, the fabric control/sideband pipeline and the output saturation logic. Identify which constructs (dynamic Z-mux clear, RND/W-mux constant, pattern detect) must be coded in an inference-recognisable form.

**Feeds:** Block Diagram, Datapath, Overview · **Depends on:** S1, S2

**Spec evidence:**
- [P2] "pipeline ~3 stages: input regs / multiply / accumulate. Must map onto one DSP48E2"
- [P2] "400 MHz target, UltraScale+"

**Decisions:**
- D2 Implementation style for the DSP48E2: **Inference-friendly behavioural RTL written to mirror the DSP48E2 register structure. The verification plan includes a check of the synthesis utilization/mapping report.** (decided)
  - options: Inference-friendly behavioural RTL with use_dsp attributes, mapping verified in synthesis reports / Direct DSP48E2 primitive instantiation inside a parameterized wrapper
  - User answer (Q1). Behavioural RTL keeps parameters flexible and simulators portable. The mapping risk (clear via Z-mux, RND injection, pattern detect) is handled by coding the RTL to mirror DSP registers and by checking the synthesis report.

**Done when:**
- The block diagram shows the DSP48E2 boundary with AREG/BREG, MREG and PREG, plus fabric delay lines for valid, clear and last, and the output saturation path.
- Each spec stage is mapped to a named DSP register, and the RTL always-block structure that infers it is described (one register per stage, no logic between M and P other than the add/mux).
- The equivalent OPMODE (W/X/Y/Z mux) settings are listed for accumulate, clear-and-load, and hold/invalid, and the RTL expressions that infer them are listed.
- The doc lists which functions live inside the DSP and which in fabric, and names any construct that may fail inference, with a fallback coding style for it.

## S5. Pipeline latency and alignment of valid, clear and last through the DSP stages

**Goal:** Fix the end-to-end latency and build the cycle-by-cycle pipeline table. Valid, clear and last travel in fabric shift registers whose depth matches the DSP register depth. Clear must reach the accumulate stage on the same cycle as its product.

**Feeds:** Timing & Pipeline · **Depends on:** S4

**Spec evidence:**
- [P2] "pipeline ~3 stages: input regs / multiply / accumulate."
- [P2] "pass a `last` sideband through with the same latency"
- [P2] "y = sum(a*b), running; output each cycle a valid product is accumulated"

**Decisions:**
- D3 Output register after PREG (total latency): **Latency 4. A fabric output register follows the saturation/round-select mux, and valid_out and last_out are delayed by 4.** (default, medium impact, medium confidence)
  - options: Latency 3: y/sat formed by a combinational saturation mux driven by PREG and the registered pattern-detect / Latency 4: add a fabric output register after the saturation mux
  - At 400 MHz on UltraScale+, DSP clock-to-out plus a LUT mux plus routing into unknown downstream logic is risky. The spec only says '~3', so adding one register buys timing margin.

**Done when:**
- A pipeline table shows, per cycle, a/b, product, accumulator, y and the positions of valid, clear and last.
- The latency is stated as a single number, and valid_out, last_out and sat are shown to align with their y.
- The clear delay is shown to align with the MREG-to-PREG transfer of the same sample.

## S6. Accumulate/clear/hold control via dynamic Z-mux selection with no dead cycle

**Goal:** Define the control truth table at the accumulate stage from (valid_d, clear_d). valid=1, clear=0 gives P <= P + M. valid=1, clear=1 gives P <= M + RND, which starts a new sum with the current product. valid=0 holds P. The control must allow back-to-back clears and continuous accumulation with no bubble.

**Feeds:** Control Logic · **Depends on:** S4, S5

**Spec evidence:**
- [P2] "clear input: starts a new accumulation with the current product (no dead cycle)"
- [P2] "valid in, valid out, no back-pressure needed (stream is continuous or gapped by valid)"
- [P2] "output each cycle a valid product is accumulated"

**Decisions:**
- D4 Clear mechanism: **A pipelined clear selects Z=0 (P = product + RND) on the clearing sample's accumulate cycle. Back-to-back clears are allowed.** (decided)
  - options: Pipelined clear switches the DSP Z mux from P-feedback to 0 (and W to the RND constant) for the clearing sample / Reset the P register, then load (introduces a dead cycle)
  - The spec requires 'no dead cycle' and says the new accumulation starts with the current product. Only an OPMODE switch achieves this inside one DSP.
- D5 Behaviour on invalid cycles: **The pipeline is free-running with valid tagging. On beats where valid_d is low, the accumulator holds and valid_out stays low.** (decided)
  - options: Free-running pipeline; on invalid beats the accumulator holds (CEP gating or zero addend) / Stall the whole pipeline on invalid beats
  - The spec says the stream is 'gapped by valid' with no back-pressure. Invalid beats must not contribute, and outputs appear only for valid products.
- D6 Clear asserted on a cycle where valid is low: **clear is qualified by valid and is ignored on invalid beats.** (default, medium impact, medium confidence)
  - options: Ignore clear unless valid is high / Latch a pending clear and apply it to the next valid product / Clear immediately to zero (empty accumulation)
  - The spec defines clear as starting a new accumulation 'with the current product', which exists only on valid beats. Ignoring clear otherwise is the simplest consistent rule.

**Done when:**
- The truth table covers all (valid_d, clear_d) combinations, giving the OPMODE/CE setting, the accumulator next-state, valid_out and the effect on the overflow flag.
- The doc shows that holding on invalid beats does not disturb the running sum.
- Back-to-back clears, and a clear on the very first sample after reset, are covered.

## S7. Round-to-nearest via RND injection at clear and saturation via pattern detect

**Goal:** Make the running output correctly rounded and saturated on every valid cycle without a per-cycle fabric adder. Inject the half-LSB rounding constant once per accumulation (at clear), so the truncated slice of P is always round(sum). Detect out-of-range P with the DSP pattern detector, then select slice/max/min in fabric.

**Feeds:** Datapath, Control Logic · **Depends on:** S1, S4, S6

**Spec evidence:**
- [P2] "output Q1.15, round to nearest, saturate (no wrap!) + flag when saturated"

**Decisions:**
- D7 Rounding implementation and tie behaviour: **Round-half-up (ties toward +inf). The 2^(slice_lsb-1) constant is injected via the W mux on the clearing sample, so every running output is round(sum).** (default, medium impact, medium confidence)
  - options: Round-half-up: add 0.5 output-LSB once per accumulation (W-mux RND at clear), then truncate / Convergent (round-half-even) using pattern detect on the discarded bits / Round-half-away-from-zero via fabric logic
  - This costs no fabric and no latency, and it is the standard DSP48 idiom. 'Round to nearest' does not specify ties, and half-up has a tiny positive bias that some beamformer users may object to.
- D8 Saturation detection location: **Use the DSP48E2 pattern detector. If neither PATTERNDETECT nor PATTERNBDETECT is set, saturate to max or min by sign (P[47]) and assert sat.** (default, medium impact, high confidence)
  - options: DSP pattern detector with a mask checking that P bits above the output MSB are all-0 or all-1 (PATTERNDETECT/PATTERNBDETECT) / Fabric reduction over the upper P bits
  - The comparison is free inside the DSP and is registered with PREG, which helps reach 400 MHz. The fabric mux then only selects between slice, max and min. With inferred RTL, the pattern-detect inference must be confirmed in synthesis.

**Done when:**
- The RND constant value is given as a formula of the parameters, and its injection point is tied to the clear selection.
- The doc shows that adding the offset once per accumulation gives a correctly rounded output for every running partial sum.
- The doc states how rounding is guaranteed for an accumulation that starts after reset without a clear, e.g. P resets to the RND constant or the first sample must carry clear.
- The pattern/mask values are given as formulas, together with the max/min selection logic and the RTL form that infers the pattern detector.
- The doc states that the output slice is taken after rounding, and that a rounding carry into saturation is handled.

## S8. Accumulator headroom and sticky overflow flag detection

**Goal:** Decide the widths of the physical and logical accumulator, and how 'the accumulator itself overflows' is detected. The pattern detector is used for output saturation, so overflow detection must be in fabric. Define when the sticky flag clears.

**Feeds:** Datapath, Control Logic, Parameters · **Depends on:** S1, S6, S7

**Spec evidence:**
- [P2] "accumulator needs guard bits, at least 256 full-scale products without overflow"
- [P2] "sticky flag if the accumulator itself overflows anyway"
- [P2] "widths must be parameters (a, b, accumulator, output)"

**Decisions:**
- D9 Accumulator width and overflow-detection boundary: **The DSP accumulates at the full 48 bits. ACC_W defaults to 40 and defines the overflow boundary. The flag is set when P[47:ACC_W-1] is not all-equal on a valid accumulate.** (default, medium impact, medium confidence)
  - options: Physical P is always 48 bits; ACC_W (default 40 = 32+8 guard) is the logical limit; overflow = P bits above ACC_W-1 not a sign extension (fabric reduction) / ACC_W default 48 with overflow detected from addend/accumulator/result sign bits / Physical accumulator truncated to ACC_W
  - Keeping all 48 bits keeps saturation correct even past the logical limit, and the check is a small registered reduction. Detecting a true 48-bit wrap would need extra sign logic.
- D10 Clearing of the sticky overflow flag: **Cleared by reset only; the flag stays set across clears.** (default, low impact, low confidence)
  - options: Cleared only by reset / Cleared by reset and by clear (per accumulation) / Separate flag-clear input
  - 'Sticky' most commonly means hold until reset, so a monitor cannot miss an event. Per-accumulation semantics are equally plausible for a beamformer.

**Done when:**
- The physical and logical accumulator widths are stated, with the guaranteed number of full-scale products at defaults (accounting for the RND offset).
- The overflow detection expression, its pipeline stage and its alignment to valid_out are specified.
- The set/clear rules of the sticky flag are given, including the interaction with a clear on the same cycle.

## S9. Synchronous active-high reset scope and 400 MHz clocking constraints

**Goal:** Define the single-clock domain and which registers take the sync active-high reset: valid/last/clear pipelines, flags, and the P register. Code resets so that synthesis maps them onto the DSP48E2 sync resets (RSTP etc.) and they do not block DSP absorption. List the timing-critical paths at 400 MHz.

**Feeds:** Clocking & Reset · **Depends on:** S5, S7

**Spec evidence:**
- [P2] "sync active-high reset"
- [P2] "400 MHz target, UltraScale+"

**Decisions:**
- D11 Reset scope: **Apply sync reset to the valid/clear/last pipelines, the sat and overflow flags, the output register and P (RSTP). A/B/M registers are not reset.** (default, low impact, high confidence)
  - options: Reset control pipelines, flags and PREG; leave A/B/M datapath regs unreset / Reset every register including all DSP internal registers / Reset only control/valid and flags
  - This ensures valid_out is low after reset and the accumulator starts from a known value. Leaving the operand regs unreset reduces reset fanout, which matters at 400 MHz, and maps directly onto DSP sync resets in inferred RTL.

**Done when:**
- A single clock is stated, with no CDC.
- A reset table lists every register group with its reset value or 'not reset', including the P reset value chosen in S7.
- Behaviour in the first cycles after reset deasserts is defined: no spurious valid_out, a known accumulator value, and clear flags.
- Critical paths are identified with their mitigation: PREG to saturation mux to output reg, the overflow reduction, and reset fanout.

## S10. Corner cases: -1 x -1, saturation edges, rounding ties, clear/valid interactions

**Goal:** Enumerate the boundary behaviours the RTL must get right, with the expected result for each.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S6, S7, S8, S9

**Spec evidence:**
- [P2] "output Q1.15, round to nearest, saturate (no wrap!) + flag when saturated"
- [P2] "clear input: starts a new accumulation with the current product (no dead cycle)"
- [P2] "sticky flag if the accumulator itself overflows anyway"

**Done when:**
- The list includes (-1)x(-1) = +1 saturating to 0x7FFF with sat set, plus positive and negative saturation.
- It includes a rounding carry that pushes the output into saturation.
- It includes exact ties for positive and negative values.
- It includes back-to-back clears, a clear with valid low, and a long gap in valid.
- It includes more than 256 full-scale products reaching the overflow boundary.
- It includes reset mid-accumulation, a first accumulation after reset without clear, and last coinciding with clear.
- Each case states the expected y, sat, overflow flag, valid_out and last_out.

## S11. Verification: bit-accurate reference model, alignment assertions and DSP-mapping/timing checks

**Goal:** Plan verification that proves numerical correctness against a bit-accurate model, cycle alignment of the sidebands, and the implementation requirements. The inferred RTL must map onto exactly one DSP48E2 with all pipeline registers, the clear mux and the pattern detector absorbed, and must meet 400 MHz on UltraScale+.

**Feeds:** Verification Plan · **Depends on:** S10

**Spec evidence:**
- [P2] "Must map onto one DSP48E2"
- [P2] "pass a `last` sideband through with the same latency"
- [P2] "400 MHz target, UltraScale+"

**Done when:**
- A reference-model spec is defined (wide integer accumulate, round, saturate), with a scoreboard compared on every valid_out.
- Directed tests exist for every S10 corner case, plus constrained-random streams with random valid gaps, clear and last, run across several parameter sets.
- Assertions cover: latency of valid, last and clear; no valid_out without valid_in; sat matching the reference; overflow flag stickiness.
- Coverage points cover clear/valid combinations, saturation in both directions, and ties.
- A synthesis mapping check confirms, from the utilization/mapping report, that there is exactly one DSP48E2, that AREG/BREG/MREG/PREG are absorbed, that OPMODE is dynamic, that the pattern detector is used, and that there are no fabric adders in the accumulate path.
- 400 MHz timing closure is checked on a representative UltraScale+ part.

## S12. Record defaulted choices and open questions for the spec author

**Goal:** Collect every still-defaulted decision (D1, D3, D6-D11) with its chosen default and question. Record D2 as settled by the user's answer. Collect implicit assumptions: operands are two's complement, there is a single clock, last is only delayed and not otherwise interpreted, outputs hold when invalid, and inference is the mapping method with the fallback risk noted.

**Feeds:** Assumptions & Open Questions · **Depends on:** S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11

**Spec evidence:**
- [P2] "pipeline ~3 stages: input regs / multiply / accumulate."
- [P2] "sticky flag if the accumulator itself overflows anyway"

**Done when:**
- Each defaulted decision is listed with its default, its question and the sections affected if it changes.
- D2 is recorded as decided by the user, together with the residual inference risk and how S11 checks it.
- Implicit assumptions are listed separately from open questions.
- Every open question is referenced by the section it affects.

## Assumptions (defaults not confirmed by the user)

- D1 Parameter legality enforcement for single-DSP mapping: Elaboration-time checks restrict widths so the design always fits one DSP48E2. The wider operand goes on the 27-bit port. Fractional-bit parameters set the output slice. (medium impact, high confidence)
- D3 Output register after PREG (total latency): Latency 4. A fabric output register follows the saturation/round-select mux, and valid_out and last_out are delayed by 4. (medium impact, medium confidence)
- D6 Clear asserted on a cycle where valid is low: clear is qualified by valid and is ignored on invalid beats. (medium impact, medium confidence)
- D7 Rounding implementation and tie behaviour: Round-half-up (ties toward +inf). The 2^(slice_lsb-1) constant is injected via the W mux on the clearing sample, so every running output is round(sum). (medium impact, medium confidence)
- D8 Saturation detection location: Use the DSP48E2 pattern detector. If neither PATTERNDETECT nor PATTERNBDETECT is set, saturate to max or min by sign (P[47]) and assert sat. (medium impact, high confidence)
- D9 Accumulator width and overflow-detection boundary: The DSP accumulates at the full 48 bits. ACC_W defaults to 40 and defines the overflow boundary. The flag is set when P[47:ACC_W-1] is not all-equal on a valid accumulate. (medium impact, medium confidence)
- D10 Clearing of the sticky overflow flag: Cleared by reset only; the flag stays set across clears. (low impact, low confidence)
- D11 Reset scope: Apply sync reset to the valid/clear/last pipelines, the sat and overflow flags, the output register and P (RSTP). A/B/M registers are not reset. (low impact, high confidence)
