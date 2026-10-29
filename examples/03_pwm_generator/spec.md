# PWM Controller – Programmer's Model (rev 0.3)

Up to 8 independent PWM channels for motor/LED control. Each channel has its own period and
duty. Changes written by software must never produce a truncated or runt pulse: new
values take effect at the next period boundary.

## Bus interface

Simple synchronous register bus, 32-bit, word-aligned:
`reg_wr`, `reg_rd`, `reg_addr[7:0]`, `reg_wdata[31:0]`, `reg_rdata[31:0]`.
Read data is returned one cycle after `reg_rd`. No wait states, no error response.

## Register map

| Offset | Name | Access | Bits | Description |
|--------|------|--------|------|-------------|
| 0x00 | CTRL | RW | [0] GEN | Global enable. 0 = all channels stopped. |
| | | | [31:16] PRESC | Clock prescaler. Counters advance every PRESC+1 clocks. |
| 0x10 + 0x10*n | CHn_CFG | RW | [0] EN | Channel enable. |
| | | | [1] POL | Output polarity. 0 = active-high, 1 = active-low. |
| | | | [2] CENTER | 0 = edge-aligned, 1 = center-aligned. |
| 0x14 + 0x10*n | CHn_PERIOD | RW | [15:0] | Period in counter ticks. |
| 0x18 + 0x10*n | CHn_DUTY | RW | [15:0] | Active time in counter ticks. |
| 0x1C + 0x10*n | CHn_COUNT | RO | [15:0] | Current counter value. |

Reserved bits read as 0. All registers reset to 0.

## Behaviour

- Edge-aligned: output active at start of period, inactive after DUTY ticks.
- Center-aligned: active pulse is centred in the period; period is twice as long as
  edge-aligned for the same PERIOD value (up/down counting).
- DUTY = 0 → output always inactive. DUTY ≥ PERIOD → output always active.
- PERIOD, DUTY and CENTER are double-buffered (shadow registers) and load at the period boundary.
- Disabled channel drives its inactive level.

Clock: `clk` (100 MHz). Reset: `rst_n`, active-low. Outputs: `pwm_out[NUM_CH-1:0]`, must be
glitch-free (registered).
