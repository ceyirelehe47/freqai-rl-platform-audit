# 阶段 2.6.0 报告:Route C 课程资格审查、泛化审计与反作弊基础设施

- 日期:2026-08-25/26(UTC)
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / Python 3.11.16
- 上游:Freqtrade 2026.7,commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,工作树 clean(零修改)
- 判定:**PASS**
- 测试:438 项全部通过(2.5 38 / 2.5.1 74 / 2.5.2 78 / 2.5.2a 81 / 2.6.0 167);2.5.2a PPO 回归烟雾通过
- 本阶段未训练任何正式课程模型;极短测试级 PPO(128 步)仅用于确认评估器能读取 SB3 模型
- 是否允许进入阶段 2.6.1:**允许**

---

## 1. 执行摘要

在任何人工课程正式训练之前,本阶段建立了完整的课程资格审查、泛化
审计与反作弊基础设施:冻结 RouteCEnvCore-v1.0.0(含两项冻结前修复:
终端观察仓位归零、缺失预测目录致命化)、以真实时间表达课程参数的
时间尺度系统(5m/15m/1h 折扣等价,最大误差 2.3e-14)、可哈希的课程
章程预注册工具、可插拔生成器协议(隐藏状态严格隔离 + 自动审计)、
三类审计探针生成器(分段漂移/平滑潜在趋势/Null Control)、统一
确定性评估器(重复运行与输入顺序无关)、泛化等级 G0-G5 判级、12 项
成对反事实考试、隐藏考试隔离(mock-hidden pack + 脱敏输出 + 退休
机制)、checkpoint 版本兼容守卫与 G5 Warm/Cold 迁移协议空白演示。
五类故意作弊策略(步数/绝对价格/周期/未来泄漏/Null 高频)全部被
正确识别;探针课程基线排序 Oracle(+5.9%) > 规则(+2.2%) >
trivial(<=0),Null Control 切断全部可预测优势,课程资格 QUALIFIED。

## 2. PASS / FAIL

**PASS**(30 项 PASS 条件逐项见第 26 节;13 项 FAIL 条件零命中)。

## 3. RouteCEnvCore-v1.0 冻结(工作包 0)

冻结版本(RouteCEnvCore-v1.0.0 / ObservationSpec-v1 /
BinaryLongFlatAction-v1 / NetLogEquityReward-v1 /
MarketOpenCausalExecution-v1 / TerminalLiquidation-v1)定义于
`src/rl_platform/versions.py`,并:

- 注入实验 config(`rc.update(spec_versions())`)→ 进入 config_hash
  → 进入指纹与 identifier(任何版本变化必然改变指纹);
- 写入 execution_contract 与实验 manifest(`spec_versions` 段);
- 写入 checkpoint sidecar manifest 并在加载时逐项校验
  (`assert_versions_compatible`),不兼容即 `CheckpointCompatibilityError`,
  绝不勉强恢复;
- 环境类暴露 `env_core_version` 等类属性供运行时校验。

冻结规则:此后任何课程/生成器/考试失败默认不得通过修改 env.py /
ledger.py / market_execution.py / reward 补救。

## 4. 两项冻结前修复

1. **终端观察仓位**:`env.py` terminated 时清算后账本 btc=0,观察
   仓位字段同步置 0(不得显示已不存在的多头仓位);info 分别保留
   `requested_target_position`(模型最后请求)、
   `actual_position_after_liquidation`(恒 0)、
   `terminal_liquidation`(完整清算诊断)。验证:
   obs[-1]==0、ledger.btc==0、get_observation 一致、telescoping
   保持 5.6e-16(`environment_freeze_manifest.json` 的
   pre_freeze_fix_1 pass=true;test_terminal_observation_position)。
