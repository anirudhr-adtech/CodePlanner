# MA plan: 06_round_robin_arbiter

## S1. Scope the RRA-001 arbiter and trace R1-R11 to MA content

**Goal:** Write the Overview: a zero-latency, N-way (2..32) round-robin arbiter with lock/burst support, a MAX_LOCK bound on locked-continuation cycles, binary index/valid and locked-status outputs, targeting 500 MHz in 7 nm at N=16. Include a requirement-to-section trace table and record the clarifications from Q1-Q3.

**Feeds:** Overview · **Depends on:** none

**Spec evidence:**
- [P2] "shared-resource arbiter for the on-chip interconnect (up to 32 masters)."
- [P3] "The arbiter shall support N requesters, N a parameter in 2..32."
- [P3] "Grant decision shall be made in the same cycle as the request (zero-latency) to avoid bubbles on the interconnect."

**Decisions:**
- D1 Grant path latency structure: **gnt is computed combinationally in the same cycle from req, lock and registered state (pointer, lock owner, lock counter). No pipeline stage is allowed on req->gnt.** (decided)
  - options: Purely combinational grant from req/lock plus registered arbitration state / Registered grant (1-cycle latency)
  - R4 requires a zero-latency grant to avoid interconnect bubbles.

**Done when:**
- Overview states the function, the N range, the zero-latency property, the lock/MAX_LOCK feature (MAX_LOCK counts continuation cycles only) and the 500 MHz/7 nm/N=16 target
- Trace table maps each of R1-R11 to at least one MA section
- Overview states that the arbiter is work-conserving, with no idle cycles on lock release or expiry

## S2. Define the req/lock/gnt/index/valid/locked port list and the N, MAX_LOCK parameters

**Goal:** Fix every port with its width, direction and timing class (combinational output vs registered state), and every parameter with its derived widths.

**Feeds:** Interface, Parameters · **Depends on:** S1

**Spec evidence:**
- [P3] "The arbiter shall drive a one-hot `gnt[N-1:0]`; at most one bit is set per cycle."
- [P3] "The arbiter shall output the binary index of the granted requester and a valid flag."
- [P3] "The arbiter shall output a status flag indicating the current grant is a locked continuation."
- [P3] "To bound latency, a single lock shall not exceed MAX_LOCK consecutive cycles; MAX_LOCK = 0 means unlimited."

**Decisions:**
- D2 Downstream backpressure / grant-accept input: **No accept/ready input. Every asserted grant counts as a served cycle for pointer and lock-counter updates.** (default, medium impact, medium confidence)
  - options: No accept/ready input: a grant is consumed in every cycle it is asserted / Add a resource ready/enable input that freezes arbitration state
  - The spec lists no such signal, and the zero-latency interconnect context suggests the resource accepts a grant every cycle.
- D3 Timing of index/valid/locked outputs: **gnt_idx (width $clog2(N)), gnt_valid (= |gnt) and gnt_locked are combinational and cycle-aligned with gnt.** (default, medium impact, high confidence)
  - options: Combinational, same cycle as gnt / Registered (one cycle after gnt)
  - Registering them would misalign them with the zero-latency grant and make them useless as a same-cycle mux select.

**Done when:**
- Port table lists clk, rst_n, req[N-1:0], lock[N-1:0], gnt[N-1:0], index, valid and the locked flag, with widths and directions
- Index width rule is stated for N=2..32, including N that is not a power of 2
- MAX_LOCK semantics (number of locked-continuation cycles; burst up to MAX_LOCK+1 grants) and the counter width ($clog2(MAX_LOCK+1)) are stated, with MAX_LOCK=0 meaning no counter
- Parameter checks (N in 2..32, MAX_LOCK>=0) are specified as elaboration-time assertions

## S3. Design the round-robin priority core: pointer register and masked priority encoding

**Goal:** Specify how the next grant is chosen so that the last-granted requester has the lowest priority, using a structure fast enough for N=16 at 500 MHz.

