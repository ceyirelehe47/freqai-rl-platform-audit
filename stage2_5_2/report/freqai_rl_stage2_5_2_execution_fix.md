# 阶段 2.5.2:Route C 实时执行状态与完整成交语义修复

- 日期:2026-08-25(UTC)
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / 项目 ~/projects/crypto_rl
- 上游:Freqtrade tag 2026.7,commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(零修改,始/终 clean)
- 判定:**PASS**(二十一节 27 项条件全部满足;详见第三节对表)
- 结论:**允许进入阶段 2.6**(未开始;阶段 2.6 人工课程训练不在本阶段范围)

---

## 一、执行摘要

阶段 2.5.1 的七个加固点全部通过,但遗留四类未闭环问题:live 策略扫描整段
历史目标生成信号;`Trade.is_open` 被直接当作多头(无法识别零成交挂单、部分
成交与待退出订单);窄 K 线下环境与回测器交易数不一致(只比较了成交子集);
缓存 COMPLETE 只校验文件名与行数。

本阶段完成六个工作包:

- **A 执行状态解析器**(`src/rl_platform/execution_state.py`):从真实
  Trade/Order 状态解析 FLAT / PENDING_ENTRY / PARTIAL_ENTRY / LONG /
  PENDING_EXIT / PARTIAL_EXIT / INCONSISTENT 七态;实际暴露按源码语义
  (trade.amount 只汇总已关闭订单,活动订单的部分成交从 Order.filled
  单独累计);INCONSISTENT 一律 fail closed。
- **B Live 只处理最新一行**:历史/回填行一律无信号;最新行由
  [真实执行状态 + 最新目标 + 最新 do_predict + 活动订单] 生成交易意图;
  同方向挂单不重复下单;挂单期间目标反转通过官方
  `adjust_entry_price/adjust_exit_price` 返回 None 取消(不删除数据库
  Order,同一 heartbeat 不生成反向订单);do_predict != 1 不产生任何
  订单变化;backtest 与 live 双路径分开实现,populate 幂等。
- **C 真实订单生命周期**:FreqtradeBot 级集成 harness(Fake Exchange 只
  替代外部交易所),链路 `RouteCModel.rl_model_predict -> 策略
  populate_* -> FreqtradeBot.process -> create/fetch/cancel_order ->
  Trade/Order 持久层 -> 下一 heartbeat`;任务书十二节 12 个场景全部
  通过,订单状态变化全部走官方 update_trade_state / handle_cancel_order /
  adjust_order_price 路径。
- **D bar 内一 tick 执行合同**:环境与策略共用
  `price_clamp.bar_executable_price`(请求滑点价触及当根 high/low 时按
  tick 向 bar 内移动一格,bar 容纳不下时 fallback open,输出规范化到与
  price_to_precision 十进制往返一致的浮点);七轮 parity(含窄 K 线两轮
  与零振幅一轮)信号数/订单数/交易数/时间/价格/单笔收益逐笔一致,
  不再比较成交子集;并对阶段 2.5.1 窄 K 线不一致给出更正后的根因诊断。
- **E 缓存内容验证**(`src/rl_platform/cache_content.py`):每文件记录
  sha256/行数/首末时间戳/完整日期序列哈希/目标列与 do_predict 列哈希,
  绑定实验指纹;启动前内容级校验,任何不符即 INCONSISTENT 默认中止;
  七类损坏场景全部 fail closed。
- **F 代码清理**:ScriptedPolicy.save 重复定义删除;live/backtest 状态
  变量语义限定(_last_target_position 仅 backtest 跨窗口);废除
  Trade.is_open 直接推导持仓的全部旧入口与 live 整段扫描旧路径;
  2.5.2 实验目录纳入代码树指纹。

测试:阶段 2.5 38 项 + 阶段 2.5.1 74 项 + 阶段 2.5.2 新增 78 项,共 190 项
全部通过(旧测试仅按任务书十八节规则更新 1 个文件的建模方式,见第五节);
PPO 回归烟雾三轮(全新/缓存复用/模型重载)全部通过。

## 二、PASS / FAIL

**PASS。** 二十一节 27 项条件逐项对表见下节;二十二节 FAIL 条件无一触发。

