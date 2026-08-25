# FreqAI RL 阶段一与阶段二审计报告

- 生成时间:2026-08-25 UTC
- 审计对象:Freqtrade tag `2026.7`,commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`
- 执行环境:WSL `CryptoRL-Ubuntu-24.04`(Ubuntu 24.04),conda `freqtrade-rl`(Python 3.11.16),PyTorch cu130,RTX 3060 Laptop 6GB
- 数据:BTC/USDT spot 1h,Binance US(binanceus),回测区间 2026-06-01 → 2026-07-01 UTC
- 证据分级:【源码确认】【实验确认】【文档声明】【合理推断】【尚未确认】均逐条标注

---

## 1. 执行摘要

阶段一(官方链路验收)与阶段二(交易语义审计)全部完成,关键产物齐备。
**结论:原生 FreqAI RL 链路可用,但其训练环境与 Freqtrade 回测器存在一处系统性
一根 K 线执行错位,叠加奖励与净值严重脱钩、episode 未平仓不入账、费用模型
无滑点/价差等问题。推荐路线 B:Freqtrade 保留为数据与交易平台,训练改用
自定义 Gymnasium 环境。**

最重要的一条证据(§18):同一信息集(观察 2026-06-01 00:00 这根 K 线)下,
三动作 RL 训练环境做成 **−11.29%**,而 Freqtrade 回测器对同信号做成 **+8.87%**,
方向相反;要让回测器复现 RL 环境的成交价,必须把信号再提前一根 K 线。

## 2. 最终路线建议

**路线 B(推荐)**:Freqtrade 负责数据下载/管理、正式回测、Dry-run 与未来实盘;
训练(状态、动作、费用、滑点、奖励、episode)改用独立自定义 Gymnasium 环境。
详细依据见 §23。

## 3. 环境、版本与固定仓库

| 项 | 值 | 证据 |
|---|---|---|
| Freqtrade | 2026.7 | 【实验确认】`git describe --tags --exact-match` = 2026.7 |
| commit | 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5 | 【实验确认】`git rev-parse HEAD` |
| 上游仓库状态 | 任务开始与结束均 `git status --short` 为空 | 【实验确认】日志 00_precheck.log / 12_final_check.log |
| Python / env | 3.11.16 @ miniforge3/envs/freqtrade-rl | 【实验确认】`which python` |
| pip check | No broken requirements found | 【实验确认】 |
| GPU | RTX 3060 Laptop,驱动 581.15,CUDA 13.0 | 【实验确认】nvidia-smi |
| 本任务新增 pip 包 | pytest 9.1.1、pytest-mock、pytest-xdist、pytest-asyncio、pytest-timeout(仅测试工具,运行时依赖未动) | 【实验确认】 |

## 4. 数据源与质量

- 交易所选择过程:直连(WSL fake-IP TUN)对所有交易所 API 超时;经本地代理
  (http://127.0.0.1:7897)Binance 主站返回 **HTTP 451(地区封锁)**,OKX/Kraken 可用。
  按任务顺序应先 Binance;经用户指示改用 **Binance US(binanceus,官方站点、
  freqtrade 原生支持)**,其公共端点经代理 HTTP 200。【实验确认】02b/02d 日志。
- freqtrade 异步 ccxt(aiohttp)默认不读环境变量代理,本任务通过
  `exchange.ccxt_config.aiohttp_trust_env=true`(freqtrade 官方配置字段,
  exchange.py:269-277 会并入 ccxt)解决,未改任何源码/全局代理/SSL 设置。
- 下载:`freqtrade download-data --exchange binanceus --pairs BTC/USDT --timeframes 1h
  --timerange 20260401-20260701`,feather 格式,2999 根(2026-04-01 00:00 →
  2026-08-03 22:00 UTC,含任务区间之外的顺延数据)。
- 质量检查全部通过:UTC、0 重复、0 缺失小时、OHLC 合法、0 零/负价、0 负量、0 NaN。
  SHA-256:`4771471d6138150d1dd549cac1b003d4cf56ae059422a8f0487c0332610dea7e`。
  【实验确认】data_quality_summary.md

## 5. 阶段一执行结果

### 5.1 官方原始路径(ReinforcementLearner + 官方五动作映射)

- 命令:`freqtrade backtesting --config config_freqai-rl-platform-audit-2026-7-official5ac.json
  --strategy OfficialRLStrategy5ac --freqaimodel ReinforcementLearner
  --timerange 20260601-20260701 --cache none --export trades`
- 结果:退出码 0,耗时 107s;5 个训练窗口(每窗 30 天,训练特征 12 列、
  train/test=482/238 行,PPO timesteps=482×train_cycles=482/窗,
  device=cuda(SB3 明确警告 MLP 用 GPU 效率低,但确实在 GPU 上);
  峰值显存 1585 MiB,峰值 RSS ≈ 2.0 GB;回测 1 笔交易,−1.756 USDT(−0.18%)。
- **关键发现**:5 个窗口的预测动作分布中,4 个窗口 **100% 为动作 3
  (Short_enter)**,仅 1 个窗口出现 1 次动作 1(167×3+1×1)。
  即官方默认五动作环境在 `can_short=False`(spot)下,agent 被奖励函数引导
  学会开空仓(开仓即 +25,不分方向),而策略把 &-action==3 映射到 enter_short,
  回测器因 spot 忽略空信号 → 绝大多数动作被静默丢弃。
  【源码确认+实验确认】
- 源码根因:`Base5ActionRLEnv` 的 `step()/is_tradesignal()` 完全不检查
  `self.can_short`(Base5ActionRLEnv.py:32-135),该字段只在三动作环境与
  `BaseEnvironment` 部分公式中使用。**官方原始路径与 spot long-only 目标
  行为不兼容(非报错,而是动作静默失效)。**

### 5.2 最小 long-only 适配路径(AuditBase3RLModel + AuditLongOnlyRLStrategy)

- 组合:`MyRLEnv = Base3ActionRLEnv` + 上游测试模型同款奖励(逐行复制自
  tests/freqai/test_models/ReinforcementLearner_test_3ac.py,未做任何奖励设计);
  策略映射 1=enter_long、2=exit_long,can_short=False。
- 结果:退出码 0;5 窗训练;**7 笔交易,−21.292 USDT(−2.13%)**;
  动作分布(168 行/窗):窗1 {0:7, 1:160, 2:1},窗2 {1:168},窗3 {0:12, 1:155, 2:1},
  窗4 {0:17, 1:147, 2:4},窗5(48 行) {0:6, 1:42};do_predict 全程 1.0。
- 与官方模型的差异(逐项):仅替换内嵌环境基类(5Ac→3Ac);策略删除
  short 分支;两策略统一 minimal_roi={"0":100}、stoploss=−0.99(事实禁用,
  上游测试策略原值 roi=0.1/stoploss=−0.05 会污染动作流,已列为审计偏差)。

## 6. 模型保存与重新加载机制(实验三分支)

| 分支 | 触发条件 | 观察到的行为 | 证据 |
|---|---|---|---|
| 预测缓存复用 | `backtesting_predictions/cb_btc_<ts>_prediction.feather` 存在且行数匹配 | 5× "Found backtesting prediction file",**不加载模型、不训练**,结果与首跑逐字一致(7 trades/−2.13%);模型与缓存文件字节零变更(仅 run_params.json 更新) | run2,49s |
| 模型重载 | 缓存缺失/行数不匹配,但 `sub-train-*/cb_btc_<ts>_model.zip` 存在 | 无 "Could not find model"、无任何 "Starting training";预测缓存重新生成;模型 zip SHA-256 不变;结果一致 | run3,16s |
| 重新训练 | 模型文件也不存在 | "Starting training…" → "Saving backtest model to disk" | 首跑 |

- 源码依据:freqai_interface.py:329-340(缓存优先)、366-400(model_exists→
  dd.load_data,SB3 `MODELCLASS.load(zip)`)、data_kitchen.py:928-959(缓存校验
  仅看行数与 date 列)。【源码确认+实验确认】
- 注意:预测缓存只按"文件名+行数"判定有效——**同窗不同策略/不同奖励/不同
  seed 的模型若生成过缓存,会被静默复用**;复现实验必须先清缓存(本任务
  run3 即演示了这一点)。

## 7. TensorBoard 验证

- 每个训练窗口生成一个 event 文件(user_data/models/<identifier>/tensorboard/BTC/PPO_n/),
  两个 identifier 共 10 个,均非零字节。
- `tensorboard --inspect` 可读。实际 tag:actions/Buy、actions/Neutral、actions/Sell、
  eval/mean_reward、eval/mean_ep_length、rollout/ep_len_mean、rollout/ep_rew_mean、
  time/fps、info/tick、info/action、info/position、info/current_profit_pct、
  info/total_profit、info/total_reward、info/trade_duration、info/TimeLimit.truncated。
- **不存在** policy/value loss、entropy 等 train/ 标量:本审计配置
  model_training_parameters 未设 verbose(=0),SB3 不输出训练标量。
  【实验确认】tensorboard_tags.txt

## 8. FreqAI RL 源码调用流程(阶段二 §13)

```text
Freqtrade 策略 populate_indicators()
 └─ self.freqai.start(dataframe, metadata, strategy)        freqai_interface.py:130
     └─(回测)start_backtesting()                            freqai_interface.py:273
         ├─ 滑窗: train_period_days(30d) → backtest_period_days(7d),共 5 窗
         ├─ 缓存有效 → get_backtesting_prediction() 直接复用 &-action
         └─ 否则 use_strategy_to_populate_indicators() → set_freqai_targets()
            → BaseReinforcementLearningModel.train()        RL/BaseReinforcementLearningModel.py:99
              ├─ filter_features/make_train_test_datasets(33% 测试集)
              ├─ build_ohlc_price_dataframes(): %-raw_open/high/low/close → prices
              ├─ feature_pipeline = VarianceThreshold + MinMaxScaler(-1,1),仅在训练窗拟合
              ├─ set_train_and_eval_environments()           :153
              │   ├─ MyRLEnv(df=train_features, prices=prices_train, window_size=CONV_WIDTH, fee=exchange.get_fee)
              │   └─ eval_env=Monitor(MyRLEnv(test…)) + MaskableEvalCallback(存 best_model.zip)
              └─ ReinforcementLearner.fit()                  prediction_models/ReinforcementLearner.py:47
                  ├─ total_timesteps = train_cycles × len(train_features)
                  └─ PPO(policy_type, env, tensorboard_log=…).learn()
         → predict()                                         RL/BaseReinforcementLearningModel.py:252
             ├─ drop_ohlc_from_df → feature_pipeline.transform
             └─ rl_model_predict(): output.rolling(CONV_WIDTH).apply(model.predict) :280
                 → 每行写入 &-action(预测窗口【含当前行】)
         → dk.get_predictions_to_append() + save_backtesting_prediction()
 → 策略回到 dataframe: &-action / do_predict 列
 → populate_entry_trend: do_predict==1 且 &-action==1 → enter_long=1
 → Freqtrade 回测引擎: 信号 shift(1) → 下一根 K 线 open 成交
    (optimize/backtesting.py:551-568, 1148-1162)
