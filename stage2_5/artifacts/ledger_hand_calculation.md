# 净值账本手算对照(阶段 2.5)

全部公式与 test_ledger.py / test_synthetic_sequences.py 的断言一一对应,
数值用 Python 浮点复核(相对误差 < 1e-12)。

## 基础公式(fee = f,滑点 = s bps)

```text
买入(open[t+1] = p):
  成交价   exec = p * (1 + s/10000)
  数量     qty  = cash / (exec * (1 + f))        [现金覆盖名义+费用]
  名义     notional = qty * exec = cash / (1 + f)
  费用     fee_buy = notional * f = cash * f / (1 + f)

卖出(open[t+1] = q):
  成交价   exec = q * (1 - s/10000)
  所得     proceeds = qty * exec * (1 - f)
  费用     fee_sell = qty * exec * f

完整开平(单笔收益比):
  R = q * (1 - f) / (p * (1 + f))
```

## 手算用例(f = 0.001,s = 0,cash0 = 100)

1. 买入 p=100:qty = 100/100.1 = 0.999000999...;
   名义 = 99.90009990...;费用 = 0.09990010...(=100*0.001/1.001)。
2. 同价卖出 q=100:proceeds = qty*100*0.999 = 99.80019980...;
   R = 99.8002/100 = (1-0.001)/(1+0.001) = 0.998002。
   即同价开平损失 2f/(1+f) = 0.199800%(≈ 2*单边费率)。
3. 买 110 卖 100(锯齿对齐用例):R = 100*0.999/(110*1.001) = 99.9/110.11
   = 0.9072745...,单笔 -9.2725%;与 Freqtrade 回测器 profit_ratio
   -0.0927254564 一致(公式相同)。
4. fee=0 同价开平:R = 1,净值严格回到 100(test_fee_zero_slip_zero_round_trip)。

## 滑点手算(s=5bps,f=0.001,买 p=110)

```text
exec = 110 * 1.0005 = 110.055
qty  = 100 / (110.055 * 1.001) = 0.9077...
费用 = qty * 110.055 * 0.001
滑点成本 = qty * (110.055 - 110) = qty * 0.055
```

test_slippage_formula_end_to_end 逐项断言吻合(1e-12 / 1e-9)。

## 与 Freqtrade 回测器的终值差(复利口径)

Freqtrade 的 stake = amount*rate 不为买入费预留现金(费用全部体现在
profit_abs 的 open_value*(1+f) 里);环境按现金覆盖成本约束预留。
设 W 为期初净值、R 为环境单笔收益比,单笔循环后:

```text
环境终值     W * R
回测器终值   W * (1 + q2*(1-f)/q1 - (1+f))
差(闭式)    W * f * (1 - R)
```

锯齿买 110 卖 100(f=0.001):差 = 100*0.001*(1-0.9072745) = 0.0092725,
实测差 0.0092725,残差 -9.2e-08(amount/price 精度截断)。
f=0 时差恒为 0(实测 -9.1e-08,同源)。相对量级每笔 ~f*(1-R),f=0.001 时
不超过 1e-4 相对,不影响研究结论。

## 终端清算手算(s6:episode 结束仍持多头)

锯齿 [0]*23+[1]*6:step23(决策行 23)目标 1 -> 买在 open[24](次日 00:00,
值 zigzag[24%6]=120?按序列值 130);保持到决策行 28(最后决策步),
terminated -> 在 open[29](最终执行 bar)按卖出滑点+费用强制清仓,
最终净值 = 现金(无未入账未实现盈亏),cum log reward = log(终值/100)。
test_s6_terminal_liquidation 断言买入时点 2026-06-02T00:00:00Z 与清算后 btc=0。

## 累计奖励与净值一致性

每个 episode:cum_reward_raw = Σ log(E_{t+1}/E_t) = log(E_final/E_0)( telescoping,
仅浮点误差)。24 个(序列×脚本)组合全部断言 |cum - log(E/E0)| < 1e-12
(test_all_sequences_and_scripts)。
