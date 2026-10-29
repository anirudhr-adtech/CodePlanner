# Micro-architecture: `crc32_stream`

## 1. Overview

`crc32_stream` computes the IEEE 802.3 (Ethernet FCS) CRC-32 over a stream of 32-bit words,
4 bytes per clock, with no bubbles between back-to-back frames. It watches a valid/ready
stream without modifying it and, at the end of each frame, emits the final CRC on its own
valid/ready result channel.

Key features:
- CRC-32/ISO-HDLC parameters: polynomial 0x04C11DB7 (reflected form 0xEDB88320), init 0xFFFFFFFF, reflected input and output, final XOR 0xFFFFFFFF.
- Reflected (LSB-first) shift-register formulation, so no explicit bit reversal of data or result is needed.
- Four parallel next-state networks (8/16/24/32 data bits) for the partial last word, selected by the byte-enable.
- Frame-to-frame CRC register reload in the same cycle as the last beat, giving 100% throughput.
- One registered result slot; sticky error flag for illegal byte-enable patterns.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **Clock / reset** | | | |
| `clk` | in | 1 | 312.5 MHz data-path clock. |
| `rst_n` | in | 1 | Synchronous active-low reset. |
| **Input stream (tap)** | | | |
| `s_valid` | in | 1 | Beat valid. |
| `s_ready` | out | 1 | Beat accepted when `s_valid && s_ready`. |
| `s_data` | in | 32 | Data; byte *i* of the beat is `s_data[8i+7:8i]`, byte 0 first on the wire. |
| `s_keep` | in | 4 | Byte enables; must be `4'b1111` except on the last beat. |
| `s_last` | in | 1 | Last beat of the frame. |
| **Result channel** | | | |
| `m_crc_valid` | out | 1 | Final CRC available. |
| `m_crc_ready` | in | 1 | Consumer accepts result. |
| `m_crc` | out | 32 | Final CRC (already reflected and inverted). FCS byte order on the wire is `m_crc[7:0]` first. |
| **Status** | | | |
| `keep_err` | out | 1 | Sticky: an illegal `s_keep` pattern was seen. |
| `err_clr` | in | 1 | Pulse; clears `keep_err`. |

When used as a pure tap, `s_ready` is ANDed into the parent stream's ready by the
integrator. It only deasserts in the rare case described in §6.

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `POLY_REFL` | `32'hEDB88320` | any 32-bit | Reflected polynomial (bit-reversed 0x04C11DB7). |
| `INIT` | `32'hFFFFFFFF` | any 32-bit | CRC register preset at frame start. |
| `XOROUT` | `32'hFFFFFFFF` | any 32-bit | Final XOR. |
| `DATA_W` | 32 | fixed 32 | Data width (fixed in this version; see §11). |
| `KEEP_W` | `DATA_W/8` = 4 | derived | Byte-enable width. |

Changing `POLY_REFL`/`INIT`/`XOROUT` gives any reflected CRC-32 variant. Non-reflected
variants are out of scope (§11).

## 4. Block Diagram

```
 s_data[31:0] ------------------+----------------+----------------+----------------+
                                |                |                |                |
 crc_q[31:0] --+--------------->|                |                |                |
               |          +-----v-----+    +-----v-----+    +-----v-----+    +-----v-----+
               |          | crc_nxt8  |    | crc_nxt16 |    | crc_nxt24 |    | crc_nxt32 |
               |          | (d[7:0])  |    | (d[15:0]) |    | (d[23:0]) |    | (d[31:0]) |
               |          +-----+-----+    +-----+-----+    +-----+-----+    +-----+-----+
               |                |c8              |c16             |c24             |c32
               |                +-------+--------+-------+--------+-------+--------+
               |                        |   4:1 mux, sel = nbytes (from s_keep, s_last)
               |                        v
               |                   crc_upd[31:0] ----------------+
               |                        |                        | ^ XOROUT
               |        INIT --->|\     |                        v
               |                 | |<---+               +--------------+
               +-----------------| |  sel = s_last      |   res_q      |---> m_crc
                     crc_q <-----|/                     | res_valid_q  |---> m_crc_valid
                                                        +--------------+
 s_keep,s_last ---> keep decode ---> nbytes, keep_bad ---> keep_err_q (sticky)
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_nxt8/16/24/32` | `crc32_nxt #(.NBITS(8/16/24/32))` | Purely combinational XOR networks computing the CRC after N data bits. |
| — (inline) | keep decode | Maps `s_keep`/`s_last` to `nbytes` and `keep_bad`. |
| — (inline) | result slot | `res_q`, `res_valid_q`, output handshake. |

## 5. Datapath

