# MA plan: 01_updown_counter

## S1. Scope the parameterizable up/down counter with WRAP/SATURATE modes and terminal-count flag

**Goal:** Write the Overview: an N-bit synchronous up/down counter with parallel load (priority over counting), a compile-time WRAP/SATURATE overflow policy, a tc flag decoded from the registered count and the live up input, and an area-over-speed design goal.

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P1] "# updown_counter"
- [P2] "N-bit counter, N parameterizable (default 8)"
- [P2] "parameter MODE: WRAP or SATURATE"
- [P2] "Fmax is not critical; small area preferred"

**Decisions:**
- D9 Is MODE fixed at elaboration time or selectable at runtime: **Compile-time parameter; only the selected overflow logic is generated** (decided)
  - options: Compile-time parameter / Runtime input pin
  - The spec says 'parameter MODE', and a parameter also saves area.

**Done when:**
- The Overview fits in one paragraph and states the function, the load-over-count priority, both MODE behaviours, the tc purpose and the small-area goal
- The Overview states that MODE is fixed at elaboration
- The Overview states that count is registered and tc is a combinational decode

## S2. Define ports and the N/MODE parameters, including how MODE is encoded

**Goal:** Produce the port table (clk, rst, en, up, load, load_val[N-1:0], count[N-1:0], tc) and the parameter table (N default 8; MODE with its legal values and default).

**Feeds:** Interface, Parameters · **Depends on:** S1

**Spec evidence:**
- [P2] "inputs: en, up (1=count up, 0=count down), load, load_val[N-1:0]"
- [P2] "outputs: count[N-1:0], tc (terminal count)"
- [P2] "N-bit counter, N parameterizable (default 8)"
- [P2] "parameter MODE: WRAP or SATURATE"

**Decisions:**
- D1 MODE parameter representation and default value: **String parameter MODE with legal values "WRAP" and "SATURATE", default "WRAP"** (default, low impact, medium confidence)
  - options: String parameter "WRAP"/"SATURATE", default "WRAP" / Integer parameter with localparams WRAP=0/SATURATE=1, default WRAP / Integer parameter, default SATURATE
  - This matches the spec wording directly and is well supported by Verilog-2001 synthesis tools. WRAP is the conventional counter default.
- D7 Definition of 'max': **max = 2^N-1 (all ones); no separate modulus parameter** (default, medium impact, high confidence)
  - options: Full range 2^N-1 (all ones) / Separate MAX parameter below 2^N-1
  - The spec describes an 'N-bit counter' and mentions no modulus, so full range is implied. The user's tc formula uses MAX without defining it otherwise.

