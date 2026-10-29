# Micro-architecture: `ctrl_regs`

## 1. Overview

`ctrl_regs` is an AXI4-Lite slave exposing seven 32-bit control/status registers in a 4 KB
window. It supports RW, RO, W1C (write-1-to-clear) and WO self-clearing (SC) access types,
byte-lane writes via `WSTRB`, and `SLVERR` for unmapped addresses.

Key features:
- Fully independent AW and W acceptance: each channel has its own one-entry holding register, so the address and data can arrive in any order.
- One outstanding write and one outstanding read; all `*READY`/`*VALID` outputs are registered, with no combinational paths from inputs to outputs.
- Interrupt-status register where a hardware set wins over a software clear in the same cycle, so events are never lost; level `irq` output.
- Command bits produce single-cycle pulses to the core and read back as 0.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Global** | | | |
| `aclk` | in | 1 | Clock. |
| `aresetn` | in | 1 | Active-low reset, synchronous to `aclk`. |
| **Write address** | | | |
| `s_awvalid` | in | 1 | |
| `s_awready` | out | 1 | `!aw_full_q && rst_done_q`. |
| `s_awaddr` | in | 12 | Byte address; bits [1:0] ignored. |
| `s_awprot` | in | 3 | Ignored. |
| **Write data** | | | |
| `s_wvalid` | in | 1 | |
| `s_wready` | out | 1 | `!w_full_q && rst_done_q`. |
| `s_wdata` | in | 32 | |
| `s_wstrb` | in | 4 | Byte-lane enables. |
| **Write response** | | | |
| `s_bvalid` | out | 1 | |
| `s_bready` | in | 1 | |
| `s_bresp` | out | 2 | `2'b00` OKAY, `2'b10` SLVERR. |
| **Read address** | | | |
| `s_arvalid` | in | 1 | |
| `s_arready` | out | 1 | `!rvalid_q && rst_done_q`. |
| `s_araddr` | in | 12 | |
| `s_arprot` | in | 3 | Ignored. |
| **Read data** | | | |
| `s_rvalid` | out | 1 | |
| `s_rready` | in | 1 | |
| `s_rdata` | out | 32 | |
| `s_rresp` | out | 2 | OKAY / SLVERR. |
| **Core side** | | | |
| `ctrl_en` | out | 1 | CTRL.EN |
| `ctrl_mode` | out | 3 | CTRL.MODE |
| `ctrl_prescale` | out | 8 | CTRL.PRESCALE |
| `cmd_start` | out | 1 | 1-cycle pulse. |
| `cmd_abort` | out | 1 | 1-cycle pulse. |
| `cmd_soft_rst` | out | 1 | 1-cycle pulse. |
| `sts_busy` | in | 1 | STATUS.BUSY (live, same clock domain). |
| `sts_fifo_empty` | in | 1 | |
| `sts_fifo_full` | in | 1 | |
| `sts_fifo_level` | in | 8 | |
| `evt_set` | in | 4 | Event pulses: [0] DONE, [1] ERR, [2] OVF, [3] UNF. |
| `irq` | out | 1 | Level interrupt, registered. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `ADDR_W` | 12 | 5–32 | Address width (window size 2^ADDR_W bytes). |
| `VERSION` | `32'h0001_0000` | any | Value of the VERSION register. |
| `PRESCALE_RST` | `8'h01` | any | Reset value of CTRL.PRESCALE. |
| `IDX_W` | `ADDR_W-2` | derived | Word-index width. |

## 4. Block Diagram

```
  AW ch --->[aw hold: aw_full_q, aw_addr_q]---+
                                              +--> write ctrl --(wr_en, wr_idx, wr_data, wr_strb)--+
  W  ch --->[w hold:  w_full_q, w_data_q,     |    (do_write)                                     |
                      w_strb_q]---------------+          |                                        v
                                                         v                             +---------------------+
  B  ch <---[bvalid_q, bresp_q]<--------------------- decode (mapped?)                 |  register bank      |
                                                                                       |  CTRL  INT_EN       |
  AR ch --->(ar_fire)---> read decode + mux -->[rdata_q, rresp_q, rvalid_q]---> R ch   |  INT_STATUS (W1C)   |
                                   ^                                                   |  SCRATCH  CMD (SC)  |
                                   +----------------- register values / STATUS inputs--|  STATUS/VERSION(RO) |
                                                                                       +---------------------+
                                           evt_set --> INT_STATUS set ;  irq_q = |(INT_STATUS & INT_EN)
```

