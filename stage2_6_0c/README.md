# 阶段 2.6.0c:密封信任根、候选运行时绑定与反作弊复制闭环

> **阶段 2.6.0b 遗留的四个正式阻塞在本目录全部修复。**
> 阻塞内容:issuer 信任根可被 context 覆盖(保留承诺、替换 issuer、
> 自签 checkpoint 即可获得资格)、沙箱内实际执行的
> `rl_candidate_runtime` 未被承诺绑定(profile 只绑定隔离配置,
> staging 复制与启动之间存在 TOCTOU)、三类作弊原因取样被硬编码为
> 2 个 seed(`replication_eps[:2]`)而冻结门槛为 3——
> `SUSPECTED_CHEATING` 永不可达、strict Null 资格可退化为
> `qualification_pass=true` 布尔占位(验证不读报告、不重算 hash)。
>
> **本目录只完成信任链闭环修复,未开始正式课程训练。**

- 判定:**PASS**(详见 report/route_c_stage2_6_0c_sealed_trust_closure.md)
- 测试:2.5 → 2.6.0c 全量回归 **864 项全部通过,零失败**
  (数字见 report 与 artifacts/regression_test_summary.md)
- 上游:Freqtrade 2026.7(commit `52bc96f`)clean,零修改
- `RouteCEnvCore-v1.0.0` 及全部冻结合同未修改

## 本阶段修复(工作包 A-F)

| 工作包 | 修复 |
|---|---|
| A issuer 信任根收归承诺 | `run_sealed_exam` 删除 issuer 覆盖参数;信任根唯一从 commitment canonical payload 构造(先做自洽校验:重算 Ed25519 公钥指纹/协议/runner hash 格式/smoke 策略);context issuer 降级为展示副本,与承诺逐字段 canonical equality,不同即 EXAM_INVALID;"承诺绑 A + context 换 B + B 自签 checkpoint + B runner"端到端攻击被拒 |
| B 候选运行时内容绑定 | 新增 candidate-runtime-manifest-v1:递归扫描 `rl_candidate_runtime` 全部真实文件(不限 .py;symlink 拒绝;五个安全关键文件必在),逐文件 sha256 + 协议版本 → rt- tree hash 进入承诺;`launch_sandboxed` 在 staging 复制后、unshare/bootstrap 前对实际执行副本重算 manifest 并与承诺逐字节比对(TOCTOU fail closed);bootstrap 跳过 Landlock/worker 改协议/guard 短路/增删文件/换 symlink 全部使旧承诺失效 |
| C 反作弊复制闭环 | 删除五处 `[:2]` 硬编码;每种原因按冻结门槛 `max(min_distinct_cheat_seeds, min_failing_cheat_episodes)` 动态取样不同 seed,pack seed 不足直接 EXAM_INVALID;seed 内聚合规则 per-seed-worst-variant-v1 预注册进判定器哈希(同 seed 多 cut/variant 先聚合,变体净收益取最坏值,bootstrap 抽样单位是 seed);absolute_price / episode_position / periodic_pattern 三类 3-seed 作弊策略真实触发 SUSPECTED_CHEATING(此前不可达);删除 `or True` 永真断言并加静态扫描 |
| D 真实 Null 资格报告 | null-qualification-v2:报告内嵌族实现指纹/Observation Schema hash/EvalConfig(含 fee)/timeframe/资格参数/资格审查代码哈希/seed;binding 携带完整 canonical 报告 payload 进入承诺哈希;bool-only 占位构建与验证双侧拒绝;验证重读 payload:重算报告 hash + family/version/实现/schema/fee/timeframe/seed/checks 全对账(21 例篡改矩阵全拒) |
| E 协议升级 | sealed-exam-commitment-v3 / sealed-exam-context-v3 / hidden-exam-cli-v4(单一来源)/ course-verdict-spec-v3(冻结 seed 聚合规则)/ candidate-runtime-manifest-v1 / null-qualification-v2;v1/v2 承诺与 v2 context 显式拒绝;缺 runtime hash 的承诺拒绝;checkpoint manifest v3 与 training attestation v1 语义未变不升级 |
| F mock 正式全链路 | 真实 Null 报告 → issuer/受信 runner → 256-step PPO smoke(仅验证 provenance/sandbox/接口,正常挂科)→ attestation → v3 承诺 → 系统级沙箱 → 四原因 3-seed 反事实套件 → 冻结判定 FAIL → 幂等重试 → 详细披露退休;issuer 覆盖攻击/runtime/Null/协议四组篡改矩阵全部拒绝 |

## 关键证据(artifacts/)

| 文件 | 结论 |
|---|---|
| issuer_context_override_attack.json | attack_blocked=true(端到端 EXAM_INVALID) |
| trusted_issuer_consistency.json | 自洽矩阵全拒;smoke 改动改变承诺哈希 |
| candidate_runtime_tree_manifest.json | 承诺绑定 manifest 且与源一致 |
| candidate_runtime_tamper_matrix.json | all_tamper_invalidates=true |
| staged_runtime_integrity.json | 正常 staging 逐字节一致;复制后替换 fail closed |
| anticheat_replication_coverage.json | all_reasons_meet_threshold=true(四原因 3 seed) |
| anticheat_seed_cluster_bootstrap.json | 逐 seed 聚合明细 + seed 级 bootstrap |
| absolute_price / episode_position / periodic_pattern _cheat_integration.json | 三类 3-seed 作弊 SUSPECTED_CHEATING(此前不可达) |
| null_qualification_report_bindings.json | 三族真实报告绑定(完整 payload) |
| null_qualification_tamper_matrix.json | all_negative_cases_rejected=true |
| sealed_exam_tamper_matrix_v3.json | all_rejected=true(v1/v2/缺 runtime/bool-only/v2 context) |
| mock_sealed_exam_v4_summary.json | 全链路 FAIL(正常挂科)+ 幂等 + 退休 |
| regression_test_summary.md | 8 目录 864 项零失败 |
| upstream_integrity.txt | vendor clean;HEAD 52bc96f;冻结版本逐项 |

## 目录

- `report/` 主报告
- `src/` rl_curriculum(评估侧)+ rl_candidate_runtime(最小候选
  运行时,沙箱内唯一项目代码)+ rl_platform(冻结环境核心,未修改)
- `experiments/route_c_stage2_6_0c/` run_all.py(全部证据生成)
- `tests/` 阶段 2.6.0c 新增测试(6 个文件,83 项)
- `artifacts/` 证据(null_reports/ 为三族 mock 资格报告全文)
- `logs/` 实验运行日志

## 不包含

真实 issuer 私钥、正式隐藏种子、正式私有生成器、模型二进制、真实
行情、数据库、API Key、代理认证、私人凭证。mock 私钥仅在临时目录
即时生成,不进入 Git;实验工作目录(_work,含 checkpoint/密钥)不
进入发布。

## 下一步

本阶段完成后由独立审查决定是否允许进入 2.6.1;本目录不自行开始
正式 PPO 课程训练。
