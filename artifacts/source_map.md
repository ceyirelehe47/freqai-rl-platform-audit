# FreqAI RL 源码地图(固定版本)

- Freqtrade tag: 2026.7
- Commit: 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5
- 生成时间: 2026-08-25 UTC
- 所有行号均来自该 commit 的工作区文件(cat -n 读取)。

## 文件清单

| 文件 | 关键内容 |
|---|---|
| freqtrade/freqai/RL/BaseEnvironment.py | 通用环境基类:observation/reward 接口/费用函数/利润核算/reset |
| freqtrade/freqai/RL/Base3ActionRLEnv.py | 三动作环境(Neutral=0/Buy=1/Sell=2)与状态机 step() |
| freqtrade/freqai/RL/Base4ActionRLEnv.py | 四动作环境(Neutral=0/Exit=1/Long_enter=2/Short_enter=3) |
| freqtrade/freqai/RL/Base5ActionRLEnv.py | 五动作环境(Neutral=0/Long_enter=1/Long_exit=2/Short_enter=3/Short_exit=4) |
| freqtrade/freqai/RL/BaseReinforcementLearningModel.py | 训练/推理核心:train()/set_train_and_eval_environments()/predict()/rl_model_predict() |
| freqtrade/freqai/prediction_models/ReinforcementLearner.py | 官方默认 RL 模型,内嵌 MyRLEnv(Base5ActionRLEnv) 与默认奖励 |
| freqtrade/freqai/freqai_interface.py | start()/start_backtesting() 滑窗回测循环/模型存在性判断 |
| freqtrade/freqai/data_kitchen.py | 预测缓存(check_if_backtest_prediction_is_valid 等)/模型命名 |
| freqtrade/freqai/data_drawer.py | save_data()/load_data() 模型与元数据持久化 |
| freqtrade/optimize/backtesting.py | 回测引擎:set_fee()/信号 shift(1)/_enter_trade() 成交价 |
| tests/freqai/test_models/ReinforcementLearner_test_3ac.py | 上游三动作测试模型(含奖励函数) |
| tests/strategy/strats/freqai_rl_test_strat.py | 上游 RL 测试策略(&-action→enter_long/exit_long 映射) |
| tests/freqai/conftest.py | make_rl_config():上游认可的 rl_config 最小字段集 |
| docs/freqai-reinforcement-learning.md | RL 官方文档(配置示例、"Not for production"声明) |

## 关键结论(源码级,待实验复核的注明)

1. 官方 ReinforcementLearner.MyRLEnv 继承 **Base5ActionRLEnv**(五动作,含做空),不是三动作。
   - prediction_models/ReinforcementLearner.py:9,106
2. 官方文档示例策略的动作映射是五动作(1=enter_long,2=exit_long,3=enter_short,4=exit_short)。
   - docs/freqai-reinforcement-learning.md:78-99
3. 上游仓库自带三动作 long-only 组合:ReinforcementLearner_test_3ac + freqai_rl_test_strat
   (enter_long=&-action==1, exit_long=&-action==2, can_short=False)。
   - tests/strategy/strats/freqai_rl_test_strat.py:61-85, can_short=False at line 25
4. 默认奖励函数明确标注非生产用途(开仓+25/空仓保持-1/持仓保持随时长线性惩罚/平仓 pnl×100×系数)。
   - prediction_models/ReinforcementLearner.py:112-171
   - docs/freqai-reinforcement-learning.md:138-142
5. step() 顺序:先 _current_tick += 1 → _update_unrealized_total_profit() → calculate_reward()(此时仓位仍是转换前)→ 仓位转换 → 回撤检查 → info/observation。
   - RL/Base3ActionRLEnv.py:42-110
6. observation = signal_features[current_tick - window_size : current_tick],**不含当前 tick 行**。
   - RL/BaseEnvironment.py:253-260
7. 预测时 rl_model_predict 用 rolling(CONV_WIDTH) 窗口,**含当前行**。
   - RL/BaseReinforcementLearningModel.py:280-303
8. RL 环境成交价:current_price() = prices.iloc[_current_tick].open(open 价)。
   - RL/BaseEnvironment.py:375-376
9. 费用公式:add_entry_fee=p*(1+fee), add_exit_fee=p/(1+fee);long PnL=(exit_adj-open_adj)/open_adj。
   - RL/BaseEnvironment.py:294-301, 322-326
10. fee 来源:config["fee"] 优先,否则 data_provider._exchange.get_fee()(取 whitelist[0])。
    - RL/BaseEnvironment.py:86-89; RL/BaseReinforcementLearningModel.py:200-203
11. add_state_info=true 且非 live(回测)→ 直接抛 OperationalException。
    - RL/BaseEnvironment.py:96-101
12. 回测滑窗:优先复用 backtesting_predictions/*.feather(不重载模型);缓存无效时若模型文件存在则 dd.load_data() 重载,否则训练。save_backtest_models 默认 True。
    - freqai_interface.py:329-340, 366-400, 73
13. Freqtrade 回测:信号列 shift(1) 后在下一根 K 线以该 K 线 open 成交;入场价默认 row open。
    - optimize/backtesting.py:551-568, 1148-1162(OPEN_IDX), 1476-1491 注释
14. 回测费率:config["fee"] 优先,否则 max(taker, maker)。
    - optimize/backtesting.py:268-281
15. 特征管道:VarianceThreshold + MinMaxScaler(-1,1),仅在训练窗口拟合;原始 OHLC 以 %-raw_* 列传入环境 prices,并可选从特征中删除(drop_ohlc_from_features)。
    - freqai_interface.py:559-587; RL/BaseReinforcementLearningModel.py:305-375
16. 训练步数:total_timesteps = train_cycles × len(train_features)。
    - prediction_models/ReinforcementLearner.py:56-57
17. 回撤终止:_total_profit 或 _total_unrealized_profit < 1-max_training_drawdown_pct 时 _done=True。
    - RL/Base3ActionRLEnv.py:85-89; RL/BaseEnvironment.py:82
18. 训练环境无滑点/无价差:step 中价格唯一来源是 prices.iloc[tick].open,
    trade_history、get_unrealized_profit、current_price 均如此,无 spread/depth 模型。
    - RL/BaseEnvironment.py:285-303, 375-376
19. 回测器信号 shift(1) 后入场用 row open(HEADERS 不含 volume,
    LONG_IDX=5/enter_long)。
    - optimize/backtesting.py:108-120, 551-568, 1148-1162
20. 有效性判定与 is_tradesignal 是两套逻辑:reward 用 _is_valid()(-2 罚),
    状态机用 is_tradesignal()(决定是否转换仓位/记账)。long-only 下
    Buy-while-Long 在 3Ac 中 is_tradesignal=False → 无状态变化也无费用。
    - RL/Base3ActionRLEnv.py:53-54, 112-140