| Instance | Module | Purpose |
|----------|--------|---------|
| — (inline) | AW/W holding regs | Decouple AW and W arrival. |
| — (inline) | write control | Executes the write when both are held and the B channel is free. |
| — (inline) | register bank | Storage and access-type semantics. |
| — (inline) | read control | Single-cycle decode + registered read data. |

## 5. Datapath

**Registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `aw_full_q` | 1 | 0 | AW holding register occupied. |
| `aw_idx_q` | `IDX_W` | 0 | Held write word index (`awaddr[ADDR_W-1:2]`). |
| `w_full_q` | 1 | 0 | W holding register occupied. |
| `w_data_q` | 32 | 0 | Held write data. |
| `w_strb_q` | 4 | 0 | Held write strobes. |
| `bvalid_q` | 1 | 0 | Write response pending. |
| `bresp_q` | 2 | 0 | Write response code. |
| `rvalid_q` | 1 | 0 | Read response pending. |
| `rdata_q` | 32 | 0 | Read data. |
| `rresp_q` | 2 | 0 | Read response code. |
| `ctrl_q` | 16 (bits [3:0], [15:8] used) | `{PRESCALE_RST, 4'b0, 3'b0, 1'b0}` | CTRL. |
| `int_sts_q` | 4 | 0 | INT_STATUS. |
| `int_en_q` | 4 | 0 | INT_ENABLE. |
| `scratch_q` | 32 | 0 | SCRATCH. |
| `cmd_q` | 3 | 0 | START/ABORT/SOFT_RST pulse registers. |
| `irq_q` | 1 | 0 | Registered interrupt. |
| `rst_done_q` | 1 | 0 | Goes high one cycle after reset release; gates the READY outputs. |

**Address decode** (word index = `addr[11:2]`):

| Index | Register | Read value | Write effect | Resp |
|-------|----------|------------|--------------|------|
| 0x000 | CTRL | `{16'b0, ctrl_q[15:8], 4'b0, ctrl_q[3:0]}` | byte-merged RW (masked to defined bits) | OKAY |
| 0x001 | STATUS | `{16'b0, sts_fifo_level, 5'b0, sts_fifo_full, sts_fifo_empty, sts_busy}` | ignored | OKAY |
| 0x002 | INT_STATUS | `{28'b0, int_sts_q}` | W1C on bits [3:0] (lane 0) | OKAY |
| 0x003 | INT_ENABLE | `{28'b0, int_en_q}` | RW bits [3:0] (lane 0) | OKAY |
| 0x004 | CMD | `32'b0` | pulses (lane 0 bits [1:0], lane 3 bit 31) | OKAY |
| 0x005 | SCRATCH | `scratch_q` | byte-merged RW | OKAY |
| 0x006 | VERSION | `VERSION` | ignored | OKAY |
| other | – | `32'b0` | ignored | **SLVERR** |

**Byte-lane merge** for RW registers:

```verilog
function [31:0] merge(input [31:0] old, input [31:0] d, input [3:0] s);
  merge = { s[3] ? d[31:24] : old[31:24], s[2] ? d[23:16] : old[23:16],
            s[1] ? d[15:8]  : old[15:8],  s[0] ? d[7:0]   : old[7:0] };
endfunction
```

**INT_STATUS (W1C, set-wins)**

```verilog
wire [3:0] clr = (do_write && wr_idx == 2 && w_strb_q[0]) ? w_data_q[3:0] : 4'b0;
int_sts_q <= (int_sts_q & ~clr) | evt_set;      // set wins over clear
irq_q     <= |(int_sts_n & int_en_n);           // based on next-state values
```

**CMD (self-clearing)**

```verilog
cmd_q[0] <= do_write && wr_idx == 4 && w_strb_q[0] && w_data_q[0];   // START
cmd_q[1] <= do_write && wr_idx == 4 && w_strb_q[0] && w_data_q[1];   // ABORT
cmd_q[2] <= do_write && wr_idx == 4 && w_strb_q[3] && w_data_q[31];  // SOFT_RST
```

