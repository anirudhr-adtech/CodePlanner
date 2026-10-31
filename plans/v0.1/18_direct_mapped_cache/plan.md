# MA plan: 18_direct_mapped_cache

## S1. Fix cache geometry, address split and write-back/write-allocate policy for the 4 KiB direct-mapped Kestrel D-cache

**Goal:** Write the overview: 4 KiB, 32-byte lines, 128 lines. Show the 32-bit byte-address split into tag[31:12] (20 bits), index[11:5] (7 bits), word[4:2] and byte[1:0]. Record write-back with write-allocate and the bus-sharing reason for it. State that every CPU-port access is cacheable and that no maintenance ops exist in this version. Define the parameters and mark which are fixed by the spec and which may be generalised.

**Feeds:** Overview, Parameters · **Depends on:** none

**Spec evidence:**
- [P3] "direct-mapped, 4 KiB, 32-byte"
- [P3] "The core is a 32-bit in-order pipeline with byte-addressed, 32-bit-wide loads and"
- [P3] "it uses byte strobes for sub-word stores. Policy is write-back with"
- [P3] "We looked at write-through, but the bus is shared with the DMA and the"

**Decisions:**
- D1 Write policy: **Write-back with write-allocate. A store miss always refills the line before merging.** (decided)
  - options: write-back + write-allocate / write-through + no-allocate
  - P3 states this explicitly. The bus also forces it: the write-data channel has no byte strobes and only full-line bursts exist.

**Done when:**
- Address split table gives tag/index/word/byte bit ranges, and the ranges sum to 32 bits
- Parameter table lists ADDR_W, CACHE_BYTES and LINE_BYTES, plus derived NUM_LINES=128, WORDS_PER_LINE=8 and TAG_W=20, and marks which are fixed
- Overview states the direct-mapped, write-back and write-allocate policy and why write-through was rejected
- Overview states that all CPU-port accesses are cacheable and that no flush/invalidate exists in this version

## S2. Define the CPU request/response port and the interconnect burst port signal by signal

**Goal:** Specify both external interfaces with widths, directions and handshake rules.
- CPU side: req valid/ready carrying addr, we, wdata and wstrb; a single resp_valid with rdata; responses in order with no ID; no uncached bit.
- Bus side: request channel (line-aligned addr, rw, valid/ready); write-data channel (valid/ready/last, no strobes); read-data channel (valid/last, no ready); write-done pulse.
- Protocol consequences: no error signalling, read data must always be sunk, no partial-line writes.
- There is no maintenance sideband port.

**Feeds:** Interface · **Depends on:** S1

**Spec evidence:**
- [P4] "On the CPU side, the core issues one request at a time using a valid/ready handshake"
- [P4] "(address, read/write, write data, byte strobes)"
- [P4] "per hit. Responses come back in order on a single response-valid strobe. The core always"
- [P4] "waits for each response, so you don't need an ID."
- [P5] "channel (line-aligned address, read/write) with valid/ready, a write-data channel with"
- [P5] "valid/ready/last, a read-data channel with valid/last (the cache must always accept read"
- [P5] "data, so there's no ready), and a write-done pulse when a write burst is committed. Bursts"
- [P5] "are always one full line, 8 beats of 32 bits, in incrementing order starting at word 0."

**Done when:**
- Every port is listed in a table with name, direction, width and description
- Handshake rules are stated: a transfer occurs on valid&&ready, and the payload is held stable while valid&&!ready
- Rules state that bus read data is accepted unconditionally on every valid beat and that write-done is a single-cycle pulse
- Interface notes record that the write-data channel has no strobes and the bus has no error response
- Interface notes record whether wstrb is ignored on loads
- The interface table has no uncached or maintenance signals, and a note explains why

## S3. Lay out storage: data SRAM, tag SRAM, valid/dirty flop arrays and victim line buffer

**Goal:** Map the 4 KiB of data and the 128 tags onto single-port, 1-cycle synchronous SRAMs with byte enables. Keep valid and dirty in flops so that reset clears them in one cycle. Size the victim line buffer needed for evictions. Draw the top-level block diagram connecting the arrays, the lookup stage, the miss FSM and the two ports.

**Feeds:** Block Diagram, Datapath, Parameters · **Depends on:** S1

**Spec evidence:**
- [P6] "The physical design team says we get single-port synchronous SRAMs with 1-cycle read"
- [P6] "latency and byte-write enables. They would rather keep valid/dirty out of SRAM so a reset"
- [P6] "doesn't take 128 cycles."

