# 策略收益计数勘误：192 → 160

日期：2026-09-10。本文件为报告层勘误，不修改任何旧评估 JSON 原件。

## 错误

上一轮 Agent 最终报告把评估表中的 `pair` 列计入收益策略，得到 192 个"策略收益值"。

## 正确口径

评估策略白名单只有五类：`always_flat`、`always_long`、`c3_cost_ignorant`、`reference`、`oracle`。
`pair` 是样本坐标编号，`*_trades`（交易次数）是元数据，均不是收益类别，不得计入正/负/零收益计数。
32 个 episode × 5 类策略 = **160 个策略收益值**。

## 本轮独立重算结果

来源：本轮只读校准桥在用户 WSL 对旧批次 `c3reserve_v1_20260910T050655_93442` 的真实重算输出
`handoff_run/monitored_run/c3_calibration_bridge/analysis.json`
（sha256：`bbd99ef25054a30e3d46aa049f7a887fe305db2e1600b56819ebe20efbfd29eb`）：

- `n_policy_returns = 160`，`n_episodes = 32`
- 排除元数据：`pair`、`*_trades`（analysis.json `return_counts.excluded_metadata` 原文）
- 逐策略各 n=32：
  - always_flat：负 0 / 正 0 / 零 32
  - always_long：负 32 / 正 0 / 零 0
  - c3_cost_ignorant：负 17 / 正 15 / 零 0
  - reference：负 15 / 正 17 / 零 0
  - oracle：负 0 / 正 16 / 零 16
- 合计：负 64 / 正 48 / 零 48（总数 160）

旧报告的"64 个负收益"计数与本轮重算一致；本轮重算基于固定白名单与旧批次原件，可作独立口径引用。