Each `cmd_q` bit is high for exactly one cycle after the write executes.

## 6. Control Logic

**Write path**

```verilog
aw_fire  = s_awvalid && s_awready;     // s_awready = !aw_full_q && rst_done_q
w_fire   = s_wvalid  && s_wready;      // s_wready  = !w_full_q  && rst_done_q
do_write = aw_full_q && w_full_q && !bvalid_q;
```

| Register | Next value |
|----------|------------|
| `aw_full_q` | `do_write ? 0 : (aw_fire ? 1 : aw_full_q)` |
| `w_full_q` | `do_write ? 0 : (w_fire ? 1 : w_full_q)` |
| `bvalid_q` | `do_write ? 1 : (s_bready ? 0 : bvalid_q)` |
| `bresp_q` | on `do_write`: `mapped(aw_idx_q) ? OKAY : SLVERR` |

`do_write` and `aw_fire` cannot coincide for the same holding register, because
`aw_fire` requires `!aw_full_q` while `do_write` requires `aw_full_q`. The same holds for W.

Write-channel state (per transaction):

| State | `aw_full` | `w_full` | `bvalid` | Next |
|-------|-----------|----------|----------|------|
| IDLE | 0 | 0 | 0 | AW_ONLY / W_ONLY / BOTH |
| AW_ONLY | 1 | 0 | 0 | BOTH on `w_fire` |
| W_ONLY | 0 | 1 | 0 | BOTH on `aw_fire` |
| BOTH | 1 | 1 | 0 | RESP (`do_write`, register updated) |
| RESP | 0 | 0 | 1 | IDLE on `s_bready` (the next AW/W may already be accepted during RESP) |

**Read path**

```verilog
s_arready = !rvalid_q && rst_done_q;
ar_fire   = s_arvalid && s_arready;
```

| Register | Next value |
|----------|------------|
| `rvalid_q` | `ar_fire ? 1 : (s_rready ? 0 : rvalid_q)` |
| `rdata_q` | on `ar_fire`: `read_mux(s_araddr[11:2])` |
| `rresp_q` | on `ar_fire`: `mapped(idx) ? OKAY : SLVERR` |

## 7. Timing & Pipeline

- **Write latency:** if AW and W arrive together in cycle N, the register updates at the end of N+1 and `BVALID` is high from N+2.
- **Read latency:** an AR in cycle N gives `RVALID` and `RDATA` in N+1.
- **Throughput:** one write per 2 cycles and one read per 2 cycles (reads and writes run concurrently). This is acceptable for a control path, per the spec.

| Cyc | AWV/AWR | WV/WR | aw_full | w_full | do_write | BV/BR | ARV/ARR | RV/RR | Note |
|-----|---------|-------|---------|--------|----------|-------|---------|-------|------|
| 0 | 1/1 | 0/1 | 0 | 0 | 0 | 0/1 | 1/1 | 0/1 | AW for SCRATCH accepted; read of CTRL accepted |
| 1 | 0/0 | 1/1 | 1 | 0 | 0 | 0/1 | 0/0 | 1/1 | W arrives one cycle late; CTRL data returned |
| 2 | 0/0 | 0/0 | 1 | 1 | **1** | 0/1 | 1/1 | 0/1 | SCRATCH updated at end of cycle; read of SCRATCH (returns OLD value) |
| 3 | 1/1 | 1/1 | 0 | 0 | 0 | 1/1 | 0/0 | 1/1 | B OKAY; next AW+W (to 0x100, unmapped) accepted |
| 4 | 0/0 | 0/0 | 1 | 1 | **1** | 0/1 | 0/1 | 0/1 | unmapped write, nothing changes |
| 5 | | | 0 | 0 | 0 | 1/1 | | | BRESP = SLVERR |

## 8. Clocking & Reset