## 三、二十一节 PASS 条件对表

| # | 条件 | 结果 | 证据 |
|---|---|---|---|
| 1 | Freqtrade 上游零修改 | ✅ 始/终 clean,tag 2026.7/52bc96f | upstream_integrity.txt |
| 2 | 不再用 Trade.is_open 直接表示实际多头 | ✅ dryrun_state 委托 execution_state;resolve_initial_position 兼容入口同样按七态映射 | execution_state.py;test_dryrun_init 回归通过 |
| 3 | 零成交 pending entry 识别为无实际暴露 | ✅ PENDING_ENTRY,模型观察 0 | test_execution_state_resolver;场景 2 |
| 4 | 部分 entry 识别为有暴露+活动 entry | ✅ PARTIAL_ENTRY,模型观察 1 | 场景 3;partial_entry_trace.csv |
| 5 | pending exit 保持实际多头暴露 | ✅ PENDING_EXIT,暴露=trade.amount | 场景 6 |
| 6 | 冲突订单 fail closed | ✅ INCONSISTENT:不生成订单+完整诊断+无静默选择 | resolver 四类冲突用例 |
| 7 | Live 只在最新一行生成信号 | ✅ 历史/回填行 enter=exit=0 | test_history_rows_never_signal |
| 8 | 历史回填行全部无交易信号 | ✅ 100 行历史前 99 行无信号 | 场景 1 |
| 9 | 同方向 pending 不产生重复订单 | ✅ 信号层 hold_pending_*;bot 层 pair 白名单移除+similar order 双保险 | 场景 2/6/7 |
| 10 | pending entry 目标反转安全取消 | ✅ adjust_entry_price->None 官方路径;零成交删 trade/部分成交保留暴露 | 场景 10/10b;target_reversal_cancel_trace.csv |
| 11 | pending exit 目标反转安全取消 | ✅ adjust_exit_price->None;取消后保持 LONG | 场景 11 |
| 12 | 零成交 rejected/expired 后状态正确恢复 | ✅ 恢复 FLAT(trade 删除),下一有效 heartbeat 可重入 | 场景 9/9b;pending_entry_trace.csv |
| 13 | 部分成交金额走官方订单更新路径 | ✅ fetch 脚本驱动 update_trade_state->update_order->recalc;测试无 Trade.amount 手工篡改 | 场景 3/7 |
| 14 | 进程重启可从数据库恢复 | ✅ 五状态(PENDING_ENTRY/PARTIAL_ENTRY/LONG/PENDING_EXIT/PARTIAL_EXIT)新实例恢复一致 | 场景 12;restart_recovery_trace.csv |
| 15 | 完整 FreqAI->Strategy->FreqtradeBot->Order/Trade 链路 | ✅ 真实 rl_model_predict+真实策略+真实 FreqtradeBot+Fake Exchange+文件 SQLite | freqtradebot_full_chain.md |
| 16 | do_predict=0/2 不产生订单变化 | ✅ 不生成新订单、不取消既有订单 | 链路测试 test_do_predict_invalid |
| 17 | 窄 K 线下完整交易数一致 | ✅ 窄轮 17==17==17(信号/环境/回测) | narrow_bar_full_parity.json |
| 18 | 不再只比较成交子集 | ✅ compare_round 断言全路径相等 | test_full_fill_parity.py |
| 19 | 0/5/10bps 完整路径一致 | ✅ 七轮逐笔一致 | full_fill_parity.md |
| 20 | 缓存内容/日期/哈希得到校验 | ✅ 双层守卫(名称行数+内容级) | cache_content.py;cache_content_manifest.json |
| 21 | 错误缓存启动前中止 | ✅ 7 类损坏场景全部 INCONSISTENT 中止(退出码 3) | cache_corruption_tests.json |
| 22 | 旧 112 项测试全部通过 | ✅ 38+74 全过(1 个文件按规则更新) | regression_test_summary.md |
| 23 | 新测试全部通过 | ✅ 78 项 | 同上 |
| 24 | PPO 回归烟雾通过 | ✅ 三轮:预算 512/512×5 窗、720 动作无 NaN、复用复现 2 笔交易、重载 0 训练动作一致 | ppo_regression_smoke.json |
| 25 | 上游仓库最终 clean | ✅ | upstream_integrity.txt |

