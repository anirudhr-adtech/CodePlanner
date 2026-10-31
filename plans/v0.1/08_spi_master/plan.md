# MA plan: 08_spi_master

## S1. Scope the SPI master: one-word full-duplex engine with 4 CS lines and a 5-register programmer's model

**Goal:** Write the Overview. State that the block is a single-word, register-driven SPI master with no FIFO. It supports modes 0-3, 8/16/32-bit words, 4 active-low chip selects, an optional CS hold for multi-word flash commands, and a done interrupt. Also state the non-goals: no DMA, no slave mode, no multi-master.

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P2] "General-purpose SPI master for flash, ADCs and sensors on the SoC peripheral bus."
- [P3] "Full duplex: every transfer shifts out TXDATA and shifts in RXDATA."
- [P3] "Optional "hold CS" so multi-word flash commands can stay in one CS window."

**Decisions:**
- D1 TX buffering depth and the effect of a TXDATA write while BUSY: **Single shift register with no buffer. A TXDATA write while BUSY (with EN=1) is discarded and sets STATUS.TX_OVR. The in-flight transfer is unaffected.** (default, medium impact, medium confidence)
  - options: Single shift register, no buffer; a write while busy is dropped and sets TX_OVR / One-entry holding register that queues the next word; TX_OVR only when the holding register is also full / Write while busy overwrites the in-flight word
  - The spec defines TX_OVR purely as 'written while busy' and has no TX-empty flag, which implies there is no queue. Drop-and-flag is the simplest consistent reading.

**Done when:**
- The Overview lists every P3 feature with a one-line description of how it is realised.
- An explicit non-goals list exists: no FIFO, no slave mode, no DMA.
- The TX buffering policy from D1 and the 'EN only gates start' semantics from D11 are stated in the Overview.

## S2. Define the register bus port, SPI pins and the CTRL/CLKDIV/TXDATA/RXDATA/STATUS register file

**Goal:** Write the Interface section. Give the full port list: clk, rst_n, addr[4:0], wdata, we, re, rdata, sclk, mosi, miso, cs_n[3:0], irq. Specify read timing, address decode, access types, W1C semantics, and write side effects: a TXDATA write starts a transfer only when EN=1 and the engine is not BUSY, and clearing CS_HOLD while idle-held releases CS. Also specify reserved-bit behaviour.

**Feeds:** Interface · **Depends on:** S1

**Spec evidence:**
- [P4] "32-bit simple register bus: `addr[4:0]`, `wdata[31:0]`, `we`, `re`, `rdata[31:0]`."
- [P4] "return data one cycle after `re`. No wait states."
- [P6] "Writing starts a transfer. Data is right-aligned."
- [P6] "[0] BUSY (RO), [1] DONE (W1C), [2] TX_OVR (W1C)"

**Decisions:**
- D2 Read data path timing: **rdata is registered. It is decoded on the cycle re is high and presented the next cycle, with no wait states. Reads have no side effects.** (decided)
  - options: Registered rdata captured on the cycle re is high, valid the following cycle / Combinational rdata
  - P4 explicitly requires read data one cycle after re with no wait states.
- D3 When CTRL and CLKDIV fields take effect relative to a transfer: **Snapshot CPOL, CPHA, LSB_FIRST, SIZE, CS_SEL and DIV into engine-local registers when a transfer starts. CS_HOLD stays live: it is sampled at the end of LAG and also while idle-held, per the Q1 answer. EN stays live as a start gate only, per the Q2 answer.** (default, medium impact, medium confidence)
  - options: Snapshot CPOL/CPHA/LSB_FIRST/SIZE/CS_SEL/DIV at the TXDATA write; later CTRL writes affect only the next transfer / Live fields used directly by the engine during the transfer
  - 'Chip select used by the next transfer' implies configuration binds at transfer start. Snapshotting avoids glitching SCLK, CS or the shift order when software writes mid-transfer. The CS_HOLD and EN live behaviour is fixed by the user's answers.