```

训练环境内部(step 一步,Base3ActionRLEnv.py:30-110):
`_current_tick += 1` → 判 `_end_tick` 终止 → `_update_unrealized_total_profit()` →
`calculate_reward(action)`(**此时仓位仍是转换前**)→ `is_tradesignal()` 则转换仓位
(Sell in long-only → `_update_total_profit()` 实现)→ 回撤检查 → info/observation。

## 9. 三动作 long-only 状态机(§14)

动作枚举(Base3ActionRLEnv.py:12-15):`Neutral=0, Buy=1, Sell=2`;
位置枚举(BaseEnvironment.py:31-34):`Short=0, Long=1, Neutral=0.5`。

| 初始仓位 | 动作 | _is_valid | is_tradesignal | 结果 | 费用 | 奖励(官方3ac) | 实验 |
|---|---|---|---|---|---|---|---|
| 空 | 0 保持 | ✓ | ✗ | 无变化 | 无 | −1 | t1 |
| 空 | 1 进入 | ✓ | ✓ | →Long,记 _last_trade_tick | 无(开仓不即时扣费,费在 PnL 公式内) | +25 | t2/t3 |
| 空 | 2 退出 | ✗(long-only) | ✗ | 无变化,**时间照常推进** | 无 | −2 | t5(−2/步) |
| 多 | 0 保持 | ✓ | ✗ | 无变化 | 无 | −1×duration/max_dur | t2 |
| 多 | 1 再进入 | ✓ | ✗(3Ac 中 Buy-while-Long 非 tradesignal) | 无变化,无费用 | 无 | −1×duration/max_dur | t4(与 t2 轨迹相同) |
| 多 | 2 退出 | ✓ | ✓ | `_update_total_profit()` 实现 → 空 | 退出费在 PnL 公式 | pnl 放大系(×100~300) | t3/t6 |

要点【源码确认+实验确认】:
- 无效动作(空仓 Exit)**照常推进时间并获得 −2 奖励,但不产生任何费用**;
- 奖励在**仓位转换之前**计算(step 第 49 行在 53-71 行之前)——Exit 的奖励
  读取的 pnl 是"以当前 open 估值的未实现利润",随后才落地实现;
- 开仓无即时费用;费用完全体现在 `get_unrealized_profit()` 的进/出价调整中。

## 10. observation 与 action 时间线(§15)——核心差异

**训练环境**(BaseEnvironment.py:253-260 + Base3ActionRLEnv.py:43):

```text
reset(): _current_tick = _start_tick = window_size
obs_t = signal_features[_current_tick − window_size : _current_tick]   ← 不含当前 tick
agent 依 obs 选动作 a
step(a): _current_tick += 1 → 执行价 = open[_current_tick]
```
即:决策信息末行 = 行 t,动作执行价 = **open[t+2]**(reset 后第一步就从
_start_tick+1 开始执行,跳过了 _start_tick 行)。实验:obs 末行 = 行 0(00:00),
Enter 成交在 open[2](02:00)。【实验确认,4 条 synthetic trace 一致】

**历史推理/回测**(BaseReinforcementLearningModel.py:291-303 +
backtesting.py:551-568):
```text
rolling(CONV_WIDTH) 窗口【含当前行 t】→ &-action 写在行 t
→ 回测引擎 shift(1) → 成交价 = open[t+1]
```
即:决策信息末行 = 行 t,成交价 = open[t+1]。

**结论:同一信息集下,训练环境的动作比回测器晚一根 K 线执行
(训练 gap=2,推理/回测 gap=1)。**这是结构性的(由 step 先自增与
rolling 含当前行共同造成),不修改核心源码无法消除。
当前 K 线完整性:两侧特征都只用到已收盘 K 线;MinMaxScaler 仅在训练窗拟合
(freqai_interface.py:559-587),无未来数据泄漏。randomize_starting_position
只改 _start_tick,不改变 gap 结构。【源码确认+实验确认】

## 11. 价格与成交语义(§15)

- RL 环境成交价:`current_price()` = `prices.iloc[_current_tick].open`
  (BaseEnvironment.py:375-376);开仓与退出价都取执行 tick 的 **open**。
- 观察中的价格:raw OHLC 以 `%-raw_*` 特征进入(可选保留在 observation 中,
  drop_ohlc_from_features=false 时),经 MinMaxScaler 缩放。
- 同一价格既作为观察信息又作为立即成交价格的情况:训练环境**不存在**
  (观察行与执行行相差 2);推理/回测侧,rolling 窗含行 t 而成交在 open[t+1],
  也**不存在**"看到当根 open 即刻成交"的前视。
- 但注意 §10 的错位使**训练时学到的"动作→价格后果"映射比回测/实盘晚一根**,
  在波动市场上产生系统性偏差(锯齿实验中方向相反)。
- Freqtrade 回测成交:entry 默认 `row[OPEN_IDX]`(backtesting.py:1148-1162),
  exit 市价单同样按下一根 open(可用 timeframe_detail 细化,本审计未启用)。

最终时间线(以审计结果为准):

```text
特征可见(行 t 收盘后) → agent action(训练:obs 末行 t,推理:&-action 在行 t)
→ RL env 价格: open[t+2](训练) / open[t+1](推理)
→ reward: 训练环境在动作执行 tick 用 open 计价
→ Freqtrade signal: enter/exit_long 写在行 t(推理路径)
→ Freqtrade fill: open[t+1]
```

## 12. 手续费与盈亏公式(§16)

RL 环境(BaseEnvironment.py:285-326):

```text
add_entry_fee(p) = p × (1 + fee)
add_exit_fee(p)  = p / (1 + fee)
Long 未实现 PnL = (open[t]/(1+fee) − open[e]×(1+fee)) / (open[e]×(1+fee))
退出实现: total_profit += pnl(stake_amount≠"unlimited", 不复利)
                或 total_profit ×= (1+pnl)(stake_amount=="unlimited", 复利)
