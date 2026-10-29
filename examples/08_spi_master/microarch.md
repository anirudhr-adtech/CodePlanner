# Micro-architecture: `spi_master`

## 1. Overview

`spi_master` is a memory-mapped, full-duplex SPI master. A write to TXDATA starts one
transfer of 8, 16 or 32 bits on the selected chip select, in any of the four CPOL/CPHA
modes, with configurable bit order. SCLK is generated from the system clock by a
half-period counter. All pin outputs (`sclk`, `mosi`, `cs_n`) come straight from flops.

Key features:
- One half-period engine: every SPI edge is an "event" generated when the divider counter expires; mode decoding decides whether an event drives MOSI or samples MISO.
- One shift register for TX and one for RX, with alignment muxes for size and bit order.
- Guaranteed half-SCLK CS lead, lag and minimum CS-high time.
- CS_HOLD for multi-word transactions; DONE interrupt with W1C status.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | System clock (100 MHz target). |
| `rst_n` | in | 1 | Active-low reset; async assert, sync de-assert. |
| **Register bus** | | | |
| `addr` | in | 5 | Byte address; bits [1:0] ignored. |
| `wdata` | in | 32 | Write data. |
| `we` | in | 1 | Write strobe (single cycle). |
| `re` | in | 1 | Read strobe (single cycle). |
| `rdata` | out | 32 | Read data, valid the cycle after `re` (registered). |
| **Interrupt** | | | |
| `irq` | out | 1 | Level interrupt: `IRQ_EN & DONE`. |
| **SPI pins** | | | |
| `sclk` | out | 1 | Serial clock (registered). |
| `mosi` | out | 1 | Master out, slave in (registered). |
| `miso` | in | 1 | Master in, slave out. |
| `cs_n` | out | `NUM_CS` | Active-low chip selects (registered, at most one low). |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `NUM_CS` | 4 | 1–4 | Number of chip-select outputs (`CS_SEL` values ≥ `NUM_CS` select none). |
| `DIV_W` | 16 | 1–16 | Divider width (CLKDIV[DIV_W-1:0] implemented). |

Derived: `half_period = DIV + 1` system clocks; `f_sclk = f_clk / (2 * (DIV + 1))`.
At 100 MHz, DIV = 1 gives 25 MHz and DIV = 0 gives 50 MHz.

## 4. Block Diagram

```
         addr/wdata/we/re
               |
        +--------------+   ctrl/div/cs_sel      +---------------------------+
        |  reg_if      |----------------------->|        spi_engine         |
        |  CTRL CLKDIV |   start, tx_word       |  +---------+  event,lead  |
        |  STATUS RX   |----------------------->|  | div_cnt |---------+    |
        |  rdata reg   |<-----------------------|  +---------+         v    |
        +--------------+  done, busy, rx_word   |  +---------+   +---------+|---> sclk
              |                                 |  |  FSM    |-->| edge    ||
             irq                                |  | IDLE/   |   | decode  ||---> mosi
                                                |  | XFER/   |   +---------+|
                                                |  | LAG/GAP |     |   |    |<--- miso
                                                |  +---------+  drive sample|
                                                |    tx_sh[32]  rx_sh[32]   |---> cs_n[NUM_CS]
                                                +---------------------------+
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_regs` | `spi_regs` | Register decode, CTRL/CLKDIV storage, STATUS W1C logic, read mux, `irq`. |
| `u_eng` | `spi_engine` | Divider, FSM, edge counter, shift registers, pin flops. |

## 5. Datapath

**Register block**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `ctrl_q` | 17 (bits 0–5, 8–10, 16 used) | 0 | CTRL fields. |
| `div_q` | `DIV_W` | 0 | CLKDIV. |
| `rx_q` | 32 | 0 | RXDATA, written by the engine on completion. |
| `done_q` | 1 | 0 | STATUS.DONE (sticky, W1C). |
| `txovr_q` | 1 | 0 | STATUS.TX_OVR (sticky, W1C). |
| `rdata_q` | 32 | 0 | Registered read data. |

`start = we && addr[4:2]==3'd2 && EN && !busy`; `txovr_set = we && addr[4:2]==3'd2 && busy`.

