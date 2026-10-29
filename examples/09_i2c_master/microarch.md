# Micro-architecture: `i2c_master`

## 1. Overview

`i2c_master` is a firmware-driven, byte-level I2C master for Standard mode (100 kHz) and
Fast mode (≤ 400 kHz) with open-drain SCL/SDA. Firmware writes one command per byte (any
mix of START, WRITE, READ, ACK value and STOP) and gets an interrupt when it finishes.

The design has two layers:
- **Byte controller** – decodes the command register and sequences START → 8 data bits → ACK bit → STOP.
- **Bit controller** – runs each bit-level primitive (START, STOP, WRITE-bit, READ-bit) as a series of quarter-period phases, drives the open-drain enables, honours clock stretching, and detects arbitration loss.

Key features:
- Repeated START (Sr) for EEPROM random reads.
- 7-bit addressing: firmware sends the address byte `{addr[6:0], R/W}` with a START|WRITE command. No dedicated address hardware is needed.
- Clock stretching and multi-master clock synchronization through SCL read-back.
- Arbitration-loss detection on SDA mismatch and on an unexpected STOP.
- Bus-busy tracking from START/STOP conditions on the bus.
- 2-flop synchronizers plus a programmable spike filter (≥ 50 ns) on SCL/SDA inputs.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | Peripheral clock (48 MHz nominal). |
| `rst_n` | in | 1 | Active-low reset; async assert, sync de-assert. |
| **Register bus** | | | |
| `addr` | in | 5 | Byte address; [1:0] ignored. |
| `wdata` | in | 32 | Write data. |
| `we` | in | 1 | Write strobe. |
| `re` | in | 1 | Read strobe. |
| `rdata` | out | 32 | Read data, registered, valid one cycle after `re`. |
| `irq` | out | 1 | `IEN & IF`. |
| **Pads (open drain)** | | | |
| `scl_i` | in | 1 | SCL pad input (asynchronous). |
| `scl_oe` | out | 1 | 1 = drive SCL low, 0 = release (pulled up externally). |
| `sda_i` | in | 1 | SDA pad input (asynchronous). |
| `sda_oe` | out | 1 | 1 = drive SDA low, 0 = release. |

Pad wrapper: `assign SCL = scl_oe ? 1'b0 : 1'bz; assign scl_i = SCL;` (same for SDA). The
block never drives a 1.

**Register map**

| Offset | Name | Access | Fields |
|--------|------|--------|--------|
| 0x00 | PRESC | RW | [15:0] quarter-period = PRESC + 1 clocks |
| 0x04 | CTRL | RW | [0] EN, [1] IEN, [6:4] FILT (spike-filter length, clocks) |
| 0x08 | TXR | RW | [7:0] byte to transmit |
| 0x0C | RXR | RO | [7:0] last byte received |
| 0x10 | CMD | WO | [0] STA, [1] STO, [2] RD, [3] WR, [4] ACK (value sent after a read: 0 = ACK, 1 = NACK), [7] IACK (clear IF) |
| 0x14 | STATUS | RO | [0] IF, [1] TIP, [2] AL, [3] BUSY (bus), [4] RXACK (1 = slave NACKed) |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `FILT_RST` | 3 | 0–7 | Reset value of CTRL.FILT. |

Recommended PRESC values (f_clk = 48 MHz):

| Mode | PRESC | Quarter `q` | SCL freq (no stretching) | tLOW / tHIGH |
|------|-------|-------------|--------------------------|--------------|
| Standard | 119 | 2.50 µs | 100 kHz | 5.0 / 5.0 µs (min 4.7 / 4.0) |
| Fast | 31 | 0.667 µs | 375 kHz | 1.33 / 1.33 µs (min 1.3 / 0.6) |

A 50 % duty cycle at exactly 400 kHz gives tLOW = 1.25 µs, which breaks the Fast-mode
minimum of 1.3 µs. 375 kHz is therefore the fastest compliant setting with this phase scheme
(see §11).

## 4. Block Diagram