(表中 25 行对应任务书二十一节的 25 个分号项;全部满足。)

## 四、Trade/Order 状态解析依据(固定源码)

- `freqtradebot.execute_entry`(freqtradebot.py:884-):限价单在下单当刻
  创建 `Trade(amount=0, is_open=True)`;`order_status=="open"` 时无成交。
- `trade_model.recalc_trade_from_orders`(trade_model.py:1261-):
  `if o.ft_is_open or not o.filled: continue` —— **活动订单上的部分成交
  不计入 trade.amount**,必须从 Order.filled 单独累计。
- `LocalTrade.open_orders`(trade_model.py:587):`ft_is_open` 且非 stoploss。
- `Order.safe_filled/safe_remaining/safe_amount`(trade_model.py:131-158);
  `constants.NON_OPEN_EXCHANGE_STATES=(cancelled,canceled,expired,rejected,closed)`。
- `update_trade_state`(freqtradebot.py:2328-)/`update_order`/
  `handle_cancel_enter/exit`(1867/1958):官方订单状态同步与取消路径;
  零成交入场取消后 `trade.delete()`。
- `manage_open_orders -> replace_order -> strategy.adjust_order_price`
  (freqtradebot.py:1580-1738):官方挂单替换/取消扩展点,回调返回 None
  即「取消且不替换」(interface.py:693/730 文档语义)。
- 回测撮合 `_get_order_filled`(backtesting.py:788):`low <= rate <= high`
  闭区间;入场 `min(rate, high)`、出场 `max(rate, low)` 后
  `price_to_precision`(_exit_trade)。

## 五、实际暴露定义、活动订单定义、仓位映射

见 `artifacts/freqai_rl_stage2_5_2/execution_state_matrix.md`(七态×事实
矩阵、INCONSISTENT 触发条件、模型观察映射);映射规则同时写入实验
manifest(position_mapping 字段)。epsilon:`freqai.route_c.amount_epsilon`
(默认 1e-12)。

## 六、Live 最新行信号逻辑(工作包 B)

双路径(`RouteCStrategy._apply_signals`):

- **live(DRY_RUN/LIVE)**:`latest_row_signals(df, state, target, dp)` ——
  整表清零 enter/exit(幂等,不残留上一 heartbeat),只按最新行写信号;
  规则矩阵:FLAT+1→enter;LONG+0→exit;同方向挂单→hold;反转→本
  heartbeat 无任何新订单(取消由 adjust_* 回调完成);do_predict!=1→
  无信号不取消;INCONSISTENT→无信号。
- **backtest**:`targets_to_signals` 顺序扫描(初始 0,跨窗口状态由模型层
  延续),与 live 完全分开,不靠同一循环兼容。

历史回填:FreqAI 首次传入整段历史时,`live_predict_frame` 用隔离顺序推理器
生成展示目标,执行状态不受影响;最新一行的观察仓位来自执行状态解析
(`get_model_position_live`,七态映射),INCONSISTENT 时 fail closed
(不调用模型,trace 记录)。

## 七至十一、pending entry / partial entry / pending exit / partial exit 生命周期

逐 heartbeat 状态迁移与订单计数见证据:
`pending_entry_trace.csv`(零成交→过期恢复→重入)、
`partial_entry_trace.csv`(40% 成交→反转取消保留暴露→按实际暴露退出)、
`pending_exit_trace.csv`(零成交退出→反转取消保持 LONG)、
`partial_exit_trace.csv`(50% 卖出→补完→FLAT)。
要点:同方向挂单期间绝不重复下单;反转取消后**下一** heartbeat 按实际
暴露决策(部分入场保留暴露→LONG→目标 0 生成按剩余量的 exit)。

## 十二、目标反转与取消

官方扩展点 `adjust_entry_price/adjust_exit_price` 返回 None(上游语义:
取消且不替换)。仅 DRY_RUN/LIVE 生效(回测 dp 无逐行语义,保持基类默认)。
do_predict != 1 时返回 current_order_rate(不因无效预测取消)。取消动作
由 `handle_replace_order -> handle_cancel_enter/exit -> cancel_order_with_result`
完成,零成交且无成交单时上游删除 trade;不直接删除数据库 Order。

