# MA plan: 20_rv32i_5stage_pipeline

## S1. Scope the Fivestage RV32I core: R1 instruction list, exclusions, and trap-to-halt treatment of ECALL/EBREAK/FENCE.I

**Goal:** Write the Overview. Fivestage is a 5-stage in-order RV32I core with Harvard TCM ports, a retire-trace port and a halt-on-trap mechanism. State which RV32I v2.1 encodings are implemented and which are excluded (CSRs, interrupts, privilege). State that ECALL, EBREAK, illegal encodings and any encoding outside the R1 list (such as FENCE.I) trap in EX and halt the core. No trap vectoring exists.

**Feeds:** Overview, Assumptions & Open Questions · **Depends on:** none

**Spec evidence:**
- [P1] "RV32I core"
- [P2] "Implement the RISC-V RV32I base integer ISA (unprivileged spec v2.1)"
- [P2] "FENCE may be a no-op."
- [P2] "No CSRs, interrupts or privilege modes in this version."
- [P2] "Illegal instruction handling: TBD."

**Decisions:**
- D1 Handling of ECALL, EBREAK and FENCE.I (encodings not listed in R1): **ECALL and EBREAK trap in EX and halt the core, as the user's answer to Q2 states. FENCE.I is not in the R1 list, so it is decoded as an illegal encoding and takes the same halt path. FENCE (all fm/pred/succ variants) executes as a NOP and retires.** (decided)
  - options: Execute as architectural NOPs that retire normally / Treat as traps that halt the core (same path as illegal instructions) / EBREAK halts; ECALL as NOP
  - The user answer to Q2 explicitly puts ECALL and EBREAK on the illegal/halt path. FENCE.I belongs to Zifencei, is absent from R1, and therefore falls under 'illegal encodings'.

**Done when:**
- The Overview lists every R1 mnemonic grouped by format (R/I/S/B/U/J).
- The Overview states that FENCE is a retiring NOP, and that ECALL, EBREAK, FENCE.I and other non-R1 encodings halt the core.
- The R7 exclusions are listed, and it is noted that halt is the only trap response (no vectoring, no CSRs) and that only rst exits it.
- The Assumptions section records that FENCE.I is treated as illegal by inference from the R1 list.

## S2. Define the top-level ports: imem with enable, dmem with byte strobes, retire trace, halted/halt_pc, and the RESET_PC parameter

**Goal:** Specify every top-level port with its direction, width and timing:
- the instruction port: imem_addr = pc_next (combinational) and imem_en;
- the data port: address, enable, write enable, 4-bit byte strobe, write data, read data;
- the retire-trace bundle;
- the halted and halt_pc status outputs from the R11 answer;
- clock and reset.
Also specify the build-time parameters.

**Feeds:** Interface, Parameters · **Depends on:** S1

**Spec evidence:**
- [P2] "Harvard memory: separate instruction and data ports."
- [P2] "Both are synchronous memories with a fixed 1-cycle read latency and no wait states (tightly coupled SRAM)."
- [P2] "The data port supports byte, halfword and word access with byte write strobes."
- [P2] "Reset vector is configurable at build time."
- [P2] "Provide a retire-trace port (PC, instruction, rd, write data, valid)"

**Decisions:**
- D2 Memory port handshake: **There is no ready or stall input from either memory. The core drives address, enable and strobes, and assumes read data is valid exactly one cycle after an enabled request. The SRAM holds its output while enable is deasserted.** (decided)
  - options: No handshake: request/enable only, data always valid exactly 1 cycle later / Valid/ready handshake for future wait-state support
  - R5 mandates a fixed 1-cycle latency with no wait states (TCM). The Q1 answer relies on the SRAM holding its output when imem_en is low.

