# Micro-architecture: `async_fifo`

## 1. Overview

`async_fifo` moves 26-bit pixel words from the sensor clock domain (`wclk`, 74.25 MHz,
may stop) to the system clock domain (`rclk`, 200 MHz). The two clocks are fully
asynchronous. The design follows the classic Gray-pointer architecture:

- Each side keeps a binary pointer (for addressing and level arithmetic) and a registered Gray copy of it. Only the Gray copy crosses domains.
- A 2-FF synchronizer brings the Gray pointer into the other domain. Exactly one bit changes per increment, so a sample is always either the old or the new pointer, never a mix.
- `full` is computed only in the write domain and `empty` only in the read domain, from the local pointer and the synchronized remote pointer. Both are **pessimistic**: they may assert too early or de-assert too late, but data is never lost or duplicated.
- `almost_full` / `almost_empty` use the same synchronized pointers converted back to binary.
- Read data is registered: `rd_data` is valid the cycle after an accepted `rd_en`.
- Each side's reset also resets the other side, so the two pointers can never disagree after a one-sided reset.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Write domain** | | | |
| `wclk` | in | 1 | Write clock (sensor pixel clock, 74.25 MHz, may stop). |
| `wrst_n` | in | 1 | Write-side reset, active low, asynchronous. |
| `wr_en` | in | 1 | Write request; accepted when `!wr_full`. |
| `wr_data` | in | `DATA_W` | `{sof, eol, rgb[23:0]}` (format is opaque to the FIFO). |
| `wr_full` | out | 1 | FIFO full (as seen from the write domain). |
| `wr_almost_full` | out | 1 | Write-side level ≥ `AF_LEVEL`. |
| **Read domain** | | | |
| `rclk` | in | 1 | Read clock (200 MHz). |
| `rrst_n` | in | 1 | Read-side reset, active low, asynchronous. |
| `rd_en` | in | 1 | Read request; accepted when `!rd_empty`. |
| `rd_data` | out | `DATA_W` | Read data, registered; valid in the cycle after an accepted read. |
| `rd_valid` | out | 1 | High for one cycle when `rd_data` holds newly read data (convenience). |
| `rd_empty` | out | 1 | FIFO empty (as seen from the read domain). |
| `rd_almost_empty` | out | 1 | Read-side level ≤ `AE_LEVEL`. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `DATA_W` | 26 | 1–512 | Word width. |
| `DEPTH` | 32 | 4–4096, power of 2 | Number of entries. |
| `AF_LEVEL` | `DEPTH-4` | 1..`DEPTH` | `wr_almost_full` threshold. |
| `AE_LEVEL` | 4 | 0..`DEPTH-1` | `rd_almost_empty` threshold. |
| `SYNC_STAGES` | 2 | 2–4 | Synchronizer depth (3 recommended above ~500 MHz). |
| `ADDR_W` | `$clog2(DEPTH)` | derived | RAM address width (5). |
| `PTR_W` | `ADDR_W+1` | derived | Pointer width with wrap bit (6). |

## 4. Block Diagram

```
          wclk domain                          |                     rclk domain
                                               |
 wr_en ->+------------+ waddr  +-----------------------------+ raddr +------------+<- rd_en
 wr_data |  wptr_full |------->|  u_mem  DEPTH x DATA_W      |<------| rptr_empty |
         |  wbin,wgray|  we    |  write: wclk (sync)         |       | rbin,rgray |
         |  wfull,waf |------->|  read : async, into rd_data |       | rempty,rae |
         +------------+        +-------------+---------------+       +------------+
            |    ^                           |  rd_data_q (rclk)        |    ^
     wgray  |    | wq2_rgray                 v                    rgray |    | rq2_wgray
            |    |                       rd_data                        |    |
            |  +------------+                              +------------+    |
            |  | sync_r2w   |<---------------------------- | (rgray)    |    |
            |  | 2FF x PTR_W|                              +------------+    |
            |  +------------+                                               |
            |                                              +------------+   |
            +--------------------------------------------->| sync_w2r   |---+
                                                           | 2FF x PTR_W|
                                                           +------------+
   wrst_n --+--> [rst_sync wclk] --> wrst_int_n      rrst_n --+--> [rst_sync rclk] --> rrst_int_n
            |          ^ async clear = wrst_n & rrst_n          |          ^ async clear = wrst_n & rrst_n
            +----------------------------------------------------+
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_wptr` | `afifo_wptr_full` | Write pointers, `wr_full`, `wr_almost_full`. |
| `u_rptr` | `afifo_rptr_empty` | Read pointers, `rd_empty`, `rd_almost_empty`, `rd_data` register. |
| `u_mem` | `afifo_mem` | Dual-clock storage (LUT-RAM/flop array; BRAM for large DEPTH). |
| `u_sync_w2r` | `sync_ff #(PTR_W, SYNC_STAGES)` | `wgray` → `rq2_wgray` in `rclk`. |
| `u_sync_r2w` | `sync_ff #(PTR_W, SYNC_STAGES)` | `rgray` → `wq2_rgray` in `wclk`. |
| `u_wrst`, `u_rrst` | `rst_sync` | Reset synchronizers (async assert, sync release). |

