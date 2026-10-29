# Micro-architecture: `updown_counter`

## 1. Overview

`updown_counter` is an N-bit synchronous binary counter. It supports a parallel load,
a count enable, a direction select, and two overflow policies chosen at elaboration time:
wrap-around (modulo 2^N) or saturation at the range limits. A terminal-count flag `tc`
shows that the counter sits at the boundary in the current direction.

Key features:
- One `N`-bit register and one shared adder/subtractor (`count ± 1`).
- Priority: `rst` > `load` > `en` (count) > hold.
- `MODE` parameter selects WRAP or SATURATE behaviour at the boundaries.
- `count` is a register output. `tc` is decoded from `count` and `up` (see §11 for the registered option).

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | Clock, rising-edge. |
| `rst` | in | 1 | Synchronous active-high reset; sets `count` to 0. |
| **Control** | | | |
| `en` | in | 1 | Count enable. When 1 (and `load`=0), count one step in direction `up`. |
| `up` | in | 1 | Direction: 1 = increment, 0 = decrement. |
| `load` | in | 1 | Parallel load; has priority over `en`. |
| `load_val` | in | `N` | Value loaded when `load`=1. |
| **Status** | | | |
| `count` | out | `N` | Current counter value (register output). |
| `tc` | out | 1 | Terminal count: `(up && count==MAX) || (!up && count==0)`. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `N` | 8 | 1–64 | Counter width. |
| `MODE` | `0` (WRAP) | 0 = WRAP, 1 = SATURATE | Boundary behaviour. |
| `MAX` | `{N{1'b1}}` | derived (localparam) | Maximum count value, 2^N − 1. |

An elaboration check (`generate` + `$error`) rejects `MODE` values other than 0 or 1.

## 4. Block Diagram

```
                  up
                  |
   count_q ---+-->[ +1 / -1 ]---- step_val ----+
              |                                |
              |   [ boundary detect ]          |
              +-->  at_max, at_zero -----+     |
              |                          |     v
              |                    +-----v-----------+
   load_val --+------------------->|  next-value mux |----> count_n
              |      load, en ---->|  (priority)     |        |
              |                    +-----------------+        |
              |                                               v
              |                                        +-----------+
              +<---------------------------------------| count_q   |<- clk, rst
                                                       +-----------+
                                                             |
                                    up, at_max, at_zero ---> tc
```

| Instance | Module | Purpose |
|----------|--------|---------|
| — (inline) | step unit | `count_q + 1` or `count_q - 1`, selected by `up`. |
| — (inline) | boundary detect | `at_max = (count_q == MAX)`, `at_zero = (count_q == 0)`. |
| — (inline) | next-value mux | Applies priority and MODE policy. |

The design is small enough that no submodules are instantiated.

## 5. Datapath

**Registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `count_q` | `N` | 0 | Counter state; drives `count`. |

**Combinational signals**

| Signal | Width | Definition |
|--------|-------|------------|
| `step_val` | `N` | `up ? count_q + 1'b1 : count_q - 1'b1` (one adder with carry-in, operand `{N{~up}}`). |
| `at_max` | 1 | `count_q == MAX` (N-input AND). |
| `at_zero` | 1 | `count_q == 0` (N-input NOR). |
| `at_bound` | 1 | `up ? at_max : at_zero`. |

A single adder implements both directions: `count_q + (up ? 1 : {N{1'b1}})`, which is
`count_q - 1` in two's complement. In WRAP mode the natural N-bit overflow gives the
wrap-around, so no extra logic is needed.

## 6. Control Logic

There is no FSM; the next-value selection is a priority mux.

| Priority | Condition | `count_n` |
|----------|-----------|-----------|
| 1 | `rst` | `0` |
| 2 | `load` | `load_val` |
| 3 | `en && at_bound && MODE==SATURATE` | `count_q` (hold at limit) |
| 4 | `en` | `step_val` (wraps naturally in WRAP mode) |
| 5 | otherwise | `count_q` |

```verilog
always @(posedge clk)
  if (rst)                                     count_q <= '0;
  else if (load)                               count_q <= load_val;
  else if (en && !(MODE==1 && at_bound))       count_q <= step_val;

assign tc = at_bound;
```

## 7. Timing & Pipeline

- **Latency:** 1 cycle from `load`/`en` to the new `count`.
- **Throughput:** one step per cycle.
- **`tc` timing:** combinational from `count_q` and `up`. It reflects the current register value, so it is high during the cycle in which the counter sits at the boundary.
- **Critical path:** `count_q` → N-bit adder carry chain → mux → `count_q`. On FPGA this uses the dedicated carry chain.

