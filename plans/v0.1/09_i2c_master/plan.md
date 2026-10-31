# MA plan: 09_i2c_master

## S1. Scope the I2C master for the 24C256 + PMIC multi-master bus

**Goal:** Write the Overview of the controller. It is a master-only I2C controller in a multi-master system, serving an EEPROM and a clock-stretching PMIC at 100/400 kHz with 7-bit addressing. Firmware drives it byte-by-byte through an OpenCores-style register set on the SoC's plain register port. State explicitly what is out of scope: slave mode, 10-bit addressing, Fast-mode Plus/HS.

**Feeds:** Overview, Assumptions & Open Questions · **Depends on:** none

**Spec evidence:**
- [P1] "i2c master - quick notes from arch review"
- [P2] "talks to the EEPROM (24C256) and the PMIC on the same bus"
- [P2] "7 bit addressing only"
- [P2] "needs std mode 100k and fast mode 400k"

**Decisions:**
- D1 Feature scope and address handling: **Master-only, 7-bit. Firmware writes {addr[6:0],R/W} into TXR and issues a STA+WR command, so there is no dedicated address register or automatic address phase in hardware.** (decided)
  - options: Master-only, 7-bit; firmware writes {addr,R/W} into TXR as an ordinary byte / Master-only, 7-bit; dedicated address register with automatic address phase / Master + slave mode
  - The user fixed the register layout as OpenCores-style PRESC/CTRL/TXR/RXR/CMD/STATUS. That layout has no address register, and in that model the address is just the first byte written. This matches 'i2c master' and '7 bit addressing only'.

**Done when:**
- Overview lists the supported conditions (START, STOP, Sr), both speed modes, ACK/NACK handling, clock stretching and arbitration-loss detection.
- Out-of-scope items (slave mode, 10-bit, >400 kHz, SMBus PEC) are listed explicitly.
- The EEPROM random-read sequence (S, addr+W, word addr hi, word addr lo, Sr, addr+R, data..., NACK, P) is shown as a firmware-level example using TXR/CMD writes.
- The Overview states that the design follows the OpenCores I2C master programming model, adapted to a 32-bit plain register port.

## S2. Open-drain pad interface and noisy-bus input conditioning

**Goal:** Define how SCL/SDA connect to open-drain pads with external pullups. Define the input path from the pads to internal logic: a synchronizer plus a glitch filter for the noise from the DC-DC.

**Feeds:** Interface, Datapath, Block Diagram · **Depends on:** S1

**Spec evidence:**
- [P2] "SCL/SDA are open drain pads w/ external pullups"
- [P2] "Ravi says the bus is noisy near the DC-DC, maybe filter inputs?"

**Decisions:**
- D2 Pad-side signal convention: **Separate input and drive-low-enable signals per line (scl_i, scl_oe, sda_i, sda_oe). The IP never drives high, and the pad cell sits outside the IP.** (default, medium impact, high confidence)
  - options: Separate scl_i / scl_oe (oe=1 drives low) and sda_i / sda_oe; pad output tied to 0 in the pad ring / Bidirectional inout ports inside the IP / OpenCores-style scl_pad_o (tied 0) / scl_padoen_o (active-low enable) triplet
  - This is the standard synthesizable way to model open drain with external pullups. It avoids inout ports inside the IP and makes the 'drive high' bug impossible. The OpenCores triplet is functionally equivalent and differs only in naming and polarity.
- D3 Input glitch filtering: **2-flop synchronizer followed by a digital glitch filter (majority/counter). Filter length is a synthesis parameter; at 48 MHz the default suppresses spikes of at least 50 ns (the I2C Fast-mode tSP). No register field is added, so the agreed register layout is unchanged.** (default, medium impact, medium confidence)
  - options: 2-flop synchronizer only / Synchronizer + digital glitch filter sized to suppress >=50 ns spikes, filter length as a synthesis parameter / Synchronizer + glitch filter with runtime-programmable length (e.g. a CTRL field) / Rely on analog pad filter
  - Ravi reports noise. Fast mode requires 50 ns spike suppression, and pads may not provide it. A parameterized filter covers this without adding to the OpenCores-style register set. Filter delay must be counted in the SCL timing and arbitration sampling.

