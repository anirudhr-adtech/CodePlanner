# Micro-architecture: `fivestage_rv32i`

## 1. Overview

`fivestage_rv32i` is an in-order, single-issue RV32I core with a classic five-stage
pipeline:

| Stage | Name | Work |
|-------|------|------|
| IF | Fetch | Instruction SRAM output for `pc_f`; next-PC selection. |
| ID | Decode | Decode, immediate generation, register-file read (with WB bypass), load-use hazard detection. |
| EX | Execute | Operand forwarding, ALU, branch compare and target, redirect, store-data/strobe formatting. |
| MEM | Memory | Data SRAM access (address, write data and strobes presented). |
| WB | Writeback | Load-data extraction and sign extension, register-file write, retire trace. |

Hazard strategy (R3, R4):
- **Forwarding** from EX/MEM and MEM/WB into EX covers every RAW dependency except load-use.
- **Load-use:** a 1-cycle stall (bubble into EX), then forward from WB.
- **Control:** predict not-taken. Branches, JAL and JALR resolve in EX. A redirect flushes the two younger instructions in IF and ID, a 2-cycle penalty.
- The register file writes in WB, and a **write-through bypass** lets ID read a value that WB writes in the same cycle.

Both memories are synchronous, with 1-cycle read latency (R5). The instruction SRAM is
addressed with `pc_next`, so its output is aligned with `pc_f` in IF. The data SRAM is
addressed in MEM, and its output is consumed in WB.

Expected CPI is about 1.1–1.3, depending on load-use frequency and taken-branch density.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | Core clock. |
| `rst` | in | 1 | Synchronous, active-high reset (R8). |
| **Instruction memory** | | | |
| `imem_en` | out | 1 | Read enable. When 0, the SRAM holds its previous output. |
| `imem_addr` | out | 32 | Byte address (`pc_next`); bits [1:0] are always 0. |
| `imem_rdata` | in | 32 | Instruction, 1 cycle after the address. |
| **Data memory** | | | |
| `dmem_en` | out | 1 | Access enable (load or store). |
| `dmem_we` | out | 1 | 1 = store. |
| `dmem_wstrb` | out | 4 | Byte write enables. |
| `dmem_addr` | out | 32 | Byte address (the SRAM uses `[31:2]`). |
| `dmem_wdata` | out | 32 | Store data, lane-replicated. |
| `dmem_rdata` | in | 32 | Load data, 1 cycle after the address (in WB). |
| **Retire trace (R10)** | | | |
| `trace_valid` | out | 1 | An instruction retired this cycle. |
| `trace_pc` | out | 32 | Its PC. |
| `trace_instr` | out | 32 | Its encoding. |
| `trace_rd_we` | out | 1 | It wrote a register (rd ≠ x0). |
| `trace_rd` | out | 5 | Destination register. |
| `trace_rd_wdata` | out | 32 | Value written. |
| `trace_mem_we` | out | 1 | It was a store. |
| `trace_mem_addr` | out | 32 | Store address. |
| `trace_mem_wdata` | out | 32 | Store data (lane-replicated) and |
| `trace_mem_wstrb` | out | 4 | strobes. |
| **Status** | | | |
| `halted` | out | 1 | Core stopped on an illegal instruction / ECALL / EBREAK (see §11). |
| `halt_pc` | out | 32 | PC of the instruction that caused the halt. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `RESET_PC` | 32'h0000_0000 | any, 4-byte aligned | Reset vector (R8). |
| `RF_RESET` | 0 | 0/1 | 1 = reset x1–x31 to 0 (eases lock-step with the ISS; costs reset fan-out). |
| `XLEN` | 32 | fixed | Data width (localparam). |

## 4. Block Diagram

