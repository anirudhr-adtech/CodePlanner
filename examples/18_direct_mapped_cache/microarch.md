# Micro-architecture: `dcache_dm`

## 1. Overview

`dcache_dm` is a 4 KiB, direct-mapped, write-back, write-allocate L1 data cache with
32-byte (8-word) lines for the Kestrel 32-bit in-order core. It has a two-stage hit
pipeline:

- **S0 (Access):** the CPU request is accepted and the tag and data SRAMs are read at the request's index.
- **S1 (Compare):** the tag is compared, and read data is returned or store data is written.

Read hits have 1-cycle latency and full throughput (one per cycle). Store hits take 2 cycles
each, because the single-port data SRAM is used once for the S0 read and once for the S1
write. A miss is handled by a central FSM that optionally writes back a dirty victim line
through a line buffer, refills the line with an 8-beat burst, and then **replays** the
original request through the pipeline, so the request completes as an ordinary hit.

Valid and dirty bits are held in flip-flops, so reset invalidates the whole cache in one
cycle. The tag and data arrays are single-port synchronous SRAMs with 1-cycle read latency.

Address breakdown (32-bit byte address):

```
 31                  12 11          5 4      2 1   0
+----------------------+-------------+--------+-----+
|        TAG (20)      |  INDEX (7)  | WORD(3)|BYTE |
+----------------------+-------------+--------+-----+
```

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | Core clock. |
| `rst_n` | in | 1 | Active-low reset, async assert / sync de-assert. |
| **CPU request** | | | |
| `cpu_req_valid` | in | 1 | Request valid. |
| `cpu_req_ready` | out | 1 | Cache can accept a request this cycle. |
| `cpu_req_addr` | in | 32 | Byte address (bits [1:0] used only by the core to build strobes). |
| `cpu_req_we` | in | 1 | 1 = store, 0 = load. |
| `cpu_req_wstrb` | in | 4 | Byte enables for stores. |
| `cpu_req_wdata` | in | 32 | Store data, already lane-aligned by the core. |
| **CPU response** | | | |
| `cpu_resp_valid` | out | 1 | One-cycle pulse per accepted request (load data or store acknowledgement). In order. |
| `cpu_resp_rdata` | out | 32 | Load data (full word; the core extracts bytes/halfwords). Don't-care for stores. |
| **Memory request channel** | | | |
| `mem_req_valid` | out | 1 | Burst request valid. |
| `mem_req_ready` | in | 1 | Interconnect accepts the request. |
| `mem_req_addr` | out | 32 | Line-aligned address (`[4:0] = 0`). |
| `mem_req_we` | out | 1 | 1 = write burst (writeback), 0 = read burst (refill). |
| **Memory write data** | | | |
| `mem_wvalid` | out | 1 | Write beat valid. |
| `mem_wready` | in | 1 | Interconnect accepts the beat. |
| `mem_wdata` | out | 32 | Write beat data. |
| `mem_wlast` | out | 1 | Last (8th) beat. |
| `mem_wdone` | in | 1 | One-cycle pulse: write burst committed. |
| **Memory read data** | | | |
| `mem_rvalid` | in | 1 | Read beat valid (the cache always accepts it). |
| `mem_rdata` | in | 32 | Read beat data. |
| `mem_rlast` | in | 1 | Last (8th) beat. |

The SRAMs are instantiated inside the cache. Their wrapper ports are listed in §4.

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `CACHE_BYTES` | 4096 | power of 2, ≥ 2×LINE_BYTES | Total capacity. |
| `LINE_BYTES` | 32 | fixed 32 | Line size (fixed by the interconnect burst = 8 × 32 bit). |
| `ADDR_W` | 32 | fixed | Address width. |
| `WORDS` | `LINE_BYTES/4` = 8 | derived | Words per line = beats per burst. |
| `LINES` | `CACHE_BYTES/LINE_BYTES` = 128 | derived | Number of lines. |
| `OFF_W` | `$clog2(WORDS)` = 3 | derived | Word-offset width. |
| `IDX_W` | `$clog2(LINES)` = 7 | derived | Index width. |
| `TAG_W` | `ADDR_W - IDX_W - OFF_W - 2` = 20 | derived | Tag width. |

## 4. Block Diagram