**Done when:**
- Pad port table lists direction, active level and the open-drain meaning of each signal.
- Input path latency (synchronizer + filter cycles) is quantified at 48 MHz and fed into the S3 timing budget.
- It is stated that every internal decision (ACK, arbitration, stretching, START/STOP detection) uses the filtered inputs.

## S3. Clocking, reset and PRESC-based SCL timing from an uncertain ~48 MHz peripheral clock

**Goal:** Define the clock domain and the reset scheme. Define how 100 kHz and 400 kHz SCL timing (tLOW, tHIGH, tSU;STA, tHD;STA, tSU;STO, tBUF, tSU;DAT, tHD;DAT) is derived from the OpenCores-style PRESC register on a peripheral clock whose frequency is not pinned down.

**Feeds:** Clocking & Reset, Parameters, Timing & Pipeline · **Depends on:** S2

**Spec evidence:**
- [P2] "clk: whatever the SoC peripheral clock is, probably 48 MHz"
- [P2] "needs std mode 100k and fast mode 400k"

**Decisions:**
- D4 Clock domain structure: **Single peripheral clock domain for the register port and the I2C engine. SCL/SDA are treated as asynchronous inputs and synchronized in S2.** (default, medium impact, high confidence)
  - options: Single clock domain: register port and I2C engine both on the peripheral clock / Separate bus clock and I2C kernel clock with CDC
  - The spec mentions only one clock. The user said the register port is 'the same simple 32-bit bus as the other peripherals' with registered rdata, which points to a synchronous peripheral-clock port. A single domain avoids CDC on the register file and command handshakes.
- D5 SCL timing programmability: **Single runtime-programmable PRESC register in OpenCores style. SCL period is about 5*(PRESC+1) peripheral clocks, divided into fixed sub-phases from which the START/STOP setup and hold and the data setup and hold derive. PRESC is a single 16-bit field in one 32-bit register, not split lo/hi, and must only be changed while CTRL.EN=0.** (decided)
  - options: Single runtime PRESC register, OpenCores-style (each SCL period = 5*(PRESC+1) clk, split into fixed phases) / Separate SCL low/high count registers / Fixed parameters for 48 MHz with a 1-bit std/fast mode select
  - The user's answer fixes the register layout as PRESC/CTRL/TXR/RXR/CMD/STATUS, which means one prescaler rather than separate low/high counts. A runtime value still handles the uncertain clock and both modes.

**Done when:**
- Clock domain and reset polarity/synchronization are stated, and the reset state of SCL/SDA drive is 'released'.
- The PRESC-to-SCL formula is given, with example values at 48 MHz for 100 kHz and 400 kHz.
- A table maps each I2C timing parameter (Sm and Fm minimums) to the fixed sub-phase that produces it, with the margin at those example values.
- The Fm tLOW >= 1.3 us constraint is checked against the fixed duty cycle. If the duty cycle cannot meet it at exactly 400 kHz, the recommended Fm PRESC (and the resulting slightly lower SCL) is stated.
- Minimum legal PRESC is derived from synchronizer/filter latency, and the behaviour for illegal values or for writing PRESC while EN=1 is defined.
- Synthesis parameters (PRESC width, filter length) are listed with defaults.

## S4. Plain 32-bit register port, OpenCores-style register map, CMD semantics and IRQ

**Goal:** Define the CPU-facing plain register port (addr[4:0], wdata, we, re, registered rdata) and the OpenCores-style register map PRESC/CTRL/TXR/RXR/CMD/STATUS. Define the CMD bits firmware uses to issue START/WRITE/READ/STOP one byte at a time, the single-byte buffering, and the IRQ mechanism.

**Feeds:** Interface, Control Logic, Parameters · **Depends on:** S1, S3

