Hi team,

For the new 10G MAC we need a CRC block that can sit on the receive and transmit data paths and
compute the Ethernet FCS on the fly. Some background and what we need:

The data path inside the MAC is 32 bits wide, using an AXI-Stream-like valid/ready handshake.
Byte 0 of a frame is in bits [7:0] of the first word, byte 1 in [15:8], and so on. Frames are
any length from 1 byte upward. On the last word of a frame we get a 4-bit byte-enable telling
us how many of the bytes are real; the valid bytes are always packed at the bottom, so you'll
only see 0001, 0011, 0111 or 1111 there. Every other word is always fully populated.

The CRC is the standard Ethernet one: polynomial 0x04C11DB7, register preset to all ones,
reflected in and out like the 802.3 spec, and the result inverted at the end. A good sanity
check is that the ASCII string "123456789" should produce 0xCBF43926.

We need to process a full word every clock with no bubbles between frames, because the MAC
streams back-to-back frames. When a frame ends, please give us the final 32-bit CRC with its
own valid/ready so the TX side can append it and the RX side can compare it. The block
shouldn't modify the data stream; it just watches it, so it can be used as a "tap".

Target clock is 312.5 MHz on an UltraScale+ part. We'd like to reuse the block on ASIC later.
Reset is synchronous active-low like the rest of the MAC.

If something is malformed (for example a weird byte-enable), flag it somehow, but don't hang.

Thanks!
