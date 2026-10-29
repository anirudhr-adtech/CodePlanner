# Micro-architecture: `uart_xcvr`

## 1. Overview

`uart_xcvr` is a full-duplex UART with independent transmit and receive paths. They share a
programmable 16x baud-tick generator. Both host sides use a valid/ready stream and are
buffered by small synchronous FIFOs.

Key features:
- Runtime-programmable baud rate: `baud_div` sets the clock cycles per 16x oversampling tick. The design works with any system clock.
- Frame: 1 start bit, 8 data bits LSB first, optional even/odd parity, 1 stop bit (8N1 / 8E1 / 8O1).
- RX: 2-flop input synchronizer, 16x oversampling, 3-sample majority vote at mid-bit, start-bit verification to reject idle-line glitches.
- Per-byte `frame_err` and `parity_err` stored in the RX FIFO next to the data, so firmware knows exactly which byte is bad.
- Sticky `rx_overrun` when a byte arrives while the RX FIFO is full.
- Back-to-back TX frames with no idle gap when the TX FIFO has data.
- Break / stuck-low line handling: the receiver does not re-arm until the line returns high.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | System clock (e.g. 50 or 100 MHz). |
| `rst_n` | in | 1 | Active-low reset; async assert, sync de-assert (synchronized at top). |
| **Configuration** | | | |
| `baud_div` | in | 16 | Clock cycles per 16x tick. `baud_div = round(f_clk / (16 * baud))`. 0 is treated as 1. |
| `parity_en` | in | 1 | 1 = a parity bit is sent/expected after the data bits. |
| `parity_odd` | in | 1 | 0 = even parity, 1 = odd parity (ignored when `parity_en=0`). |
| **TX stream (host → UART)** | | | |
| `tx_data` | in | 8 | Byte to transmit. |
| `tx_valid` | in | 1 | `tx_data` is valid. |
| `tx_ready` | out | 1 | TX FIFO can accept a byte (`!txf_full`). Transfer occurs when `tx_valid && tx_ready`. |
| **RX stream (UART → host)** | | | |
| `rx_data` | out | 8 | Received byte at the RX FIFO head. |
| `rx_frame_err` | out | 1 | Stop bit of `rx_data` was sampled as 0. |
| `rx_parity_err` | out | 1 | Parity of `rx_data` did not match (always 0 when parity was disabled for that frame). |
| `rx_valid` | out | 1 | RX FIFO not empty; `rx_data`/error flags valid (FWFT). |
| `rx_ready` | in | 1 | Host consumes the head entry when `rx_valid && rx_ready`. |
| **Status** | | | |
| `tx_level` | out | `LVL_W` | Number of bytes in the TX FIFO. |
| `rx_level` | out | `LVL_W` | Number of bytes in the RX FIFO. |
| `tx_busy` | out | 1 | TX FSM is not IDLE or the TX FIFO is not empty. |
| `rx_busy` | out | 1 | RX FSM is not IDLE (a frame is being received). |
| `rx_overrun` | out | 1 | Sticky: a received byte was dropped because the RX FIFO was full. |
| `status_clr` | in | 1 | Single-cycle pulse; clears `rx_overrun`. |
| **Serial pins** | | | |
| `rxd` | in | 1 | Serial input, asynchronous to `clk`; idles high. |
| `txd` | out | 1 | Serial output, registered; idles high. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `FIFO_DEPTH` | 8 | 2–256, power of 2 | Depth of both TX and RX FIFOs. |
| `LVL_W` | `$clog2(FIFO_DEPTH)+1` | derived | Width of the level outputs. |
| `OSR` | 16 | fixed | Oversampling ratio (localparam; the sample-point constants assume 16). |

Example `baud_div` values:

| f_clk | Baud | `baud_div` | Actual baud | Error |
|-------|------|-----------|-------------|-------|
| 50 MHz | 115200 | 27 | 115741 | +0.47 % |
| 50 MHz | 9600 | 326 | 9586 | −0.15 % |
| 100 MHz | 115200 | 54 | 115741 | +0.47 % |
| 100 MHz | 9600 | 651 | 9601 | +0.01 % |

With a 16-bit divider, the lowest baud rate at 100 MHz is about 95 baud.