**Done when:**
- The port table gives name, direction, width and description for the imem, dmem, trace, halted, halt_pc, clk and rst ports.
- It is stated that imem_addr is combinational from the next-PC mux and that halted is a registered output.
- Read-data timing relative to the address/enable cycle is stated for both memory ports, including the hold-output assumption when enable is low.
- The byte-strobe meaning and the store-data lane replication rule are given for SB/SH/SW.
- The parameter table includes RESET_PC (the reset vector) with a default value, and any address-width parameter is justified or omitted.

## S3. IF stage: combinational imem_addr = pc_next, registered pc_f, SRAM output feeding IF/ID

**Goal:** Document the fetch organisation agreed in Q1:
- the next-PC mux selects RESET_PC (during reset), ex_target (on redirect), the held PC (on stall or halt), or pc_f+4;
- imem_addr = pc_next and pc_f is registered from pc_next, so imem_rdata lines up with pc_f in IF and is captured into IF/ID;
- imem_en is deasserted on a load-use stall or while halted;
- on a redirect, the younger IF/ID contents are squashed through their valid bits.

**Feeds:** Datapath, Timing & Pipeline, Block Diagram · **Depends on:** S2

**Spec evidence:**
- [P2] "Classic 5-stage in-order pipeline: IF, ID, EX, MEM, WB."
- [P2] "Both are synchronous memories with a fixed 1-cycle read latency and no wait states (tightly coupled SRAM)."
- [P2] "Target CPI close to 1."

**Decisions:**
- D3 Fetch organisation with synchronous imem: **The imem address is combinational from the next-PC mux: imem_addr = pc_next.
- pc_f is registered from pc_next, so imem_rdata in the next cycle aligns with pc_f in IF and is captured into IF/ID.
- On a load-use stall or while halted, imem_en = 0 so the SRAM holds its output.
- On a redirect, the address becomes ex_target and the younger IF/ID instruction is squashed by clearing its valid bit.
- During reset, the address is RESET_PC with imem_en = 1.** (decided)
  - options: imem address driven combinationally from the next-PC mux; pc_f registered from pc_next; imem_rdata captured into IF/ID / imem address from the PC register with an extra fetch stage / Separate IF/ID flop after the SRAM output
  - Settled by the user's answer to Q1.

**Done when:**
- The next-PC mux inputs and priority are specified: reset > redirect > stall/halt hold > pc_f+4.
- imem_en is specified for each condition (reset, normal, load-use stall, redirect, halted), and it is shown that ID keeps the correct instruction across a stall.
- Cycle diagrams cover the sequential fetch, the redirected stream, and the transition into halt.
- The combinational path EX redirect → pc_next → imem_addr is called out for timing.

## S4. ID stage: decoder with illegal detection, immediate generator and 2R1W register file with x0 hard-wired

**Goal:** Specify the decode of all R1 opcodes into control fields:
- ALU op and operand selects;
- memory size and sign;
- write-back select;
- branch/jump type;
- rd write enable;
- rs1/rs2-used flags;
- an illegal/trap flag covering non-R1 encodings, ECALL, EBREAK and FENCE.I.
Also specify the I/S/B/U/J immediates and the register file, including how a same-cycle WB write and ID read are resolved.

**Feeds:** Datapath, Control Logic · **Depends on:** S3

**Spec evidence:**
- [P2] "x0 is hard-wired to zero."
- [P2] "Resolve data hazards with forwarding wherever possible; stall only for load-use."
- [P2] "Illegal instruction handling: TBD."

**Decisions:**
- D4 Register-file WB→ID same-cycle hazard: **Use a flop-based 31×32 register file written on posedge, with a combinational write-through bypass on address match (rd≠0).** (default, low impact, high confidence)
  - options: Write-through bypass inside the register file / Write on negedge / Third forwarding source from WB into ID/EX
  - This keeps a single clock edge (R8) and needs no extra stall or forwarding source. It is standard practice for 5-stage cores.