**Spec evidence:**
- [P2] "CPU interface: TBD, something simple that firmware can drive byte-by-byte, with an irq"
- [P2] "detect ACK/NACK from slave; master must NACK the last byte of a read"

**Decisions:**
- D6 CPU bus protocol: **Plain 32-bit register port, the same as the other peripherals. Signals are addr[4:0] (byte address, bits [1:0] ignored), wdata[31:0], we, re and rdata[31:0]. rdata is registered and valid one cycle after re. There are no wait states and no error response.** (decided)
  - options: APB (APB3/APB4 with PREADY/PSLVERR) / Simple synchronous register port (addr, wdata, we, re, rdata) / AHB-Lite / Wishbone
  - This was settled by the user's answer to Q1.
- D7 Command model: **OpenCores-style byte-level CMD register with STA, STO, RD, WR, ACK and IACK. STA issued while the bus is held by this master produces a repeated START. ACK selects the value the master drives after RD, and firmware sets NACK on the last read byte. STO may be combined with WR or RD.** (decided)
  - options: Byte-level CMD register: STA, STO, RD, WR, ACK, IACK bits, one command at a time (OpenCores style) / Transaction-level descriptor (address, length, direction) with hardware sequencing
  - The spec asks for 'drive byte-by-byte' and requires the master to NACK the last read byte. The user fixed an OpenCores-style CMD register.
- D8 Data buffering depth: **Single TXR transmit register and single RXR receive register, with no FIFOs.** (decided)
  - options: Single TXR + single RXR / Small TX/RX FIFOs (e.g. 4-16 deep)
  - The user-specified OpenCores-style layout has exactly one TXR and one RXR. Byte-by-byte control with one IRQ per byte is adequate at 400 kHz (~22 us per byte).
- D9 Interrupt and status structure: **OpenCores-style interrupt. One level-sensitive active-high irq = STATUS.IF & CTRL.IEN. IF is set on command completion or arbitration loss (and on timeout if D12 is kept) and is cleared by writing CMD.IACK. STATUS also exposes RxACK, BUSY (bus busy), AL and TIP. There are no separate W1C/enable registers.** (decided)
  - options: OpenCores style: single IF flag in STATUS, gated by CTRL.IEN, cleared by CMD.IACK; STATUS holds RxACK, BUSY, AL, TIP / Separate IRQ-enable register + W1C multi-flag status / Multiple IRQ lines
  - The user fixed the layout as PRESC/CTRL/TXR/RXR/CMD/STATUS with no IRQ-enable or W1C registers, which implies the OpenCores IF/IEN/IACK scheme. How a timeout cause is folded in is left to D12.

**Done when:**
- Port table for the register interface matches the agreed signals (addr[4:0], wdata[31:0], we, re, rdata[31:0]) and states the one-cycle registered read latency and the behaviour of simultaneous we/re.
- Register map gives word offsets for PRESC, CTRL, TXR, RXR, CMD and STATUS (and any spare offset used for D12). For each it gives fields, access type, reset value and read value. Write-only CMD/TXR read-back and unmapped offsets are defined.
- It is stated whether TXR/RXR and CMD/STATUS share offsets as in the original OpenCores design or have separate offsets.
- CTRL fields (EN, IEN) and STATUS fields (RxACK, BUSY, AL, TIP, IF) are defined, including when AL and IF set and clear.
- The CMD semantics table covers every legal combination, including STA on an already-held bus = Sr, STO-only, RD with ACK/NACK, and simultaneous RD+WR or a write with no bits set (treated as illegal or ignored).
- Behaviour on writing CMD while TIP=1, after arbitration loss, or while EN=0 is defined.
- Firmware sequences are written out for EEPROM byte write, EEPROM random read with Sr and final NACK, and a PMIC register read.

## S5. Bit-level engine: START/STOP/Sr generation with clock-stretching synchronization

**Goal:** Specify the bit controller FSM that produces START, repeated START, STOP, data bits and the ACK bit on SCL/SDA, driven by the PRESC phase timing. Specify how SCL high timing waits for the PMIC to release a stretched clock.