## 4. Block Diagram

```
                     baud_div
                        |
                  +-----------+  tick (1 clk pulse every baud_div clks)
                  | baud_gen  |----------------+--------------------+
                  +-----------+                |                    |
                                               v                    v
 tx_data/valid  +-----------+  pop/head  +-----------+       +-----------+   push   +-----------+  rx_data/err
 ------------->| u_txf     |----------->|  tx_fsm   |--txd   |  rx_fsm   |--------->| u_rxf     |------------->
 <-- tx_ready  | sync_fifo |            | shift_tx  |        | shift_rx  |  {pe,fe, | sync_fifo |  rx_valid -->
               | 8 x DEPTH |            | parity    |  rxd   | majority  |   data}  | 10 x DEPTH|  <-- rx_ready
               +-----------+            +-----------+   |    +-----------+          +-----------+
                                                        |          ^                      |
                                                        v          | rx_s                 | full
                                                  +-----------+    |                      v
                                                  | rx_sync   |----+               rx_overrun (sticky)
                                                  | 2-flop    |
                                                  +-----------+
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_baud` | `uart_baud_gen` | 16-bit down-counter producing the shared 16x `tick`. |
| `u_txf` | `sync_fifo #(.DATA_W(8), .DEPTH(FIFO_DEPTH))` | TX byte buffer (FWFT). |
| `u_tx` | `uart_tx` | TX FSM, shift register, parity generator, `txd` register. |
| `u_rxsync` | `sync_2ff` | 2-flop synchronizer for `rxd`, reset value 1. |
| `u_rx` | `uart_rx` | RX FSM, sample counter, majority voter, shift register, error checks. |
| `u_rxf` | `sync_fifo #(.DATA_W(10), .DEPTH(FIFO_DEPTH))` | RX buffer holding `{parity_err, frame_err, data[7:0]}`. |

## 5. Datapath

**Baud generator**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `div_cnt` | 16 | 0 | Counts clock cycles inside one tick period. |

```verilog
wire [15:0] div_eff = (baud_div == 16'd0) ? 16'd1 : baud_div;
wire        tick    = (div_cnt >= div_eff - 16'd1);    // >= tolerates a runtime decrease of baud_div
always @(posedge clk) div_cnt <= tick ? 16'd0 : div_cnt + 16'd1;
```

**Transmitter**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `tx_state` | 3 | IDLE | TX FSM state. |
| `tx_scnt` | 4 | 0 | Tick counter within the current bit (0..15). |
| `tx_bidx` | 3 | 0 | Data-bit index (0..7). |
| `tx_shift` | 8 | 0 | Shift register; LSB is driven during DATA, shifted right each bit. |
| `tx_par` | 1 | 0 | Parity bit computed at load: `^tx_head ^ parity_odd`. |
| `tx_pen_q` | 1 | 0 | `parity_en` latched at frame start. |
| `txd_q` | 1 | 1 | Registered serial output (glitch-free pin). |

`txd_q` next value: START → 0, DATA → `tx_shift[0]`, PARITY → `tx_par`, STOP/IDLE → 1.

**Receiver**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `rx_meta`, `rx_s` | 1 each | 1 | 2-flop synchronizer; reset to idle level to avoid a false start bit. |
| `rx_state` | 3 | IDLE | RX FSM state. |
| `rx_scnt` | 4 | 0 | Tick counter within the current bit. |
| `rx_bidx` | 3 | 0 | Data-bit index. |
| `smp` | 2 | 2'b11 | Samples taken at `rx_scnt` = 6 and 7. |
| `rx_shift` | 8 | 0 | Data shift register; new bit enters at MSB, so after 8 bits LSB-first data is aligned. |
| `rx_pen_q`, `rx_podd_q` | 1 each | 0 | Parity config latched at start-bit detection. |
| `rx_perr` | 1 | 0 | Parity error for the current frame. |
| `ovr_q` | 1 | 0 | Sticky overrun. |

**Majority vote** (evaluated on the tick where `rx_scnt == 8`):

```verilog
wire bit_val = (smp[1] & smp[0]) | (smp[1] & rx_s) | (smp[0] & rx_s);  // samples at 6, 7, 8
```

