# 策略能力矩阵(工作包 A)

阶段 2.6.0 的单一 ActContext 使普通候选可读 df/n_rows/hidden/
future_returns;阶段 2.6.0a 拆为四类互不继承的接口。

| 接口 | act 签名 | 可见信息 | 读取 hidden | 用途 |
|---|---|---|---|---|
| CandidatePolicy | `(observation: 'np.ndarray') -> 'int'` | 仅 observation(含仓位槽位) | 否 | 正式候选(SB3 等) |
| ObservableBaselinePolicy | `(observation: 'np.ndarray') -> 'int'` | observation + schema 名称->槽位映射(无 df) | 否 | 可信规则基线 |
| OraclePolicy | `(ctx: 'OracleActContext') -> 'int'` | OracleActContext:当前行隐藏状态 + 当前仓位(无未来/无 df) | 是(仅当前行) | 课程可解性上限 |
| TestOnlyProbePolicy | `act(observation, harness_ctx)` | 测试 harness ctx(df/hidden/future_returns,仅测试路径构造) | 是(仅测试 harness) | 反作弊审计探针 |

- 正式评估入口 assert_formal_candidate 对 TestOnlyProbePolicy、
  OraclePolicy 与非策略对象一律拒绝(FormalPolicyRejected)。
- 正式 hidden exam 默认以子进程运行候选(candidate_worker:
  JSON-lines 只传 observation 数组;环境清洗;错误脱敏)。
- 基线规则(如 rule_trend)从 observation 槽位读取 ma_ratio/ret_4,
  不再读取 ctx.df。

## 具体策略归属

| 策略 | 接口 | reads_hidden | is_test_only_harness |
|---|---|---|---|
| AlwaysFlatPolicy | ObservableBaselinePolicy | False | False |
| AlwaysLongPolicy | ObservableBaselinePolicy | False | False |
| RandomPolicy | ObservableBaselinePolicy | False | False |
| PeriodicTogglePolicy | ObservableBaselinePolicy | False | False |
| OneStepGreedyPolicy | ObservableBaselinePolicy | False | False |
| HighTurnoverPolicy | ObservableBaselinePolicy | False | False |
| RuleTrendPolicy | ObservableBaselinePolicy | False | False |
| OracleSegmentedDriftPolicy | OraclePolicy | True | False |
| OracleSmoothLatentDriftPolicy | OraclePolicy | True | False |
| SB3CheckpointPolicy | CandidatePolicy | False | False |
| StepCounterCheaterProbe | TestOnlyProbePolicy | False | True |
| AbsolutePriceCheaterProbe | TestOnlyProbePolicy | False | True |
| PeriodicCheaterProbe | TestOnlyProbePolicy | False | True |
| FutureLeakProbe | TestOnlyProbePolicy | False | True |
| NullOvertraderProbe | TestOnlyProbePolicy | False | True |