2. **缺失预测目录致命化**:`run_experiment.py` 中 freqtrade 退出码 0
   但 backtesting_predictions 不存在 → manifest 标记 invalid +
   self_check=INCONSISTED + 记录原始 FileNotFoundError + 模型目录
   保留(models_dir_kept=true)+ 退出码 4(CACHE_PIPELINE_EXIT_CODE);
   不再写成 SKIPPED 后继续成功;freqtrade 非 0 退出码仍如实透传
   (test_missing_prediction_dir_is_fatal,monkeypatch 全链路)。

## 5. 时间尺度系统(工作包 A)

`src/rl_curriculum/timebase.py`:

- timeframe(5m/15m/1h)→ 分钟/秒;真实时长 ↔ bars(非整数默认
  ceil,规则显式入 manifest;支持 floor/raise);
- 6h/24h/7d 在三档 timeframe 的换算无 off-by-one
  (24h@15m=96,7d@15m=672,7d@5m=2016);
- gamma = exp(log(0.5) × step_duration / reward_half_life):以真实
  时间半衰期定义折扣,5m/15m/1h 下相同真实时间点的累计折扣一致,
  12 组(半衰期×时点)×3 timeframe 最大误差 2.28e-14
  (`timebase_equivalence.json`);
- 本阶段只冻结"以真实时间定义 gamma"的机制,不冻结最终数值。

## 6. 课程章程(工作包 B)

`charter.py`:22 个必填字段(名称版本/教授与不教授能力/可见信息/
隐藏状态/训练族/开发小测族/隐藏族接口/训练与外推参数范围/Null
构造/Oracle/规则基线/trivial/12 项反作弊考试/行为指标/挂科与无效
条件/迁移目标/环境版本)校验 + sort_keys 规范化 JSON + SHA-256
哈希;修改任何内容(参数/考试/指标/门槛)必然改变哈希
(test_course_charter_hash);评估器/checkpoint 守卫拒绝章程哈希
不匹配。审计探针课程示例章程(`probe_charter.py`,charter_hash
见 `course_charter_example.json`)声明训练参数
drift 18-30bps / vol 20-32bps / regime 12-40 bars(15m 下即
3-6.7 小时段长),外推 drift 30-45bps / vol 32-50bps。本阶段未
创建正式趋势课程章程。

## 7. 生成器协议(工作包 C)

`generator_api.py`:BaseMarketGenerator 输出合法因果时间连续
OHLCV(open[t]==close[t-1])+ 尺度不变可观察特征 + 隔离隐藏状态 +
族名/版本/参数/种子/元信息 + Null 声明;wick/volume 噪声与收益
过程 RNG 分离派生(共同前缀拼接的基础)。自动审计:观察字段枚举、
禁止命名模式(regime/future/latent/steps_to/...)、隐藏列交集、
OHLC 合法性、NaN/inf、hidden 行数一致性、同 seed 完全确定、
不同 seed 产生不同 Episode、版本变化改变指纹
(`generator_determinism.json` / `hidden_state_observation_audit.json`
全 pass)。

## 8. 审计探针生成器(工作包 D)

- **探针 A probe_segmented_drift(probe-A-v1)**:随机横盘/正/负
  漂移分段,高斯噪声,regime 长度与顺序随机,支持显式 regimes 供
  顺序随机化反事实;隐藏状态 = regime_direction / strength /
  bars_to_regime_end / regime_index;
- **探针 B probe_smooth_latent_drift(probe-B-v1)**:OU 潜在漂移,
  无分段边界,趋势强度连续变化,独立代码路径;隐藏 = latent_drift_bps;
- **探针 C probe_null_control(probe-C-v1)**:与 A 同参数轨迹的
  收益相位随机化重排(边际分布精确保留),隐藏 regime 标签保留但
  与重排后收益独立(Oracle 无优势的可验证构造);
- 统一可观察特征(尺度不变):ret_1/ret_4/ret_12/vol_24/ma_ratio。
- 模拟隐藏探针(考试包中的 B 族)只用于测试隐藏考试基础设施,
  不具备正式考试资格;正式隐藏生成器将在课程冻结后由独立评估
  Agent 在另一工作区创建。

