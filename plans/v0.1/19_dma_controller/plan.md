# MA plan: 19_dma_controller

## S1. Fix v1 scope: 4-channel word-aligned mem-to-mem copier, no overlap, no scatter-gather

**Goal:** Write the Overview stating what the v1 DMA does and does not do. Record the confirmed word-aligned-only policy and the confirmed non-overlapped datapath, because they drive burst math, register checks, error codes and bandwidth.

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P3] "Memory-to-memory copy engine with 4 independent channels."
- [P6] "Byte-granular transfers vs word-aligned only? (Firmware team would be OK with word-aligned"
- [P6] "Descriptor chaining / scatter-gather: not for v1."
- [P2] "Status: incomplete, please fill in the gaps in the uArch."

**Decisions:**
- D1 Transfer granularity / alignment: **Word-aligned only. SRC[1:0], DST[1:0] and LEN[1:0] must all be 0. If any is misaligned at START, the channel sets ERR with ERR_CODE 3 (configuration error), never becomes BUSY, and generates no bus traffic. Byte-granular copies are not supported in v1.** (decided)
  - options: Word-aligned only: SRC, DST and LEN must be multiples of 4; anything else is a config error / Byte-granular with WSTRB masking and a realignment shifter
  - User answer Q1 confirmed this policy. It removes the byte-lane realignment shifter and partial-strobe logic.

**Done when:**
- Overview lists in-scope features: 4 channels, AXI4 burst master, AXI4-Lite config, round-robin sharing, per-channel interrupt and error.
- Overview lists out-of-scope items for v1: scatter-gather/chaining, byte-granular copies, read/write overlap.
- The alignment rule (bits [1:0]=0 on SRC, DST and LEN; ERR_CODE 3 otherwise) is stated once and referenced by the register-check and error sections.
- Overview states the expected v1 bandwidth of about 41% of port peak (~1.64 B/cycle at 16-beat bursts).

## S2. Define the AXI4 master, AXI4-Lite slave and interrupt ports

**Goal:** Specify the full top-level port list: the 32-bit AXI4 master (AR/R/AW/W/B), the 32-bit AXI4-Lite slave, the interrupt output, and ACLK/ARESETn. Decide how much AXI concurrency the master uses.

**Feeds:** Interface · **Depends on:** S1

**Spec evidence:**
- [P3] "Must use AXI4 bursts for performance. Our interconnect is AXI4, 32-bit data, 32-bit"
- [P3] "Channels share the one AXI master port."
- [P4] "Programmed through an AXI4-Lite slave port (32-bit)."
- [P3] "a start bit. Hardware copies the data and raises an interrupt when done."

**Decisions:**
- D10 AXI master outstanding transactions and IDs: **At most one outstanding burst at a time: a read burst, then its write burst. A single fixed ARID/AWID is used. Burst type is INCR, size is 4 bytes, and cache/prot/lock/qos are tied to constants.** (default, medium impact, high confidence)
  - options: One outstanding burst at a time (read then write), single fixed AXI ID / Multiple outstanding bursts with per-channel AXI IDs and reorder handling
  - The non-overlapped v1 datapath confirmed in Q2 never needs more than one burst in flight. Out-of-order response tracking is avoided and error attribution to a channel is trivial. Multiple outstanding transactions belong with the v2 overlap work.
- D11 Interrupt output structure: **A single active-high level interrupt. It is asserted while any bit in (global INT_STATUS & INT_ENABLE) is set; the status bits are write-1-to-clear.** (default, low impact, high confidence)
  - options: Single level-sensitive irq = OR(global status & enable) / One irq line per channel / Pulse/edge interrupt
  - The spec mentions one global interrupt status/enable register, which implies one aggregated line. Level interrupts are the SoC norm.

**Done when:**
- Every AXI4 master and AXI4-Lite slave signal is listed with direction, width and the tie-off value if unused (AxCACHE, AxPROT, AxLOCK, AxQOS, etc.).
- AxSIZE=2 (4 bytes), AxBURST=INCR and the ID policy are stated.
- The interrupt port polarity and level/pulse behavior are stated.

## S3. Parameterize channel count and MAX_BURST (16-beat default for the DDR controller)

