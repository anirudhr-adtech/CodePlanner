# Micro-architecture: `sync_fifo`

## 1. Overview

`sync_fifo` is a single-clock, parameterizable first-in-first-out buffer with
first-word-fall-through (FWFT) read semantics. The head entry is always visible on `rd_data`
while `empty` is low, and asserting `rd_en` pops it in that same cycle, so there is zero
read latency.

Key features:
- Configurable `DATA_W` and `DEPTH` (power of two).
- Circular buffer with extra-MSB read/write pointers, giving full/empty without a separate counter.
- Registered `full`, `empty`, `almost_full` and `level` outputs (no combinational paths from inputs to status).
- Programmable `almost_full` threshold through an input port.
- Sticky `overflow`/`underflow` error flags, cleared by `err_clr`.
- Simultaneous read and write supported in every state.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | Single clock; all logic is rising-edge triggered. |
| `rst_n` | in | 1 | Active-low reset, asynchronous assert, synchronous de-assert (synchronized externally). |
| **Write port** | | | |
| `wr_en` | in | 1 | Write request. Accepted when `!full`, or when `full && rd_en` (see §9). |
| `wr_data` | in | `DATA_W` | Write data, sampled on the cycle `wr_en` is accepted. |
| `full` | out | 1 | FIFO holds `DEPTH` entries. |
| `almost_full` | out | 1 | `level >= af_thresh`. |
| **Read port** | | | |
| `rd_en` | in | 1 | Pop request. Accepted when `!empty`. |
| `rd_data` | out | `DATA_W` | Head-of-queue data; valid whenever `empty == 0` (FWFT). |
| `empty` | out | 1 | FIFO holds zero entries. |
| **Status / config** | | | |
| `level` | out | `ADDR_W+1` | Number of entries stored (0..`DEPTH`). |
| `af_thresh` | in | `ADDR_W+1` | Almost-full threshold, treated as quasi-static. |
| `overflow` | out | 1 | Sticky: a write was attempted while full and not accepted. |
| `underflow` | out | 1 | Sticky: a read was attempted while empty. |
| `err_clr` | in | 1 | Single-cycle pulse; clears `overflow` and `underflow`. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `DATA_W` | 32 | 1–1024 | Data width in bits. |
| `DEPTH` | 16 | 2–65536, power of 2 | Number of entries. |
| `ADDR_W` | `$clog2(DEPTH)` | derived (localparam) | Memory address width. |
| `PTR_W` | `ADDR_W + 1` | derived (localparam) | Pointer width (extra wrap bit). |

The design checks `DEPTH` in elaboration: if `DEPTH` is not a power of two, a `generate`
block triggers `$error`.

## 4. Block Diagram

```
             wr_en,wr_data                                   rd_en
                  |                                            |
                  v                                            v
          +---------------+        wr_addr        +-------------------+
          |  write ctrl   |---------------------->|                   |
          |  wr_ptr[PTR]  |        wr_data/we     |   mem[DEPTH]      |  rd_data
          +---------------+---------------------->|   (dist RAM /     |---------->
                  |                               |    flop array)    |
                  |  wr_ptr          rd_addr      |  async read port  |
                  |          +------------------->|                   |
                  v          |                    +-------------------+
          +---------------+  |    +---------------+
          | status logic  |<-+----|  read ctrl    |<----- rd_en
          | full/empty/   |  rd_ptr | rd_ptr[PTR] |
          | level/af      |         +---------------+
          +---------------+
             |  |   |   \______ overflow / underflow (sticky, err_clr)
          full empty level almost_full
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_mem` | `sync_fifo_mem` (or inferred array) | `DEPTH x DATA_W` storage, 1 sync write port, 1 async read port. |
| — (inline) | write control | `wr_ptr` register and increment. |
| — (inline) | read control | `rd_ptr` register and increment. |
| — (inline) | status logic | Next-state calculation for `full`, `empty`, `level`, `almost_full`, error flags. |

## 5. Datapath

**Registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `wr_ptr` | `PTR_W` | 0 | Write pointer; `wr_ptr[ADDR_W-1:0]` is the write address, MSB is the wrap bit. |
| `rd_ptr` | `PTR_W` | 0 | Read pointer; same format. |
| `level_q` | `PTR_W` | 0 | Registered fill level. |
| `full_q` | 1 | 0 | Registered full flag. |
| `empty_q` | 1 | 1 | Registered empty flag. |
| `af_q` | 1 | 0 | Registered almost-full flag. |
| `ovf_q` | 1 | 0 | Sticky overflow. |
| `udf_q` | 1 | 0 | Sticky underflow. |
| `mem[0:DEPTH-1]` | `DATA_W` each | not reset | Storage array. |

