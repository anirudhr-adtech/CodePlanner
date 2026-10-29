# FIR-01: Channel filter for the DDC – architecture requirements

**Context.** After the digital down-converter's decimator, each channel needs a linear-phase
low-pass FIR. The filter runs at the decimated sample rate, which is the fabric clock rate
(one new sample every clock, 491.52 MHz on a Zynq UltraScale+ RFSoC). There are 32 channels,
so DSP slice count matters more than latency.

**Requirements**

- R1. Linear-phase FIR with a configurable number of taps N (16 for the first product; up to 64 later). The impulse response is always symmetric, h[k] = h[N-1-k]. Both even and odd N must be supported.
- R2. Input: 16-bit signed samples, Q1.15. Output: 16-bit signed, Q1.15.
- R3. Coefficients: 18-bit signed, Q1.17. They must be loadable at run time from the control processor (via a simple write port; the AXI-Lite wrapper exists already). Changing the filter must not create a glitch: no output sample may be computed from a mix of old and new coefficients.
- R4. Throughput: one input and one output sample per clock, sustained.
- R5. Exploit symmetry to halve the multiplier count. The design should map onto DSP48E2 slices using dedicated cascade routing where possible.
- R6. Provide a bit-growth analysis and justify the internal widths. Outputs must saturate, not wrap. Rounding to nearest.
- R7. Latency is not critical (< 100 ns is fine) but must be constant and documented.
- R8. The upstream decimator provides a valid signal. In this product it is always high once running, but the filter must behave sensibly if it drops.

**Decision required.** The team has argued about using the transposed form or a systolic
form. Please make the call in the micro-architecture and document why.