**Feeds:** Control Logic, Timing & Pipeline, Datapath · **Depends on:** S2, S3, S4

**Spec evidence:**
- [P2] "start / stop / repeated start (EEPROM random read needs Sr)"
- [P2] "PMIC does clock stretching, must support it"

**Decisions:**
- D10 Clock-stretching mechanism: **After releasing SCL, freeze the PRESC phase counter until the filtered SCL input reads high, then continue the high phases. This applies to every SCL rising edge (data, ACK, Sr, STOP setup).** (decided)
  - options: After releasing SCL, hold the phase counter until filtered scl_i reads high, then count the high phases / Fixed-time sampling ignoring SCL readback
  - The spec requires stretching support. SCL readback synchronization is the only correct way to do it, and it also gives clock synchronization for multi-master.

**Done when:**
- Bit FSM states and transitions are enumerated for IDLE, START, Sr, data bit write/read, ACK write/read and STOP, with the SDA/SCL drive value in each sub-phase.
- SDA changes only while SCL is low (except START/STOP), and the tHD;DAT/tSU;DAT margins are shown in PRESC phase units.
- The Sr sequence (release SDA, release SCL, wait high, tSU;STA, pull SDA) is specified, including stretching during Sr.
- Waveform figures are given for START, one data bit with stretching, Sr, and STOP.

## S6. Byte-level datapath: TXR/RXR shift register, ACK/NACK sampling and generation

**Goal:** Define the byte controller that sequences 8 data bits plus the ACK bit for each CMD. Define the shift register between TXR and RXR, and how slave ACK/NACK is captured into STATUS.RxACK or the master's ACK/NACK from CMD.ACK is driven on reads.

**Feeds:** Datapath, Control Logic · **Depends on:** S4, S5

**Spec evidence:**
- [P2] "detect ACK/NACK from slave; master must NACK the last byte of a read"
- [P2] "7 bit addressing only"

**Done when:**
- Byte FSM is specified (decode CMD -> optional START -> 8 bits -> ACK bit -> optional STOP -> done), with its handshake to the bit engine and its TIP/IF updates.
- Shift register is MSB-first, loaded from TXR and unloaded to RXR. The SDA sampling point (mid-SCL-high, after the filter) is stated, as is when RXR becomes valid relative to IF.
- Received ACK/NACK goes to STATUS.RxACK. It is stated that a NACK does not abort, and firmware decides on STOP.
- Master ACK/NACK drive on reads comes from CMD.ACK, with the last-byte-NACK usage documented.

## S7. Multi-master support: bus-busy tracking and arbitration loss with the debug MCU

**Goal:** Specify how the master detects that the debug MCU owns the bus (STATUS.BUSY), how it behaves when START is commanded while the bus is busy, how it detects losing arbitration during address/data, and how it recovers.

**Feeds:** Control Logic, Corner Cases & Error Handling · **Depends on:** S5, S6

**Spec evidence:**
- [P2] "there's a debug MCU that can also master the bus sometimes -> need arbitration loss detection"
- [P2] "SCL/SDA are open drain pads w/ external pullups"

**Decisions:**
- D11 Arbitration-loss and bus-busy behaviour: **STATUS.BUSY is set by any START and cleared by STOP (and by reset). A STA command waits while the bus is busy. On arbitration loss (SDA released but read low while SCL is high, or an unexpected START/STOP) the master releases both lines at once, aborts the command, sets STATUS.AL and IF, and does not retry automatically.** (default, medium impact, medium confidence)
  - options: Track START/STOP for STATUS.BUSY; STA waits while busy; on loss release lines immediately, abort, set AL + IF, no auto-retry / Same, but STA while busy is an immediate arbitration loss (original OpenCores behaviour) / Same, with hardware auto-retry after bus free
  - This is the standard I2C multi-master behaviour. Firmware-driven retry fits the byte-by-byte model. Waiting while busy avoids colliding with the debug MCU, although the original OpenCores core flags AL instead, and the author may expect that.