**Done when:**
- A decode table maps each R1 instruction to its control-field values, including the rs1-used and rs2-used flags.
- The illegal-flag conditions are listed: opcode, funct3, funct7, the shift-immediate funct7 checks, ECALL/EBREAK/FENCE.I, and the low two bits ≠ 11.
- Immediate formats are given with bit slicing for I/S/B/U/J.
- The register file is specified with the x0 rule and the write-through bypass.
- The ID/EX register contents are listed, including valid, PC, instruction bits and the trap flag.

## S5. EX stage: ALU, branch comparator, target adders, forwarding network and trap detection point

**Goal:** Define the EX datapath:
- the ALU operations;
- branch condition evaluation, signed and unsigned;
- JAL/JALR/branch target computation, with JALR clearing bit 0;
- the link (PC+4) value;
- forwarding muxes for rs1, rs2 and store data, sourced from EX/MEM and MEM/WB.
Also define EX as the point where a valid trap-flagged instruction raises the halt request, using its PC as halt_pc.

**Feeds:** Datapath, Control Logic · **Depends on:** S4

**Spec evidence:**
- [P2] "Resolve data hazards with forwarding wherever possible; stall only for load-use."
- [P2] "Branches and jumps are resolved in EX. Static predict-not-taken. Flush wrong-path instructions on a redirect."

**Decisions:**
- D5 Forwarding paths: **Forward from EX/MEM (ALU or link result) and from MEM/WB (ALU, link or extended load data) into both EX operand muxes. These muxes also feed the branch comparator and the store-data path. The youngest producer wins. Load-use is the only stall, and it lasts 1 cycle.** (decided)
  - options: EX/MEM→EX and MEM/WB→EX (incl. load data) for both operands and store data; 1-cycle load-use stall / Additional MEM-stage store-data forwarding
  - R3 requires forwarding wherever possible and allows stalls only for load-use.
- D6 Control-transfer resolution point and penalty: **All branches, JAL and JALR resolve in EX, with static not-taken prediction. A taken branch or jump squashes the IF and ID instructions, giving 2 bubbles.** (decided)
  - options: All branches/JAL/JALR resolved in EX, 2-cycle taken penalty / JAL resolved early in ID
  - R4 explicitly requires resolution in EX.

**Done when:**
- The ALU op list covers all R1 ops, with shift-amount slicing.
- The forwarding-select equations are written, including the rd≠0, RegWrite and valid qualifications and the priority.
- Redirect target and redirect valid are defined for branches, JAL and JALR (target & ~1).
- The trap-request signal is defined as (EX valid & trap flag), together with how halt_pc is captured.
- It is stated that store data and the branch compare use forwarded values.

## S6. MEM/WB stages: dmem access timing, byte-lane strobes and load extension

**Goal:** Specify when the dmem address, enable, write enable, strobe and write data are driven. Specify that synchronous read data returns one cycle later, and how it is lane-selected and sign- or zero-extended for LB/LH/LW/LBU/LHU. Specify the write-back mux.

**Feeds:** Datapath, Timing & Pipeline, Corner Cases & Error Handling · **Depends on:** S5

**Spec evidence:**
- [P2] "The data port supports byte, halfword and word access with byte write strobes."
- [P2] "Misaligned accesses are not expected from the software."
- [P2] "Both are synchronous memories with a fixed 1-cycle read latency and no wait states (tightly coupled SRAM)."

**Decisions:**
- D7 dmem request stage and load-data alignment location: **Drive dmem from the EX/MEM register during MEM, so load data arrives in WB. Lane select and extension happen in WB using the registered addr[1:0] and size. The extended value is the MEM/WB forwarding source.** (default, medium impact, medium confidence)
  - options: Drive dmem from the EX/MEM register in MEM; data returns in WB; lane-select and extend in WB / Drive dmem combinationally from the EX ALU output so data returns in MEM
  - This keeps the ALU→SRAM-address path out of EX and keeps the load-use penalty at 1 cycle. The resulting critical path is SRAM out → extend → forward mux → ALU.
