# MA plan: 07_uart_transceiver

## S1. Scope the UART core as a vendor-IP replacement behind a separate register wrapper

**Goal:** Write the Overview: a single-clock UART core (TX + RX + two FIFOs) for a GPS module and debug console. It is configured at runtime by divider and parity inputs, and it exposes valid/ready streams to a register wrapper owned by another team. State what is out of scope (registers, interrupts, flow control).

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P2] "we need our own UART block instead of the vendor IP"
- [P2] "It talks to a"
- [P5] "the register wrapper is done"
- [P5] "separately by another team."

**Decisions:**
- D1 Core boundary vs register wrapper: **The core exposes raw config input ports and valid/ready streams. Registers and interrupt logic live in the wrapper.** (decided)
  - options: Core exposes raw config inputs (divider, parity) and stream ports; wrapper owns registers and interrupts / Core includes its own CSR block
  - The spec says the register wrapper is done separately and the CPU side is a valid/ready stream.

**Done when:**
- Overview names the use cases (GPS, debug console), the target baud rates 9600 and 115200, and clocks of 50 MHz and 100 MHz.
- Overview explicitly lists what is out of scope: CSRs, interrupt generation, RTS/CTS flow control, and configurable data or stop bit counts.

## S2. Define the port list: serial pins, runtime config, TX/RX streams with per-byte error sideband, and overflow/status

**Goal:** Enumerate every port with direction, width, and meaning. This covers clk, reset, rxd, txd, the divider input, parity enable/odd inputs, the TX input stream, and the RX output stream carrying data plus frame/parity error flags. It also covers the overflow indication and FIFO status outputs useful to the wrapper.

**Feeds:** Interface · **Depends on:** S1

**Spec evidence:**
- [P5] "The CPU side should look"
- [P5] "like a simple valid/ready stream on both directions"
- [P3] "so even/odd parity has to be optional and switchable at runtime."
- [P2] "Firmware should be able to set the baud rate at runtime through a"

**Decisions:**
- D2 CPU-side interface protocol: **A valid/ready handshake on both directions. The TX sink accepts a byte when valid && ready. The RX source holds data and flags stable while valid && !ready.** (decided)
  - options: AXI-Stream-style valid/ready for TX in and RX out / Register/strobe interface
  - Stated directly in P5.
- D3 Parity configuration ports: **Two runtime inputs, parity_en and parity_odd, shared by TX and RX. Each FSM latches them at the start of a frame.** (default, low impact, high confidence)
  - options: Two runtime inputs parity_en and parity_odd shared by TX and RX / Separate TX/RX parity configs / Compile-time parameter
  - The spec requires optional even/odd parity switchable at runtime. One link partner implies a shared setting. Latching at frame start avoids mid-frame corruption.

**Done when:**
- Port table is complete, with direction, width, clock domain, and reset value for every output.
- The RX stream payload is defined as 8 data bits plus frame_err and parity_err sideband bits, aligned with that byte's valid.
- The handshake rules (no combinational valid-on-ready dependency, data stable while stalled) are written down.

## S3. Parameterize the core so the clock frequency is never hard-coded

**Goal:** Define the Parameters section: divider width, FIFO depth, and sync stages. Show that a runtime divider covers 9600 and 115200 baud at both 50 MHz and 100 MHz with acceptable error.

**Feeds:** Parameters · **Depends on:** S2

**Spec evidence:**
- [P2] "Our system clock is 50 MHz, but other projects run at 100 MHz, so please"
- [P2] "don't hard-code it."
- [P5] "put a small FIFO on each side (8 bytes is"

**Decisions:**
- D4 How clock independence is achieved: **A runtime divider input with a parameterized width. The RTL contains no clock-frequency constant.** (decided)
  - options: Runtime divider only; no clock-frequency parameter in RTL / CLK_FREQ parameter plus runtime baud select / Both CLK_FREQ (for a reset-default divider) and runtime divider
  - The spec asks not to hard-code the clock and to set baud via a divider at runtime.
- D5 FIFO depth: **A FIFO_DEPTH parameter, default 8, used for both TX and RX FIFOs.** (decided)
  - options: Parameter FIFO_DEPTH default 8 (power of 2) / Fixed 8 / Larger default (16)
  - The spec suggests 8 bytes. Parameterizing costs nothing.

