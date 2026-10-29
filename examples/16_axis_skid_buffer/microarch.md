# Micro-architecture: `axis_skid`

## 1. Overview

`axis_skid` is a 2-entry AXI-Stream register slice ("skid buffer"). It fully registers both
the forward path (`TVALID`, `TDATA`, `TKEEP`, `TLAST`, `TUSER`) and the backward path
(`TREADY`), and still sustains one beat per clock.

The trick: `s_tready` is a registered signal, so it reaches the upstream one cycle late. In
the cycle the downstream stalls, the upstream may still push one more beat. A second
"skid" register catches that beat so it is not lost.

Key features:
- No combinational path from any input to any output (in both directions).
- 100% throughput when `m_tready` is held high; no bubbles when a stall is released.
- Generic payload: `TDATA`/`TKEEP`/`TLAST`/`TUSER` are packed into one vector and passed through unchanged.
- Small: 2 × payload registers plus 3 control flops and one 2:1 mux on the output register input.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Global** | | | |
| `aclk` | in | 1 | Clock. |
| `aresetn` | in | 1 | Active-low synchronous reset. |
| **Slave (input) stream** | | | |
| `s_tvalid` | in | 1 | |
| `s_tready` | out | 1 | Registered: `!skid_valid_q`. |
| `s_tdata` | in | `DATA_W` | |
| `s_tkeep` | in | `DATA_W/8` | |
| `s_tlast` | in | 1 | |
| `s_tuser` | in | `USER_W` | Only present if `USER_W > 0`. |
| **Master (output) stream** | | | |
| `m_tvalid` | out | 1 | Registered: `out_valid_q`. |
| `m_tready` | in | 1 | |
| `m_tdata` | out | `DATA_W` | Registered. |
| `m_tkeep` | out | `DATA_W/8` | Registered. |
| `m_tlast` | out | 1 | Registered. |
| `m_tuser` | out | `USER_W` | Registered. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `DATA_W` | 64 | 8–4096, multiple of 8 | TDATA width. |
| `USER_W` | 0 | 0–1024 | TUSER width (0 = port unused, tied off). |
| `KEEP_W` | `DATA_W/8` | derived | TKEEP width. |
| `PAY_W` | `DATA_W + KEEP_W + 1 + USER_W` | derived | Packed payload width (`{tuser, tlast, tkeep, tdata}`). |

`USER_W = 0` is handled with a `generate` that removes the `tuser` slice from the packing.
The ports remain at width 1 and are ignored, which keeps the port list legal Verilog.

## 4. Block Diagram

```
                     +----------------------+
 s_payload ----+---->| skid_q  (PAY_W)      |---+
               |     | skid_valid_q         |   |     +-----+      +----------------------+
               |     +----------------------+   +---->| 1   |      | out_q  (PAY_W)       |---> m_payload
               |                                      |  mux|----->| out_valid_q          |---> m_tvalid
               +------------------------------------->| 0   |      +----------------------+
                                                      +--^--+
                                                         | sel = skid_valid_q
 s_tready <---- ~skid_valid_q                                         m_tready -----> (control)
```

| Instance | Module | Purpose |
|----------|--------|---------|
| — (inline) | output register | `out_q`/`out_valid_q`: drives the master interface. |
| — (inline) | skid register | `skid_q`/`skid_valid_q`: holds the one beat accepted during a stall. |
| — (inline) | control | Next-state logic for both valid flags. |

## 5. Datapath

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `out_valid_q` | 1 | 0 | Output register holds a beat (`m_tvalid`). |
| `out_q` | `PAY_W` | not reset | Output payload. |
| `skid_valid_q` | 1 | 0 | Skid register holds a beat; `s_tready = !skid_valid_q`. |
| `skid_q` | `PAY_W` | not reset | Skid payload. |

**Handshake qualifiers**

```verilog
wire s_fire   = s_tvalid && s_tready;           // s_tready = !skid_valid_q
wire out_free = !out_valid_q || m_tready;       // output reg will be empty after this edge
```

**Payload moves**

| Condition | `out_q` loads | `skid_q` loads |
|-----------|---------------|----------------|
| `out_free && skid_valid_q` | `skid_q` | – |
| `out_free && !skid_valid_q && s_fire` | `s_payload` | – |
| `!out_free && s_fire` | – | `s_payload` |
| otherwise | hold | hold |

The output register's D-input has a 2:1 mux (`skid_q` vs `s_payload`) selected by
`skid_valid_q`, which is a flop. That keeps the mux select off the critical path.

## 6. Control Logic

The two valid flags form an implicit 3-state FSM (`skid` cannot be full while `out` is empty):

| State | `out_valid_q` | `skid_valid_q` | `s_tready` | `m_tvalid` |
|-------|---------------|----------------|------------|------------|
| EMPTY | 0 | 0 | 1 | 0 |
| ONE | 1 | 0 | 1 | 1 |
| TWO (skid) | 1 | 1 | 0 | 1 |

| Current | `s_fire` | `m_tready` | Next | Action |
|---------|----------|------------|------|--------|
| EMPTY | 0 | x | EMPTY | – |
| EMPTY | 1 | x | ONE | `out_q ← s` |
| ONE | 0 | 0 | ONE | hold |
| ONE | 0 | 1 | EMPTY | beat delivered |
| ONE | 1 | 1 | ONE | deliver + `out_q ← s` (streaming) |
| ONE | 1 | 0 | TWO | `skid_q ← s` (the "skid") |
| TWO | – (`s_tready=0`) | 0 | TWO | hold |
| TWO | – | 1 | ONE | deliver, `out_q ← skid_q` |

