# Micro-architecture: `dma4_axi`

## 1. Overview

`dma4_axi` is a 4-channel memory-to-memory DMA engine. Software programs each channel's
source, destination and length through an AXI4-Lite slave port and then sets START. One
shared transfer engine, with one AXI4 master port, services the active channels **one burst
at a time**, picking the next channel with a round-robin arbiter after every burst. A
channel moving megabytes therefore gets at most one burst before the others get a turn.

Each burst is a read burst into a 16-word internal buffer, followed by a write burst from
that buffer. The burst length is the largest value that:
- does not exceed `MAX_BURST` (16) beats,
- does not exceed the remaining length, and
- does not cross a 4 KB boundary on either the source or the destination address.

v1 scope (decisions on the open items, see §11):
- Word-aligned transfers only (SRC, DST, LEN multiples of 4); misalignment is a configuration error.
- Maximum burst 16 beats × 32 bit.
- No read/write overlap (the read burst completes before the write burst starts).
- Graceful abort at burst boundaries.
- A per-channel REMAIN register shows progress.
- Completion, error and abort are reported per channel; one `dma_irq` output with enables.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `ACLK` | in | 1 | Single clock for both AXI ports. |
| `ARESETn` | in | 1 | Active-low reset (AXI convention: sync de-assert). |
| **AXI4-Lite slave (registers)** | | | |
| `s_awaddr` | in | 8 | Write address (byte offset). |
| `s_awvalid` / `s_awready` | in / out | 1 / 1 | Write-address handshake. |
| `s_wdata` | in | 32 | Write data. |
| `s_wstrb` | in | 4 | Byte strobes (see §11, item 7). |
| `s_wvalid` / `s_wready` | in / out | 1 / 1 | Write-data handshake. |
| `s_bresp` | out | 2 | OKAY, or SLVERR for unmapped offsets. |
| `s_bvalid` / `s_bready` | out / in | 1 / 1 | Write-response handshake. |
| `s_araddr` | in | 8 | Read address. |
| `s_arvalid` / `s_arready` | in / out | 1 / 1 | Read-address handshake. |
| `s_rdata` | out | 32 | Read data. |
| `s_rresp` | out | 2 | OKAY / SLVERR. |
| `s_rvalid` / `s_rready` | out / in | 1 / 1 | Read-data handshake. |
| **AXI4 master — read** | | | |
| `m_araddr` | out | 32 | Burst start address. |
| `m_arlen` | out | 8 | Beats − 1 (0..15). |
| `m_arsize` | out | 3 | Constant `3'b010` (4 bytes). |
| `m_arburst` | out | 2 | Constant `2'b01` (INCR). |
| `m_arid`, `m_arlock`, `m_arcache`, `m_arprot` | out | 1, 1, 4, 3 | Constants 0, 0, `4'b0011`, `3'b000`. |
| `m_arvalid` / `m_arready` | out / in | 1 / 1 | Read-address handshake. |
| `m_rdata` | in | 32 | Read data. |
| `m_rresp` | in | 2 | Read response per beat. |
| `m_rlast` | in | 1 | Last read beat. |
| `m_rvalid` / `m_rready` | in / out | 1 / 1 | Read-data handshake. |
| **AXI4 master — write** | | | |
| `m_awaddr` | out | 32 | Burst start address. |
| `m_awlen` | out | 8 | Beats − 1. |
| `m_awsize`, `m_awburst`, `m_awid`, `m_awlock`, `m_awcache`, `m_awprot` | out | – | Same constants as the read channel. |
| `m_awvalid` / `m_awready` | out / in | 1 / 1 | Write-address handshake. |
| `m_wdata` | out | 32 | Write data. |
| `m_wstrb` | out | 4 | Constant `4'hF`. |
| `m_wlast` | out | 1 | Last write beat. |
| `m_wvalid` / `m_wready` | out / in | 1 / 1 | Write-data handshake. |
| `m_bresp` | in | 2 | Write response. |
| `m_bvalid` / `m_bready` | in / out | 1 / 1 | Write-response handshake. |
| **Interrupt** | | | |
| `dma_irq` | out | 1 | Level, active high: `\|(IRQ_STATUS & IRQ_EN)`. |

### Register map (AXI4-Lite, 32-bit, channel *n* at `0x20 × n`)