**Done when:**
- Arbitration-loss conditions are listed: SDA mismatch on data/address/ACK bits, START or STOP detected at an unexpected time, and loss during Sr/STOP generation.
- Lines are released within a bounded number of clocks after loss is detected, and that bound is given.
- The BUSY state machine is specified, including the initial state after reset when another master may already be mid-transfer.
- How AL is cleared (e.g. on next CMD write or IACK) is defined, and the command FSM returns to IDLE cleanly.

## S8. Error and corner cases: NACKs, stuck/stretched bus, illegal commands

**Goal:** Enumerate abnormal conditions on a bus shared with a stretching PMIC, a debug master and noise, and define what hardware does in each case within the OpenCores-style register set.

**Feeds:** Corner Cases & Error Handling, Control Logic · **Depends on:** S4, S6, S7

**Spec evidence:**
- [P2] "PMIC does clock stretching, must support it"
- [P2] "Ravi says the bus is noisy near the DC-DC, maybe filter inputs?"
- [P2] "detect ACK/NACK from slave; master must NACK the last byte of a read"

**Decisions:**
- D12 Stuck-bus / stretching timeout: **Add an optional programmable stretch/stuck timeout register at a spare offset (0 = disabled, the reset value). On expiry the master releases the lines, aborts, sets a STATUS timeout bit and IF. Clearing CTRL.EN always forces release. Bus recovery (9 SCL clocks) is out of scope.** (default, low impact, low confidence)
  - options: No timeout (wait forever, firmware clears CTRL.EN to force release) / Programmable SCL-low/stretch timeout in a spare register offset that aborts, releases lines, sets a STATUS timeout bit and IF / Fixed SMBus-style 25-35 ms timeout
  - With an unbounded stretch, a misbehaving PMIC or a noisy line could hang firmware. A disable-able timeout costs little, and with a reset value of 0 the core behaves exactly like the OpenCores layout. It does add a register beyond the agreed list, so it needs confirmation.

**Done when:**
- The corner-case table covers address NACK, data NACK during write, RD without a prior address, CMD written while TIP=1, EN cleared mid-transfer, PRESC written while EN=1, timeout, glitches near SCL edges, STA while BUSY, and reset during a transfer.
- Each row gives the hardware action, the resulting STATUS bits/IF, and whether the bus is released or held.
- It is stated whether bus recovery (9 clocks) is in or out of scope.

## S9. Block diagram and end-to-end transaction timing

**Goal:** Assemble the blocks into a diagram and give end-to-end timing for representative transactions. The blocks are the register port and register file, byte controller, bit engine with PRESC phase counter, input filter, BUSY/arbitration monitor, and IRQ logic.

**Feeds:** Block Diagram, Timing & Pipeline · **Depends on:** S2, S3, S4, S5, S6, S7, S8

**Spec evidence:**
- [P2] "start / stop / repeated start (EEPROM random read needs Sr)"
- [P2] "needs std mode 100k and fast mode 400k"

**Done when:**
- Block diagram shows every block and the signals between them, including the register-port signals, pad-side signals and irq.
- Latency is stated from a CMD write (we) to the first SCL/SDA activity, from the final ACK to IF/irq, and for register reads (re to rdata = 1 cycle).
- A timeline of an EEPROM random read at the chosen Fm PRESC is shown, marking firmware interrupt points.
- The worst-case firmware IRQ service deadline per byte is derived for both modes, given single-byte buffering.

## S10. Verification plan with EEPROM, stretching-PMIC and competing-master models

**Goal:** Define testbench components and test scenarios that cover every requirement in the arch-review notes plus the agreed register port.

**Feeds:** Verification Plan · **Depends on:** S9

**Spec evidence:**
- [P2] "talks to the EEPROM (24C256) and the PMIC on the same bus"
- [P2] "PMIC does clock stretching, must support it"
- [P2] "there's a debug MCU that can also master the bus sometimes -> need arbitration loss detection"
- [P2] "Ravi says the bus is noisy near the DC-DC, maybe filter inputs?"

