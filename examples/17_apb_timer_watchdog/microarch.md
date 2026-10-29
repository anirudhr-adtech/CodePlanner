# Micro-architecture: `tmrwdt`

## 1. Overview

`tmrwdt` is an APB3 slave peripheral containing two identical general-purpose timers and a
watchdog. Everything runs on PCLK. The block has three parts: a bus-interface unit that
decodes APB accesses into per-register write and read strobes, two instances of a timer
core (`tmr_core`), and one watchdog core (`wdt_core`). Interrupt status registers and the
output interrupt logic sit at the top level.

Key features:
- Zero-wait-state APB3 slave (PREADY = 1); PSLVERR on unmapped offsets.
- Two 32-bit down-counters with an 8-bit prescaler (divide by 1..256), one-shot and periodic modes, and a compare match.
- Four RW1C timer interrupt sources with individual enables; a level `timer_irq` output.
- A 32-bit watchdog with an 8-bit prescaler, a two-stage expiry (warning interrupt, then reset request), window mode, a kick key and a lock key protecting its configuration.
- A sticky `wdt_rst_req` output, cleared only by PRESETn.

Timer period: `T = (LOAD + 1) × (PRESC + 1)` PCLK cycles.
Watchdog timeout to warning: `(WDT_LOAD + 1) × (PRESC + 1)` cycles; to reset: twice that.

## 2. Interface

| Name | Dir | Width | Description |
|------|-----|-------|-------------|
| **APB3 slave** | | | |
| `PCLK` | in | 1 | Peripheral clock; all logic is rising-edge triggered. |
| `PRESETn` | in | 1 | Active-low reset (async assert, sync de-assert at SoC level). |
| `PSEL` | in | 1 | Slave select. |
| `PENABLE` | in | 1 | Access phase. |
| `PWRITE` | in | 1 | 1 = write, 0 = read. |
| `PADDR` | in | 12 | Byte address offset; bits [1:0] ignored. |
| `PWDATA` | in | 32 | Write data. |
| `PRDATA` | out | 32 | Read data, valid in the access phase. |
| `PREADY` | out | 1 | Tied 1. |
| `PSLVERR` | out | 1 | Error response in the access phase for unmapped offsets. |
| **Interrupts / reset** | | | |
| `timer_irq` | out | 1 | `\|(irq_status & irq_en)`, level, active high. |
| `wdt_irq` | out | 1 | `warn_q & wdt_int_en`, level, active high. |
| `wdt_rst_req` | out | 1 | Watchdog reset request, registered, sticky until PRESETn. |

## 3. Parameters

| Name | Default | Legal range | Description |
|------|---------|-------------|-------------|
| `NUM_TIMERS` | 2 | fixed 2 | Kept as a localparam; the register map is laid out for 2 timers. |
| `KICK_KEY` | 32'h5A5A_A5A5 | any | Value that services the watchdog. |
| `UNLOCK_KEY` | 32'h1ACC_E551 | any | Value that unlocks the watchdog configuration. |
| `WDT_LOAD_RST` | 32'hFFFF_FFFF | any | Reset value of WDT_LOAD and WDT_VALUE. |
| `PRESC_W` | 8 | fixed 8 | Prescaler width (localparam, matches the register field). |

## 4. Block Diagram

```
          APB3                                                     timer_irq
  PSEL/PENABLE/PWRITE  +------------------+   wr/rd strobes    +-----------+  ^
  PADDR/PWDATA ------->|  u_apb           |------------------->| u_t0      |--+-- zero/cmp evt --+
  PRDATA/PSLVERR <-----|  apb_regif       |<-- rdata T0 -------| tmr_core  |                    |
                       |  - addr decode   |                    +-----------+                    v
                       |  - wr strobes    |------------------->| u_t1      |-- zero/cmp evt -->+---------+
                       |  - PRDATA mux    |<-- rdata T1 -------| tmr_core  |                   | irq_regs|
                       |  - PSLVERR       |                    +-----------+                   | status, |
                       |                  |----------------------------------------------->   | enable  |
                       |                  |<---------------- IRQ_STATUS/EN/MASKED ------------+---------+
                       |                  |                    +-----------+
                       |                  |------------------->| u_wdt     |---> wdt_irq
                       |                  |<-- rdata WDT ------| wdt_core  |---> wdt_rst_req
                       +------------------+                    +-----------+
```