**Decisions:**
- D2 Data SRAM organisation: **One 1024x32 single-port data SRAM addressed by {index,word} with 4 byte-write enables, plus a separate 128x20 single-port tag SRAM.** (default, medium impact, high confidence)
  - options: 1024x32 word-wide single-port SRAM with 4 byte enables / 128x256 line-wide SRAM with 32 byte enables / 8 banks of 128x32
  - This matches both the 32-bit CPU access and the 32-bit bus beat. Refill writes and writeback reads move one word per cycle with no wide muxing, and the byte enables serve store strobes directly.
- D3 Location of valid/dirty state: **Valid and dirty live in two 128-bit flop arrays that reset clears. The tag SRAM is not initialised.** (decided)
  - options: 128-entry valid and dirty flop arrays / valid/dirty bits in tag SRAM
  - P6 asks to keep valid/dirty out of SRAM so that reset does not take 128 cycles.

**Done when:**
- Block diagram shows the CPU port, lookup/compare stage, data SRAM, tag SRAM, valid/dirty flops, victim buffer, miss FSM and bus port, with no maintenance or uncached path
- Each array has its depth, width, port type and address source listed
- The read and write uses of each SRAM port are enumerated per operation: load hit, store hit, refill and writeback

## S4. Design the 1-cycle load-hit pipeline that accepts a request every cycle

**Goal:** Define the two-stage flow. In the accept cycle, the CPU address drives the tag and data SRAM reads. In the next cycle, the tag compare and valid check produce resp_valid and rdata. Work out how req_ready is generated so back-to-back read hits run at full rate without a combinational path from SRAM output to ready. Define what happens to a younger request that was already accepted when the older one misses.

**Feeds:** Datapath, Control Logic, Timing & Pipeline · **Depends on:** S2, S3

**Spec evidence:**
- [P4] "(address, read/write, write data, byte strobes). We'd like hits to return data the cycle"
- [P4] "after the request is accepted, with a new request accepted every cycle for back-to-back"
- [P4] "On the CPU side, the core issues one request at a time using a valid/ready handshake"

**Decisions:**
- D4 req_ready generation under back-to-back loads: **Speculative accept with a one-entry replay holding register. req_ready depends only on registered state (FSM idle, stage-1 not a store), never on the tag compare.** (default, medium impact, medium confidence)
  - options: Speculatively accept the next request; on a miss in stage 1, hold it in a replay register and re-read the SRAMs after the miss / Gate req_ready combinationally on the stage-1 hit result
  - This keeps the SRAM-to-compare-to-ready-to-core path off the critical path while still giving full-rate read hits. At most one younger request can be in flight.

**Done when:**
- Stage diagram shows what happens in the accept cycle and in the response cycle of a load hit
- The req_ready equation uses only registered signals
- The replay path is defined: the younger request is held, and its SRAM read is redone after the miss completes
- A waveform shows 4 back-to-back load hits with one response per cycle

## S5. Design the store-hit path within the 2-cycle budget on single-port SRAM

**Goal:** A store needs the tag compare (from an SRAM read) before its byte-enabled data write, and the data SRAM has only one port. Define:
- when the write happens,
- how the next request is held off,
- when the store response is returned,
- when the dirty bit is set.
Show that loads following stores see the correct data.

**Feeds:** Datapath, Control Logic, Timing & Pipeline · **Depends on:** S4

**Spec evidence:**
- [P4] "read hits. Stores can be slower if it helps, but please don't make them more than 2 cycles"
- [P3] "it uses byte strobes for sub-word stores. Policy is write-back with"
- [P6] "latency and byte-write enables. They would rather keep valid/dirty out of SRAM so a reset"

**Decisions:**
- D5 Store hit implementation: **2-cycle store with no store buffer. The data SRAM byte-write happens in the compare cycle, and the response is issued in that same cycle. req_ready is deasserted during that cycle, so stores sustain one every 2 cycles.** (default, medium impact, high confidence)
  - options: 2-cycle store: read tag in cycle 1, compare and byte-write data SRAM in cycle 2, req_ready low for that cycle / Store buffer: write deferred into a free SRAM cycle, with load forwarding
  - This meets the stated limit of 2 cycles per store hit. It avoids a store buffer and its forwarding and hazard logic.

**Done when:**
- A cycle-by-cycle table for a store hit gives SRAM port use, the dirty-bit update and response timing
- Waveforms cover store→load to the same word and load→store→load
- Data SRAM byte enables are derived from wstrb only on a store hit

## S6. Design the miss engine: dirty-victim writeback, full-line refill and store-miss allocate