**Storage.** `mem` is written synchronously at `wr_ptr[ADDR_W-1:0]` when `wr_fire`. It is
read asynchronously at `rd_ptr[ADDR_W-1:0]`, so `rd_data = mem[rd_ptr[ADDR_W-1:0]]`. An async
read maps to distributed (LUT) RAM on FPGA and to a flop array plus read mux on ASIC; that
works for depths up to about 64. For deeper FIFOs, see §11 (block-RAM variant).

**Handshake qualifiers**

```verilog
wire wr_fire = wr_en && (!full_q || rd_fire);   // write accepted
wire rd_fire = rd_en && !empty_q;               // read accepted
```

`wr_fire` depends on `rd_fire`, but `rd_fire` does not depend on `wr_fire`, so there is no
combinational loop.

**Pointer and level update**

```verilog
wr_ptr_n  = wr_ptr + wr_fire;
rd_ptr_n  = rd_ptr + rd_fire;
level_n   = level_q + wr_fire - rd_fire;      // PTR_W-bit arithmetic
full_n    = (level_n == DEPTH);
empty_n   = (level_n == 0);
af_n      = (level_n >= af_thresh);
```

Using `level_n` keeps all flags registered and exactly consistent with each other. The
pointer-only form, `full = (wr_ptr[MSB] != rd_ptr[MSB]) && (wr_ptr[ADDR_W-1:0] == rd_ptr[ADDR_W-1:0])`,
is kept as an assertion cross-check (§10).

## 6. Control Logic

There is no explicit FSM. The FIFO state is implied by `level_q`, as shown below.

| Implied state | Condition | `empty` | `full` | Accepted ops |
|---------------|-----------|---------|--------|--------------|
| EMPTY | `level == 0` | 1 | 0 | write only (read flagged as underflow) |
| PARTIAL | `0 < level < DEPTH` | 0 | 0 | read, write, both |
| FULL | `level == DEPTH` | 0 | 1 | read; write only if read in the same cycle |

Next-state transitions in each cycle:

| Current | `wr_fire` | `rd_fire` | Next |
|---------|-----------|-----------|------|
| EMPTY | 1 | 0 | PARTIAL (or FULL if `DEPTH==1`; excluded by `DEPTH>=2`) |
| PARTIAL | 1 | 0 | PARTIAL or FULL (if `level==DEPTH-1`) |
| PARTIAL | 0 | 1 | PARTIAL or EMPTY (if `level==1`) |
| PARTIAL/FULL | 1 | 1 | unchanged |
| FULL | 0 | 1 | PARTIAL |

**Error flags**

```verilog
ovf_n = err_clr ? 1'b0 : (ovf_q | (wr_en && !wr_fire));
udf_n = err_clr ? 1'b0 : (udf_q | (rd_en && !rd_fire));
```

If `err_clr` and a new error occur in the same cycle, `err_clr` wins and the new error is
lost. This is documented in §11.

## 7. Timing & Pipeline

- **Write latency:** data written in cycle N is visible on `rd_data` in cycle N+1 if the FIFO was empty, since `empty` falls at N+1.
- **Read latency:** 0 cycles (FWFT). `rd_data` is valid during the cycle `rd_en` is asserted.
- **Throughput:** 1 write and 1 read per cycle, sustained.
- **Critical path:** `rd_ptr` → read mux (`log2(DEPTH)` levels) → `rd_data` → downstream logic. Also `level_q` → adder → comparator → `full_q`.

Cycle-by-cycle example (`DEPTH=4`):

| Cycle | wr_en | wr_data | rd_en | level (after) | empty | full | rd_data (during) | Note |
|-------|-------|---------|-------|---------------|-------|------|------------------|------|
| 0 | 1 | A | 0 | 1 | 1 | 0 | x | write A |
| 1 | 1 | B | 0 | 2 | 0 | 0 | A | A visible (FWFT) |
| 2 | 1 | C | 1 | 2 | 0 | 0 | A | pop A, push C |
| 3 | 1 | D | 0 | 3 | 0 | 0 | B | |
| 4 | 1 | E | 0 | 4 | 0 | 0 | B | becomes full |
| 5 | 1 | F | 0 | 4 | 0 | 1 | B | F rejected, overflow=1 |
| 6 | 1 | F | 1 | 4 | 0 | 1 | B | pop B, push F (full + rd) |
| 7 | 0 | - | 1 | 3 | 0 | 1 | C | |

(The `empty`/`full` columns show the registered values seen during that cycle.)

## 8. Clocking & Reset