## 十三、进程重启恢复

场景 12:五种状态下销毁全部 Python 实例,重建 FreqtradeBot/模型/策略
(同一文件 SQLite),执行状态恢复一致(restart_recovery_trace.csv)。
解析器为纯函数,重启即从 Trade/Order 表重推导,不依赖内存属性。

## 十四、完整 FreqtradeBot 调用链

`artifacts/freqai_rl_stage2_5_2/freqtradebot_full_chain.md` + 
`freqtradebot_full_chain_trace.csv`。Fake Exchange 只替代外部交易所
(脚本化 open/部分成交/全部成交/rejected/expired/cancelled),FreqtradeBot、
Trade、Order、策略生命周期全部真实;每 heartbeat 完整跑
`process()`(analyze→manage_open_orders→exit_positions→enter_positions)。

## 十五、窄 K 线完整 parity(工作包 D)

执行合同(任务书十三节推荐方案,依据固定源码撮合语义):
1. 请求滑点价触及当根 high/low 时,按 tick 整数格向 bar 内部移动一格
   (买入严格小于 high、卖出严格大于 low);
2. bar 范围容纳不下内部价(单 tick/零振幅)时 fallback 为当根 open
   (源码允许边界价且 open∈[low,high] 闭区间恒当根成交);
3. 所有输出价格规范化(round 10 位)到与 price_to_precision 十进制往返
   一致的同一浮点,数据价格同网格(消除 1 ulp 漂移);
4. 环境与 RouteCStrategy 使用同一函数(`bar_executable_price`),
   策略经 populate 阶段缓存的执行 bar OHLC 地图定位当前 bar
   (回测 dp 被防未来切片,不含当前 bar;缓存仅执行模拟用,不向模型
   提供未来特征);live 下定位不到实时 bar 时退回旧 bps 请求价。

七轮(十四节清单)结果(full_fill_parity.md / narrow_bar_full_parity.json):
全部信号数==entry 数==exit 数==完成交易数==环境成交数(17==17==17,
零成交轮为 0==0),entry/exit 时间与价格逐笔一致(同 tick 网格同浮点),
单笔收益一致(≤1e-7),环境终值==逐笔递推 E,回测终值==递推 W
(stake 费差口径 + amount 精度截断预算 5e-6/笔,均为已知闭式口径)。

### 窄 K 线根因诊断(更正阶段 2.5.1 结论)

阶段 2.5.1 把交易数缺口归因于「恰等边界限价卖单不在当根撮合」——**错误**
(源码为闭区间 `low<=rate<=high`)。真实根因(narrow_bar_root_cause.md):
clamp 到边界后 `price_to_precision` 十进制往返产生与数据浮点相差 1 ulp 的
订单价,闭区间判定失败→订单滞留→unfilledtimeout 循环取消/重挂→占位吞掉
后续入场。受控复现:零振幅数据 trade #9 退出单滞留 4 天,吞掉 4 个入场
(13 vs 17 逐笔对应)。执行合同使订单价与边界至少隔一个完整 tick,
消除该病态;fallback 路径订单价与数据边界为同一浮点,按恒等成交。

## 十六、缓存内容校验(工作包 E)

双层守卫:第一层 cache_guard(名称/行数,四态,2.5.1 语义保留);
第二层 cache_content(启动前,仅当第一层 COMPLETE):文件 sha256、
行数、首末时间戳、完整日期序列哈希(与窗口理论序列和 manifest 双核对)、
目标列/do_predict 列哈希、规范化内容哈希、manifest 存在且 identifier/
fingerprint 与当前实验一致。任何不符→INCONSISTENT→默认中止(退出码 3);
--repair-partial-cache 整体 quarantine(移动不删除,保留模型)。
成功运行后生成 `models/<identifier>/cache_content_manifest.json`。
七类损坏场景(目标列修改/日期移动一天/窗口互换/另一 seed/feather 损坏/
manifest 缺失/正确缓存)全部按预期判定(cache_corruption_tests.json)。