| Instance | Module | Purpose |
|----------|--------|---------|
| `u_apb` | `apb_regif` | Decodes APB access into one-hot register strobes, builds PRDATA and PSLVERR. |
| `u_t0`, `u_t1` | `tmr_core` | Prescaler, 32-bit down-counter, compare, event pulses. Created with `generate`. |
| `u_wdt` | `wdt_core` | Watchdog counter, lock, kick/window checking, warning and reset request. |
| — (inline) | irq regs | `irq_status[3:0]` (RW1C), `irq_en[3:0]`, `timer_irq` output. |

## 5. Datapath

### 5.1 Bus interface (`apb_regif`)

```verilog
wire acc     = PSEL & PENABLE;          // access phase
wire wr      = acc &  PWRITE;
wire rd      = acc & ~PWRITE;
wire [9:0] a = PADDR[11:2];             // word index
```

The address decoder produces a one-hot `hit[17:0]` with one bit per register in the map.
`mapped = |hit`. Write strobes: `we_<reg> = wr & hit_<reg>`. Writes to RO registers
(Tn_VALUE, IRQ_MASKED, WDT_VALUE) produce no strobe and no error.

`PRDATA` is a combinational AND-OR mux of `hit` with each register's read value. It is
zero when `!rd` or when unmapped, which keeps the bus quiet when the slave is not selected.
`PSLVERR = acc & ~mapped`. `PREADY = 1'b1`.

### 5.2 Timer core (`tmr_core`, one per timer)

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `en_q` | 1 | 0 | CTRL.EN |
| `mode_q` | 1 | 0 | CTRL.MODE (1 = periodic) |
| `presc_q` | 8 | 0 | CTRL.PRESC |
| `load_q` | 32 | 0 | Tn_LOAD |
| `cmp_q` | 32 | 0 | Tn_CMP |
| `value_q` | 32 | 0 | Tn_VALUE (down-counter) |
| `pcnt_q` | 8 | 0 | Prescaler counter |

Datapath equations:

```verilog
wire tick    = en_q & (pcnt_q >= presc_q);          // >= : safe if PRESC is lowered mid-count
wire expire  = tick & (value_q == 32'd0);
wire [31:0] value_dec = expire ? (mode_q ? load_q : 32'd0) : value_q - 32'd1;

// prescaler
pcnt_n  = (we_load | ~en_q | tick) ? 8'd0 : pcnt_q + 8'd1;

// counter: SW load has priority over a hardware tick
value_n = we_load ? PWDATA : (tick ? value_dec : value_q);

// enable: SW write to CTRL has priority over hardware clear in one-shot
en_n    = we_ctrl ? PWDATA[0] : ((expire & ~mode_q) ? 1'b0 : en_q);

// events (single-cycle pulses)
zero_evt = expire;
cmp_evt  = tick & ~we_load & (value_dec == cmp_q) & ~(expire & ~mode_q);
```

`cmp_evt` is suppressed on the one-shot expiry tick, because the value does not change
there (it stays 0). Without this, `CMP = 0` would fire twice. In periodic mode a reload to
`LOAD == CMP` does produce a compare match, which is consistent with "a count tick makes
VALUE equal CMP".

The two equality comparators (`value_q == 0`, `value_dec == cmp_q`) and the 32-bit
decrementer are the main logic, about 32-bit adder depth.

### 5.3 Interrupt registers (top level)

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `irq_status` | 4 | 0 | {T1_CMP, T1_ZERO, T0_CMP, T0_ZERO}, RW1C |
| `irq_en` | 4 | 0 | Enables |

