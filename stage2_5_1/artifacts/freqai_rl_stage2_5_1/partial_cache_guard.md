# 部分缓存防护(工作包 E)验证记录

## 单元级(NONE/COMPLETE/PARTIAL/INCONSISTENT 分类 + fail closed + quarantine)
- 预期文件数: 5
- 构造: 5 窗只留窗 1/3 -> 状态 PARTIAL, 缺失 3 个
- 无修复参数: enforce 抛 PartialCacheError(启动前中止), 缓存文件 mtime/内容未变;
- COMPLETE 不移动任何文件; NONE 直接放行;
- quarantine: 整目录 rename(同文件系统原子), 文件逐字节不变, 兄弟模型目录保留。

## 集成级(硬性验收, 真实 5 窗 stage251-rc-2f131f3b15)
- 人为只保留窗 1/3 缓存(cb_btc_1780876800_prediction.feather, cb_btc_1782086400_prediction.feather, cb_btc_1782691200_prediction.feather 被移除)
- 无修复参数: run_experiment 退出码 3(freqtrade 未启动, 缓存未动)
- --repair-partial-cache: 整体 quarantine -> /home/cryptorl/projects/crypto_rl/user_data/models/stage251-rc-2f131f3b15/backtesting_predictions_quarantine_20260825T110415Z
- 修复后动作序列与无缓存基线逐行一致: True
- 修复后交易与基线一致: True
- 未重新训练(模型文件 mtime 不变): True
- identifier 不变: True