**Done when:**
- TB components are listed: a register-port driver (we/re with one-cycle rdata), a wired-AND bus model with pullups, a 24C256 behavioural model (2-byte word address, random/sequential read), a PMIC model with configurable stretching, a second-master model, a glitch injector, and an I2C protocol checker/monitor.
- Scenarios cover both speeds at 48 MHz and at a non-48 MHz clock, Sr random read, last-byte NACK, address/data NACK, long stretching, arbitration loss at the address bit, data bit and Sr, STA while BUSY, timeout (if kept), glitch rejection, and reset mid-transfer.
- Register tests cover reset values, access types, ignored addr[1:0], read latency, IACK clearing IF, and IEN gating of irq.
- Assertions cover the I2C timing minimums (tLOW, tHIGH, tSU/HD STA/STO/DAT, tBUF), no driving high, and SDA stable while SCL is high except START/STOP.
- Coverage goals are stated for CMD bit combinations, FSM states and STATUS flags.

## S11. Consolidate assumptions and open questions from the informal arch-review notes

**Goal:** Collect every remaining defaulted decision and unresolved item from the notes into the Assumptions & Open Questions section. Unresolved items include the uncertain clock frequency and the 'maybe' on filtering. Record the resolved CPU-interface answer as an assumption baseline.

**Feeds:** Assumptions & Open Questions · **Depends on:** S1, S2, S3, S4, S7, S8

**Spec evidence:**
- [P2] "CPU interface: TBD, something simple that firmware can drive byte-by-byte, with an irq"
- [P2] "clk: whatever the SoC peripheral clock is, probably 48 MHz"
- [P2] "Ravi says the bus is noisy near the DC-DC, maybe filter inputs?"

**Done when:**
- Every defaulted decision (D2, D3, D4, D11, D12) is listed with its assumed choice and the question to resolve it.
- Decisions settled by the Q1 answer (D1, D5, D6, D8, D9) are recorded as resolved, citing the OpenCores-style layout.
- Any deviation from the original OpenCores core is listed (32-bit registers, single PRESC field, STA-while-busy behaviour, optional timeout register).
- Any assumption about the pad cells (analog filter present? drive strength) and the pullup values / bus capacitance is recorded.
- The assumed minimum peripheral clock frequency for meeting 400 kHz timing with the PRESC scheme is stated.

## Assumptions (defaults not confirmed by the user)

- D2 Pad-side signal convention: Separate input and drive-low-enable signals per line (scl_i, scl_oe, sda_i, sda_oe). The IP never drives high, and the pad cell sits outside the IP. (medium impact, high confidence)
- D3 Input glitch filtering: 2-flop synchronizer followed by a digital glitch filter (majority/counter). Filter length is a synthesis parameter; at 48 MHz the default suppresses spikes of at least 50 ns (the I2C Fast-mode tSP). No register field is added, so the agreed register layout is unchanged. (medium impact, medium confidence)
- D4 Clock domain structure: Single peripheral clock domain for the register port and the I2C engine. SCL/SDA are treated as asynchronous inputs and synchronized in S2. (medium impact, high confidence)
- D11 Arbitration-loss and bus-busy behaviour: STATUS.BUSY is set by any START and cleared by STOP (and by reset). A STA command waits while the bus is busy. On arbitration loss (SDA released but read low while SCL is high, or an unexpected START/STOP) the master releases both lines at once, aborts the command, sets STATUS.AL and IF, and does not retry automatically. (medium impact, medium confidence)
- D12 Stuck-bus / stretching timeout: Add an optional programmable stretch/stuck timeout register at a spare offset (0 = disabled, the reset value). On expiry the master releases the lines, aborts, sets a STATUS timeout bit and IF. Clearing CTRL.EN always forces release. Bus recovery (9 SCL clocks) is out of scope. (low impact, low confidence)
