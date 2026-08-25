# 人工价格序列 × 固定动作序列 审计输出

环境: AuditBase3RLModel.MyRLEnv (真实固定版本类)
价格: open=high=low=close=series 值, volume=1, 30 根 1h
window_size=1, seed=42, stake_amount=100(不复利), can_short=False

### constant fee=0.0 t1_all_hold: final_total_profit=1.00000000, final_total_reward=-28.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### constant fee=0.0 t2_enter_hold: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.00000000
### constant fee=0.0 t3_enter_exit: final_total_profit=1.00000000, final_total_reward=-0.003, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### constant fee=0.0 t4_repeat_enter: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.00000000
### constant fee=0.0 t5_repeat_exit_flat: final_total_profit=1.00000000, final_total_reward=-56.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### constant fee=0.0 t6_alt_enter_exit: final_total_profit=1.00000000, final_total_reward=350.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### constant fee=0.0 t7_hold_to_end: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.00000000
### constant fee=0.001 t1_all_hold: final_total_profit=1.00000000, final_total_reward=-28.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### constant fee=0.001 t2_enter_hold: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=-0.00199700
### constant fee=0.001 t3_enter_exit: final_total_profit=0.99800300, final_total_reward=-149.704, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### constant fee=0.001 t4_repeat_enter: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=-0.00199700
### constant fee=0.001 t5_repeat_exit_flat: final_total_profit=1.00000000, final_total_reward=-56.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### constant fee=0.001 t6_alt_enter_exit: final_total_profit=0.97204194, final_total_reward=-1745.806, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### constant fee=0.001 t7_hold_to_end: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=-0.00199700
### rising fee=0.0 t1_all_hold: final_total_profit=1.00000000, final_total_reward=-28.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### rising fee=0.0 t2_enter_hold: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=12.10999419
### rising fee=0.0 t3_enter_exit: final_total_profit=1.21000000, final_total_reward=362.997, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### rising fee=0.0 t4_repeat_enter: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=12.10999419
### rising fee=0.0 t5_repeat_exit_flat: final_total_profit=1.00000000, final_total_reward=-56.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### rising fee=0.0 t6_alt_enter_exit: final_total_profit=2.40000000, final_total_reward=4970.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### rising fee=0.0 t7_hold_to_end: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=12.10999419
### rising fee=0.001 t1_all_hold: final_total_profit=1.00000000, final_total_reward=-28.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### rising fee=0.001 t2_enter_hold: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=12.08381348
### rising fee=0.001 t3_enter_exit: final_total_profit=1.20758363, final_total_reward=362.272, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### rising fee=0.001 t4_repeat_enter: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=12.08381348
### rising fee=0.001 t5_repeat_exit_flat: final_total_profit=1.00000000, final_total_reward=-56.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### rising fee=0.001 t6_alt_enter_exit: final_total_profit=2.36924614, final_total_reward=4960.774, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### rising fee=0.001 t7_hold_to_end: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=12.08381348
### falling fee=0.0 t1_all_hold: final_total_profit=1.00000000, final_total_reward=-28.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### falling fee=0.0 t2_enter_hold: final_total_profit=1.00000000, final_total_reward=24.907, terminated=True, last_pos=Long, unreal_pnl_end=-0.52170310
### falling fee=0.0 t3_enter_exit: final_total_profit=0.81000000, final_total_reward=-121.503, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### falling fee=0.0 t4_repeat_enter: final_total_profit=1.00000000, final_total_reward=24.907, terminated=True, last_pos=Long, unreal_pnl_end=-0.52170310
### falling fee=0.0 t5_repeat_exit_flat: final_total_profit=1.00000000, final_total_reward=-56.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### falling fee=0.0 t6_alt_enter_exit: final_total_profit=0.50000000, final_total_reward=-550.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### falling fee=0.0 t7_hold_to_end: final_total_profit=1.00000000, final_total_reward=24.907, terminated=True, last_pos=Long, unreal_pnl_end=-0.52170310
### falling fee=0.001 t1_all_hold: final_total_profit=1.00000000, final_total_reward=-28.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### falling fee=0.001 t2_enter_hold: final_total_profit=1.00000000, final_total_reward=24.907, terminated=True, last_pos=Long, unreal_pnl_end=-0.52265826
### falling fee=0.001 t3_enter_exit: final_total_profit=0.80838243, final_total_reward=-121.261, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### falling fee=0.001 t4_repeat_enter: final_total_profit=1.00000000, final_total_reward=24.907, terminated=True, last_pos=Long, unreal_pnl_end=-0.52265826
### falling fee=0.001 t5_repeat_exit_flat: final_total_profit=1.00000000, final_total_reward=-56.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### falling fee=0.001 t6_alt_enter_exit: final_total_profit=0.49101348, final_total_reward=-548.652, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### falling fee=0.001 t7_hold_to_end: final_total_profit=1.00000000, final_total_reward=24.907, terminated=True, last_pos=Long, unreal_pnl_end=-0.52265826
### zigzag fee=0.0 t1_all_hold: final_total_profit=1.00000000, final_total_reward=-28.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### zigzag fee=0.0 t2_enter_hold: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.44444444
### zigzag fee=0.0 t3_enter_exit: final_total_profit=0.88888889, final_total_reward=-133.337, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### zigzag fee=0.0 t4_repeat_enter: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.44444444
### zigzag fee=0.0 t5_repeat_exit_flat: final_total_profit=1.00000000, final_total_reward=-56.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### zigzag fee=0.0 t6_alt_enter_exit: final_total_profit=6.19166667, final_total_reward=6107.500, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### zigzag fee=0.0 t7_hold_to_end: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.44444444
### zigzag fee=0.001 t1_all_hold: final_total_profit=1.00000000, final_total_reward=-28.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### zigzag fee=0.001 t2_enter_hold: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.44155988
### zigzag fee=0.001 t3_enter_exit: final_total_profit=0.88711377, final_total_reward=-133.070, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### zigzag fee=0.001 t4_repeat_enter: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.44155988
### zigzag fee=0.001 t5_repeat_exit_flat: final_total_profit=1.00000000, final_total_reward=-56.000, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### zigzag fee=0.001 t6_alt_enter_exit: final_total_profit=6.15334083, final_total_reward=6096.002, terminated=True, last_pos=Neutral, unreal_pnl_end=0.00000000
### zigzag fee=0.001 t7_hold_to_end: final_total_profit=1.00000000, final_total_reward=23.740, terminated=True, last_pos=Long, unreal_pnl_end=0.44155988

## reset 语义快照

reset 前(2 步后): {'_current_tick': 3, '_position': 'Long', '_last_trade_tick': 2, '_total_profit': 1.0, 'total_reward': 24.996666666666666, 'trade_history_len': 1}
reset 后: {'_current_tick': 1, '_position': 'Neutral', '_last_trade_tick': None, '_total_profit': 1.0, 'total_reward': 0.0, 'trade_history_len': 0, '_start_tick': 1, '_end_tick': 29}

## randomize_starting_position=True 时 _start_tick(seed 1/2/3): [7, 3, 5]

## 手算对照(与 CSV 逐项比较)

1. 上涨 long 100→110, fee=0.001: entry_adj=100.100000, exit_adj=109.890110, 预期 pnl=0.09780330 (9.78033%)
   无费 pnl=0.10000000;费差=0.00219670
2. 下跌 long 100→90, fee=0.001: 预期 pnl=-0.10179730;无费=-0.10000000;费差=0.00179730
3. 恒定价格开平 100→100, fee=0.001: 预期 pnl=-0.0019970040 (≈ -2*fee = -0.002)
   无费 pnl=0.0000000000;费差=0.0019970040
