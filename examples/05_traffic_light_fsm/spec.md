Traffic light controller for a 4-way intersection (north-south road crossing east-west road).

Needs to:
* Cycle NS and EW: green, yellow, then red, with the usual safety gap where both are red.
* Have car sensors on both roads. If cars keep coming on the road that's green, keep it green
  longer, but not forever. If nobody is waiting on the other road there's no need to switch.
* Pedestrian push buttons for each crossing. Pedestrians get a WALK light, then a flashing
  DON'T WALK before the lights change.
* Yellow about 4 seconds. Green at least 10 seconds.

The FPGA board runs at 50 MHz. Sensors and buttons come from the field wiring.

(Exact timing and what to do on power-up TBD — use sensible values.)