**Done when:**
- Parameter table lists DIV_WIDTH, FIFO_DEPTH, and SYNC_STAGES with default values and legal ranges.
- A worked table gives the divider value and resulting baud error for 9600 and 115200 at 50 MHz and 100 MHz, with all errors under 2%.
- DIV_WIDTH is shown to be wide enough for 9600 baud at 100 MHz.

## S4. Design the 16x oversample tick generator driven by the runtime divider

**Goal:** Specify the baud tick counter that produces a single-cycle enable at 16x the baud rate, shared by RX sampling and TX bit timing. Define the divider semantics and what happens when the divider changes or is zero.

**Feeds:** Datapath, Timing & Pipeline · **Depends on:** S3

**Spec evidence:**
- [P4] "The receiver should oversample at 16x and sample in the middle of each bit."
- [P2] "so it has to be reliable at 9600 baud and also at"
- [P2] "115200 baud."

**Decisions:**
- D6 Divider semantics and baud generator structure: **An integer divider giving clk cycles per 16x tick (div = round(f_clk/(16*baud))). One free-running tick generator is shared by RX and TX, and TX advances one bit every 16 ticks.** (default, medium impact, medium confidence)
  - options: Integer divider = clk/(16*baud) producing one shared 16x tick for RX and TX / Divider = clk/baud with separate per-bit counters / Fractional (accumulator) divider
  - Integer error is about 0.5% at 115200 for both 50 and 100 MHz, which is well within UART tolerance. This is the simplest and most common structure.

**Done when:**
- Divider formula and counter behaviour (reload, tick pulse width of 1 clk) are specified.
- Behaviour for divider = 0 or 1 is defined (clamp or hold idle).
- Behaviour when the divider changes mid-frame is defined (takes effect at the next tick reload).

## S5. Specify the RX front end: synchronizer, glitch filter, and false-start rejection

**Goal:** Define how the asynchronous rxd pin is synchronized, filtered against noise, and how a start bit is qualified. A short low glitch on an idle line must never launch a frame.

**Feeds:** Datapath, Control Logic · **Depends on:** S4

**Spec evidence:**
- [P4] "noisy, so some glitch filtering would be appreciated."
- [P4] "Please also make sure a short glitch"
- [P4] "on the idle line isn't taken as a start bit."

**Decisions:**
- D7 Glitch filter method: **A 2-FF synchronizer, followed by a 3-sample majority vote at oversample ticks 7/8/9 of every bit, including the start bit.** (default, medium impact, medium confidence)
  - options: Majority vote of 3 oversamples around mid-bit (ticks 7,8,9) / Continuous N-sample debounce filter ahead of the FSM / Both
  - This is standard practice (16550-style), rejects glitches shorter than about 1/16 bit without adding latency, and keeps the mid-bit sampling the spec requested.
- D8 Start-bit qualification: **A falling edge arms the receiver. If the majority-voted mid-start sample is high, the receiver aborts to IDLE without producing a byte.** (decided)
  - options: Detect falling edge, then re-verify low at mid-start-bit (majority); abort to IDLE if high / Accept on falling edge
  - The spec explicitly forbids treating a short idle-line glitch as a start bit.

**Done when:**
- Synchronizer depth and metastability argument are documented.
- The maximum glitch width rejected is stated in oversample ticks.
- The abort path from START_CHECK back to IDLE is shown in the FSM diagram.

## S6. Define the RX frame FSM with per-byte frame/parity error tagging

**Goal:** Specify the RX FSM states (IDLE, START, DATA x8 LSB first, PARITY optional, STOP), the shift register, the parity check, and the stop-bit check. Errors must be tied to the exact byte they affect.

**Feeds:** Control Logic, Datapath · **Depends on:** S5

**Spec evidence:**
- [P3] "Frame format is the usual 8 data bits, 1 stop bit, LSB first."
- [P3] "bad stop bit or a parity mismatch, the CPU needs to know which byte was affected, not just"
- [P3] "that an error happened at some point."

**Decisions:**
- D9 Per-byte error reporting mechanism: **Errored bytes are still pushed. Each RX FIFO entry is {parity_err, frame_err, data[7:0]}, and the flags appear as sideband on the RX stream with that byte.** (default, high impact, high confidence)
  - options: Store frame_err/parity_err with each byte in the RX FIFO (10-bit entries) and output them as RX stream sideband / Drop erroneous bytes and count errors / Separate error FIFO
  - This is the only option that tells the CPU which byte was bad while keeping order. It costs 2 extra bits per FIFO entry.