```
        +------+   imem_addr=pc_next   +----------+
        | PC   |---------------------->| I-SRAM   |  (external)
        | mux  |<--redirect/target--+  +----+-----+
        +--+---+                    |       | imem_rdata
           | pc_f                   |       v
   IF  ----+------------------------|-------+---------------------------------------
           |  IF/ID: d_valid,d_pc,d_instr   |
   ID  +---v----------+   +--------+   +----+-----+    +------------+
       |  u_dec       |   | u_imm  |   | u_rf     |<---| WB write   |
       |  decoder     |   | immgen |   | 31x32    |    | + bypass   |
       +---+----------+   +---+----+   +----+-----+    +------------+
           | ctrl            | imm          | rs1/rs2 val
       +---v-----------------v--------------v-----+   +-------------+
       | u_haz: load-use detect -> stall_f/stall_d |   |             |
       +-------------------------------------------+   |             |
   ----------  ID/EX: e_* -------------------------------------------- |
   EX  +--------------+   +-------+   +------------+   +-----------+  |
       | u_fwd fwd    |-->| u_alu |   | u_bru      |-->| redirect, |--+
       | muxes A/B    |-->|       |   | cmp+target |   | flush     |
       +--------------+   +---+---+   +------------+   +-----------+
                              | ex_result, store fmt (u_stfmt)
   ----------  EX/MEM: m_* ---+---------------------------------------
   MEM            dmem_addr/wdata/wstrb/en/we --> D-SRAM (external)
   ----------  MEM/WB: w_* -------------------------------------------
   WB   dmem_rdata --> u_ldext (align/sign-extend) --> wb_data --> RF, fwd, trace
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_dec` | `rv_decode` | Opcode/funct decode into control bundle; illegal detection. |
| `u_imm` | `rv_immgen` | I/S/B/U/J immediate generation. |
| `u_rf` | `rv_regfile` | 31 × 32 flops (x0 hard-wired), 2 async read ports, 1 write port, WB→ID bypass. |
| `u_haz` | `rv_hazard` | Load-use stall detection. |
| `u_fwd` | `rv_forward` | EX operand forwarding muxes. |
| `u_alu` | `rv_alu` | ADD/SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND. |
| `u_bru` | `rv_branch` | Branch comparator, branch/JAL/JALR target, redirect generation. |
| `u_stfmt` | `rv_store_fmt` | Store data lane replication and strobes. |
| `u_ldext` | `rv_load_ext` | Load byte/half extraction and sign/zero extension. |

## 5. Datapath

### 5.1 Pipeline registers

| Register group | Fields (width) | Reset |
|----------------|----------------|-------|
| PC | `pc_f` (32) | `RESET_PC` |
| IF/ID | `d_valid` (1), `d_pc` (32), `d_instr` (32) | `d_valid = 0` |
| ID/EX | `e_valid`, `e_pc`, `e_instr`, `e_rs1_val` (32), `e_rs2_val` (32), `e_imm` (32), `e_rs1`, `e_rs2`, `e_rd` (5 each), control bundle `e_ctrl` (§5.3) | `e_valid = 0` |
| EX/MEM | `m_valid`, `m_pc`, `m_instr`, `m_result` (32: ALU result, address, or pc+4), `m_wdata` (32), `m_wstrb` (4), `m_rd` (5), `m_rd_we`, `m_is_load`, `m_is_store`, `m_ld_f3` (3) | `m_valid = 0` |
| MEM/WB | `w_valid`, `w_pc`, `w_instr`, `w_result` (32), `w_rd`, `w_rd_we`, `w_is_load`, `w_ld_f3`, `w_addr_lo` (2), `w_is_store`, `w_mem_addr`, `w_wdata`, `w_wstrb` | `w_valid = 0` |
| Halt | `halted_q` (1), `halt_pc_q` (32) | 0 |

Every side-effecting enable (RF write, `dmem_en`, redirect, trace) is ANDed with its stage's
`valid`. A bubble is `valid = 0`, so the other fields are don't-care and are not reset.

### 5.2 IF: next PC

```verilog
wire [31:0] pc_plus4 = pc_f + 32'd4;
assign pc_next  = rst        ? RESET_PC :
                  redirect   ? ex_target :
                  (stall_f | halted_q) ? pc_f : pc_plus4;
assign imem_addr = pc_next;
assign imem_en   = rst | redirect | ~(stall_f | halted_q);
// pc_f <= pc_next every cycle; imem_rdata in the next cycle corresponds to pc_f
```

When `imem_en = 0` (stall), the SRAM output holds, so the IF instruction stays aligned with
the held `pc_f`.

### 5.3 ID: decode and register read

Control bundle produced by `u_dec`:

| Field | Width | Meaning |
|-------|-------|---------|
| `alu_op` | 4 | ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND |
| `a_sel` | 2 | 0 = rs1, 1 = PC, 2 = zero |
| `b_sel` | 1 | 0 = rs2, 1 = imm |
| `rd_we` | 1 | Writes rd (forced 0 when rd = x0) |
| `is_load`, `is_store` | 1, 1 | Memory op |
| `is_branch`, `is_jal`, `is_jalr` | 1 each | Control transfer |
| `f3` | 3 | funct3 (branch cond / mem size) |
| `uses_rs1`, `uses_rs2` | 1, 1 | For hazard detection |
| `trap` | 1 | Illegal, ECALL or EBREAK |

Decode table:

| opcode | Instr | Imm | a_sel | b_sel | alu_op | rd_we | Other | uses rs1/rs2 |
|--------|-------|-----|-------|-------|--------|-------|-------|--------------|
| 0110111 | LUI | U | zero | imm | ADD | 1 | | 0/0 |
| 0010111 | AUIPC | U | PC | imm | ADD | 1 | | 0/0 |
| 1101111 | JAL | J | – | – | – | 1 | is_jal, result = pc+4 | 0/0 |
| 1100111 | JALR (f3=000) | I | rs1 | imm | ADD | 1 | is_jalr, result = pc+4 | 1/0 |
| 1100011 | Bxx (f3≠010,011) | B | – | – | – | 0 | is_branch | 1/1 |
| 0000011 | Lx (f3 ∈ 000,001,010,100,101) | I | rs1 | imm | ADD | 1 | is_load | 1/0 |
| 0100011 | Sx (f3 ∈ 000,001,010) | S | rs1 | imm | ADD | 0 | is_store | 1/1 |
| 0010011 | OP-IMM | I | rs1 | imm | by f3 (+f7[5] for SRAI) | 1 | shifts: f7 must be 0000000/0100000 | 1/0 |
| 0110011 | OP | – | rs1 | rs2 | by f3 + f7[5] | 1 | f7 ∈ {0000000, 0100000 for ADD/SUB, SRL/SRA} | 1/1 |
| 0001111 | FENCE | – | – | – | – | 0 | NOP | 0/0 |
| 1110011 | ECALL/EBREAK | – | – | – | – | 0 | trap | 0/0 |
| other | – | – | – | – | – | 0 | trap (illegal) | 0/0 |

Immediates (`u_imm`), all sign-extended from bit 31:
I = `instr[31:20]`; S = `{instr[31:25], instr[11:7]}`;
B = `{instr[31], instr[7], instr[30:25], instr[11:8], 1'b0}`;
U = `{instr[31:12], 12'b0}`; J = `{instr[31], instr[19:12], instr[20], instr[30:21], 1'b0}`.

Register file with write-through bypass (WB writes at the clock edge; ID reads in the same
cycle):

```verilog
rs1_val = (d_rs1 == 0) ? 0 :
          (wb_we && wb_rd == d_rs1) ? wb_data : rf[d_rs1];
// same for rs2
```

### 5.4 EX: forwarding, ALU, branch

```verilog
// forwarding priority: youngest producer first (EX/MEM), then MEM/WB, then ID/EX value
fwd_a = (m_valid & m_rd_we & ~m_is_load & (m_rd == e_rs1) & (e_rs1 != 0)) ? m_result :
        (wb_we                          & (w_rd == e_rs1) & (e_rs1 != 0)) ? wb_data  :
        e_rs1_val;
fwd_b = /* same with e_rs2 */;

op_a = (a_sel == PC) ? e_pc : (a_sel == ZERO) ? 32'd0 : fwd_a;
op_b = b_sel ? e_imm : fwd_b;
alu_out   = ALU(alu_op, op_a, op_b);
ex_result = (is_jal | is_jalr) ? e_pc + 4 : alu_out;

// branch unit
eq  = (fwd_a == fwd_b);
lt  = ($signed(fwd_a) < $signed(fwd_b));
ltu = (fwd_a < fwd_b);
taken = is_branch & (f3==BEQ ? eq : f3==BNE ? ~eq : f3==BLT ? lt :
                     f3==BGE ? ~lt : f3==BLTU ? ltu : ~ltu);
ex_target = is_jalr ? ((fwd_a + e_imm) & ~32'd1) : (e_pc + e_imm);
redirect  = e_valid & ~halted_q & (is_jal | is_jalr | taken);
```

`wb_we = w_valid & w_rd_we` and `wb_data` come from §5.6. A load in MEM never needs to be
forwarded: the load-use stall guarantees it (asserted in §10).