**Done when:**
- The port table gives direction, width and description for every bus pin and SPI pin.
- Address decode covers 0x00 to 0x10. Reads of unmapped offsets and of the WO TXDATA register return a documented value, e.g. 0.
- Write behaviour is specified per register: W1C bits, read-only BUSY, a TXDATA write ignored when EN=0, and the CTRL write that clears CS_HOLD triggering CS release.
- Reserved CTRL bits are documented as read-as-zero or as stored.

## S3. Fix parameters: DIV width 16, 4 chip selects, 32-bit max word

**Goal:** Write the Parameters section. Decide which spec constants become RTL parameters (e.g. NUM_CS=4, DIV_W=16, MAX_BITS=32) and which stay fixed by the programmer's model.

**Feeds:** Parameters · **Depends on:** S2

**Spec evidence:**
- [P3] "SCLK = f_clk / (2 × (DIV + 1)). DIV is 16 bits."
- [P3] "Up to 4 chip selects, active low; only one active at a time."
- [P3] "Transfer size 8, 16 or 32 bits; MSB-first or LSB-first."

**Done when:**
- The parameter table lists name, default, legal range and the register fields each parameter affects.
- Parameters that would break the register map are flagged as fixed or constrained. Example: NUM_CS>4 overflows CS_SEL[9:8].

## S4. Design the SCLK divider as clock-enable ticks in the system clock domain

**Goal:** Specify the divider counter that produces a half-period tick every DIV+1 system clocks. Show how SCLK toggles, how CPOL sets the idle level, and how leading and trailing edges are labelled for shift and sample. Confirm that DIV=0 gives f_clk/2 (50 MHz at 100 MHz), which meets the 25 MHz requirement.

**Feeds:** Block Diagram, Datapath, Timing & Pipeline · **Depends on:** S3

**Spec evidence:**
- [P3] "SCLK = f_clk / (2 × (DIV + 1)). DIV is 16 bits."
- [P7] "Up to 25 MHz SCLK with a 100 MHz system clock is required. Faster is a bonus."
- [P6] "Idle level of SCLK."

**Decisions:**
- D4 SCLK generation method: **Use a single system clock domain. A 16-bit down-counter produces a tick every DIV+1 cycles, and the SCLK flop toggles on ticks during SHIFT. There are no derived clocks.** (default, high impact, high confidence)
  - options: SCLK is a registered output toggled on divider ticks; all logic stays on the system clock / SCLK as a separate divided clock domain driving the shift register
  - This is industry standard for peripheral SPI masters. It avoids CDC and clock-tree work and hits f_clk/2 exactly at DIV=0.

**Done when:**
- Divider behaviour for DIV=0, 1 and 0xFFFF is described with the resulting SCLK frequencies.
- Tick generation is shown to give exactly 50% duty for every DIV.
- The leading and trailing edge mapping for CPOL=0/1 is tabulated.
- The same tick counter is shown to time the LEAD, LAG and GAP phases.

## S5. Specify the shift datapath for modes 0-3, 8/16/32-bit sizes, MSB/LSB order and right-aligned data

**Goal:** Define the TX shift register and RX capture register. Specify how a right-aligned TXDATA word of SIZE bits is serialised MSB-first or LSB-first. Specify how received bits are assembled right-aligned into RXDATA, including zeroing the upper bits for 8/16-bit words. Specify when MOSI changes and when MISO is sampled for CPHA=0 and CPHA=1, including first-bit setup for CPHA=0 during LEAD.

**Feeds:** Datapath, Block Diagram · **Depends on:** S4

**Spec evidence:**
- [P6] "0 = sample on leading edge, 1 = sample on trailing edge."
- [P6] "Last received word, right-aligned."
- [P6] "00 = 8 bit, 01 = 16 bit, 10 = 32 bit, 11 = reserved."
- [P3] "Supports SPI modes 0–3 (CPOL/CPHA)."

