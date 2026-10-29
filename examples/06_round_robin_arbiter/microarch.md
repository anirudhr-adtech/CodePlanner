# Micro-architecture: `rr_arbiter`

## 1. Overview

`rr_arbiter` is an N-way round-robin arbiter with zero-latency (combinational) grant and
optional grant locking for multi-cycle transfers. It uses the **masked/unmasked dual
priority-select** scheme:
- A registered thermometer mask `mask_q` marks the requesters that rank above the last winner.
- When any masked request exists, the lowest-index masked request wins; otherwise the lowest-index unmasked request wins (the wrap-around).
- After each fresh arbitration, the mask moves past the winner, so the winner becomes lowest priority (R5).

A lock register holds the grant on its owner while `lock` is asserted (R6). An optional
lock-length counter forces release after `MAX_LOCK` cycles (R7). Requirement traceability
is given in §11.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | Clock. |
| `rst_n` | in | 1 | Asynchronous active-low reset (R10). |
| **Requesters** | | | |
| `req` | in | `N` | Request vector; `req[i]` from requester i. |
| `lock` | in | `N` | Lock request; meaningful only while `gnt[i] && req[i]`. |
| **Grant** | | | |
| `gnt` | out | `N` | One-hot grant (combinational, same cycle as `req`). |
| `gnt_valid` | out | 1 | `|gnt`. |
| `gnt_id` | out | `IDX_W` | Binary index of the granted requester (0 when `!gnt_valid`). |
| `gnt_locked` | out | 1 | 1 when this cycle's grant is a locked continuation (R9). |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `N` | 8 | 2–32 | Number of requesters (R1). |
| `MAX_LOCK` | 16 | 0–65535 | Max consecutive cycles of a locked grant; 0 = unlimited (R7). |
| `IDX_W` | `$clog2(N)` | derived | Width of `gnt_id`. |
| `LCNT_W` | `MAX_LOCK==0 ? 1 : $clog2(MAX_LOCK+1)` | derived | Lock counter width. |

## 4. Block Diagram

```
 req ---+------------------------------+
        |                              v
        |  mask_q --->[ AND ]--> masked_req --->[ LSB select ]--> gnt_m --+
        |                                                                 |
        +---------------------------->[ LSB select ]--> gnt_u ----------+ |
                                                                        v v
                                        any_masked ------------->[  mux  ]--> arb_gnt
                                                                         |
 owner_q, lock_q, req --> locked_now ------------------------------+    |
                                                                   v    v
                                                                [  mux  ]------> gnt
                                                                     |            |
                                                                     |   [onehot2bin]--> gnt_id
                                                                     v
                                     +----------------------------------------+
 lock ------------------------------>| state update: mask_q, owner_q, lock_q, |
                                     |               lock_cnt_q               |
                                     +----------------------------------------+
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_sel_m` | `lsb_select #(N)` | Isolates the lowest set bit of `masked_req` (`x & -x`). |
| `u_sel_u` | `lsb_select #(N)` | Isolates the lowest set bit of `req`. |
| `u_enc` | `onehot2bin #(N)` | OR-tree encoder for `gnt_id`. |
| — (inline) | state update | Mask, lock owner and lock counter registers. |

## 5. Datapath

**Registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `mask_q` | `N` | all 1s | Thermometer mask: bit j = 1 when requester j ranks above the last winner. |
| `owner_q` | `N` | 0 | One-hot owner of the previous cycle's grant. |
| `lock_q` | 1 | 0 | The previous grant requested a lock, so the grant is held this cycle. |
| `lock_cnt_q` | `LCNT_W` | 0 | Number of consecutive locked continuation cycles so far. |

**Combinational logic**

```verilog
wire [N-1:0] masked_req = req & mask_q;
wire         any_masked = |masked_req;
wire [N-1:0] gnt_m      = masked_req & (~masked_req + 1'b1);  // lowest set bit
wire [N-1:0] gnt_u      = req        & (~req        + 1'b1);
wire [N-1:0] arb_gnt    = any_masked ? gnt_m : gnt_u;

wire         locked_now = lock_q && |(owner_q & req);         // owner still requesting
assign       gnt        = locked_now ? owner_q : arb_gnt;
assign       gnt_valid  = |gnt;
assign       gnt_locked = locked_now;
```

