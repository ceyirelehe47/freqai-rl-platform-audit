# 回归测试汇总(阶段 2.5.2)

| 套件 | 结果 |
|---|---|
| 阶段 2.5(tests/freqai_rl_stage2_5) | 38 passed |
| 阶段 2.5.1(tests/freqai_rl_stage2_5_1) | 74 passed |
| 阶段 2.5.2(tests/freqai_rl_stage2_5_2) | 78 passed |
| 合计 | **190 passed / 0 failed / 0 skipped** |

命令:

```bash
python -m pytest tests/freqai_rl_stage2_5/ tests/freqai_rl_stage2_5_1/ \
    tests/freqai_rl_stage2_5_2/ --ignore=tests/freqai_rl_stage2_5_2/ppo_smoke.py -q
```

更新说明(任务书十八节):`test_live_trade_state_resync.py` 按规则更新——
旧断言把「入场/退出挂单零成交」建模为「Trade 表为空/无订单」,依据固定源码
`execute_entry` 在下单当刻即创建 amount=0 的 open Trade,该建模错误;新断言用
真实 Order 建模零成交挂单(PENDING_ENTRY / PENDING_EXIT),要求不重复下单
(与 FreqtradeBot `handle_similar_open_order` 行为一致),更严格而非放宽。
其余 73 项零修改。

PPO 回归烟雾(独立脚本 `tests/freqai_rl_stage2_5_2/ppo_smoke.py`,非 pytest):
三轮(全新训练/完整缓存复用/模型重载)全部通过,详见 ppo_regression_smoke.json。
