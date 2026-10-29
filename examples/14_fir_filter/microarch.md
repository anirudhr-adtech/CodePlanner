# Micro-architecture: `fir_sym_systolic`

## 1. Overview

`fir_sym_systolic` is an N-tap linear-phase (symmetric) FIR filter that processes one
sample per clock. It uses a **symmetric systolic** structure. Each of the `M = ceil(N/2)`
taps is one DSP48E2 slice that pre-adds the two input samples sharing a coefficient,
multiplies by that coefficient, and adds the result into a dedicated `PCIN→PCOUT` cascade.

Key features:
- `M` multipliers instead of `N` (8 DSPs for N = 16), with every inter-DSP connection on dedicated cascade routing apart from one broadcast "tail" sample.
- Constant latency `L = M + 4` cycles (12 cycles = 24.4 ns for N = 16 at 491.52 MHz).
- Run-time coefficient reload through a shadow bank with a **staggered commit**: the switch-over is sample-exact, and no output mixes old and new coefficients.
- Full-precision 38-bit accumulation (for N = 16), round-to-nearest via a bias injected at the head of the cascade, and output saturation.
- Clock-enable driven by `in_valid`, so gaps in the input stream are handled correctly.

**Form decision (R5 / "decision required")**

| Criterion | Direct form + adder tree | Transposed form | Symmetric systolic (chosen) |
|-----------|--------------------------|-----------------|-----------------------------|
| Multipliers using symmetry | M | N (pairing needs a separate delay line, which removes the benefit) | **M** |
| Input fanout | N (delay line taps) | N (broadcast to every multiplier) | **M** (tail sample only) |
| Adder structure | fabric tree, irregular routing | DSP cascade | **DSP cascade** |
| Latency | ~log2(M)+4 | ~4 | M+4 |
| Fmax risk at 491 MHz | adder tree in fabric | broadcast net with fanout N | low |

Latency is explicitly not critical (R7), while DSP count and Fmax are (32 channels at
491 MHz). Systolic wins.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | Sample clock (491.52 MHz). |
| `rst` | in | 1 | Synchronous active-high reset (maps onto DSP `RST*` pins). |
| **Sample stream** | | | |
| `in_valid` | in | 1 | Sample valid; used as the global clock-enable `ce`. |
| `in_x` | in | `DATA_W` | Input sample, Q1.15. |
| `out_valid` | out | 1 | `out_y` holds a new output sample. |
| `out_y` | out | `OUT_W` | Output sample, Q1.15, rounded and saturated. |
| `out_sat` | out | 1 | `out_y` was saturated. |
| **Coefficient port** | | | |
| `coef_we` | in | 1 | Write `coef_wdata` to shadow coefficient `coef_addr`. |
| `coef_addr` | in | `CA_W` | Index k = 0..M−1 (h[k] = h[N−1−k]). |
| `coef_wdata` | in | `COEF_W` | Coefficient, Q1.17. |
| `coef_commit` | in | 1 | Pulse: switch the active bank to the shadow bank. |
| `coef_busy` | out | 1 | Commit in progress; shadow writes are ignored. |
| `coef_err` | out | 1 | Sticky: a shadow write was attempted while busy. Cleared by reset. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `N_TAPS` | 16 | 2–64 | Filter length (even or odd). |
| `DATA_W` | 16 | 2–26 | Sample width (≤26 so the pre-add result fits the 27-bit pre-adder). |
| `COEF_W` | 18 | 2–18 | Coefficient width (DSP B port). |
| `OUT_W` | 16 | 2..`ACC_W` | Output width. |
| `OUT_SHIFT` | 17 | 0..`ACC_W-OUT_W` | Right shift from accumulator to output (Q2.32 product → Q1.15). |
| `M` | `(N_TAPS+1)/2` | derived | Number of DSP stages (8). |
| `ODD` | `N_TAPS % 2` | derived | 1 if a centre tap exists. |
| `AD_W` | `DATA_W+1` | derived | Pre-adder output width (17). |
| `PROD_W` | `AD_W+COEF_W` | derived | Product width (35). |
| `ACC_W` | `PROD_W+$clog2(M)` | derived | Accumulator width (38; ≤48). |
| `L` | `M+4` | derived | Latency in accepted samples (12). |
| `CA_W` | `max(1,$clog2(M))` | derived | Coefficient address width (3). |
| `RND` | `OUT_SHIFT>0 ? 1<<(OUT_SHIFT-1) : 0` | derived | Rounding bias. |

**Bit-growth analysis (R6), N = 16**

