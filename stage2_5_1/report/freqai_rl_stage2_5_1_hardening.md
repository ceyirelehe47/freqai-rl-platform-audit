# Route C 状态一致性与实验纪律加固报告(阶段 2.5.1)

- 生成时间:2026-08-25 UTC
- 审计对象:Freqtrade tag `2026.7`,commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(vendor 零修改,开始/结束均 clean)
- 执行环境:WSL `CryptoRL-Ubuntu-24.04`(Ubuntu 24.04),conda `freqtrade-rl`(Python 3.11.16)
- 上一阶段:`reports/freqai_rl_stage2_5_route_c_validation.md`(公开仓库 stage2_5/)
- 修改前备份:`backups/stage251_20260825/`(10 个文件,项目根非 Git 仓库)
- 加固烟雾 identifier:`stage251-rc-2f131f3b15`(完整指纹见 full_experiment_manifest.json)

---

## 1. 执行摘要

阶段 2.5.1 不重新设计路线 C,只加固七个已知问题:PPO 训练预算记录、
正式策略滑点接入、完整实验指纹、部分缓存防护、do_predict 状态机、
live 历史回填污染、conv_width 硬限制。

**结论:阶段 2.5.1 = PASS**——三十一节 27 项条件全部成立,
三十二节列举的 CONDITIONAL 类型限制仅出现一条(回测器对恰等边界限价
卖单的延迟结算,属上游撮合语义,不阻塞阶段 2.6,详见 §22)。

最重要的五项结果:

1. **PPO 实际训练步数修正**(§4/§5):每窗名义 482 步,实际按 n_steps=128
   的整数倍 rollout 执行 512 步;5 窗 base/rounded/actual 全部记录且
   `actual == rounded == 512`、`rounded % n_steps == 0`。
2. **正式滑点路径**(§8-§10):RouteCStrategy 从渲染后配置读取
   slippage_bps,custom_entry/exit_price 全链路生效;0/5/10bps 四轮 +
   窄 K 线一轮中,回测与环境侧 entry/exit 时间完全一致、价格一致
   (rel 1e-9);"训练有滑点、回测无滑点"不复存在。
3. **部分缓存 fail closed**(§13):真实 5 窗实验只保留窗 1/3 缓存时,
   无修复参数在启动前中止(退出码 3,freqtrade 未启动,缓存未动);
   `--repair-partial-cache` 整体 quarantine 后全窗重推理,动作与交易
   与无缓存基线逐字段一致,零重新训练。
4. **do_predict 状态机**(§14):无效行(do_predict=0/2 或 NaN)不调用
   模型、不更新目标状态;入场/退出被过滤后下一有效行仍正确触发;
   populate 重复调用幂等。
5. **live 心跳**(§15-§17):首次全历史回填用隔离临时状态,最新一行
   从 Trade 表读取真实仓位构造观察;每个 heartbeat 重新读库;订单未成交
   时持续表达相同目标,成交后不重复交易(真值源 = Freqtrade Trade 持久层)。

## 2. 判定:PASS

三十一节 27 项条件逐条核对:

| # | 条件 | 结果 | 证据 |
|---|---|---|---|
| 1 | 上游零修改 | ✓ | upstream_integrity.txt(开始/结束 status 空) |
| 2 | PPO 参数显式解析 | ✓ | §6,resolve_ppo_params 唯一来源+冲突报错 |
| 3 | num_timesteps 准确记录 | ✓ | §5,actual=rounded=512×5 窗 |
| 4 | 482 不再写作实际步数 | ✓ | §4/§5,本报告全文按 482(base)/512(actual) 表述 |
| 5 | conv_width≠1 启动前失败 | ✓ | §7,四处断言+测试 |
| 6 | 正式策略接入滑点 | ✓ | §8,配置读取+0bps 返回原 rate |
| 7 | 0/5/10bps 价格对齐 | ✓ | §10,四轮 rel 1e-9 |
| 8 | 窄 K 线两侧一致 | ✓ | §9/§10,限制后价格逐笔一致 |
| 9 | 指纹含完整配置 | ✓ | §10(指纹节),normalize_config 全量 |
| 10 | 指纹含训练+预热数据 | ✓ | §11,2184 行(4-01→6-30) |
| 11 | 指纹含代码树哈希 | ✓ | §11,18 文件 tree hash |
| 12 | 指纹含依赖版本 | ✓ | §12,import 实测 10 项 |
| 13 | 部分缓存不静默运行 | ✓ | §13,nofix rc=3 |
| 14 | 修复后动作与全量重推理一致 | ✓ | §13,逐行逐字段一致 |
| 15 | do_predict≠1 不更新状态 | ✓ | §14 |
| 16 | 入场被过滤后下一有效行可入场 | ✓ | §14,场景 1 |
| 17 | 退出被过滤后下一有效行可退出 | ✓ | §14,场景 2 |
| 18 | populate 重复调用一致 | ✓ | §14,幂等重建+残留清除测试 |
| 19 | 首次 live 回填不覆盖真实仓位 | ✓ | §15,隔离状态+Trade 真值 |
| 20 | 每个 heartbeat 从 Trade 同步 | ✓ | §16 |
| 21 | 未成交时持续表达目标 | ✓ | §17,场景 1/3 |
| 22 | 成交后不重复交易 | ✓ | §17,场景 2/4 |
| 23 | 模型重载行为一致 | ✓ | §21,动作/交易/mtime 三一致 |
| 24 | 阶段 2.5 原测试全过 | ✓ | §18,38 passed |
| 25 | 新测试全过 | ✓ | §19,74 passed |
| 26 | PPO 加固链路通过 | ✓ | §20,指纹→窗口→PPO→保存→加载→推理→滑点→回测 |
| 27 | 上游最终 clean | ✓ | upstream_integrity.txt |

## 3. 修改文件清单

新增(第一方,均参与代码树指纹):
- `src/rl_platform/guards.py` — conv_width 硬守卫(工作包 B)
- `src/rl_platform/ppo_params.py` — PPO 参数解析/预算/训练(工作包 A)
- `src/rl_platform/price_clamp.py` — Freqtrade 价格限制镜像(工作包 C)
- `src/rl_platform/cache_guard.py` — 缓存完整性状态+quarantine(工作包 E)
- `src/rl_platform/live_inference.py` — live 心跳推理(工作包 G)
- `experiments/freqai_rl_stage2_5_1/configs/config_stage251.template.json`
- `experiments/freqai_rl_stage2_5_1/run_experiment.py`
- `tests/freqai_rl_stage2_5_1/`(conftest + 8 个测试文件 + 2 个证据脚本)

修改(备份于 backups/stage251_20260825/):
- `src/rl_platform/env.py` — prices 强制含 high/low;成交价 clamp;
  episode_reset_count 计数;info 增加 requested_price/price_clamped
- `src/rl_platform/ledger.py` — apply_target 接受 high/low(镜像回测器
  min/max 规则);liquidate 改为无滑点口径(对齐 handle_left_open);
  TradeRecord 增加 requested_price/price_clamped
- `src/rl_platform/inference.py` — predict_frame 接收 do_predict mask;
  window_size 守卫;ScriptedPolicy 增加 save;新增 ReadPositionPolicy
- `src/rl_platform/signal_convert.py` — 重写为"有效目标→信号"状态机
  (回测模拟仓位/live 真实仓位起点;幂等清零重建)
- `src/rl_platform/fingerprint.py` — 代码树哈希/配置规范化/数据范围
  哈希/依赖版本(工作包 D);兼容入口保留
- `user_data/freqaimodels/RouteCModel.py` — 构造期 conv_width 双重断言;
  resolved PPO;fit 经 run_ppo_fit(预算落盘每窗 sub-train 目录);
  rl_model_predict 传 do_predict mask + live 分支调 live_predict_frame
- `user_data/strategies/RouteCStrategy.py` — order_types 显式 limit;
  custom_entry/exit_price 确定性滑点;populate 幂等状态机信号;
  live 下仓位起点从 Trade 表读取
