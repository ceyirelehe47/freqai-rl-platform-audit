# 回归测试总结(阶段 2.5.1)

- 阶段 2.5 原测试: 38 passed, 3 warnings in 16.37s
- 阶段 2.5.1 新测试: 74 passed, 109 warnings in 31.73s
- 全量混合运行(tests/): 112 passed(含 Backtesting 级用例)

旧测试无删除、无跳过、无断言放宽;仅两处与任务书直接相关的调整:
1. util.make_ohlc 为 K 线提供正负 0.5% 振幅(open/close 不变,净值断言不变)
   —— 工作包 C 的 high/low 价格限制需要非退化 K 线;
2. test_ledger 场景 12 的终端清算断言更新为无滑点口径
   —— 对齐 Freqtrade handle_left_open(任务书十节要求消除训练/回测滑点不一致)。