- D8 Misaligned data and instruction-target addresses: **There is no detection. Misaligned data accesses give implementation-defined lane behaviour. Branch and jump targets are used as computed, with bit 0 cleared for JALR, and misaligned targets are documented as undefined. They do not use the halt path.** (default, low impact, medium confidence)
  - options: No detection: use addr[1:0] for lane select; misaligned targets undefined / Detect and flag via an output, or halt like an illegal instruction
  - R6 says software will not generate misaligned accesses. The halt path from the R11 answer is scoped to illegal encodings, ECALL and EBREAK only.

**Done when:**
- A byte-strobe table is given per size and addr[1:0], together with the write-data lane replication.
- Load extraction and extension equations are given for all five load types.
- dmem request and response timing is shown relative to the stages.
- The write-back mux sources are listed: ALU, PC+4, load data, LUI immediate and AUIPC result.
- It is stated that the dmem enable and write are qualified by MEM valid.

## S7. Hazard and halt control: load-use stall, redirect flush, trap-halt sequence and imem_en

**Goal:** Define the stall, flush and halt control.
- Load-use: compare the ID rs1/rs2 (when actually used) against an EX load's rd. On a match, hold pc_f and IF/ID, set imem_en = 0, and insert a bubble into ID/EX.
- Redirect in EX: squash IF/ID and ID/EX.
- Trap in EX: flush the younger IF/ID and ID/EX, kill the trapping instruction so it neither retires nor writes, let the older MEM and WB instructions drain and retire, set the registered halted flag, and stop fetch with imem_en = 0.
Define the priority among these events.

**Feeds:** Control Logic, Timing & Pipeline · **Depends on:** S3, S5, S6

**Spec evidence:**
- [P2] "stall only for load-use."
- [P2] "Flush wrong-path instructions on a redirect."
- [P2] "Static predict-not-taken."
- [P2] "Illegal instruction handling: TBD."

**Decisions:**
- D9 Bubble representation in the pipeline: **Each pipeline register carries a valid bit. Flush, stall and trap bubbles clear it. Every side effect is qualified by it: RegWrite, dmem enable and write, redirect, trap request and trace valid.** (default, medium impact, high confidence)
  - options: Per-stage valid bit gating all side effects / Inject canonical NOP into pipeline registers
  - This makes trace valid trivial and guarantees that squashed stores never reach dmem. It also fits the Q1 answer, which already squashes IF/ID by clearing valid bits.
- D12 Illegal instruction handling (R11): **Illegal encodings, ECALL and EBREAK trap in EX and halt the core.
- halted is asserted as a registered output, and halt_pc gives the trapping PC.
- Older instructions drain and retire.
- The trapping instruction does not retire, and younger instructions are flushed.
- Fetch stops, and only rst exits the halt.** (decided)
  - options: NOP + flag output / Halt the core with an error output / Silently NOP
  - Settled by the user's answer to Q2.

**Done when:**
- The load-use equations are written, excluding unused rs1/rs2 (LUI, AUIPC, JAL), rd=x0 and invalid or trap-flagged ID instructions.
- Priority is stated and justified: reset > trap/halt > redirect > load-use stall.
- imem_en and pc_next are consistent with S3 during stall, flush and halt.
- The halt state machine is specified: the trap request sets halted on the next edge, halted is sticky until rst, halt_pc is captured, and no new valid instructions enter.
- Cycle diagrams cover load-use, a taken branch, JALR after a load, back-to-back taken branches, and an illegal instruction behind an older load and store.

## S8. Clocking and synchronous reset sequence to RESET_PC, including exit from halt

**Goal:** Specify the single clock domain and the synchronous active-high reset. Specify which flops are reset: PC, all valid bits, halted and halt_pc as needed. Specify which are left unreset: the datapath and the register file. Specify the first fetch: imem_addr = RESET_PC with imem_en = 1 during reset, so that the first instruction reaches ID on the correct cycle after reset is released. State that rst is the only exit from halt.

