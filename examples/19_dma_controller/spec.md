# DMA controller — requirements (draft, from kickoff meeting notes)

Owner: SoC integration. Status: incomplete, please fill in the gaps in the uArch.

## What it does
- Memory-to-memory copy engine with 4 independent channels.
- Software programs a channel with source address, destination address and length, then sets
  a start bit. Hardware copies the data and raises an interrupt when done.
- Must use AXI4 bursts for performance. Our interconnect is AXI4, 32-bit data, 32-bit
  addresses. Bursts must never cross a 4 KB boundary (AXI rule).
- Channels share the one AXI master port. Arbitrate between active channels fairly
  (round-robin). One channel must not be able to hog the bus during a huge transfer.

## Registers
- Programmed through an AXI4-Lite slave port (32-bit).
- Per channel: SRC, DST, LEN (bytes), CTRL, STATUS. A global interrupt status / enable
  register as well.
- Software should be able to see progress somehow (TBD).
- Need a way to stop a running channel (TBD how graceful).

## Errors
- If the interconnect returns SLVERR/DECERR on a read or write, stop that channel, flag an
  error, and interrupt. Other channels should keep going.
- Misconfiguration (e.g. bad alignment): flag an error rather than doing something weird.

## Not decided
- Byte-granular transfers vs word-aligned only? (Firmware team would be OK with word-aligned
  for v1.)
- Max burst length? (Interconnect supports up to 256 beats but the DDR controller likes 16.)
- Read/write overlap: nice to have, not required for v1.
- Descriptor chaining / scatter-gather: not for v1.
- Single clock with the interconnect (ACLK); reset is ARESETn.
