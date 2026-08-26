# 阶段 2.6.0d:Strict Null 统计资格与经济等价闭环

> **阶段 2.6.0c 独立审查发现的一项集中阻塞在本目录全部修复。**
> 阻塞内容:strict Null 的报告内容已被正确密封与验证,但资格判定
> 采用了错误的统计单位(bootstrap 把 3 个 seed 的 288 根 bar 当独立
> 样本)、过宽的漂移容差(per-bar 0.0008 在 96 根 15m Episode 上
> 允许约 7.68% 累计 log drift),并把"没有显著发现正收益"错误解释
> 为"已证明不存在经济上可交易的优势"——`probe_null_stochvol` 的
> 3-seed 资格样本中 Always Flat 中位 0、Always Long 中位约 +2.40%
> 仍判 `always_flat_strong_baseline=true` 并整体 PASS(`probe_null_sign`
> 的 +0.75% 同样 PASS):旧检查根本不比较 Always Long vs Always Flat。
>
> **本目录只完成资格统计语义修复,未开始正式课程训练。**

- 判定:**PASS**(详见 report/route_c_stage2_6_0d_strict_null_statistical_closure.md)
- 测试:2.5 → 2.6.0d 全量回归 **904 项全部通过,零失败**
  (= 2.6.0c 基线 864 + 本阶段新增 40)
- 上游:Freqtrade 2026.7(commit `52bc96f`)clean,零修改
- `RouteCEnvCore-v1.0.0` 及全部冻结合同未修改
  (`src/rl_platform` 与 stage2_6_0c 基线逐字节一致)

## 本阶段修复

| 项 | 修复 |
|---|---|
| A1 显式三态结论 | `QUALIFIED / INVALID_NULL / INSUFFICIENT_EVIDENCE` 取代单一布尔;反证优先裁决(结构反证或经济反证 → INVALID_NULL;六项 checks 全真 → QUALIFIED;其余 → INSUFFICIENT_EVIDENCE);INSUFFICIENT 不得进入正式考试、不得被自动转换为 PASS;**当前 3-seed 资格报告全部得到 INSUFFICIENT_EVIDENCE**(任务书硬性要求) |
| A2 seed/cluster 统计单位 | 每 seed 构成一个 cluster,其 K=8 个关联 Episode(派生 seed=seed+1000k)先在 cluster 内按算术平均聚合(per-seed-mean-episode-v1);bootstrap 抽样单位是 cluster 值列表,不再是单根 bar;报告记录原始 Episode 数/cluster 数/distinct seed 数/聚合规则/bootstrap 实际 n;**断言 bootstrap n == distinct independent clusters**(四统计块 × 三族);同 seed 9 个 Episode 只算 1 cluster |
| 经济等价(检查语义修复) | `always_flat_strong_baseline` 真正比较 Always Long vs Always Flat:cluster 级 bootstrap CI 上界 ≤ 0.005(单侧 TOST:证明无可交易无条件多头优势);per-bar 容差与 bar 级 bootstrap 全部废除;`episode_net_drift_nonexploitable` 以每 episode 累计 log drift 定义不对称带(正侧 +0.5%:可被 Long/Flat 现货利用;负侧 -1.0%:不可利用,仅结构性非中心证据) |
| 统计功效门槛 | `MIN_QUALIFICATION_CLUSTERS=64`(预注册;功效推导:每 episode Always Long 净收益 std ≈3%,K=8 的 cluster std ≈1.1%,n=64 时 CI 半宽 ≈0.27%,足以单侧 TOST 覆盖 0.005 带;实测三族 lf CI 上界 +0.0008/-0.0013/-0.0015 全部带内) |
| 协议升级 | null-qualification-v3(v1/v2 报告在 verify 层显式拒绝:"bar 级统计单位/布尔-only 语义不得使用");nqc-/nq-/format 三通道使全部旧承诺与旧报告自动失效;verify 新增 cluster 单位/聚合规则/预注册参数/三态一致性对账;sealed-exam-commitment v3 / context v3 / CLI v4 / checkpoint manifest v3 / attestation v1 语义未变不升级 |
| 2.6.0c 实现保留 | issuer 信任根(承诺唯一来源/API 面无覆盖参数)、candidate-runtime-manifest-v1 逐文件绑定、反作弊复制闭环(动态 seed 门槛,无硬编码截断,无永真断言)、Null 报告内容绑定(bool-only 拒绝)全部保留并有守卫测试;20 例篡改矩阵全拒 |

## 关键证据(artifacts/)

| 文件 | 结论 |
|---|---|
| null_qualification_v3_full_sample.json + null_reports/*.json | 三族 64 cluster × 8 episode 全部 QUALIFIED(实测 CI) |
| null_qualification_small_sample_counterexample.json | **3-seed 反例闭环**:stochvol 中位 +0.02399 / sign +0.00748 复现,三族 INSUFFICIENT_EVIDENCE,verify 拒绝进入考试 |
| null_qualification_economic_disproof.json | 漂移伪 Null(64 cluster)lf CI 下界 ≈+16.6% >> 带 → INVALID_NULL |
| economic_band_registration.json | 带/语义/功效推导预注册(0.005/0.005/0.010/64) |
| cluster_bootstrap_unit_audit.json | bootstrap n == distinct clusters 全过;9 ep/1 seed → n_clusters=1 |
| sealed_commitment_verification_v3.json | v3 承诺完整验证通过(全部 checks) |
| mock_sealed_exam_flow_v3_nulls.json | 系统级沙箱考试 FAIL(正常挂科)+ 幂等重试 + 详细披露退休 |
| null_qualification_tamper_matrix_v3.json | 20 例篡改(旧格式/非 QUALIFIED 三态/统计单位/预注册参数/bool-only...)全部被拒,baseline 通过 |
| stage2_6_0c_guards_preserved.json | 2.6.0c 闭环保留(issuer/runtime/反作弊/报告绑定) |
| upstream_integrity.txt | vendor `52bc96f` clean;冻结六合同逐项未变 |

## 目录结构

```text
report/       阶段报告(修复对照/协议设计/功效推导/回归/完整性确认)
src/          评估侧 + 最小候选运行时 + 冻结平台核心(未修改)
tests/        本阶段 40 项测试 + 共享资格缓存 helper(null_qual_cache.py)
experiments/  全链路实验脚本(run_all.py)
artifacts/    全部证据文件(null_reports/ 为三族完整资格报告)
logs/         实验运行日志
```

复现:`python3 experiments/route_c_stage2_6_0d/run_all.py`(约 80s;
三族资格报告经确定性磁盘缓存,首次生成约 35s)。