```

- fee 来源:`config["fee"]` 优先(BaseEnvironment.py:86-89),否则
  `data_provider._exchange.get_fee()`(BaseReinforcementLearningModel.py:200-203)。
  本审计 config fee=0.001 生效(回测日志 "Using fee 0.1000% from config")。
  【实验确认】
- 持仓中的未实现 PnL **已含预估退出费**(公式右端除以 (1+fee))。
- 空仓动作、无效动作:**零费用**(状态机不触发任何价格调整)。
- episode 结束未平仓:**不强制平仓、不扣退出费、未实现盈亏不进 total_profit**
  (仅用于回撤监控 _total_unrealized_profit)。
- 滑点/价差/深度:**未实现**(环境内价格唯一来源是 open 列,无任何 spread 模型)。
- 回测器费率:set_fee 同样 config 优先,否则 max(taker, maker)
  (backtesting.py:268-281);盈亏在 trade.calc_profit_ratio 中以另一套公式
  (买卖双边各扣 fee)计算——与 RL 环境的 (1+f)/(1/(1+f)) 模型数值相近但
  不完全相同(锯齿实验:RL −0.11288623 vs 回测 −0.11288711,差 ~9e-7)。【实验确认】

手算对照(与 CSV 逐项吻合,误差 <1e-9):
- 恒定 100 开平,fee=0.001:(100/1.001 − 100×1.001)/(100×1.001) = −0.0019975,
  CSV total_profit = 0.998003;
- 上涨 121→146.41:+0.207584(total 1.207584);下跌 81→65.61:−0.191618;
- fee=0 与 0.001 的差:恒定价格一笔完整开平 ≈ −2×fee = −0.2%。

## 13. 奖励函数审计(§17)

官方默认奖励(ReinforcementLearner.py:112-171 与
ReinforcementLearner_test_3ac.py:28-71,后者是本审计 3ac 路径实际使用的):

| 情形 | 奖励 |
|---|---|
| _is_valid == False(如空仓 Sell) | −2 |
| 空仓 Enter | +25(立即、无条件) |
| 空仓 Hold | −1 |
| 持仓 Hold(或持仓中重复 Enter) | −1 × trade_duration / max_trade_duration_candles |
| 持仓 Exit | sign(pnl)×(pnl+1) × 100 × {1.5 if dur≤max else 0.5} × {2 if pnl>profit_aim×rr}(3ac 版;官方 5Ac 版为 pnl×factor) |
| 其他 | 0 |

- 奖励在**每一步**计算(不只交易步)。
- **reward ≠ 净值变化**:数值与量纲均脱钩。实验:恒定价格 fee=0 下
  反复开平 14 次,total_reward=+350(全部来自 Enter+25),真实净值变化为 0;
  rising 一笔 +20.76% 的交易 reward=+362.3;constant 一笔 −0.1997% 的交易
  reward=−149.7(放大 150 倍且因 (pnl+1) 项在亏损时趋近 −1 而饱和)。【实验确认】
- total_reward 与 total_profit 方向相反完全可能(rising t7:reward 23.7 正,
  但若在下跌段同样持仓 reward 同为正奖励结构…;direct 证据:zigzag t3
  Enter +25 高奖励而交易实际 −11.29%)。
- 刷分路径已实证:在零收益价格上高频开平即可刷高 reward(t6)。
- `profit_aim`/`rr` 只影响 Exit 奖励的 ×2 阈值;`max_trade_duration_candles`
  影响 factor(1.5/0.5)与持仓惩罚斜率。
- 奖励接口能力评估:calculate_reward 内可访问 get_unrealized_profit()(含费
  预估)、_total_profit、trade_duration、position、raw_features 任意特征列
  (BaseReinforcementLearningModel.py:409-481 的 RSI 示范)。
  **"逐步扣费后的净值型奖励"原则上可以表达**(自算 equity 曲线),
  但拿到的是 open 计价 + 训练 gap=2 的净值(§10),且接口无法改变执行时机。
  【源码确认+合理推断】

## 14. episode 与 reset 审计(§18)

- `_start_tick = window_size`;`_end_tick = len(prices) − 1`(BaseEnvironment.py:139-140)。
- reset 后(实验快照):position=Neutral、_last_trade_tick=None、
  total_profit=1.0、total_reward=0、trade_history=[]、_total_unrealized_profit=1;
  下一 episode 不继承任何交易状态。【实验确认】
- terminated 触发:(a) `_current_tick == _end_tick`(数据末尾);
  (b) `_total_profit < 1−max_training_drawdown_pct` 或
  `_total_unrealized_profit < 同阈值`。truncated 恒为 False(硬编码,
  Base3ActionRLEnv.py:106)。
- 回撤终止实验:falling 序列 t7 在 tick 9(unrealized=−0.5227 < −0.5 阈值)
  提前 terminated,而非数据末尾。【实验确认】
- **episode 结束持有多头**:不执行退出、不扣退出费、未实现盈亏不进
  total_profit(t7:结束时 unrealized −11.3% 而 total_profit 仍为 1.0);
  PPO 的 eval callback 也只按 episode reward 选 best_model,不看持仓。
  【源码确认+实验确认】
- randomize_starting_position=true 时 _start_tick = random(window_size+1,
  end/4)(BaseEnvironment.py:221-225),实验 seed 1/2/3 得到不同起点;
  会缩短可用窗口并改变预热语义(观察窗仍完整,但可用步数变少)。

## 15. state info 审计(§19)

- `add_state_info=true` 时 observation 追加 3 列:current_profit_pct、
  position(Neutral=0.5/Long=1/Short=0)、trade_duration
  (BaseEnvironment.py:130-136, 261-274)。
- **回测/训练时直接抛
  `OperationalException: add_state_info is not available in backtesting`
  (BaseEnvironment.py:96-101)**——本任务实验精确复现该异常。【实验确认】
- 仅 live(Dry-run/实盘)可用:predict 时由 get_state_info() 从 Trade 表读取
  真实仓位/利润/时长注入(BaseReinforcementLearningModel.py:216-250, 293-297)。
- 后果:若启用,训练(回测)与 Dry-run 形状不同且训练根本无法进行;
  本审计目标配置 `add_state_info=false, continual_learning=false` **合理且必要**。
  continual_learning=false 意味着每窗从头训练——与回测缓存/重载机制兼容性最好。

## 16. 人工价格序列与固定动作实验(§20-21)

产物:4 序列 × 2 费率 × 7 脚本,共 8 个 CSV(规范名 4 个为 fee=0.001 版),
196 行/序列(falling 因回撤终止提前至 118 行)。全部手算吻合(§12)。
代表性结果(fee=0.001):

| 脚本 | constant | rising | falling | zigzag |
|---|---|---|---|---|
| t1 全程保持 | profit 1.0,reward −28 | 1.0 / −28 | 1.0 / −28 | 1.0 / −28 |
| t2 进入后持有到尾 | 1.0 / +23.74,终仓 Long | 1.0 / +23.74(unreal +1208%!) | tick9 回撤终止 | 1.0 / +23.74 |
| t3 开-持1-平 | **0.998003 / −0.003** | 1.207584 / +362.28 | 0.808382 / −121.26 | 0.887114 / −133.07 |
| t4 重复进入 | 与 t2 完全相同(无效,零费用) | 同左 | 同左 | 同左 |
| t5 空仓重复退出 | 1.0 / −56(−2×28,零费用) | 1.0 / −56 | 1.0 / −56 | 1.0 / −56 |
| t6 每隔一根开平 | fee=0:reward **+350**(14×25) | — | — | — |
| t7 持有到 episode 结束 | 1.0(Long 未平) | 1.0(unreal +1208% 不入账) | 回撤终止 | 1.0 |

## 17. RL 环境与 Freqtrade 回测器对比(§22)

同锯齿数据(00:00=100,01:00=110,02:00=90,03:00=120,04:00=80),fee=0.001,stake=100:

| 路径 | 信号/观察行 | 成交(Entry→Exit) | profit_ratio |
|---|---|---|---|
| RL 三动作环境 | 行 0(00:00) | open[2]=90 → open[4]=80 | **−0.11288623** |
| 回测器·同信息集(FixedSignalA,信号行 0) | 行 0(00:00) | open[1]=110 → open[3]=120 | **+0.08872945** |
| 回测器·信号提前一根(FixedSignalB,信号行 1) | 行 1(01:00) | open[2]=90 → open[4]=80 | **−0.11288711** |

- 回测侧通过真实 `Backtesting.start()` 执行(虚拟市场以测试级 monkeypatch 注入,
  未修改上游源码);exit_reason=exit_signal。
- FixedSignalB 与 RL 环境成交价完全一致,profit 差 8.8e-7 来自两侧费用公式差异。

训练环境与回测器差异表:

| 维度 | RL 训练环境 | Freqtrade 回测器 |
|---|---|---|
| 价格 | 执行 tick 的 open(观察+2 根) | 信号次根 open(shift(1),观察+1 根) |
| 时间延迟 | gap=2 | gap=1 |
| 手续费 | (1+f) / 1/(1+f) 双边进 PnL 公式 | trade.calc_profit_ratio 双边扣费(公式略异,~1e-6 差) |
| 滑点 | 无 | 无(默认) |
| 未实现盈亏 | 实时计算(open 计价),仅监控回撤 | 逐 K 线按 close 估值展示 |
| 平仓 | 仅 Sell 动作 | exit_signal/ROI/stoploss/custom_exit |
| episode 结束 | 不平仓、不入账 | handle_left_open 强制按最后可得价格估值平仓 |
| stoploss/ROI/custom_exit | 无(文档明示 env 不含这些) | 全部可用 |
| 杠杆 | 无 | 配置可用(spot 为 1) |
| state info | 仅 live 可用 | 回测不可用(报错) |
| 仓位规模 | 单位 1(stake 语义仅区分复利与否) | 钱包/可用余额/最小交易量约束 |
| compounding | stake_amount=="unlimited" 时复利 | 按钱包实际复利 |

## 18. 上游测试(§23)

命令:`python -m pytest tests/freqai/test_freqai_interface.py -k "ReinforcementLearner or get_state_info" -v`
结果:**8 passed, 0 failed, 0 skipped,154.84s**。

覆盖了:训练管线可跑通并保存 zip(RL/RL_multiproc/3ac×2/4ac 参数化,含 SVM/DI/
shuffle 被 RL 守卫自动关闭的路径)、FreqAI RL 回测滑窗产出预测文件(3 个)、
live 模式 get_state_info 的仓位/利润/时长读取与无 exchange 错误分支。
**未覆盖**(由本任务人工实验补齐):obs/执行错位、费用与 PnL 数值、训练/回测
一致性、episode 未平仓处理、奖励与净值关系。【实验确认】

## 19. lookahead / recursive 检查(§24)

- `freqtrade lookahead-analysis --help` / `recursive-analysis --help` 均存在。
- **重要副作用发现【源码确认+实验确认】**:两个分析工具的 `prepare_data()` 会对
  freqai identifier 的模型目录**整目录 rmtree 后重训**
  (optimize/analysis/lookahead.py:98-108、recursive.py:125-135,注释明示
  "to be sure nothing is carried over from older backtests")。本任务在
  recursive-analysis 运行时,审计 identifier 下的 5 个 sub-train 模型、
  TensorBoard event 与预测缓存被其清空并替换为单窗口重训结果
  (删除前全部 47 个文件的完整 SHA-256 已存档于
  artifacts/.../reload_baseline_after_run1.json;随后已重跑首跑命令重建,
  重建后回测结果与首跑一致 7 trades/−2.13%)。**与 FreqAI 组合使用这两个
  工具前必须备份/换 identifier。**
- lookahead-analysis 首次运行被配置校验拦截:`Market entry orders require
  entry_pricing.price_side = "other"`(本审计配置为 "same")。
- 修正配置(price_side=other)后前台运行 3 天区间(20260601-20260603):
  **成功运行,47s,退出码 0**;但 "found 3 trades which is less than
  minimum_trade_amount 10. Cancelling this backtest lookahead bias test"
  ——信号数低于工具自身 10 笔门槛,测试被主动取消,导出 json 生成。
  **该结果为"未判定",不能证明无偏差**;要真正执行需 ≥10 笔交易的区间,
  且每轮会触发模型目录清空与重训,成本与破坏性都需要纳入考量。
- recursive-analysis 实际运行成功(125s):"No variance on indicator(s) found due
  to recursive formula"(无递归偏差);同时报告 "found lookahead in indicator
  &-action / do_predict"。
- 解读限制:该检查把 &-action 当普通指标,比较不同数据截断下同日期的值。
  FreqAI 模型随窗口重训练,值变化是"重训敏感性"而非必然的未来数据使用;
  此结果**不能证明存在真前视**,但确实表明历史 &-action 不可复现,
  且 FreqAI 官方 lookahead 工具对本用例的解释力有限。【实验确认+合理推断】

## 20. 已确认差异(汇总)

1. 训练环境动作比同信息集回测信号晚一根执行(gap 2 vs 1)——结构性,核心源码级。
2. 官方 5Ac 环境不尊重 can_short,spot 下训练出 Short_enter 动作被回测静默丢弃。
3. 奖励与净值脱钩(开仓+25/空仓−1/Exit 放大 100~300 倍/零收益刷分+350)。
4. episode 结束不强制平仓、未实现盈亏不入账(total_profit 高估)。
5. 环境无滑点/价差/深度;费用模型与回测器公式略异(~1e-6)。
6. add_state_info 回测不可用(硬报错)——训练/回测/live 不对称的官方限制。
7. 预测缓存按"文件名+行数"判定,跨策略/奖励/seed 静默复用风险。
8. 回撤终止以未实现口径参与判断,训练可能频繁提前终止(falling t7)。
9. lookahead-analysis / recursive-analysis 对 freqai identifier 模型目录有
   整目录删除副作用(prepare_data rmtree),与 FreqAI 组合具有破坏性。

## 21. 未解决问题

- PPO 每窗仅 482 timesteps(train_cycles=1),训练质量未评估(超出本任务范围)。
- lookahead-analysis 在信号数 ≥10 的区间上的完整判定(本次 3 天区间信号不足
  被工具取消;且该工具对 FreqAI identifier 有整目录删除副作用,见 §19)。
- 回测器与 RL 环境费用公式的解析级差异(数值差 ~9e-7)未逐项推导。
- TensorBoard 无 train/ 标量(verbose=0 所致);如需 loss 曲线应设 verbose=1。
- 3ac 动作分布显示 agent 近乎恒输出 Buy(160/168)——低训练量 + 奖励形状
  (Enter+25)所致,是否可通过奖励设计改善未验证(超出范围)。

## 22. 路线建议依据(§25)

### 推荐路线 B,理由

1. **训练/回测错位无法在不修改上游核心的情况下修正**:错位源于
   `BaseEnvironment._get_observation` 的 `[t−w, t)` 半开区间与 `step()` 先自增、
   以及 `rl_model_predict` rolling 含当前行的组合;任何一侧语义改动都落在
   核心仓库(持续维护 fork 的成本),不符合"只通过 user_data 扩展"的边界。
2. **奖励接口拿不到正确计价的净值**:可拿到 open 计价、gap=2 的未实现 PnL;
   逐步扣费净值需要环境本身改变成交/记账时序。
3. **原生环境无滑点/价差/深度**,且加滑点同样需要改核心环境。
4. **episode 未平仓不入账**使训练期收益信号失真(t7 类情形)。
5. **state info 的训练/回测/live 不对称**是官方硬限制。
6. 目标模型的"保持/进多/退多"三动作语义本身在 3Ac 可表达(状态机干净),
   但上述 1-5 使"训练所学"与"回测/实盘所执行"系统性不同。

### 路线 B 的边界

```text
Freqtrade:数据下载与管理、正式回测、Dry-run、未来实盘、(FreqAI 滑窗重训与模型管理可继续参考)
自定义 Gymnasium 环境:状态、动作、费用、滑点、奖励、episode、净值核算
```

### 若仍选路线 A 的最低自定义清单(不推荐但可行)

- user_data/freqaimodels 自定义模型(MyRLEnv=Base3ActionRLEnv)+ 自定义奖励
  (净值型,自算 equity);
- 必须接受的补偿/风险:训练 gap=2 与推理 gap=1 的错位(可在**特征层**
  人为 shift 一定程度的对冲,但无法根除)、episode 未平仓失真、无滑点、
  缓存复用纪律(每实验清 backtesting_predictions)、add_state_info 永远 false。

## 23. 下一阶段最小建议

1. 以本审计的 synthetic harness(tests/freqai_rl_platform_audit/)为模板,
   先在**独立 Gymnasium 环境**内实现净值型奖励 + gap=1 语义 + 可控滑点,
   复用其固定动作 CSV 回归测试;
2. Freqtrade 侧继续用本 3ac 审计组合做端到端联调(数据/回测/导出已验证);
3. 任何新奖励先过四序列×七动作回归(恒定/上涨/下跌/锯齿),要求手算逐项吻合;
4. 保持 identifier 纪律:每次策略/奖励/seed 变更换新 identifier 或清缓存。

## 24. 复现命令

```bash
wsl -d CryptoRL-Ubuntu-24.04
source ~/projects/crypto_rl/activate-freqtrade.sh
source ~/projects/crypto_rl/scripts/proxy-on.sh   # 需要网络时

