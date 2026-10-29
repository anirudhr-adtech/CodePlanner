need an axi-stream register slice to break timing between the packet engine and the
egress shaper. we're failing timing on both tvalid/tdata and on tready going back up.

- must register everything in both directions, no comb path in -> out
- must not lose throughput, 1 beat per clock when nobody stalls
- data is 64 bit, with tkeep and tlast. maybe tuser later
- should be reusable so make the width a parameter

that's it, keep it small.