```verilog
wire [3:0] set_v = {t1_cmp_evt, t1_zero_evt, t0_cmp_evt, t0_zero_evt};
wire [3:0] clr_v = we_irq_status ? PWDATA[3:0] : 4'b0;
irq_status_n = (irq_status & ~clr_v) | set_v;    // hardware set wins over W1C
timer_irq    = |(irq_status & irq_en);
```

### 5.4 Watchdog core (`wdt_core`)

| Register | Width | Reset | Purpose |
|----------|-------|-------|---------|
| `wload_q` | 32 | 0xFFFF_FFFF | WDT_LOAD |
| `wvalue_q` | 32 | 0xFFFF_FFFF | WDT_VALUE |
| `wen_q` | 1 | 0 | CTRL.EN |
| `res_en_q` | 1 | 0 | CTRL.RES_EN |
| `win_en_q` | 1 | 0 | CTRL.WIN_EN |
| `int_en_q` | 1 | 0 | CTRL.INT_EN |
| `wpresc_q` | 8 | 0 | CTRL.PRESC |
| `wpcnt_q` | 8 | 0 | Prescaler counter |
| `window_q` | 32 | 0 | WDT_WINDOW |
| `warn_q` | 1 | 0 | STATUS.WARN |
| `win_viol_q` | 1 | 0 | STATUS.WIN_VIOL |
| `locked_q` | 1 | 1 | Lock state |
| `rst_req_q` | 1 | 0 | `wdt_rst_req` |

```verilog
wire cfg_we_ok = ~locked_q;                                 // gate for LOAD/CTRL/WINDOW
wire kick      = we_kick & (PWDATA == KICK_KEY);
wire win_bad   = kick & win_en_q & (wvalue_q > window_q);   // unsigned compare
wire kick_ok   = kick & ~win_bad;
wire wtick     = wen_q & ~rst_req_q & (wpcnt_q >= wpresc_q);
wire wexpire   = wtick & (wvalue_q == 32'd0);

wvalue_n   = kick_ok ? wload_q
           : wexpire ? wload_q
           : wtick   ? wvalue_q - 1
           :           wvalue_q;
warn_n     = kick_ok ? 1'b0
           : (wexpire & ~warn_q) ? 1'b1
           : (we_wstatus & PWDATA[0]) ? 1'b0
           : warn_q;
win_viol_n = win_viol_q | win_bad;
rst_req_n  = rst_req_q | (res_en_q & ((wexpire & warn_q) | win_bad));
locked_n   = we_lock ? (PWDATA != UNLOCK_KEY) : locked_q;
```

Priority for `warn_n`: a kick clears it; a first expiry sets it; then a software W1C;
otherwise it holds. A first expiry (`wexpire & ~warn_q`) and a W1C in the same cycle
resolve to WARN = 1 (hardware set wins, the same rule as the timers).

## 6. Control Logic

### 6.1 Timer mode behaviour (per `tmr_core`)

The timer has no encoded FSM; its state is (`en_q`, `mode_q`, `value_q`).

| State | Condition | On `tick` | Next |
|-------|-----------|-----------|------|
| STOPPED | `en_q = 0` | – (no tick) | STOPPED until a CTRL write sets EN |
| COUNTING | `en_q = 1`, `value_q != 0` | `value - 1`; `cmp_evt` if result == CMP | COUNTING / AT_ZERO |
| AT_ZERO, periodic | `en_q = 1`, `value_q == 0`, `mode_q = 1` | `zero_evt`, reload LOAD | COUNTING (or AT_ZERO if LOAD = 0) |
| AT_ZERO, one-shot | `en_q = 1`, `value_q == 0`, `mode_q = 0` | `zero_evt`, EN ← 0 | STOPPED |

A Tn_LOAD write in any state loads VALUE and clears the prescaler. That restarts the
period cleanly. Setting EN does not reload; software re-arms a one-shot by writing LOAD.

### 6.2 Watchdog state machine

The watchdog state is encoded by (`wen_q`, `warn_q`, `rst_req_q`). These bits are visible
to software, so no separate state register is needed.