**Parity check:** expected `p = ^rx_shift ^ rx_podd_q`; `rx_perr <= (bit_val != p)`.

**RX FIFO write data:** `{rx_perr & rx_pen_q, ~bit_val /*frame_err*/, rx_shift}`, pushed on the
STOP-state decision tick.

## 6. Control Logic

**Tick-counting convention (both FSMs):** on each `tick` in a non-IDLE state, the action is
based on the current `scnt` value. Then `scnt <= (scnt == 15) ? 0 : scnt + 1`, and the bit
ends on the tick where `scnt == 15`. Every bit therefore lasts exactly 16 ticks
(`16 * baud_div` clocks). Every state transition, including the early exits from START (glitch) and
STOP (mid-bit), also forces `scnt <= 0`, so `scnt` is always 0 in IDLE and BREAK.

**TX FSM**

| State | Enc | `txd_q` | Transition (all on `tick`) |
|-------|-----|---------|----------------------------|
| IDLE | 3'd0 | 1 | `!txf_empty` → START: load `tx_shift <= txf_head`, `tx_par`, `tx_pen_q`; pop TX FIFO. |
| START | 3'd1 | 0 | `scnt==15` → DATA, `tx_bidx<=0`. |
| DATA | 3'd2 | `tx_shift[0]` | `scnt==15`: shift right; if `tx_bidx==7` → (`tx_pen_q` ? PARITY : STOP), else `tx_bidx++`. |
| PARITY | 3'd3 | `tx_par` | `scnt==15` → STOP. |
| STOP | 3'd4 | 1 | `scnt==15`: if `!txf_empty` → START (load + pop, no idle gap), else → IDLE. |

The TX FIFO pop (`txf_pop`) is a one-clock pulse, asserted on the loading tick.

**RX FSM**

| State | Enc | Action / transition (all on `tick`) |
|-------|-----|-------------------------------------|
| IDLE | 3'd0 | `rx_s==0` → START, `scnt<=0`, latch `rx_pen_q/rx_podd_q`. |
| START | 3'd1 | `scnt==6,7`: capture `smp`. `scnt==8`: if `bit_val==1` → IDLE (glitch rejected). `scnt==15` → DATA, `rx_bidx<=0`. |
| DATA | 3'd2 | `scnt==8`: `rx_shift <= {bit_val, rx_shift[7:1]}`. `scnt==15`: if `rx_bidx==7` → (`rx_pen_q` ? PARITY : STOP), else `rx_bidx++`. |
| PARITY | 3'd3 | `scnt==8`: `rx_perr <= (bit_val != (^rx_shift ^ rx_podd_q))`. `scnt==15` → STOP. |
| STOP | 3'd4 | `scnt==8`: push `{perr, ~bit_val, rx_shift}` to RX FIFO (or set overrun). Then if `bit_val==1` → IDLE, else → BREAK. |
| BREAK | 3'd5 | Wait for `rx_s==1` (checked every tick) → IDLE. |

The FSM leaves STOP at mid-bit on purpose. That re-arms start detection about 7 ticks early,
which absorbs baud-rate mismatch on back-to-back frames.

**Control equations**

```verilog
rxf_push   = tick && rx_state==STOP && rx_scnt==4'd8 && !rxf_full;
ovr_set    = tick && rx_state==STOP && rx_scnt==4'd8 &&  rxf_full;
ovr_q     <= status_clr ? 1'b0 : (ovr_q | ovr_set);
tx_ready   = !txf_full;     txf_push = tx_valid && tx_ready;
rx_valid   = !rxf_empty;    rxf_pop  = rx_valid && rx_ready;
tx_busy    = (tx_state != IDLE) || !txf_empty;
rx_busy    = (rx_state != IDLE);
```

## 7. Timing & Pipeline