```
 bus  +----------+ cmd,txr  +-----------------+ bit_cmd,bit_din  +------------------+  scl_oe ---> SCL pad
 ---->| i2c_regs |--------->|  byte_ctrl FSM  |----------------->|  bit_ctrl FSM    |  sda_oe ---> SDA pad
 <----| PRESC    |<---------|  sh[8], bitcnt  |<-----------------|  phase, q_cnt    |
 irq  | CTRL TXR |  done,   |                 | bit_done,dout,al |  owned           |
      | RXR STAT |  rxack,  +-----------------+                  +------------------+
      +----------+  al, rxr                                        ^   ^       ^
                                                                   |   |       | start_det/stop_det
                                                           scl_f   |   | sda_f |
                                                       +-----------+---+-------+--+
                                       scl_i, sda_i -->| sync_2ff x2 + spike_filt |
                                                       |  + bus_busy detector     |
                                                       +--------------------------+
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_regs` | `i2c_regs` | Register file, CMD decode, IF/AL/TIP status, `irq`. |
| `u_byte` | `i2c_byte_ctrl` | Command sequencer and data shift register. |
| `u_bit` | `i2c_bit_ctrl` | Quarter-phase generator, pad enables, stretching, arbitration. |
| `u_in_scl`, `u_in_sda` | `i2c_in_filt` | 2-FF synchronizer + stability filter (`FILT` clocks). |
| `u_busmon` | `i2c_bus_mon` | START/STOP condition detection, `bus_busy`. |

## 5. Datapath

**Input conditioning (per line)**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `s_meta`, `s_sync` | 1 each | 1 | 2-FF synchronizer (lines idle high). |
| `f_cnt` | 3 | 0 | Counts consecutive clocks where `s_sync != filt`. |
| `filt` (`scl_f`/`sda_f`) | 1 | 1 | Filtered level; toggles when `f_cnt == FILT`. |

```verilog
if (s_sync == filt) f_cnt <= 0;
else if (f_cnt == filt_len) begin filt <= s_sync; f_cnt <= 0; end
else f_cnt <= f_cnt + 1;
```

With FILT = 3 at 48 MHz, a level must hold 4 clocks (83 ns) to be accepted, so 50 ns
spikes are rejected. Total input delay is 2 (sync) + 4 = 6 clocks (125 ns).

**Bus monitor:** `start_det = scl_f && sda_f_q && !sda_f`; `stop_det = scl_f && !sda_f_q && sda_f`
(`sda_f_q` is `sda_f` delayed one clock). `bus_busy` is set by `start_det` and cleared by `stop_det` (reset 0).

**Bit controller**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `q_cnt` | 16 | 0 | Quarter-period counter; `q_end = (q_cnt == presc)`. |
| `phase` | 3 | 0 | Phase index within the current primitive (P1..P6 → 0..5). |
| `bstate` | 2 | B_IDLE | Primitive being executed: B_IDLE / B_START / B_STOP / B_DATA. |
| `din_q` | 1 | 1 | Bit to drive for B_DATA (1 = release). |
| `dout_q` | 1 | 1 | SDA sampled at the end of P3. |
| `scl_oe_q`, `sda_oe_q` | 1 each | 0 | Pad enables (registered). |
| `owned` | 1 | 0 | This master owns the bus (between its START and STOP). |
| `al_q` | 1 | 0 | Arbitration-lost pulse to the byte controller. |

**Byte controller**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `cstate` | 3 | C_IDLE | Byte-controller state. |
| `cmd_q` | 5 | 0 | Latched {ACK, WR, RD, STO, STA}; bits cleared as each part completes. |
| `sh` | 8 | 0 | Shift register (loaded from TXR on WRITE, collects bits on READ). |
| `bitcnt` | 3 | 0 | Data bit counter (7 → 0). |
| `rxr_q` | 8 | 0 | RXR. |
| `rxack_q` | 1 | 0 | ACK bit sampled after a WRITE (1 = NACK). |
| `tip_q`, `if_q`, `al_s` | 1 each | 0 | STATUS bits. |

## 6. Control Logic