Store formatting (`u_stfmt`, using `alu_out[1:0]` as the byte offset):

| f3 | `m_wdata` | `m_wstrb` |
|----|-----------|-----------|
| SB (000) | `{4{fwd_b[7:0]}}` | `4'b0001 << off` |
| SH (001) | `{2{fwd_b[15:0]}}` | `off[1] ? 4'b1100 : 4'b0011` |
| SW (010) | `fwd_b` | `4'b1111` |

### 5.5 MEM

```verilog
assign dmem_en    = m_valid & (m_is_load | m_is_store);
assign dmem_we    = m_valid & m_is_store;
assign dmem_addr  = m_result;
assign dmem_wdata = m_wdata;
assign dmem_wstrb = m_is_store ? m_wstrb : 4'b0;
```

The MEM stage has no other logic; its datapath is just registers to the SRAM pins, so there
is lots of setup margin. `w_addr_lo <= m_result[1:0]`.

### 5.6 WB

```verilog
// u_ldext
sh   = dmem_rdata >> {w_addr_lo, 3'b000};
ld   = (w_ld_f3 == LB)  ? {{24{sh[7]}},  sh[7:0]}  :
       (w_ld_f3 == LH)  ? {{16{sh[15]}}, sh[15:0]} :
       (w_ld_f3 == LBU) ? {24'b0, sh[7:0]} :
       (w_ld_f3 == LHU) ? {16'b0, sh[15:0]} : dmem_rdata;
wb_data = w_is_load ? ld : w_result;
wb_rd   = w_rd;   wb_we = w_valid & w_rd_we;      // rd_we already 0 for x0
```

The trace port is driven directly from MEM/WB and `wb_data`.

## 6. Control Logic

### 6.1 Hazard detection (ID)

```verilog
load_use = e_valid & e_is_load & (e_rd != 0) &
           ((d_uses_rs1 & (e_rd == d_rs1)) | (d_uses_rs2 & (e_rd == d_rs2)));
stall_f  = d_valid & load_use;     // hold PC and IF/ID
stall_d  = d_valid & load_use;     // inject bubble into ID/EX
```

`load_use` is conservative for stores whose rs2 depends on the load (they could forward
WB→MEM), but it is simple; see §11.

### 6.2 Pipeline register control

| Condition | PC / IF | IF/ID | ID/EX | EX/MEM | MEM/WB |
|-----------|---------|-------|-------|--------|--------|
| Normal | advance | ← IF | ← ID | ← EX | ← MEM |
| `load_use` | hold (`imem_en=0`) | hold | **bubble** | ← EX | ← MEM |
| `redirect` | ← `ex_target` | **bubble** | **bubble** | ← EX | ← MEM |
| `trap` in EX (`e_valid & e_trap`) | hold, set `halted_q` | bubble | bubble | **bubble** (trap does not retire) | ← MEM |
| `halted_q` | hold (`imem_en=0`) | bubble | bubble | bubble | ← MEM |

Priority: `rst` > trap > redirect > load_use. `redirect` and `load_use` cannot occur in the
same cycle: `redirect` requires ID/EX to hold a branch/jump, while `load_use` requires it to
hold a load. Trap and redirect are likewise exclusive (a trap instruction is not a
branch). The priority order exists only for robustness.

An instruction in EX is always on the correct path: any older control transfer resolved
in EX one cycle earlier and would already have flushed it. This is why redirects and traps
are taken in EX without further qualification.

### 6.3 Halt behaviour (trap)

There is no FSM beyond `halted_q`:

| State | Condition | Behaviour | Exit |
|-------|-----------|-----------|------|
| RUN | `halted_q = 0` | normal | trap in EX → HALT (`halt_pc_q ← e_pc`) |
| HALT | `halted_q = 1` | fetch stopped; older instructions in MEM/WB drain and retire | `rst` only |

`halted = halted_q`, which is registered.

## 7. Timing & Pipeline

**Latency/penalty table**

| Event | Penalty (cycles) | Mechanism |
|-------|------------------|-----------|
| ALU → dependent ALU (back-to-back) | 0 | EX/MEM → EX forward |
| ALU → dependent, 2 apart | 0 | MEM/WB → EX forward |
| Any → dependent, 3 apart | 0 | RF write-through bypass |
| Load → dependent (next instr) | 1 | stall, then MEM/WB → EX forward |
| Load → dependent, 2 apart | 0 | MEM/WB → EX forward |
| Taken branch / JAL / JALR | 2 | flush IF/ID + ID/EX |
| Not-taken branch | 0 | predict not-taken |