| Offset | Name | Access | Reset | Fields |
|--------|------|--------|-------|--------|
| +0x00 | CHn_SRC | RW (RO while BUSY) | 0 | Source address; [1:0] must be 0 |
| +0x04 | CHn_DST | RW (RO while BUSY) | 0 | Destination address; [1:0] must be 0 |
| +0x08 | CHn_LEN | RW (RO while BUSY) | 0 | Length in bytes; [1:0] must be 0 |
| +0x0C | CHn_CTRL | WO (reads 0) | – | [0] START, [1] ABORT (write-1 pulses) |
| +0x10 | CHn_STATUS | mixed | 0 | [0] BUSY (RO), [1] DONE (W1C), [2] ERR (W1C), [3] ABORTED (W1C), [5:4] ERR_CODE (RO) |
| +0x14 | CHn_REMAIN | RO | 0 | Bytes remaining in the current transfer |
| 0x80 | IRQ_STATUS | RO | 0 | [3:0] DONE\|ABORTED per channel, [7:4] ERR per channel |
| 0x84 | IRQ_EN | RW | 0 | [7:0] enables matching IRQ_STATUS |

ERR_CODE: 0 = none, 1 = read response error, 2 = write response error, 3 = configuration
error. Interrupts are cleared by W1C writes to CHn_STATUS. IRQ_STATUS is a read-only view, so
there is a single source of truth.

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `NUM_CH` | 4 | fixed 4 | Channels (the register map is laid out for 4). |
| `MAX_BURST` | 16 | 1–256, power of 2 | Max beats per burst; also the buffer depth. |
| `DATA_W` | 32 | fixed 32 | AXI data width. |
| `ADDR_W` | 32 | fixed 32 | AXI address width. |
| `BEAT_W` | `$clog2(MAX_BURST)+1` = 5 | derived | Width that can hold 1..MAX_BURST. |
| `PAGE_WORDS` | 1024 | derived | 4096 / 4: words per 4 KB page. |

## 4. Block Diagram

```
             AXI4-Lite slave                                         dma_irq
                  |                                                     ^
                  v                                                     |
        +-------------------+  cfg/start/abort   +-------------------------------+
        |  u_regs           |------------------->|  u_ch[0..3]  dma_channel      |
        |  axil_slave +     |<-- status/remain --|  SRC/DST/LEN, cur_src/cur_dst,|
        |  decode/readmux   |                    |  remain, busy/done/err/abort  |
        +-------------------+                    +-------------------------------+
                                                     | busy[3:0]     ^ update/ack
                                                     v               |
                                              +-------------+        |
                                              |  u_arb      |  grant |
                                              |  rr_arb4    |--------+
                                              +------+------+        |
                                                     | gnt_id        |
                                                     v               |
        +---------------------------------------------------------------------+
        |  u_eng  dma_engine                                                  |
        |   FSM: IDLE→ARB→CALC→RD_ADDR→RD_DATA→WR→WR_RESP→UPDATE              |
        |   burst calc (min of rem, MAX_BURST, src 4K room, dst 4K room)      |
        |   +----------------------+                                          |
        |   | u_buf 16 x 32 regs   |  R beats in ---> W beats out             |
        |   +----------------------+                                          |
        +---------------------------------------------------------------------+
                 |  AR / R                         |  AW / W / B
                 v                                 v
                         AXI4 master port
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_regs` | `dma_axil_regs` | AXI4-Lite slave protocol, address decode, read mux, register write strobes. |
| `u_ch[n]` | `dma_channel` (×4, `generate`) | Programmed and working registers, status bits, start/abort/config checking. |
| `u_arb` | `rr_arb4` | Round-robin arbiter over `busy & ~err` requests. |
| `u_eng` | `dma_engine` | Burst sizing, AXI4 master sequencing, data buffer, response checking. |
| `u_buf` | inline in `u_eng` | `MAX_BURST × 32` register array, written by R beats and read by W beats. |

## 5. Datapath

### 5.1 Per-channel registers (`dma_channel`)

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `src_q` | 32 | 0 | Programmed source (SW view). |
| `dst_q` | 32 | 0 | Programmed destination. |
| `len_q` | 32 | 0 | Programmed length (bytes). |
| `cur_src_q` | 32 | 0 | Working source pointer. |
| `cur_dst_q` | 32 | 0 | Working destination pointer. |
| `rem_q` | 32 | 0 | Remaining bytes (= CHn_REMAIN). |
| `busy_q` | 1 | 0 | Transfer in progress. |
| `done_q` | 1 | 0 | Sticky, W1C. |
| `err_q` | 1 | 0 | Sticky, W1C. |
| `aborted_q` | 1 | 0 | Sticky, W1C. |
| `err_code_q` | 2 | 0 | Cause of the last error. Cleared on START. |
| `abort_pend_q` | 1 | 0 | Abort requested while the engine owns this channel. |