- D10 Receiver behaviour after a framing error / break: **After a bad stop bit, the receiver waits for rxd to be high before re-arming. No separate break flag is generated; a break shows up as a byte of 0x00 with frame_err.** (default, low impact, medium confidence)
  - options: Wait for line to return high (idle) before re-arming start detection / Re-arm immediately after stop sample / Additionally report a break flag
  - This prevents a held-low line from flooding the FIFO with error bytes. Break reporting was not requested.

**Done when:**
- The FSM state diagram has transitions gated by the 16x tick and a bit counter.
- Parity is computed as XOR of the data bits, with the odd/even selection defined, and the parity state is skipped when disabled.
- The stop bit is sampled at mid-bit, and the byte plus flags are pushed when that sample is taken (no need to wait for the full stop bit).

## S7. Define the TX path: FIFO-fed shift register with optional parity and stop bit

**Goal:** Specify the TX FSM, which pops the TX FIFO, sends start, 8 data bits LSB first, optional parity, and stop. Bit timing is every 16 ticks, and back-to-back frames run with no gaps. txd idles high.

**Feeds:** Datapath, Control Logic · **Depends on:** S4, S2

**Spec evidence:**
- [P3] "Frame format is the usual 8 data bits, 1 stop bit, LSB first. Some GPS modules use parity,"
- [P5] "like a simple valid/ready stream on both directions"

**Done when:**
- The TX FSM and shift register are specified, with txd registered (glitch-free output).
- Parity config is latched at the TX frame start.
- Back-to-back throughput is defined: the next start bit begins immediately after the stop bit when the FIFO is non-empty.

## S8. Specify TX and RX synchronous FIFOs and the RX overflow policy

**Goal:** Define both FIFOs (width, depth, full/empty logic, pointer scheme). Settle exactly what happens and what is signalled when a byte arrives and the RX FIFO is full.

**Feeds:** Datapath, Block Diagram, Corner Cases & Error Handling · **Depends on:** S6, S7, S3

**Spec evidence:**
- [P5] "The CPU is slow to service interrupts, so put a small FIFO on each side (8 bytes is"
- [P5] "If the RX FIFO overflows we must know about it."

**Decisions:**
- D11 RX overflow behaviour and signalling: **The incoming byte is dropped and FIFO contents are preserved. A sticky rx_overflow output is set, cleared by an rx_overflow_clr input, and a one-cycle pulse is also provided for the wrapper's interrupt logic.** (default, medium impact, medium confidence)
  - options: Drop incoming byte; assert sticky overflow flag cleared by an input pulse / Drop incoming byte; emit single-cycle overflow pulse (wrapper makes it sticky) / Overwrite oldest; tag next delivered byte with overrun flag
  - Preserving already-received data is the 16550 convention. The sticky flag guarantees a slow CPU sees it, and the pulse lets the wrapper count events or raise an interrupt.

**Done when:**
- FIFO widths are stated: TX 8 bits, RX 10 bits (data + 2 error flags).
- Full/empty/count outputs available to the wrapper are listed.
- Simultaneous push and pop when full or empty is defined.
- The overflow flag set/clear timing is defined, including a clear coinciding with a new overflow.

## S9. Assemble the block diagram and end-to-end timing/latency

**Goal:** Draw the top-level block diagram (tick gen, RX sync/filter, RX FSM, RX FIFO, TX FIFO, TX FSM) and document latencies. These are the stream-accept to start-bit delay and the stop-bit sample to rx_valid delay, plus sustained throughput at maximum baud.

**Feeds:** Block Diagram, Timing & Pipeline · **Depends on:** S4, S5, S6, S7, S8

**Spec evidence:**
- [P4] "The receiver should oversample at 16x and sample in the middle of each bit."
- [P5] "so put a small FIFO on each side"

**Done when:**
- The block diagram shows every module and every signal crossing between modules.
- Latency numbers are given in clock cycles and oversample ticks for both directions.
- A timing waveform is included for one 8N1 frame and one 8E1 frame with mid-bit sample points marked.

## S10. Define clocking, reset, and the asynchronous rxd crossing

**Goal:** State that the design has one clock domain with rxd as the only asynchronous input. Define the reset style and reset values: txd high, FIFOs empty, FSMs idle, overflow cleared.