**Decisions:**
- D5 MISO capture path: **Capture MISO directly in the system clock domain on the sampling tick, treating it as synchronous to our generated SCLK. The MA documents the round-trip timing budget at DIV=0 and DIV=1.** (default, medium impact, medium confidence)
  - options: Sample MISO directly into the RX shift register on the sample tick (single flop, no synchroniser) / 2-flop synchroniser with compensated (delayed) sampling point / Sample one system clock later than the nominal edge to absorb round-trip delay
  - MISO is launched by the slave from our own SCLK, so it is not truly asynchronous. A 2-flop synchroniser adds 2 cycles of latency, which breaks the half-period window at 50 MHz.
- D6 Behaviour for SIZE=11 (reserved): **Treat SIZE=11 as 32-bit.** (default, low impact, low confidence)
  - options: Treat as 32-bit / Treat as 8-bit / Ignore the TXDATA write (no transfer)
  - This is benign and deterministic. It needs no extra error flag and never truncates data.

**Done when:**
- A bit-index table exists for every SIZE × LSB_FIRST combination, for both TX and RX.
- MOSI launch and MISO sample edges are tabulated for all 4 modes, including where bit 0 is presented before the first SCLK edge when CPHA=0.
- The RXDATA update instant and the zeroing of upper bits for 8/16-bit words are specified.

## S6. Build the transfer sequencer FSM (IDLE/LEAD/SHIFT/LAG/GAP plus HELD) with live CS_HOLD and CS switch-over

**Goal:** Define the control FSM: IDLE → LEAD (≥ half SCLK) → SHIFT (2×N half-periods) → LAG (≥ half SCLK). At the end of LAG, CS_HOLD is sampled live. If CS_HOLD=1, the FSM parks in HELD with CS low and BUSY low. If CS_HOLD=0, CS de-asserts → GAP (≥ half SCLK high) → IDLE. While parked in HELD: clearing CS_HOLD de-asserts all CS on the next cycle (cs_held<=0), with no LAG or GAP phase and BUSY staying low. A new transfer to the same CS continues the window. A new transfer to a different CS releases the old CS and asserts the new one in the same cycle, with no CS-high gap, then runs LEAD. EN gates only the IDLE/HELD → LEAD start. Generate cs_n one-hot-low from the snapshotted CS_SEL.

**Feeds:** Control Logic, Block Diagram · **Depends on:** S4, S5

**Spec evidence:**
- [P7] "At least half an SCLK period from CS assertion to the first SCLK edge, and from the last"
- [P7] "At least half an SCLK period of CS high between transfers."
- [P6] "Keep CS asserted after the transfer."
- [P3] "Up to 4 chip selects, active low; only one active at a time."

**Decisions:**
- D7 How a held CS is released and how CS_SEL changes while held are handled: **Both release methods work. Clearing CS_HOLD while idle with CS held de-asserts all CS on the next cycle (cs_held<=0). There is no extra hold or guard phase, and BUSY stays low. CS_HOLD is read live at the end of LAG, so clearing it during the last transfer of a burst releases CS automatically. A new transfer selecting a different CS while one is held releases the old CS and asserts the new one in the same cycle, with no CS-high gap between different devices.** (decided)
  - options: Clearing CTRL.CS_HOLD while idle with CS held starts a CS deassert (with the guard time) without a transfer / CS stays held until the next transfer completes with CS_HOLD=0; clearing the bit alone does nothing / Both: clearing CS_HOLD while idle-held de-asserts CS next cycle with no guard; CS_HOLD read live at end of LAG; a different CS_SEL swaps CS in the same cycle
  - This is the user's answer to Q1.