```
  CPU req                     +-----------------------------------------------+
  valid/addr/we/  ----------->|  S0 request mux / SRAM address mux             |
  wstrb/wdata     <-- ready --|  (cpu / replay / writeback-read / refill)      |
                              +------+--------------------+---------------------+
                                     | tag_addr,we        | data_addr,we,be,wdata
                                     v                    v
                              +-------------+      +--------------+
                              | u_tag_ram   |      | u_data_ram   |
                              | 128 x 20    |      | 1024 x 32    |
                              | 1RW, 1-cyc  |      | 1RW, byte-WE |
                              +------+------+      +------+-------+
                                     | tag_rdata          | data_rdata
              +---------------+      v                    v
 valid_q[128] |  S1 regs      |  +-------+          +-----------+
 dirty_q[128] |  s1_addr/we/  |->| cmp   |--hit---->| resp mux  |---> cpu_resp_valid/rdata
     |        |  wstrb/wdata  |  +-------+          +-----------+
     |        +---------------+      |                    |
     v                               v                    v
  +----------------------------------------------------------+     +----------------+
  |  u_ctrl : miss FSM (IDLE, LOOKUP, WB_RD, WB_REQ, WB_DATA, |---->| u_wbbuf 8 x 32 |--> mem_wdata
  |  WB_WAIT, RF_REQ, RF_DATA, REPLAY), beat counter          |     +----------------+
  +----------------------------------------------------------+
        |  mem_req_*                            ^ mem_rvalid/rdata/rlast (into data RAM)
        v                                       |
                     system interconnect (burst protocol)
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_tag_ram` | `sram_1rw #(.W(20), .D(128))` | Tag array. Ports: `ce, we, addr[6:0], wdata[19:0], rdata[19:0]`. |
| `u_data_ram` | `sram_1rw_be #(.W(32), .D(1024))` | Data array, word addressed by `{index, word}`. Ports: `ce, we, be[3:0], addr[9:0], wdata, rdata`. |
| `u_ctrl` | `dcache_ctrl` | Main FSM, SRAM address/enable muxing, memory-interface sequencing. |
| `u_wbbuf` | inline register file | 8 × 32 victim-line buffer that decouples SRAM reads from `mem_wready` back-pressure. |
| — (inline) | `valid_q`, `dirty_q` | 128-bit flop vectors with per-index set/clear. |

## 5. Datapath

