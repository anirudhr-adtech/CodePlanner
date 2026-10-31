# MA plan: 14_fir_filter

## S1. Frame FIR-01 as one symmetric channel filter per DDC channel, DSP-count-first

**Goal:** Write the Overview: what one FIR-01 instance does, how the 32 instances relate to the DDC, and the design priorities (DSP count over latency, sustained 1 sample/clk at 491.52 MHz).

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P2] "each channel needs a linear-phase"
- [P2] "one new sample every clock, 491.52 MHz on a Zynq UltraScale+ RFSoC"
- [P2] "so DSP slice count matters more than latency."
- [P4] "Throughput: one input and one output sample per clock, sustained."

**Decisions:**
- D1 Channel-to-hardware mapping: **One fully parallel FIR instance per channel; 32 instances in the system** (decided)
  - options: One fully parallel FIR instance per channel (32 instances) / Time-multiplexed FIR shared across channels
  - Each channel delivers one new sample every fabric clock, so there is no spare cycle to time-share multipliers between channels.

**Done when:**
- Overview states one instance = one channel, 1 in/1 out sample per clock at 491.52 MHz
- Priority order (DSP count > fabric > latency) is stated explicitly
- Per-instance and 32-channel DSP48E2 counts for N_TAPS=16 and N_TAPS=64 are quoted (ceil(N_TAPS/2) per instance)
- Overview states that each instance owns its coefficient bank and that the wrapper may broadcast writes to all 32 channels

## S2. Define the N_TAPS generic, sample/valid ports and per-instance coefficient write port

**Goal:** Specify the Parameters (N_TAPS default 16, legal 2-64, widths) and the Interface (sample in/valid, sample out/valid, per-instance coefficient write port and commit driven by the existing AXI-Lite wrapper, which may broadcast).

**Feeds:** Parameters, Interface · **Depends on:** S1

**Spec evidence:**
- [P4] "Linear-phase FIR with a configurable number of taps N (16 for the first product; up to 64 later)."
- [P4] "Both even and odd N must be supported."
- [P4] "Input: 16-bit signed samples, Q1.15. Output: 16-bit signed, Q1.15."
- [P4] "Coefficients: 18-bit signed, Q1.17."
- [P4] "They must be loadable at run time from the control processor (via a simple write port; the AXI-Lite wrapper exists already)."
- [P4] "The upstream decimator provides a valid signal."

**Decisions:**
- D2 How N is configured: **N_TAPS is a synthesis parameter (default 16, legal range 2-64, even or odd); only coefficient values change at run time, via the shadow bank and commit** (decided)
  - options: Synthesis-time generic N (structure sized per build) / Runtime-programmable tap count up to 64
  - User answer Q1. Sizing the DSP chain to N_TAPS is what saves DSPs for the N=16 product.
- D12 Coefficient storage across the 32 channels: **Each instance holds its own coefficient bank and write port; the wrapper can broadcast one write to all channels** (decided)
  - options: Independent coefficient bank per instance (wrapper may broadcast writes) / Single coefficient bank shared by all 32 channels
  - User answer Q2 accepted this default; keeps the core self-contained and supports per-channel filters.

**Done when:**
- Parameter table lists N_TAPS (default 16, legal 2-64), input/coef/output widths and formats, and derived values (number of DSPs = ceil(N_TAPS/2), coefficient address width)
- Elaboration-time check rejects N_TAPS outside 2..64
- Port table gives name, direction, width, format and clock domain for every port, including coefficient address/data/write-enable/commit
- Odd vs even N_TAPS effect on the address map is stated (ceil(N_TAPS/2) unique coefficients written)
- Broadcast usage by the wrapper (same write/commit to all instances) is described as a wrapper feature requiring no core change

## S3. Make the transposed-vs-systolic call with symmetric pre-adder mapping on DSP48E2

**Goal:** Choose the filter structure, justify it against transposed form, and draw the Block Diagram showing the DSP chain, pre-adder operand sourcing, cascades and centre-tap handling for odd N_TAPS.

**Feeds:** Block Diagram, Datapath, Overview · **Depends on:** S2

