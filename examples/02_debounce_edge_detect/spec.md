Hi team,

We're building a small control panel for our industrial kiosk and we have four mechanical
push buttons wired straight to FPGA pins. Right now the firmware sees multiple presses every
time someone pushes a button, which I'm told is "bounce". We need a hardware block that
cleans this up.

What we want: for each button, a clean level signal that only changes after the button has
been stable for a while, around 10 ms is what our hardware guy suggests, but we'd like to be
able to change that when we build the bitstream. The board clock is 50 MHz today, but the next
revision will be 100 MHz, so please don't hard-code it.

The firmware also really only cares about the moment a button is pressed and the moment it's
released, so it would be great to get a one-clock pulse for each of those events.

The buttons are active-low on the board (pressed = 0), but we'd prefer the block's output to be
"1 = pressed". There's a global reset coming from our reset controller, active-low.

Also, these pins are obviously not synchronized to anything, so please make sure that's handled
properly. Our last vendor's design had metastability problems.

Thanks,
Priya