**Goal:** Define the miss/refill FSM for a blocking cache. On a miss it must:
- if the victim is dirty, read its 8 words out of the data SRAM (1-cycle latency) and burst them on the write channel under ready backpressure;
- issue the line read;
- write the 8 incoming beats into the data SRAM unconditionally;
- update the tag, valid and dirty state;
- complete the original load or store.
Decide the ordering between the writeback burst, write-done and the refill read.

**Feeds:** Control Logic, Datapath, Timing & Pipeline, Block Diagram · **Depends on:** S3, S4, S5

**Spec evidence:**
- [P5] "are always one full line, 8 beats of 32 bits, in incrementing order starting at word 0."
- [P5] "valid/ready/last, a read-data channel with valid/last (the cache must always accept read"
- [P5] "data, so there's no ready), and a write-done pulse when a write burst is committed. Bursts"
- [P5] "Read latency on the interconnect is variable, typically 10–20 cycles."
- [P7] "for MMIO, and whether to do critical-word-first. Make a call and tell us what you assumed."

**Decisions:**
- D6 Dirty eviction structure and ordering vs. refill: **8-word victim buffer. Copy the victim out of the SRAM (8 cycles), issue the refill read request, and send the writeback burst from the buffer in parallel. Any later miss that needs the victim buffer, or that reads the victim's line address, waits for write-done of the outstanding writeback.** (default, medium impact, medium confidence)
  - options: Copy victim into an 8x32 victim buffer, then issue the refill read and drain the writeback in parallel / Serial: write back the victim, wait for write-done, then issue the refill read / Read the victim directly from the SRAM into the write channel with a skid register
  - This takes the writeback off the critical refill path on a 10–20 cycle bus. Using write-done as the commit point preserves read-after-write ordering on the shared interconnect without assuming the channels are ordered.
- D7 Store-miss handling: **Refill the whole line, then replay the original request (load or store) through the lookup pipeline. The response comes from the replayed hit.** (default, low impact, medium confidence)
  - options: Refill the line, then replay the store through the normal store-hit path / Merge store bytes into the matching refill beat as it is written
  - This reuses the hit datapath and keeps a single response source. The cost is 1–2 extra cycles per miss.
- D8 Critical-word-first / early restart: **No critical-word-first, because the bus cannot reorder beats, and no early restart. The response is returned after all 8 beats are written and the access is replayed.** (default, low impact, medium confidence)
  - options: None: respond after the full line is refilled / Early restart: forward the requested word as its beat arrives (bus order is fixed from word 0) / Critical-word-first (not possible: bursts always start at word 0)
  - P5 fixes burst order starting at word 0, so true CWF would need interconnect changes. Early restart adds forwarding and hazard logic that a first cut does not need.

**Done when:**
- The FSM diagram shows every state, every transition condition, and the SRAM and bus usage in each state
- No state can drop a read-data beat: the data SRAM is guaranteed free whenever rd_valid can occur
- The writeback read path handles the 1-cycle SRAM latency and wr_ready backpressure without losing or duplicating a beat
- Tag, valid and dirty updates are specified for a clean miss, a dirty miss and a store miss
- A miss latency formula is given for clean and dirty misses as a function of bus read latency

## S7. Document the agreed scope: no uncached/MMIO path and no cache maintenance in this version

**Goal:** Record the user-confirmed answers to the P7 open items. The cache has no uncached path; the core or a wrapper must decode MMIO and route it around the cache. The cache has no flush or invalidate of any kind. State the architectural consequences:
- an MMIO-addressed request reaching the cache is cached like any other;
- DMA coherence is not maintained by the cache, so dirty data reaches memory only on natural eviction.
List the proposed follow-ups as non-implemented hooks: a flush_req/inv_req sideband walking 128 indices, and a cpu_req_uncached bit with single-beat bus transactions. Note which structures already make them cheap, such as the flop-based valid/dirty and the reusable writeback path.

**Feeds:** Interface, Control Logic, Assumptions & Open Questions · **Depends on:** S2, S6

**Spec evidence:**
- [P7] "Things we haven't decided yet: cache maintenance ops (flush/invalidate), uncached regions"
- [P7] "for MMIO, and whether to do critical-word-first. Make a call and tell us what you assumed."
- [P3] "We looked at write-through, but the bus is shared with the DMA and the"

**Decisions:**
- D9 Uncached / MMIO support: **No uncached path. Every CPU-port request is cached, and the core or a wrapper must decode MMIO ranges and route them around the cache. A cpu_req_uncached bit with single-beat transactions is only a possible future option and would need an interconnect protocol extension.** (decided)
  - options: No uncached path: all accesses through this port are cacheable, and MMIO is routed around the cache by the core/SoC / Parameterised uncached address window using full-line bursts / Add a separate single-beat uncached bus port
  - Settled by the user's answer to Q1.
