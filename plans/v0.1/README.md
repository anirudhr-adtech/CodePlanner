# MA step plans, agent v0.1

Produced by `python3 -m agent --all` with the Claude planner and a simulated user that
answers from each example's MA doc. Each folder holds `plan.md` (readable plan),
`plan.json` (the planner contract), `qa.json` (questions the agent asked, with answers)
and `judge.json` (comparison with the MA doc answer key).

| Spec | Steps | Decisions | Defaulted | Asked | Match / key decisions | Material diffs | Missing |
|---|---|---|---|---|---|---|---|
| [01_updown_counter](01_updown_counter/plan.md) | 11 | 10 | 5 | 1 | 13/15 | 0 | 0 |
| [02_debounce_edge_detect](02_debounce_edge_detect/plan.md) | 11 | 11 | 9 | 0 | 10/13 | 0 | 0 |
| [03_pwm_generator](03_pwm_generator/plan.md) | 12 | 12 | 9 | 1 | 10/14 | 1 | 0 |
| [04_sync_fifo](04_sync_fifo/plan.md) | 11 | 12 | 7 | 3 | 13/13 | 0 | 0 |
| [05_traffic_light_fsm](05_traffic_light_fsm/plan.md) | 11 | 11 | 9 | 2 | 7/13 | 2 | 0 |
| [06_round_robin_arbiter](06_round_robin_arbiter/plan.md) | 11 | 11 | 6 | 3 | 10/14 | 0 | 1 |
| [07_uart_transceiver](07_uart_transceiver/plan.md) | 12 | 12 | 7 | 0 | 13/15 | 0 | 0 |
| [08_spi_master](08_spi_master/plan.md) | 12 | 11 | 8 | 2 | 13/15 | 0 | 2 |
| [09_i2c_master](09_i2c_master/plan.md) | 11 | 12 | 5 | 1 | 14/16 | 2 | 0 |
| [10_async_fifo](10_async_fifo/plan.md) | 11 | 11 | 6 | 2 | 11/14 | 1 | 1 |
| [11_interrupt_controller](11_interrupt_controller/plan.md) | 11 | 12 | 8 | 2 | 12/15 | 1 | 0 |
| [12_crc32_engine](12_crc32_engine/plan.md) | 12 | 12 | 7 | 2 | 5/12 | 3 | 1 |
| [13_pipelined_mac](13_pipelined_mac/plan.md) | 12 | 11 | 8 | 1 | 8/14 | 2 | 2 |
| [14_fir_filter](14_fir_filter/plan.md) | 12 | 12 | 9 | 2 | 12/15 | 1 | 2 |
| [15_axi_lite_regfile](15_axi_lite_regfile/plan.md) | 11 | 11 | 7 | 1 | 13/15 | 0 | 1 |
| [16_axis_skid_buffer](16_axis_skid_buffer/plan.md) | 11 | 11 | 9 | 0 | 12/14 | 0 | 0 |
| [17_apb_timer_watchdog](17_apb_timer_watchdog/plan.md) | 12 | 12 | 8 | 2 | 12/16 | 0 | 4 |
| [18_direct_mapped_cache](18_direct_mapped_cache/plan.md) | 12 | 11 | 7 | 2 | 12/14 | 2 | 0 |
| [19_dma_controller](19_dma_controller/plan.md) | 12 | 11 | 7 | 2 | 10/14 | 1 | 2 |
| [20_rv32i_5stage_pipeline](20_rv32i_5stage_pipeline/plan.md) | 12 | 12 | 5 | 2 | 11/14 | 2 | 0 |