- Single clock `aclk`. The `sts_*` and `evt_set` inputs must be synchronous to `aclk`; CDC for core signals from other domains is the integrator's job (§11).
- `aresetn` is active-low and treated as synchronous (assert and de-assert sampled on `aclk`), which the AXI specification permits. During reset all `VALID` outputs are low, as AXI requires; `READY` outputs are also held low during reset: because `aw_full_q` and the other holding flags reset to 0, the READYs would otherwise be high, so each READY is ANDed with `rst_done_q`.
- `cmd_soft_rst` is only an output pulse; it does not reset this block.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| W before AW (or AW before W) | Held independently; the write executes once both are present. |
| Second AW while the first is still held | `s_awready = 0` until `do_write`; no reordering. |
| Write to RO register (STATUS, VERSION) | Ignored, OKAY. |
| Read of CMD (WO) | Returns 0, OKAY. |
| Unmapped read/write | SLVERR; read data 0; write has no effect. |
| `WSTRB = 0` | Valid AXI transaction; nothing is modified, OKAY response; CMD pulses are not generated. |
| W1C clear and hardware set of the same bit in one cycle | Bit stays set (set wins). |
| Read and write of the same register in the same cycle | Read returns the pre-write value. |
| Unaligned address | `addr[1:0]` ignored (AXI-Lite masters are expected to be aligned). |
| Master holds `BREADY`/`RREADY` low | Response held stable; further writes/reads stall via `aw_full`/`rvalid`. |

## 10. Verification Plan

**Environment:** an AXI4-Lite master BFM (or a VIP) with randomizable AW/W skew and B/R
back-pressure, a register-model scoreboard (UVM RAL or a hand-written model), and an AXI
protocol checker.

**Directed tests**
1. Reset values of every register, including the PRESCALE reset of `0x01`.
2. RW registers: write and read back with all 16 `WSTRB` patterns.
3. Reserved bits read 0 after writing all ones.
4. W1C: set events, clear some via write, verify the rest; simultaneous set and clear of the same bit.
5. `irq` follows `INT_STATUS & INT_EN`, including masking and unmasking a pending interrupt.
6. CMD: each bit gives exactly one `cmd_*` pulse; `WSTRB` lane gating; reads 0.
7. Unmapped addresses (0x01C, 0x100, 0xFFC) give SLVERR on read and write.
8. AW/W skew: W 0–5 cycles before AW, AW 0–5 cycles before W, both simultaneous.
9. B and R back-pressure up to 10 cycles.

**Random:** 10k random transactions (mixed reads and writes, random addresses including
unmapped, random strobes, random skew and back-pressure); the RAL mirror is checked on every read.

**Assertions**

```systemverilog
a_bstable: assert property (@(posedge aclk) disable iff(!aresetn)
             s_bvalid && !s_bready |=> s_bvalid && $stable(s_bresp));
a_rstable: assert property (@(posedge aclk) disable iff(!aresetn)
             s_rvalid && !s_rready |=> s_rvalid && $stable({s_rdata, s_rresp}));
a_b_after: assert property (@(posedge aclk) disable iff(!aresetn)
             $rose(s_bvalid) |-> $past(aw_full_q && w_full_q));
a_cmd_pulse: assert property (@(posedge aclk) disable iff(!aresetn) cmd_start |=> !cmd_start);
a_evt_kept: assert property (@(posedge aclk) disable iff(!aresetn)
             evt_set[0] |=> int_sts_q[0]);
```

**Coverage:** every register × {read, write}; every access type; all WSTRB values for RW
registers; AW-first, W-first and simultaneous; set/clear collision; SLVERR on both channels.

## 11. Assumptions & Open Questions

1. **Writes to RO registers** respond OKAY (silently ignored) rather than SLVERR. SLVERR is reserved for unmapped addresses, as the spec states.
2. **Throughput of 1 transaction per 2 cycles** per direction: chosen for registered, combinational-free handshakes. A full-rate version would make `AWREADY` depend on `BREADY`.
3. **CTRL is masked to defined bits**, so writes to reserved bits [7:4] and [31:16] are discarded.
4. **SOFT_RST** is a 1-cycle pulse to the core; whether it should also clear CTRL/INT registers is an open question for the core owner.
5. **Status inputs** are assumed synchronous; if the core runs on another clock, add 2-flop synchronizers for single bits and a handshake or Gray-code crossing for `FIFO_LEVEL`.
6. **AxPROT is ignored**: no secure/privileged access filtering.
7. **READY during reset** is forced low for strict compliance with integrators that check it; this costs one flop.