**Spec evidence:**
- [P5] "The team has argued about using the transposed form or a systolic"
- [P5] "Please make the call in the micro-architecture and document why."
- [P4] "Exploit symmetry to halve the multiplier count."
- [P4] "The design should map onto DSP48E2 slices using dedicated cascade routing where possible."
- [P4] "The impulse response is always symmetric, h[k] = h[N-1-k]."

**Decisions:**
- D3 Filter structure: **Systolic symmetric form using the DSP48E2 pre-adder, ACOUT/ACIN delay-line cascade and PCOUT/PCIN adder chain** (default, high impact, high confidence)
  - options: Systolic symmetric form: A/ACOUT input cascade + PCOUT partial-sum cascade, pre-adder per DSP / Transposed form: input broadcast to all DSPs, partial sums in PCOUT chain
  - Transposed form needs the input broadcast to every DSP (high fanout at 491.52 MHz across up to 32 DSPs) and does not combine cleanly with the pre-adder for symmetry. Systolic keeps routing on dedicated cascades and uses ceil(N/2) DSPs with no fabric adder tree, at ~N/2 extra cycles of latency the spec tolerates.
- D4 Odd-N centre tap: **Centre tap occupies the last DSP of the chain with the D (second pre-adder) operand held at zero, keeping a uniform cascade** (default, low impact, high confidence)
  - options: Centre tap in a DSP with pre-adder second operand forced to zero / Centre tap with pre-adder bypassed / Centre tap multiplier in fabric
  - Keeps every stage identical and the cascade unbroken; costs no extra DSP versus ceil(N/2).

**Done when:**
- A comparison table (DSP count, fabric adders, input fanout, cascade usage, latency, Fmax risk) for transposed vs systolic is written with the final call
- Block diagram shows ceil(N_TAPS/2) DSP48E2 stages, ACOUT and PCOUT cascades, the source of the mirrored sample for each pre-adder (e.g. fabric SRL delay line), and the output stage
- Even and odd N_TAPS chains are both drawn or described, including the centre-tap stage and the N_TAPS=2/3 degenerate chains
- Fabric resources outside DSPs (delay lines, registers) are estimated for N_TAPS=16 and N_TAPS=64

## S4. Bit-growth analysis from Q1.15 x Q1.17 through the 48-bit P cascade

**Goal:** Derive the width at every datapath point (pre-adder, multiplier, cascade accumulator, output) and justify that nothing overflows inside the DSP chain for N_TAPS up to 64.

**Feeds:** Datapath, Parameters · **Depends on:** S3

**Spec evidence:**
- [P4] "Provide a bit-growth analysis and justify the internal widths."
- [P4] "Coefficients: 18-bit signed, Q1.17."
- [P4] "Input: 16-bit signed samples, Q1.15. Output: 16-bit signed, Q1.15."

**Decisions:**
- D5 Internal precision policy: **Full precision: 17-bit pre-add (Q2.15), 35-bit product (Q3.32), accumulation in the 48-bit P cascade (about 40 bits needed for 32 products), quantised once at the output** (default, medium impact, high confidence)
  - options: Full precision through pre-adder, multiplier and P cascade; single quantisation at the output / Truncate/round partial sums inside the chain
  - All widths fit DSP48E2 natively (27-bit pre-adder, 27x18 multiplier, 48-bit P), so full precision is free and the output is exactly one rounding of the ideal result.

**Done when:**
- A width table lists format (Qm.n) and bit count at pre-adder out, multiplier out and accumulator for general N_TAPS, with worst-case values for N_TAPS=16 and N_TAPS=64
- Worst-case accumulator magnitude is bounded both by generic ceil(log2(N_TAPS/2)) growth and by sum|h[k]|, and shown to fit 48 bits
- Bit position of the Q1.15 output inside the accumulator (LSBs dropped, guard bits above) is identified

## S5. Round-to-nearest and saturating output stage

**Goal:** Specify how the accumulator is rounded to 16 bits and saturated (not wrapped), and where those operations live (DSP vs fabric), without breaking 491.52 MHz timing.

