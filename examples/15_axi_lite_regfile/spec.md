# `ctrl_regs` – AXI4-Lite register block

Bus: AXI4-Lite slave, 32-bit data, 4 KB window (12-bit address). Clock `aclk`, reset `aresetn`.
Unmapped addresses → SLVERR. Reserved bits read 0, writes ignored. WSTRB must be honoured.

| Offset | Name | Access | Bits | Reset | Description |
|--------|------|--------|------|-------|-------------|
| 0x000 | CTRL | RW | [0] EN | 0 | Core enable |
| | | | [3:1] MODE | 0 | Operating mode |
| | | | [15:8] PRESCALE | 0x01 | Clock prescaler |
| 0x004 | STATUS | RO | [0] BUSY | – | Live core status |
| | | | [1] FIFO_EMPTY | – | |
| | | | [2] FIFO_FULL | – | |
| | | | [15:8] FIFO_LEVEL | – | |
| 0x008 | INT_STATUS | W1C | [0] DONE, [1] ERR, [2] OVF, [3] UNF | 0 | Set by hardware event pulses, write 1 to clear |
| 0x00C | INT_ENABLE | RW | [3:0] | 0 | Interrupt mask; `irq = |(INT_STATUS & INT_ENABLE)` |
| 0x010 | CMD | WO, SC | [0] START, [1] ABORT, [31] SOFT_RST | 0 | Writing 1 produces a one-cycle pulse to the core; reads as 0 |
| 0x014 | SCRATCH | RW | [31:0] | 0 | Software scratch |
| 0x018 | VERSION | RO | [31:0] | param | IP version |

Notes:
- The AW and W channels may arrive in any order or together; don't assume they're aligned.
- Low-performance control path; simplicity over throughput.
- Hardware event pulses must never be lost, even if software is clearing at the same time.