### 上游交互发现(记录,非阻塞)

COMPLETE 缓存复用时,上游 `check_if_feature_list_matches_strategy`
(freqai_interface.py:326-337)比较「策略现供特征」与「存盘特征」;
RL 配置 `drop_ohlc_from_features=true` 只在训练侧剔除 %-raw_*,存盘列表
不含它们,而复用检查用策略现供列表(含)→OperationalException。
阶段 2.5.1 未做完整缓存复跑所以未暴露。处理:2.5.2 模板改
`drop_ohlc_from_features=false`(特征列表两侧一致;环境价格提取不受
影响——build_ohlc_price_dataframes 从未 drop 的 df 过滤)。上游零修改。

## 十七、原测试回归与更新说明(任务书十八节)

- 阶段 2.5:38 项全部通过,零修改。
- 阶段 2.5.1:74 项全部通过。其中 `test_live_trade_state_resync.py`
  按十八节规则更新(断言更接近真实 Freqtrade):
  1. 旧断言把「入场挂单零成交」建模为「Trade 表为空」——固定源码
     execute_entry 在下单当刻即创建 amount=0 的 open Trade,建模错误;
     新断言用真实 Order 建模零成交挂单(PENDING_ENTRY),要求**不**重复
     入场(旧断言要求重复 enter=1,与 2.5.2 八节矛盾)。
  2. 旧断言要求零成交退出单期间持续重复 exit 信号;上游
     execute_trade_exit→handle_similar_open_order 对同方向挂单防重复,
     新断言与之对齐(PENDING_EXIT 不重复 exit)。更严格而非放宽。
  3. 其余 5 项(含 FLAT 真入场、LONG 不重复、真值源、滑点配置、trace
     证据)语义保留,经真实 populate 入口驱动(不再调用已废除的私有方法)。
- 阶段 2.5.2 新增:78 项(A/B 单元 45 + 链路 16 + 反转后续 4 + parity 2 +
  缓存内容 10 + 生命周期证据 1)。

## 十八、新测试结果与 PPO 回归烟雾(任务书二十节)

确定性测试通过后运行烟雾(seed42/fee0.001/slip5bps/tick0.01/
conv_width=1/BTCUSDT 1h,真实 PPO):

- 完整指纹→滑窗→PPO→保存→加载→顺序推理→策略→回测链路退出码 0;
- 预算:5 窗全部 base482→rounded512→actual512(rollouts=4,resets=2);
- 720 行动作全部 ∈{0,1},无 NaN(分布 0:212 / 1:508);
- 缓存内容校验 COMPLETE;
- 复跑(缓存完整):名称+内容双层 COMPLETE,交易路径逐字段复现(2 笔),
  0 次新训练;
- 模型重载(删缓存保模型):上游 model_exists 跳过训练,0 次新训练,
  动作逐字段一致。
不评价收益(烟雾 2 笔交易的盈亏与本阶段判定无关)。

## 十九、修改文件清单

新增:
- `src/rl_platform/execution_state.py`(七态解析器)
- `src/rl_platform/cache_content.py`(内容级缓存校验)
- `experiments/freqai_rl_stage2_5_2/`(runner、config_stage252 模板、runtime)
- `tests/freqai_rl_stage2_5_2/`(8 个测试文件 + bot_harness + ppo_smoke,78 项)
- `artifacts/freqai_rl_stage2_5_2/`(18 个证据文件)
- `reports/freqai_rl_stage2_5_2_execution_fix.md`(本报告)

修改(改动前备份于 `backups/stage252_20260825/`):
- `src/rl_platform/dryrun_state.py`(委托执行状态解析器)
- `src/rl_platform/live_inference.py`(fail-closed 语义)
- `src/rl_platform/signal_convert.py`(latest_row_signals live 路径)
- `src/rl_platform/price_clamp.py`(bar_executable_price 执行合同)
- `src/rl_platform/ledger.py`(price_tick 执行合同路径)
- `src/rl_platform/env.py`(price_tick 参数,info 增 moved/fallback)
- `src/rl_platform/inference.py`(删除重复 save)
- `src/rl_platform/fingerprint.py`(代码树纳入 2.5.2 实验目录)
- `user_data/freqaimodels/RouteCModel.py`(tick/epsilon 配置、live 快照)
- `user_data/strategies/RouteCStrategy.py`(双路径信号、adjust 反转取消、
  执行合同价格、执行 bar 缓存)