# 预检查/数据
bash tests/freqai_rl_platform_audit/00_precheck.sh   # (脚本在 logs 目录有对应实现)
freqtrade download-data --exchange binanceus --pairs BTC/USDT --timeframes 1h \
  --timerange 20260401-20260701 --userdir ~/projects/crypto_rl/user_data \
  --config experiments/freqai_rl_platform_audit/configs/config_download_binanceus.json

# 官方 5ac 路径 / 3ac 审计路径
freqtrade backtesting --config experiments/freqai_rl_platform_audit/configs/config_freqai-rl-platform-audit-2026-7-official5ac.json \
  --userdir ~/projects/crypto_rl/user_data --strategy OfficialRLStrategy5ac \
  --freqaimodel ReinforcementLearner --timerange 20260601-20260701 --cache none --export trades
freqtrade backtesting --config experiments/freqai_rl_platform_audit/configs/config_freqai-rl-platform-audit-2026-7.json \
  --userdir ~/projects/crypto_rl/user_data --strategy AuditLongOnlyRLStrategy \
  --freqaimodel AuditBase3RLModel --timerange 20260601-20260701 --cache none --export trades

# 阶段二核心实验
python tests/freqai_rl_platform_audit/synthetic_env_audit.py     # 4序列×2费率×7动作 CSV
python tests/freqai_rl_platform_audit/env_vs_backtest.py         # RL env vs 回测器
python tests/freqai_rl_platform_audit/stateinfo_lookahead.sh     # add_state_info 报错+help
bash    tests/freqai_rl_platform_audit/lookahead_run.sh          # recursive 实跑
cd vendor/freqtrade && python -m pytest tests/freqai/test_freqai_interface.py \
  -k "ReinforcementLearner or get_state_info" -v                  # 上游测试