**Feeds:** Datapath, Timing & Pipeline · **Depends on:** S4

**Spec evidence:**
- [P4] "Outputs must saturate, not wrap."
- [P4] "Rounding to nearest."

**Decisions:**
- D6 Rounding implementation and tie behaviour: **Round-half-up by injecting a constant 2^(k-1) into the first DSP of the chain (C port or RND), then truncate; saturation by guard-bit compare (fabric or DSP pattern detect) in a registered output stage** (default, low impact, medium confidence)
  - options: Round-half-up: add 0.5 LSB constant injected at the head of the P cascade / Convergent (round-half-even) using DSP pattern detect / Rounding adder in fabric after the chain
  - Bias injection costs zero extra adders or cycles; half-up tie bias is negligible with 17 dropped bits. Saturation detection is a small registered stage that keeps timing.

**Done when:**
- Rounding constant value and injection point are specified
- Saturation condition (guard bits not all equal to sign) and clamp values 0x7FFF/0x8000 are specified
- Number of pipeline registers in the output stage is stated and fed into the latency count

## S6. Glitch-free shadow-bank commit aligned to the systolic skew

**Goal:** Design the per-instance coefficient write path so every output sample uses only old or only new coefficients, accounting for each output's partial products being formed in different DSPs on different cycles.

**Feeds:** Control Logic, Interface, Timing & Pipeline · **Depends on:** S3, S2

**Spec evidence:**
- [P4] "Changing the filter must not create a glitch: no output sample may be computed from a mix of old and new coefficients."
- [P4] "They must be loadable at run time from the control processor (via a simple write port; the AXI-Lite wrapper exists already)."

**Decisions:**
- D7 Coefficient update mechanism: **Shadow coefficient registers per tap; on commit, a swap token travels along the chain one stage per partial-sum delay, loading each DSP's active B register exactly when the first post-commit output's partial sum reaches it** (default, high impact, high confidence)
  - options: Shadow bank + commit token that propagates down the DSP chain with the same skew as the partial sum / Shadow bank swapped in all DSPs on the same cycle / Flush/blank the output during reload
  - The user answer confirms a shadow bank plus commit; a simultaneous swap in a systolic chain would mix coefficients for in-flight outputs, so a skewed token places the boundary between two output samples with no blanking.
- D8 Commit trigger: **Explicit commit strobe on the write port; writes before commit only touch the shadow bank** (default, medium impact, medium confidence)
  - options: Explicit commit write (strobe/register) after loading all coefficients / Implicit commit on write to the last coefficient address
  - Consistent with the user's 'shadow bank and commit' wording; allows partial or out-of-order reloads and atomic broadcast commits across all 32 channels from the wrapper.
- D9 Clock domain of the coefficient write port: **Write port is synchronous to the fabric clock; the existing AXI-Lite wrapper performs any clock crossing** (default, medium impact, medium confidence)
  - options: Write port synchronous to the 491.52 MHz fabric clock (wrapper does CDC) / Write port in the AXI-Lite clock domain with CDC inside FIR-01
  - Keeps FIR-01 single-clock; with broadcast, one crossing in the wrapper serves all 32 instances.

**Done when:**
- Timing diagram shows commit, token propagation and the first output sample fully using new coefficients
- Argument that token delay per stage equals partial-sum delay per stage for both even and odd N_TAPS
- Behaviour for writes arriving while a swap is in flight, and for commit with no prior writes, is specified
- Use of DSP48E2 B1/B2 registers or fabric shadow registers is chosen and resource cost stated
- A broadcast commit is shown to switch all 32 channels on the same input sample index

## S7. Behaviour when the decimator valid drops

**Goal:** Define how in_valid gaps affect filter state and out_valid so the filter output equals the FIR of the valid-only sample stream.

**Feeds:** Control Logic, Corner Cases & Error Handling, Timing & Pipeline · **Depends on:** S3, S6

**Spec evidence:**
- [P4] "The upstream decimator provides a valid signal."
- [P4] "In this product it is always high once running, but the filter must behave sensibly if it drops."