| Point | Range (worst case) | Bits | Format |
|-------|-------------------|------|--------|
| x | [−2^15, 2^15−1] | 16 | Q1.15 |
| pre-add x_a + x_b | [−2^16, 2^16−2] | 17 | Q2.15 |
| coefficient | [−2^17, 2^17−1] | 18 | Q1.17 |
| product | magnitude ≤ 2^16·2^17 = 2^33 | 35 | Q3.32 |
| sum of M = 8 products | magnitude ≤ 2^36 (+RND) | 38 | Q6.32 |
| output after `>>> 17` | saturate to [−2^15, 2^15−1] | 16 | Q1.15 |

The 38-bit width covers the absolute worst case: every coefficient at full scale and the
input correlated with the coefficient signs. A real low-pass with unity DC gain has
Σ|h| ≈ 1.1–1.5, so it uses about 1 integer bit above Q1. The extra integer bits only cost
DSP P-register bits, which are free up to 48. Saturation catches out-of-band overload.
`ACC_W ≤ 48` holds for every legal N (64 taps: 35 + 5 = 40).

## 4. Block Diagram

```
           ce = in_valid
in_x -->[sr0]->[sr1]->[sr2]->[sr3]-> ... ->[sr(N-2)]->[sr(N-1)]---+ tail (broadcast, fanout M)
          |             |                       |                  |
          v             v                       v                  |
       +------+      +------+               +--------+             |
 tail->| +    |      | +    |       ...     | +      |<------------+
       | AD0  |      | AD1  |               | AD(M-1)|  (centre: tail operand = 0 if ODD)
       | x c0 |      | x c1 |               | x cM-1 |
       | M0   |      | M1   |               | M(M-1) |
 RND ->| P0   |----->| P1   |---->  ...  -->| P(M-1) |--> [sat/shift] --> [y_q] --> out_y
       +------+ PCOUT+------+ PCOUT         +--------+                  [sat_q]--> out_sat
        DSP 0         DSP 1                  DSP M-1
          ^             ^                       ^
        cact0         cact1                   cact(M-1)   <-- shadow bank + staggered commit
```

(The forward delay line advances by 2 registers per stage: stage k takes `sr[2k]`.)

| Instance | Module | Purpose |
|----------|--------|---------|
| `g_tap[k].u_dsp` | inferred DSP48E2 (A/D pre-adder, B coef, PCIN cascade) | Stage k: AD, M and P registers. |
| `u_dline` | SRL/register chain | `sr[0..N-1]`. On DSP48E2 the even positions map to the A1/A2 registers through the ACIN/ACOUT cascade; odd lengths use fabric flops. |
| `u_coef` | `fir_coef_bank` | Shadow bank, active bank, commit stagger chain. |
| `u_out` | inline | Shift, saturation, `out_valid` fill counter. |

## 5. Datapath

All registers below are clock-enabled by `ce = in_valid` unless marked "free".

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `sr[i]`, i = 0..N−1 | `DATA_W` | 0 | Input delay line; `sr[0]` is the input register. |
| `ad_q[k]` | `AD_W` | 0 | Pre-adder output, stage k. |
| `m_q[k]` | `PROD_W` | 0 | Product, stage k. |
| `p_q[k]` | `ACC_W` | 0 | Cascade partial sum, stage k. |
| `y_q` | `OUT_W` | 0 | Output sample. |
| `sat_q` | 1 | 0 | Output saturated. |
| `vld_q` (free) | 1 | 0 | `out_valid`. |
| `fill_q` | `$clog2(L)` | 0 | Counts accepted samples until the pipeline is primed. |
| `c_sh[k]` (free) | `COEF_W` | 0 | Shadow coefficient bank. |
| `c_act[k]` | `COEF_W` | 0 | Active coefficients (DSP BREG). |
| `pend_q` (free) | 1 | 0 | Commit requested, waiting for the next `ce`. |
| `sw_q[k]` | 1 | 0 | Commit stagger chain. |

**Per-stage equations** (k = 0..M−1):

```verilog
sr[0]   <= in_x;          sr[i] <= sr[i-1];                       // i = 1..N-1
tail    =  sr[N-1];
ad_q[k] <= sr[2*k] + ((ODD && k == M-1) ? 0 : tail);              // pre-add
m_q[k]  <= ad_q[k] * c_act[k];                                    // signed
p_q[0]  <= RND + m_q[0];                                          // cascade head
p_q[k]  <= p_q[k-1] + m_q[k];                                     // k >= 1
```

