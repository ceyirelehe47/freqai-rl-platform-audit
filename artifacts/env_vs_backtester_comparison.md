# RL 训练环境 vs Freqtrade 回测器对比(相同锯齿数据,fee=0.001,stake=100)

锯齿序列(索引:价格): 0:100.0, 1:110.0, 2:90.0, 3:120.0, 4:80.0, 5:130.0,…循环

## RL 三动作环境(t3_enter_exit,来自 synthetic_zigzag_trace.csv)
- 观察窗口末行 = 数据行 0(00:00,价格100;obs 不含当前 tick)
- Enter 执行: tick 2(02:00), 价格 open=90.0
- Exit 执行: tick 4(04:00), 价格 open=80.0
- 平仓后 total_profit = 0.8871137742266615,单笔净值变化 = -0.11288623

## Freqtrade 回测器(真实 Backtesting.start(),虚拟市场 monkeypatch)
### FixedSignalA
- open_date=2026-06-01 01:00:00+00:00 open_rate=110.0 | close_date=2026-06-01 03:00:00+00:00 close_rate=120.0 | profit_ratio=0.08872945 profit_abs=8.880930 | exit_reason=exit_signal is_open=False
### FixedSignalB
- open_date=2026-06-01 02:00:00+00:00 open_rate=90.0 | close_date=2026-06-01 04:00:00+00:00 close_rate=80.0 | profit_ratio=-0.11288711 profit_abs=-11.299887 | exit_reason=exit_signal is_open=False

## 对照结论
- RL 环境:观察行0(00:00,100) → 动作执行在 open[2](02:00,90):错开 2 根。
- FixedSignalA(信号行0):回测成交 open[1](01:00,110):错开 1 根。
- FixedSignalB(信号行1):回测成交 open[2](02:00,90):与 RL 执行同根同价。
- 即:RL 训练环境的动作比『同信息集回测信号』晚一根 K 线执行;
  要让回测复现 RL 的成交价,必须把信号再提前一根(FixedSignalB)。