**Decisions:**
- D10 Valid handling strategy: **Global clock-enable driven by registered in_valid with replicated CE registers to meet fanout at 491.52 MHz; out_valid tracks the enabled pipeline so outputs equal the FIR of valid samples only** (default, medium impact, medium confidence)
  - options: Global clock-enable: whole pipeline (DSP CE pins, delay lines, swap token, output stage) advances only when in_valid=1; out_valid is the delayed valid / Free-running pipeline treating invalid cycles as zero samples / Free-running pipeline with out_valid only (state corrupted by gaps)
  - Keeps the systolic alignment intact across gaps and gives mathematically correct output; DSP48E2 has per-register CE pins so cost is mostly CE fanout.

**Done when:**
- Every stateful element is classified as CE-gated or free-running, including the coefficient swap token
- out_valid generation and its relation to in_valid are specified with a timing diagram showing a gap
- CE fanout/replication plan for ceil(N_TAPS/2) DSPs at 491.52 MHz is stated
- Latency is stated in valid samples (constant) as well as clock cycles when valid=1

## S8. Pipeline register map and constant-latency budget under 100 ns

**Goal:** Enumerate every register from input to output and prove a constant latency below 49 cycles (100 ns at 491.52 MHz) for N_TAPS up to 64.

**Feeds:** Timing & Pipeline · **Depends on:** S3, S5, S7

**Spec evidence:**
- [P4] "Latency is not critical (< 100 ns is fine) but must be constant and documented."
- [P2] "one new sample every clock, 491.52 MHz on a Zynq UltraScale+ RFSoC"

**Done when:**
- Register-by-register list (input reg, A1/A2, AD, M, P per stage, output stage) is given
- Latency formula L(N_TAPS) in cycles is given and evaluated for N_TAPS=2, 16 and 64, with ns values, all <100 ns
- Statement that latency is fixed per build and independent of coefficient values, commit timing and valid pattern (in valid samples)
- DSP48E2 internal registers used to meet 491.52 MHz are identified (fully pipelined mode)

## S9. Single fabric clock and minimal-reset strategy for DSP-heavy datapath

**Goal:** Define the clock and reset scheme: one 491.52 MHz clock, which registers are reset, and what outputs and coefficient banks look like during and after reset.

**Feeds:** Clocking & Reset · **Depends on:** S7

**Spec evidence:**
- [P2] "one new sample every clock, 491.52 MHz on a Zynq UltraScale+ RFSoC"
- [P4] "In this product it is always high once running, but the filter must behave sensibly if it drops."

**Decisions:**
- D11 Reset scope: **Synchronous active-high reset on control state only; datapath/DSP registers not reset; out_valid held low until the pipeline has filled with valid samples; coefficient banks retain or reset to a documented default** (default, low impact, medium confidence)
  - options: Synchronous reset on control only (valid pipeline, swap token, commit state); datapath and DSP registers unreset, outputs masked by out_valid / Synchronous reset of all registers including DSP pipeline and coefficient banks
  - Xilinx guidance for high-Fmax DSP datapaths; avoids reset fanout to ceil(N/2) DSPs in each of 32 instances while outputs remain well-defined via out_valid.

**Done when:**
- Clock domain(s) listed with frequency; any CDC delegated to the wrapper is stated
- Reset polarity, synchronicity and the list of reset vs non-reset registers are given
- Post-reset contents of active and shadow coefficient banks and out_valid behaviour until pipeline fill are specified

## S10. Corner cases: overflow coefficients, swap during gaps, N_TAPS extremes

**Goal:** Enumerate and resolve edge conditions so the MA defines behaviour everywhere.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S5, S6, S7, S9

**Spec evidence:**
- [P4] "Outputs must saturate, not wrap."
- [P4] "Both even and odd N must be supported."
- [P4] "Changing the filter must not create a glitch: no output sample may be computed from a mix of old and new coefficients."

**Done when:**
- Cases covered: full-scale inputs with sum|h|>1 (saturation), -1.0 inputs pre-added (-2.0 fits 17 bits), N_TAPS=2/3/63/64, commit while valid is low, back-to-back commits, broadcast commit while one channel's valid differs, writes to out-of-range addresses
- Each case has a defined outcome and the mechanism that guarantees it