tensorboard --inspect --logdir ~/projects/crypto_rl/user_data/models/freqai-rl-platform-audit-2026-7/tensorboard
```

## 25. 关键附件索引

| 附件 | 内容 |
|---|---|
| artifacts/freqai_rl_platform_audit/source_map.md | 源码地图(20 条结论+行号) |
| artifacts/.../data_quality_summary.md/.json | 数据质检 |
| artifacts/.../exchange_connectivity.txt | 交易所连通性矩阵 |
| artifacts/.../stage1_first_run_summary.md + action_stats.json | 官方 5ac 首跑产物清单+动作分布 |
| artifacts/.../stage1_audit3ac_run1_summary.md + action_stats.json | 3ac 首跑 |
| artifacts/.../reload_baseline_after_run1.json / reload_snapshot_run2.json / run3.json | 重载三分支文件级证据 |
| artifacts/.../synthetic_{constant,rising,falling,zigzag}_trace.csv(+_fee0 版) | 固定动作逐步 trace |
| artifacts/.../synthetic_summary.md | 汇总+reset 快照+随机起点+手算 |
| artifacts/.../env_vs_backtester_comparison.md | RL vs 回测器对比 |
| artifacts/.../tensorboard_tags.txt | event 文件与 tag |
| artifacts/.../lookahead_analysis_result.json | lookahead 导出(如生成) |
| logs/freqai_rl_platform_audit/*.log | 全部命令日志(00-11b) |
| tests/freqai_rl_platform_audit/*.py | 可重复实验脚本 |
| experiments/freqai_rl_platform_audit/configs/*.json | 全部配置 |