**Engine**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `state` | 2 | IDLE | FSM state. |
| `div_cnt` | `DIV_W` | 0 | Half-period counter; `event = (div_cnt == div_lat)`. |
| `edge_cnt` | 6 | 0 | SPI edge index 0..2N−1 (N ≤ 32 → 64 edges). |
| `tx_sh` | 32 | 0 | Transmit shift register. |
| `rx_sh` | 32 | 0 | Receive shift register. |
| `cfg_lat` | 7 | 0 | {CPOL, CPHA, LSB_FIRST, SIZE, CS_SEL} latched at `start`; `div_lat` too. |
| `sclk_q` | 1 | 0 (driven to CPOL in IDLE) | SCLK pin flop. |
| `mosi_q` | 1 | 0 | MOSI pin flop. |
| `cs_n_q` | `NUM_CS` | all 1 | CS pin flops. |
| `cs_held` | 1 | 0 | CS still asserted from a previous CS_HOLD transfer. |

**Size and bit-order alignment** (N = 8/16/32 from `SIZE`; `last_edge = 2N − 1`):

```verilog
// load (MSB-first left-aligns so the head is always tx_sh[31]; LSB-first keeps head at tx_sh[0])
tx_load = lsb ? tx_word
              : (size==2'd0) ? {tx_word[7:0], 24'b0}
              : (size==2'd1) ? {tx_word[15:0], 16'b0} : tx_word;
tx_head = lsb ? tx_sh[0] : tx_sh[31];
tx_next = lsb ? {1'b0, tx_sh[31:1]} : {tx_sh[30:0], 1'b0};

// sample: MSB-first fills from the bottom (ends right-aligned); LSB-first fills from the top
rx_next = lsb ? {miso, rx_sh[31:1]} : {rx_sh[30:0], miso};
rx_word = !lsb ? rx_sh
              : (size==2'd0) ? {24'b0, rx_sh[31:24]}
              : (size==2'd1) ? {16'b0, rx_sh[31:16]} : rx_sh;
```

For MSB-first transfers smaller than 32 bits, `rx_word` keeps stale upper bits from earlier
transfers unless `rx_sh` is cleared at `start`. It is cleared (`rx_sh <= 0` on load), so the
upper bits read 0.

**Edge decode** (per event in XFER; `lead = !edge_cnt[0]`):

| Mode | CPHA | Drive MOSI (`mosi_q<=tx_head; tx_sh<=tx_next`) | Sample MISO (`rx_sh<=rx_next`) |
|------|------|-----------------------------------------------|--------------------------------|
| 0, 2 | 0 | at `start` (first bit) and on trailing edges except the last | leading edges |
| 1, 3 | 1 | leading edges | trailing edges |

`sclk_q <= ~sclk_q` on every XFER event; in IDLE `sclk_q <= CPOL` (from `ctrl_q`, so idle
polarity follows the register immediately).

## 6. Control Logic

**FSM**

| State | Enc | Outputs | Transition |
|-------|-----|---------|------------|
| IDLE | 2'd0 | `busy=0`; `sclk_q=CPOL`; `cs_n` = held CS or all 1 | `start` → XFER: latch cfg/div, `tx_sh<=tx_load`, `rx_sh<=0`, `div_cnt<=0`, `edge_cnt<=0`, drive `cs_n_q[CS_SEL]=0`. If CPHA=0, also do a drive (`mosi_q<=tx_head(tx_load)`, shift). |
| XFER | 2'd1 | `busy=1` | On each `event`: toggle SCLK, perform drive/sample per table, `edge_cnt++`. When `event && edge_cnt==last_edge` → LAG, `rx_q<=rx_word` (one cycle later via `rx_wr` strobe). |
| LAG | 2'd2 | `busy=1`, CS still low | `event` → if `CS_HOLD` (live register value): IDLE, `cs_held<=1`, `done_set`; else `cs_n_q<=all 1`, → GAP. |
| GAP | 2'd3 | `busy=1`, CS high | `event` → IDLE, `done_set`. |

