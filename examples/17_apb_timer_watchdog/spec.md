# TMRWDT – Dual Timer + Watchdog Peripheral

**Document:** TMRWDT-PRM rev 0.3 (programmer's reference model)
**Bus:** AMBA APB3, 32-bit data, 12-bit address offset, little-endian
**Clock:** PCLK (up to 100 MHz) **Reset:** PRESETn, active low

## 1. Functional summary

TMRWDT contains two identical 32-bit general-purpose down-counting timers (TIMER0, TIMER1)
and one 32-bit watchdog (WDT). Each timer has an 8-bit prescaler, one-shot and periodic
modes, and a compare match. The watchdog generates a warning interrupt on first expiry and a
reset request on second expiry, supports windowed kicking, and has its configuration
protected by a lock key.

Outputs:
- `timer_irq` – level, active high, OR of enabled timer interrupt sources.
- `wdt_irq` – level, active high, watchdog warning interrupt.
- `wdt_rst_req` – active high, to the system reset controller. Once asserted it stays
  asserted until PRESETn.

## 2. Register map

| Offset | Name | Access | Reset | Description |
|--------|------|--------|-------|-------------|
| 0x000 | T0_CTRL | RW | 0x0000_0000 | Timer 0 control |
| 0x004 | T0_LOAD | RW | 0x0000_0000 | Timer 0 reload value |
| 0x008 | T0_VALUE | RO | 0x0000_0000 | Timer 0 current count |
| 0x00C | T0_CMP | RW | 0x0000_0000 | Timer 0 compare value |
| 0x010 | T1_CTRL | RW | 0x0000_0000 | Timer 1 control |
| 0x014 | T1_LOAD | RW | 0x0000_0000 | Timer 1 reload value |
| 0x018 | T1_VALUE | RO | 0x0000_0000 | Timer 1 current count |
| 0x01C | T1_CMP | RW | 0x0000_0000 | Timer 1 compare value |
| 0x020 | IRQ_STATUS | RW1C | 0x0000_0000 | Raw timer interrupt status |
| 0x024 | IRQ_EN | RW | 0x0000_0000 | Timer interrupt enables |
| 0x028 | IRQ_MASKED | RO | 0x0000_0000 | IRQ_STATUS & IRQ_EN |
| 0x100 | WDT_LOAD | RW (lock) | 0xFFFF_FFFF | Watchdog reload value |
| 0x104 | WDT_VALUE | RO | 0xFFFF_FFFF | Watchdog current count |
| 0x108 | WDT_CTRL | RW (lock) | 0x0000_0000 | Watchdog control |
| 0x10C | WDT_WINDOW | RW (lock) | 0x0000_0000 | Window open threshold |
| 0x110 | WDT_KICK | WO | – | Write KICK key to service the watchdog |
| 0x114 | WDT_STATUS | mixed | 0x0000_0004 | Watchdog status |
| 0x118 | WDT_LOCK | RW | 0x0000_0001 | Lock control |

### Tn_CTRL
| Bits | Field | Description |
|------|-------|-------------|
| 0 | EN | 1 = counter runs |
| 1 | MODE | 0 = one-shot, 1 = periodic |
| 7:2 | – | reserved, read 0 |
| 15:8 | PRESC | Count every PRESC+1 PCLK cycles |
| 31:16 | – | reserved |

Timer behaviour:
- Writing Tn_LOAD loads Tn_VALUE immediately and restarts the prescaler.
- When the counter is at 0 and a count tick occurs: the ZERO flag is set. In periodic mode
  the counter reloads from Tn_LOAD. In one-shot mode the counter stays at 0 and hardware
  clears EN.
- When a count tick makes Tn_VALUE equal to Tn_CMP, the CMP flag is set.

### IRQ_STATUS / IRQ_EN / IRQ_MASKED
| Bit | Source |
|-----|--------|
| 0 | T0_ZERO |
| 1 | T0_CMP |
| 2 | T1_ZERO |
| 3 | T1_CMP |

`timer_irq = |IRQ_MASKED[3:0]`.

### WDT_CTRL
| Bits | Field | Description |
|------|-------|-------------|
| 0 | EN | Watchdog enable |
| 1 | RES_EN | Allow reset request |
| 2 | WIN_EN | Enable window mode |
| 3 | INT_EN | Enable warning interrupt |
| 15:8 | PRESC | Count every PRESC+1 PCLK cycles |

### WDT_KICK
Writing 0x5A5A_A5A5 reloads WDT_VALUE from WDT_LOAD and clears WARN.
If WIN_EN = 1 and WDT_VALUE > WDT_WINDOW at the time of the kick, this is a window
violation.

### WDT_STATUS
| Bit | Field | Access | Description |
|-----|-------|--------|-------------|
| 0 | WARN | RW1C | First expiry occurred |
| 1 | WIN_VIOL | RO | Window violation occurred (sticky until reset) |
| 2 | LOCKED | RO | Mirrors lock state |

### WDT_LOCK
Writing 0x1ACC_E551 unlocks WDT_LOAD, WDT_CTRL and WDT_WINDOW. Writing any other value
locks them. Reads return 1 when locked. Locked out of reset.

## 3. Watchdog behaviour

1. While EN = 1, WDT_VALUE counts down once per watchdog tick.
2. At the tick where WDT_VALUE is 0: if WARN = 0, set WARN and reload. If WARN = 1
   (software did not service the warning), assert `wdt_rst_req` if RES_EN = 1.
3. A window violation asserts `wdt_rst_req` immediately if RES_EN = 1.

## 4. Bus behaviour

- Zero wait states (PREADY tied high).
- PSLVERR is returned for accesses to unmapped offsets.
- Writes to reserved bits are ignored; reserved bits read as zero.