- **Bit time:** `16 * baud_div` clocks. 8N1 frame = 10 bits = `160 * baud_div` clocks (4320 clocks = 86.4 µs at 50 MHz / 115200).
- **TX latency:** from `tx_valid && tx_ready` with an empty TX FIFO and IDLE FSM, `txd` falls 2 to `baud_div+1` clocks later: 1 clock for FIFO `empty` to fall, up to one tick period to align to the next tick, 1 clock for the `txd_q` register.
- **TX throughput:** 100 % line utilisation while the TX FIFO is non-empty (STOP → START directly).
- **RX latency:** with T0 = the tick on which the start bit is detected, the byte is pushed at T0 + 153 ticks (8N1) or T0 + 169 ticks (with parity), i.e. bit 9 (or 10) at `scnt==8`. `rx_valid` rises one clock later.
- **Detection delay:** the synchronizer adds 2 clocks, and start detection waits for the next tick (≤ 1 tick). The sample centre is therefore 0 to +1 tick late relative to the true bit centre.
- **Clock tolerance:** the last sample (stop bit) is at about 9.5 bit times. The allowed combined TX/RX baud mismatch is about ±(0.5 − 1/16)/9.5 ≈ ±4.6 %.

TX frame for byte `0xA5`, even parity (`^0xA5 = 0`), tick-level view:

| Ticks after load | State | `txd` | Bit |
|------------------|-------|-------|-----|
| 0–15 | START | 0 | start |
| 16–31 | DATA (bidx 0) | 1 | b0 |
| 32–47 | DATA (bidx 1) | 0 | b1 |
| 48–63 | DATA (bidx 2) | 1 | b2 |
| 64–79 | DATA (bidx 3) | 0 | b3 |
| 80–95 | DATA (bidx 4) | 0 | b4 |
| 96–111 | DATA (bidx 5) | 1 | b5 |
| 112–127 | DATA (bidx 6) | 0 | b6 |
| 128–143 | DATA (bidx 7) | 1 | b7 |
| 144–159 | PARITY | 0 | p (even) |
| 160–175 | STOP | 1 | stop |

RX start-bit handling (clock level, `baud_div = 2`, so ticks occur on even clocks; `rxd`
falls just before clock 0):

| Clock | tick # after T0 | `rx_s` | `rx_scnt` (before) | Action |
|-------|-----------------|--------|--------------------|--------|
| 0 | – | 1 | – | `rx_meta` captures 0 |
| 1 | – | 0 | – | `rx_s` = 0 (synchronized) |
| 2 | T0 | 0 | – | IDLE sees `rx_s==0` on tick → START, `scnt<=0` |
| 4 … 14 | 1 … 6 | 0 | 0 … 5 | count |
| 16 | 7 | 0 | 6 | `smp[1] <= rx_s` |
| 18 | 8 | 0 | 7 | `smp[0] <= rx_s` |
| 20 | 9 | 0 | 8 | majority(`smp[1]`,`smp[0]`,`rx_s`) = 0 → valid start |
| 34 | 16 | 0/1 | 15 | enter DATA, `rx_bidx<=0` |
| 52 | 25 | b0 | 8 | b0 decided, shifted into `rx_shift[7]` |

The centre of the start bit is 16 clocks (8 ticks) after the pin edge, at about clock 15.
The decision samples straddle clocks 16–20, i.e. at most 1 tick late, as stated above.

## 8. Clocking & Reset

- **One clock domain** (`clk`). `rxd` is the only asynchronous input, synchronized by `u_rxsync` (2 flops, `ASYNC_REG`/`dont_touch` attributes, placed close together). Both flops reset to 1.
- **Reset:** `rst_n` active-low, async assert / sync de-assert. Reset sets both FSMs to IDLE, `txd_q=1`, `div_cnt=0`, empties both FIFOs and clears `ovr_q`.
- **No derived clocks.** `tick` is a clock-enable, never used as a clock.
- **Configuration changes:** `parity_en`/`parity_odd` are latched per frame, so changing them mid-frame does not corrupt the current frame. `baud_div` is not latched, because it is shared by TX and RX. Firmware must change it only while `!tx_busy && !rx_busy`.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| Glitch on idle line shorter than ~6 ticks | Start detected, but the majority at mid start bit reads 1 → FSM returns to IDLE, nothing pushed. |
| Glitch inside a data bit | Masked if it covers at most 1 of the 3 samples. |
| Stop bit sampled 0 | Byte pushed with `frame_err=1`; RX goes to BREAK until the line is high. |
| Break condition (line held low ≥ 1 frame) | One entry `{data=0x00, frame_err=1}` pushed, then RX waits in BREAK; no stream of fake bytes. |
| Parity mismatch | Byte pushed with `parity_err=1`; data delivered unchanged. |
| RX FIFO full at push time | Byte dropped, `rx_overrun` set (sticky until `status_clr`); FIFO contents preserved. |
| `tx_valid` when TX FIFO full | `tx_ready=0`; host must hold the data (stream semantics). No data lost. |
| `baud_div` = 0 | Treated as 1 (tick every clock). |
| `baud_div` decreased mid-count | `>=` comparison ends the current tick period immediately; no 65536-cycle wrap. |
| `status_clr` and a new overrun in the same cycle | Clear wins (consistent with the `sync_fifo` error-flag policy). |