`div_cnt` behaviour: in XFER/LAG/GAP, `div_cnt <= event ? 0 : div_cnt + 1`; held at 0 in IDLE.

**Held chip select.** If a transfer starts while `cs_held=1` and `CS_SEL` names a different
CS than the held one, the held CS is released and the new one asserted in the same cycle.
The required CS-high gap does not apply between different devices. If `CS_HOLD` is cleared
while IDLE with `cs_held=1`, the engine de-asserts all CS on the next cycle (`cs_held<=0`).

**Status / interrupt**

```verilog
done_q   <= done_set | (done_q & ~(w1c_status & wdata[1]));
txovr_q  <= txovr_set | (txovr_q & ~(w1c_status & wdata[2]));   // set wins over clear
irq       = ctrl_q[16] & done_q;
busy      = (state != IDLE);
```

## 7. Timing & Pipeline

- **Transfer duration** (clocks, from the TXDATA write cycle to `DONE`): `1 + (2N + 2) × (DIV + 1)` with CS de-assertion, or `1 + (2N + 1) × (DIV + 1)` with CS_HOLD.
- **CS lead / lag / gap:** exactly one half-period each (meets the spec minimum).
- **Max SCLK:** 50 MHz at DIV = 0 (100 MHz clk). MISO is sampled on the system-clock edge that launches the sampling SCLK edge. The round trip (`sclk` out + slave tCO + `miso` in + setup) must fit in one half-period: 10 ns at DIV = 0, 20 ns at DIV = 1. 25 MHz is the guaranteed spec point.
- **Throughput:** with back-to-back writes polling BUSY, 8-bit at DIV = 1: 1 + 18 × 2 = 37 clocks per byte, i.e. about 21.6 Mbit/s.

Mode 0, 8-bit MSB-first, `TXDATA = 0xA5` (1010_0101), DIV = 0. Values are those seen during each cycle:

| Cycle | State | edge_cnt | Event | `cs_n` | `sclk` | `mosi` | Action at end of cycle |
|-------|-------|----------|-------|--------|--------|--------|------------------------|
| 0 | IDLE | – | – | 1 | 0 | x | TXDATA write → start, drive b7 |
| 1 | XFER | 0 | lead ↑ | 0 | 0 | 1 (b7) | sample MISO b7 |
| 2 | XFER | 1 | trail ↓ | 0 | 1 | 1 | drive b6 |
| 3 | XFER | 2 | lead ↑ | 0 | 0 | 0 (b6) | sample b6 |
| 4 | XFER | 3 | trail ↓ | 0 | 1 | 0 | drive b5 |
| … | … | … | … | 0 | … | … | … |
| 15 | XFER | 14 | lead ↑ | 0 | 0 | 1 (b0) | sample b0 |
| 16 | XFER | 15 | trail ↓ | 0 | 1 | 1 | last edge, no drive; → LAG, capture RX |
| 17 | LAG | – | event | 0 | 0 | 1 | release CS → GAP |
| 18 | GAP | – | event | 1 | 0 | 1 | → IDLE, DONE=1 |
| 19 | IDLE | – | – | 1 | 0 | 1 | `irq` high if IRQ_EN |

## 8. Clocking & Reset

- **One clock domain.** SCLK is a data output toggled by a flop, never a clock inside the block, so there are no generated-clock constraints internally. Constrain `sclk`/`mosi`/`cs_n` as outputs and `miso` as an input relative to a virtual clock derived from `clk / (2 × (DIV + 1))`, or use a multicycle path for low speeds.
- **MISO is not double-synchronized.** It is source-synchronous to our own SCLK, so a 2-flop synchronizer would only add latency and break sampling at high speed. Use an IOB input flop.
- **Reset:** all registers clear; `cs_n_q` resets to all ones (no device selected). `sclk_q` resets to 0 and follows CPOL from the first IDLE cycle; with CPOL = 1, firmware should set CTRL before selecting a device.
- **Configuration:** CPOL/CPHA/SIZE/LSB/CS_SEL/DIV are latched at `start`, so writes to CTRL/CLKDIV during a transfer only affect the next transfer. Exceptions: CS_HOLD is read live at the end of LAG, and CPOL drives idle SCLK directly.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| TXDATA write while BUSY | Ignored; TX_OVR set. |
| TXDATA write while EN=0 | Ignored, no flag (block disabled). |
| SIZE = 2'b11 (reserved) | Treated as 32-bit. |
| CS_SEL ≥ NUM_CS | Transfer runs with no CS asserted (useful for dummy clocks); documented, not an error. |
| CPOL changed while `cs_held` | SCLK moves to the new idle level while CS is low, which the slave sees as a clock edge. Firmware must not do this; flagged by an assertion. |
| EN cleared during a transfer | Current transfer completes (EN only gates `start`). |
| W1C clear of DONE in the same cycle as `done_set` | Set wins, so no completion event is lost. |
| RXDATA read during transfer | Returns the previous word (`rx_q` is updated only at completion). |