**Feeds:** Datapath, Block Diagram · **Depends on:** S2

**Spec evidence:**
- [P3] "Arbitration shall be round-robin: after requester i is granted, requester i has the lowest priority in the next arbitration."
- [P3] "A grant shall only be given to a requester whose `req` is asserted in that cycle."
- [P3] "Must close timing at 500 MHz in 7 nm for N=16."

**Decisions:**
- D4 Round-robin implementation structure: **Dual masked/unmasked fixed-priority encoders with a registered thermometer mask derived from the last granted index. Each find-first is implemented as a log-depth prefix-OR.** (default, medium impact, medium confidence)
  - options: Dual priority encoder: thermometer mask of positions above the last grant, masked and unmasked fixed-priority encoders, select masked if non-empty / Rotate -> fixed-priority -> rotate back (barrel shifters) / Parallel-prefix (Kogge-Stone style) find-first-set on doubled request vector
  - This avoids barrel shifters on the critical path, has log2(N) depth, and is the standard choice for single-cycle RR at high frequency.
- D5 Pointer update policy: **The registered pointer/mask updates to the granted index in every cycle gnt_valid=1, including locked-continuation cycles. It holds its value when no grant is given.** (default, medium impact, high confidence)
  - options: Update pointer to the granted index on every cycle a grant is issued; hold when idle / Update pointer only at the end of a lock or burst / Advance pointer every cycle regardless of grant
  - This directly implements R5 and the Q2 answer (the former owner is lowest priority after expiry). Holding on idle preserves fairness history.

**Done when:**
- Equations or pseudo-RTL are given for the mask, the masked request, both encoders, the select and the pointer next-state
- It is shown that gnt is one-hot or zero and is a subset of req in every case
- A worked N=4 example shows the priority order after each grant

## S4. Specify lock ownership: lock_req = |(gnt & lock & req), owner override, and same-cycle release when the owner drops req

**Goal:** Define the lock-owner state and its override of the RR core, following the Q1 answer: the lock is honoured only when it is asserted together with gnt and req, and it is released with immediate re-arbitration when the owner drops req.

**Feeds:** Control Logic, Datapath · **Depends on:** S3

**Spec evidence:**
- [P3] "A requester may assert `lock[i]` together with `req[i]` while granted to keep the grant in the following cycle (multi-cycle burst / atomic access)."
- [P3] "A grant shall only be given to a requester whose `req` is asserted in that cycle."

**Decisions:**
- D6 Lock sampling and release semantics: **lock_req = |(gnt & lock & req). In cycle t, if lock_req (and the MAX_LOCK limit is not reached), set lock_q and register the owner as the granted index. In cycle t+1, if lock_q and req[owner], grant the owner (overriding RR). Otherwise release the lock and use normal RR in that same cycle, with no idle cycle. A lock[i] without gnt[i], or a lock without req, is ignored.** (decided)
  - options: Register lock_active/owner when gnt[i]&req[i]&lock[i]; next cycle grant owner only if req[owner] is still high, else drop the lock and arbitrate normally in that same cycle / Lock forces grant next cycle even if req drops (violates R3) / Combinational lock that holds the grant in the same cycle
  - The user's answer to Q1 confirms this behaviour.

**Done when:**
- The lock state (lock_q and an owner index or one-hot) is specified with next-state equations using lock_req = |(gnt & lock & req)
- The override mux between the lock-owner grant and the RR grant is shown, including the req[owner] qualification
- Ignored cases are listed: lock without req, lock from a non-granted requester, and owner dropping req (same-cycle fallback to RR)

## S5. Define the MAX_LOCK continuation counter: burst of up to MAX_LOCK+1 grants, expiry re-arbitration, no hardware for MAX_LOCK=0

**Goal:** Specify the counter that limits locked-continuation cycles to MAX_LOCK, the forced release at expiry with the former owner at lowest priority, and removal of the logic when MAX_LOCK=0.