## 9. 基线策略(工作包 E)

`policies.py` 统一 act(obs, ctx) 接口:SB3 checkpoint(加载即版本
+ 章程守卫)、Oracle(A/B 各一,读隐藏,仅可解性上限,永不做训练
输入)、可观察规则策略(ma_ratio>0.001 且 ret_4>0,只用模型可见
信息)、Always Flat/Long、Random、Periodic Toggle、One-Step
Greedy、High-Turnover,以及五类故意作弊策略(见第 18 节)。

## 10. 课程资格关系(工作包 M)

探针 A(12 seeds):Oracle +5.94% > 规则 +2.22% > One-Step
Greedy -0.006% > Periodic -5.18% > Always Long -8.48%(q10 深亏)
≈ Random -8.51% > High-Turnover -13.38%;探针 B(8 seeds):
Oracle +2.17% > 规则 +0.85% > Always Long -1.31% > Random -2.93%。
四项资格条件(oracle_gt_rule / rule_gt_trivial /
always_long_not_passing_everywhere / always_flat_not_top)全部成立,
课程状态 **QUALIFIED**(`baseline_ordering.json`)。Always Long
中位 -8.5% 且 q10 深亏 → 不能通过所有考试;Always Flat 收益 0
恒低于 Oracle;Periodic Toggle 无法及格。

## 11. 评估器(工作包 F + N)

`evaluator.py`:确定性 Episode 评估(Episode 按 canonical spec
排序、RNG 种子派生固定、bootstrap 种子 20260826、结果与文件遍历
顺序和进程调度无关;`evaluator_determinism.json`:repeat_identical
= input_order_independent = true;评估代码哈希 e-370c6064...)。
输出:初末净值/扣费收益/最大回撤/换手/交易数/费用/平均仓位/持仓
时长/行为指纹(动作 SHA-256)/相对 Always Flat 与规则基线的逐
episode 配对差 + paired bootstrap 95% 区间/相对 Oracle 的 regret/
分 family / 分参数区间 / q10 / 最差 / seed 通过比例。统计纪律:
中位数、均值、10% 分位、最差 Episode、种子通过比例、family 与
参数区间分组、paired bootstrap(不只报最佳 seed/总平均)。
每次评估保存:checkpoint SHA-256(sidecar)、章程哈希、考试包
哈希、环境版本、评估器代码哈希、依赖版本、起止时间、退出状态。

## 12. 泛化等级 G0-G5(工作包 G)

`grades.py`:G0 只训练 Episode → G1 未见种子(不得单独称真正
泛化)→ G2 参数外推 → G3 未见生成器族 → G4 反事实/Null/反作弊
全过(课程毕业最低要求)→ G5 Warm/Cold 迁移(可迁移模型最低
要求,协议见 transfer.py)。合成用例 G0-G4 分类全对
(`generalization_grade_probe.json` classification_correct=true);
规则策略在真实四 split 评估 + 反事实全过后判 **G4**。具体及格线
留待 2.6.2 以 Oracle/规则/trivial 校准后冻结。

## 13. 共同前缀考试(工作包 H.1)

`test_common_prefix_future_suffix`:前 cut 行逐位保留 base
(直接拼接 + 几何缩放后缀,无浮点重建漂移),断言共同前缀 OHLC+
特征逐位一致;Oracle/规则动作一致率 1.0;FutureLeakProbe 在多
切割点(0.3/0.5/0.7)下首个分歧 step = cut-1(未来后缀改变了
过去决策)→ 判未来泄漏(`common_prefix_invariance.json`)。

## 14. 参数外推(工作包 M)

drift 30-45bps / vol 32-50bps(超出训练 18-30 / 20-32)下规则
策略中位 +9.79%(训练范围 +2.22%),G2 通过
(`parameter_extrapolation_probe.json`)。

## 15. 生成器族外推(工作包 M)

