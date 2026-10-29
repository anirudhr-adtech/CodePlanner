# Micro-architecture: `intc32`

## 1. Overview

`intc32` merges 32 interrupt sources into one level `irq` for the RV32 core. It provides
per-source priority (0–7, 0 = disabled), enable and edge/level trigger configuration, a global
threshold, and a CLAIM/COMPLETE protocol with hardware-tracked nesting.

Key features:
- Per-source optional 2-FF synchronizer (`SYNC_MASK` parameter) for asynchronous GPIO lines.
- Rising-edge detection with a latched pending bit for edge sources; live level for level sources.
- 32-input priority max-finder tree (ties go to the lowest ID), registered once for timing.
- In-service stack built from one valid bit plus a stored source ID per priority level (7 levels). The effective threshold is `max(THRESHOLD, highest in-service level)`, so only strictly higher priorities can preempt.
- A claim re-checks eligibility in the same cycle, so a stale tree result is never handed out.
- Source-to-`irq` latency: 3 cycles (level, synchronized) or 4 cycles (edge, synchronized).

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | 100 MHz system clock. |
| `rst_n` | in | 1 | Active-low reset; async assert, sync de-assert. |
| **Sources / core** | | | |
| `src` | in | 32 | Interrupt request lines (active high). Bits in `SYNC_MASK` may be asynchronous. |
| `irq` | out | 1 | To core external-interrupt input; high while a claimable interrupt exists. |
| **Register bus** | | | |
| `addr` | in | 6 | Byte address; [1:0] ignored. |
| `wdata` | in | 32 | Write data. |
| `we` | in | 1 | Write strobe. |
| `re` | in | 1 | Read strobe (CLAIM read has side effects). |
| `rdata` | out | 32 | Registered read data, valid the cycle after `re`. |

**Register map**

| Offset | Name | Access | Description |
|--------|------|--------|-------------|
| 0x00–0x0C | PRIO0–PRIO3 | RW | PRIOk[4j+2:4j] = priority of source 8k+j (j = 0..7); bit 4j+3 reserved (reads 0). |
| 0x10 | ENABLE | RW | 1 = source enabled. |
| 0x14 | TRIGGER | RW | 1 = rising edge, 0 = level (active high). |
| 0x18 | PENDING | RO | Effective pending vector (edge latch or live level), before enable/priority. |
| 0x1C | PEND_CLR | WO | Write 1 to clear the edge-pending latch of that source. |
| 0x20 | THRESHOLD | RW | [2:0]; only priorities > THRESHOLD can interrupt. |
| 0x24 | CLAIM | RO* | [31] VALID, [4:0] ID. Read claims the interrupt (side effect). Returns 0 if none. |
| 0x28 | COMPLETE | WO | [4:0] ID of the finished interrupt. |
| 0x2C | INSERVICE | RO | [7:1] in-service level bits, [10:8] effective threshold. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `NSRC` | 32 | fixed | Number of sources (register layout assumes 32). |
| `SYNC_MASK` | 32'hFFFF_FFFF | any | Bit i = 1 inserts a 2-FF synchronizer on `src[i]`. Clear for sources that are synchronous to `clk` to save 2 cycles. |
| `PRIO_W` | 3 | fixed | Priority width (levels 0–7). |
| `ID_W` | 5 | derived | `$clog2(NSRC)`. |

## 4. Block Diagram

