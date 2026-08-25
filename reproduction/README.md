# freqai_rl_platform_audit 复现说明

固定版本:Freqtrade tag 2026.7(commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5)。
主报告:`~/projects/crypto_rl/reports/freqai_rl_phase1_2_audit.md`。

## 环境与网络

```bash
wsl -d CryptoRL-Ubuntu-24.04
source ~/projects/crypto_rl/activate-freqtrade.sh   # freqtrade-rl conda 环境
source ~/projects/crypto_rl/scripts/proxy-on.sh     # 需要外网时(经 Windows 本地代理 7897)
```

freqtrade 异步 ccxt 需要代理时,配置里已含 `exchange.ccxt_config.aiohttp_trust_env: true`。

## 核心复现路径(按顺序)

1. 数据(已存在则跳过):
   `freqtrade download-data --config experiments/freqai_rl_platform_audit/configs/config_download_binanceus.json --pairs BTC/USDT --timeframes 1h --timerange 20260401-20260701 --userdir ~/projects/crypto_rl/user_data`
2. 官方 5 动作路径:
   `freqtrade backtesting --config experiments/freqai_rl_platform_audit/configs/config_freqai-rl-platform-audit-2026-7-official5ac.json --userdir ~/projects/crypto_rl/user_data --strategy OfficialRLStrategy5ac --freqaimodel ReinforcementLearner --timerange 20260601-20260701 --cache none --export trades`
3. 3 动作 long-only 路径:同上,换 config_freqai-rl-platform-audit-2026-7.json /
   AuditLongOnlyRLStrategy / AuditBase3RLModel。
4. 重载/缓存实验:再次运行步骤 3(命中预测缓存);删除
   `user_data/models/freqai-rl-platform-audit-2026-7/backtesting_predictions/*.feather`
   后再运行(命中模型重载)。
5. 人工序列与固定动作:
   `python tests/freqai_rl_platform_audit/synthetic_env_audit.py`
6. RL 环境 vs 回测器:
   `python tests/freqai_rl_platform_audit/env_vs_backtest.py`
7. add_state_info 报错复现 + 分析工具帮助:
   `bash tests/freqai_rl_platform_audit/stateinfo_lookahead.sh`
8. recursive/lookahead:
   `bash tests/freqai_rl_platform_audit/lookahead_run.sh`(price_side 修正版配置:
   config_lookahead_variant.json)
9. 上游测试:
   `cd vendor/freqtrade && python -m pytest tests/freqai/test_freqai_interface.py -k "ReinforcementLearner or get_state_info" -v`
   (需 pytest/pytest-mock/pytest-xdist/pytest-asyncio/pytest-timeout,已装)

## 注意

- **预测缓存纪律**:策略/奖励/seed/配置任何改变后,必须删除对应 identifier 的
  backtesting_predictions(缓存只按文件名+行数判定有效,会静默复用旧预测)。
- 本审计自研文件全部位于 user_data/strategies、user_data/freqaimodels、
  tests/、experiments/、artifacts/、logs/、reports/;vendor/freqtrade 保持零修改。
- 复现实验顺序执行约 15~25 分钟(不含 lookahead-analysis)。
