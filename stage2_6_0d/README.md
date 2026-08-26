# 阶段 2.6.0d:Strict Null 统计资格与经济等价闭环

> **阶段 2.6.0c 独立审查发现的集中阻塞在本目录全部修复(完整任务书语义)。**
> 阻塞:资格判定统计单位错误(bootstrap 把 3 seed 的 288 根 bar 当
> 独立样本)、漂移容差过宽(per-bar 0.0008 折算 ~7.68%/日)、把
> "没有显著发现正收益"当作"已证明不存在可交易优势"——stochvol
> 3-seed 样本 Always Long 中位 ~+2.40%(sign ~+0.75%)且 Always
> Flat 中位 0 仍判 `always_flat_strong_baseline=true` 并 PASS。
>
> **本目录只完成资格统计语义修复,未开始正式课程训练。**

- 判定:**PASS**(report/route_c_stage2_6_0d_strict_null_statistical_
  qualification.md)
- 测试:2.5 → 2.6.0d 全量回归 **921 项全部通过,零失败零跳过**
- 上游:Freqtrade 2026.7(`52bc96f`)clean,零修改;冻结六合同未变

## 本阶段实现(工作包 A-F)

| 项 | 实现 |
|---|---|
| A1 三态结论 | QUALIFIED / INVALID_NULL / INSUFFICIENT_EVIDENCE;反证优先;INSUFFICIENT 不得进入考试、不得自动转 PASS;**3-seed 报告全部不再 QUALIFIED**(stochvol 因 CI 下界超 margin 判 INVALID_NULL) |
| A2 统计单位 | seed cluster(每 seed 聚合 K 个关联 Episode);**bootstrap n == distinct independent clusters**(四差值块 × 三族);288-bar 场景 n==3;antithetic pack 6 ep/3 cluster/n==3 |
| A3 非优越性检验 | 四个差值(AlwaysLong/Oracle/Rule/HFT vs Flat)全部要求**中心 <= margin 且 97.5% 单侧上置信界 <= margin**(HFT 容差 0);不用 p-value、不用 CI 包含零;统计方法/置信 0.95/bootstrap 2000 次/seed 20260826 冻结进 spec 哈希 |
| A4 经济 margin | 只来自 Null Qualification Spec:**精确往返摩擦 1-(1-fee)²×(1-slip)² = 0.001999**(按 EvalConfig 计算,非写死);绑定 fee/slippage/price tick/Episode 真实时长(24h)/timeframe/比较策略/聚合方式;生成器参数通道删除 |
| A5 功效 | 每族 **64 独立 cluster × 16 原始 Episode**;确定性 MC(六类场景):零优势误判 INVALID 0.0%、2×margin 错判 QUALIFIED 0.3%、1×margin 拒绝功效 84.8% 全达标;**32 cluster 实证不足**(零优势 QUALIFIED 成功率仅 59.25%,固定预注册 seeds 不允许重选) |
| B 结构平衡 | **antithetic pairing(生成层镜像)**:同 seed 同随机流收益逐位取负(绝对收益/波动状态/wick 不变);pair 内多头优势与累计漂移精确抵消;无终点约束;pair 不进 obs;顺序 seeded 随机化。**关键结论:镜像同样抵消任何确定性漂移 → family 资格判定必须用原始样本,结构平衡只用于 pack 层** |
| B2 pack-level validity | family 与 pack 分离;执行器候选评估前对物化 null episodes 现算 pack validity 并与承诺 npv- 哈希对账;每族 ≥32 独立 cluster;**偶然正漂移 pack → EXAM_INVALID(候选不进入评估,不判 FAIL/作弊)**;mock pack 每族扩到 32 antithetic pair |
| B4 构建不可候选依赖 | 构建算法候选出现前冻结(npb- 哈希入承诺);namespace seed 推导;attempt counter + 匿名拒绝原因;签名无任何候选输入 |
| C 报告与绑定 | 报告记录完整统计证据(协议/三态/实现绑定/spec hash/margin 推导/统计协议/真实时长/每 cluster 差值/中心与上界/功效引用/level);承诺 v4 绑定 nqs-/nq-/npv-/nqc-/npa-/npac-/npb- 全部哈希;隐藏 seed 不进公开承诺(只 hash+非敏感摘要) |
| E 协议 | **sealed-exam-commitment-v4**(v3 进弃用)/ **null-qualification-v3** / **hidden-exam-cli-v5**;context v3 / checkpoint manifest v3 / attestation v1 / runtime manifest v1 语义未变不升级;旧协议显式拒绝,不静默补默认 |
| F mock 全链路 | Spec → 功效 → 64×16 三族资格 → mock null pack(32 pair/族)→ pack validity → issuer → 256-step PPO smoke(允许挂科)→ attestation → v4 承诺 → 系统级沙箱(pack validity 现算对账)→ 反事实 → FAIL → 幂等 → 披露退休;双篡改矩阵全拒 |

## 关键证据(artifacts/,任务书清单逐名对齐)

| 文件 | 结论 |
|---|---|
| null_qualification_spec.json | margin 0.001999 精确推导 + 统计协议冻结 |
| null_economic_margin_derivation.json | 往返摩擦硬上限 + 按 Episode 真实时间语义 |
| null_power_analysis.json | 三目标全达标;32-cluster 充分性实证 |
| seed_cluster_bootstrap_evidence.json | bootstrap n == distinct clusters(全块) |
| legacy_three_seed_reports_rejection.json | 旧 3-seed 证据全部被新 verifier 拒收 |
| stochvol / sign_positive_long_edge_rejection.json | +2.40%/+0.75% 反例复现且经济检查失败 |
| valid_null_family_qualification.json | 三族 64×16 全部 QUALIFIED(lf 上界 ≤ margin) |
| actual_pack_null_validity.json | mock pack 32 pair/族 PACK_VALID |
| antithetic_pair_integrity.json | 逐位镜像/漂移精确抵消/builder attempt 记录 |
| pseudo_null_rejection_matrix.json | 固定漂移/可预测趋势/HFT 正收益/小幅漂移全拒 |
| pack_accidental_drift_rejection.json | 偶然正漂移 pack → EXAM_INVALID(候选不评估) |
| null_qualification_tamper_matrix_v3.json | 16 例全拒(含 seeds 偏离 namespace 重算对账) |
| sealed_exam_tamper_matrix_v4.json | v3 承诺/缺字段全拒 |
| mock_sealed_exam_v5_summary.json | 沙箱考试 FAIL(正常挂科)+ 幂等 + 披露退休 |
| regression_test_summary.md | 921 项零失败 |
| upstream_integrity.txt | vendor 52bc96f clean;冻结六合同未变 |

## 目录结构

```text
report/       阶段报告(修复对照/协议设计/功效推导/回归/PASS 对照)
src/          评估侧 + 最小候选运行时 + 冻结平台核心(未修改)
tests/        本阶段 57 项测试 + 共享资格链缓存 helper
experiments/  全链路实验脚本(run_all.py)
artifacts/    全部证据文件(含 null_reports/ 三族完整报告)
logs/         实验运行日志
```

复现:`python3 experiments/route_c_stage2_6_0d/run_all.py`(资格链
经确定性磁盘缓存,首次生成约 12 分钟,之后秒级)。