**Feeds:** Control Logic, Parameters · **Depends on:** S4

**Spec evidence:**
- [P3] "To bound latency, a single lock shall not exceed MAX_LOCK consecutive cycles; MAX_LOCK = 0 means unlimited."
- [P3] "Starvation-free: every requester holding `req` continuously shall be granted within a bounded number of cycles."

**Decisions:**
- D7 MAX_LOCK counting and expiry behaviour: **MAX_LOCK counts only locked-continuation cycles, so a burst is at most MAX_LOCK+1 consecutive grants (one arbitrated cycle plus up to MAX_LOCK continuations). After MAX_LOCK continuations, lock_req is ignored and the next cycle re-arbitrates normally with the former owner at lowest priority. The arbiter is work-conserving: if nobody else requests, the former owner is re-granted through normal RR, and that grant starts a new burst.** (decided)
  - options: Count all consecutive grant cycles of the burst including the initial grant / Count only locked-continuation cycles (burst length MAX_LOCK+1) / At expiry, force at least one cycle where the owner cannot be granted
  - The user's answer to Q2 settles this. Users who need the limit to include the first cycle set the parameter to L-1.
- D8 Interaction of MAX_LOCK=0 (unlimited) with starvation-freedom R11: **Allow MAX_LOCK=0 with no counter hardware. Document that R11 then holds only under the assumption that every lock is released in finite time. With MAX_LOCK>0 the wait is bounded. The user stated (N-1)*MAX_LOCK; the MA writer must re-derive the exact bound under the D7 counting, where each other master can hold up to MAX_LOCK+1 cycles, giving (N-1)*(MAX_LOCK+1). The discrepancy must be recorded.** (decided)
  - options: Guarantee R11 only when MAX_LOCK>0; with MAX_LOCK=0 the bound is conditional on masters releasing lock in finite time / Forbid MAX_LOCK=0 by assertion / Use a hidden internal cap when MAX_LOCK=0
  - The user's answer to Q3 selected this option. The numeric bound must be consistent with the Q2 counting.

**Done when:**
- Counter reset, increment (on each locked-continuation grant), clear (on release or new burst) and limit conditions are given as equations
- The expiry condition (count == MAX_LOCK blocks the lock_q set) is specified, with a cycle-by-cycle example for MAX_LOCK=3: cycle 0 arbitrated, cycles 1-3 continuations, cycle 4 re-arbitrated, shown both with and without competing requesters
- A generate-if that removes the counter when MAX_LOCK=0 is described
- The worst-case wait bound formula for MAX_LOCK>0 is derived consistently with continuation-only counting

## S6. Derive gnt index, valid and locked-continuation status outputs

**Goal:** Specify the one-hot to binary encoder, the valid flag and the locked flag so they are consistent with gnt in every cycle.

**Feeds:** Datapath, Interface · **Depends on:** S4, S5

**Spec evidence:**
- [P3] "The arbiter shall output the binary index of the granted requester and a valid flag."
- [P3] "The arbiter shall output a status flag indicating the current grant is a locked continuation."

**Decisions:**
- D9 Semantics of the locked-continuation flag: **The locked flag is high only in cycles where the grant is issued by the lock override (lock_q & req[owner]). It is low on the initial arbitrated grant of a burst, on a re-grant after expiry, and whenever gnt_valid=0. It is therefore high for at most MAX_LOCK consecutive cycles when MAX_LOCK>0.** (decided)
  - options: Asserted only in cycles where the grant comes from the lock override (not the first cycle of a burst) / Asserted on every cycle of a locked burst, including the first
  - R9 says 'locked continuation', which excludes the initial grant. This matches the continuation-only counting in D7.

**Done when:**
- The OR-tree one-hot to binary encoder is specified, and index is defined (e.g. 0) when valid=0
- valid = |gnt is stated
- The locked flag equation is given and checked against the S5 MAX_LOCK=3 example (high in cycles 1-3 only)

