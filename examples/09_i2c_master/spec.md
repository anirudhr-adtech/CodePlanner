i2c master - quick notes from arch review

- talks to the EEPROM (24C256) and the PMIC on the same bus
- needs std mode 100k and fast mode 400k
- start / stop / repeated start (EEPROM random read needs Sr)
- 7 bit addressing only
- detect ACK/NACK from slave; master must NACK the last byte of a read
- PMIC does clock stretching, must support it
- there's a debug MCU that can also master the bus sometimes -> need arbitration loss detection
- SCL/SDA are open drain pads w/ external pullups
- clk: whatever the SoC peripheral clock is, probably 48 MHz
- CPU interface: TBD, something simple that firmware can drive byte-by-byte, with an irq
- Ravi says the bus is noisy near the DC-DC, maybe filter inputs?