```
 src[31:0]
    |
 +--------------+  s_lvl[31:0]  +--------------+  pend[31:0]  +-----------+ elig[31:0] +-------------------+
 | u_sync       |-------------->| u_pend       |------------->| eligible  |----------->| u_tree            |
 | 2FF per bit  |               | edge detect  |              | pend&en&  |  prio[*]   | 32->1 max-finder  |
 | (SYNC_MASK)  |               | edge latch   |              | prio!=0   |----------->| tie: lowest ID    |
 +--------------+               | level bypass |              +-----------+            +-------------------+
                                +--------------+                                            | (reg)
                                   ^      ^ clear (claim / PEND_CLR)          best_vld_q, best_id_q, best_prio_q
                                   |      |                                                   |
 bus --> +-----------------------------------------------+   eff_thr   +---------+           v
         | u_regs: PRIO/ENABLE/TRIGGER/THRESHOLD         |<------------| u_isr   |   irq = best_vld_q &&
 <-- rdata| CLAIM logic (recheck) / COMPLETE decode       |------------>| stack   |        best_prio_q > eff_thr
         +-----------------------------------------------+ claim/compl | 7 x {v, |
                                                                       |  id[5]} |
                                                                       +---------+
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_sync` | `sync_2ff` (generate per bit) | Synchronize `src[i]` when `SYNC_MASK[i]`. |
| `u_pend` | `intc_pending` | Rising-edge detect, edge-pending latches, pending mux. |
| `u_tree` | `intc_maxfind` | Five-level compare/select tree + output register. |
| `u_isr` | `intc_isr_stack` | In-service bits, stored IDs, effective threshold. |
| `u_regs` | `intc_regs` | Config registers, CLAIM/COMPLETE handling, read mux. |

## 5. Datapath

**Registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `s1`, `s2` | 32 each | 0 | Synchronizer stages (bypassed per `SYNC_MASK`). |
| `s_q` | 32 | 0 | Previous synchronized level, for edge detection. |
| `epend_q` | 32 | 0 | Edge-pending latches. |
| `prio_q[0:31]` | 3 each | 0 | Source priorities. |
| `en_q` | 32 | 0 | Enable mask. |
| `trig_q` | 32 | 0 | Trigger type (1 = edge). |
| `thr_q` | 3 | 0 | THRESHOLD. |
| `best_vld_q` | 1 | 0 | Tree output: some eligible source exists. |
| `best_id_q` | 5 | 0 | Tree output: winning ID. |
| `best_prio_q` | 3 | 0 | Tree output: winning priority. |
| `isr_v[7:1]` | 7 | 0 | In-service flag per priority level. |
| `isr_id[1:7]` | 5 each | 0 | ID that was claimed at each level. |
| `rdata_q` | 32 | 0 | Registered read data. |

**Pending and eligibility**

```verilog
wire [31:0] s_lvl = (SYNC_MASK & s2) | (~SYNC_MASK & src);
wire [31:0] rise  = s_lvl & ~s_q;
// set wins over clear: a new edge in the claim/clear cycle is a new event
epend_n = trig_q & ((epend_q & ~claim_clr_vec & ~pclr_vec) | rise);   // cleared when level-type
pend    = (trig_q & epend_q) | (~trig_q & s_lvl);
elig[i] = pend[i] & en_q[i] & (prio_q[i] != 3'd0);
```

**Max-finder tree.** Each node merges a lower-ID candidate `L` with a higher-ID candidate
`H`: `take_L = L.v & (~H.v | (L.p >= H.p))`. The node output is `take_L ? L : H`, and `v` is
`L.v | H.v`. Five levels (32 → 16 → 8 → 4 → 2 → 1) give each node a 3-bit compare and an
8-bit mux, about 12–15 gate levels in total. That fits easily in 10 ns, and the result is
registered into `best_*_q`.

**Effective threshold**

```verilog
// highest set in-service level (priority encoder over isr_v[7:1]), 0 if none
isr_top = isr_v[7] ? 7 : isr_v[6] ? 6 : ... : isr_v[1] ? 1 : 0;
eff_thr = (isr_top > thr_q) ? isr_top : thr_q;
irq     = best_vld_q & (best_prio_q > eff_thr);
```

## 6. Control Logic

There is no multi-state FSM. The behaviour is defined by two register-access operations and
the in-service stack.

**CLAIM (read of 0x24)**

```verilog
wire claim_rd = re && addr[5:2]==4'h9;
wire claim_ok = claim_rd && best_vld_q && elig[best_id_q]
                         && (prio_q[best_id_q] > eff_thr);         // recheck against live state
wire [2:0] L  = prio_q[best_id_q];
on claim_ok:  isr_v[L] <= 1;  isr_id[L] <= best_id_q;
              if (trig_q[best_id_q]) claim_clr_vec[best_id_q] = 1;  // edge pending cleared
rdata_q <= claim_ok ? {1'b1, 26'b0, best_id_q} : 32'b0;
```