Cycle-by-cycle example (`N=2`, `MAX=3`):

| Cycle | rst | load | load_val | en | up | count (during) | tc | count (next) WRAP | count (next) SAT |
|-------|-----|------|----------|----|----|----------------|----|-------------------|------------------|
| 0 | 1 | 0 | - | - | - | x | x | 0 | 0 |
| 1 | 0 | 0 | - | 1 | 1 | 0 | 0 | 1 | 1 |
| 2 | 0 | 1 | 2 | 1 | 1 | 1 | 0 | 2 | 2 |
| 3 | 0 | 0 | - | 1 | 1 | 2 | 0 | 3 | 3 |
| 4 | 0 | 0 | - | 1 | 1 | 3 | 1 | 0 | 3 |
| 5 | 0 | 0 | - | 1 | 0 | 0 (WRAP) / 3 (SAT) | 1 / 0 | 3 | 2 |
| 6 | 0 | 0 | - | 0 | 0 | 3 / 2 | 0 / 0 | 3 | 2 |

## 8. Clocking & Reset

- Single clock domain `clk`; no CDC.
- `rst` is **synchronous**, active-high, as the spec requires. It must be synchronized to
  `clk` upstream. It sets `count_q` to 0.
- `up`, `en`, `load` and `load_val` are assumed synchronous to `clk`.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| `load` and `en` together | `load` wins; `count_n = load_val`. |
| `load_val` equals a boundary | Loaded as-is; `tc` reflects it on the next cycle. |
| Increment at MAX, WRAP | `count_n = 0`. |
| Increment at MAX, SATURATE | Holds at MAX; `tc` stays 1. |
| Decrement at 0, WRAP | `count_n = MAX`. |
| Decrement at 0, SATURATE | Holds at 0; `tc` stays 1. |
| `up` changes while `en`=0 | `tc` updates combinationally (it depends on `up`); `count` unchanged. |
| `N = 1` | MAX = 1; the counter toggles between 0 and 1 in WRAP mode. |

## 10. Verification Plan

**Testbench:** self-checking, with a behavioural reference model
(`ref = load ? load_val : en ? f(ref, up, MODE) : ref`) compared every cycle.

**Directed tests**
1. Reset clears count to 0.
2. Count up from 0 through MAX and check the wrap or saturate result for each MODE.
3. Count down from MAX through 0 and check the wrap or saturate result.
4. Load priority over `en`, including loading MAX and 0.
5. `tc` for both directions at both boundaries.
6. Hold when `en`=0.

**Random:** random `en`/`up`/`load`/`load_val` for 50k cycles, `N ∈ {1, 4, 8, 32}`, both MODEs.

**Assertions (SVA)**

```systemverilog
a_load:  assert property (@(posedge clk) disable iff(rst) load |=> count == $past(load_val));
a_hold:  assert property (@(posedge clk) disable iff(rst) !load && !en |=> $stable(count));
a_sat_hi:assert property (@(posedge clk) disable iff(rst)
           MODE==1 && !load && en && up && count==MAX |=> count==MAX);
a_wrap:  assert property (@(posedge clk) disable iff(rst)
           MODE==0 && !load && en && up && count==MAX |=> count==0);
a_tc:    assert property (@(posedge clk) tc == ((up && count==MAX) || (!up && count==0)));
```

**Coverage:** wrap/saturate events in both directions; `load` and `en` together; `tc` rise/fall;
consecutive loads.

## 11. Assumptions & Open Questions

1. **`tc` is combinational** (decoded from `count_q` and `up`). Registering it would add a cycle of lag or need a look-ahead compare; since the spec only requires `count` to be registered, the cheaper option was taken. If `tc` must be glitch-free for an asynchronous consumer, add a `TC_REG` parameter that computes `tc` from `count_n`.
2. **`tc` ignores `en`.** It reports the boundary position, not "the counter is about to roll over". Users who need a roll-over pulse can AND `tc` with `en`.
3. **MODE is a parameter**, not a runtime input, as the spec implies. A runtime mode bit would cost one AND gate if needed later.
4. **Synchronous reset** as specified. For an ASIC with async-reset libraries, swap the reset style; the behaviour is unchanged.
5. **`load_val` is not range-checked**; every N-bit value is legal.