### 5.1 Registers

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `state_q` | 4 | IDLE | Main FSM state (§6). |
| `s1_valid_q` | 1 | 0 | S1 holds a request (implied by state ∈ {LOOKUP}; kept for clarity). |
| `s1_addr_q` | 32 | 0 | Address of the request in S1 / being serviced. |
| `s1_we_q` | 1 | 0 | Store flag. |
| `s1_wstrb_q` | 4 | 0 | Byte strobes. |
| `s1_wdata_q` | 32 | 0 | Store data. |
| `victim_tag_q` | 20 | 0 | Tag read in S1, captured on a miss (SRAM output isn't held across cycles). |
| `beat_q` | 4 | 0 | Beat/word counter for WB_RD (0..8), WB_DATA (0..7) and RF_DATA (0..7). |
| `wbbuf_q[0:7]` | 32 each | not reset | Victim line buffer. |
| `valid_q` | 128 | 0 | Line valid bits. |
| `dirty_q` | 128 | 0 | Line dirty bits. |

Derived fields: `s1_tag = s1_addr_q[31:12]`, `s1_idx = s1_addr_q[11:5]`,
`s1_word = s1_addr_q[4:2]`.

### 5.2 Hit detection (S1)

```verilog
wire s1_line_valid = valid_q[s1_idx];
wire s1_line_dirty = dirty_q[s1_idx];
wire s1_hit        = (state_q == LOOKUP) & s1_line_valid & (tag_rdata == s1_tag);
wire s1_miss       = (state_q == LOOKUP) & ~s1_hit;
```

`cpu_resp_rdata = data_rdata` (direct from the SRAM output; no mux needed, because the data
SRAM was read at `{s1_idx, s1_word}` in the previous cycle).

### 5.3 SRAM port muxing

Both SRAMs are single-ported. Exactly one source drives each port per cycle:

| State / condition | tag_ram | data_ram | Purpose |
|-------------------|---------|----------|---------|
| Accept (`cpu_req_valid & cpu_req_ready`) | read `req_idx` | read `{req_idx, req_word}` | S0 lookup of the new request |
| LOOKUP & hit & `s1_we` | idle | **write** `{s1_idx, s1_word}`, `be = s1_wstrb` | Store hit |
| WB_RD, `beat_q < 8` | idle | read `{s1_idx, beat_q[2:0]}` | Read victim words |
| RF_DATA & `mem_rvalid` | write `s1_idx ← s1_tag` on `mem_rlast` | **write** `{s1_idx, beat_q[2:0]}`, `be = 4'hF` | Refill |
| REPLAY | read `s1_idx` | read `{s1_idx, s1_word}` | Re-lookup after refill |

`cpu_req_ready` is 0 in every row except "Accept", so the rows never conflict (§6.2).

### 5.4 Writeback buffer

During WB_RD, a read issued at `beat_q = k` returns data at `k+1`, which is captured into
`wbbuf_q[k]`:

```verilog
if (state_q == WB_RD && beat_q != 0) wbbuf_q[beat_q-1] <= data_rdata;
```

WB_RD lasts 9 cycles (`beat_q` 0..8): reads are issued at 0–7 and the last capture happens
at 8. In WB_DATA, `mem_wdata = wbbuf_q[beat_q[2:0]]`, and `beat_q` advances on
`mem_wvalid & mem_wready`.

### 5.5 Valid / dirty update

```verilog
// refill complete
if (state_q == RF_DATA && mem_rvalid && mem_rlast) begin
  valid_q[s1_idx] <= 1'b1;
  dirty_q[s1_idx] <= 1'b0;
end
// store hit (includes the replayed store after write-allocate)
if (s1_hit && s1_we_q) dirty_q[s1_idx] <= 1'b1;
```

The two updates are mutually exclusive by state. There is no invalidate path (§11).

### 5.6 Memory addresses

| Burst | `mem_req_addr` |
|-------|----------------|
| Writeback | `{victim_tag_q, s1_idx, 5'b0}` |
| Refill | `{s1_tag, s1_idx, 5'b0}` |

## 6. Control Logic

### 6.1 Main FSM (`u_ctrl`)

Encoding: 4-bit binary (9 states). One-hot is an equally valid choice for FPGA.

| State | Enc | Outputs (asserted) | Transitions |
|-------|-----|--------------------|-------------|
| IDLE | 0 | `cpu_req_ready` | accept → LOOKUP; else IDLE |
| LOOKUP | 1 | `cpu_resp_valid` if hit; `cpu_req_ready` if read hit | read hit & accept → LOOKUP; read hit & !accept → IDLE; store hit → IDLE; miss & victim valid & dirty → WB_RD (capture `victim_tag_q ← tag_rdata`); miss & clean → RF_REQ |
| WB_RD | 2 | data_ram read | `beat_q == 8` → WB_REQ (beat ← 0) |
| WB_REQ | 3 | `mem_req_valid`, `mem_req_we=1` | `mem_req_ready` → WB_DATA |
| WB_DATA | 4 | `mem_wvalid`, `mem_wlast` when `beat_q==7` | `mem_wready & beat_q==7` → WB_WAIT (beat ← 0) |
| WB_WAIT | 5 | – | `mem_wdone` → RF_REQ |
| RF_REQ | 6 | `mem_req_valid`, `mem_req_we=0` | `mem_req_ready` → RF_DATA (beat ← 0) |
| RF_DATA | 7 | data_ram write on `mem_rvalid` | `mem_rvalid & mem_rlast` → REPLAY |
| REPLAY | 8 | tag/data SRAM read at S1 address | → LOOKUP (always hits) |

"accept" = `cpu_req_valid & cpu_req_ready`. When accepted, the S1 registers load from the
CPU request. In every other state the S1 registers hold, so the miss request stays in S1
until it completes.

### 6.2 Ready / response equations

```verilog
assign cpu_req_ready  = (state_q == IDLE) | (s1_hit & ~s1_we_q);
assign cpu_resp_valid = s1_hit;          // loads and stores both get one response
```

`cpu_req_ready` does not depend on `cpu_req_valid`, so the valid/ready rules hold and no
combinational loop exists with the core. It does depend on the tag-SRAM output through the
comparator; that is the main timing path (§7).

### 6.3 Beat counter

| State | Increment condition | Clear |
|-------|--------------------|-------|
| WB_RD | every cycle | on exit |
| WB_DATA | `mem_wvalid & mem_wready` | on exit |
| RF_DATA | `mem_rvalid` | on entry (in RF_REQ) |

## 7. Timing & Pipeline

| Operation | Latency (accept → `cpu_resp_valid`) | Throughput |
|-----------|-------------------------------------|------------|
| Load hit | 1 cycle | 1 / cycle |
| Store hit | 1 cycle | 1 / 2 cycles |
| Clean miss (load or store) | `L + 11` cycles | – |
| Dirty miss | ≈ `L + W + 29` cycles (see below) | – |

Here `L` = cycles from the refill request handshake to the first `mem_rvalid`, assuming the
8 beats arrive back-to-back. `W` = cycles from the last write beat to `mem_wdone`.

Clean-miss breakdown (request accepted at cycle −1):
LOOKUP (0) → RF_REQ (1, `mem_req_ready` in the same cycle) → first beat at `1+L` → last beat
at `L+8` → REPLAY at `L+9` → LOOKUP hit and response at `L+10`. That is `L+11` cycles from
acceptance. With L = 10: 21 cycles.

The dirty miss adds WB_RD (9) + WB_REQ (≥1) + WB_DATA (≥8) + WB_WAIT (W) ≈ 18 + W cycles,
before RF_REQ.

**Hit pipeline example** (A, B: load hits; C: store hit; D: load hit):

| Cycle | Req on CPU bus | `cpu_req_ready` | State | S1 holds | SRAM activity | `cpu_resp_valid` |
|-------|----------------|-----------------|-------|----------|---------------|------------------|
| 0 | A | 1 | IDLE | – | read A | 0 |
| 1 | B | 1 | LOOKUP | A (hit) | read B | 1 (A data) |
| 2 | C (st) | 1 | LOOKUP | B (hit) | read C | 1 (B data) |
| 3 | D | **0** | LOOKUP | C (st hit) | **write C** | 1 (C ack) |
| 4 | D | 1 | IDLE | – | read D | 0 |
| 5 | – | 1 | LOOKUP | D (hit) | – | 1 (D data) |

**Critical paths**
1. `tag_rdata` (SRAM clock-to-Q) → 20-bit comparator → AND `valid_q[s1_idx]` (128:1 mux) → `cpu_req_ready` → core issue logic → back into the S0 SRAM address mux. This is the classic cache-ready path. If timing fails, the fallback is `cpu_req_ready = (state==IDLE) | (state==LOOKUP & ~s1_we_q)` with S1-stall logic. That would cost an extra replay on a miss.
2. `data_rdata` → `cpu_resp_rdata` → core load-align/forwarding logic.

## 8. Clocking & Reset

- **Single clock** `clk` for the cache, SRAMs and both interfaces. The interconnect is
  synchronous to `clk` (no CDC). If the interconnect runs on another clock, an async bridge
  is placed outside this block.
- **Reset:** `rst_n` active low, async assert / sync de-assert. Reset clears `state_q`,
  `valid_q`, `dirty_q` and the counters. The SRAM contents are not initialized; with
  `valid_q = 0` every tag is ignored, so no 128-cycle init sweep is needed (the PD
  request).
- **SRAM enables:** `ce` is asserted only in the rows of §5.3, to save power.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| Store miss | Write-allocate: (writeback) → refill → REPLAY → store hit writes data and sets dirty. One response. |
| Victim invalid | Treated as clean; no writeback even if `dirty_q` holds a stale 1 (dirty is only meaningful when valid). |
| Miss to the same index as the victim, different tag | Normal case for direct-mapped; handled as above. |
| `mem_req_ready` held low | FSM waits in WB_REQ / RF_REQ; the CPU stays stalled (`cpu_req_ready = 0`). |
| `mem_wready` back-pressure | WB_DATA holds `mem_wvalid` and the current beat; the buffer decouples it from the SRAM. |
| Gaps between `mem_rvalid` beats | RF_DATA waits; `beat_q` advances only on valid beats. |
| `mem_rvalid` outside RF_DATA | Protocol error; the data is ignored. An assertion flags it in simulation. |
| `mem_rlast` on a beat other than the 8th | Protocol error; an assertion flags it. The design trusts `mem_rlast` to end the refill. |
| Store with `wstrb = 0` | Treated as a store hit/miss with no bytes changed; the line is still marked dirty (benign). |
| Load immediately after a store to the same word | The store blocks S0 for one cycle, so the load reads the SRAM after the write commits; no bypass needed. |
| Reset during a miss | Burst is abandoned; the interconnect must also be reset (same reset domain). |
| Interconnect errors | The protocol has no error response; nothing to handle. See §11. |

## 10. Verification Plan

**Environment:** a SystemVerilog testbench with:
- A CPU-side driver issuing random loads/stores, with a configurable address pool. A small pool of tags at the same index forces evictions.
- A memory-side slave model that has a backing sparse memory, configurable random latency `L` ∈ [1, 30], random `mem_req_ready`/`mem_wready` stalls, and random gaps between read beats.
- A scoreboard holding a golden flat-memory model. Every load response is compared with the golden value at that address. At end of test, the cache contents are flushed by a test-only backdoor that walks dirty lines, and backing memory is compared with the golden model.

**Directed tests**
1. Cold load miss → refill → hit on all 8 words of the line.
2. Back-to-back load hits at 1/cycle (check `cpu_req_ready` stays high).
3. Store hit, then load of the same word (RAW through the SRAM).
4. Store miss (allocate) followed by an eviction of that line (writeback contents correct, including partial byte strobes).
5. Dirty eviction with max `mem_wready` back-pressure.
6. Clean eviction (no writeback burst issued).
7. Ping-pong two tags at one index for 1000 iterations.
8. Reset mid-refill, then normal operation.

**Random:** 1M requests; mix of 60% loads / 40% stores; address pools sized at 0.5×, 1× and
8× cache capacity.

**Assertions (SVA)**

```systemverilog
a_one_resp:   // every accepted request gets exactly one response, in order (tracked by counter)
  assert property (@(posedge clk) disable iff(!rst_n) resp_cnt <= req_cnt && req_cnt - resp_cnt <= 1);
a_ready_st:   assert property (@(posedge clk) disable iff(!rst_n)
                (s1_hit && s1_we_q) |-> !cpu_req_ready);
a_replay_hit: assert property (@(posedge clk) disable iff(!rst_n)
                (state_q == REPLAY) |=> s1_hit);
a_rvalid_ok:  assert property (@(posedge clk) disable iff(!rst_n)
                mem_rvalid |-> state_q == RF_DATA);
a_rlast_8:    assert property (@(posedge clk) disable iff(!rst_n)
                (mem_rvalid && mem_rlast) |-> beat_q == 7);
a_wb_addr:    assert property (@(posedge clk) disable iff(!rst_n)
                mem_req_valid |-> mem_req_addr[4:0] == 5'b0);
a_sram_1port: assert property (@(posedge clk) disable iff(!rst_n)
                !(u_data_ram.we && cpu_req_valid && cpu_req_ready));
```

**Coverage:** every FSM state and transition; load/store × hit/clean miss/dirty miss; all 16
`wstrb` patterns on stores; back-pressure on each memory channel; `L` min/max; consecutive
misses to the same index; accept in LOOKUP (pipelined hit).

## 11. Assumptions & Open Questions

1. **Cache maintenance ops are not supported in this version.** Proposed follow-up: a `flush_req`/`inv_req` port with FLUSH states that walk all 128 indices, write back dirty lines and clear `valid_q`. The flop-based valid/dirty bits make invalidate-all a 1-cycle operation.
2. **There are no uncached/MMIO regions.** All accesses are cached. Recommendation: the core or a wrapper decodes MMIO ranges and bypasses the cache. Alternatively, add a `cpu_req_uncached` bit with single-beat memory transactions, which would require extending the interconnect protocol.
3. **No critical-word-first.** The interconnect always bursts from word 0. The replay approach costs 2 cycles after the last beat. Early restart (returning the requested word as it streams in) is a possible future optimization: about `7 − word` cycles saved on average.
4. **The writeback completes before the refill starts** (we wait for `mem_wdone`). The victim and refill addresses are always different, so issuing the refill during WB_DATA would be safe if the interconnect keeps reads and writes independent. That would save about W+8 cycles per dirty miss. It is deferred until the interconnect ordering rules are confirmed.
5. **Store hits take 2 cycles** (allowed by the brief). A 1-entry store buffer that writes during the next idle data-SRAM cycle would give 1/cycle stores, at the cost of load-to-store-buffer address-compare logic.
6. **There is no error response** from the interconnect. If a bus error is added later, the refill would need to abort without setting valid, and an error flag would go back to the core.
7. **The core never sends a new request before the previous response arrives**, except through the pipelined read-hit path, which `cpu_req_ready` controls. There is no `cpu_resp_ready`: the core always accepts responses.
8. The SRAM read data is **not held** across cycles where `ce = 0`. The design never relies on that (the victim tag is captured into a register).