- **One clock domain** (`clk`). No CDC inside the block.
- **Reset:** `rst_n` is active-low, asserted asynchronously and released synchronously by the
  reset synchronizer at the top level. Reset clears the pointers, `level_q`, `full_q`, `af_q`
  and the error flags, and sets `empty_q=1`.
- `mem` is not reset. That saves area and lets the FPGA infer LUT-RAM. Its contents are
  unreachable until written, because `empty` gates every read.
- `af_thresh` is treated as quasi-static: change it only while the consumer ignores
  `almost_full`. A mid-traffic change takes effect on the next cycle without glitches,
  because `af_q` is registered.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| Write when full, no read | Write dropped, `overflow` set, pointers unchanged. |
| Write when full and read in the same cycle | Both accepted (`wr_fire` uses `rd_fire`); level stays `DEPTH`. The write targets the slot being freed; the async read returns the old data before the clock edge commits the write. `wr_fire` depends combinationally on `rd_en`, but it is internal and never exported, so no external loop can form. |
| Read when empty | Read ignored, `underflow` set, `rd_data` is don't-care. |
| Read and write when empty | Only the write is accepted (`rd_fire=0` because `empty_q=1`); read flags underflow. No bypass path, which keeps timing simple. |
| `af_thresh = 0` | `almost_full` is constantly 1. |
| `af_thresh > DEPTH` | `almost_full` never asserts. |
| Pointer wrap | Natural `PTR_W`-bit overflow; the extra MSB distinguishes full from empty. |
| X on `wr_en`/`rd_en` | Assertion fires in simulation (§10). |

## 10. Verification Plan

**Testbench:** a self-checking SystemVerilog testbench with a queue-based reference model.
Every accepted write pushes to the model; every accepted read compares `rd_data` against
the model's front entry.

**Directed tests**
1. Reset values: `empty=1`, `full=0`, `level=0`, `overflow=underflow=0`.
2. Fill to full, then check `full`, `level=DEPTH` and `almost_full`.
3. Overflow: write when full → data dropped, `overflow` sticky until `err_clr`.
4. Drain to empty, then check underflow on an extra read.
5. Simultaneous read and write at empty, at partial level and at full.
6. Pointer wrap: run 3×`DEPTH` operations and check ordering.
7. Threshold sweep: `af_thresh` from 0 to `DEPTH+1`.

**Constrained-random:** random `wr_en`/`rd_en` with duty-cycle knobs (10/50/90%), 100k
cycles, several `DATA_W`/`DEPTH` parameter sets (8×2, 32×16, 64×256).

**Assertions (SVA)**

```systemverilog
a_no_full_empty:  assert property (@(posedge clk) disable iff(!rst_n) !(full && empty));
a_level_range:    assert property (@(posedge clk) disable iff(!rst_n) level <= DEPTH);
a_ptr_full:       assert property (@(posedge clk) disable iff(!rst_n)
                    full == ((wr_ptr[ADDR_W]!=rd_ptr[ADDR_W]) && (wr_ptr[ADDR_W-1:0]==rd_ptr[ADDR_W-1:0])));
a_ptr_empty:      assert property (@(posedge clk) disable iff(!rst_n) empty == (wr_ptr == rd_ptr));
a_ovf_sticky:     assert property (@(posedge clk) disable iff(!rst_n) overflow && !err_clr |=> overflow);
a_no_x_ctrl:      assert property (@(posedge clk) disable iff(!rst_n) !$isunknown({wr_en, rd_en}));
```

**Coverage:** each implied state; every (state × wr_fire × rd_fire) cross; overflow; underflow;
`err_clr` colliding with a new error; at least 2 pointer wraps; `almost_full` rise and fall.

## 11. Assumptions & Open Questions

1. **DEPTH is a power of two.** This keeps the pointer logic trivial. Non-power-of-two depths need modulo wrap logic and are out of scope.
2. **FWFT with async-read memory.** Chosen to meet the spec's "same-cycle data" request. For deep FIFOs (>64 entries) that need block RAM (synchronous read), use a variant with a 1-entry output prefetch register that keeps FWFT behaviour. Exposed as a future parameter `MEM_STYLE`.
3. **No write-to-read bypass at empty.** A write in cycle N is readable at N+1 at the earliest. The spec did not require a bypass, and leaving it out removes a mux from the critical path.
4. **Full + read + write accepted.** The spec asked for simultaneous read/write "including when full"; we interpret that as accepting the write.
5. **`err_clr` wins** over a new error in the same cycle. Confirm with the software team.
6. **`level` width** is `ADDR_W+1` so it can represent `DEPTH` itself.
7. **Overflow condition** is defined as `wr_en && !wr_fire` (attempted but rejected write).