Start sequence (CTRL write with bit 0 = 1, while `!busy_q`):

```verilog
cfg_bad = (src_q[1:0] != 0) | (dst_q[1:0] != 0) | (len_q[1:0] != 0);
if (cfg_bad)           {err_q, err_code_q} <= {1'b1, 2'd3};     // not started
else if (len_q == 0)   done_q <= 1'b1;                          // nothing to do
else begin
  cur_src_q <= src_q; cur_dst_q <= dst_q; rem_q <= len_q;
  busy_q <= 1'b1; err_code_q <= 2'd0;
end
```

Engine update (from `u_eng` at UPDATE, for the granted channel only):

```verilog
if (upd_ok) begin
  cur_src_q <= cur_src_q + {beats, 2'b00};
  cur_dst_q <= cur_dst_q + {beats, 2'b00};
  rem_q     <= rem_q     - {beats, 2'b00};
  if (rem_q == {beats, 2'b00}) begin busy_q <= 0; done_q <= 1; end
  else if (abort_pend_q)       begin busy_q <= 0; aborted_q <= 1; end
end
if (upd_err) begin busy_q <= 0; err_q <= 1; err_code_q <= eng_err_code; end
```

Completion takes priority over a pending abort: if the last burst completes, the transfer is
DONE. `abort_pend_q` is cleared whenever `busy_q` falls.

### 5.2 Engine registers (`dma_engine`)

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `state_q` | 3 | IDLE | Engine FSM. |
| `gnt_q` | 2 | 0 | Channel being serviced. |
| `addr_r_q` | 32 | 0 | Burst read address (latched `cur_src`). |
| `addr_w_q` | 32 | 0 | Burst write address (latched `cur_dst`). |
| `beats_q` | 5 | 0 | Beats in this burst (1..16). |
| `rcnt_q` | 5 | 0 | Read beats received / buffer write index. |
| `wcnt_q` | 5 | 0 | Write beats sent / buffer read index. |
| `aw_done_q` | 1 | 0 | AW handshake completed in WR. |
| `rerr_q` | 1 | 0 | Any RRESP ≠ OKAY in this burst. |
| `buf_q[0:15]` | 32 each | not reset | Data buffer. |

### 5.3 Burst-length calculation (CALC, registered)

```verilog
wire [29:0] words_rem = cur_rem[31:2];                     // of the granted channel
wire [10:0] src_room  = 11'd1024 - {1'b0, cur_src[11:2]};  // 1..1024 words to the 4KB edge
wire [10:0] dst_room  = 11'd1024 - {1'b0, cur_dst[11:2]};
beats_n = min4(words_rem, MAX_BURST, src_room, dst_room);  // ≥ 1 because rem > 0
```

`min4` is three cascaded comparator/mux stages. The comparison against `words_rem` saturates
first (`|words_rem[29:5] ? MAX_BURST : words_rem[4:0]`) to keep the comparators 11 bits wide.
The result is registered into `beats_q` at the end of CALC, so the path never reaches the AXI
outputs.

`m_arlen = m_awlen = beats_q - 1`. Because the read and write bursts both use `beats_q` and
each was clipped to its own 4 KB room, neither burst crosses a page.

### 5.4 Data buffer

- R phase: on `m_rvalid & m_rready`, `buf_q[rcnt_q] <= m_rdata; rcnt_q++`.
- W phase: `m_wdata = buf_q[wcnt_q]`; `m_wlast = (wcnt_q == beats_q - 1)`; on `m_wvalid & m_wready`, `wcnt_q++`.

Read and write are never concurrent in v1, so a simple indexed array is enough (no FIFO
full/empty logic).

### 5.5 Round-robin arbiter (`rr_arb4`)

```verilog
req[n]  = busy[n] & ~err[n];
// rotate req by ptr_q, pick lowest set bit (fixed priority), rotate back
gnt     = rr_pick(req, ptr_q);
ptr_n   = (gnt_valid & arb_en) ? gnt_id + 1 : ptr_q;   // 2-bit wrap
```

`arb_en` is pulsed by the engine in ARB. `ptr_q` (2 bits, reset 0) makes the channel after
the last-granted one the highest priority, which gives strict fairness at burst granularity.