| State | `wen` | `warn` | `rst_req` | Event | Action | Next |
|-------|-------|--------|-----------|-------|--------|------|
| OFF | 0 | x | 0 | CTRL write EN=1 (unlocked) | – | RUN or WARNED |
| RUN | 1 | 0 | 0 | `wexpire` | WARN←1, reload, `wdt_irq` if INT_EN | WARNED |
| RUN | 1 | 0 | 0 | `kick_ok` | reload | RUN |
| RUN/WARNED | 1 | x | 0 | `win_bad` | WIN_VIOL←1; RST_REQ←1 if RES_EN | FIRED / unchanged |
| WARNED | 1 | 1 | 0 | `kick_ok` | WARN←0, reload | RUN |
| WARNED | 1 | 1 | 0 | `wexpire`, RES_EN=1 | RST_REQ←1 | FIRED |
| WARNED | 1 | 1 | 0 | `wexpire`, RES_EN=0 | reload; WARN stays 1 | WARNED |
| FIRED | x | x | 1 | any | counter frozen; waits for PRESETn | FIRED |

### 6.3 Lock

| `locked_q` | Write to WDT_LOAD / WDT_CTRL / WDT_WINDOW | Write to WDT_LOCK | Write to WDT_KICK |
|------------|-------------------------------------------|-------------------|-------------------|
| 1 | Ignored (no PSLVERR) | `UNLOCK_KEY` → 0; other → 1 | Always allowed |
| 0 | Written | `UNLOCK_KEY` → 0; other → 1 | Always allowed |

Gated strobes inside `wdt_core`: `we_wload_g = we_wload & ~locked_q`, and the same for
CTRL and WINDOW. A write to WDT_LOCK and a config write cannot occur in the same cycle (one
APB access per cycle), so lock and access never race.

### 6.4 Read-value mapping

| Register | Read value |
|----------|-----------|
| Tn_CTRL | `{16'b0, presc_q, 6'b0, mode_q, en_q}` |
| IRQ_MASKED | `{28'b0, irq_status & irq_en}` |
| WDT_CTRL | `{16'b0, wpresc_q, 4'b0, int_en_q, win_en_q, res_en_q, wen_q}` |
| WDT_STATUS | `{29'b0, locked_q, win_viol_q, warn_q}` |
| WDT_LOCK | `{31'b0, locked_q}` |
| WDT_KICK | `32'b0` (write-only) |

## 7. Timing & Pipeline

- **APB access:** 2 cycles (setup + access), zero wait states. Writes commit at the rising edge that ends the access phase. Read data reflects register state during the access phase.
- **Write-to-effect:** register visible to hardware in the cycle after the access phase.
- **Event-to-interrupt latency:** `zero_evt` at cycle N → `irq_status` set at N+1 → `timer_irq` high at N+1 (combinational AND-OR from registered status).
- **Interrupt clear:** a W1C in the access phase at cycle N → `timer_irq` low at N+1 (unless the event re-fires at N).
- **Critical paths:** `value_q` → 32-bit decrement → `== cmp_q` → `irq_status`; PADDR → decoder → 18:1 PRDATA mux → bus. Both are well under 10 ns at 100 MHz in typical processes.

Cycle-by-cycle timer 0 example: LOAD = 2 (already written, VALUE = 2), PRESC = 1, periodic,
IRQ_EN[0] = 1. Cycle 0 is the access phase of the CTRL write (EN=1, MODE=1, PRESC=1).

| Cycle | en_q | pcnt_q | tick | value_q | value_n | zero_evt | irq_status[0] | timer_irq |
|-------|------|--------|------|---------|---------|----------|---------------|-----------|
| 0 | 0 | 0 | 0 | 2 | 2 | 0 | 0 | 0 |
| 1 | 1 | 0 | 0 | 2 | 2 | 0 | 0 | 0 |
| 2 | 1 | 1 | 1 | 2 | 1 | 0 | 0 | 0 |
| 3 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 0 |
| 4 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| 5 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 6 | 1 | 1 | 1 | 0 | 2 | **1** | 0 | 0 |
| 7 | 1 | 0 | 0 | 2 | 2 | 0 | **1** | **1** |
| … | | | | | | | | |
| 12 | 1 | 1 | 1 | 0 | 2 | **1** | 1 | 1 |