- D8 Coverage of BUSY and DONE relative to the LAG and GAP phases: **BUSY covers the period from the TXDATA write until the engine reaches IDLE (after GAP) or HELD (after LAG). DONE and RXDATA are updated at that point. A release by clearing CS_HOLD while held has no GAP, per Q1. The MA flags that an immediate same-CS transfer after such a release may give a CS-high time shorter than half an SCLK period.** (default, medium impact, medium confidence)
  - options: BUSY stays high through LAG and the inter-transfer CS-high GAP; DONE set when the engine returns to IDLE (or parks in HELD) / BUSY drops and DONE is set at the last SCLK edge; the guard is enforced by delaying the start of the next transfer internally
  - This guarantees the P7 timing by construction for normal transfers without an internal queue, which is consistent with D1. The cost is up to one extra SCLK period of latency per word.

**Done when:**
- The FSM state diagram has every transition condition, including EN (start gate only), live CS_HOLD at the end of LAG, CS_HOLD cleared while HELD, and same versus different CS_SEL from HELD.
- Each phase duration is expressed in divider ticks and shown to be ≥ half an SCLK period for all DIV.
- An argument shows that at most one cs_n is low in every state and cycle, including the same-cycle CS swap.
- The block diagram shows the register file, divider, FSM, TX/RX shifters, cs_held/cs_n logic and IRQ logic with their connections.

## S7. Define STATUS flag set/clear priority and the done interrupt

**Goal:** Specify BUSY, DONE and TX_OVR: their set conditions, W1C clearing, and priority when a set and a W1C happen in the same cycle. TX_OVR is set only for a TXDATA write while BUSY with EN=1; writes while EN=0 set nothing. Specify the irq output and its relationship to IRQ_EN and DONE.

**Feeds:** Control Logic, Interface · **Depends on:** S2, S6

**Spec evidence:**
- [P6] "TX_OVR = TXDATA written while busy."
- [P3] "Interrupt on transfer done."
- [P6] "Interrupt enable."

**Decisions:**
- D9 Interrupt signalling type: **A registered, level-sensitive irq = STATUS.DONE & CTRL.IRQ_EN. Software clears it by writing 1 to DONE. TX_OVR does not raise the interrupt.** (default, low impact, high confidence)
  - options: Level irq = DONE & IRQ_EN, cleared by W1C of DONE / Single-cycle pulse on transfer completion / Level, also asserted on TX_OVR
  - This is the standard sticky-status plus enable pattern for SoC peripherals, and the spec names only transfer done as the interrupt source.

**Done when:**
- A set/clear truth table covers each STATUS bit, including a hardware set and a software W1C in the same cycle, with the winner stated.
- The irq equation and its register stage are specified.
- TXDATA writes are specified for each case: while BUSY with EN=1 (TX_OVR set, data dropped), while EN=0 (ignored, no flag), and while EN=0 during a finishing transfer (ignored, no flag).

## S8. Produce cycle-level timing for transfers at DIV=0 and DIV=1, including back-to-back, held-CS and CS-swap sequences

**Goal:** Write the Timing & Pipeline section. Give the latency from the TXDATA write to CS assertion, to the first SCLK edge, to the last edge, to DONE/RXDATA valid, and to readiness for the next write. Compute throughput at 25 MHz and 50 MHz. Show the held-CS continuation, the same-cycle CS swap followed by LEAD, and release by clearing CS_HOLD. Check the MISO sample window against D5.

**Feeds:** Timing & Pipeline · **Depends on:** S6, S7

**Spec evidence:**
- [P7] "Up to 25 MHz SCLK with a 100 MHz system clock is required. Faster is a bonus."
- [P7] "At least half an SCLK period of CS high between transfers."
- [P4] "return data one cycle after `re`. No wait states."

**Done when:**
- Waveforms or tables cover mode 0 and mode 3 8-bit transfers at DIV=1 (25 MHz), showing clk, cs_n, sclk, mosi, miso sample points, BUSY and DONE.
- Total cycles per transfer are given as a formula in DIV and SIZE, for both the CS_HOLD=0 path (LEAD+SHIFT+LAG+GAP) and the held path.
- A waveform shows the CS_HOLD release-by-clear timing (cs_n high on the next cycle) and the same-cycle CS swap.
- The MISO timing budget at DIV=0 is stated, with assumptions about pad and slave delay.