## 5. Datapath

**Write domain registers** (`wclk`, reset by `wrst_int_n`)

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `wbin` | `PTR_W` | 0 | Binary write pointer; `waddr = wbin[ADDR_W-1:0]`. |
| `wgray` | `PTR_W` | 0 | Registered Gray of `wbin` (only signal crossing to `rclk`). |
| `wq1_rgray`, `wq2_rgray` | `PTR_W` | 0 | Synchronizer stages for `rgray`. |
| `wfull_q` | 1 | 0 | `wr_full`. |
| `waf_q` | 1 | 0 | `wr_almost_full`. |

```verilog
wire             w_fire     = wr_en & ~wfull_q;
wire [PTR_W-1:0] wbin_n     = wbin + w_fire;
wire [PTR_W-1:0] wgray_n    = (wbin_n >> 1) ^ wbin_n;
// full: next write Gray equals synced read Gray with the two MSBs inverted
wire             wfull_n    = (wgray_n == {~wq2_rgray[PTR_W-1:PTR_W-2], wq2_rgray[PTR_W-3:0]});
wire [PTR_W-1:0] wq2_rbin   = gray2bin(wq2_rgray);           // XOR prefix chain
wire [PTR_W-1:0] wlevel_n   = wbin_n - wq2_rbin;              // modulo 2^PTR_W, 0..DEPTH
wire             waf_n      = (wlevel_n >= AF_LEVEL);
```

**Read domain registers** (`rclk`, reset by `rrst_int_n`)

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `rbin` | `PTR_W` | 0 | Binary read pointer; `raddr = rbin[ADDR_W-1:0]`. |
| `rgray` | `PTR_W` | 0 | Registered Gray of `rbin`. |
| `rq1_wgray`, `rq2_wgray` | `PTR_W` | 0 | Synchronizer stages for `wgray`. |
| `rempty_q` | 1 | 1 | `rd_empty`. |
| `rae_q` | 1 | 1 | `rd_almost_empty`. |
| `rd_data_q` | `DATA_W` | 0 | Registered read data. |
| `rd_valid_q` | 1 | 0 | `rd_valid`. |

```verilog
wire             r_fire   = rd_en & ~rempty_q;
wire [PTR_W-1:0] rbin_n   = rbin + r_fire;
wire [PTR_W-1:0] rgray_n  = (rbin_n >> 1) ^ rbin_n;
wire             rempty_n = (rgray_n == rq2_wgray);
wire [PTR_W-1:0] rlevel_n = gray2bin(rq2_wgray) - rbin_n;
wire             rae_n    = (rlevel_n <= AE_LEVEL);
always @(posedge rclk) if (r_fire) rd_data_q <= mem[rbin[ADDR_W-1:0]];
```

**Memory:** `mem[0:DEPTH-1]`, `DATA_W` bits per entry. Synchronous write on `wclk` when
`w_fire`; asynchronous read addressed by `rbin` and captured into `rd_data_q` on `rclk`. Not
reset. At 32 × 26 bits this maps to dual-clock distributed RAM (FPGA) or an 832-flop array
(ASIC). For DEPTH ≥ 256, use a true dual-clock RAM macro with a synchronous read port; the
read-side timing is unchanged, because the RAM output register takes the place of `rd_data_q`.

## 6. Control Logic

There is no explicit FSM; each side is a pointer counter plus a registered flag comparator.

| Write-side condition | `wr_full` | Write accepted |
|----------------------|-----------|----------------|
| `wlevel < DEPTH` (as seen) | 0 | yes |
| `wlevel == DEPTH` (as seen) | 1 | no; `wr_en` ignored |

| Read-side condition | `rd_empty` | Read accepted |
|---------------------|------------|---------------|
| `rgray == rq2_wgray` | 1 | no; `rd_en` ignored |
| otherwise | 0 | yes; `rd_data` valid next cycle |

Gray conversion (`PTR_W = 6`):

```verilog
function [PTR_W-1:0] gray2bin(input [PTR_W-1:0] g);
  integer i; begin
    gray2bin[PTR_W-1] = g[PTR_W-1];
    for (i = PTR_W-2; i >= 0; i = i-1) gray2bin[i] = gray2bin[i+1] ^ g[i];
  end
endfunction
```