**Hazard example**

```
I1: lw   x1, 0(x2)
I2: add  x3, x1, x4      # load-use on x1
I3: beq  x3, x0, L       # x3 from I2 (EX/MEM forward), taken
I4: addi x5, x5, 1       # wrong path
I5: addi x6, x6, 1       # wrong path
L:  I6: sub x7, x7, x8
```

| Cycle | IF | ID | EX | MEM | WB | Event |
|-------|----|----|----|-----|----|-------|
| 1 | I1 | | | | | |
| 2 | I2 | I1 | | | | |
| 3 | I3 | I2 | I1 | | | load_use (I1 rd = I2 rs1) → stall |
| 4 | I3 | I2 | bubble | I1 | | dmem read x1 |
| 5 | I4 | I3 | I2 | bubble | I1 | I2.rs1 forwarded from WB (`wb_data` = load) |
| 6 | I5 | I4 | I3 | I2 | bubble | I3.rs1 = x3 from EX/MEM; taken → redirect to L |
| 7 | I6 | bubble | bubble | I3 | I2 | I4, I5 flushed |
| 8 | I7 | I6 | bubble | bubble | I3 | |
| 9 | … | … | I6 | bubble | bubble | |

6 instructions issued, 2 wrong-path, 1 stall bubble; I1–I3 retire at 5, 7, 8.

**Critical paths (in expected order)**
1. `dmem_rdata` → load-extend → `wb_data` → EX forward mux → 32-bit comparator → `redirect` → `pc_next` mux → `imem_addr` (SRAM setup). This is the classic EX-resolve path. If needed, branch compare can be moved to a registered "branch in MEM" scheme (3-cycle penalty) or WB forwarding of loads can be registered.
2. EX forward mux → 32-bit adder (`fwd_a + e_imm` for JALR) → `pc_next` → `imem_addr`.
3. ID: `imem_rdata` (IF/ID) → decoder → hazard compare → `imem_en` / IF/ID hold enable.

## 8. Clocking & Reset

- **Single clock** `clk`; both SRAMs are on the same clock. No CDC.
- **Reset:** `rst`, synchronous, active high (R8). During reset, `pc_next = RESET_PC` with
  `imem_en = 1`, so the instruction at `RESET_PC` is already on `imem_rdata` in the first
  cycle after reset, with `pc_f = RESET_PC`. All stage `valid` bits and `halted_q` clear.
  Datapath fields in the pipeline registers are not reset.
- **Register file:** not reset by default (`RF_RESET = 0`). The ISA does not define reset
  values, and x0 is hard-wired. For lock-step simulation with an ISS, set `RF_RESET = 1` or
  initialize the ISS registers to match.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| Write to x0 | `rd_we` forced to 0 in decode; also never forwarded (`rs != 0` term). |
| Producer and consumer both x0 | No forward; reads 0. |
| Two producers in flight for the same rd | EX/MEM is checked before MEM/WB, so the youngest value wins. |
| Load followed by a store using the loaded value as data (rs2) | Stalls 1 cycle (conservative), then forwards from WB. |
| Load followed by a store using the loaded value as address (rs1) | Stalls 1 cycle (true load-use). |
| JALR with rd == rs1 | Target uses the forwarded old rs1 in EX; rd is written later in WB. Correct by construction. |
| Branch whose operand comes from a load 2 instructions earlier | WB forward, no stall. |
| Branch target not 4-byte aligned (target[1] = 1) | RV32I without C would raise instruction-address-misaligned. Here: not handled; an assertion flags it in simulation (§11). |
| Misaligned load/store (e.g. LW at addr[1:0]≠0) | Software guarantees none (R6). Hardware performs the access with the offset bits ignored for LW, and SH at offset 3 behaves as SH at offset 2; an assertion flags it. |
| FENCE / FENCE.I | Executes as a NOP (single in-order core, no caches). |
| ECALL, EBREAK, illegal encoding | Trap: the core halts (§6.3, §11). |
| Stall and flush in the same cycle | Impossible by construction (§6.2); asserted. |

## 10. Verification Plan