**Feeds:** Clocking & Reset · **Depends on:** S3, S7

**Spec evidence:**
- [P2] "Reset vector is configurable at build time. Single clock, synchronous active-high reset."

**Decisions:**
- D10 Reset scope and first fetch: **Single clock with synchronous active-high reset.
- pc_f is set to RESET_PC, all valid bits are cleared and halted is cleared.
- During reset, imem_addr = RESET_PC with imem_en = 1, as in the Q1 answer.
- The register file is not reset; x0 is hard-wired.** (decided)
  - options: Reset PC, valid bits and halt state only; register file not reset; imem_addr = RESET_PC with imem_en=1 during reset / Reset all flops including the register file
  - R8 and the Q1/Q2 answers settle the clock, the reset style, the vector, the first-fetch behaviour and that rst exits the halt.

**Done when:**
- A reset-value table is given for every control flop, including halted and halt_pc.
- A cycle-by-cycle sequence runs from reset deassertion to the first retire, without a duplicate fetch of RESET_PC.
- It is stated that asserting rst while halted restarts from RESET_PC.
- It is stated that there are no other clock domains and no CDC.

## S9. Retire-trace port sourced from WB for ISS lock-step, with halt-aware retirement

**Goal:** Define the trace port. At most one instruction retires per cycle, in program order, from WB. The fields are valid, PC, instruction, rd and write data, where write data is the final extended load value. Define how non-writing instructions are reported. State that the trapping instruction never asserts trace valid, so the ISS comparison ends at the last older retire and the testbench uses halted/halt_pc to check the trap.

**Feeds:** Interface, Datapath, Verification Plan · **Depends on:** S6, S7

**Spec evidence:**
- [P2] "Provide a retire-trace port (PC, instruction, rd, write data, valid) for lock-step comparison with a reference ISS."

**Decisions:**
- D11 Trace port timing and content for non-writing instructions: **Drive the trace combinationally from the WB stage, with valid = WB valid. Instructions with no register write, or with rd=x0, report rd=0 and data=0. Stores are traced only by PC and instruction. The trapping instruction is not traced.** (default, medium impact, medium confidence)
  - options: Combinational from WB; rd=0 and wdata=0 when no register write; no extra fields / Registered one cycle after WB / Add mem address/data/strobe and a reg-write-enable field
  - This matches R10's field list and the Q2 answer that the trapping instruction does not retire. The lack of store visibility is recorded as an open question.

**Done when:**
- Trace field widths and their sourcing from the MEM/WB registers are specified.
- It is shown that PC and instruction bits are carried down the pipeline.
- The rule for non-writing instructions is stated.
- It is confirmed that flushed, bubbled and trapping instructions never assert valid, and that older instructions in MEM/WB at trap time still retire.

## S10. Corner cases: trap interactions, x0, and hazard combinations

**Goal:** Document the corner cases with their expected behaviour:
- Trap interactions: a trap-flagged instruction in the shadow of a taken branch (squashed, no halt); a trap in EX while an older store is in MEM (the store completes); a trap-flagged instruction stalled behind a load-use (no spurious stall from garbage rs fields); a trap in EX coinciding with a redirect being impossible (same stage, one instruction).
- x0: forwarding suppression for rd=x0 and loads to x0.
- Hazard combinations: a branch or JALR depending on a load (stall then forward), store data forwarded from a load, and a redirect with a pending load-use stall.

**Feeds:** Corner Cases & Error Handling, Assumptions & Open Questions · **Depends on:** S4, S7, S9

**Spec evidence:**
- [P2] "Illegal instruction handling: TBD."
- [P2] "No CSRs, interrupts or privilege modes in this version."
- [P2] "x0 is hard-wired to zero."
- [P2] "Misaligned accesses are not expected from the software."