- `tests/freqai_rl_stage2_5_1/test_live_trade_state_resync.py`(按十八节更新)

## 二十、已知限制(不阻塞阶段 2.6)

1. 零振幅 fallback:bar 无法容纳内部价时按 open 成交(合同允许的显式
   fallback,两侧一致;真实市场 BTC/USDT tick=0.01,单 tick bar 罕见)。
2. live custom 价格退回 bps 公式:实时 ticker 定位不到执行 bar 时
   (live 订单在盘口簿成交,无 bar 语义;Dry-run 链路测试覆盖此路径)。
3. 上游 COMPLETE 缓存复用 + drop_ohlc_from_features=true 的特征校验
   冲突(见十六节;2.5.2 以配置规避,上游零修改)。
4. Fake Exchange 的脚本化订单状态替代真实交易所回包(任务书允许的
   测试级替代;FreqtradeBot/Trade/Order/策略生命周期全部真实)。

## 二十一、是否允许进入阶段 2.6

**允许。** 本阶段判定 PASS;按任务书二十六节,任务结束后停止,
不开始阶段 2.6。

## 二十二、完整复现命令

```bash
# WSL CryptoRL-Ubuntu-24.04,conda freqtrade-rl
source ~/projects/crypto_rl/activate-freqtrade.sh
cd ~/projects/crypto_rl

# 1. 全部确定性测试(190 项)
python -m pytest tests/freqai_rl_stage2_5/ tests/freqai_rl_stage2_5_1/ tests/freqai_rl_stage2_5_2/ \
    --ignore=tests/freqai_rl_stage2_5_2/ppo_smoke.py -q

# 2. PPO 回归烟雾(三轮:全新/缓存复用/模型重载)
source scripts/proxy-on.sh
python tests/freqai_rl_stage2_5_2/ppo_smoke.py

# 3. 单独实验入口
python experiments/freqai_rl_stage2_5_2/run_experiment.py \
    --timerange 20260601-20260701 --seed 42 --fee 0.001 \
    --slippage-bps 5 --price-tick 0.01 --suffix smoke

# 4. 上游完整性
git -C vendor/freqtrade describe --tags --exact-match   # 2026.7
git -C vendor/freqtrade rev-parse HEAD                  # 52bc96f...
git -C vendor/freqtrade status --short                  # 空
```

## 二十三、证据索引(artifacts/freqai_rl_stage2_5_2/)

| 文件 | 内容 |
|---|---|
| execution_state_matrix.md | 七态×事实矩阵/INCONSISTENT 条件/仓位映射 |
| execution_state_trace.csv | 解析器 9 用例状态矩阵 |
| live_latest_row_trace.csv | live 最新行 8 heartbeat 信号意图 |
| pending_entry_trace.csv | 入场挂单→过期恢复→重入 |
| partial_entry_trace.csv | 40% 成交→反转取消→按剩余退出 |
| pending_exit_trace.csv | 退出挂单→反转取消保持 LONG |
| partial_exit_trace.csv | 50% 卖出→补完→FLAT |
| target_reversal_cancel_trace.csv | 入场/退出反转取消全链 |
| restart_recovery_trace.csv | 五状态重启恢复 |
| freqtradebot_full_chain.md/.csv | 完整链路说明+主线路径 trace |
| narrow_bar_full_parity.json | 七轮 parity 汇总(分支计数/终值) |
| full_fill_parity.md | 七轮逐笔对比明细 |
| narrow_bar_root_cause.md | 窄 K 线根因诊断(更正 2.5.1 结论) |
| cache_content_manifest.json | 烟雾缓存内容清单(副本) |
| cache_corruption_tests.json/.csv | 7 类损坏场景判定矩阵 |
| ppo_regression_smoke.json | 烟雾三轮证据 |
| regression_test_summary.md | 190 项回归汇总 |
| upstream_integrity.txt | 上游始/终状态与三条 git 命令输出 |
