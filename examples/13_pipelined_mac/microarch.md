# Micro-architecture: `fxp_mac`

## 1. Overview

`fxp_mac` is a pipelined signed fixed-point multiply-accumulate unit. Each valid input pair
`(a, b)` is multiplied and added to a full-precision accumulator. A running, rounded,
saturated result is emitted for every valid input. `in_clr` starts a new sum with the
current product, so back-to-back accumulations have no dead cycle.

Key features:
- Parameterized operand, accumulator and output widths; default Q1.15 × Q1.15 → Q10.30 accumulator (40 bits) → Q1.15 output.
- Three arithmetic register stages (input, multiply, accumulate) that map one-to-one onto DSP48E2 `AREG/BREG`, `MREG` and `PREG`, plus one fabric stage for saturation. Total latency is 4 cycles.
- Round-to-nearest (ties toward +∞) at zero cost, by pre-loading the rounding bias into the accumulator on clear.
- Output saturation with a per-sample `out_sat` flag; sticky accumulator-overflow flag.
- Valid-only pipeline (no back-pressure) with a `last` sideband matched in latency.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | 400 MHz clock. |
| `rst` | in | 1 | Synchronous active-high reset. |
| **Input** | | | |
| `in_valid` | in | 1 | `in_a`/`in_b`/`in_clr`/`in_last` are valid. |
| `in_a` | in | `A_W` | Signed operand a (two's complement, `A_FRAC` fractional bits). |
| `in_b` | in | `B_W` | Signed operand b (`B_FRAC` fractional bits). |
| `in_clr` | in | 1 | This sample starts a new accumulation (acc = a·b instead of acc + a·b). |
| `in_last` | in | 1 | Sideband; delayed to `out_last`. |
| **Output** | | | |
| `out_valid` | out | 1 | `out_y` holds the result for one input sample. |
| `out_y` | out | `OUT_W` | Rounded, saturated running sum (`OUT_FRAC` fractional bits). |
| `out_sat` | out | 1 | `out_y` was saturated for this sample. |
| `out_last` | out | 1 | `in_last` of the corresponding sample. |
| `out_acc` | out | `ACC_W` | Full-precision accumulator (debug/chaining), includes rounding bias (§5). |
| **Status** | | | |
| `acc_ovf` | out | 1 | Sticky: the accumulator wrapped. |
| `err_clr` | in | 1 | Clears `acc_ovf`. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `A_W` | 16 | 2–27 | Width of a (≤27 for a single DSP48E2 A port). |
| `B_W` | 16 | 2–18 | Width of b (≤18 for the B port). |
| `A_FRAC` | 15 | 0..`A_W-1` | Fractional bits of a. |
| `B_FRAC` | 15 | 0..`B_W-1` | Fractional bits of b. |
| `ACC_W` | 40 | `A_W+B_W`–48 | Accumulator width (≤48 for the DSP P register). |
| `OUT_W` | 16 | 2..`ACC_W` | Output width. |
| `OUT_FRAC` | 15 | ≤ `A_FRAC+B_FRAC` | Output fractional bits. |
| `P_W` | `A_W+B_W` | derived | Product width (32). |
| `SHIFT` | `A_FRAC+B_FRAC-OUT_FRAC` | derived | Output right-shift (15). |
| `GUARD` | `ACC_W-P_W` | derived | Guard bits (8). |
| `RND` | `SHIFT>0 ? 1<<(SHIFT-1) : 0` | derived | Rounding bias (`0x4000`). |

**Guard-bit check.** The largest-magnitude product is (−1)·(−1) = +2^30 in Q2.30 (fits in
32 signed bits). A 40-bit accumulator holds up to 2^39 − 1, so 2^39/2^30 = 512 full-scale
products can be summed without overflow. That meets the "≥256" requirement. An elaboration
check `$error`s if `ACC_W < P_W + 8`.

## 4. Block Diagram

```
          S1 (AREG/BREG)        S2 (MREG)              S3 (PREG)                  S4 (fabric)
in_a --->[a1_q]--+
                 |  (x)  ---->[p2_q]--sext--+
in_b --->[b1_q]--+                          |   +------+                       +-----------+
                                            +-->|  +   |---->[acc_q]--+------->| saturate  |-->[y4_q]---> out_y
                                     RND --+--->| mux  |       ^      |        | >>>SHIFT  |-->[sat4_q]-> out_sat
                                           |    +--^---+       |      +-> out_acc+-----------+
                                           |       |  clr2     |
                                           |       +-----------+  (acc feedback)
in_valid->[v1]--------->[v2]------------------------->[v3]------------------------->[v4]---> out_valid
in_clr -->[c1]--------->[c2]
in_last ->[l1]--------->[l2]------------------------->[l3]------------------------->[l4]---> out_last
                                          overflow detect ---> acc_ovf_q (sticky)
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_dsp` | inferred (or `DSP48E2` primitive) | S1–S3: input regs, multiplier, accumulator with W-mux selecting `RND` (C port) or P feedback. |
| — (inline) | `sat_round` | S4: arithmetic shift and saturation in fabric. |
| — (inline) | valid/sideband pipe | 4-deep shift registers for `valid`, `last`; 2-deep for `clr`. |

## 5. Datapath

**Registers**

| Register | Width | Reset | Stage | Purpose |
|----------|-------|-------|-------|---------|
| `a1_q`, `b1_q` | `A_W`, `B_W` | 0 | S1 | Input operands (DSP AREG/BREG). |
| `v1_q`, `c1_q`, `l1_q` | 1 each | 0 | S1 | valid / clr / last. |
| `p2_q` | `P_W` | 0 | S2 | Product `a1_q * b1_q` (signed; DSP MREG). |
| `v2_q`, `c2_q`, `l2_q` | 1 each | 0 | S2 | |
| `acc_q` | `ACC_W` | `RND` | S3 | Accumulator (DSP PREG). |
| `v3_q`, `l3_q` | 1 each | 0 | S3 | |
| `y4_q` | `OUT_W` | 0 | S4 | Saturated output. |
| `sat4_q`, `v4_q`, `l4_q` | 1 each | 0 | S4 | |
| `acc_ovf_q` | 1 | 0 | – | Sticky overflow. |

The S1 and S2 data registers (`a1_q`, `b1_q`, `p2_q`) advance every cycle regardless of
valid, which keeps them DSP-friendly (no CE needed). Only `acc_q` is qualified by `v2_q`.

**Multiply (S2):** `p2_q <= $signed(a1_q) * $signed(b1_q)`. `p_ext` is `p2_q` sign-extended
to `ACC_W`.

**Accumulate (S3) with rounding bias**

```verilog
if (v2_q)
  acc_q <= c2_q ? (p_ext + RND) : (acc_q + p_ext);
```

Adding `RND` once at the start of each sum means `acc_q >>> SHIFT` (floor) equals
round-to-nearest of the true sum. No rounding adder is needed in S4. The reset value of
`acc_q` is also `RND`, so a sum started without `in_clr` after reset is rounded correctly
too. On the DSP48E2, `C = RND` and `OPMODE` selects `W = C` when `c2_q`, else `W = P`.

**Overflow detect (S3):** only in the accumulate case (`!c2_q`). If `acc_q` and `p_ext`
have the same sign and the sum's sign differs, set `acc_ovf_q`. (The clear case cannot
overflow because `|p_ext + RND| < 2^(ACC_W-1)`.)