A 训练机制 → B 模拟隐藏机制(OU,独立代码路径,无共享隐藏列):
规则策略中位 +0.85%,G3 通过(`generator_family_holdout_probe.json`)。

## 16. 反事实考试(工作包 H.2-H.11)

12 项成对变换全部实现并有区分力:

- 价格尺度(×0.1/×10/×100)与初始价格(50/500):Oracle/规则
  动作一致率 1.0;AbsolutePriceCheater 崩溃;
- Episode 长度(共享前缀 57/144 bars):Oracle/规则一致;
  StepCounterCheater 首个分歧暴露;
- 时间平移(+37h):一致(课程无日历特征);
- Regime 顺序随机化(保持段集合):读市场的策略动作变化;
  StepCounter/Periodic 动作序列完全不变(不读市场);
- 无关特征注入(3 噪声列)/置乱(vol_24):行为与成绩不变;
- 真信号消融(置乱 ma_ratio+ret_4,5 episodes):中位优势下降
  (+2.2% → -0.6% 量级);对不读信号的策略正确标记"未下降";
- 趋势镜像(log 域取反 + 隐藏方向标签同步反转):方向捕获
  (capture=sum(action×next_return))在原始与镜像市场均为正;
- 成本单调性(fee×1/2/4):净值非增、换手不升。

## 17. Null Control(工作包 H.12)

相位随机化重排构造(边际分布精确保留、隐藏标签保留但独立):
Always Flat 超额 0;规则超额中位 -1.21%(正超额比例 0.125);
Oracle 超额中位 -0.049%(正超额比例 0.375,bootstrap CI 含 0,
对比 A 上 +5.94% 的预测优势消失);NullOvertrader 超额 -10.1%、
换手 0.989(高换手+扣费亏损+挂科)。无任何稳定异常正收益
(`null_control_report.json`)。

## 18. 故意作弊策略检测(工作包 I)

`cheater_detection_matrix.json`:**5/5 全部被识别**——

| 作弊策略 | 识别证据 | 结论 |
|---|---|---|
| StepCounterCheater | Episode 长度不变性失败(首分歧 step)+ regime 重排动作不变 | SUSPECTED_CHEATING(episode_position) |
| AbsolutePriceCheater | 价格尺度/初始价格不变性失败(动作一致率崩塌) | SUSPECTED_CHEATING(absolute_price) |
| PeriodicCheater | regime 重排动作不变 + 动作周期检测(period=12) | SUSPECTED_CHEATING(periodic_pattern) |
| FutureLeakProbe | 观察字段审计(future_* 禁入)+ 多切割点共同前缀分歧 + Null 稳定正超额 | SUSPECTED_CHEATING(future_leak) |
| NullOvertrader | Null 高换手(0.989)+ 扣费亏损(-10.1%)+ Null 挂科 | 普通挂科(非作弊高分) |

该错误 observation 环境仅存在于测试构造(FutureLeakProbePolicy +
ctx.future_returns),绝不在正式训练代码路径。

## 19. 隐藏考试隔离(工作包 K)