**Reset coupling.** The async clear of both reset synchronizers is `wrst_n & rrst_n`, so
asserting either reset immediately (asynchronously) resets **both** pointer sets. Each side
leaves reset synchronously to its own clock, after both inputs are de-asserted.

## 7. Timing & Pipeline

- **Throughput:** one write per `wclk` and one read per `rclk`, sustained.
- **Write → visible to reader (empty de-assert):** the `wgray` register updates at write edge W0. `rq1` captures it at the first `rclk` edge after W0 (+setup), `rq2` at the next, and `rempty_q` at the third. Latency is 2–3 `rclk` cycles plus up to one `rclk` period of phase uncertainty, about 15–20 ns at 200 MHz.
- **Read → space visible to writer (full de-assert):** 2–3 `wclk` cycles plus phase, about 27–40 ns at 74.25 MHz.
- **Read data latency:** 1 `rclk` cycle after an accepted `rd_en`.
- **Sizing:** the reader (200 MHz) is faster than the writer (74.25 MHz), so in steady state the FIFO runs near empty. DEPTH = 32 absorbs reader stalls of up to 32 / 74.25 MHz ≈ 430 ns.

Cycle trace, read domain: a single write to an empty FIFO (`wgray` goes 000000 → 000001 at t = 0):

| rclk edge | `rq1_wgray` | `rq2_wgray` | `rempty_q` | `rd_en` | `rd_data_q` | `rd_valid` |
|-----------|-------------|-------------|------------|---------|-------------|------------|
| R0 (t ≈ 1 ns) | 000001 | 000000 | 1 | 0 | – | 0 |
| R1 | 000001 | 000001 | 1 | 0 | – | 0 |
| R2 | 000001 | 000001 | **0** | 1 | – | 0 |
| R3 | 000001 | 000001 | 1 | 0 | **D0** | 1 |

Each row shows register values after that edge; `rd_en` is the value driven in the following
cycle. The consumer sees `rd_empty=0` after R2 and raises `rd_en`, which is accepted at R3
(`r_fire=1`, `rbin_n=1`, `rgray_n=000001 == rq2_wgray`). At R3 `rd_data_q` captures D0
and `rempty_q` is set again.

Write domain: filling to full with no reads (DEPTH=32). After the 32nd accepted write,
`wbin = 32 = 100000b`, `wgray = 110000b`; `rgray = 000000` with its two MSBs inverted is
`110000` → `wr_full` = 1 in the same cycle the 32nd write is registered.

## 8. Clocking & Reset

**Clock domains:** `wclk` (74.25 MHz, may stop) and `rclk` (200 MHz), asynchronous.

**Crossings**

| # | Signal | From → To | Width | Method |
|---|--------|-----------|-------|--------|
| 1 | `wgray` | wclk → rclk | `PTR_W` | Gray code + `SYNC_STAGES`-FF synchronizer |
| 2 | `rgray` | rclk → wclk | `PTR_W` | Gray code + `SYNC_STAGES`-FF synchronizer |
| 3 | `mem[*]` → `rd_data_q` | wclk → rclk | `DATA_W` | Qualified by pointer protocol (entry stable ≥ 2 rclk before it can be read) |
| 4 | `wrst_n` → rclk logic, `rrst_n` → wclk logic | async | 1 | Reset synchronizers (async assert, sync de-assert) |

**Constraints (SDC/XDC)**

```tcl
set_clock_groups -asynchronous -group [get_clocks wclk] -group [get_clocks rclk]
# Gray buses: bound skew/delay to the *faster* (source-side worst) period so at most one bit is in flight
set_max_delay -datapath_only 5.000 -from [get_cells u_wptr/wgray_reg[*]] -to [get_cells u_sync_w2r/q1_reg[*]]
set_max_delay -datapath_only 5.000 -from [get_cells u_rptr/rgray_reg[*]] -to [get_cells u_sync_r2w/q1_reg[*]]
# Vivado alternative / addition:
set_bus_skew 5.000 -from [get_cells u_wptr/wgray_reg[*]] -to [get_cells u_sync_w2r/q1_reg[*]]
set_bus_skew 5.000 -from [get_cells u_rptr/rgray_reg[*]] -to [get_cells u_sync_r2w/q1_reg[*]]
# Memory read path is protocol-qualified; bound it to one rclk period
set_max_delay -datapath_only 5.000 -from [get_cells u_mem/mem_reg[*][*]] -to [get_cells u_rptr/rd_data_q_reg[*]]
set_property ASYNC_REG TRUE [get_cells {u_sync_*/q*_reg[*] u_*rst/s*_reg}]
```