## S9. Define the single clock domain, reset style, output idle values and EN start-gate semantics

**Goal:** Write the Clocking & Reset section. Specify one system clock and the reset polarity and type. Give reset values for all registers and SPI outputs: cs_n all high, sclk at the CPOL reset value, mosi defined. Document that EN only gates the start of new transfers and never aborts one in flight.

**Feeds:** Clocking & Reset · **Depends on:** S6

**Spec evidence:**
- [P6] "Block enable."
- [P6] "Idle level of SCLK."
- [P7] "Up to 25 MHz SCLK with a 100 MHz system clock is required."

**Decisions:**
- D10 Reset style: **Active-low rst_n with asynchronous assertion and synchronous deassertion provided externally. All control, status and SPI output flops are reset, so cs_n goes high immediately on reset.** (default, low impact, medium confidence)
  - options: Asynchronous assert, synchronous deassert, active-low rst_n / Fully synchronous active-high reset
  - Asynchronous reset guarantees chip selects are inactive even before the clock runs, which protects attached flash. The spec does not name a reset.
- D11 Effect of clearing CTRL.EN: **No abort. EN only gates the start of a transfer. Clearing EN mid-transfer lets the current transfer finish normally, including LAG, CS release or hold, and DONE. TXDATA writes while EN=0 are ignored and set no flag; TX_OVR is not set.** (decided)
  - options: Immediate abort: FSM to IDLE, CS deasserted, no DONE / Graceful: the current word finishes, then the block idles / EN only gates new transfers
  - This is the user's answer to Q2.

**Done when:**
- The reset value table covers every register field and the cs_n, sclk and mosi outputs.
- EN appears in the FSM from S6 only as a start-gate term; no abort path exists.
- The section states that there is no clock-domain crossing, apart from the MISO input assumption from D5.
- The section states SCLK idle-level behaviour when CPOL is written while idle or idle-held.

## S10. Enumerate corner cases: writes while busy or disabled, held-CS release and swap, mid-transfer config writes, DIV extremes, reserved SIZE

**Goal:** Write Corner Cases & Error Handling. List each hazardous scenario with its defined behaviour, tied to the decisions above, including the consequences of the Q1 and Q2 answers.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S5, S6, S7, S9

**Spec evidence:**
- [P6] "TX_OVR = TXDATA written while busy."
- [P6] "Chip select used by the next transfer."
- [P6] "00 = 8 bit, 01 = 16 bit, 10 = 32 bit, 11 = reserved."

**Done when:**
- Each of the following has a stated outcome: TXDATA write while BUSY; TXDATA write while EN=0 (including during a finishing transfer); EN cleared mid-transfer; EN cleared while idle-held (CS stays held until CS_HOLD is cleared); CTRL/CLKDIV write mid-transfer; CS_HOLD cleared during the last transfer of a burst; CS_HOLD cleared while idle-held; different CS_SEL while held (same-cycle swap, no gap); same-CS transfer right after release-by-clear (short CS-high gap per D8); SIZE=11; DIV=0 and DIV=0xFFFF; W1C racing a set; RXDATA read during a transfer; reset during a transfer.

## S11. Plan verification with an SPI slave model across modes, sizes, bit orders, dividers and CS sequences

**Goal:** Write the Verification Plan. Specify a testbench with a bus driver and a behavioural SPI slave/monitor. The monitor checks bit order, sampling edges, CS timing (≥ half SCLK LEAD, LAG and GAP for normal transfers), one-hot CS, and RXDATA. Add directed tests for the corner cases, a functional coverage list, and assertions.

**Feeds:** Verification Plan · **Depends on:** S8, S10

**Spec evidence:**
- [P3] "Supports SPI modes 0–3 (CPOL/CPHA)."
- [P7] "At least half an SCLK period from CS assertion to the first SCLK edge, and from the last"
- [P3] "Up to 4 chip selects, active low; only one active at a time."