**Goal:** Define the configuration parameters, especially MAX_BURST. It sizes the 16-word burst buffer and the beat counters, and is the hook for the v2 2×MAX_BURST FIFO.

**Feeds:** Parameters · **Depends on:** S1

**Spec evidence:**
- [P6] "Max burst length? (Interconnect supports up to 256 beats but the DDR controller likes 16.)"
- [P3] "Memory-to-memory copy engine with 4 independent channels."

**Decisions:**
- D2 Maximum burst length: **Compile-time parameter MAX_BURST (power of two, 1..256), default 16. Hardware issues shorter bursts at the end of a transfer and at 4 KB boundaries.** (default, medium impact, high confidence)
  - options: Compile-time parameter, default 16 beats / Fixed 256 beats / Software-programmable per channel up to a compile-time max
  - 16 beats suits the DDR controller. The Q2 answer already assumes a 16-word buffer and refers to MAX_BURST as a sizing parameter. A parameter keeps the 256-beat option open without redesign.

**Done when:**
- The parameter table lists NUM_CHANNELS (4), MAX_BURST (default 16), ADDR_W=32, DATA_W=32 and the LEN register width, each with legal range and default.
- Every buffer depth and counter width in later sections is expressed in terms of these parameters.

## S4. Lay out the AXI4-Lite register map: per-channel SRC/DST/LEN/CTRL/STATUS with ERR_CODE, global INT, progress

**Goal:** Define every register, its field layout, access type and side effects. Include the ERR_CODE encoding (3 = configuration error), how software observes progress, and how start/stop/clear work.

**Feeds:** Interface, Control Logic · **Depends on:** S1, S2

**Spec evidence:**
- [P4] "Per channel: SRC, DST, LEN (bytes), CTRL, STATUS. A global interrupt status / enable"
- [P4] "Software should be able to see progress somehow (TBD)."
- [P4] "Need a way to stop a running channel (TBD how graceful)."

**Decisions:**
- D7 Progress visibility mechanism: **Add a read-only per-channel REMAINING register, updated after each write burst completes (BRESP). SRC, DST and LEN keep the values software programmed.** (default, low impact, medium confidence)
  - options: Read-only per-channel REMAINING (bytes left) register / Live SRC/DST registers that advance during the transfer / Bytes-transferred counter
  - Software can re-read its programmed values. REMAINING gives exact progress consistent with data actually written, which also helps diagnose errors and aborts.

**Done when:**
- The address map gives offsets for all 4 channel register blocks and the global INT_STATUS/INT_ENABLE registers.
- CTRL fields are defined: START (self-clearing), STOP/ABORT, and the per-channel interrupt enable if any.
- STATUS fields are defined: BUSY, DONE, ERR, ERR_CODE (with 3 = configuration error and distinct codes for read-response and write-response errors), ABORTED.
- The behavior of writes to SRC/DST/LEN/START while a channel is BUSY is specified (for example, ignored).
- AXI4-Lite response behavior for unmapped addresses is specified.

## S5. Burst splitter: per-burst length from remaining bytes, MAX_BURST and 4 KB boundaries on both src and dst

**Goal:** Define the address-generation datapath that carves a channel's word-aligned transfer into AXI bursts that never cross 4 KB on either the read side or the write side.

**Feeds:** Datapath · **Depends on:** S3, S4

**Spec evidence:**
- [P3] "Bursts must never cross a 4 KB boundary (AXI rule)."
- [P3] "(round-robin). One channel must not be able to hog the bus during a huge transfer."

**Done when:**
- The burst beat count is defined as min(remaining_words, MAX_BURST, words to the next 4 KB boundary of src, words to the next 4 KB boundary of dst).
- It is stated that one read burst and its matching write burst use the same beat count.
- Per-channel current-src, current-dst and remaining registers, and how they advance after each burst, are described.
- A worked example is included: a transfer whose src and dst have different 4 KB offsets.

## S6. 16-word shared buffer and store-and-forward copy datapath (no read/write overlap)

**Goal:** Describe how read data reaches the write channel through the shared MAX_BURST-deep buffer. Each burst is read completely before its write burst starts, as confirmed for v1.