The interval between `zero_evt` pulses is 6 cycles = (2 + 1) × (1 + 1), matching the formula.

Watchdog sequence (PRESC = 0, LOAD = 3, RES_EN = INT_EN = 1, never kicked):

| Cycle | wvalue_q | wexpire | warn_q | wdt_irq | rst_req_q |
|-------|----------|---------|--------|---------|-----------|
| t | 0 | 1 | 0 | 0 | 0 |
| t+1 | 3 | 0 | 1 | 1 | 0 |
| t+2 | 2 | 0 | 1 | 1 | 0 |
| t+3 | 1 | 0 | 1 | 1 | 0 |
| t+4 | 0 | 1 | 1 | 1 | 0 |
| t+5 | 0 (frozen) | 0 | 1 | 1 | **1** |

From first expiry to reset request: (LOAD + 1) × (PRESC + 1) = 4 cycles, matching §1.

## 8. Clocking & Reset

- **One clock domain** (PCLK). No CDC inside the block. `wdt_rst_req` leaves the domain to
  the reset controller, which must synchronize it if it runs on a different clock. The
  signal is registered and glitch-free.
- **Reset:** PRESETn, active low, async assert / sync de-assert. All registers reset to the
  values in §5 (notably `locked_q = 1`, `wload_q = wvalue_q = 32'hFFFF_FFFF`).
- **`wdt_rst_req` loop:** the SoC reset controller resets this block with PRESETn when the
  request fires, which clears `rst_req_q`. The reset controller must stretch its own reset
  pulse; this block guarantees the request stays high until PRESETn arrives.
- Clock gating is not used; `en_q = 0` stops the counters, so the dynamic power of the
  idle counters is just the register clock load.

## 9. Corner Cases & Error Handling

| Case | Behaviour |
|------|-----------|
| Unmapped offset (read or write) | PSLVERR = 1 in the access phase; write ignored; PRDATA = 0. |
| Write to RO register (Tn_VALUE, IRQ_MASKED, WDT_VALUE, WDT_STATUS bits 1–2) | Ignored, no error. |
| Read of WDT_KICK | Returns 0, no error. |
| Tn_LOAD write in the same cycle as a tick | Load wins; prescaler restarts; no event from that tick. |
| CTRL write in the same cycle as a one-shot expiry | Software EN value wins; `zero_evt` still fires. |
| PRESC lowered below the current `pcnt_q` | `>=` compare makes a tick on the next cycle; no 256-cycle stall. |
| LOAD = 0, periodic | `zero_evt` on every tick; period = PRESC + 1. |
| CMP = LOAD, periodic | CMP and ZERO fire on the same tick (reload makes VALUE == CMP). |
| W1C and hardware set on the same bit, same cycle | Set wins; the bit stays 1. |
| Kick with wrong key | Ignored entirely (no reload, no violation). |
| Kick while window closed (VALUE > WINDOW, WIN_EN = 1) | WIN_VIOL ← 1; rst_req if RES_EN; counter not reloaded. |
| WINDOW ≥ LOAD with WIN_EN = 1 | Window always open; no violations possible. |
| Kick while WDT disabled | Reloads and clears WARN; harmless. |
| Watchdog locked and enabled | Cannot be disabled by software without first unlocking (intended). |
| Expiry with RES_EN = 0 and WARN already set | Counter reloads and continues; WARN stays set; no reset. |
| After `wdt_rst_req` asserts | Watchdog counter frozen; APB still operates normally until PRESETn. |

## 10. Verification Plan

**Environment:** a UVM-lite SystemVerilog testbench with an APB3 master BFM, a register
model that predicts all readable values, and a cycle-accurate reference model of each timer
and the watchdog. The scoreboard checks PRDATA on every read and the interrupt/reset outputs
on every cycle.