**Registers**

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `crc_q` | 32 | `INIT` | Running CRC of the current frame (reflected, not inverted). |
| `res_q` | 32 | 0 | Final CRC of the last completed frame. |
| `res_valid_q` | 1 | 0 | `res_q` holds an unconsumed result. |
| `keep_err_q` | 1 | 0 | Sticky illegal-keep flag. |

**Next-state networks.** Each `crc32_nxt` instance is the unrolled reflected LFSR. It is
written as a constant-bound loop that synthesis flattens into an XOR network (no registers):

```verilog
function automatic [31:0] crc_nxt(input [31:0] c, input [31:0] d, input integer nbits);
  integer i;
  begin
    crc_nxt = c;
    for (i = 0; i < nbits; i = i + 1)
      crc_nxt = (crc_nxt >> 1) ^ (((crc_nxt[0] ^ d[i]) ? POLY_REFL : 32'h0));
  end
endfunction
```

Data bit `d[0]` (the LSB of byte 0) is processed first, matching Ethernet's LSB-first bit
order. That is why the reflected form needs no bit reversal. For 32 data bits, each output
bit is the XOR of at most about 30 inputs (bits of `crc_q` and `s_data`). That maps to 2–3
LUT6 levels, comfortably within the 3.2 ns budget.

**Byte-count decode**

| `s_last` | `s_keep` | `nbytes` | `keep_bad` |
|----------|----------|----------|------------|
| 0 | `1111` | 4 | 0 |
| 0 | other | 4 | 1 |
| 1 | `0001` | 1 | 0 |
| 1 | `0011` | 2 | 0 |
| 1 | `0111` | 3 | 0 |
| 1 | `1111` | 4 | 0 |
| 1 | other non-zero | highest set bit index + 1 | 1 |
| 1 | `0000` | 0 (CRC unchanged) | 1 |

```verilog
crc_upd = (nbytes == 1) ? c8 : (nbytes == 2) ? c16 : (nbytes == 3) ? c24 :
          (nbytes == 4) ? c32 : crc_q;
```

**Register updates (when `s_fire = s_valid && s_ready`)**

```verilog
crc_q       <= s_last ? INIT : crc_upd;
if (s_last) begin
  res_q       <= crc_upd ^ XOROUT;
end
res_valid_q <= (s_fire && s_last) ? 1'b1 : (m_crc_ready ? 1'b0 : res_valid_q);
keep_err_q  <= err_clr ? 1'b0 : (keep_err_q | (s_fire && keep_bad));
```

## 6. Control Logic

There is no explicit FSM. Frame state is implicit: `crc_q == INIT` marks the start of a
frame, and `s_last` closes it. The only control is the result-slot handshake.

| Implied state | Condition | Behaviour |
|---------------|-----------|-----------|
| IN_FRAME | always | Every accepted beat updates `crc_q`; a last beat reloads `INIT`. |
| RESULT_EMPTY | `res_valid_q == 0` | Last beat may complete; `s_ready = 1`. |
| RESULT_PENDING | `res_valid_q == 1` | `m_crc_valid = 1`; a new last beat can only be accepted if `m_crc_ready` frees the slot in the same cycle. |

```verilog
assign s_ready     = !res_valid_q || m_crc_ready;
assign m_crc_valid = res_valid_q;
assign m_crc       = res_q;
```

`s_ready` is combinational from `m_crc_ready`. The consumer (MAC TX/RX control) reads the
result in the cycle it appears, so in normal operation `s_ready` stays at 1 and the data
path never stalls. If the result consumer must be fully decoupled, a register slice can be
put on the result channel (§11).

## 7. Timing & Pipeline

- **Latency:** the final CRC is valid one cycle after the last beat is accepted.
- **Throughput:** 32 bits per clock (10 Gb/s at 312.5 MHz), with back-to-back frames and no idle cycles, because `crc_q` reloads `INIT` in the same edge that captures the result.
- **Critical path:** `crc_q`/`s_data` → `crc_nxt32` XOR tree → 4:1 mux → `crc_q` D-input (about 4 LUT levels). `s_keep` decode runs in parallel with the XOR trees.

Cycle-by-cycle: frame A = "123456789" (9 bytes), immediately followed by frame B.
`m_crc_ready = 1` throughout.

| Cycle | s_valid | s_data | s_keep | s_last | crc_q (during) | res_valid | m_crc | Note |
|-------|---------|--------|--------|--------|----------------|-----------|-------|------|
| 0 | 1 | `34333231` | `1111` | 0 | `FFFFFFFF` | 0 | – | "1234" |
| 1 | 1 | `38373635` | `1111` | 0 | `641C1F5C` | 0 | – | "5678" |
| 2 | 1 | `xxxxxx39` | `0001` | 1 | `651F2550` | 0 | – | "9"; crc_upd = `340BC6D9` |
| 3 | 1 | B0 | `1111` | 0 | `FFFFFFFF` | 1 | `CBF43926` | frame B starts, A's result out |
| 4 | 1 | B1 | `1111` | 0 | f(B0) | 0 | – | |