Invariant: `L > eff_thr ≥ isr_top`, so a claim always sets a currently free, strictly higher
level. The in-service stack is therefore always a valid LIFO.

**COMPLETE (write of 0x28, ID = `wdata[4:0]`)**

| Condition | Action |
|-----------|--------|
| Some level L with `isr_v[L] && isr_id[L]==ID` | Clear `isr_v[L]` for the highest such L. |
| No match | Ignored (no error). |

**Nesting example**

| Step | Event | `isr_v[7:1]` | eff_thr (THRESHOLD = 0) | Claimable |
|------|-------|-------------|-------------------------|-----------|
| 1 | UART (ID 4, prio 3) pending → claim → 4 | 0000100 | 3 | prio ≥ 4 |
| 2 | Timer (ID 1, prio 6) edge → claim → 1 | 0100100 | 6 | prio 7 only |
| 3 | GPIO (ID 20, prio 5) pending | 0100100 | 6 | not claimable, `irq=0` |
| 4 | COMPLETE 1 | 0000100 | 3 | GPIO now claimable, `irq=1` |
| 5 | claim → 20 | 0010100 | 5 | prio ≥ 6 |
| 6 | COMPLETE 20, COMPLETE 4 | 0000000 | 0 | any prio ≥ 1 |

**Register writes:** PRIO/ENABLE/TRIGGER/THRESHOLD take effect next cycle. The tree result
reflects them one cycle after that. PEND_CLR clears `epend_q` bits (a simultaneous new edge
wins).

## 7. Timing & Pipeline

- **Pipeline:** `src` → s1 → s2 (sync) → `epend_q` (edge only) → tree → `best_*_q` → `irq` (combinational from `best_*_q`, `isr_v`, `thr_q`).
- **Latency (`src` rise to `irq`):** edge + sync = 4 cycles; level + sync = 3 cycles; edge without sync = 2 cycles; level without sync = 1 cycle.
- **CLAIM:** read data one cycle after `re`. `irq` drops on the cycle after the claim edge if nothing else is claimable, because `isr_v` updates at the claim edge.
- **Throughput:** one CLAIM or COMPLETE per bus cycle; back-to-back claims are safe because of the re-check.

Edge source (ID 7, prio 3, enabled, synchronized), with values after each clock edge:

| Edge | `src[7]` | `s1[7]` | `s2[7]` | `s_q[7]` | `epend_q[7]` | `best_vld_q`/`best_id_q` | `irq` |
|------|----------|---------|---------|----------|--------------|--------------------------|-------|
| E0 | 1 (pulse) | 0 | 0 | 0 | 0 | 0 / – | 0 |
| E1 | 0 | 1 | 0 | 0 | 0 | 0 / – | 0 |
| E2 | 0 | 0 | 1 | 0 | 0 | 0 / – | 0 |
| E3 | 0 | 0 | 0 | 1 | **1** (rise seen) | 0 / – | 0 |
| E4 | 0 | 0 | 0 | 0 | 1 | **1 / 7** | **1** |
| E5 | CPU `re` CLAIM | | | | 1 | 1 / 7 | 1 |
| E6 | | | | | 0 (cleared) | 1 / 7 (clears at E7) | 0 (`isr_v[3]=1` → eff_thr=3, not > 3) |

A single-cycle pulse that is synchronous to `clk` survives the 2-FF stage; see §11 for
asynchronous pulses.

## 8. Clocking & Reset