## 10. Verification Plan

**Testbench:** UVM-lite SystemVerilog testbench with a UART bus-functional model (BFM). The
BFM drives `rxd` with configurable baud error, parity and glitch injection, and decodes
`txd` independently. A scoreboard compares bytes and error flags in both directions. A
loopback mode connects `txd` → `rxd`.

**Directed tests**
1. Reset: `txd=1`, `tx_ready=1`, `rx_valid=0`, `rx_overrun=0`.
2. Single byte TX at 115200 / 50 MHz: check bit times = 432 clocks ± 0.
3. Single byte RX, 8N1 / 8E1 / 8O1, patterns 0x00, 0xFF, 0x55, 0xAA, 0xA5.
4. Back-to-back TX of 8 bytes: no gap between stop bit and next start bit.
5. Parity error injection → `rx_parity_err=1` on exactly that byte.
6. Framing error and break (line low for 3 frame times) → exactly one error entry, recovery after line high.
7. Overrun: send FIFO_DEPTH+2 bytes without reading → first DEPTH bytes intact, `rx_overrun=1`.
8. Idle-line glitch of 1, 3, 5, 7 ticks → no byte received for ≤ 5 ticks.
9. Runtime parity switch between frames.

**Random tests:** random bytes, parity config, inter-frame gaps, `rx_ready` back-pressure and
BFM baud offset uniformly in ±3 %, for 10k frames in loopback and in independent mode.

**Assertions (SVA)**

```systemverilog
a_txd_idle:     assert property (@(posedge clk) disable iff(!rst_n) tx_state==IDLE |-> txd);
a_tx_start_low: assert property (@(posedge clk) disable iff(!rst_n) tx_state==START |-> !txd);
a_bit_len:      // txd stable for 16*div_eff clocks within each bit (checked by BFM monitor)
a_push_onehot:  assert property (@(posedge clk) disable iff(!rst_n) !(rxf_push && ovr_set));
a_ovr_sticky:   assert property (@(posedge clk) disable iff(!rst_n) rx_overrun && !status_clr |=> rx_overrun);
a_scnt_range:   assert property (@(posedge clk) disable iff(!rst_n) rx_state==IDLE |-> rx_scnt==0);
```

**Coverage:** all TX/RX states and transitions; parity modes × error types; overrun; glitch
lengths 1–8 ticks; baud offsets −4 %..+4 % in 1 % bins; `baud_div` values {1, 2, 27, 326, 651, 65535};
back-to-back RX frames with zero gap.

## 11. Assumptions & Open Questions

1. **Shared 16x tick.** One baud generator serves TX and RX, which saves area. Independent TX/RX baud rates are out of scope.
2. **3-sample majority vote** at ticks 6–8 is the "glitch filtering" requested. A longer digital filter on `rxd` was not added, because it would shift the sample point.
3. **One stop bit only.** The spec says 8N1-style frames; 2-stop-bit and 5–7-bit data are not supported.
4. **Error flags are stored per byte** in the RX FIFO (10-bit entries), as requested. Overrun is a separate sticky flag, because the dropped byte has no FIFO slot.
5. **Break** is reported as a single framing error with data 0x00. A dedicated `rx_break` flag can be added if firmware needs to tell break apart from a bad stop bit.
6. **FIFO depth 8**, as in the spec, but parameterized. Interrupt generation (e.g. RX level threshold) is left to the register wrapper, which can use `rx_level`/`tx_level`.
7. **`baud_div` is not latched per frame.** Firmware must change it only while the link is idle; confirm with the wrapper team.
8. **No hardware flow control** (RTS/CTS), because the spec does not mention it.