### 5.6 AXI4-Lite slave (`dma_axil_regs`)

- Write: AW and W are accepted independently into holding registers (`aw_hold_q`, `w_hold_q` with valid flags). When both are held and `!s_bvalid`, the register write is performed and `s_bvalid` is set (`s_bresp = SLVERR` if unmapped). `s_awready = !aw_held & !s_bvalid`, and the same for `s_wready`.
- Read: `s_arready = !s_rvalid`. On the handshake, the read mux result is registered into `s_rdata` and `s_rvalid` is set the next cycle; `s_rvalid` is held until `s_rready`.
- Each channel gets one-hot write strobes (`we_src[n]`, `we_ctrl[n]`, …) for one cycle.

## 6. Control Logic

### 6.1 Engine FSM

Encoding: 3-bit binary.

| State | Enc | Outputs | Transitions |
|-------|-----|---------|-------------|
| IDLE | 0 | – | `\|req` → ARB |
| ARB | 1 | `arb_en`; latch `gnt_q` | → CALC (a request is guaranteed: IDLE only exits on `\|req`; if the requester was aborted meanwhile, `!gnt_valid` → IDLE) |
| CALC | 2 | latch `beats_q`, `addr_r_q`, `addr_w_q`; clear counters, `rerr_q` | → RD_ADDR |
| RD_ADDR | 3 | `m_arvalid` | `m_arready` → RD_DATA |
| RD_DATA | 4 | `m_rready = 1` | `m_rvalid & m_rlast` → (`rerr_q \| rresp_err`) ? UPDATE(error) : WR |
| WR | 5 | `m_awvalid = !aw_done_q`; `m_wvalid = 1` | `aw_done & last W handshake` → WR_RESP |
| WR_RESP | 6 | `m_bready = 1` | `m_bvalid` → UPDATE |
| UPDATE | 7 | `upd_ok` or `upd_err` pulse to `u_ch[gnt_q]` | → IDLE |

In WR the address and data channels run in parallel (AXI allows W before AW).
`aw_done_q` is set on `m_awvalid & m_awready`. The exit condition requires both the AW
handshake and the `m_wlast` beat handshake, in either order or in the same cycle.