**Feeds:** Datapath, Block Diagram · **Depends on:** S3, S5

**Spec evidence:**
- [P6] "Read/write overlap: nice to have, not required for v1."
- [P3] "Must use AXI4 bursts for performance."

**Decisions:**
- D3 Read/write overlap: **No overlap for v1. Each burst is read completely into the 16-word buffer before its write burst starts, giving about 41% of port peak (~1.64 B/cycle for 16-beat bursts). Overlap using a 2×MAX_BURST FIFO, with the next AR issued while the current W streams, is deferred to v2.** (decided)
  - options: No overlap: complete a full read burst into the buffer, then issue the write burst / Overlapped: next read burst issued while the current write burst drains (2×MAX_BURST FIFO) / Cut-through: write starts as soon as read data arrives
  - User answer Q2 confirmed this. Store-and-forward also means a read error is known before any write is issued.
- D5 Buffer organization: **One shared MAX_BURST-deep x 32-bit buffer (16 words by default), owned by the currently granted channel for one read+write burst pair.** (default, medium impact, high confidence)
  - options: Single shared MAX_BURST x 32 buffer used by whichever channel holds the grant / Per-channel FIFOs
  - With burst-pair arbitration only one channel moves data at a time. Per-channel buffers would cost 4x the storage for no throughput gain. The Q2 answer refers to a single 16-word buffer.

**Done when:**
- The block diagram shows the register file, 4 channel contexts, arbiter, burst splitter, shared buffer, AXI read engine, AXI write engine and interrupt logic.
- Buffer depth and width are given, along with the mapping of read data to WDATA, WSTRB (all-ones) and WLAST.
- The buffer write side is driven by the R channel and the read side by the W channel, with explicit ownership rules.
- The v2 extension point (2×MAX_BURST FIFO, early AR issue) is noted, without being implemented.

## S7. Round-robin arbitration at burst-pair granularity and per-channel state machines

**Goal:** Define how active channels share the single master port fairly. Define each channel's FSM (IDLE, CHECK, WAIT_GRANT, RD, WR, DONE/ERR) and the engine-level FSM.

**Feeds:** Control Logic · **Depends on:** S5, S6

**Spec evidence:**
- [P3] "Channels share the one AXI master port. Arbitrate between active channels fairly"
- [P3] "(round-robin). One channel must not be able to hog the bus during a huge transfer."
- [P5] "Other channels should keep going."

**Decisions:**
- D4 Arbitration granularity: **Round-robin re-arbitration after every completed read+write burst pair. The pointer advances past the winner, and only BUSY channels with no error are eligible.** (default, medium impact, high confidence)
  - options: Re-arbitrate after every read+write burst pair (round-robin pointer advances past winner) / Re-arbitrate after N bursts or a byte quota / Re-arbitrate only at transfer completion
  - The spec requires round-robin and no hogging. Per-burst switching bounds any channel's wait to (NUM_CHANNELS-1) burst pairs and maps naturally onto the shared-buffer, non-overlapped datapath.

**Done when:**
- The channel FSM states and transitions are drawn or tabled, including the START-time configuration check: a misaligned config goes straight to ERR (ERR_CODE 3) without entering BUSY or requesting the bus.
- The engine FSM (ARB -> AR -> R beats -> AW/W -> B -> update -> ARB) is specified.
- The worst-case wait for a channel is stated in burst pairs.
- How DONE is set and REMAINING updated after the final burst is defined.

## S8. Stop/abort semantics, AXI error (SLVERR/DECERR) and ERR_CODE 3 misconfiguration handling

**Goal:** Define exactly what happens on software stop, on a read or write error response, and on bad programming, while keeping the AXI protocol legal and other channels running.

**Feeds:** Corner Cases & Error Handling, Control Logic · **Depends on:** S4, S7

**Spec evidence:**
- [P5] "If the interconnect returns SLVERR/DECERR on a read or write, stop that channel, flag an"
- [P5] "error, and interrupt. Other channels should keep going."
- [P5] "Misconfiguration (e.g. bad alignment): flag an error rather than doing something weird."
- [P4] "Need a way to stop a running channel (TBD how graceful)."

