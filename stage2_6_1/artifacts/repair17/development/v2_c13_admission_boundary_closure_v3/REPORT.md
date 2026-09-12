# R17 准入边界 v3 轮最终报告（诚实 FAIL）

任务 ID：`R17V2C13AdmissionBoundaryAndColdReadClosure-v3`
接手基线：`04b2978a1e2c375bd347168f2a9eeded790b393e`（本地=远端，分支 `route-c-stage2-6-1-repair17`）

## 首页结论

- **本轮边界修复工程：FAIL**
- **本轮统计：NOT_RUN**（未运行任何新实验/qualification/exposure/训练）
- **正式资格：NOT_ISSUED**（未签发任何资格，未创建 C2 namespace，未消耗生产 claim）

旧 v2 状态不变：数值路径 COMPLETE；stored-table strict diagnostic PASS；工程合同 FAIL；正式资格 NOT_ISSUED。
本提交为失败证据提交，**不得用于准入**；未创建代码候选 C 的准入资格语义（定向关键组未通过，按 RUNBOOK §2 停止）。

## 各阶段真实状态

| 阶段 | 状态 | 关键事实 |
|---|---|---|
| S0 接手校验+保护证据 | 完成 | 本地 HEAD=远端=基线 `04b2978a`；源码三目录 clean；历史 lock SHA `c9152b62…` 保持；只读区 6 目录 4148 文件快照（`s0_before/`） |
| S1 应用给定实现 | 完成 | check rc=0 → `--apply` rc=0，`applied=true`；输出恰为 SOURCE_MAP 九文件（7 改+2 新）；`git diff --check` 干净；recovery 已存 `apply/recovery/` |
| S2 同步+源码身份+定向 | **FAIL（停止点）** | `r17_sync.sh` rc=0；`source_guard()` 十成员含新 guard（sha `daf603e6…`，与应用器输出一致）；Python 3.11.16/freqtrade-rl。监护入口定向八文件：**152 tests / 1 fail / 0 error / 0 skip，业务 rc=1** |
| S3 代码候选 C | 未创建 | 定向未过，按任务书不提交候选 |
| S4 完整 R17-first 回归 | 未运行 | 未消耗 |
| S5 真实包副本负例 | 未运行 | 未消耗 |
| S6 证据 E + 提交后冷验 | 未运行 | 未消耗（本报告为失败证据提交，非 E） |

## 唯一失败用例与根因

`tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py::test_v10_one_shot_claim`

```
stage2_6_1_runner/r17_v2_c13_profile.py:830: in consume_production_claim
    admitted = validate_claim_admission(auth)
stage2_6_1_runner/r17_v2_c13_profile.py:916: in validate_claim_admission
    require(plan['contract'] == fixed_contract() if not auth.synthetic
            else plan['contract'].get('synthetic_profile') is True, ...)
r17_v2_c13_profile.ProfileError: production/synthetic contract and authority disagree
```

### 机制

1. v10 的 `_claim_fixture`（基线原有，本包未修改该测试文件）以 `prof.synthetic_authority(...)` 建显式合成 authority，再以 `prof.make_plan(fixture_runtime())` 建计划 —— `contract=None` 采用生产 `fixed_contract()`，无 `synthetic_profile` 键。
2. 新 `validate_claim_admission` 对 synthetic authority 要求 `plan['contract']['synthetic_profile'] is True`；生产合同无该键 → require 失败。
3. 该夹具 receipt 同时携带假回归包摘要 `'package_sha256': 'aa'*32` 且未创建实际回归包 —— 这正是本轮 TASKBOOK S2 明确禁止恢复的旧 unhealthy 夹具形态；即使合同检查放行，后续 `verify_package`（synthetic 亦需 structural 实包）也会拒绝。

### 对照：本包认可的合法 synthetic 夹具形态

修改后的 `test_curriculum261_r17_v2_c13_claim_protocol.py`（本包已更新，20 测试全过）以
`contract = dict(prof.fixed_contract(), synthetic_profile=True)` + 实际 fixture 回归包（`rev.package_digest(pkg)`）构造，与新准入边界自洽。

### 判定

给定实现与基线未修改测试之间存在真实行为冲突：包内更新了 claim_protocol / regression_evidence 两个测试文件，但 pipeline 测试的 `_claim_fixture`（v10 的独立副本）未在修改面内，其旧形态被新边界按设计拒绝。按 TASKBOOK S3/RUNBOOK §2：不修改测试预期、不另设计修复、不放宽检查，本轮按失败交付原始证据。

### 部署前提排查（已排除）

pipeline 测试文件三方哈希一致（仓库工作树 = 部署副本 = 基线 Git blob = `cda40202…`），见 `deployment_checks/pipeline_test_three_way.txt`；`source_imports.json` 证明实际导入的十成员与应用器输出字节一致。失败非陈旧部署所致。

## 保护对象不变性（应用后复核）

- 历史 lock `r17_v2_c13_source_lock.py` SHA-256：`c9152b62192a93571c16ba62e0ef2e70522f108726f3eb83fd25d48007a77c55`（与接手时一致）
- 历史只读区 6 目录 4148 文件：与 S0 快照逐字节一致（`READONLY_AREA_UNCHANGED`）
- 生产旧 claim（v2_c13_engineering_claim 区）：包含于上述只读区比对，未变
- 未创建任何生产 plan/receipt/admission/full-regression/claim；未运行任何新主实验

## 定向八文件真实计数（监护入口 monitored_run，2026-09-12 09:28–09:36 CST）

| 测试文件 | tests | fail | error | skip |
|---|---|---|---|---|
| test_curriculum261_r17_v2_c13_admission_guard（新） | 28 | 0 | 0 | 0 |
| test_curriculum261_r17_v2_c13_claim_protocol（改） | 20 | 0 | 0 | 0 |
| test_curriculum261_r17_v2_c13_regression_evidence（改） | 31 | 0 | 0 | 0 |
| test_curriculum261_r17_v2_c13_pipeline（基线原样） | 42 | **1** | 0 | 0 |
| test_curriculum261_r17_v2_c13_reader_binding | 7 | 0 | 0 | 0 |
| test_curriculum261_r17_v2_c13_synthetic_chain | 11 | 0 | 0 | 0 |
| test_curriculum261_r17_v2_c13_source_provenance | 5 | 0 | 0 | 0 |
| test_curriculum261_r17_c2_launch_prep | 8 | 0 | 0 | 0 |
| **合计** | **152** | **1** | **0** | **0** |

入口 rc=1（`targeted/entry.rc`）；JUnit 原件 `targeted/monitored_run/junit.xml`；逐文件统计 `targeted/junit_breakdown.json`。

## Git 提交说明

本提交包含：应用后的九文件给定实现（如实保留工作树状态，未回滚）+ 本证据根全部原件 + `.gitattributes` 新根 `-text` 规则。
run_supervision 活动追加（2 M + 175 ??）按 SOURCE_MAP 单独记账，未混入本提交。
提交为失败证据提交；后续轮次如需修复，应由助手下发新的代码包，明确 pipeline v10 夹具与新边界的调和方式（更新该测试夹具为 synthetic 合同+实包形态，或调整边界语义）。

## 未运行项清单

- S4 完整 R17-first 回归（`run_bound_regression.sh`）
- S5 真实健康包八类副本负例（`probe_evidence.py`）
- S6 归档 E、提交后 full 冷验
- 任何新实验 / qualification / exposure / C2 / 正式训练
