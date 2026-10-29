# SPI Master – Programmer's Model v0.3

General-purpose SPI master for flash, ADCs and sensors on the SoC peripheral bus.

## Features
- Supports SPI modes 0–3 (CPOL/CPHA).
- SCLK = f_clk / (2 × (DIV + 1)). DIV is 16 bits.
- Up to 4 chip selects, active low; only one active at a time.
- Transfer size 8, 16 or 32 bits; MSB-first or LSB-first.
- Full duplex: every transfer shifts out TXDATA and shifts in RXDATA.
- Optional "hold CS" so multi-word flash commands can stay in one CS window.
- Interrupt on transfer done.

## Bus
32-bit simple register bus: `addr[4:0]`, `wdata[31:0]`, `we`, `re`, `rdata[31:0]`. Reads
return data one cycle after `re`. No wait states.

## Register map

| Offset | Name | Access | Bits | Description |
|--------|------|--------|------|-------------|
| 0x00 | CTRL | RW | [0] EN | Block enable. |
| | | | [1] CPOL | Idle level of SCLK. |
| | | | [2] CPHA | 0 = sample on leading edge, 1 = sample on trailing edge. |
| | | | [3] LSB_FIRST | Bit order. |
| | | | [5:4] SIZE | 00 = 8 bit, 01 = 16 bit, 10 = 32 bit, 11 = reserved. |
| | | | [9:8] CS_SEL | Chip select used by the next transfer. |
| | | | [10] CS_HOLD | Keep CS asserted after the transfer. |
| | | | [16] IRQ_EN | Interrupt enable. |
| 0x04 | CLKDIV | RW | [15:0] DIV | SCLK divider. |
| 0x08 | TXDATA | WO | [31:0] | Writing starts a transfer. Data is right-aligned. |
| 0x0C | RXDATA | RO | [31:0] | Last received word, right-aligned. |
| 0x10 | STATUS | R/W1C | [0] BUSY (RO), [1] DONE (W1C), [2] TX_OVR (W1C) | TX_OVR = TXDATA written while busy. |

## Timing
- At least half an SCLK period from CS assertion to the first SCLK edge, and from the last
  SCLK edge to CS de-assertion.
- At least half an SCLK period of CS high between transfers.
- Up to 25 MHz SCLK with a 100 MHz system clock is required. Faster is a bonus.
