MAC unit for the beamformer – requirements

- signed fixed point, two operands a, b; defaults Q1.15 x Q1.15
- widths must be parameters (a, b, accumulator, output)
- y = sum(a*b), running; output each cycle a valid product is accumulated
- clear input: starts a new accumulation with the current product (no dead cycle)
- output Q1.15, round to nearest, saturate (no wrap!) + flag when saturated
- accumulator needs guard bits, at least 256 full-scale products without overflow
- sticky flag if the accumulator itself overflows anyway
- pipeline ~3 stages: input regs / multiply / accumulate. Must map onto one DSP48E2
- valid in, valid out, no back-pressure needed (stream is continuous or gapped by valid)
- pass a `last` sideband through with the same latency
- 400 MHz target, UltraScale+
- sync active-high reset