**Decisions:**
- D6 Stop (abort) behavior: **Graceful at the burst boundary. A channel waiting for grant stops immediately. A channel in flight completes its current burst pair. The channel then clears BUSY, sets ABORTED, leaves REMAINING valid and raises its interrupt. No resume in v1.** (default, medium impact, medium confidence)
  - options: Graceful at burst boundary: finish the in-flight read+write burst pair, then halt with ABORTED status and interrupt / Immediate: drop the channel mid-burst (still completing AXI handshakes, discarding data) / Pause/resume capability
  - AXI forbids abandoning issued bursts. Finishing the pair keeps memory consistent with REMAINING, and latency is bounded to one burst pair.
- D8 AXI error response handling: **On RRESP SLVERR/DECERR on any beat, accept all beats through RLAST, issue no write burst, and mark the channel ERR with the read-error code. On BRESP error, mark the channel ERR with the write-error code. In both cases latch the faulting burst address, raise the interrupt and return the engine to arbitration for the other channels.** (decided)
  - options: Read error: accept the remaining beats until RLAST, skip the write, stop the channel. Write error: stop the channel after BRESP. / Continue the transfer and only log the error
  - The spec requires stopping only the faulty channel, flagging, interrupting and letting the others continue. Store-and-forward (D3) lets the write be skipped after a read error.

**Done when:**
- The config checks performed at START are listed: alignment of SRC/DST/LEN (ERR_CODE 3, never BUSY, no bus traffic), the LEN==0 policy, and any address wrap past 0xFFFFFFFF; each maps to an ERR_CODE.
- Behavior for START on an already BUSY channel and for STOP on an idle channel is defined.
- The read-error and write-error sequences are written step by step and show that AXI handshakes always complete.
- Abort latency is bounded and stated.
- How ERR/DONE/ABORTED are cleared and how a channel is restarted after an error is specified.

## S9. Throughput, latency and AXI handshake timing for the non-overlapped engine (~41% of peak)

**Goal:** Quantify the cycle-level behavior: cycles per burst pair, effective bandwidth consistent with the confirmed ~1.64 B/cycle at 16 beats, arbitration overhead and register-to-AXI latency. Identify registered vs combinational outputs.

**Feeds:** Timing & Pipeline · **Depends on:** S6, S7

**Spec evidence:**
- [P3] "Must use AXI4 bursts for performance."
- [P6] "Read/write overlap: nice to have, not required for v1."

**Done when:**
- A cycle timeline for one 16-beat burst pair from grant to B response is given, with the assumed slave latencies stated, and it reproduces roughly 39 cycles per 64 bytes (~1.64 B/cycle, ~41% of 4 B/cycle).
- Bandwidth for shorter bursts (4 KB splits, transfer tails) is discussed.
- All AXI master outputs are stated to be registered (or exceptions justified), with VALID never depending combinationally on READY.
- START-to-first-ARVALID latency and last-BRESP-to-interrupt latency are stated.

## S10. Single ACLK domain and ARESETn reset behavior

**Goal:** Document that everything runs on ACLK. Define reset style and reset values, including AXI VALID outputs low during reset.

**Feeds:** Clocking & Reset · **Depends on:** S2

**Spec evidence:**
- [P6] "Single clock with the interconnect (ACLK); reset is ARESETn."

**Decisions:**
- D9 Clock domains and reset: **A single ACLK domain for both AXI ports and all logic, with no CDC. ARESETn is active low; all control state resets to idle and all AXI VALID outputs are driven low in reset.** (decided)
  - options: Single ACLK domain, ARESETn active-low, no CDC / Separate register-port clock with CDC
  - The spec states a single clock with the interconnect and ARESETn.

**Done when:**
- It is stated that there is no CDC.
- Reset values are listed for every register-map field, the channel FSMs, the arbiter pointer and AXI outputs.
- The sync vs async reset implementation choice and the AXI requirement that VALIDs stay low until after reset deassertion are documented.

## S11. Verification plan: AXI VIP-based multi-channel copy, 4 KB, fairness, ERR_CODE 3 and error-injection tests

**Goal:** Define the testbench architecture, checkers, assertions and directed/random tests that prove correct copies, burst splitting, fairness, config rejection and error isolation.