- D10 Cache maintenance operations: **No maintenance ops and no invalidate path in this version. A flush_req/inv_req sideband walking all 128 indices is only a proposed follow-up.** (decided)
  - options: Sideband maintenance port with whole-cache clean+invalidate (flush) and invalidate-all / Per-address clean/invalidate encoded as extra CPU request types / No maintenance ops
  - Settled by the user's answer to Q2.

**Done when:**
- The MA states explicitly that an access to an MMIO address that reaches the cache is treated as cacheable, and that the integrator is responsible for routing MMIO around the cache
- The MA states that there are no flush/invalidate ports and that valid/dirty can be cleared only by reset
- DMA coherence limitations are stated: DMA may read stale memory for dirty lines, and DMA writes are not visible to cached lines
- The future flush/inv sideband and uncached-bit extensions are described as not implemented, and the MA identifies the structures (valid/dirty flops, writeback path, FSM idle state) that would accommodate them

## S8. Consolidate cycle-level timing for every access class

**Goal:** Write the timing chapter: latency and throughput for load hit, store hit, clean miss, dirty miss and back-to-back mixes. Include waveforms of both ports so the CPU-side guarantees in P4 and the bus-side behaviour in P5 can be checked against the design.

**Feeds:** Timing & Pipeline · **Depends on:** S4, S5, S6

**Spec evidence:**
- [P4] "after the request is accepted, with a new request accepted every cycle for back-to-back"
- [P4] "read hits. Stores can be slower if it helps, but please don't make them more than 2 cycles"
- [P5] "Read latency on the interconnect is variable, typically 10–20 cycles."

**Done when:**
- The latency/throughput table covers load hit (1/1), store hit (1/2), clean miss, dirty miss, and a miss that must wait for an earlier write-done
- Waveforms are given for a load-hit stream, a store-hit stream, a load miss with a dirty victim, and a miss with a speculatively accepted younger request
- The critical combinational path (SRAM output → tag compare → resp mux) is identified, and req_ready is shown to be off it

## S9. Specify the single clock domain and reset behaviour of flop state vs. SRAM contents

**Goal:** Document the one clock shared by the core, the cache and the interconnect. Define the reset style and which state is reset: valid/dirty arrays, FSM, handshake outputs, victim buffer and replay register. Make sure the tag and data SRAMs need no initialisation, as the PD team asked. Note that reset is the only way to invalidate the cache in this version.

**Feeds:** Clocking & Reset · **Depends on:** S3

**Spec evidence:**
- [P6] "latency and byte-write enables. They would rather keep valid/dirty out of SRAM so a reset"
- [P6] "doesn't take 128 cycles."

**Decisions:**
- D11 Clocking and reset style: **The cache, core and interconnect share a single clock. Reset is active-low, asserted asynchronously and deasserted synchronously. The valid/dirty arrays and all control and handshake flops are reset; SRAM contents and datapath registers are not.** (default, medium impact, medium confidence)
  - options: Single clock, synchronous active-low reset / Single clock, asynchronous-assert/synchronous-deassert reset / Separate core and bus clocks with CDC
  - The spec mentions no second clock. Async-assert/sync-deassert is common practice for microcontroller blocks, and it keeps reset to one cycle as P6 wants.

**Done when:**
- The clock and reset ports are defined, with reset polarity and synchronisation
- A table lists every stateful element and whether it is reset, and to what value
- The MA states that no handshake output (req_ready, resp_valid, bus valids) is asserted during reset or in the cycle after it
- The MA notes that reset discards dirty data without writeback, because no flush exists

## S10. Enumerate corner cases specific to this blocking write-back cache

**Goal:** List and resolve the hazardous scenarios and their required behaviour:
- a miss to the same index as the line being evicted;
- a re-miss to the just-evicted address before write-done;
- a store with all strobes zero;
- a load immediately after a store to the same word;
- a younger accepted request when the older one misses;
- back-to-back rd_valid beats with no gaps;
- wr_ready held low mid-burst;
- a stray rd_valid or write-done with nothing outstanding;
- misaligned addresses;
- an MMIO address arriving at the cache despite the routing assumption.

**Feeds:** Corner Cases & Error Handling · **Depends on:** S6, S7

**Spec evidence:**
- [P5] "valid/ready/last, a read-data channel with valid/last (the cache must always accept read"
- [P5] "data, so there's no ready), and a write-done pulse when a write burst is committed. Bursts"
- [P4] "per hit. Responses come back in order on a single response-valid strobe. The core always"