**Done when:**
- Each port has a direction, width, active level and one-line description
- The tc port is described as a combinational output decoded from the count register and the live up input
- The parameter table lists N (default 8, with the minimum legal value stated) and MODE (type, legal values, default)
- An illegal MODE value is handled, for example by an elaboration-time error, and the handling is documented
- max is defined as {N{1'b1}}

## S3. Specify tc as a combinational decode of registered count and live up

**Goal:** Define tc = (up && count==MAX) || (!up && count==0), with no flop and no en/load qualification. Document that tc follows a change of up within the same cycle, and that this is consistent with the registered-output rule, which applies to count only.

**Feeds:** Control Logic, Timing & Pipeline · **Depends on:** S2

**Spec evidence:**
- [P2] "tc = 1 when count is at max while counting up, or at 0 while counting down"
- [P2] "registered outputs, no combinational path from inputs to count"

**Decisions:**
- D2 tc implementation: decode of registered count plus live up, or a fully registered flop: **Combinational decode of the count register and the live up input; no extra flop. A registered TC_REG option is out of scope and is only a possible future addition.** (decided)
  - options: Combinational decode: tc = up ? (count==max) : (count==0), so there is a path from up to tc / Registered tc flop computed from next_count and the current up, so tc lags a change of up by one cycle
  - User answer Q1: tc may be a combinational decode, tc follows a change of up immediately, and only count must be registered.
- D3 Is tc qualified by en (and by load)?: **tc ignores en and load; it depends only on count and up** (decided)
  - options: tc ignores en: it depends only on count and up / tc = en & boundary condition (cascade-friendly ripple-carry style)
  - The user's answer to Q1 gives the exact formula tc = (up && count==MAX) || (!up && count==0), which has no en or load term. This agrees with the spec's definition, which uses only count and direction.

**Done when:**
- A truth table gives tc for every combination of up, count==0 and count==max
- The doc states that tc is a decode and that up is the only input with a combinational path to tc (count comes from the register)
- The doc states that tc may glitch when up or count changes, and that a registered TC_REG variant is a possible future addition
- The doc states tc behaviour in SATURATE mode while count is held at a boundary (tc stays high while the direction is unchanged)
- The doc states that tc is independent of en and load

## S4. Specify next-state priority: rst > load > en-count > hold

**Goal:** Write the control logic that selects the next count: synchronous reset first, then parallel load, then count up or down when en=1, and otherwise hold.

**Feeds:** Control Logic · **Depends on:** S2

**Spec evidence:**
- [P2] "load has priority over counting"
- [P2] "sync active-high reset `rst`, single clock `clk`"
- [P2] "inputs: en, up (1=count up, 0=count down), load, load_val[N-1:0]"

**Decisions:**
- D4 Does load require en=1?: **load acts regardless of en** (default, low impact, medium confidence)
  - options: load acts regardless of en / load acts only when en=1
  - 'Priority over counting' implies load is an independent, higher-priority operation. en gates counting only.
- D5 Reset priority and reset value: **rst has highest priority; count resets to 0** (default, low impact, high confidence)
  - options: rst overrides load and en; count resets to 0 / rst overrides; count resets to a parameterized value / load overrides rst
  - This is the industry-standard convention for synchronous reset, and the spec gives no other reset value.

**Done when:**
- A priority table covers every combination of rst, load, en and up, with the resulting next count
- The table states that up is ignored for the next count when en=0 and load=0, while up still affects tc

## S5. Design an area-minimal ±1 datapath with MODE-dependent boundary handling

**Goal:** Define the next-count datapath: one shared ±1 adder, and one boundary compare (==max / ==0 selected by up) shared between saturation and the tc decode. A next-state mux selects among load_val, the adder result, the held value and 0.

**Feeds:** Datapath · **Depends on:** S3, S4

**Spec evidence:**
- [P2] "WRAP: max+1 -> 0, 0-1 -> max"
- [P2] "SATURATE: stick at max / 0"
- [P2] "Fmax is not critical; small area preferred"

**Decisions:**
- D8 Arithmetic structure for up/down counting: **A single shared adder adds +1 or -1 (all ones). WRAP uses natural modulo-2^N overflow. SATURATE suppresses the update when the boundary compare for the current direction is true, and that compare is the same signal as tc.** (default, low impact, high confidence)
  - options: Single N-bit adder: count + (up ? 1 : {N{1'b1}}) / Separate incrementer and decrementer followed by a mux
  - The spec prefers small area and Fmax is not critical, so sharing logic is the right tradeoff. Wraparound comes for free from N-bit arithmetic, and the tc decode can double as the saturation detect.

**Done when:**
- Datapath equations are given for both MODE values
- The doc shows that WRAP needs no compare for count update, and that SATURATE uses the tc signal as its hold condition
- The doc states that MODE selects logic through generate or a constant condition, so the unused path is optimized away

## S6. Draw the block diagram: count register, ±1 adder, shared boundary detect/tc, next-state mux

**Goal:** Provide a block diagram that connects the S4 control priority to the S5 datapath. It must show that tc is a combinational output of the boundary detect, fed by the count register Q output and the up input.

**Feeds:** Block Diagram · **Depends on:** S4, S5

**Spec evidence:**
- [P2] "registered outputs, no combinational path from inputs to count"
- [P2] "outputs: count[N-1:0], tc (terminal count)"

**Done when:**
- The diagram shows every port, the N-bit count register, the adder, the boundary detect, the priority mux and the tc output
- count is driven only by the register Q output
- tc is driven by combinational decode logic from the count register and up, with no flop, per D2

## S7. Document single-cycle timing and the output-path guarantees

**Goal:** State that there is no pipeline: inputs sampled at clock edge k appear on count after edge k. List all combinational paths to outputs, including the same-cycle path from up to tc.

**Feeds:** Timing & Pipeline · **Depends on:** S3, S5

**Spec evidence:**
- [P2] "registered outputs, no combinational path from inputs to count"
- [P2] "Fmax is not critical; small area preferred"

**Decisions:**
- D11 Pipeline depth: **Single cycle with no pipelining; count comes directly from the register** (decided)
  - options: Single-cycle: next count is registered on the next edge / Pipelined compare/add
  - The spec says Fmax is not critical and requires registered outputs.

**Done when:**
- A cycle-level waveform covers load, count up, count down, hold and a boundary event in both modes
- The waveform shows tc responding in the same cycle to a change of up at a boundary
- The critical path is identified: count register through the adder/compare and mux back to the register
- Every combinational path to an output is listed: none to count; up->tc and count reg->tc for tc

## S8. Define clocking and synchronous reset behaviour

**Goal:** Document the single clk domain, the synchronous active-high rst, and the reset value of count. Give the tc value that results after reset, which depends on up because tc is a decode.

**Feeds:** Clocking & Reset · **Depends on:** S4, S3

**Spec evidence:**
- [P2] "sync active-high reset `rst`, single clock `clk`"

**Decisions:**
- D10 Clocking and reset style: **Single rising-edge clk; synchronous active-high rst; en implemented as a datapath enable, not a clock gate** (decided)
  - options: Single rising-edge clk with synchronous active-high rst, no clock gating / Asynchronous reset / Clock gating for en
  - The spec requires a sync active-high reset and a single clock.

**Done when:**
- The doc states that rst is sampled on the clk rising edge and resets count to 0, per D5
- The doc states that tc has no reset of its own: after reset, count=0 gives tc=1 when up=0 and tc=0 when up=1 (for N>=1)
- The doc states that no CDC or clock gating is present

## S9. Enumerate boundary and priority corner cases across both modes

**Goal:** List the edge behaviours: load at a boundary value, a change of up while at a boundary (tc toggles immediately), en=0 at a boundary (tc is still asserted), simultaneous rst/load/en, N=1, and an illegal MODE.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S3, S4, S5

**Spec evidence:**
- [P2] "SATURATE: stick at max / 0"
- [P2] "WRAP: max+1 -> 0, 0-1 -> max"
- [P2] "tc = 1 when count is at max while counting up, or at 0 while counting down"
- [P2] "load has priority over counting"

**Done when:**
- Each corner case lists the expected count and tc for both MODE values
- The N=1 behaviour is described: max=1 and the two boundaries are adjacent
- The doc covers tc asserted while en=0 at a boundary, and tc asserted in the same cycle as a load to a boundary value
- Handling of an illegal MODE value at elaboration is described
- The doc notes that there are no runtime error conditions

## S10. Plan verification against a reference model for both MODE values and several N

**Goal:** Define a self-checking testbench with a cycle-accurate reference model in which tc is checked combinationally against the current count and up. Directed tests cover the boundary and priority cases; random tests drive the en/up/load/rst stimulus.

**Feeds:** Verification Plan · **Depends on:** S9

**Spec evidence:**
- [P2] "N-bit counter, N parameterizable (default 8)"
- [P2] "parameter MODE: WRAP or SATURATE"
- [P2] "tc = 1 when count is at max while counting up, or at 0 while counting down"

**Done when:**
- The test matrix covers MODE in {WRAP, SATURATE} crossed with N in {1, small, 8}
- Every S9 corner case has a directed test
- Assertions check: count changes only on a clk edge; rst wins; load wins over counting; count holds at a boundary in SATURATE; tc == (up && count==MAX) || (!up && count==0) at all times
- Coverage goals include both boundaries in both directions, load during en=0, tc rising and falling, and up toggling while at a boundary

## S11. Record assumptions and the remaining open load and MODE questions

**Goal:** Collect every remaining defaulted decision (D1, D4, D5, D7, D8) as an assumption with its open question. Record that D2/D3 were resolved by the user and that TC_REG is a possible future extension.

**Feeds:** Assumptions & Open Questions · **Depends on:** S2, S3, S4, S5

**Spec evidence:**
- [P2] "registered outputs, no combinational path from inputs to count"
- [P2] "load has priority over counting"

**Done when:**
- Each defaulted decision is listed with its chosen default and the question to ask
- D2 and D3 are recorded as resolved by the user's answer, with the exact tc formula
- An optional registered TC_REG variant is noted as a future extension, not implemented
- D4 (load vs en) and D1 (MODE encoding/default) are flagged as the main remaining open items

## Assumptions (defaults not confirmed by the user)

- D1 MODE parameter representation and default value: String parameter MODE with legal values "WRAP" and "SATURATE", default "WRAP" (low impact, medium confidence)
- D7 Definition of 'max': max = 2^N-1 (all ones); no separate modulus parameter (medium impact, high confidence)
- D4 Does load require en=1?: load acts regardless of en (low impact, medium confidence)
- D5 Reset priority and reset value: rst has highest priority; count resets to 0 (low impact, high confidence)
- D8 Arithmetic structure for up/down counting: A single shared adder adds +1 or -1 (all ones). WRAP uses natural modulo-2^N overflow. SATURATE suppresses the update when the boundary compare for the current direction is true, and that compare is the same signal as tc. (low impact, high confidence)