```verilog
out_valid_n  = out_free ? (skid_valid_q | s_fire) : 1'b1;
skid_valid_n = out_free ? 1'b0 : (skid_valid_q | s_fire);
```

`m_tready` affects only the D-inputs of the four registers. No output depends on it
combinationally, which is the requirement.

## 7. Timing & Pipeline

- **Latency:** 1 cycle (input beat accepted in cycle N appears on `m_*` in N+1), or 2 cycles for the beat that skids.
- **Throughput:** 1 beat/cycle when `m_tready` is held high. After a stall, the output side delivers on every cycle that `m_tready` is high; the input side sees exactly one `s_tready = 0` cycle per stall episode.
- **Critical paths:** all port-to-register or register-to-port; the longest is `m_tready` → `out_free` → valid next-state and the mux/enable fanout to `PAY_W` flops (high fanout for wide `DATA_W`; replicate the enable if needed).

Stall example (upstream always valid, beats A, B, C, …):

| Cyc | s_tvalid/s_tready | s data | out (during) | skid (during) | m_tready | Delivered | State |
|-----|-------------------|--------|--------------|---------------|----------|-----------|-------|
| 0 | 1/1 | A | – | – | 1 | – | EMPTY |
| 1 | 1/1 | B | A | – | 1 | A | ONE |
| 2 | 1/1 | C | B | – | 0 | – | ONE → TWO (C skids) |
| 3 | 1/0 | D (held) | B | C | 0 | – | TWO |
| 4 | 1/0 | D (held) | B | C | 1 | B | TWO → ONE (out←C) |
| 5 | 1/1 | D | C | – | 1 | C | ONE |
| 6 | 1/1 | E | D | – | 1 | D | ONE |

Output deliveries are B@4, C@5, D@6: no bubble after the stall is released.

## 8. Clocking & Reset

- Single clock `aclk`; no CDC.
- `aresetn` is active-low and synchronous. Only `out_valid_q` and `skid_valid_q` are reset; the payload registers are not, which reduces reset fanout on wide buses (AXI only requires `TVALID` to be low during reset). After reset `s_tready = 1`, which is permitted because the upstream must keep `TVALID` low during reset.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| Downstream stalls the cycle a beat is accepted | Beat goes to `skid_q`; nothing is lost. |
| Stall released while skid full | `out_q ← skid_q` and the skid empties; `s_tready` returns next cycle. |
| `s_tvalid` drops while stalled | Nothing new; state holds. |
| `m_tready` high with nothing valid | No effect (`out_valid_q = 0`). |
| Packet boundaries | `TLAST`/`TKEEP` travel with their beat; the slice never splits, merges or reorders beats. |
| AXI rule "VALID must not depend on READY" | Satisfied: `m_tvalid` is a flop. |
| AXI rule "once VALID, payload stable until READY" | Satisfied: `out_q` only loads when `out_free`. |

## 10. Verification Plan

**Testbench:** a source driver with random `s_tvalid` and a sink with random `m_tready`; a
queue scoreboard compares every delivered `{tdata, tkeep, tlast, tuser}` in order.

**Directed tests**
1. Continuous flow with `m_tready = 1`: N beats in, N beats out, 1 per cycle.
2. Single-cycle stall at each position: the §7 table sequence.
3. Long stall (10 cycles) with the upstream pushing: exactly 2 beats buffered, `s_tready` low.
4. Alternating `m_tready` (1010…) with upstream always valid: no loss, no duplicates.
5. Reset in the middle of traffic: valids cleared, the stream restarts cleanly.

**Random:** 1M cycles with independent valid/ready probabilities in {10, 50, 90, 100}%;
check zero loss, ordering, and the throughput bound "deliveries ≥ cycles with
`m_tready && m_tvalid`".

**Assertions (SVA)**

```systemverilog
a_m_stable: assert property (@(posedge aclk) disable iff(!aresetn)
              m_tvalid && !m_tready |=> m_tvalid && $stable({m_tdata,m_tkeep,m_tlast,m_tuser}));
a_no_two_wo_one: assert property (@(posedge aclk) disable iff(!aresetn) skid_valid_q |-> out_valid_q);
a_full_tput: assert property (@(posedge aclk) disable iff(!aresetn)
              s_tvalid && s_tready && m_tready && out_valid_q |=> m_tvalid);
```

**Formal:** prove the stream-preservation property, ordering, and "no comb path"
(structural check, or a lint rule that flags combinational paths from inputs to outputs).

**Coverage:** every state transition in §6; stall lengths 1, 2 and >2; packet boundary
(`tlast`) while skidding.

## 11. Assumptions & Open Questions

1. **Reset style:** the spec didn't say; synchronous active-low `aresetn` is assumed to match AXI convention.
2. **TUSER** is supported now through `USER_W` (default 0) because the spec mentions "maybe tuser later". Adding it later then needs no interface change.
3. **TKEEP width** is fixed to `DATA_W/8`; `TSTRB`, `TID` and `TDEST` are not present. They can be added to the packed payload in the same way.
4. **Payload not reset:** chosen to reduce reset fanout; a `RESET_PAYLOAD` parameter could be added if the downstream observes `TDATA` while `TVALID = 0`.
5. **Topology:** the two-register "output + skid" form is chosen over a 2-entry circular FIFO because its output always comes from one register (`out_q`), which is better for timing at the output port.