`eng_err_code` = 1 if `rerr_q` (read error), or 2 if `m_bresp[1]` in WR_RESP (SLVERR=2'b10,
DECERR=2'b11).

### 6.2 Channel status FSM (per channel, implied by bits)

| State | `busy` | Event | Next |
|-------|--------|-------|------|
| IDLE | 0 | START & config OK & LEN>0 | ACTIVE |
| IDLE | 0 | START & config bad | IDLE, ERR=1, code 3 |
| IDLE | 0 | START & LEN=0 | IDLE, DONE=1 |
| ACTIVE | 1 | `upd_ok` & last | IDLE, DONE=1 |
| ACTIVE | 1 | `upd_ok` & abort_pend | IDLE, ABORTED=1 |
| ACTIVE | 1 | `upd_err` | IDLE, ERR=1, code 1/2 |
| ACTIVE | 1 | ABORT & engine not on this channel (`!(eng_busy & gnt_q==n)`) | IDLE, ABORTED=1 (immediate) |
| ACTIVE | 1 | ABORT & engine on this channel | ACTIVE, abort_pend=1 (stops at UPDATE) |
| ACTIVE | 1 | START | ignored |

`eng_busy = (state_q inside {CALC..UPDATE})`. The engine samples a channel's working
registers only in CALC, after ARB. A channel aborted between ARB and CALC is handled by the
"engine on this channel" row, because `gnt_q` is already latched in ARB.

### 6.3 Interrupt

```verilog
irq_status = {err_q[3:0], done_q[3:0] | aborted_q[3:0]};
dma_irq    = |(irq_status & irq_en_q);
```

## 7. Timing & Pipeline

**Per-burst occupancy** (no overlap): `1 (ARB) + 1 (CALC) + Tar + Lr + B_R + Taw/w + B_W + Lb + 1 (UPDATE)`.

Example: a 4-beat burst, `m_arready` immediate, first R beat 2 cycles after the AR
handshake, beats back-to-back, `m_awready`/`m_wready` always 1, B arrives 2 cycles after
`wlast`:

| Cycle | State | AR | R | AW | W | B | Note |
|-------|-------|----|---|----|---|---|------|
| 0 | ARB | | | | | | grant ch0, ptr → 1 |
| 1 | CALC | | | | | | beats_q ← 4 |
| 2 | RD_ADDR | V,R | | | | | AR handshake |
| 3 | RD_DATA | | | | | | waiting |
| 4 | RD_DATA | | b0 | | | | |
| 5 | RD_DATA | | b1 | | | | |
| 6 | RD_DATA | | b2 | | | | |
| 7 | RD_DATA | | b3 L | | | | rlast |
| 8 | WR | | | V,R | w0 | | AW + first W |
| 9 | WR | | | | w1 | | |
| 10 | WR | | | | w2 | | |
| 11 | WR | | | | w3 L | | wlast |
| 12 | WR_RESP | | | | | | |
| 13 | WR_RESP | | | | | V | BRESP OKAY |
| 14 | UPDATE | | | | | | ch0: cur += 16 B, rem −= 16 B |
| 15 | IDLE→ARB | | | | | | next channel |

That is 15 cycles for 16 bytes. For a full 16-beat burst under the same latencies, it is
39 cycles for 64 bytes ≈ 1.64 B/cycle (41% of the 4 B/cycle port peak). Overlapping reads and
writes (§11) roughly doubles that.

**Fairness latency:** with all 4 channels active, a channel waits at most 3 bursts
(≈ 3 × 39 cycles) between its own bursts.

**Register access latency:** AXI4-Lite write takes 1 cycle from both AW+W held to `s_bvalid`;
a read returns `s_rvalid` 1 cycle after the AR handshake.

**Critical paths:** `cur_src/cur_dst/rem` mux (4:1 by `gnt_q`) → 11-bit subtract → 3-level
min → `beats_q`. This is fully contained in CALC. The 32-bit `cur_* + beats*4` adders are
in UPDATE.

## 8. Clocking & Reset

- **Single clock domain**, ACLK, shared by both AXI ports and all logic. No CDC.
- **Reset:** ARESETn, active low. The design uses it synchronously (AXI recommends sync de-assert; the design treats it as a synchronous reset to all control flops). All control state is cleared (`busy=done=err=aborted=0`, engine IDLE, arbiter pointer 0). The data buffer is not reset.
- **AXI reset rules:** `m_arvalid`, `m_awvalid`, `m_wvalid`, `s_bvalid` and `s_rvalid` are driven low during reset and come only from registered state afterwards.
- No clock gating in v1.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| SRC/DST/LEN not word-aligned at START | ERR, code 3; channel never becomes busy; no bus traffic. |
| LEN = 0 at START | DONE immediately; no bus traffic. |
| START while BUSY | Ignored. |
| SRC/DST/LEN write while BUSY | Ignored (registers are RO while busy). The working copies are unaffected. |
| Burst would cross a 4 KB boundary | Clipped at the boundary by the `src_room`/`dst_room` terms; the next burst starts on the new page. |
| SRC and DST at different page offsets | Each burst is clipped by whichever is closer to its boundary; bursts may get short near boundaries but stay legal. |
| RRESP error on any beat | The remaining beats are still accepted (AXI requires completing the burst); `rerr_q` is set; the write phase is skipped (no bad data written); channel ERR code 1. Pointers are not advanced, so REMAIN shows the failing position. |
| BRESP error | Channel ERR code 2; pointers not advanced. |
| Error on one channel | Only that channel stops; the others are still arbitrated (`req` masks `err`). |
| ABORT while the engine is mid-burst on that channel | The burst completes (read and write), then the channel stops with ABORTED. AXI transactions are never truncated. |
| ABORT on an idle channel | Ignored. |
| ABORT on the last burst | DONE takes priority over ABORTED. |
| Address wrap past 0xFFFF_FFFF | Cannot happen inside a burst (the 4 KB clip ensures it); a transfer that wraps the 32-bit space wraps naturally between bursts (documented, not checked). |
| `m_rlast` early/late versus `beats_q` | Protocol violation by the slave; an assertion fires. The design trusts `m_rlast`. |
| Lite writes with partial `s_wstrb` | See §11, item 7. |

## 10. Verification Plan

**Environment:** a SystemVerilog/UVM-style testbench:
- An AXI4-Lite master agent with a register model.
- An AXI4 slave memory model with configurable AR/AW/W ready back-pressure, R/B latency, and error injection by address range.
- An AXI protocol checker (VIP or an open-source SVA checker) on the master port.
- A scoreboard: for each channel, expected destination contents = source contents. It checks memory at DONE, and checks that no bytes outside [DST, DST+LEN) were written.

**Directed tests**
1. Single channel, LEN = 4, 64, 4096, 1 MB; SRC/DST page-aligned.
2. 4 KB crossing: SRC = 0x0FF8, DST = 0x2FF0, LEN = 256. Check every AR/AW burst stays within a page and the burst lengths are as computed.
3. All 4 channels active at once: bursts strictly rotate 0→1→2→3; no channel starved.
4. Misaligned SRC/DST/LEN → ERR code 3, no AXI traffic.
5. LEN = 0 → DONE, no traffic.
6. Read error mid-burst → whole burst consumed, no write issued, ERR code 1, other channels continue.
7. Write error → ERR code 2.
8. ABORT while granted (finishes the burst) and while waiting (immediate).
9. W1C of DONE/ERR/ABORTED; `dma_irq` masking via IRQ_EN.
10. Lite slave: AW before W, W before AW, simultaneous; back-pressure on `s_bready`/`s_rready`.

**Random:** random channel configs (aligned), random start/abort timing, random slave
latencies and back-pressure; 10k transfers. Error injection at a 1% rate.

**Assertions (SVA)**

```systemverilog
a_4k_ar: assert property (@(posedge ACLK) disable iff(!ARESETn)
           m_arvalid |-> (m_araddr[11:0] + ((m_arlen+1) << 2)) <= 13'h1000);
a_4k_aw: assert property (@(posedge ACLK) disable iff(!ARESETn)
           m_awvalid |-> (m_awaddr[11:0] + ((m_awlen+1) << 2)) <= 13'h1000);
a_len_eq:  assert property (@(posedge ACLK) disable iff(!ARESETn)
           m_awvalid |-> m_awlen == beats_q - 1);
a_ar_stable: assert property (@(posedge ACLK) disable iff(!ARESETn)
           (m_arvalid && !m_arready) |=> m_arvalid && $stable(m_araddr) && $stable(m_arlen));
a_wlast:   assert property (@(posedge ACLK) disable iff(!ARESETn)
           (m_wvalid && m_wlast) |-> wcnt_q == beats_q - 1);
a_rlast:   assert property (@(posedge ACLK) disable iff(!ARESETn)
           (m_rvalid && m_rready && m_rlast) |-> rcnt_q == beats_q - 1);
a_onehot_gnt: assert property (@(posedge ACLK) disable iff(!ARESETn)
           upd_ok |-> u_ch[gnt_q].busy_q);
```

**Coverage:** beats 1..16; clip reason (rem / MAX / src page / dst page); every FSM state and
arc; each channel × {DONE, ERR1, ERR2, ERR3, ABORTED-immediate, ABORTED-pending}; 1–4
channels active; arbiter pointer at each value with each request pattern.

## 11. Assumptions & Open Questions

1. **Word-aligned only for v1** (firmware agreed). Byte-granular support would need a byte-shifter/realigner between R and W plus first/last `wstrb` masks.
2. **`MAX_BURST = 16`**, as preferred by the DDR controller. It is a parameter up to 256; the buffer grows with it (`MAX_BURST × 32` flops — use an SRAM above 32).
3. **No read/write overlap.** v2 recommendation: make the buffer a FIFO of 2×MAX_BURST and issue the next burst's AR while the current W streams, giving about 2× throughput.
4. **Progress visibility** is via CHn_REMAIN (bytes left). The programmed SRC/DST/LEN keep their values, so software can restart a transfer by writing START again.
5. **Abort is graceful at burst granularity.** The worst-case abort latency is one burst (≈ 40 cycles at 16 beats).
6. **ARESETn is treated as a synchronous reset** (common for AXI IP). Change to async assert if the SoC reset scheme requires it.
7. **AXI4-Lite writes ignore `s_wstrb`.** Every write updates all 32 bits of the register. Byte-wise register writes are not supported; software is expected to use 32-bit accesses. Confirm with the firmware team.
8. **Unmapped Lite offsets return SLVERR.** Reserved register bits read as zero.
9. **Fixed AXI attributes:** ID 0, AxCACHE = 0011 (normal non-cacheable bufferable), AxPROT = 0. Coherency with CPU caches is software's responsibility.
10. **Interrupt granularity:** a single `dma_irq` line, with sources visible in IRQ_STATUS. Per-channel IRQ lines can be added trivially if the interrupt controller has spare inputs.
