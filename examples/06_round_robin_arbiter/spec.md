# RRA-001: Round-Robin Arbiter – Requirements

**Context:** shared-resource arbiter for the on-chip interconnect (up to 32 masters).

| ID | Requirement |
|----|-------------|
| R1 | The arbiter shall support N requesters, N a parameter in 2..32. |
| R2 | Each requester i drives `req[i]`. The arbiter shall drive a one-hot `gnt[N-1:0]`; at most one bit is set per cycle. |
| R3 | A grant shall only be given to a requester whose `req` is asserted in that cycle. |
| R4 | Grant decision shall be made in the same cycle as the request (zero-latency) to avoid bubbles on the interconnect. |
| R5 | Arbitration shall be round-robin: after requester i is granted, requester i has the lowest priority in the next arbitration. |
| R6 | A requester may assert `lock[i]` together with `req[i]` while granted to keep the grant in the following cycle (multi-cycle burst / atomic access). |
| R7 | To bound latency, a single lock shall not exceed MAX_LOCK consecutive cycles; MAX_LOCK = 0 means unlimited. |
| R8 | The arbiter shall output the binary index of the granted requester and a valid flag. |
| R9 | The arbiter shall output a status flag indicating the current grant is a locked continuation. |
| R10 | Single clock, active-low asynchronous reset. Must close timing at 500 MHz in 7 nm for N=16. |
| R11 | Starvation-free: every requester holding `req` continuously shall be granted within a bounded number of cycles. |