## 10. Verification Plan

**Testbench:** register-level driver plus an SPI slave BFM for each mode. The BFM checks
CS-to-SCLK lead/lag/gap, samples MOSI on the correct edge, and returns a scripted MISO
pattern with configurable tCO. A scoreboard checks RXDATA and the MOSI bit stream.

**Directed tests**
1. Reset: all `cs_n` high, `sclk` 0, BUSY 0.
2. For each mode (0–3) × SIZE (8/16/32) × order (MSB/LSB): 0xA5A5_5A5A pattern, walking-1, all-0, all-1.
3. DIV sweep {0, 1, 2, 7, 0xFFFF}: measure SCLK period = 2 × (DIV + 1) clocks.
4. CS lead/lag/gap = DIV + 1 clocks each.
5. CS_HOLD: 3 transfers in one CS window, then clear CS_HOLD → CS releases.
6. CS switch while held → old CS high and new CS low in the same cycle.
7. TX_OVR: write during transfer, check flag and that the transfer is unaffected.
8. DONE/irq: W1C clearing, simultaneous set/clear.

**Random tests:** random config per transfer, random DIV in 0..15, random MISO data and
slave tCO up to 0.8 × half-period; 5k transfers.

**Assertions (SVA)**

```systemverilog
a_cs_onehot0:  assert property (@(posedge clk) disable iff(!rst_n) $onehot0(~cs_n));
a_sclk_idle:   assert property (@(posedge clk) disable iff(!rst_n) state==IDLE && !cs_held |-> sclk==ctrl_q[1]);
a_sclk_cs:     assert property (@(posedge clk) disable iff(!rst_n) $changed(sclk) |-> $past(state)==XFER || $past(state)==IDLE);
a_edges:       // number of sclk toggles between cs_n fall and rise == 2N (checked in monitor)
a_no_cpol_chg: assert property (@(posedge clk) disable iff(!rst_n) cs_held |-> $stable(ctrl_q[1]));
a_busy_start:  assert property (@(posedge clk) disable iff(!rst_n) start |=> busy);
```

**Coverage:** mode × size × order cross (24 bins); DIV ∈ {0, 1, small, large}; CS_HOLD
chains of length 1, 2, ≥ 3; every CS_SEL value including out-of-range; TX_OVR; DONE
set/clear collision.

## 11. Assumptions & Open Questions

1. **CPHA definition:** CPHA = 0 drives the first bit before the first edge and samples on leading edges; CPHA = 1 drives on leading edges and samples on trailing edges (standard Motorola convention).
2. **MISO sample point** is the exact SCLK edge (zero delay). For higher speeds or long traces, a future `SAMPLE_DLY` field could sample 1–2 system clocks later; not required for 25 MHz.
3. **No TX/RX FIFO.** The spec defines single TXDATA/RXDATA registers. DMA or FIFOs can be added at the register layer.
4. **CS_HOLD is evaluated at the end of LAG**, so firmware can clear it during the last transfer of a burst and get automatic release.
5. **MOSI holds the last bit** between transfers (no forced idle level). The spec does not define an idle level.
6. **Reserved SIZE = 11 behaves as 32-bit** rather than raising an error.
7. **Reads have no side effects** (RXDATA read does not clear DONE); confirm with the driver team.
