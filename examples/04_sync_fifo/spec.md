# Synchronous FIFO – block spec

We need a generic single-clock FIFO to sit between our packet parser and the DMA engine.

Requirements:
- Data width and depth must be configurable. Typical use: 32 bits wide, 16 entries deep.
- Write side: `wr_en` + `wr_data`. Writes when full must be ignored and flagged.
- Read side: `rd_en` → data. We'd like the data to be available on the same cycle `rd_en` is
  asserted if possible (show-ahead / first-word-fall-through) so the DMA doesn't lose a cycle.
- Status outputs: `full`, `empty`, plus `almost_full` with a programmable threshold so the
  parser can stop early. A fill-level count would be nice for debug.
- Simultaneous read and write must work, including when the FIFO is full or empty.
- One clock, active-low reset. Target is an FPGA, but it should port to ASIC too.
- Overflow and underflow should be sticky error flags that software can clear.