**Next-state**

```verilog
wire lock_timeout = (MAX_LOCK != 0) && (lock_cnt_q == MAX_LOCK - 1) && locked_now;
wire lock_req     = |(gnt & lock & req);

owner_n    = gnt;
lock_n     = lock_req && !lock_timeout;
lock_cnt_n = locked_now ? lock_cnt_q + 1'b1 : '0;          // only used while lock_n
mask_n     = (!locked_now && |req) ? ~((arb_gnt << 1) - 1'b1)  // bits strictly above winner
                                   : mask_q;
```

When the winner is index N−1, `mask_n` becomes 0, so the next arbitration falls through to
the unmasked select (the wrap-around).

## 6. Control Logic

The control state is `{lock_q}` with `owner_q` as its data. It works as a 2-state machine:

| State | Condition | `gnt` source | Transitions |
|-------|-----------|--------------|-------------|
| ARB | `lock_q == 0`, or owner dropped `req` | `arb_gnt` (round-robin) | → HOLD if `arb_gnt & lock & req` is non-zero; else stay. |
| HOLD | `lock_q == 1` and `owner_q & req` | `owner_q` | → HOLD if `owner` keeps `lock` and no timeout; → ARB on `lock` de-assert, owner `req` drop, or `lock_timeout`. |

- `mask_q` moves only on a fresh arbitration (ARB with a winner). During HOLD it stays put; it already points past the owner because of the arbitration that started the lock.
- If the owner drops `req` while `lock_q=1`, that cycle falls back to ARB: another requester may be granted at once and the lock is released.

**Lock length accounting:** the initial arbitrated cycle plus `MAX_LOCK` continuation cycles
gives at most `MAX_LOCK+1` consecutive grants per burst. If R7 is read as counting the
first cycle, set the parameter to one less (§11).

## 7. Timing & Pipeline

- **Grant latency:** 0 cycles. `gnt` is combinational from `req`, `lock_q`, `owner_q` and `mask_q` (R4).
- **Throughput:** one grant per cycle; no idle cycles between different owners.
- **Fairness bound (R11):** with `n` active requesters, a continuously requesting master waits at most `n−1` other bursts. Worst-case wait = `(N−1)·(MAX_LOCK+1)` cycles.
- **Critical path:** `req` → `~x+1` (N-bit increment) → AND → 2:1 mux → `gnt`. For N=16 this is about 6–8 logic levels with a carry-lookahead increment. At 500 MHz in 7 nm, budget about 60% of the cycle for the arbiter, since `gnt` usually feeds a downstream mux; see §11 for the parallel-prefix option.

Cycle example (`N=4`, `MAX_LOCK=0`; bit order `[3:0]`):

| Cycle | req | lock | mask_q | lock_q | gnt | gnt_locked | mask_n | Note |
|-------|-----|------|--------|--------|-----|------------|--------|------|
| 0 | 1011 | 0000 | 1111 | 0 | 0001 | 0 | 1110 | 0 wins |
| 1 | 1011 | 0000 | 1110 | 0 | 0010 | 0 | 1100 | 1 wins |
| 2 | 1011 | 1000 | 1100 | 0 | 1000 | 0 | 0000 | 3 wins, requests lock |
| 3 | 1011 | 1000 | 0000 | 1 | 1000 | 1 | 0000 | locked continuation |
| 4 | 1011 | 0000 | 0000 | 1 | 1000 | 1 | 0000 | last locked cycle, lock released |
| 5 | 0011 | 0000 | 0000 | 0 | 0001 | 0 | 1110 | wrap: unmasked select |
| 6 | 0110 | 0000 | 1110 | 0 | 0010 | 0 | 1100 | |
| 7 | 0101 | 0000 | 1100 | 0 | 0100 | 0 | 1000 | |

## 8. Clocking & Reset

