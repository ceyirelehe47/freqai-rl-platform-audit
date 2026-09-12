# R17 V10 夹具修复与续接验证报告（v3a）——工程 FAIL（提交后冷验）

任务 ID：`R17V2C13V10FixtureRepairAndVerificationResume-v3a`
失败基线（父提交）：`1ea193c0f1eb710e37aa23aa89f261617eb93c43`（旧 v3 诚实 FAIL 证据提交，永久保留）
代码候选 C：`16c45daeac0c934886157b2dbbff5509db8b7868`（单文件：pipeline 测试夹具修复）
证据提交 E：`82deed8677458dda7afc8e19c27b8148ab100699`（continuation_v3a 子树）
失败证据提交 E2：本提交（post_E_verify/ + 本报告更正；NOT_ADMITTED）

## 首页结论（按任务书 §11 更正）

- **本次 fixture 修复/续接工程：FAIL**（完成条件之一"E 后 full 冷验 ok=true/rc=0"不成立；详见 `post_E_verify/FAILURE_NOTE.md`）
- **统计：NOT_RUN**（未运行任何新实验/qualification/exposure/训练）
- **正式资格：NOT_ISSUED**（旧 v2 工程 FAIL 不追认；C2/Stage 2.6.1 资格不升级）

失败点：E 中按 RUNBOOK `cp -a` 归档的 S5 负例产物含真实目录 symlink（Git mode 120000），新 guard 的 evidence-only 后继规则要求全部为普通 blob，提交后 full 冷验 rc=1（`candidate_drift: evidence is not a regular Git blob`）。该规则同时禁止删除/类型替换，E 已推送，本根冷读不可恢复；修复由助手下发新包。

S0–S5 与 C/E 本身全部真实通过（下文如实保留）；本报告初版曾误写 PASS，本 E2 提交更正。

## 修改面与候选

唯一仓库补丁：`stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py`
（应用前 Git blob `92350d8a…` → 应用后 sha256 `2f761e76…`；由包内 `tools/apply_fixture_patch.py` check（rc=0）→ `--apply`（rc=0）应用）

- `_claim_fixture` 改为复用 claim_protocol 的 `_persist_plan_and_receipt`（synthetic 合同 + 真实临时回归包 + 真实摘要链），调用时延迟导入。
- 新增 `test_v10_fixture_is_evidence_backed_and_not_production`（1 case）与 `test_v10_unhealthy_fixture_is_still_rejected`（4 case 参数化）。
- 原有测试函数逐字不变（应用器核验 `existing_test_bodies_unchanged=true`）；不重签任何锁；source_guard 十成员与 `1ea193c` 完全一致（生产代码零改动）。

C 提交（`16c45da`）恰含这一个文件；push 后重同步，源/测试/配置 clean。

## S2 定向八文件（监护入口，2026-09-12 10:13–10:21 CST）

`tools/run_targeted.sh` 一次运行：**157 tests / 0 fail / 0 error / 0 skip**，entry rc=0，junit_check rc=0。
恰为预期 157（152+5）；pipeline 47。四个变异负例真实执行并命中预期层：

| 变异 | 拒绝层 |
|---|---|
| production_contract | production/synthetic contract and authority disagree |
| missing_regression | full regression evidence rejected at claim |
| fake_regression_digest | different full-regression evidence package |
| missing_admission | authoritative admission evidence missing |

健康夹具断言全过（实包存在、receipt 真摘要、structural verify ok、admission_eligible=False、只读、claim 未创建）。

## S4 完整 R17-first 回归

### 第一次尝试（保留于 `full_regression_attempt1_stale_deploy/`）：验证层 FAIL

- pytest 阶段：2070 tests / 0 fail / 0 error / 7 skip，entry rc=0。
- 采集阶段：成功（package_sha256 `559f22eb…`）。
- **verify 阶段 rc=1**：31 个 `test_file_hash_mismatch` —— 部署树含 31 个**从未被本仓库任何提交跟踪**的陈旧测试文件（r4–r8 时代本地开发树遗留；`git log --all` 为空证），全量集合混入非候选测试，新验证器按设计拒绝绑定。

### 部署前提修正（`deploy_stale_quarantine/`）

31 个陈旧文件逐一核验"从未跟踪"后**移动隔离**（非删除，字节与清单保全），部署测试集对齐仓库 HEAD（98=98）。仓库零改动，C 不变。此为 v3 任务书 S2"修正部署前提"授权范围内的处置。

### 第二次尝试（`full_regression/`）：全过

- **1832 tests / 0 fail / 0 error / 7 skip**（= 首试 2070 − 31 陈旧文件贡献的 238 case，自洽），entry rc=0。
- 7 skip 与源码固定白名单完全一致（R12–R16 治理 ancestry/LF 六件 + r16 wrapper selfcheck）。
- collection 对拍、test_files 绑定、监护 required/native、import 来源等全层通过。
- 健康包 full verification（C 时，包在仓库外）：**ok=true / scope=full / errors=[] / rc=0**（admission_eligible=false 为无生产 authority 的正确边界）。

## S5 真实健康包副本负例（`negative_cases/`，rc=0）

健康控制 full 通过；八类副本负例全部命中预期错误键，原包字节前后不变：

required_empty/required_duplicate→required_role_set_mismatch；critical_empty→critical_policy_mismatch；隐藏 testcase failure→junit_failures_nonzero；等数量换成员→collected_membership_mismatch；import 缺来源→import_identity_mismatch；supervisor rc 缺失→supervision_rc_mismatch；目录 symlink→non_regular_file。

其中 `nested_directory_symlink` 用例的副本包内含真实目录 symlink —— 该产物经 RUNBOOK `cp -a` 归档进 E 后成为 S6 失败根因（见首页）。

## S6 提交后 full 冷验：FAIL（`post_E_verify/`）

E push 后在 HEAD=`82deed8` 对归档健康包执行 RUNBOOK §6 只读验证：**rc=1 / ok=false / scope=full / `candidate_drift: evidence is not a regular Git blob`**。
机制、不可恢复性与修复方向见 `post_E_verify/FAILURE_NOTE.md`。未做 E2 之后的无限补提交；本 E2 仅归档失败证据并更正本报告。

## 保护对象不变性（E 前）

- 历史 lock `c9152b62…`、治理 lock `304301b7…`、relock `3e42f32d…`：与接手一致。
- 旧 v3 失败根 42 文件：逐字节不变（旧 REPORT 与失败日志原样保留，未改动）。
- 其余六个历史只读区 4148 文件：与接手快照逐字节一致。
- `git diff C -- runner/src/tests` 为空；生产 claim/plan/receipt/admission 零写入。

## Git 链

`1ea193c`（v3 失败证据，保留）→ **C `16c45da`**（fixture 修复，已推）→ **E `82deed8`**（continuation_v3a，已推）→ **E2**（本提交：post_E_verify 失败证据 + 报告更正）。
run_supervision 活动追加（2M/175??）单独记账未混入。

## 未运行项

- 无新实验/qualification/exposure/C2/正式训练（未授权、未运行）。
- "最终仓库外只读冷验"以 post_E_verify 原件形式留档（结果同 rc=1；根因同上，未重复无限补提交）。