## 8. Clocking & Reset

- Single clock domain `clk`; no CDC.
- `rst_n` is synchronous active-low. Reset loads `crc_q = INIT` and clears `res_valid_q` and `keep_err_q`. `res_q` is reset to 0 for clean waveforms; this costs 32 flops with reset, which is negligible.
- The block has no requirement on what happens to a frame interrupted by reset. Upstream must restart frames after reset.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| 1-byte frame | Single beat with `s_last=1`, `s_keep=0001`: `crc_q` goes `INIT → INIT`, result = `crc_nxt8(INIT, d) ^ XOROUT`. |
| Back-to-back last beats (1-beat frames every cycle) | Supported at full rate as long as `m_crc_ready=1`; each result occupies the slot for one cycle. |
| Result not consumed, new last beat arrives | `s_ready=0`; the beat waits. Non-last beats also stall, because `s_ready` does not look at `s_last` (keeps the logic simple; §11). |
| Illegal keep on non-last beat | Treated as 4 bytes, `keep_err` set. |
| Non-contiguous keep on last beat (e.g. `0101`) | Byte count = highest set bit + 1 (here 3), `keep_err` set. |
| `s_keep = 0000` with `s_last` | Frame closes with CRC unchanged by this beat, `keep_err` set. |
| `s_valid` low mid-frame | `crc_q` holds; gaps are allowed anywhere. |
| `err_clr` and new error in the same cycle | `err_clr` wins (clear has priority). |

## 10. Verification Plan

**Reference model:** a bytewise reflected CRC-32 (equal to Python `zlib.crc32` / C `crc32()`),
fed from the same byte stream as the DUT.

**Directed tests**
1. "123456789" as 3 beats (keep `1111`,`1111`,`0001`) → `0xCBF43926`, with the intermediate `crc_q` values listed in §7.
2. Every last-beat keep (`0001`,`0011`,`0111`,`1111`) for frame lengths 1–12.
3. Minimum-size (64-byte) and jumbo (9000-byte) Ethernet frames, plus real captured frames with known FCS.
4. Residue check: running the CRC over a frame *plus* its appended FCS must give a constant register value for every frame. The value is computed by the reference model and compared, not hard-coded.
5. Back-to-back 1-beat frames for 100 cycles with `m_crc_ready=1` → one result per cycle.
6. Result back-pressure: hold `m_crc_ready=0` and check that `s_ready` falls only while a result is pending.
7. Illegal keep patterns → `keep_err` sticky and cleared by `err_clr`.

**Constrained-random:** random frame lengths 1–2000 bytes, random `s_valid` gaps, random
`m_crc_ready` (90% high), 1M beats; scoreboard compares every result.

**Assertions (SVA)**

```systemverilog
a_res_stable: assert property (@(posedge clk) disable iff(!rst_n)
                m_crc_valid && !m_crc_ready |=> m_crc_valid && $stable(m_crc));
a_init_after_last: assert property (@(posedge clk) disable iff(!rst_n)
                s_valid && s_ready && s_last |=> crc_q == INIT);
a_ready_hi: assert property (@(posedge clk) disable iff(!rst_n) !m_crc_valid |-> s_ready);
a_keep_full: assert property (@(posedge clk) disable iff(!rst_n)
                s_valid && !s_last |-> s_keep == 4'hF);   // warning-level, environment check
```

**Coverage:** each `nbytes` value on the last beat; 1-beat frames; gap mid-frame; result
back-pressure; `keep_err` set and clear; back-to-back frames with no idle cycle.

**Equivalence:** formally check the unrolled `crc32_nxt` instances against 8/16/24/32
iterations of the serial LFSR (SymbiYosys or a commercial LEC).

## 11. Assumptions & Open Questions

1. **Reflected implementation only.** The spec asks for 802.3, which is reflected in and out. Supporting `REFIN=0` variants would need bit reversal per byte and is left out.
2. **`DATA_W` fixed at 32.** A 64-bit variant (for a future 25G path) needs 8 networks; the function above generalizes, but the keep decode and timing would need review.
3. **`s_ready` does not look at `s_last`.** Stalling only last beats would need `s_ready` to depend combinationally on `s_last`. Because the consumer always reads the result immediately, the simpler rule is used.
4. **Error reporting** is a sticky flag only; the frame's CRC is still produced so downstream can drop it. Confirm whether an in-band error bit on the result channel is wanted.
5. **Result ordering on the wire.** `m_crc[7:0]` is the first FCS byte transmitted. The TX inserter must not byte-swap.
6. **Synchronous reset** chosen to match the MAC. On ASIC, the result and CRC registers may drop reset if area matters.