- `tests/freqai_rl_stage2_5/util.py` — make_ohlc 提供正负 0.5% 振幅
  (open/close 不变;工作包 C 需要非退化 K 线)
- `tests/freqai_rl_stage2_5/test_ledger.py` — 场景 12 断言更新为
  无滑点清算口径(行为修正说明见 §22)

## 4. PPO 预算修正

阶段 2.5 的错误:`total_timesteps = train_cycles × len(train_features)`
直接传给 `model.learn()`,而 SB3 PPO 按 n_steps 的整数倍收集 rollout,
实际执行步数是向上取整后的值。阶段 2.5 报告"每窗 482 timesteps"
应更正为:名义 482,实际 512(本阶段起所有记录按 base/rounded/actual
三值区分,旧报告作为历史记录不改动)。

## 5. 每窗实际训练步数

```text
窗口   base(=1×482)  rounded(ceil(482/128)×128)  actual(num_timesteps)  rollouts  episode_resets
1-5    482            512                         512                    4         2
```

- 来源:各窗 `sub-train-BTC_<ts>/ppo_budget.json`(run_ppo_fit 训练后写入);
- 硬校验:`actual == rounded`、`rounded % n_steps == 0`(不满足即抛错);
- episode_resets=2:初始 reset + 训练中 481 步 episode 结束后的 1 次 reset
  (512 = 481 + 31,PPO 在 episode 边界继续 rollout);
- 汇总证据:ppo_budget_per_window.csv。

## 6. 完整 resolved PPO 参数

唯一来源 `freqai.route_c.ppo`(resolved_ppo_parameters.json):

```text
policy_type=MlpPolicy  device=cpu  n_envs=1  seed=42
n_steps=128  batch_size=64  n_epochs=10  learning_rate=0.00025
gamma=0.90  gae_lambda=0.95  clip_range=0.20  ent_coef=0.0
vf_coef=0.5  max_grad_norm=0.5  normalize_advantage=true  net_arch=[32,32]
```

- 冲突检测:渲染阶段(strict)若 rl_config/model_training_parameters 出现
  任何 PPO 构造键即报错;模板已移除 net_arch/learning_rate/gamma 旧位置。
  freqtrade 进程内 strict=False——源码确认 FreqtradeValidator 会按
  schema 自动填充 rl_config 默认键(net_arch=[128,128] 等),该注入发生在
  指纹之后,不进入指纹;训练只用 resolved 值。
- 实际传入 PPO 的参数与 manifest 完全一致(run_ppo_fit 直接展开
  resolved["constructor"])。
- SB3 2.9.0 构造签名与上述键完全兼容,无差异需记录。

## 7. conv_width 保护