**Bit-level primitives.** Every phase lasts `q = PRESC + 1` clocks. Phases marked **W**
release SCL and do not start counting until `scl_f == 1`; that is how clock stretching and
multi-master clock synchronization are handled.

| Primitive | P1 | P2 | P3 (W) | P4 | P5 | P6 |
|-----------|----|----|--------|----|----|----|
| START (bus owned → Sr) | SCL 0, SDA hold | SCL 0, SDA 1 | SCL 1, SDA 1 | SCL 1, SDA 1 | SCL 1, **SDA 0** | SCL 1, SDA 0 |
| START (bus idle) | – skip | – skip | SCL 1, SDA 1 | SCL 1, SDA 1 | SCL 1, **SDA 0** | SCL 1, SDA 0 |
| DATA (write/read bit) | SCL 0, SDA hold | SCL 0, SDA = `din` | SCL 1, SDA = `din`; **sample at end** | SCL 1, SDA = `din` | – | – |
| STOP | SCL 0, SDA hold | SCL 0, SDA 0 | SCL 1, SDA 0 | SCL 1, SDA 0 | SCL 1, **SDA 1** | SCL 1, SDA 1; check |

"SCL 1/SDA 1" means the enable is released (`oe = 0`). A READ bit is a DATA primitive with
`din = 1`. The ACK bit is a DATA primitive with `din = ACK` (after a read) or `din = 1` (after
a write, sampling the slave's ACK).

**Bit-controller transitions**

| Event | Action |
|-------|--------|
| `bit_cmd` issued in B_IDLE | Go to the primitive; `phase` = P1 (or P3 for START with `!owned`). |
| `q_end` in a non-W phase, or in a W phase after `scl_f` went high | `phase++`; `q_cnt <= 0`. |
| End of last phase | `bit_done` pulse; B_IDLE. START sets `owned=1`, STOP clears it. |
| P4 of DATA and `scl_f == 0` (another master pulled SCL low) | End P4 early (clock synchronization): `bit_done` now; the next P1 continues low. |

**Arbitration loss (`al`)**, raised for one clock:

```verilog
al = (bstate==B_DATA  && phase==P3 && q_end && scl_f && din_q && !sda_f)   // we sent 1, bus shows 0
   | (bstate==B_START && phase==P4 && q_end && !sda_f)                     // SDA held low by someone else
   | (bstate==B_STOP  && phase==P6 && q_end && !sda_f)                     // could not release SDA
   | (stop_det && owned && bstate!=B_STOP);                                // foreign STOP
```

On `al`: `scl_oe_q <= 0`, `sda_oe_q <= 0`, `owned <= 0`, and the bit controller returns to B_IDLE.

**Byte-controller FSM**

| State | Enc | Action | Next |
|-------|-----|--------|------|
| C_IDLE | 3'd0 | Wait for a CMD write with any of STA/WR/RD/STO set (and EN). Latch `cmd_q`, set TIP. | STA → C_START (only when `!bus_busy || owned`; else wait here); WR → C_WRITE (`sh<=TXR`, `bitcnt<=7`); RD → C_READ (`bitcnt<=7`); STO → C_STOP. |
| C_START | 3'd1 | Issue START; wait `bit_done`. | WR → C_WRITE; RD → C_READ; STO → C_STOP; else C_DONE. |
| C_WRITE | 3'd2 | Issue DATA with `din=sh[7]`; on `bit_done`: `sh<<=1`, `bitcnt--`. | After bit 0 → C_ACK. |
| C_READ | 3'd3 | Issue DATA with `din=1`; on `bit_done`: `sh<={sh[6:0],dout}`. | After bit 0 → C_ACK. |
| C_ACK | 3'd4 | Issue DATA with `din = WR ? 1 : cmd_q.ACK`; on `bit_done`: WR → `rxack_q<=dout`; RD → `rxr_q<=sh`. | STO → C_STOP; else C_DONE. |
| C_STOP | 3'd5 | Issue STOP; wait `bit_done`. | C_DONE. |
| C_DONE | 3'd6 | `tip<=0`, `if<=1`, clear `cmd_q`. | C_IDLE. |

Any state with `al` → `al_s<=1`, `if<=1`, `tip<=0`, clear `cmd_q`, C_IDLE.

Status equations: `if_q` is cleared by CMD.IACK (set wins); `al_s` is cleared by the next CMD
write that has STA set; `irq = IEN & if_q`.

## 7. Timing & Pipeline

- **Primitive durations:** DATA = 4q; START = 4q from idle, 6q for Sr; STOP = 6q. Stretching adds the time spent waiting in a W phase.
- **Byte time:** 9 bits × 4q = 36q (90 µs at Standard mode, 24 µs at Fast mode / PRESC = 31).
- **Firmware gap:** between commands SCL stays released (high) with SDA unchanged, so the bus is idle-safe while firmware services `irq`.
- **Spec timing (Standard, q = 2.5 µs):** tSU;DAT = 1q = 2.5 µs (min 0.25), tVD;DAT = 1q ≤ 3.45 µs, tSU;STA = tHD;STA = tSU;STO = 2q = 5 µs, tBUF ≥ 4q.
- **Spec timing (Fast, q = 0.667 µs):** tVD;DAT = 0.667 µs ≤ 0.9 µs; all other minima met at 2q = 1.33 µs.

Phase-level trace: command `STA|WR` with `TXR = 0xA0` (address 0x50, write) on an idle bus, slave ACKs, no stretching:

| Quarter | Primitive / phase | SCL | SDA | Note |
|---------|-------------------|-----|-----|------|
| 0 | START P3 | 1 | 1 | |
| 1 | START P4 | 1 | 1 | SDA checked high at end |
| 2 | START P5 | 1 | 0 | **START condition** |
| 3 | START P6 | 1 | 0 | `owned=1` at end |
| 4 | b7 P1 | 0 | 0 | SCL falls, SDA held |
| 5 | b7 P2 | 0 | 1 | b7 = 1 (released) |
| 6 | b7 P3 | 1 | 1 | sample: 1 → no AL |
| 7 | b7 P4 | 1 | 1 | |
| 8 | b6 P1 | 0 | 1 | |
| 9 | b6 P2 | 0 | 0 | b6 = 0 |
| 10–11 | b6 P3–P4 | 1 | 0 | |
| 12–35 | b5..b0 | … | 1,0,0,0,0,0 | same 4-phase pattern |
| 36 | ACK P1 | 0 | 0 | |
| 37 | ACK P2 | 0 | 0 | master releases, slave drives 0 |
| 38 | ACK P3 | 1 | 0 | `dout=0` → RXACK = 0 |
| 39 | ACK P4 | 1 | 0 | `bit_done` → C_DONE, IF = 1 |

Total: 40q = 4800 clocks (100 µs) in Standard mode.

EEPROM random read = 4 commands: `STA|WR (A0)` → `WR (addr_hi)` → `WR (addr_lo)` →
`STA|WR (A1)` [Sr] → `RD|ACK=1|STO`.

## 8. Clocking & Reset

- **Single clock domain** (`clk`). `scl_i`/`sda_i` are asynchronous and pass through 2-FF synchronizers (`ASYNC_REG`) before the filter. No other CDC.
- SCL is generated as a data signal (open-drain enable), not as a clock.
- **Reset:** all FSMs idle, both pad enables released (lines float high), `owned=0`, `bus_busy=0`, filters preset to 1.
- **EN = 0:** pad enables are forced to 0 and the FSMs held idle; register writes are still accepted.
- **PRESC/FILT changes** take effect immediately; firmware must only change them while `TIP=0`.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| Slave NACKs address or data | RXACK=1 reported; transaction not aborted automatically; firmware issues STO. |
| Clock stretching (slave holds SCL low) | W phase waits indefinitely for `scl_f==1` (see §11 on timeouts). |
| Another master wins arbitration | `al`: lines released immediately, AL=1, IF=1. The rest of the current byte is not clocked; the winning master continues undisturbed. |
| STA while another master owns the bus (`bus_busy && !owned`) | Command waits in C_IDLE (TIP=1) until `stop_det`, then starts. |
| Foreign STOP while we own the bus | Treated as arbitration loss. |
| CMD written while TIP=1 | Ignored (no queueing); firmware must wait for IF. |
| CMD with STA and STO only | START immediately followed by STOP (bus reset pattern) – legal. |
| CMD with RD and WR both set | WR takes precedence; RD ignored. |
| Spike < FILT+1 clocks on SCL/SDA | Filtered; no state change. |
| Reset in the middle of a transfer | Lines released; slaves may be left mid-byte (see §11, bus recovery). |

## 10. Verification Plan

**Testbench:** open-drain bus model (wired-AND with pull-up, configurable rise time). Agents:
an I2C slave model (24C256 behavioural EEPROM with ACK/NACK and clock stretching), a second
I2C master model to provoke arbitration, and a glitch injector.

**Directed tests**
1. Write byte to EEPROM: START, address, 2 addr bytes, data, STOP; check the EEPROM model contents.
2. Random read with repeated START and NACK on last byte.
3. Address NACK (no slave at address) → RXACK=1, then STOP.
4. Clock stretching of 0, 1q, 10q and 1 ms on a data bit and on ACK.
5. Arbitration: both masters address different slaves; the loser sees AL at the first differing bit, and the winner's transfer completes intact.
6. Foreign STOP during our transfer → AL.
7. STA while bus busy → waits for STOP, then proceeds.
8. Glitch injection of 1–5 clocks on SCL high and SDA during data → no corruption with FILT=3.
9. Standard and Fast PRESC: measure tLOW, tHIGH, tSU;STA, tHD;STA, tSU;STO, tBUF and tSU;DAT against I2C spec limits in the bus monitor.

**Random tests:** random command sequences (legal and illegal combinations), random stretching,
random arbitration start time, 2k transactions.

**Assertions (SVA)**

```systemverilog
a_no_start_in_data: assert property (@(posedge clk) disable iff(!rst_n)
                      bstate==B_DATA && phase inside {P3,P4} |-> $stable(sda_oe_q));
a_release_on_al:    assert property (@(posedge clk) disable iff(!rst_n) al |=> !scl_oe_q && !sda_oe_q);
a_owned_only_ours:  assert property (@(posedge clk) disable iff(!rst_n) owned |-> bus_busy);
a_tip_if:           assert property (@(posedge clk) disable iff(!rst_n) $fell(tip_q) |-> if_q);
a_sda_changes_low:  // SDA output changes only while SCL output is low, except in START P5 / STOP P5
```

**Coverage:** every byte-controller transition; START from idle and Sr; ACK and NACK in
both directions; stretching in each W phase; arbitration loss in START, DATA (address and
data byte) and STOP; FILT values 0 and 7; Standard and Fast mode.

## 11. Assumptions & Open Questions

The spec left several items TBD. Decisions taken:

1. **CPU interface:** a register interface like the industry-standard OpenCores I2C (PRESC/CTRL/TXR/RXR/CMD/STATUS), one command per byte with an IF interrupt, chosen as "simple, byte-by-byte". It is on the same simple 32-bit bus as the other peripherals.
2. **Clock:** 48 MHz assumed; PRESC makes the design work with any f_clk ≥ 10 MHz. Below that, the 6-clock input delay becomes a significant part of q.
3. **Fast mode runs at 375 kHz**, not 400 kHz, to meet tLOW ≥ 1.3 µs with a 50 % duty cycle. An asymmetric low/high split (e.g. 3:2 phases) would allow 400 kHz; deferred.
4. **Input filtering:** "maybe filter inputs" is implemented as a programmable 0–7 clock stability filter, default 3 (rejects ≥ 50 ns spikes as required for Fast mode).
5. **No timeouts.** A slave stretching forever or a stuck bus blocks TIP. Recommend adding an SMBus-style 25–35 ms timeout and a 9-clock bus-recovery command in a later revision.
6. **NACK handling** is left to firmware (no automatic STOP).
7. **Bus-busy at reset** is assumed false; if another master is mid-transfer at our reset, the first STA could collide, which is then caught by arbitration detection.
8. **10-bit addressing, high-speed mode and slave mode** are out of scope.