**Done when:**
- The coverage cross includes mode × SIZE × LSB_FIRST × CS_SEL × {DIV=0, 1, large} × CS_HOLD × {EN cleared mid-transfer or not}.
- Assertions are listed: $onehot0(~cs_n); minimum LEAD, LAG and GAP in clk cycles derived from DIV; SCLK at its idle level whenever all cs_n are high; BUSY low while HELD; no TX_OVR when EN=0; rdata valid one cycle after re.
- Directed tests exist for each S10 corner case, a multi-word flash read under CS_HOLD, release by clearing CS_HOLD, and a CS swap from the held state.

## S12. Record assumptions and open questions from the defaulted decisions

**Goal:** Write Assumptions & Open Questions. Collect every remaining defaulted decision (D1, D3, D4, D5, D6, D8, D9, D10) with its chosen behaviour and the question for the spec author. Record the resolved Q1 and Q2 answers (D7, D11) as settled assumptions. List spec gaps: no reset given, MISO timing, reserved SIZE, and the possible short CS-high gap after release-by-clear.

**Feeds:** Assumptions & Open Questions · **Depends on:** S1, S2, S4, S5, S6, S7, S9

**Spec evidence:**
- [P1] "SPI Master – Programmer's Model v0.3"
- [P6] "11 = reserved."

**Done when:**
- Each defaulted decision appears with its choice, its impact if wrong, and the open question text.
- The D7 and D11 user answers are recorded as resolved, with their architectural consequences.
- Physical-timing assumptions are stated explicitly: the MISO round trip at 50 MHz SCLK, and the absence of a CS-high gap on a device swap or after a release-by-clear.

## Assumptions (defaults not confirmed by the user)

- D1 TX buffering depth and the effect of a TXDATA write while BUSY: Single shift register with no buffer. A TXDATA write while BUSY (with EN=1) is discarded and sets STATUS.TX_OVR. The in-flight transfer is unaffected. (medium impact, medium confidence)
- D3 When CTRL and CLKDIV fields take effect relative to a transfer: Snapshot CPOL, CPHA, LSB_FIRST, SIZE, CS_SEL and DIV into engine-local registers when a transfer starts. CS_HOLD stays live: it is sampled at the end of LAG and also while idle-held, per the Q1 answer. EN stays live as a start gate only, per the Q2 answer. (medium impact, medium confidence)
- D4 SCLK generation method: Use a single system clock domain. A 16-bit down-counter produces a tick every DIV+1 cycles, and the SCLK flop toggles on ticks during SHIFT. There are no derived clocks. (high impact, high confidence)
- D5 MISO capture path: Capture MISO directly in the system clock domain on the sampling tick, treating it as synchronous to our generated SCLK. The MA documents the round-trip timing budget at DIV=0 and DIV=1. (medium impact, medium confidence)
- D6 Behaviour for SIZE=11 (reserved): Treat SIZE=11 as 32-bit. (low impact, low confidence)
- D8 Coverage of BUSY and DONE relative to the LAG and GAP phases: BUSY covers the period from the TXDATA write until the engine reaches IDLE (after GAP) or HELD (after LAG). DONE and RXDATA are updated at that point. A release by clearing CS_HOLD while held has no GAP, per Q1. The MA flags that an immediate same-CS transfer after such a release may give a CS-high time shorter than half an SCLK period. (medium impact, medium confidence)
- D9 Interrupt signalling type: A registered, level-sensitive irq = STATUS.DONE & CTRL.IRQ_EN. Software clears it by writing 1 to DONE. TX_OVR does not raise the interrupt. (low impact, high confidence)
- D10 Reset style: Active-low rst_n with asynchronous assertion and synchronous deassertion provided externally. All control, status and SPI output flops are reset, so cs_n goes high immediately on reset. (low impact, medium confidence)