四处断言(guards.assert_conv_width,异常消息固定为
"Route C 当前仅验证 conv_width=1。提高窗口长度前必须实现跨调用特征
缓冲和 live 去重。",无自动降级):

1. 配置渲染(run_experiment.render_config);
2. RouteCModel.__init__(父类规范化前后各一次:kwargs config 与
   最终 CONV_WIDTH);
3. 顺序推理入口(SequentialPositionPredictor 构造);
4. 实验启动前检查(主流程复用 1)。

测试:test_conv_width_guard.py(正常/异常/非整数 1.5/字符串/None、
模型构造、渲染守卫);conv_width 同时进入完整配置与指纹顶层字段,
任何变化产生新 identifier。

## 8. 正式滑点接入(RouteCStrategy)

- 滑点从渲染后配置 `freqai.route_c.slippage_bps` 读取,不写死;
- 入场退出同值:`custom_entry_price = proposed_rate×(1+bps/1e4)`,
  `custom_exit_price = proposed_rate×(1-bps/1e4)`;bps=0 返回原 rate;
- `order_types` 显式 limit(钩子仅对 limit 单生效);
- 不影响手续费(费仍按成交名义金额计,回测器口径不变);
- 滑点配置进入指纹(完整配置);
- 测试:test_live_trade_state_resync.py::test_strategy_slippage_from_config。

## 9. 窄 K 线价格限制

上游规则(固定 commit 源码确认):
- entry:`new_rate=custom_entry_price(default=open)` → 若变更经
  price_to_precision → `min(rate, 当根 high)`(long);
- exit_signal 族:`rate=custom_exit_price(default=open)` → `max(rate,
  当根 low)`(long,exit 侧无 precision 处理);
- forced exit(handle_left_open):当根 open 平仓,不走 custom price,
  不收滑点,扣手续费。

环境镜像(ledger/price_clamp):买入成交价 = min(请求价, 当根 high),
卖出 = max(请求价, 当根 low);环境 prices 强制提供执行 bar 的
open/high/low/close。两侧使用同一最终成交价。

precision 差异说明:entry 侧 price_to_precision 上界为 1 个价格 tick
(虚拟市场 1e-8 可忽略;真实 BTC/USDT tick=0.01,相对 ~1e-7,
比 5bps 小两个数量级);测试用虚拟市场做精确断言,真实市场差异
记录为已知限制(§22)。

窄 K 线验证:±0.5bps 十字星 bar + 5bps 滑点,买入请求必超 high、
卖出必破 low → 两侧成交价 = 限制后价格(high/low),逐笔一致
(route_c_slippage_parity.md 的 narrow 轮 + narrow_candle_price_clamp.json)。

**发现(回测器撮合边界)**:当 clamp 后卖价恰等于当根 low 时,
Freqtrade 回测器不在当根撮合该限价卖单(需价格严格穿越挂单价),
卖单延迟结算期间吞掉后续 enter 信号。窄轮对齐改为双方同刻成交子集
逐笔比较(价格/时间/单笔收益全部一致);该行为为上游挂单撮合语义,
不是两侧价格限制不一致。

## 10. 端到端滑点对齐(工作包 C 第十节)

链路:真实 RouteCStrategy(滑点钩子+状态机信号)+ ScriptedRouteCModel
(RouteCModel 的确定性 scripted 适配:仅覆盖 fit 返回 ScriptedPolicy,
不训练 PPO;测试级,生产路径不依赖)+ 真实 Backtesting.start()
+ 虚拟市场(SYN/USDT,precision 1e-8)+ FreqAI 全流水线
(特征→pipeline→逐窗 scripted→保存→顺序推理→信号→回测)。

| 轮次 | fee | slip | 回测交易数 | 结果 |
|---|---|---|---|---|
| fee0_slip0 | 0 | 0 | 16 | 时间/价格/单笔收益全一致;终值=递推闭式(1e-9) |
| fee001_slip0 | 0.001 | 0 | 16 | 同上;终值差=逐笔递推 stake 口径差 |
| fee001_slip5bps | 0.001 | 5 | 16 | 同上,非零滑点两侧一致 |
| fee001_slip10bps | 0.001 | 10 | 16 | 同上 |
| fee001_slip5bps_narrow | 0.001 | 5 | 13(全十字星) | 双方同刻成交逐笔一致;全部被限制 |

- 单笔收益率误差 ≤ 1e-7(回测 round 8 位),明确上限;
- 终值:环境侧与逐笔递推闭式一致(1e-9);回测侧与递推差仅精度截断
  (≤5e-6/笔);环境-回测费差 = stake 口径差(每笔 W·f/(1+f) 量级,
  阶段 2.5 单笔公式 W·f·(1-R) 的多笔推广);
- 环境重放目标序列来自 FreqAI 预测缓存(全链路输出,非手工信号)。

## 10a. 完整实验指纹(工作包 D)

组成(任一变化 → 新 fingerprint → 新 identifier → 新缓存目录):

1. Freqtrade commit;
2. 第一方代码 tree hash:src/rl_platform/**/*.py、RouteCModel.py、
   RouteCStrategy.py、experiments/freqai_rl_stage2_5{,_1}/**/*.py|json
   (18 个文件,排除 runtime/logs/artifacts/__pycache__/模型/缓存;
   内容哈希,mtime 无关——专项测试验证触碰 mtime 不变);
3. 完整最终解析配置(排序规范化 JSON;移除 freqai.identifier 避免自指;
   渲染→指纹→写 identifier 的顺序消除循环);
4. 数据范围哈希(§11)+ 评估区间行数;
5. 依赖版本(§12)+ resolved PPO 参数 + conv_width 顶层字段。

单变量指纹变化测试(任务书三十节 12 项):seed/fee/slippage/
PPO n_steps/PPO gamma/conv_width/特征配置/run_experiment.py/
配置模板/RouteCModel 代码/RouteCStrategy 代码/训练数据一行/
依赖版本模拟值/timerange——全部产生新指纹(test_full_fingerprint.py)。

六文件手写清单已废除(collect_code_hashes 保留为兼容入口,指向
tree hash)。

## 11. 数据哈希范围

```text
source_file: BTC_USDT-1h.feather
sha256: 47e7813723acf2ba69d7198de94c83cf81a7642e8bf469d40730ecb62f914baa
rows_hashed: 2184(2026-04-01 00:00 → 2026-06-30 23:00)
eval_rows: 720([2026-06-01, 2026-07-01))
训练窗口: 5 窗 × [T-30d, T),T ∈ {06-08, 06-15, 06-22, 06-29, 07-06 截断}
预测窗口: 5 窗 × [T, T+7d) 截断到 07-01
```

范围规则:数据文件中所有 date < 评估结束时间的行——覆盖评估区间 +
全部训练数据 + startup/预热(最早训练窗起点 5-08 前推 99 根 startup +
buffer,含于 4-01 起)。专项测试:评估结束后新增 K 线不改变哈希;
修改任何一行训练数据改变哈希。所有实际消费的 train/test 行均位于
已哈希范围(窗口边界由同一算法推导并与真实 DataKitchen 对拍一致);
若发现实际消费数据超出哈希范围,实验判无效(fail 语义写入 run_experiment)。

## 12. 依赖版本(import 实测)

```text
python 3.11.16          freqtrade 2026.7 (commit 52bc96f)
stable_baselines3 2.9.0 gymnasium 1.3.0
torch 2.13.0+cu130      numpy 2.4.6   pandas 3.0.3
scikit-learn 1.9.0      ccxt 4.5.68
os Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.39
```

## 13. 部分缓存防护

状态定义(运行前检查,预期窗口集合从 timerange 与窗口配置推导,
不写死 5;与真实 DataKitchen.split_timerange 逐窗对拍一致):

- NONE:无缓存(全新实验);COMPLETE:预期文件全在且行数=窗口 bar 数;
- PARTIAL:只有部分预期窗口;INCONSISTENT:多余文件或行数不符。

默认 fail closed:PARTIAL/INCONSISTENT → 启动前中止(退出码 3),
打印缺失/多余清单;freqtrade 子进程未启动,旧缓存 mtime/内容未变。

显式修复 `--repair-partial-cache`:整个 backtesting_predictions 目录
rename 到带 UTC 时间戳的 quarantine 目录(同文件系统原子移动,
不删除,附说明文件),保留全部已训练模型,从第一窗起重推理,
顺序状态从空仓正确开始(新进程 _last_target_position=0)。

**集成硬验收**(真实 5 窗 stage251-rc-2f131f3b15):
- 构造:只留窗 1/3 缓存(窗 2/4/5 文件移除);
- 无修复:退出码 3,缓存未动 ✓;
- 修复:quarantine=`backtesting_predictions_quarantine_20260825T110415Z`,
  5 窗全部重新顺序推理,动作序列与无缓存基线逐行一致,
  交易逐字段一致,模型文件 mtime 不变(零重新训练),identifier 不变 ✓。

证据:partial_cache_guard.md / partial_cache_repair_trace.json /
partial_cache_guard_unit.json。

## 14. do_predict 状态机

生成时机调查(源码确认):`BaseReinforcementLearningModel.predict` 在
调用 rl_model_predict 之前执行 `dk.filter_features(training_filter=False)`,
其中把含 NaN 的预测行标记为 0(data_kitchen.py,do_predict=1 有效),
长度与预测 dataframe 严格对齐;datasieve transform 的 outlier 数组被
上游 RL 分支丢弃,但本配置禁用 SVM/DI(use_SVM_to_remove_outliers=
false、DI_threshold=0),NaN 检查即完整语义。RouteCModel 在 mask 长度
与行数不一致时拒绝推理(fail fast)。

顺序推理(predict_frame)逐行:do_predict≠1 或观察含 NaN/Inf →
不调用模型、输出当前目标、不更新顺序状态(测试验证无效行未消费
policy 游标)。

信号生成(targets_to_signals 状态机):do_predict≠1 行不生成信号、
仓位状态不变;空仓+有效目标 1 → enter;多头+有效目标 0 → exit;
目标与状态相同 → 无信号。回测 initial=0;live initial=Trade 表
真实仓位。幂等:每次先清零 enter_long/enter_tag/exit_long 再重建,
旧 dataframe 残留信号被清除;populate_entry/exit 先后重复调用结果
完全一致(专项测试)。

四场景回归(test_do_predict_state_machine.py):
- 空仓入场被阻止(dp=0)→ 无入场、状态 0;下一有效行目标 1 → 正常入场 ✓
- 多头退出被阻止 → 状态 1;下一有效行目标 0 → 正常退出 ✓
- 模型过期(dp=2)→ 无信号、不改变目标或状态 ✓
- 重复调用 → 信号完全相同 ✓

## 15. 首次 live 全历史推理

live_predict_frame(工作包 G):
- 历史回填调用(行数>conv_width):隔离的临时 SequentialPositionPredictor
  (初始空仓)生成历史目标序列,仅供 UI 展示,不写入任何执行状态;
  随后**重新从 Trade 表读取真实仓位**,用真实仓位构造最新一行观察,
  只让最新一行决定当前交易目标。
- 增量 heartbeat(行数=conv_width=1):每次都从 Trade 表重新读取真实
  仓位构造观察并预测。
- `_last_target_position` 仅用于 backtest 跨窗口延续;live 下作为
  do_predict 无效行的 fallback 目标(不更新状态语义),不作为仓位真值源。

测试(test_live_full_history_inference.py,内存 SQLite + 真实 Trade 模型 +
真实 RouteCModel.rl_model_predict 调用链):首次 100 行历史 + 真实仓位 1
→ 最新观察仓位分量=1(ReadPositionPolicy 回显)、历史段隔离重放全 0、
实时状态保持 1;下一 heartbeat 仍从数据库读取;模型重新加载(新实例)
后仍正确;空仓初始状态;do_predict=0/2(含无先验目标回落真实仓位);
连续历史回填不改变执行状态 ✓。

## 16. Trade 状态 heartbeat 同步

每个 heartbeat 的仓位真值源固定为 Freqtrade Trade 持久层:
`RouteCStrategy._current_position_for_signals` 在 DRY_RUN/LIVE runmode 下
调用 `get_initial_position_live(pair)`(Trade.get_trades_proxy(is_open=True)),
与官方 BaseReinforcementLearningModel.get_state_info 同款公开接口;
不依赖内存中的上一目标。逐 heartbeat trace:live_full_history_trace.csv。

## 17. 订单未成交时的行为

四场景(test_live_trade_state_resync.py,真实 Trade 表驱动信号生成):
- 入场未成交(Trade 空)目标 1 → 每个 heartbeat 持续生成 enter ✓
- 入场已成交(Trade open long)目标 1 → 不再重复入场 ✓
- 退出未成交(仍 open long)目标 0 → 持续生成 exit ✓
- 退出完成(Trade 空)目标 0 → 不再重复退出 ✓

阶段 2.5.1 不实现部分成交引擎;订单成交状态以 Trade 持久层为准,
重复决策幂等。trace:live_trade_resync_trace.csv。

## 18. 原测试回归

阶段 2.5 原测试:38 passed(无删除、无跳过、无断言放宽)。
两处与任务书直接相关的调整(非放宽,已在 §3/§22 说明):
make_ohlc 提供真实振幅(K 线不再是 open=high=low 的退化形态,
open/close 与全部净值断言不变);test_ledger 场景 12 清算断言更新为
无滑点口径(行为修正,方向是对齐回测器)。

## 19. 新测试结果

阶段 2.5.1 新测试:74 passed(tests/freqai_rl_stage2_5_1/):

| 文件 | 覆盖 |
|---|---|
| test_ppo_budget.py | 预算取整/参数解析/冲突检测/真实 128 步训练/预算落盘/TB 生成 |
| test_conv_width_guard.py | 四处断言/非整数拒绝/指纹联动 |
| test_full_fingerprint.py | 配置规范化/单变量 12+ 项/代码树/数据范围/依赖实测/manifest 完整性 |
| test_partial_cache_guard.py | 窗口推导对拍 DataKitchen/四状态/fail closed/quarantine |
| test_do_predict_state_machine.py | 四场景+幂等+残留清除+推理 mask |
| test_route_c_slippage_live_strategy.py | 五轮端到端对齐+窄 K 线(真实 RouteCStrategy 全链路) |
| test_live_full_history_inference.py | 历史回填隔离/heartbeat/重载/空仓/do_predict |
| test_live_trade_state_resync.py | 未成交重复意图/成交不重复/配置滑点 |

全量混合运行(tests/):112 passed(38+74,含 Backtesting 级用例;
Trade.use_db 测试隔离已处理)。

## 20. PPO 加固烟雾

参数:BTC/USDT 1h、Long/Flat、conv_width=1、seed=42、fee=0.001、
slippage=5bps、显式 PPO 参数(§6)。完整链路:完整指纹 →
新 identifier(stage251-rc-2f131f3b15)→ FreqAI 5 窗 →
AlignedLongFlatEnv(含 clamp)→ PPO(512 步/窗)→ 模型保存 →
加载 → 顺序推理(do_predict mask)→ RouteCStrategy 滑点(5bps)→
Freqtrade 回测。不评价收益。

记录:每窗 base=482/rounded=512/actual=512/rollouts=4/
episode_resets=2;动作分布 1×336 + 0×384(720 行);无 NaN;
模型文件与预测缓存清单见 manifest;回测 2 笔(均 exit_signal):
06-08 01:00 买 63634.26 → 06-15 01:00 卖 65588.47(+2.87%);
06-22 01:00 买 63962.31 → 06-29 01:00 卖 59641.22(-6.94%)。
成交价已含 5bps 滑点(正式策略钩子生效)。

TensorBoard tags(12 个,全在):
rollout/ep_rew_mean、rollout/ep_len_mean、train/policy_gradient_loss、
train/value_loss、train/entropy_loss、train/explained_variance、
train/approx_kl(+clip_fraction/clip_range/learning_rate/loss/time/fps)。
指标值不评价(任务书只要求生成、无 NaN、与 identifier 对应)。

## 21. 模型重载

删除该 identifier 全部预测缓存、保留模型 → 重跑:
- 实际重新训练为零(sub-train 模型文件 mtime 不变;
  run_params/pair_dictionary 为 FreqAI 启动期元数据,每次运行重写,
  不属于训练产物,已在快照中排除并说明);
- 交易逐字段一致(2 笔,含 5bps 滑点成交价);
- 动作逐行一致(720 行);
- manifest 与 identifier 不变。
证据:reload_determinism.json / baseline_trades.csv。

## 22. 已知限制(均不阻塞阶段 2.6)

1. **回测器恰等边界限价卖单延迟结算**(§9 发现):clamp 后卖价恰等于
   当根 low 时,回测器不在当根撮合(需价格严格穿越),延迟期间吞掉
   后续 enter。仅影响"窄 K 线 + 滑点恰好触边"的极端场景;常规振幅
   (请求价在 bar 内部)不受影响;两侧成交价在该场景下仍逐笔一致。
   不阻塞:阶段 2.6 人工训练的市场 K 线有正常振幅。
2. **entry 侧 price_to_precision 差异**:环境未模拟价格精度截断,
   上界 1 个价格 tick(真实市场相对 ~1e-7 << 5bps)。不阻塞。
3. **stake 口径差**(继承阶段 2.5,已闭式推导并多笔推广):回测器
   stake=amount×rate 不为买入费预留现金,环境按现金覆盖成本约束;
   终值差有界且两侧单笔收益率公式严格一致。不阻塞(阶段 2.6 人工
   训练用环境口径,回测对比按推导闭式校验)。
4. **部分成交细粒度金额同步未实现**(任务书边界内):Trade 状态源与
   重复意图逻辑已正确;金额级部分成交留待后续。不阻塞阶段 2.6。
5. 测试 harness 未模拟真实网络延迟(任务书三十二节明示允许)。
6. 上游 dataprovider 对 indicator_periods_candles=[] 的边界缺陷
   (阶段 2.5 已记录)继续用 [10] 绕过(expand_all 不产生特征)。

无三十三节 FAIL 条目中的任何一项。

## 23. 是否允许进入阶段 2.6

**允许**。27 项 PASS 条件全部成立;已知限制均不阻塞。
阶段 2.6(人工课程训练)可以开始,建议入口:在本阶段加固后的
run_experiment 2.5.1 入口上叠加人工市场数据源(数据范围哈希会自动
覆盖新文件)。

## 24. 完整复现命令

```bash
source ~/projects/crypto_rl/scripts/proxy-on.sh
source ~/projects/crypto_rl/activate-freqtrade.sh
cd ~/projects/crypto_rl

# 全部确定性测试(112 项)
python -m pytest tests/ -q

# PPO 加固烟雾(指纹 -> FreqAI 5 窗 -> PPO 512 步/窗 -> 顺序推理 -> 滑点回测)
python experiments/freqai_rl_stage2_5_1/run_experiment.py \
    --timerange 20260601-20260701 --seed 42 --slippage-bps 5 \
    --fee 0.001 --suffix smoke --extract-actions

# 证据收集(重载确定性 + 部分缓存集成 + TB tags)
python tests/freqai_rl_stage2_5_1/ppo_evidence.py --suffix smoke
python tests/freqai_rl_stage2_5_1/make_evidence.py smoke

# 上游完整性
git -C vendor/freqtrade describe --tags --exact-match   # 2026.7
git -C vendor/freqtrade rev-parse HEAD                  # 52bc96f...
git -C vendor/freqtrade status --short                  # 空
```

## 25. 证据文件索引

`artifacts/freqai_rl_stage2_5_1/`(21 个文件,均有实际内容):

| 文件 | 内容 |
|---|---|
| resolved_ppo_parameters.json | 完整 resolved PPO 参数 |
| ppo_budget_per_window.csv / ppo_budget_unit.json | 每窗与单元级预算记录 |
| tensorboard_tags.txt | TB tags(12 个) |
| conv_width_guard.txt | 四处断言验证记录 |
| route_c_slippage_parity.md / .json | 五轮端到端对齐明细 |
| narrow_candle_price_clamp.json | 窄 K 线限制公式证据 |
| full_experiment_manifest.json | 完整 manifest(指纹/配置/代码树/数据/依赖/预算/窗口/缓存) |
| data_fingerprint_scope.json | 数据哈希范围 |
| code_tree_fingerprint.json | 18 文件代码树哈希 |
| dependency_versions.json | 依赖版本实测 |
| partial_cache_guard.md / partial_cache_repair_trace.json / partial_cache_guard_unit.json | 部分缓存防护三份证据 |
| do_predict_state_trace.csv | 状态机轨迹 |
| live_full_history_trace.csv / live_trade_resync_trace.csv | live 逐 heartbeat 轨迹 |
| regression_test_summary.md | 38+74 回归总结 |
| ppo_hardening_smoke.json | 烟雾汇总 |
| reload_determinism.json / baseline_trades.csv | 重载确定性与基线交易 |
| upstream_integrity.txt | 上游开始/结束完整性 |