**Feeds:** Verification Plan · **Depends on:** S5, S7, S8, S9

**Spec evidence:**
- [P3] "Bursts must never cross a 4 KB boundary (AXI rule)."
- [P3] "One channel must not be able to hog the bus during a huge transfer."
- [P5] "Other channels should keep going."

**Done when:**
- The testbench is described: AXI4-Lite master driver, AXI4 slave memory model with configurable latency and error injection, scoreboard comparing dst memory to src.
- Assertions are listed: no burst crosses 4 KB; AxLEN+1 <= MAX_BURST; AXI handshake stability; WLAST on the correct beat; no AW issued before the matching read burst completes; one outstanding burst at a time; no AR from a channel rejected with ERR_CODE 3.
- Directed tests are listed: LEN = 4 bytes, LEN not a multiple of the burst size, transfers straddling 4 KB with different src/dst offsets, each of SRC/DST/LEN misaligned (expect ERR_CODE 3, no bus traffic), LEN==0, stop mid-transfer, SLVERR/DECERR on read and on write with other channels active.
- A fairness test is included: 1 huge and 3 small transfers, checking the max grant wait.
- A bandwidth check against the S9 figure is included.
- Coverage goals are listed: all channel FSM states and transitions, all ERR_CODEs, all 4 channels concurrently active.

## S12. Record v1 assumptions, confirmed answers and remaining open questions for SoC integration

**Goal:** Collect the confirmed decisions (word alignment, no overlap) and every remaining defaulted decision (burst length, progress, stop semantics, outstanding transactions, interrupt structure, arbitration quota, buffer organization) so the kickoff owners can confirm them.

**Feeds:** Assumptions & Open Questions · **Depends on:** S1, S2, S3, S4, S6, S7, S8

**Spec evidence:**
- [P2] "Status: incomplete, please fill in the gaps in the uArch."
- [P4] "Software should be able to see progress somehow (TBD)."
- [P4] "Need a way to stop a running channel (TBD how graceful)."

**Done when:**
- The confirmed answers (Q1 alignment / ERR_CODE 3; Q2 no overlap / ~41% peak) are recorded as resolved.
- Each remaining defaulted decision is listed with its chosen default and the question to the owner.
- Assumptions about the slave/interconnect are listed: in-order responses for a single ID, no exclusive access, and src/dst regions non-overlapping (overlap undefined).
- Future extensions are noted with hooks: read/write overlap with a 2×MAX_BURST FIFO, byte-granular copies, scatter-gather.

## Assumptions (defaults not confirmed by the user)

- D10 AXI master outstanding transactions and IDs: At most one outstanding burst at a time: a read burst, then its write burst. A single fixed ARID/AWID is used. Burst type is INCR, size is 4 bytes, and cache/prot/lock/qos are tied to constants. (medium impact, high confidence)
- D11 Interrupt output structure: A single active-high level interrupt. It is asserted while any bit in (global INT_STATUS & INT_ENABLE) is set; the status bits are write-1-to-clear. (low impact, high confidence)
- D2 Maximum burst length: Compile-time parameter MAX_BURST (power of two, 1..256), default 16. Hardware issues shorter bursts at the end of a transfer and at 4 KB boundaries. (medium impact, high confidence)
- D7 Progress visibility mechanism: Add a read-only per-channel REMAINING register, updated after each write burst completes (BRESP). SRC, DST and LEN keep the values software programmed. (low impact, medium confidence)
- D5 Buffer organization: One shared MAX_BURST-deep x 32-bit buffer (16 words by default), owned by the currently granted channel for one read+write burst pair. (medium impact, high confidence)
- D4 Arbitration granularity: Round-robin re-arbitration after every completed read+write burst pair. The pointer advances past the winner, and only BUSY channels with no error are eligible. (medium impact, high confidence)
- D6 Stop (abort) behavior: Graceful at the burst boundary. A channel waiting for grant stops immediately. A channel in flight completes its current burst pair. The channel then clears BUSY, sets ABORTED, leaves REMAINING valid and raises its interrupt. No resume in v1. (medium impact, medium confidence)
