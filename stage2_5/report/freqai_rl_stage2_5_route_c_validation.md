# FreqAI 编排层与自定义对齐环境可行性验证报告(阶段 2.5 / 路线 C)

- 生成时间:2026-08-25 UTC
- 审计对象:Freqtrade tag `2026.7`,commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(vendor 零修改)
- 执行环境:WSL `CryptoRL-Ubuntu-24.04`(Ubuntu 24.04),conda `freqtrade-rl`(Python 3.11.16)
- 上一阶段报告:`reports/freqai_rl_phase1_2_audit.md`(公开仓库 ceyirelehe47/freqai-rl-platform-audit)
- 数据:BTC/USDT spot 1h,Binance US,评估区间 [2026-06-01 00:00, 2026-07-01 00:00) UTC

---

## 1. 执行摘要

阶段 2.5 回答一个架构问题:能否在不修改 Freqtrade 核心、不维护 fork 的前提下,
保留 FreqAI 的特征流水线、滑动训练窗口、模型保存加载与回测编排,同时使用
自己的对齐 Gymnasium 环境、净值账本、净值奖励和顺序状态推理。

**结论:可行。路线 C 判定为 CONDITIONAL PASS**——二十五节列出的 17 项通过
条件全部成立(证据见各节),另存在若干不阻塞下一阶段的非核心限制(§21)。

最重要的三条证据:

1. **时间对齐(§18)**:同一锯齿数据、同一目标仓位变化下,自定义环境与真实
   `Backtesting.start()` 的 entry/exit 时间与价格完全一致(均"信息截至 t →
   open[t+1] 成交",差 < 1e-9);上一阶段"训练 gap=2 vs 回测 gap=1"的
   系统性错位在路线 C 下消除。
2. **重载确定性(§14)**:删除预测缓存保留模型重跑,两轮回测成交逐字段一致;
   独立进程加载保存的 5 个模型+特征管线重推理 720 行,与 FreqAI 生成的
   目标仓位序列逐行零差异。
3. **奖励=净值(§9)**:24 组人工序列实验中,episode 累计未缩放 log reward
   与 log(最终净值/初始净值)之差全部 < 1e-12(纯浮点)。

## 2. 路线 C 判定:CONDITIONAL PASS

十七项通过条件逐条核对(编号对应任务书二十五节):

| # | 条件 | 结果 | 证据 |
|---|---|---|---|
| 1 | 无 Freqtrade 核心修改 | ✓ | upstream_integrity.txt(开始/结束 status 均空) |
| 2 | 自定义环境能通过 FreqAI 创建和训练 | ✓ | §19,5 窗 PPO 各 482 timesteps |
| 3 | 观察截至 K 线 t | ✓ | §6,观察窗含当前行 t |
| 4 | 动作在 open[t+1] 执行 | ✓ | §6/§17,execution_time = decision_time + 1h 全部断言 |
| 5 | 训练与回测不再错一根 K 线 | ✓ | §18,两侧成交同根同价 |
| 6 | 净值账本通过手算测试 | ✓ | §7,17 项账本断言 |
| 7 | 奖励严格来自扣费净值变化 | ✓ | §9,telescoping 一致性 < 1e-12 |
| 8 | Episode 未平仓正确清算 | ✓ | §10,终端强制清算,终值=现金 |
| 9 | 无非法动作 | ✓ | §11,Discrete(2) 幂等目标仓位 |
| 10 | 训练与推理观察形状一致 | ✓ | §12/§14,重推理 720 行零差异 |
| 11 | 顺序推理窗口内正确 | ✓ | §12,6 项推理测试 |
| 12 | 跨 FreqAI 子窗口保持状态 | ✓ | §13,窗 1-4 末仓位 1 → 窗 5 从多头继续 |
| 13 | 模型重载后动作可复现 | ✓ | §14,trades 一致 + 重推理一致 |
| 14 | Dry-run 状态初始化路径可行 | ✓ | §15,真实 Trade 表读取测试 5 项 |
| 15 | 实验指纹能隔离缓存 | ✓ | §16,seed 42/43 → 两个 identifier,零缓存命中 |
| 16 | PPO 最小链路能运行 | ✓ | §19,数据→环境→PPO→保存→加载→推理→回测 |
| 17 | 上游仓库保持干净 | ✓ | upstream_integrity.txt |

判定为 CONDITIONAL PASS 而非纯 PASS 的原因:存在二十六节所列非核心限制
(回测器复利终值与环境的 stake 语义差、回测侧滑点依赖 custom price 钩子且
被 clamp 到当根 high/low、Dry-run 订单拒绝后的重同步未实现等),每项均
不阻塞下一阶段(§21 逐项说明)。

## 3. 固定版本和 commit

| 项 | 值 | 证据 |
|---|---|---|
| Freqtrade tag | 2026.7 | git describe --tags --exact-match(任务开始与结束各一次) |
| commit | 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5 | 同上 |
| git status | 始终为空 | logs/freqai_rl_stage2_5/00_precheck.log + upstream_integrity.txt |
| Python | 3.11.16 @ miniforge3/envs/freqtrade-rl | pytest 会话头 |
| 运行时依赖 | 未新增、未升级(仅使用既有 gymnasium/SB3/torch) | pip 环境未变更 |

## 4. 自定义环境架构

代码布局与职责边界见 `artifacts/freqai_rl_stage2_5/architecture_summary.md`。
核心包 `src/rl_platform`(约 700 行):账本(ledger)、对齐环境(env)、
顺序推理(inference)、信号转换(signal_convert)、指纹(fingerprint)、
Dry-run 状态(dryrun_state)。FreqAI 适配层 `RouteCModel`(约 160 行)与
策略 `RouteCStrategy`(约 90 行)保持薄:只覆盖官方声明的扩展点,
不复制 FreqAI 内部源码;特征过滤、缩放、OHLC 提取、窗口切分、缓存判定、
模型持久化全部复用 FreqAI 官方实现。

## 5. 被覆盖的 FreqAI 扩展点

只覆盖三个方法(均为官方文档/源码注释明示的用户扩展点):

1. **set_train_and_eval_environments()**:默认构造 Base5ActionRLEnv(其
   step() 的 open[t+2] 执行语义与官方记账/奖励不符合本任务),替换为
   `AlignedLongFlatEnv`。不依赖未公开接口;prices_train/test 与
   train/test_features 的行对齐由官方 train() 的内部顺序保证
   (BaseReinforcementLearningModel.py:118-145)。
2. **fit()**:默认 ReinforcementLearner.fit 挂 MaskableEvalCallback(本环境
   无动作掩码)且 PPO device=auto 会选 GPU;改为最小 PPO:device="cpu"
   (route_c 配置)、set_random_seed(seed)、PPO(seed=seed)。
   total_timesteps = train_cycles × len(train_features) 与官方公式一致。
3. **rl_model_predict()**:默认 rolling(CONV_WIDTH).apply() 逐行独立预测,
   无法传递当前目标仓位;替换为 `SequentialPositionPredictor`。依赖
   dk.label_list 与 dataframe.index(公开),以及 freqai_interface.
   start_backtesting 在同一模型实例上按时间顺序调用 train/predict
   (源码 301-405 行的窗口循环,【源码确认】)。

不覆盖:train()/predict()/build_ohlc_price_dataframes/save_data。
上游升级维护风险评估见 §22。

## 6. 时间语义

冻结的因果时间线(与 Freqtrade 回测"信息截至 t → open[t+1] 成交"一致):

```text
K 线 t 已收盘
→ 观察含行 t 的特征窗口 [t-w+1, t] + 当前目标仓位(末维)
→ 输出目标仓位 action ∈ {0,1}
→ 在 open[t+1] 执行(含确定性滑点与手续费)
→ 新仓位承担 open[t+1] → close[t+1]
→ 期末净值 E[t+1],奖励 log(E[t+1]/E[t])
```

- 环境:决策 t ∈ [window_size-1, N-2];执行 bar ∈ [window_size, N-1];
  **最后一根 bar 从不进入观察**(纯执行/清算 bar)。
- 推理:`SequentialPositionPredictor.build_observation` 与
  `AlignedLongFlatEnv._observation` 为同一构造(特征窗口 ravel + 末维仓位),
  训练与历史推理观察形状严格一致。
- 策略层零额外 shift:信号写在行 t,Freqtrade 引擎自身 shift(1) 在
  open[t+1] 成交(backtesting.py:551-568,上一阶段已源码确认)。
- 未使用任何特征 shift 或奖励偏移来"凑对齐"——对齐由环境 step 顺序、
  顺序推理与信号转换三处共同实现(include_shifted_candles=0)。

## 7. 单步净值账本

`LongFlatLedger` 显式维护现金、BTC 数量、当前目标仓位、成交价、成交名义、
手续费、滑点成本、已实现盈亏、未实现盈亏、总净值;每步 info 可导出全部
字段(决策/执行时间、动作、前后目标、成交方向、原始 open、滑点后成交价、
费用、数量、期初/期末净值、原始/缩放奖励、terminated 等,见
synthetic_*_trace.csv 列)。

单步顺序(任务书第六节):记录 close[t] 期初净值 → 旧仓位承担
close[t]→open[t+1] 跳空(由持仓自然实现) → open[t+1] 执行目标变化 →
扣费/滑点 → 新仓位承担 open[t+1]→close[t+1] → close[t+1] 期末净值。

账本单元测试 17 项(test_ledger.py):全程空仓、买后价格不变/涨/跌、
完整开平(4 参数化)、重复目标多头/空仓、频繁切换、fee=0 与 0.001、
滑点 0/5/10bps、终端清算、reset 清空、非法动作报错——全部手算对照,
公式与数值见 `artifacts/.../ledger_hand_calculation.md`。

## 8. 手续费与滑点公式

费用口径与 Freqtrade 2026.7 现货回测器一致:

```text
买入:qty = cash / (p*(1+f));名义 = cash/(1+f);费用 = 名义*f
卖出:所得 = qty*q*(1-f);费用 = qty*q*f
单笔收益比 R = q*(1-f) / (p*(1+f))
```

等价于回测器 open_value = amount*rate*(1+fee)(backtesting.py:1269 Order.cost)、
close_value = amount*rate*(1-fee)(trade_model.calc_close_trade_value)、
profit_ratio = close/open - 1(trade_model.py:1202-1230)。
【源码确认+实验确认:单笔 profit_ratio 两公式实测差 ≤ 5e-9(回测侧 round 8)。】

复利终值存在可推导的 stake 语义差:Freqtrade 的 stake=amount*rate 不为买入
费预留现金,环境按现金覆盖成本约束预留。单笔循环后
**环境终值 − 回测终值 = W·f·(1−R)**(闭式推导见
env_vs_freqtrade_parity.md);f=0.001 时每笔相对量级 ≤ 1e-4,
锯齿实测差 0.0092725 vs 闭式 0.0092725,残差 −9.2e-08(精度截断)。
f=0 时差恒为 0(实测 −9.1e-08)。该差异不影响研究结论,但正式系统若要
逐 USDT 对账需选择一种口径并固定。

确定性滑点(基点):买入价 = open[t+1]×(1+s/1e4),卖出价 = open[t+1]×(1−s/1e4);
费用按滑点后名义金额计算;重复目标零成交零费用;费用与滑点分别累计、
无重复扣除(滑点单调性测试:0/5/10bps 三类序列终值严格递减,
slippage_monotonicity.csv/json)。

回测侧复现:通过 IStrategy 用户钩子 custom_entry_price / custom_exit_price
(backtesting.py:1041/892 调用点,limit 单生效)注入相同确定性滑点,
无需修改核心;注意回测器会把价格 clamp 到当根 high/low 内——锯齿测试
数据为此在 high/low 预留了滑点余量,这也是真实 K 线下的自然属性。

## 9. 奖励与净值一致性

奖励 r_t = log(E_{t+1}/E_t),E 为扣除手续费与滑点后的总净值;
reward_scale 固定常数写入配置(route_c.reward_scale=1.0),info 同时记录
原始值与缩放值。无开仓奖励、无空仓/胜率/利润目标/交易次数奖励、
无回撤/持仓时长/换手惩罚(换手已由费用+滑点内生惩罚)。

一致性证明:episode 内 telescoping
Σ log(E_{t+1}/E_t) = log(E_final/E_0)。
24 组(4 序列 × 6 目标脚本)实验全部断言 |cum − log(E/E0)| < 1e-12
(test_all_sequences_and_scripts)。【实验确认】

## 10. Episode 终端处理

采用"预留不进入观察的最终执行 bar":数据 N 根时决策最大到 N-2,
执行与清算发生在 open[N-1]。terminated 时若仍持多头,在 open[N-1]
按卖出滑点+手续费强制清仓(liquidate),最终净值 = 现金,
无未入账未实现盈亏。该口径与 Freqtrade 回测器 handle_left_open
用最后一根 bar 的 open 强平(backtesting.py:1294-1297
exit_row[OPEN_IDX],ExitType.FORCE_EXIT)同族同价。
【源码确认+实验确认:s6 终端清算测试,清算后 btc=0、终值=现金】

不使用最终 close 清算,因此无需任务书第九节的 close 口径豁免声明。

## 11. 目标仓位动作

Discrete(2):0=目标空仓,1=目标多头。幂等:重复输出同一目标不产生交易、
不产生费用(账本与序列实验双重断言);不存在非法动作(空仓 Sell 类
无效动作问题在目标仓位语义下消失);无需奖励惩罚教状态机。
当前目标仓位以固定 0.0/1.0 编码进入观察末维——训练、历史推理、模型重载
使用同一编码;不使用官方 add_state_info(其回测不可用,上一阶段 §15)。
训练/推理/未来 Dry-run 中编码一致(Dry-run 初始仓位来自 Trade 表,§15)。

## 12. 顺序状态推理

`SequentialPositionPredictor`:初始化当前目标仓位 → 逐行"特征窗口+当前
仓位"构造观察 → model.predict → 记录动作并更新仓位 → 下一行。
前 window_size−1 行与 NaN 特征行(预热期)保持当前仓位,不调用模型。

确定性测试 6 项(test_sequential_inference.py):观察形状与仓位末维、
首跑/同进程重跑一致、跨窗口拼接 == 整段推理、FixedSequencePolicy
逐位一致、目标→信号转换(重复目标无重复信号)、NaN 守卫。
PPO 级复现见 §14。【实验确认】

## 13. FreqAI 子窗口状态连续性

机制:freqai_interface.start_backtesting 在**同一 FreqAI 模型实例**上按
时间顺序对每个窗口调用 train()/predict()(源码 301-405 行的有序 zip 循环,
self.model 实例跨窗口存活)。RouteCModel 以实例属性
`_last_target_position` 携带上一窗口末尾目标仓位,rl_model_predict 每窗
从该值开始顺序推理。模型可以在窗口间切换(每窗重训),持仓状态不重置。

实测(PPO 烟雾,720 行 5 窗):窗口 1-4 末目标仓位均为 1,窗口 5 从
多头状态继续,在 06-28 行转 0(成交 06-29 01:00 open,与回测 trades 的
close_date 一致),窗口 5 末为 0。
cross_window_state_trace.csv。【源码确认+实验确认】

脆弱点说明:该机制依赖"同一实例跨窗口"这一当前实现行为(而非契约),
上游若改为每窗重建模型实例则会失效——缓解与替代方案见 §22。

## 14. 模型保存和重载

三分支行为沿用 FreqAI 官方(缓存优先/模型重载/重训)。路线 C 的验证:

1. **run1**(训练+预测缓存生成):5 窗 PPO 训练,顺序推理生成
   &-target_position,回测 1 笔(06-01 01:00 买 @73903.14 →
   06-29 01:00 卖 @59671.06,exit_signal);
2. **run2**(删除 backtesting_predictions,保留 sub-train-*_model.zip):
   日志 0 次 "Starting training",5 窗全部
   "Could not find backtesting prediction file" 后走模型重载+顺序推理;
   **两轮回测成交逐字段一致**(trades_identical=True);
3. **独立重推理**(新进程):加载 5 个保存模型 zip + feature_pipeline.pkl,
   从原始 feather 重算 4 特征、按窗 transform、跨窗顺序推理 720 行,
   与 run2 重建的预测缓存序列**逐行零差异**(reinference_identical=True)。

reload_determinism.md/json。【实验确认】

## 15. Dry-run 状态初始化验证

`dryrun_state.resolve_initial_position(trades, pair)`:无 open trade → 0;
该 pair 的 open 多头 → 1;出现空头持仓 → 显式报错(配置漂移保护)。
生产入口 `get_initial_position_live(pair)` 调用
`Trade.get_trades_proxy(is_open=True)`——与官方
BaseReinforcementLearningModel.get_state_info 完全相同的公开接口,
不使用 add_state_info,不保存 API Key,不连接真实账户。

测试级验证(test_dryrun_init.py,5 项):在内存 sqlite + 真实 freqtrade
持久层中构造 Trade——无持仓→0、open 多头→1、已平仓不计入、
其他 pair 不计入、空头报错,全部通过。未启动长期 Dry-run。
未覆盖:订单被拒/部分成交/断线后的状态重同步(列为 §21 风险)。

## 16. 实验指纹和缓存隔离

`run_experiment.py` 在渲染 config 前计算指纹:freqtrade commit + 6 个自有
代码文件 SHA-256 + 奖励/费用/滑点配置 + 特征清单 + timerange + 裁剪后
数据 SHA-256 + seed + 模型类型 + 关键训练参数。identifier =
stage25-rc-<指纹前 10 位>;完整输入存 manifest(实验清单
experiment_manifest.json)。identifier 在 IFreqaiModel.__init__ 读取
config(freqai_interface.py:69),故注入点在 config 渲染阶段,
不修改 FreqAI 缓存校验代码。

验证:
- 函数级(test_fingerprint.py,3 项):相同输入 → 相同 identifier;
  分别只改 seed/slippage/fee/特征/数据哈希/训练参数/环境代码/timerange
  → identifier 必变;
- 集成级:seed 42 → stage25-rc-b6259bb8d5;seed 43 →
  stage25-rc-fd60a4fd52(新模型目录,5 窗全部
  "Could not find backtesting prediction file",零旧缓存命中)。
  cache_fingerprint_test.json。【实验确认】

## 17. 人工价格序列测试

四类序列(恒定/持续上涨/持续下跌/锯齿,open=high=low=close,volume=1,
30 根)× 六种目标序列(全程 0 / 全程 1 / 0→1→1→0 / 1→1→1 /
0→1→0→1→0 / 结束时仍 1),逐步输出 24 列 CSV
(synthetic_{constant,rising,falling,zigzag}_trace.csv + synthetic_summary.csv)。

验收断言全部通过:
- 信息截至 t,成交严格位于 open[t+1](execution_time = decision_time+1h,720 步全查);
- 无 t+2 错位;
- 重复目标零交易零费用;
- 终端多头正确清算(s6:2026-06-02T00:00Z 买入,terminated 后 btc=0,终值=现金);
- 累计 log reward 与净值比一致(<1e-12);
- 锯齿手算:决策行 1 观察 → 买 open[2]=90;决策行 3 → 卖 open[4]=80;
  单笔净值比 80×0.999/(90×1.001) 精确吻合——与上一阶段 RL 环境的
  成交价相同,但信息集从"行 0 却隔两根执行"修正为"行 1 下一根执行";
- fee=0/slip=0 恒定价格开平净值严格回到 100。【实验确认】

## 18. 环境与 Freqtrade 回测对比

同锯齿数据、同目标变化(决策行 0 转多 → 行 5 转空),环境侧逐步 step,
回测侧真实 `Backtesting.start()`(虚拟市场测试级 monkeypatch 注入,
stake_amount=unlimited + dry_run_wallet=100 全仓复利对齐环境语义,
虚拟市场精度 1e-8 排除截断干扰)。三种口径:

| 口径 | entry | exit | 单笔收益(env/bt) | 终值差(env−bt) |
|---|---|---|---|---|
| fee=0, slip=0 | 01:00 @110 | 06:00 @100 | −0.0909090909 / −0.0909090909 | −9.09e-08 |
| fee=0.001, slip=0 | 01:00 @110 | 06:00 @100 | −0.0927254564 / −0.0927254564 | +9.27e-03 |
| fee=0.001, slip=5bps | 01:00 @110.055 | 06:00 @99.95 | −0.0936322775 / −0.0936322775 | +9.36e-03 |

- entry/exit 时间与价格全部一致(相对 1e-9);交易数两侧一致;
- 单笔收益率一致(≤5e-9,回测 round 8);
- 零费终值差 < 1e-5(仅精度截断);
- 有费终值差与闭式 W·f·(1−R) 吻合(残差 <1e-7,§8);
- 滑点轮:环境确定性滑点公式与回测 custom_entry/exit_price 钩子
  成交价 110.055/99.95 完全一致。

**上一阶段的"环境 open[t+2] vs 回测 open[t+1]"错位不复存在。**
env_vs_freqtrade_parity.md/json。【实验确认】

## 19. PPO 烟雾测试

命令与全链路:

```text
run_experiment.py(指纹→config)→ freqtrade backtesting
→ FreqAI 5 窗(30d 训练/7d 预测)→ AlignedLongFlatEnv → PPO(MlpPolicy,cpu)
→ 模型保存 → 顺序推理 → &-target_position → 信号 → 回测
```

- 训练:5 窗 × 482 timesteps(train_cycles=1),device=**cpu**(SB3 日志),
  seed=42;全部完成,无异常;
- 模型文件:每窗 sub-train-*/cb_btc_<ts>_model.zip + feature_pipeline.pkl;
- 动作分布:672 行目标 1 / 48 行目标 0(93% 集中单一动作,如实记录;
  低训练量下属预期,不代表架构失败;无 NaN、无非法动作);
- 回测:1 笔(06-01 01:00 买 → 06-29 01:00 卖,exit_signal,−19.39%)
  ——首行转多 → open[1] 成交,与 gap=1 语义一致;烟雾测试不评价收益;
- 重载:run2(模型重载分支)成交逐字段一致;独立重推理 720 行零差异(§14);
- 缓存隔离:seed 43 独立 identifier(§16)。

ppo_smoke_summary.json。【实验确认】

## 20. 真实数据裁剪与哈希

半开区间 [2026-06-01 00:00, 2026-07-01 00:00) UTC 裁剪:
**720 根**(首 2026-06-01 00:00,末 2026-06-30 23:00),
规范化 CSV(date,open,high,low,close,volume)的
SHA-256 = `cea1349c564688243ec90df020cfb2a03bae212cf1c2a118864147532a82250a`,
写入实验指纹。feather 中 2026-07-01 之后的数据未进入任何评估;
训练预热(30 天训练窗)使用更早数据,不进入评估指标。
未把市场数据文件提交到公开仓库。data_slice_summary.json。【实验确认】

## 21. 已知限制(每项是否阻塞下一阶段)

1. **复利终值 stake 语义差 W·f·(1−R)/笔**(§8):可推导、量级 ≤1e-4 相对;
   不阻塞;正式系统对账时固定口径即可。
2. **回测侧滑点依赖 custom_*_price 钩子**且被 clamp 到当根 high/low:
   不阻塞(锯齿已验证端到端一致);含义是回测滑点不能超过当根振幅,
   这与限价单语义一致。
3. **Dry-run 订单拒绝/部分成交/断线后的状态重同步未实现**:不阻塞阶段
   2.5(验证目标为初始化路径),列为正式系统必做项。
4. **PPO 烟雾模型未利用观察中的仓位分量**(敏感性实验:pos=0/1 输出同动作)
   且动作高集中:训练量 482 步所致;不阻塞——状态传递的正确性由重推理
   一致性证明,与模型是否利用无关;正式训练需扩大 timesteps 并复查。
5. **indicator_periods_candles 不能为空列表**:上游 dataprovider.
   get_required_startup 对空列表 max([]) 直接崩溃(上游边界缺陷);
   本任务配置 [10] 绕过(expand_all 不产生新特征)。不阻塞,已记录。
6. **TensorBoard 自定义 info/* 标量不再输出**(未挂上游
   TensorboardCallback):SB3 标准 rollout 标量仍写;不阻塞。
7. **预测缓存的行数判定仍为 FreqAI 原生行为**:指纹在 config 层隔离,
   同 identifier 内手工改动代码仍可能命中旧缓存——已由"代码哈希进指纹"
   消解(代码变 → 新 identifier);运行时纪律保持 run_experiment 入口。

## 22. 上游维护风险

| 依赖点 | 性质 | 风险与缓解 |
|---|---|---|
| set_train_and_eval_environments 可覆盖 | 官方文档明示的用户扩展点;依赖 data_dictionary 与 prices 行对齐(train() 内部顺序) | 低;若上游改变 train() 内部顺序需复查对齐 |
| fit 可覆盖 | 官方文档明示 | 低 |
| rl_model_predict 可覆盖 | 官方文档明示;依赖 dk.label_list/index | 低 |
| start_backtesting 同一实例按序调用 train/predict | 实现行为而非契约(源码 301-405) | **中**;若上游改为每窗重建实例,实例属性法失效。替代方案:从 dd.append_df 已累积的历史预测末行恢复仓位(数据在 data_drawer,公开),或经 dk 传递;均为 user_data 层可实现,无需 fork |
| Trade.get_trades_proxy | 公开持久层接口(官方 get_state_info 同款) | 低 |
| custom_entry/exit_price 钩子 | 官方策略接口 | 低;clamp 行为随上游 |
| identifier 读取时机(__init__) | 配置生命周期 | 低;指纹注入保持在 config 渲染层 |

总体:全部依赖位于官方声明的扩展点或公开接口,无需 fork;
最脆弱的是窗口间实例存活假设(已给出两条 user_data 层备选)。

## 23. 下一阶段建议

1. **路线 C 可作为正式架构基础**(条件见 §21,均不阻塞);
   建议下一阶段顺序:
   a. Dry-run 级顺序推理接入(真实 heartbeat 路径,短期模拟);
   b. 订单拒绝/部分成交/断线后的仓位重同步设计;
   c. 扩大 PPO 训练量并引入评估集,检查动作分布与仓位分量利用;
   d. 复利口径选择(stake 语义差)写入正式账本规范。
2. 保持实验纪律:一切实验经 run_experiment.py 入口(指纹/manifest 自动化);
   lookahead/recursive 分析工具若需运行,继续遵守一次性 identifier +
   备份纪律(工具会 rmtree 模型目录,上一阶段 §19)。
3. 特征与奖励研究不在本阶段展开(边界遵任务书)。

## 24. 全部复现命令

```bash
wsl -d CryptoRL-Ubuntu-24.04
source ~/projects/crypto_rl/activate-freqtrade.sh
source ~/projects/crypto_rl/scripts/proxy-on.sh   # freqtrade 启动需拉取市场信息

# 1. 全部确定性测试(38 项)
cd ~/projects/crypto_rl
python -m pytest tests/freqai_rl_stage2_5/ -v            # 含账本/序列/对齐/滑点/推理/指纹/dry-run

# 2. PPO 烟雾(指纹->config->freqtrade 全链路,seed 42)
python experiments/freqai_rl_stage2_5/run_experiment.py \
  --timerange 20260601-20260701 --seed 42 --suffix ppo_base --extract-actions

# 3. 模型重载分支(删预测缓存,保留模型)
rm -rf user_data/models/stage25-rc-b6259bb8d5/backtesting_predictions
python experiments/freqai_rl_stage2_5/run_experiment.py \
  --timerange 20260601-20260701 --seed 42 --suffix ppo_reload --extract-actions

# 4. 重载确定性与跨窗口证据(对比两轮 zip + 独立重推理 + 仓位敏感性)
python tests/freqai_rl_stage2_5/ppo_evidence.py <run1.zip> <run2.zip>

# 5. 缓存指纹隔离(seed 43 -> 新 identifier)
python experiments/freqai_rl_stage2_5/run_experiment.py \
  --timerange 20260601-20260701 --seed 43 --suffix cache_iso

# 6. 汇总证据
python tests/freqai_rl_stage2_5/make_evidence.py
```

## 25. 关键附件索引

| 附件 | 内容 |
|---|---|
| artifacts/freqai_rl_stage2_5/architecture_summary.md | 架构/职责边界/扩展点表/设计决策 |
| artifacts/.../experiment_manifest.json | 实验清单(3 个 manifest 的 identifier/指纹/数据哈希) |
| artifacts/.../data_slice_summary.json | 裁剪区间/720 根/SHA-256 |
| artifacts/.../ledger_hand_calculation.md | 全部公式手算对照 |
| artifacts/.../synthetic_{constant,rising,falling,zigzag}_trace.csv | 4 序列 × 6 目标序列逐步 trace(24 列) |
| artifacts/.../synthetic_summary.csv | 24 组合终值/累计奖励/费用/交易数汇总 |
| artifacts/.../env_vs_freqtrade_parity.md/.json | 环境与真实回测器三口径对比+闭式推导 |
| artifacts/.../slippage_monotonicity.csv/.json | 滑点单调性(0/5/10bps × 3 序列) |
| artifacts/.../sequential_inference_trace.csv | 720 行目标仓位序列(带窗口列) |
| artifacts/.../cross_window_state_trace.csv | 各窗首末行与状态传递 |
| artifacts/.../reload_determinism.md/.json | 三层重载证据+仓位敏感性 |
| artifacts/.../cache_fingerprint_test.json | 指纹隔离(函数级+集成级) |
| artifacts/.../ppo_smoke_summary.json | PPO 烟雾汇总 |
| artifacts/.../upstream_integrity.txt | 上游 tag/commit/status |
| logs/freqai_rl_stage2_5/*.log | 00_precheck / ppo_smoke_run1 / ppo_smoke_run2_reload / cache_fingerprint_run_seed43 |
| src/rl_platform/*.py | 核心包源码 |
| user_data/freqaimodels/RouteCModel.py, user_data/strategies/RouteCStrategy.py | 薄适配层 |
| tests/freqai_rl_stage2_5/*.py | 38 项测试 + 证据脚本 |
| experiments/freqai_rl_stage2_5/ | run_experiment.py + 配置模板 + runtime manifests |