**Done when:**
- Each corner case has its trigger, its required behaviour and the mechanism that guarantees it
- The MA states that there is no bus error handling, because the protocol has none
- The MA lists the assumed core behaviour for misaligned accesses
- Protocol violations from the bus (unexpected rd_valid or write-done) are given a defined behaviour: ignore or assertion
- A misrouted MMIO access is documented as cached normally, and an optional simulation-only assertion hook on a configurable MMIO range is described

## S11. Plan verification against a reference memory model with a randomised interconnect

**Goal:** Define the testbench:
- a scoreboard comparing every load response against a flat golden memory;
- a bus model with randomised read latency (including under 10 and over 20 cycles) and random wr_ready backpressure;
- directed tests for each corner case in S10.
Add assertions for both handshake protocols and coverage of hit/miss/dirty combinations. Check memory consistency at end of test by comparing golden memory against bus memory merged with the cache's dirty lines, since no flush exists.

**Feeds:** Verification Plan · **Depends on:** S8, S10

**Spec evidence:**
- [P5] "Read latency on the interconnect is variable, typically 10–20 cycles."
- [P4] "after the request is accepted, with a new request accepted every cycle for back-to-back"

**Done when:**
- Testbench components are listed: CPU driver, bus responder, golden memory, scoreboard, and a backdoor reader of cache state for end-of-test checks
- The directed test list maps one-to-one to the S10 corner cases, plus performance checks for the 1-cycle load hit and the 2-cycle store hit
- Assertions are listed for valid/ready stability, exactly 8 beats with last on beat 8, line-aligned bus addresses, and one response per accepted request
- Coverage points include index aliasing, dirty evictions, each strobe pattern, eviction under wr_ready backpressure, and replay of a speculatively accepted request

## S12. Record assumptions and open questions for the Arch team

**Goal:** Collect every defaulted decision (D2, D4–D8, D11) and every implicit assumption into one list that Arch can sign off. Implicit assumptions include: the core never issues misaligned accesses; DMA traffic is not snooped; MMIO is routed outside the cache. Record the resolved P7 items (no uncached path, no maintenance ops, no critical-word-first) and the proposed follow-ups. Each item states the consequence if the assumption is wrong.

**Feeds:** Assumptions & Open Questions · **Depends on:** S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11

**Spec evidence:**
- [P7] "Things we haven't decided yet: cache maintenance ops (flush/invalidate), uncached regions"
- [P7] "for MMIO, and whether to do critical-word-first. Make a call and tell us what you assumed."

**Done when:**
- Every defaulted decision appears with its chosen value and its question to Arch
- The three P7 items (maintenance, MMIO, critical-word-first) are answered explicitly, with the user-confirmed answers marked as such
- DMA coherence is called out as not provided by this version, and software must avoid sharing cacheable buffers with DMA
- The future extensions (flush_req/inv_req sideband, cpu_req_uncached with a single-beat bus extension) are listed as follow-ups

## Assumptions (defaults not confirmed by the user)

- D2 Data SRAM organisation: One 1024x32 single-port data SRAM addressed by {index,word} with 4 byte-write enables, plus a separate 128x20 single-port tag SRAM. (medium impact, high confidence)
- D4 req_ready generation under back-to-back loads: Speculative accept with a one-entry replay holding register. req_ready depends only on registered state (FSM idle, stage-1 not a store), never on the tag compare. (medium impact, medium confidence)
- D5 Store hit implementation: 2-cycle store with no store buffer. The data SRAM byte-write happens in the compare cycle, and the response is issued in that same cycle. req_ready is deasserted during that cycle, so stores sustain one every 2 cycles. (medium impact, high confidence)
- D6 Dirty eviction structure and ordering vs. refill: 8-word victim buffer. Copy the victim out of the SRAM (8 cycles), issue the refill read request, and send the writeback burst from the buffer in parallel. Any later miss that needs the victim buffer, or that reads the victim's line address, waits for write-done of the outstanding writeback. (medium impact, medium confidence)
- D7 Store-miss handling: Refill the whole line, then replay the original request (load or store) through the lookup pipeline. The response comes from the replayed hit. (low impact, medium confidence)
- D8 Critical-word-first / early restart: No critical-word-first, because the bus cannot reorder beats, and no early restart. The response is returned after all 8 beats are written and the access is replayed. (low impact, medium confidence)
- D11 Clocking and reset style: The cache, core and interconnect share a single clock. Reset is active-low, asserted asynchronously and deasserted synchronously. The valid/dirty arrays and all control and handshake flops are reset; SRAM contents and datapath registers are not. (medium impact, medium confidence)