## S7. Block diagram and 500 MHz critical-path budget for the combinational req->gnt path

**Goal:** Draw the block diagram (mask/pointer regs, dual PE, lock override mux, continuation counter, encoders) and analyse the combinational depth from req/lock inputs to gnt/index outputs at N=16.

**Feeds:** Block Diagram, Timing & Pipeline · **Depends on:** S3, S4, S5, S6

**Spec evidence:**
- [P3] "Must close timing at 500 MHz in 7 nm for N=16."
- [P3] "Grant decision shall be made in the same cycle as the request (zero-latency) to avoid bubbles on the interconnect."

**Decisions:**
- D10 I/O timing budget assumption for the combinational path: **Assume req and lock are launched from flops in the masters and gnt/idx are captured by flops or a mux in the resource. The arbiter's req->gnt and req->idx logic is budgeted at about 1 ns of the 2 ns period.** (default, medium impact, medium confidence)
  - options: Assume req/lock come from master flops and gnt/index go to flops, with the arbiter allotted about 50% of the 2 ns cycle / Arbiter owns the full cycle (registered inputs and outputs inside) / Budget supplied by the integrator
  - Zero latency makes the arbiter part of an inter-block combinational path, so a budget split must be assumed to evaluate the 500 MHz target.

**Done when:**
- The block diagram shows all registers and combinational blocks with signal flow
- The critical path is identified (req -> masked PE -> select -> lock override mux qualified by req[owner] -> gnt -> index), with logic-depth estimates for N=16 and N=32
- The lock/expiry control is shown to depend only on registered state plus req[owner], keeping it off the deep path
- The statement 'no pipeline stages; all state updates at clock edge from current-cycle grant' is explicit

## S8. Single-clock domain and active-low asynchronous reset of pointer, lock and counter state

**Goal:** Specify the clock and reset scheme and the reset value of every state element.

**Feeds:** Clocking & Reset · **Depends on:** S3, S4, S5

**Spec evidence:**
- [P3] "Single clock, active-low asynchronous reset."

**Decisions:**
- D11 Reset style and deassertion synchronisation: **All state flops use async active-low reset (always @(posedge clk or negedge rst_n)). Synchronous deassertion is the integrator's responsibility; no internal synchroniser is added.** (default, low impact, medium confidence)
  - options: Async assert on rst_n low; deassertion assumed synchronised externally / Integrate a reset synchroniser inside the arbiter
  - R10 fixes an async active-low reset. Reset synchronisers are normally provided at SoC level.

**Done when:**
- Reset values are listed for the pointer/mask (e.g. requester 0 highest priority), lock_q, owner and the continuation counter
- It is stated that after reset with lock_q=0, gnt follows pure RR, and that gnt=0, valid=0 and locked=0 hold whenever req=0
- The single clock is confirmed, with no CDC

## S9. Enumerate corner cases: lock edge cases, MAX_LOCK expiry and re-grant, N extremes and the starvation bound

**Goal:** Document behaviour for every unusual input combination and prove the starvation bound under continuation-only MAX_LOCK counting.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S4, S5, S6

**Spec evidence:**
- [P3] "Starvation-free: every requester holding `req` continuously shall be granted within a bounded number of cycles."
- [P3] "A requester may assert `lock[i]` together with `req[i]` while granted to keep the grant in the following cycle (multi-cycle burst / atomic access)."
- [P3] "The arbiter shall support N requesters, N a parameter in 2..32."

**Done when:**
- Cases covered: all req low; single requester; all requesters; lock without req; lock from a non-granted master; owner drops req while lock_q=1 (same-cycle RR fallback); expiry with others requesting (owner lowest priority); expiry with sole requester (immediate re-grant, new burst, locked flag low); lock asserted on the expiry cycle; MAX_LOCK=1; N=2; N=32; non-power-of-2 N
- The starvation bound is derived for MAX_LOCK>0 with bursts of up to MAX_LOCK+1, and the MAX_LOCK=0 caveat is linked to D8
- It is stated that there are no illegal-input error outputs; illegal combinations are ignored