**Reference:** lock-step comparison against an ISS (Spike or Sail) using the retire-trace
port. Every retired instruction's PC, instruction, rd/value and store address/data/strobe
must match the ISS commit log.

**Test sources**
1. `riscv-tests` rv32ui-p-* (all RV32I instruction tests), with ECALL used as end-of-test (it halts the core).
2. `riscv-dv` random instruction streams (RV32I only), 1000 seeds, with high branch density and dependency-chain options.
3. Directed hazard tests:
   - ALU→ALU dependency at distance 1, 2, 3 for rs1 and rs2.
   - Load-use at distance 1 (stall) and 2 (no stall), for rs1, rs2 and the store-data case.
   - Back-to-back taken branches, branch to branch target, JAL followed by JALR.
   - JALR with rd == rs1; jumps whose link register is consumed immediately.
   - Writes to x0 followed by reads of x0.
   - All load/store sizes at all byte offsets (aligned ones), sign extension.
4. Illegal-instruction sweep: every reserved opcode and invalid funct3/funct7 → halt with the correct `halt_pc`, and no state changes after the trap.

**Assertions (SVA)**

```systemverilog
a_no_mem_load_fwd: assert property (@(posedge clk) disable iff(rst)
    (e_valid && m_valid && m_is_load && m_rd_we && m_rd != 0 &&
     ((e_uses_rs1 && m_rd == e_rs1) || (e_uses_rs2 && m_rd == e_rs2))) |-> 0);
a_excl:    assert property (@(posedge clk) disable iff(rst) !(redirect && load_use));
a_x0:      assert property (@(posedge clk) disable iff(rst) wb_we |-> wb_rd != 0);
a_tgt_aln: assert property (@(posedge clk) disable iff(rst) redirect |-> ex_target[1:0] == 0);
a_dmem_aln:assert property (@(posedge clk) disable iff(rst)
    dmem_en && m_ld_f3[1:0]==2'b10 |-> dmem_addr[1:0] == 0);
a_flush:   assert property (@(posedge clk) disable iff(rst) redirect |=> !d_valid && !e_valid);
a_halt_quiet: assert property (@(posedge clk) disable iff(rst)
    halted_q |-> !e_valid && !d_valid && !redirect);
```

**Coverage:** every opcode/funct3/funct7 combination; each forwarding source (EX/MEM,
MEM/WB, RF bypass) × operand (A, B, store data, branch compare, JALR base); load-use stall
for each load type; redirect by each control-transfer type; stall followed immediately by a
redirect; consecutive redirects; halt with 0, 1 and 2 older instructions draining.

## 11. Assumptions & Open Questions

1. **Illegal-instruction handling (R11 is TBD).** Chosen: illegal encodings, ECALL and EBREAK trap in EX and **halt** the core (`halted`, `halt_pc`). Older instructions retire; the trapping one does not. This is safe and testbench-friendly (riscv-tests end on ECALL). When privileged support is added, this becomes a real trap: redirect to `mtvec`, writing `mepc`/`mcause`. The EX-stage trap point already has the precise-exception property the trap needs (all older instructions complete, all younger ones are flushed).
2. **Misaligned accesses and jump targets are not detected** in hardware (R6 says software never produces them). Simulation assertions catch them. Precise misaligned exceptions need the trap mechanism from item 1.
3. **Branch resolution in EX** gives a 2-cycle taken penalty. A future improvement is a small BTB/BHT in IF, or moving JAL resolution to ID (1-cycle penalty) with an adder on the ID PC.
4. **Store-data load-use stall is conservative.** A WB→MEM store-data forward would remove 1 cycle for `lw x1; sw x1` sequences (memcpy loops), at the cost of a mux on `dmem_wdata`.
5. **Memories are always ready** (no wait states, R5). Supporting waiting memories (e.g. caches) would need global `stall` inputs from `imem_ready`/`dmem_ready` that freeze all pipeline registers.
6. **FENCE.I is a NOP.** Self-modifying code needs software to guarantee that the I-SRAM write completes before the fetch. With the Harvard ports this needs a system-level path to write the I-SRAM.
7. **Register file in flops** (31 × 32), with 2 async read ports. FPGA targets can use LUT-RAM (duplicated per read port).
8. **The trace port reports retirement in WB.** Stores are reported at WB too (their memory write happened in MEM one cycle earlier), which is adequate for ISS lock-step.
