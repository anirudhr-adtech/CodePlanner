# RV32I core "Fivestage" — requirements

| ID | Requirement |
|----|-------------|
| R1 | Implement the RISC-V RV32I base integer ISA (unprivileged spec v2.1): LUI, AUIPC, JAL, JALR, BEQ/BNE/BLT/BGE/BLTU/BGEU, LB/LH/LW/LBU/LHU, SB/SH/SW, ADDI/SLTI/SLTIU/XORI/ORI/ANDI/SLLI/SRLI/SRAI, ADD/SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND. FENCE may be a no-op. |
| R2 | Classic 5-stage in-order pipeline: IF, ID, EX, MEM, WB. |
| R3 | Target CPI close to 1. Resolve data hazards with forwarding wherever possible; stall only for load-use. |
| R4 | Branches and jumps are resolved in EX. Static predict-not-taken. Flush wrong-path instructions on a redirect. |
| R5 | Harvard memory: separate instruction and data ports. Both are synchronous memories with a fixed 1-cycle read latency and no wait states (tightly coupled SRAM). |
| R6 | The data port supports byte, halfword and word access with byte write strobes. Misaligned accesses are not expected from the software. |
| R7 | No CSRs, interrupts or privilege modes in this version. |
| R8 | Reset vector is configurable at build time. Single clock, synchronous active-high reset. |
| R9 | x0 is hard-wired to zero. |
| R10 | Provide a retire-trace port (PC, instruction, rd, write data, valid) for lock-step comparison with a reference ISS. |
| R11 | Illegal instruction handling: TBD. |