**Saturate (S4)**

```verilog
wire signed [ACC_W-SHIFT-1:0] r = acc_q >>> SHIFT;            // rounded value
wire hi  = (r >  $signed({1'b0, {(OUT_W-1){1'b1}}}));         // > MAX
wire lo  = (r <  $signed({1'b1, {(OUT_W-1){1'b0}}}));         // < MIN
y4_q   <= hi ? {1'b0,{(OUT_W-1){1'b1}}} : lo ? {1'b1,{(OUT_W-1){1'b0}}} : r[OUT_W-1:0];
sat4_q <= v3_q & (hi | lo);
```

In hardware, `hi`/`lo` reduce to "bits `r[ACC_W-SHIFT-1:OUT_W-1]` are not all equal",
with the sign bit picking the direction. That is a 10-bit AND/OR reduction (2 LUT levels).

## 6. Control Logic

There is no FSM; control is entirely the valid/sideband pipe.

| Signal | Equation |
|--------|----------|
| `v1_q, c1_q, l1_q` | `<= in_valid, in_valid & in_clr, in_last` |
| `v2_q, c2_q, l2_q` | `<= v1_q, c1_q, l1_q` |
| `acc_en` | `v2_q` (DSP `CEP`) |
| `acc_sel_rnd` | `c2_q` (DSP `OPMODE[W]` = C vs P) |
| `v3_q, l3_q` | `<= v2_q, l2_q` |
| `v4_q, l4_q` | `<= v3_q, l3_q` |
| `out_valid, out_last` | `= v4_q, l4_q & v4_q` |
| `acc_ovf_q` | `<= err_clr ? 0 : acc_ovf_q \| (v2_q & !c2_q & ovf)` |

`in_clr` is masked with `in_valid`, so a stray clear on an invalid cycle has no effect.

## 7. Timing & Pipeline

- **Latency:** 4 cycles from `in_valid` to `out_valid` (S1, S2, S3, S4).
- **Throughput:** 1 MAC per clock; clear costs no extra cycle.
- **Critical paths at 400 MHz (2.5 ns):** multiplier and 48-bit ALU are inside the hard DSP pipeline; the fabric path is `acc_q` (PREG) → shift (wiring) → 10-bit saturation reduction → output mux → `y4_q`, about 3 LUT levels.

Cycle example (Q1.15; values in hex; `RND = 0x4000`):