**Done when:**
- A corner-case table lists each combination above with the expected behaviour and cycle count.
- It is stated that a trap-flagged instruction on the wrong path never sets halted.
- The misaligned-access behaviour from D8 is recorded.

## S11. Block diagram and end-to-end pipeline timing for Fivestage

**Goal:** Produce the consolidated block diagram:
- the five stages, pipeline registers and two SRAM ports;
- the combinational pc_next → imem_addr path;
- the forwarding network, hazard and halt unit, redirect path and trace tap.
Produce a timing summary with CPI analysis (load-use = 1 stall, taken transfer = 2 bubbles) and the critical paths.

**Feeds:** Block Diagram, Timing & Pipeline · **Depends on:** S3, S4, S5, S6, S7, S9

**Spec evidence:**
- [P2] "Classic 5-stage in-order pipeline: IF, ID, EX, MEM, WB."
- [P2] "Target CPI close to 1."

**Done when:**
- The diagram shows every pipeline register, the SRAM output captured into IF/ID, and the halt logic.
- A penalty table covers each hazard class, plus the trap-drain behaviour.
- At least two critical paths are identified: EX redirect → pc_next → imem_addr, and dmem rdata → extend → forward → ALU/branch compare → redirect.

## S12. Verification plan: ISS lock-step via the trace port, halt checks and directed hazard tests

**Goal:** Plan verification:
- run a reference ISS in lock-step on trace valid;
- run riscv-tests rv32ui, adapting the pass/fail signalling to ECALL/EBREAK halting;
- run constrained-random aligned streams;
- add directed forwarding, stall and flush tests, strobe and extension checks, x0 checks, and reset-vector checks;
- add trap tests for illegal encodings, ECALL, EBREAK and FENCE.I that check halted, halt_pc, the drain of older instructions and that the trapping instruction does not retire;
- add assertions and coverage.

**Feeds:** Verification Plan, Assumptions & Open Questions · **Depends on:** S9, S10, S11

**Spec evidence:**
- [P2] "for lock-step comparison with a reference ISS."
- [P2] "Misaligned accesses are not expected from the software."
- [P2] "Target CPI close to 1."

**Done when:**
- The testbench is described: 1-cycle SRAM models that hold their output when enable is low, the ISS comparator, the store checker and the halt monitor.
- The test list maps to requirements R1–R11.
- Assertions are listed: no dmem write while invalid; x0 never written; at most one retire per cycle; single-cycle load-use stall; imem_en=0 and no retire after halted except for older drains; halted sticky until rst.
- A CPI measurement is planned.
- The remaining defaulted decisions (D4, D7, D8, D9, D11) are listed as open questions in Assumptions.

## Assumptions (defaults not confirmed by the user)

- D4 Register-file WB→ID same-cycle hazard: Use a flop-based 31×32 register file written on posedge, with a combinational write-through bypass on address match (rd≠0). (low impact, high confidence)
- D7 dmem request stage and load-data alignment location: Drive dmem from the EX/MEM register during MEM, so load data arrives in WB. Lane select and extension happen in WB using the registered addr[1:0] and size. The extended value is the MEM/WB forwarding source. (medium impact, medium confidence)
- D8 Misaligned data and instruction-target addresses: There is no detection. Misaligned data accesses give implementation-defined lane behaviour. Branch and jump targets are used as computed, with bit 0 cleared for JALR, and misaligned targets are documented as undefined. They do not use the halt path. (low impact, medium confidence)
- D9 Bubble representation in the pipeline: Each pipeline register carries a valid bit. Flush, stall and trap bubbles clear it. Every side effect is qualified by it: RegWrite, dmem enable and write, redirect, trap request and trace valid. (medium impact, high confidence)
- D11 Trace port timing and content for non-writing instructions: Drive the trace combinationally from the WB stage, with valid = WB valid. Instructions with no register write, or with rd=x0, report rd=0 and data=0. Stores are traced only by PC and instruction. The trapping instruction is not traced. (medium impact, medium confidence)