**Feeds:** Clocking & Reset · **Depends on:** S2

**Spec evidence:**
- [P2] "Our system clock is 50 MHz, but other projects run at 100 MHz, so please"
- [P4] "The line is"

**Decisions:**
- D12 Reset style: **Active-low reset, asserted asynchronously and deasserted synchronously (synchronizer is the integrator's responsibility). txd resets high.** (default, low impact, low confidence)
  - options: Asynchronous assert, synchronous deassert, active-low / Fully synchronous active-high
  - This is a common FPGA/ASIC-portable choice. It matters little architecturally, but must match the wrapper team's convention.

**Done when:**
- The single clock domain is documented, and rxd is identified as the only CDC point, with its synchronizer.
- Reset values are listed for every state element that is visible at outputs.
- txd is guaranteed to idle high during and after reset.

## S11. Enumerate corner cases: runtime reconfiguration, noise, errors, and FIFO extremes

**Goal:** Collect all edge behaviours in one place. These are divider or parity changes mid-frame, divider 0, a glitch on idle, a glitch mid-bit, a break, back-to-back RX frames with minimal stop, RX overflow while the CPU stalls, a TX stream stall, and a reset mid-frame.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S6, S7, S8

**Spec evidence:**
- [P3] "so even/odd parity has to be optional and switchable at runtime."
- [P4] "on the idle line isn't taken as a start bit."
- [P5] "If the RX FIFO overflows we must know about it."

**Done when:**
- Each corner case has a defined expected behaviour referencing the relevant FSM state.
- The baud mismatch tolerance of the RX sampling scheme is computed and stated.
- Simultaneous frame and parity errors on one byte are defined (both flags set).

## S12. Write the verification plan and list open assumptions

**Goal:** Define a testbench with a UART BFM. It should cover loopback at 9600 and 115200 for 50 and 100 MHz, all parity modes, injected parity and stop errors checked against the exact byte, glitch injection, baud offset tolerance, and RX overflow with stalled ready. Record the remaining assumptions and open questions.

**Feeds:** Verification Plan, Assumptions & Open Questions · **Depends on:** S9, S10, S11

**Spec evidence:**
- [P2] "so it has to be reliable at 9600 baud and also at"
- [P3] "the CPU needs to know which byte was affected"
- [P4] "Please also make sure a short glitch"

**Done when:**
- The test list maps each spec requirement (P2-P5) to at least one test.
- A scoreboard checks per-byte error-flag alignment with data.
- Assertions are listed for the valid/ready protocol, FIFO no-overflow/no-underflow, and txd idle high.
- Coverage goals include all parity modes, error types, the overflow event, and divider extremes.
- The open questions section lists every defaulted decision with its question.

## Assumptions (defaults not confirmed by the user)

- D3 Parity configuration ports: Two runtime inputs, parity_en and parity_odd, shared by TX and RX. Each FSM latches them at the start of a frame. (low impact, high confidence)
- D6 Divider semantics and baud generator structure: An integer divider giving clk cycles per 16x tick (div = round(f_clk/(16*baud))). One free-running tick generator is shared by RX and TX, and TX advances one bit every 16 ticks. (medium impact, medium confidence)
- D7 Glitch filter method: A 2-FF synchronizer, followed by a 3-sample majority vote at oversample ticks 7/8/9 of every bit, including the start bit. (medium impact, medium confidence)
- D9 Per-byte error reporting mechanism: Errored bytes are still pushed. Each RX FIFO entry is {parity_err, frame_err, data[7:0]}, and the flags appear as sideband on the RX stream with that byte. (high impact, high confidence)
- D10 Receiver behaviour after a framing error / break: After a bad stop bit, the receiver waits for rxd to be high before re-arming. No separate break flag is generated; a break shows up as a byte of 0x00 with frame_err. (low impact, medium confidence)
- D11 RX overflow behaviour and signalling: The incoming byte is dropped and FIFO contents are preserved. A sticky rx_overflow output is set, cleared by an rx_overflow_clr input, and a one-cycle pulse is also provided for the wrapper's interrupt logic. (medium impact, medium confidence)
- D12 Reset style: Active-low reset, asserted asynchronously and deasserted synchronously (synchronizer is the integrator's responsibility). txd resets high. (low impact, low confidence)