- **Single clock domain.** The only crossings are the `src` bits marked in `SYNC_MASK`. Each is a single-bit level crossing using 2-FF synchronizers (`ASYNC_REG`); every bit is handled independently, so no bus coherency is needed.
- **Reset:** all configuration clears to 0 (all sources disabled, priority 0, level-triggered, threshold 0). The in-service stack and pending latches clear, and `irq=0`.
- Synchronizer flops reset to 0; a source that is high at reset release shows as a level (or a rising edge one cycle after release, if configured as edge).

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| CLAIM with nothing claimable | Returns 0 (VALID=0); no state change. |
| Tree result stale (source dropped or was masked in the last cycle) | Re-check fails → CLAIM returns 0; software retries or returns from the trap. |
| Higher-priority source arrives in the cycle of a claim | Lower one may be claimed (tree is 1 cycle behind); the higher one preempts on the next cycle as nesting allows. |
| New edge in the same cycle as its claim | Edge latch stays set (set wins); the source becomes pending again. |
| Level source still high after COMPLETE | Re-interrupts immediately (by design). |
| COMPLETE with an ID that is not in service | Ignored. |
| Same ID in service at two levels (priority raised while in service) | COMPLETE clears the highest matching level first (LIFO). |
| Out-of-order COMPLETE (lower level first) | That level is cleared; the effective threshold stays at the highest remaining level. |
| Priority changed while in service | Stored level is used for completion; no corruption. |
| Trigger switched edge → level | `epend_q` bit cleared, live level used. |
| Asynchronous pulse shorter than one clock period | May be missed (see §11). |

## 10. Verification Plan

**Testbench:** SystemVerilog with a transaction-level reference model that holds pending,
priority, in-service stack and threshold, and predicts every CLAIM result and the `irq`
level each cycle. The bus driver performs CLAIM/COMPLETE sequences that mimic a nesting
ISR.

**Directed tests**
1. Reset: all registers 0, `irq=0`, CLAIM returns 0.
2. Single level source, priority 1..7, threshold sweep 0..7 → `irq` only when prio > threshold.
3. Edge source: pulse → pending latched → claim clears → PENDING bit 0.
4. Tie-break: sources 3, 9 and 30 at the same priority → claims return 3, then 9, then 30 (with completes in between).
5. Full nesting: claim at 1, 2, ..., 7 in sequence; complete in reverse; check INSERVICE and `irq` at each step.
6. Preemption blocking: an equal-priority source does not raise `irq` while that level is in service.
7. PEND_CLR on a stuck edge pending.
8. Back-to-back CLAIM reads in consecutive cycles → second returns the correct next source or 0.
9. Latency: measure `src`→`irq` for every SYNC_MASK/trigger combination.

**Random:** random source activity, random config writes and an ISR model that claims,
optionally re-enables nesting, and completes after a random delay; 1M cycles compared
against the model.

**Assertions (SVA)**

```systemverilog
a_irq_def:     assert property (@(posedge clk) disable iff(!rst_n) irq == (best_vld_q && best_prio_q > eff_thr));
a_claim_level: assert property (@(posedge clk) disable iff(!rst_n) claim_ok |-> !isr_v[prio_q[best_id_q]]);
a_claim_hi:    assert property (@(posedge clk) disable iff(!rst_n) claim_ok |-> prio_q[best_id_q] > isr_top);
a_prio0_never: assert property (@(posedge clk) disable iff(!rst_n) claim_ok |-> prio_q[best_id_q] != 0);
a_edge_clr:    assert property (@(posedge clk) disable iff(!rst_n)
                 claim_ok && trig_q[best_id_q] && !rise[best_id_q] |=> !epend_q[$past(best_id_q)]);
```

**Coverage:** every source claimed at least once; each priority level in service; nesting
depth 0–7; ties at each priority; claim returning 0 due to stale tree; COMPLETE no-match;
same-cycle edge and claim.

## 11. Assumptions & Open Questions

1. **Priority 0 = disabled**, and **THRESHOLD masks ≤ THRESHOLD** ("ignore everything at or below"), as in the spec.
2. **Nesting tracked in hardware** with one in-service slot per priority level. That gives exactly 7 nesting levels and needs no separate stack pointer. The core must still re-enable its global interrupt enable inside the ISR for preemption to happen.
3. **Edge = rising edge, level = active high** only; no polarity register. Add one if active-low peripherals appear.
4. **Asynchronous GPIO pulses** must be at least 1.5 clock periods wide to be captured reliably. The GPIO block is assumed to stretch shorter events, or to provide its own latched interrupt.
5. **CLAIM VALID bit** at [31] is used because ID 0 is a real source. Software must check VALID, not ID ≠ 0.
6. **PRIO packing:** 4-bit fields (3 used), 8 sources per register, for easy shift/mask in firmware.
7. **One-cycle tree staleness** is accepted to keep the 32-input compare tree off the bus read path. The re-check guarantees correctness; only optimality can be one cycle late.
