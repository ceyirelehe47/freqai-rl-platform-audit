# 路线 C 架构说明(阶段 2.5)

## 职责边界

```text
vendor/freqtrade (tag 2026.7, commit 52bc96f,零修改)
├── 历史数据下载与管理
├── 正式回测(Backtesting.start())
├── FreqAI 编排:特征流水线、训练/验证切分、滑动时间窗口、
│   模型生命周期、模型保存/加载、历史模型切换、预测缓存
└── 未来 Dry-run / 实盘执行

src/rl_platform/(项目自有核心包,约 700 行)
├── ledger.py        Long/Flat 净值账本(现金/BTC/费/滑点/已实现/未实现)
├── env.py           AlignedLongFlatEnv(gymnasium.Env,不继承 Freqtrade 基类)
├── inference.py     SequentialPositionPredictor 顺序状态推理 + 测试用脚本策略
├── signal_convert.py 目标仓位 -> enter/exit 信号转换
├── fingerprint.py   实验指纹 -> identifier(缓存隔离)
└── dryrun_state.py  Dry-run/实盘初始仓位(读 Trade 表,不用 add_state_info)

user_data/freqaimodels/RouteCModel.py   FreqAI 薄适配层(~160 行)
user_data/strategies/RouteCStrategy.py  Freqtrade 策略薄适配层(~90 行)
experiments/freqai_rl_stage2_5/         run_experiment.py(指纹入口)+配置模板
tests/freqai_rl_stage2_5/               38 项测试 + 证据脚本
```

## 时间语义(gap=1,训练=推理=回测)

```text
K 线 t 收盘 -> 观察含行 t 的特征窗口 + 当前目标仓位 -> 输出目标仓位
-> open[t+1] 执行(含滑点/费用) -> close[t+1] 期末净值 -> 奖励 = log(E'/E)
```

- 环境:决策 t ∈ [window_size-1, N-2],执行/清算 bar ∈ [window_size, N-1];
  最后一根 bar 不进入任何观察(纯执行/清算 bar);
- 推理:SequentialPositionPredictor 逐行构造与训练完全相同的观察;
- 回测:&-target_position 写在行 t,Freqtrade 自身 shift(1) -> open[t+1] 成交,
  本层零额外 shift。

## FreqAI 扩展点覆盖清单

| 覆盖方法 | 原默认行为 | 新行为 | 依赖的内部接口 |
|---|---|---|---|
| RouteCModel.set_train_and_eval_environments | 构造 Base5ActionRLEnv(open[t+2] 执行、官方记账/奖励) | 构造 AlignedLongFlatEnv | 官方声明可覆盖;依赖 data_dictionary["train/test_features"] 与 prices_train/test 的行对齐(train() 内部顺序保证) |
| RouteCModel.fit | ReinforcementLearner.fit + MaskableEvalCallback + device auto | 最小 PPO(device=cpu、set_random_seed(seed)、无 eval callback) | MODELCLASS/self.net_arch/self.CONV_WIDTH(公开属性);total_timesteps 公式与官方一致 |
| RouteCModel.rl_model_predict | rolling(CONV_WIDTH).apply 逐行独立预测 | SequentialPositionPredictor 顺序推理,跨窗口经实例属性 _last_target_position 延续 | dk.label_list、dataframe.index(公开);freqai_interface.start_backtesting 在同一模型实例上按时间顺序调用 train/predict(源码 301-405 行,窗口循环有序) |
| RouteCStrategy(feature_engineering_standard / set_freqai_targets / populate_entry/exit_trend) | 官方示例特征与 &-action 映射 | 4 个因果特征 + &-target_position 目标列 + 目标变化转信号 | 官方 FreqAI 策略接口(文档化) |

不覆盖 train()/predict()/build_ohlc_price_dataframes:特征过滤、缩放、
OHLC 提取、缓存判定全部复用官方实现。

## 实验指纹

run_experiment.py 在渲染 config 前计算指纹(freqtrade commit + 6 个自有代码
文件 SHA-256 + 奖励/费用/滑点配置 + 特征清单 + timerange + 裁剪后数据
SHA-256 + seed + 模型类型 + 训练参数),identifier = stage25-rc-<指纹前 10 位>。
identifier 在 IFreqaiModel.__init__(freqai_interface.py:69)读取
config["freqai"]["identifier"] 展开,因此指纹注入点在 config 渲染阶段,
不修改 FreqAI 缓存校验代码。

## 关键设计决策

1. 账本费用口径对齐回测器:买入 qty = cash/(p*(1+f)),卖出所得 = qty*p*(1-f),
   等价于回测器 open_value = amount*rate*(1+f)、close_value = amount*rate*(1-f);
   单笔 profit_ratio 两公式完全一致,复利终值差 = W*f*(1-R)(stake 语义差异,
   见 env_vs_freqtrade_parity.md 推导)。
2. 终端清算用最终执行 bar 的 open(与 Freqtrade handle_left_open 用最后一根
   bar 的 open 强平同族),不使用最终 close 清算。
3. 滑点通过确定性公式进环境;回测侧用 custom_entry_price/custom_exit_price
   用户钩子复现(limit 单生效,会被 clamp 到当根 high/low 内,
   backtesting.py:1041/892)。
4. 目标仓位在训练与推理中以相同编码进入观察末维(0.0/1.0 浮点),
   不经过 FreqAI 特征缩放(账户状态用固定已知编码)。
