# updown_counter

- N-bit counter, N parameterizable (default 8)
- inputs: en, up (1=count up, 0=count down), load, load_val[N-1:0]
- load has priority over counting
- outputs: count[N-1:0], tc (terminal count)
- tc = 1 when count is at max while counting up, or at 0 while counting down
- parameter MODE: WRAP or SATURATE
  - WRAP: max+1 -> 0, 0-1 -> max
  - SATURATE: stick at max / 0
- sync active-high reset `rst`, single clock `clk`
- registered outputs, no combinational path from inputs to count
- Fmax is not critical; small area preferred
