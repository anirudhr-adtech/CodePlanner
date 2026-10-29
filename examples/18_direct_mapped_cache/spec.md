From: CPU architecture team
To: RTL
Subject: L1 D-cache for the "Kestrel" microcontroller core — design brief

Hi all,

We need a first-cut L1 data cache for Kestrel. Keep it simple: direct-mapped, 4 KiB, 32-byte
lines. The core is a 32-bit in-order pipeline with byte-addressed, 32-bit-wide loads and
stores, and it uses byte strobes for sub-word stores. Policy is write-back with
write-allocate. We looked at write-through, but the bus is shared with the DMA and the
write traffic would kill us.

On the CPU side, the core issues one request at a time using a valid/ready handshake
(address, read/write, write data, byte strobes). We'd like hits to return data the cycle
after the request is accepted, with a new request accepted every cycle for back-to-back
read hits. Stores can be slower if it helps, but please don't make them more than 2 cycles
per hit. Responses come back in order on a single response-valid strobe. The core always
waits for each response, so you don't need an ID.

Behind the cache sits our system interconnect. It has a simple burst protocol: a request
channel (line-aligned address, read/write) with valid/ready, a write-data channel with
valid/ready/last, a read-data channel with valid/last (the cache must always accept read
data, so there's no ready), and a write-done pulse when a write burst is committed. Bursts
are always one full line, 8 beats of 32 bits, in incrementing order starting at word 0.
Read latency on the interconnect is variable, typically 10–20 cycles.

The physical design team says we get single-port synchronous SRAMs with 1-cycle read
latency and byte-write enables. They would rather keep valid/dirty out of SRAM so a reset
doesn't take 128 cycles.

Things we haven't decided yet: cache maintenance ops (flush/invalidate), uncached regions
for MMIO, and whether to do critical-word-first. Make a call and tell us what you assumed.

Thanks,
— Arch
