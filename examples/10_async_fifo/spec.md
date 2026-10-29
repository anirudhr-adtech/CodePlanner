ASYNC FIFO — camera pixel bridge

* wr side: sensor pixel clock, 74.25 MHz (can stop when sensor is off)
* rd side: system clock, 200 MHz
* clocks fully async, no phase relationship
* data: 24-bit RGB + 1 bit SOF + 1 bit EOL = 26 bits (make width a parameter)
* depth: 32 (parameter, power of 2 OK)
* wr: wr_en, wr_data, wr_full, wr_almost_full (threshold = parameter)
* rd: rd_en, rd_data, rd_empty, rd_almost_empty (threshold = parameter)
* standard style: registered read data, 1 cycle after rd_en
* each side has its own reset, active low; resets can come at different times
* Gray pointers + 2FF syncs, must be CDC-clean (we run SpyGlass CDC)
* need the timing constraints too
* no data loss / no duplication ever, full/empty may be pessimistic