**SpyGlass CDC setup:** declare `wclk`/`rclk` as asynchronous clock domains, and declare the
FIFO so that rule `Ac_unsync02` on the memory path is waived as FIFO-qualified:
`fifo -memory u_mem.mem -rd_ptr u_rptr.rbin -wr_ptr u_wptr.wbin`. The synchronizers are
recognized as conventional multi-flop (`Ac_sync01`); the Gray-encoded buses pass
`Ac_conv02`.

**Reset:** two async active-low resets. Either one asserted resets both sides (coupled
async clear); each side releases synchronously to its own clock. If `wclk` is stopped
when the resets de-assert, the write side stays in reset until `wclk` runs, which is
harmless: no writes can happen without a clock.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| `wr_en` while `wr_full` | Ignored. Data not written. No error flag (spec does not ask for one). |
| `rd_en` while `rd_empty` | Ignored; `rd_data_q` holds; `rd_valid=0`. |
| `wclk` stops with data in FIFO | Reader still sees the last synchronized `wgray` and drains everything written. |
| `rclk` stops | Writer fills to full and then stops accepting; no loss. |
| Only one side reset | Coupled reset clears both sides; in-flight data is discarded (it is invalid anyway after a one-sided reset). |
| Synchronizer goes metastable | Resolves to old or new Gray value; both are valid pointers, so flags are at worst pessimistic for one more cycle. |
| `AF_LEVEL`/`AE_LEVEL` | Based on stale remote pointer: `almost_full` may be late to clear, `almost_empty` may be late to clear (both conservative). |
| Pointer wrap | `PTR_W`-bit modulo arithmetic; MSB distinguishes full/empty. |

## 10. Verification Plan

**Testbench:** two independent clock generators with randomized period jitter and random
start phase; ratios swept from 1:5 to 5:1 (not just 74.25/200). A scoreboard queue checks
ordering, no loss and no duplication. Writer and reader traffic generators have random
duty cycles.

**Directed tests**
1. Reset values: `rd_empty=1`, `wr_full=0`, `rd_almost_empty=1`.
2. Single write → measure empty de-assert latency (2–3 rclk).
3. Fill to full with the reader stalled; check exactly DEPTH words accepted.
4. Drain to empty; the extra `rd_en` is ignored.
5. Stop `wclk` mid-stream; the reader drains all accepted words.
6. Assert `wrst_n` alone mid-traffic → both sides empty; then resume.
7. Thresholds: `wr_almost_full` at level ≥ `AF_LEVEL`, `rd_almost_empty` at ≤ `AE_LEVEL`.

**Random:** 1M words with random clock ratios and traffic, including the extremes of a
reader 10× faster and a writer 10× faster.

**CDC-specific:** run with a metastability-injection model in the synchronizers (random
extra cycle of delay per bit) to prove the protocol tolerates it. Run SpyGlass CDC and RDC
with zero unwaived violations.

**Assertions (SVA)**

```systemverilog
a_wgray_onehot: assert property (@(posedge wclk) disable iff(!wrst_int_n) $onehot0(wgray ^ $past(wgray)));
a_rgray_onehot: assert property (@(posedge rclk) disable iff(!rrst_int_n) $onehot0(rgray ^ $past(rgray)));
a_no_wr_full:   assert property (@(posedge wclk) disable iff(!wrst_int_n) wfull_q |-> $stable(wbin));
a_no_rd_empty:  assert property (@(posedge rclk) disable iff(!rrst_int_n) rempty_q |-> $stable(rbin));
a_wlevel_max:   assert property (@(posedge wclk) disable iff(!wrst_int_n) (wbin - gray2bin(wq2_rgray)) <= DEPTH);
```

**Coverage:** full and empty reached; wrap of both pointers ≥ 3 times; simultaneous full and
read activity; clock ratio bins; one-sided resets on each side; `wclk` stop/start.

## 11. Assumptions & Open Questions

1. **Coupled resets.** The spec says resets "can come at different times". We assume either side may be reset at any time and that resetting one side must flush the whole FIFO. If the sensor side needs to be reset without disturbing data already queued, a reset handshake protocol is needed instead.
2. **No overflow/underflow flags.** The spec asks for none; writers and readers must respect `wr_full`/`rd_empty`.
3. **`rd_valid` added** as a convenience, so the consumer does not need to delay `rd_en` itself.
4. **2 synchronizer stages** are sufficient at 200 MHz / 74.25 MHz for typical MTBF on modern nodes. Use `SYNC_STAGES = 3` if the library's MTBF analysis requires it.
5. **Skew bound = 5 ns** (the faster clock period) is used for both Gray buses, which is conservative for the `wclk`-sourced bus.
6. **DEPTH = 32** is assumed sufficient for the reader's worst-case stall (≈ 430 ns). Confirm against the system interconnect latency.
