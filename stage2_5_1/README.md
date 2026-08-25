# 阶段 2.5.1:Route C 状态一致性与实验纪律加固

本目录为公开复现材料,对应本地主报告
`~/projects/crypto_rl/reports/freqai_rl_stage2_5_1_hardening.md`。
上一阶段材料见 [stage2_5/](../stage2_5/)(不覆盖)。

## 判定:PASS

阶段 2.5.1 加固的七个问题与结果:

| 问题 | 结果 |
|---|---|
| PPO 实际训练步数与完整参数未记录 | 每窗 base=482 / rounded=512 / actual=512;resolved 参数唯一来源 + 冲突报错 |
| 正式 RouteCStrategy 未接入训练同款滑点 | custom_entry/exit_price 从配置读取,0/5/10bps 端到端对齐(rel 1e-9) |
| 指纹未覆盖完整训练数据/配置/全部代码 | 代码树哈希(18 文件)+ 完整规范化配置 + 全量数据范围(2184 行)+ 依赖版本 |
| 部分缓存可能错误重置跨窗口状态 | NONE/COMPLETE/PARTIAL/INCONSISTENT 四态;PARTIAL 启动前中止;--repair 整体 quarantine 后与基线逐行一致 |
| do_predict≠1 时目标/信号/仓位失同步 | 无效行不调用模型、不更新状态;信号状态机;populate 幂等 |
| 首次 live 全历史回填覆盖真实持仓 | 历史回填隔离状态;最新行与每个 heartbeat 从 Trade 表读取真值 |
| conv_width≠1 未被阻止 | 四处硬断言(渲染/模型构造/推理入口/启动检查),指纹含 conv_width |

加固烟雾:`stage251-rc-2f131f3b15`(BTC/USDT 1h,seed 42,fee 0.001,
slip 5bps,conv_width=1,PPO 显式参数);上游 Freqtrade 2026.7 /
commit 52bc96f 零修改;模型重载与部分缓存修复均逐字段一致。

## 目录结构

```text
stage2_5_1/
├── README.md
├── report/       主报告(25 节)
├── src/          rl_platform 核心包(账本/环境/推理/信号/指纹/守卫/预算/缓存/价格限制/live)
├── adapters/     FreqAI 薄适配(RouteCModel)+ 策略(RouteCStrategy)
├── experiments/  实验入口 run_experiment.py + 配置模板
├── tests/        8 个测试文件 + 证据脚本(动态发现,无硬编码 identifier/窗口/行数)
├── artifacts/    21 个证据文件(预算/对齐/缓存/do_predict/live/回归/重载/上游完整性)
└── logs/         烟雾运行摘要
```

## 复现

环境:Ubuntu 24.04(WSL2)+ conda(freqtrade 2026.7 vendor 零修改、
stable-baselines3 2.9.0、gymnasium 1.3.0;完整版本见
artifacts/dependency_versions.json)。

```bash
python -m pytest tests/ -q                      # 112 项(38 旧 + 74 新)
python experiments/freqai_rl_stage2_5_1/run_experiment.py \
    --timerange 20260601-20260701 --seed 42 --slippage-bps 5 \
    --fee 0.001 --suffix smoke --extract-actions
python tests/freqai_rl_stage2_5_1/ppo_evidence.py --suffix smoke
python tests/freqai_rl_stage2_5_1/make_evidence.py smoke
```

回测启动需交易所市场元数据(走代理时先 source 代理脚本);
数据文件(BTC/USDT 1h feather)不入库,自行下载后按
data_fingerprint_scope.json 的范围规则对齐。

## 边界声明

- 不含真实市场数据、模型二进制、API Key、数据库、代理认证、
  Windows 用户目录或本机秘密;
- 复现脚本不硬编码 identifier / 模型目录名 / 回测 zip 名 / 窗口数 / 行数,
  全部从 manifest 与实际目录动态发现;
- 本阶段不做收益评估、不做超参搜索、不启动实盘或长期 Dry-run。