| Cyc | in (a, b, clr) | p2_q (S2) | acc_q (S3, during) | out_y (S4) | out_sat | Note |
|-----|----------------|-----------|--------------------|------------|---------|------|
| 0 | `4000, 4000, 1` | – | `RND` | – | – | 0.5 × 0.5, new sum |
| 1 | `4000, 4000, 0` | – | – | – | – | |
| 2 | `6000, 6000, 0` | `1000_0000` | – | – | – | 0.75 × 0.75 |
| 3 | `8000, 2000, 1` | `1000_0000` | `00_1000_4000` | – | – | −1 × 0.25, new sum |
| 4 | – | `2400_0000` | `00_2000_4000` | `2000` (0.25) | 0 | |
| 5 | – | `F000_0000` | `00_4400_4000` | `4000` (0.5) | 0 | |
| 6 | – | – | `FF_F000_4000` | `7FFF` | 1 | 1.0625 saturated |
| 7 | – | – | – | `E000` (−0.25) | 0 | |

## 8. Clocking & Reset

- Single clock `clk`; no CDC.
- `rst` is synchronous active-high, matching DSP48E2 `RSTx` pins (which are synchronous). Valid/sideband flops and `acc_ovf_q` must be reset. Data registers are reset for determinism, but the reset can be removed from `a1_q`/`b1_q`/`p2_q` if routing congestion matters, because `out_valid` qualifies everything.
- `acc_q` resets to `RND`, not 0 (see §5).

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| (−1) × (−1) | Product +1.0 (`0x4000_0000`), representable in Q2.30; output saturates to `0x7FFF` (+0.99997), `out_sat=1`. |
| Ties in rounding | x.5 LSB rounds toward +∞ (e.g. −0.5 LSB → 0). This is documented; convergent rounding is an open option (§11). |
| More than 512 full-scale products | Accumulator wraps, `acc_ovf` sets (sticky); outputs are wrong until the next `in_clr`. |
| Saturation is not sticky | The accumulator keeps full precision; the output recovers once the sum is back in range. |
| `in_clr` on an invalid cycle | Ignored (masked with `in_valid`). |
| Gaps in `in_valid` | `acc_q` holds; output only on valid samples. |
| `SHIFT = 0` | `RND = 0`; no rounding needed. |

## 10. Verification Plan

**Reference model:** an arbitrary-precision integer model computing `sum = Σ a·b` per
accumulation, `y = clamp(floor((sum + RND) / 2^SHIFT))`, plus the overflow flag from a
wrapped `ACC_W`-bit sum.

**Directed tests**
1. The §7 sequence: exact values and `out_sat`.
2. Corner operands: all combinations of {MIN, −1 LSB, 0, +1 LSB, MAX}².
3. Rounding ties: products giving exactly ±0.5 LSB of output.
4. Positive and negative saturation, then recovery without `in_clr`.
5. 512 products of (−1)(−1): no overflow; the 513th sets `acc_ovf`.
6. Back-to-back clears (each sample a 1-element sum).
7. Valid gaps between accumulating samples.
8. Parameter sets: (16,16,40,16), (18,25,48,24), (8,8,24,8).

**Random:** 1M random samples with random `in_clr` (5%), random valid duty cycle; scoreboard
on `out_y`, `out_sat`, `out_last`.

**Assertions**

```systemverilog
a_latency: assert property (@(posedge clk) disable iff(rst) in_valid |-> ##4 out_valid);
a_novalid: assert property (@(posedge clk) disable iff(rst) !in_valid |-> ##4 !out_valid);
a_sat_rng: assert property (@(posedge clk) disable iff(rst)
             out_valid && !out_sat |-> ($signed($past(out_acc)) >>> SHIFT) == $signed(out_y));
// out_y (S4) lags acc_q (S3) by one cycle, hence $past.
a_ovf_sticky: assert property (@(posedge clk) disable iff(rst) acc_ovf && !err_clr |=> acc_ovf);
```

**Implementation check:** post-synthesis utilization shows exactly 1 DSP48E2 and no fabric
multipliers. Timing passes at 400 MHz.

## 11. Assumptions & Open Questions

1. **"~3 stages" vs. saturation.** The three arithmetic stages map onto the DSP. Saturation needs a fabric stage, giving 4 cycles total latency. Folding saturation into S3 would put a 40-bit add plus compare in one cycle and break the DSP mapping, so the extra cycle is the deliberate choice.
2. **Rounding mode** is round-half-up (ties toward +∞), implemented via the bias pre-load. If symmetric or convergent rounding is required, S4 needs the discarded bits and an extra adder.
3. **Output each cycle** is interpreted as "every valid sample produces the running sum". A dot-product-only output (valid only on `last`) can be obtained by the consumer gating with `out_last`.
4. **Accumulator wrap is not saturated**, only flagged. The DSP ALU cannot saturate natively, and 8 guard bits exceed the stated requirement.
5. **No back-pressure**, as stated. If a downstream stall appears later, add a global CE to all stages (DSP CE pins) rather than a skid buffer.
6. `out_acc` includes the `RND` bias. Consumers that chain accumulators must subtract it or use `out_y`.