公开开发考试(生成器与种子可见,详细 trace)与 mock-hidden
pack(`mock_hidden_pack.json`,12 episodes,四 split,pack_hash
p-29ca2216...,明确声明"只用于测试隐藏考试基础设施,不具备正式
考试资格")。隐藏评估 CLI(`rl_curriculum.hidden_exam_cli`):
默认只输出聚合成绩与状态(逐 Episode trace/种子/参数全部脱敏,
`hidden_exam_redaction_report.json` pass);记录 pack hash/章程
哈希/环境版本/评估器代码哈希/依赖/时间/退出码。正式隐藏包将由
独立评估 Agent 在课程冻结后于另一工作区创建,存放于项目目录之外,
公开仓库只记录哈希/协议版本/是否退休;本阶段未创建任何正式隐藏
考试种子,公开仓库无隐藏种子。

## 20. 考试包退休(工作包 K)

--detailed 写出详细结果 → 立即写入退休注册表(reason 记录公开
路径)→ 再次评估/materialize 被拒绝(ExamPackError"已退休"/CLI
返回 EXAM_INVALID 退出码 5);仅聚合输出不触发退休
(`exam_retirement_test.json` 三断言全过)。

## 21. Warm/Cold 迁移协议(工作包 L)

`transfer.py`:TransferProtocolSpec 冻结必须完全相同的要素
(目标课程章程哈希/考试包哈希/种子/训练预算/容量/PPO 参数/评估
次数);Warm−Cold 逐 seed 配对 bootstrap 结论 POSITIVE /
NEUTRAL / NEGATIVE_TRANSFER;NEGATIVE 时不得强行微调保留预训练,
允许放弃旧 checkpoint、保留 Cold Start 路线并记录污染来源。空白
演示(占位策略,恒等分数)输出 NEUTRAL_TRANSFER、demo_only=true
(`transfer_protocol_demo.json`),证明协议可执行、结论可机读;
未运行正式迁移训练。

## 22. 统计与成绩单(工作包 N)

全部 artifacts 按任务书清单落盘(见第 28 节索引),无空文件;
报告含中位数/均值/q10/最差/种子通过比例/family 分组/参数区间
分组/paired bootstrap 95% 区间/动作一致率/首处分歧步/仓位差/
净值差/作弊触发状态。checkpoint 兼容守卫
(`checkpoint_compatibility_guard.json` pass):匹配版本+章程可
加载、版本篡改拒绝、章程不匹配拒绝、二进制替换(SHA-256 不一致)
拒绝、旧 2.5.2a smoke checkpoint 副本标记 legacy 工程证据
(formal_eligible=false,仅接口验证)。

## 23. 原测试回归

438 项全部通过(2.5 38 / 2.5.1 74 / 2.5.2 78 / 2.5.2a 81 /
2.6.0 167);未修改、删除、skip、xfail 任何现有测试;
`regression_test_summary.md` 全文记录。

## 24. 新测试结果

22 个测试文件 167 项全部通过(清单见 regression_test_summary.md);
fail-closed 清单(checkpoint 版本/章程哈希/考试包哈希/内容缺失/
已退休/observation 维度/NaN/非法 OHLC/reward-净值一致性等)
全部有断言覆盖。

## 25. 已知限制

1. 探针课程是审计探针而非正式课程;正式趋势课程章程及及格线
   留待 2.6.1/2.6.2;
2. Null Control 的"标签保留"构造依赖相位随机化切断可预测性,
   bootstrap CI 含 0 是统计意义上的"无稳定优势",非信息论证明;
3. mock-hidden pack 内容在公开仓库(标记 mock),仅用于验证隔离
   机制;正式隐藏考试的真正保密性依赖未来独立评估 Agent 的工作
   区隔离,本阶段只能验证接口不泄漏内容;
4. 反作弊阈值(动作一致率 0.999、Null 正超额比例 0.75 等)是
   工程判定线,将在 2.6.2 与及格线一起校准冻结;
5. SB3 接口烟雾的测试级 PPO 仅 128 步,无任何学习意义;
6. G5 仅协议 + 空白演示,未运行正式迁移训练(阶段范围外)。

## 26. 是否允许进入阶段 2.6.1 / PASS 条件对表

30 项 PASS 条件:1 冻结✓ 2 终端观察=0✓ 3 缺目录失败✓ 4 版本入
checkpoint 与 manifest✓ 5 不兼容拒绝✓ 6 真实时间表达✓ 7 gamma
三档一致✓ 8 章程规范化哈希✓ 9 隐藏不入观察✓ 10 共同前缀因果✓
11 探针可重复合法✓ 12 基线排序合理✓ 13 Null 消除优势✓ 14 评估
器确定✓ 15 G0-G4 分类正确✓ 16-20 五类作弊全发现✓ 21 尺度/长度/
初始价有效✓ 22 消融优势下降✓ 23 隐藏接口不泄漏✓ 24 mock pack
稳定哈希✓ 25 退休机制✓ 26 checkpoint 无需隐藏内容即可提交✓
27 G5 协议空白演示✓ 28 全部回归通过✓ 29 上游 clean✓ 30 未开始
正式课程训练✓。13 项 FAIL 条件零命中。**允许进入阶段 2.6.1**。

## 27. 完整复现命令

```bash
# WSL: CryptoRL-Ubuntu-24.04
source ~/projects/crypto_rl/activate-freqtrade.sh
cd ~/projects/crypto_rl

# 全量回归(438 项)
python -m pytest tests/freqai_rl_stage2_5/ tests/freqai_rl_stage2_5_1/ \
  tests/freqai_rl_stage2_5_2/ tests/freqai_rl_stage2_5_2a/ \
  tests/route_c_stage2_6_0/ -q

# 2.5.2a PPO 回归烟雾
python tests/freqai_rl_stage2_5_2a/ppo_smoke.py

# 阶段 2.6.0 全部 artifacts
python experiments/route_c_stage2_6_0/run_audit.py

# 隐藏考试 CLI(mock pack,聚合输出)
python -m rl_curriculum.hidden_exam_cli \
  --pack artifacts/route_c_stage2_6_0/mock_hidden_pack.json \
  --policy rule_trend --out /tmp/agg.json \
  --retire-registry artifacts/route_c_stage2_6_0/retired_packs.json

# 上游完整性
git -C vendor/freqtrade describe --tags --exact-match   # 2026.7
git -C vendor/freqtrade rev-parse HEAD                  # 52bc96f...
git -C vendor/freqtrade status --short                  # 空
```

## 28. 证据索引

`artifacts/route_c_stage2_6_0/`(任务书清单 23 个关键证据全部
存在,另含演示输出与测试级 checkpoint;无空文件):

| 文件 | 内容 |
|---|---|
| environment_freeze_manifest.json | 冻结版本 + 修复1证据 + 修复2索引 |
| course_charter_example.json | 示例章程 + 规范化 + 哈希 |
| timebase_equivalence.json | 12×3 等价行,最大误差 2.28e-14 |
| generator_determinism.json | A/B/C 确定性 + 版本敏感性 |
| hidden_state_observation_audit.json | 隔离审计(字段枚举/禁配/交集) |
| baseline_ordering.json | A/B 基线排序 + QUALIFIED |
| common_prefix_invariance.json | 共同前缀矩阵 |
| price_scale_invariance.json | 尺度 + 初始价格 |
| episode_length_invariance.json | 长度 + 时间平移 + regime 重排 |
| parameter_extrapolation_probe.json | G2(30-45bps 外推) |
| generator_family_holdout_probe.json | G3(A→B 族) |
| null_control_report.json | Null 四策略矩阵 |
| signal_ablation_report.json | 消融/注入/置乱/镜像/成本 |
| cheater_detection_matrix.json | 5 作弊策略 × 考试矩阵 |
| evaluator_determinism.json | 重复一致 + 顺序无关 + 代码哈希 |
| mock_hidden_exam_manifest.json | mock pack 哈希/声明 |
| hidden_exam_redaction_report.json | 脱敏验证 |
| exam_retirement_test.json | 退休/复用拒绝 |
| checkpoint_compatibility_guard.json | 版本/章程/替换守卫 + legacy |
| generalization_grade_probe.json | G0-G4 合成+真实判级 |
| transfer_protocol_demo.json | G5 协议空白演示 |
| regression_test_summary.md | 438 项回归 + fail-closed 清单 |
| upstream_integrity.txt | tag/commit/clean |

公开仓库:https://github.com/ceyirelehe47/freqai-rl-platform-audit 的
`stage2_6_0/`(不覆盖 stage2_5 / stage2_5_1 / stage2_5_2 / stage2_5_2a;
不含模型二进制、真实行情、SQLite、API Key、隐藏种子)。