## S10. Verification plan: reference model, SVA for one-hot/R3/RR/lock rules/continuation bound, and parameter sweep

**Goal:** Define how the MA will be verified against R1-R11 and the Q1-Q3 clarifications.

**Feeds:** Verification Plan · **Depends on:** S9

**Spec evidence:**
- [P3] "at most one bit is set per cycle."
- [P3] "after requester i is granted, requester i has the lowest priority in the next arbitration."
- [P3] "a single lock shall not exceed MAX_LOCK consecutive cycles"

**Done when:**
- Assertions are listed: $onehot0(gnt); gnt subset of req; valid==|gnt; idx matches gnt; locked flag implies previous-cycle lock_req for the same owner; consecutive locked cycles <= MAX_LOCK (burst <= MAX_LOCK+1) when MAX_LOCK>0; no idle cycle when req!=0 (work-conserving); RR order; bounded wait
- A cycle-accurate reference model with a scoreboard is described
- Directed tests for every S9 corner case are listed
- A parameter sweep is listed: N in {2,3,16,31,32} x MAX_LOCK in {0,1,4}, plus a formal bounded proof for small N; for MAX_LOCK=0 the bounded-wait property is proven under an assume of finite lock duration
- Coverage goals include each requester granted, lock expiry hit, lock released early by dropped req, and sole-requester re-grant after expiry

## S11. Record assumptions and open questions (backpressure, output timing, RR structure, idle pointer, timing budget, reset sync, R7/R11 caveat)

**Goal:** Collect every remaining defaulted decision and record the resolved clarifications from Q1-Q3 so the spec author can confirm them.

**Feeds:** Assumptions & Open Questions · **Depends on:** S2, S3, S4, S5, S7, S8

**Spec evidence:**
- [P3] "MAX_LOCK = 0 means unlimited."
- [P3] "Must close timing at 500 MHz in 7 nm for N=16."

**Done when:**
- Every remaining defaulted decision (D2, D3, D4, D5, D10, D11) is listed with its chosen default and an open question
- Resolved decisions D6, D7 and D8 are recorded as confirmed clarifications, including the 'set MAX_LOCK=L-1 to include the first cycle' guidance
- The R7/R11 caveat for MAX_LOCK=0 is stated explicitly
- The discrepancy between the user-quoted (N-1)*MAX_LOCK bound and the derived bound under continuation-only counting is recorded for confirmation
- The I/O timing budget and external reset-sync assumptions are recorded

## Assumptions (defaults not confirmed by the user)

- D2 Downstream backpressure / grant-accept input: No accept/ready input. Every asserted grant counts as a served cycle for pointer and lock-counter updates. (medium impact, medium confidence)
- D3 Timing of index/valid/locked outputs: gnt_idx (width $clog2(N)), gnt_valid (= |gnt) and gnt_locked are combinational and cycle-aligned with gnt. (medium impact, high confidence)
- D4 Round-robin implementation structure: Dual masked/unmasked fixed-priority encoders with a registered thermometer mask derived from the last granted index. Each find-first is implemented as a log-depth prefix-OR. (medium impact, medium confidence)
- D5 Pointer update policy: The registered pointer/mask updates to the granted index in every cycle gnt_valid=1, including locked-continuation cycles. It holds its value when no grant is given. (medium impact, high confidence)
- D10 I/O timing budget assumption for the combinational path: Assume req and lock are launched from flops in the masters and gnt/idx are captured by flops or a mux in the resource. The arbiter's req->gnt and req->idx logic is budgeted at about 1 ns of the 2 ns period. (medium impact, medium confidence)
- D11 Reset style and deassertion synchronisation: All state flops use async active-low reset (always @(posedge clk or negedge rst_n)). Synchronous deassertion is the integrator's responsibility; no internal synchroniser is added. (low impact, medium confidence)