**Directed tests**
1. Reset values of all 18 registers; reserved bits read 0.
2. RW walking-ones on every RW register; RO registers are unaffected by writes.
3. PSLVERR on several unmapped offsets (0x02C, 0x0FC, 0x11C, 0xFFC); no side effects.
4. Timer period: sweep LOAD ∈ {0, 1, 7, 1000} × PRESC ∈ {0, 1, 255}, periodic; check event spacing = (LOAD+1)(PRESC+1).
5. One-shot: single ZERO event, EN cleared, VALUE stays 0; re-arm by writing LOAD.
6. Compare: CMP ∈ {0, LOAD, LOAD/2}, in one-shot and periodic modes; one-shot with CMP = 0 fires exactly once.
7. IRQ: enable/mask each bit; W1C clear; W1C colliding with a new event.
8. LOAD write and tick in the same cycle.
9. WDT lock: locked writes ignored; unlock, write, re-lock with an arbitrary value.
10. WDT warn → reset: no kick → WARN, `wdt_irq`, then `wdt_rst_req` sticky.
11. WDT kick inside the window (OK), outside the window (violation → reset), with a wrong key (ignored).
12. RES_EN = 0: no reset on double expiry or window violation; WIN_VIOL is still recorded.

**Random:** a random APB traffic generator (reads/writes to all offsets, including
unmapped) with random kicks, running 1M cycles with small LOAD/PRESC values so events are
frequent.

**Assertions (SVA)**

```systemverilog
a_pready:      assert property (@(posedge PCLK) PREADY);
a_slverr:      assert property (@(posedge PCLK) disable iff(!PRESETn)
                 PSLVERR |-> (PSEL && PENABLE));
a_rst_sticky:  assert property (@(posedge PCLK) disable iff(!PRESETn)
                 wdt_rst_req |=> wdt_rst_req);
a_oneshot_off: assert property (@(posedge PCLK) disable iff(!PRESETn)
                 (u_t0.expire && !u_t0.mode_q && !u_t0.we_ctrl) |=> !u_t0.en_q);
a_lock:        assert property (@(posedge PCLK) disable iff(!PRESETn)
                 (u_wdt.locked_q && u_wdt.we_wload) |=> $stable(u_wdt.wload_q));
a_irq_def:     assert property (@(posedge PCLK) timer_irq == |(irq_status & irq_en));
```

**Coverage:** every register read and written; each IRQ source set, cleared and colliding;
PRESC extremes (0, 255); timer in every row of §6.1; watchdog in every row of §6.2; lock
toggled in both directions; kick in each of {OK, window violation, wrong key, disabled}.

## 11. Assumptions & Open Questions

1. **WDT_LOAD writes do not reload the counter.** A new LOAD takes effect at the next kick or expiry. That stops a locked-out-then-unlocked rogue write from instantly extending a timeout. (The spec is silent.)
2. **Writes to locked registers are silently ignored** rather than returning PSLVERR, so software lock-probing can't fault the CPU. Confirm with the software team.
3. **A window violation does not reload** the counter, and **a wrong kick key is ignored** (it is not treated as a violation). Many safety standards treat a bad key as a fault; this could become a `BADKEY_IS_VIOL` parameter.
4. **The watchdog runs on PCLK.** Real watchdogs often use an always-on low-frequency clock so they keep running if PCLK stops. If that is needed, `wdt_core` moves into its own domain with a handshake synchronizer for register writes and a 2-flop synchronizer for `rst_req`.
5. **There is no debug-halt input** to freeze the timers or watchdog while the CPU is halted. A `dbg_halt` input gating `tick`/`wtick` is recommended.
6. **PADDR[1:0] are ignored**: APB3 accesses are word-aligned, and APB3 has no PSTRB, so every write is a full-word write.
7. **Setting EN does not reload VALUE.** Software must write LOAD to (re)start a one-shot.
8. **The counter is frozen after `rst_req`** to avoid spurious interrupts during the reset hand-off.
