Hi team,

For the next board rev we need our own UART block instead of the vendor IP. It talks to a
GPS module and a debug console, so it has to be reliable at 9600 baud and also at
115200 baud. Our system clock is 50 MHz, but other projects run at 100 MHz, so please
don't hard-code it. Firmware should be able to set the baud rate at runtime through a
divider value.

Frame format is the usual 8 data bits, 1 stop bit, LSB first. Some GPS modules use parity,
so even/odd parity has to be optional and switchable at runtime. When a received byte has a
bad stop bit or a parity mismatch, the CPU needs to know which byte was affected, not just
that an error happened at some point.

The receiver should oversample at 16x and sample in the middle of each bit. The line is
noisy, so some glitch filtering would be appreciated. Please also make sure a short glitch
on the idle line isn't taken as a start bit.

The CPU is slow to service interrupts, so put a small FIFO on each side (8 bytes is
probably enough). If the RX FIFO overflows we must know about it. The CPU side should look
like a simple valid/ready stream on both directions; the register wrapper is done
separately by another team.

Thanks,
Priya