## S11. Verification plan against a bit-exact golden model

**Goal:** Plan verification proving bit-exactness, glitch-free swaps, constant latency, saturation and valid-gap behaviour across N_TAPS.

**Feeds:** Verification Plan · **Depends on:** S8, S10

**Spec evidence:**
- [P4] "Provide a bit-growth analysis and justify the internal widths."
- [P4] "Latency is not critical (< 100 ns is fine) but must be constant and documented."
- [P4] "no output sample may be computed from a mix of old and new coefficients."

**Done when:**
- Golden model defined (integer, full precision, same rounding/saturation) and compare is bit-exact
- Tests listed: impulse/step response, random data, full-scale saturation, coefficient swap with check that every output matches old or new model exactly, valid gaps random and bursty, reset mid-stream
- Parameter sweep includes even and odd N_TAPS at least 2,3,15,16,63,64, plus a negative elaboration test for out-of-range N_TAPS
- Multi-instance test with wrapper broadcast verifies all channels switch on the same sample
- Checks for constant latency and for DSP48E2 inference/cascade usage in synthesis reports (DSP count = ceil(N_TAPS/2), timing met at 491.52 MHz)

## S12. Record assumptions and open questions for the DDC team

**Goal:** Collect resolved answers, defaulted decisions and spec gaps into the Assumptions & Open Questions section.

**Feeds:** Assumptions & Open Questions · **Depends on:** S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11

**Spec evidence:**
- [P5] "Please make the call in the micro-architecture and document why."
- [P4] "the AXI-Lite wrapper exists already"

**Done when:**
- Resolved items (N_TAPS generic 2-64 default 16; per-instance coefficient bank with wrapper broadcast) are recorded as settled with their source answers
- Every remaining defaulted decision (D3-D11) appears with its chosen default and the question to the spec author
- Assumptions about the wrapper (clock domain, commit strobe, broadcast) and coefficient gain (sum|h| range) are listed
- Each open item notes which MA sections change if the answer differs

## Assumptions (defaults not confirmed by the user)

- D3 Filter structure: Systolic symmetric form using the DSP48E2 pre-adder, ACOUT/ACIN delay-line cascade and PCOUT/PCIN adder chain (high impact, high confidence)
- D4 Odd-N centre tap: Centre tap occupies the last DSP of the chain with the D (second pre-adder) operand held at zero, keeping a uniform cascade (low impact, high confidence)
- D5 Internal precision policy: Full precision: 17-bit pre-add (Q2.15), 35-bit product (Q3.32), accumulation in the 48-bit P cascade (about 40 bits needed for 32 products), quantised once at the output (medium impact, high confidence)
- D6 Rounding implementation and tie behaviour: Round-half-up by injecting a constant 2^(k-1) into the first DSP of the chain (C port or RND), then truncate; saturation by guard-bit compare (fabric or DSP pattern detect) in a registered output stage (low impact, medium confidence)
- D7 Coefficient update mechanism: Shadow coefficient registers per tap; on commit, a swap token travels along the chain one stage per partial-sum delay, loading each DSP's active B register exactly when the first post-commit output's partial sum reaches it (high impact, high confidence)
- D8 Commit trigger: Explicit commit strobe on the write port; writes before commit only touch the shadow bank (medium impact, medium confidence)
- D9 Clock domain of the coefficient write port: Write port is synchronous to the fabric clock; the existing AXI-Lite wrapper performs any clock crossing (medium impact, medium confidence)
- D10 Valid handling strategy: Global clock-enable driven by registered in_valid with replicated CE registers to meet fanout at 491.52 MHz; out_valid tracks the enabled pipeline so outputs equal the FIR of valid samples only (medium impact, medium confidence)
- D11 Reset scope: Synchronous active-high reset on control state only; datapath/DSP registers not reset; out_valid held low until the pipeline has filled with valid samples; coefficient banks retain or reset to a documented default (low impact, medium confidence)