**Why this computes the FIR.** With every register clocked (`ce = 1`), stage k sees
`sr[2k] = x(t−1−2k)` and `tail = x(t−N)`. For the output index `n` that stage k serves at
that moment, `n = t−1−k`, so the pair is `x(n−k)` and `x(n−(N−1−k))`: exactly the two
samples sharing h[k]. The partner index is the same for every stage, so a single broadcast
tail suffices. For odd N the centre stage's forward sample *is* the centre sample, so its
tail operand is forced to 0. The cascade adds one cycle per stage, which matches the
1-cycle skew between stages, so `p_q[M−1]` holds y(n) at a constant latency. (The structure
was checked against direct convolution in a bit-true model for N = 2, 3, 5, 15, 16.)

**Output stage**

```verilog
r      = p_q[M-1] >>> OUT_SHIFT;                 // RND already included => round-to-nearest
y_q   <= sat(r, OUT_W);   sat_q <= (r > MAX) || (r < MIN);
```

## 6. Control Logic

**Valid / fill.** There is no FSM. `out_valid` is the registered `ce`, gated until the
pipeline is primed:

```verilog
vld_q  <= ce && (fill_q == L-1);
fill_q <= (ce && fill_q != L-1) ? fill_q + 1 : fill_q;
```

The first `out_valid` output is therefore y(0) = h[0]·x(0) (the delay line was reset to
zero, so earlier samples count as 0). That is the true start-up response of the filter.

**Coefficient commit (R3).** For a sample-exact switch, stage k must start using its new
coefficient exactly k+1 accepted samples after the commit point, because that is when stage
k computes the product for the first new output.

| Step | Logic |
|------|-------|
| Request | `pend_q <= ce ? 1'b0 : (pend_q \| coef_commit)`: a commit arriving without `ce` is remembered. |
| Launch | On every `ce`: `sw_q[0] <= pend_q \| coef_commit` (a 1-sample pulse, because `pend_q` clears on the same `ce`). |
| Propagate | On each `ce`: `sw_q[k] <= sw_q[k-1]`. |
| Apply | On each `ce`: `if (sw_q[k]) c_act[k] <= c_sh[k]`. |
| Busy | `coef_busy = pend_q \| (\|sw_q)`; `coef_we` while busy is dropped and sets `coef_err`. |

With a continuous stream, the first output that uses the new coefficients is the response
to the sample accepted in the same cycle as `coef_commit`, and every earlier output uses
only old coefficients. (Verified in a bit-true model: a stagger of k+1 is the only value
that gives a clean switch.)

Commit state per stage:

| State | Condition | `c_act[k]` |
|-------|-----------|------------|
| OLD | `sw_q[j] == 0` for all j ≤ k since commit | old h[k] |
| SWITCH | `sw_q[k] == 1` and `ce` | loads `c_sh[k]` |
| NEW | after SWITCH | new h[k] |

## 7. Timing & Pipeline

- **Latency:** `L = M + 4` accepted samples, i.e. 12 clocks = 24.4 ns for N = 16, well under the 100 ns of R7. Breakdown: `sr[0]` (1) + `ad_q` (1) + `m_q` (1) + M cascade stages + `y_q` (1).
- **Throughput:** 1 sample per clock.
- **Critical paths:** inside the DSP (pre-adder, multiplier and 48-bit adder are each registered); the tail broadcast `sr[N−1]` → M D-ports (fanout 8; can be duplicated); and the saturation logic (a reduction over `ACC_W−OUT_SHIFT−OUT_W+1` = 6 bits plus a mux).

Impulse response, N = 4 (M = 2, L = 6), h = [2, 3, 3, 2], RND = 0 and OUT_SHIFT = 0 for
illustration, `in_valid = 1`:

| Cyc | in_x | sr[0..3] | ad_q[0..1] | m_q[0..1] | p_q[0..1] | y_q | Note |
|-----|------|----------|------------|-----------|-----------|-----|------|
| 0 | 1 | 0 0 0 0 | 0 0 | 0 0 | 0 0 | 0 | impulse |
| 1 | 0 | 1 0 0 0 | 0 0 | 0 0 | 0 0 | 0 | |
| 2 | 0 | 0 1 0 0 | 1 0 | 0 0 | 0 0 | 0 | |
| 3 | 0 | 0 0 1 0 | 0 0 | 2 0 | 0 0 | 0 | |
| 4 | 0 | 0 0 0 1 | 0 1 | 0 0 | 2 0 | 0 | tail = 1 |
| 5 | 0 | 0 0 0 0 | 1 1 | 0 3 | 0 2 | 0 | |
| 6 | 0 | 0 0 0 0 | 0 0 | 2 3 | 0 3 | **2** | y(0) = h0 at cycle L |
| 7 | 0 | | | 0 0 | 2 3 | **3** | y(1) = h1 |
| 8 | 0 | | | | 0 2 | **3** | y(2) = h2 |
| 9 | 0 | | | | | **2** | y(3) = h3 |

