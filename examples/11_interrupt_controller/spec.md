# Interrupt controller for the RV32 microcontroller

The core has a single external interrupt input. We need a controller that merges 32 peripheral
interrupt lines into it.

**Sources.** 32 inputs, `src[31:0]`. Some peripherals (timers, GPIO) produce single-cycle
pulses; others (UART, SPI) hold a level until serviced. Each source must be configurable as
edge-triggered (rising edge) or level-triggered (active high). Some of the GPIO interrupts
come from pins, so they are not synchronous to our clock.

**Priorities.** Each source has a priority from 0 to 7, where 0 means "never interrupt" and 7 is
the most urgent. A global threshold lets software ignore everything at or below a given
level. If two sources have the same priority, the lower-numbered source wins.

**Servicing.** Software reads a CLAIM register to get the ID of the highest-priority pending
source. That also marks the interrupt as in service. When the ISR is finished, software writes
the ID to a COMPLETE register. Edge interrupts should be cleared by the claim; level interrupts
stay pending as long as the line is high.

**Nesting.** While an ISR runs, only strictly higher-priority interrupts may preempt it. Up to
7 levels of nesting (one per priority level) must work, with each COMPLETE returning to the
previous level.

**Registers** (32-bit simple bus, word-aligned, 1-cycle registered read):
- Priority of each source (3 bits per source; pack them as you see fit)
- Enable mask (1 bit per source)
- Trigger type (1 bit per source: 1 = edge, 0 = level)
- Pending status (read-only), plus a way for software to clear a stuck edge pending bit
- Threshold
- Claim (read) / Complete (write)
- Something to let firmware see which levels are currently in service, for debug

The output to the core is a level `irq` that stays high while there is a claimable interrupt.
Clock is 100 MHz; source-to-`irq` latency should be "a few cycles".