- Single clock domain; no CDC. The `req` and `lock` inputs must be synchronous to `clk`.
- `rst_n` is asynchronous and active-low (R10), with synchronized de-assertion at the top level. Reset gives `mask_q=all 1s` (requester 0 has priority first), `lock_q=0`, `owner_q=0`, `lock_cnt_q=0`.
- There are no grants during reset; `gnt` is combinational, so it is forced to 0 while `!rst_n` to stay clean (one extra AND gate).

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| `req == 0` | `gnt == 0`, `gnt_id == 0`, `gnt_valid == 0`; mask unchanged. |
| Single requester | Granted every cycle; the mask cycles harmlessly. |
| `lock[i]` without `gnt[i]` | Ignored. |
| Owner drops `req` while locked | Lock released; the same cycle is re-arbitrated (no dead cycle). |
| Lock timeout (`MAX_LOCK>0`) | After `MAX_LOCK` continuation cycles, `lock_n=0`; the next cycle re-arbitrates even with `lock` still high. The requester re-enters round-robin at the lowest priority. |
| Winner is N−1 | `mask_n=0`; the next cycle uses the unmasked path (wrap). |
| X on `req` | Assertion in simulation; may produce a non-one-hot `gnt`. |
| `N` not a power of 2 | Supported; `gnt_id` range is 0..N−1. |

## 10. Verification Plan

**Testbench:** a reference model in SystemVerilog: a priority pointer `p` and a loop from
`p` to `p+N−1` that picks the first `req`. It also tracks lock and timeout state, and is
compared with `gnt` every cycle.

**Directed tests**
1. All requesters continuously requesting → grants rotate 0,1,…,N−1,0.
2. Sparse requests: check the round-robin order skips idle requesters.
3. Lock for exactly `MAX_LOCK` continuation cycles, then forced release.
4. Lock released by dropping `lock`; lock released by dropping `req`.
5. Wrap from N−1 to 0 through the unmasked path.
6. `MAX_LOCK=0`: unlimited lock held for 1000 cycles.
7. Reset during a lock.

**Random:** random `req`/`lock` with various densities, 1M cycles, `N ∈ {2, 3, 8, 16, 32}`.

**Assertions (SVA)**

```systemverilog
a_onehot0:  assert property (@(posedge clk) disable iff(!rst_n) $onehot0(gnt));
a_gnt_req:  assert property (@(posedge clk) disable iff(!rst_n) (gnt & ~req) == 0);       // R3
a_work_cons:assert property (@(posedge clk) disable iff(!rst_n) |req |-> |gnt);           // no idle when requested
a_id:       assert property (@(posedge clk) disable iff(!rst_n) gnt_valid |-> gnt[gnt_id]);
a_lock_hold:assert property (@(posedge clk) disable iff(!rst_n)
              (gnt[i] && lock[i] && req[i] && !lock_timeout) ##1 req[i] |-> gnt[i]);   // R6
a_starve:   assert property (@(posedge clk) disable iff(!rst_n)
              req[i] |-> ##[0:WORST] (gnt[i] || !req[i]));                              // R11, WORST=(N-1)*(MAX_LOCK+1)
```

Formal: run `a_onehot0`, `a_gnt_req` and `a_starve` to proof with N=4, `MAX_LOCK=3`.

**Coverage:** each requester granted after each other requester (an N×N transition cross);
lock start, continuation and each release reason; wrap-around; every requester active alone.

## 11. Assumptions & Open Questions

1. **R5 is implemented as "winner gets lowest priority next"** (the mask moves past the winner), not "the pointer advances by one". This is the stronger fairness form and is starvation-free.
2. **Lock length:** `MAX_LOCK` counts continuation cycles, so a burst lasts at most `MAX_LOCK+1` cycles. Confirm with the interconnect team; set the parameter to `L−1` if the limit `L` includes the first cycle.
3. **R4 zero latency** means `gnt` is combinational from `req`. The consumer must not feed `gnt` back into `req` combinationally (that would create a loop); this is a system-level rule.
4. **R10 timing at 500 MHz for N=16:** the `~x+1` LSB isolation is implemented as a ripple or lookahead increment. If synthesis misses timing, replace it with a parallel-prefix (Kogge-Stone) OR-scan: `lsb = x & ~(prefix_or(x) << 1)`, which is `log2(N)` levels.
5. **No grant acknowledgement:** a grant cycle counts as a served transfer. If the resource can stall (e.g. `ready`), add a `gnt_ack` input that qualifies mask/lock updates.
6. **Traceability:** R1 §3; R2/R3 §5, §10; R4 §7; R5 §5–6; R6/R7 §6; R8/R9 §2; R10 §7–8; R11 §7, §10.