## 8. Clocking & Reset

- Single clock domain. The coefficient port is assumed to be in the same domain: the AXI-Lite wrapper runs on `clk`, or the wrapper does the CDC. See §11.
- `rst` is synchronous active-high. It resets the delay line, DSP pipeline registers, `fill_q`, `vld_q`, the commit logic and both coefficient banks (to 0, so the filter outputs zero until it is programmed).
- Clock-enable: every register on the sample path uses `ce = in_valid`; DSP CE pins (`CEA`, `CEAD`, `CEM`, `CEP`, `CEB`) are tied to `ce`. The shadow bank and `pend_q` are not clock-enabled.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| `in_valid` drops | The whole pipeline freezes; the filter state is preserved and no samples are lost or duplicated. Outputs of the last L−1 samples stay inside until more samples arrive. If needed, drain by feeding zeros (§11). |
| Commit while no samples flow | `pend_q` holds the request; the switch is aligned to the next accepted sample. |
| Shadow write during commit | Ignored, `coef_err` set. Software polls `coef_busy` (busy for at most M+1 accepted samples). |
| Two commits back-to-back | The second is absorbed while busy (`pend_q` already set or chain active); recommend one commit per update. |
| Odd N | Centre stage uses no tail; its coefficient is h[(N−1)/2]. |
| N = 2 | M = 1; only the cascade head exists. |
| Input at full scale with adversarial coefficients | No internal overflow (38-bit analysis); output saturates, `out_sat` = 1. |
| `coef_addr ≥ M` | Write ignored (no error). |

## 10. Verification Plan

**Reference model:** a bit-true Python/C model of the equations in §5 (already used to check
the timing table and commit stagger), plus a floating-point `numpy.convolve` model to check
that error vs. ideal stays within ±0.5 LSB when there is no saturation.

**Directed tests**
1. Impulse response for N = 16, 15, 2, 3: output equals h[0..N−1] after L samples.
2. Step response: steady-state equals the rounded Σh.
3. Full-scale sinusoid at DC, mid-band and stopband frequencies: compare amplitude with the design response.
4. Saturation: adversarial input (sign of h) with full-scale coefficients → `out_sat` and clipped values.
5. Coefficient commit with a continuous stream: every output before the boundary matches the old-h model and every output after matches the new-h model.
6. Commit while `in_valid = 0`; shadow write during busy → `coef_err`.
7. Random `in_valid` gaps: the output sequence equals the gap-free output sequence.

**Random:** 1M random samples, random coefficient sets, random commits, random valid gaps.

**Assertions**

```systemverilog
a_lat:    assert property (@(posedge clk) disable iff(rst)
            in_valid && fill_q == L-1 |=> out_valid);
a_novld:  assert property (@(posedge clk) disable iff(rst) !in_valid |=> !out_valid);
a_busyw:  assert property (@(posedge clk) disable iff(rst) coef_busy && coef_we |=> coef_err);
a_stable: assert property (@(posedge clk) disable iff(rst) !in_valid |=> $stable(p_q[M-1]));
```

**Coverage:** even and odd N; commit with and without `ce` gaps; saturation positive and
negative; gap during commit stagger; `fill_q` reaching L−1.

**Implementation:** utilization shows M DSP48E2 per channel with PCOUT→PCIN cascades;
timing met at 491.52 MHz with the tail net duplicated if its fanout fails timing.

## 11. Assumptions & Open Questions

1. **Coefficient port clock.** Assumed to be synchronous with `clk`. If the AXI-Lite wrapper runs on a slower clock, the shadow bank should live in that domain, with `coef_commit` crossing via a pulse synchronizer. Since the shadow bank is quasi-static while not committing, it can be sampled safely.
2. **Rounding** is round-half-up through the RND bias at the cascade head.
3. **Valid-drop semantics.** Freezing (clock-enable) keeps the filter mathematically exact for gapped streams. The cost is that the last L−1 outputs need more input to come out. Confirm that is acceptable, or add a "flush" input that injects zeros.
4. **Start-up transient.** Outputs begin at y(0) with zero history. If the system wants to suppress the first N−1 transient outputs, raise the fill threshold to L−1+N−1.
5. **Coefficients reset to zero.** Software must program and commit before enabling traffic. An alternative is a parameterized default coefficient set loaded at reset.
6. **32 channels** are instantiated as 32 independent filters. A TDM/folded architecture would need fewer DSPs per channel only if the sample rate were below the clock rate, which it is not (R4).
