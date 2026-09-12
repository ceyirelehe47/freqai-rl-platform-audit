# 修改与来源地图

## 唯一仓库补丁目标

`stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py`

- 基线 Git blob：`92350d8ae5bdace6801efc120f83d616e2a24d29`。
- 替换一个 `_claim_fixture` 函数。
- 新增 `test_v10_fixture_is_evidence_backed_and_not_production`。
- 新增四 case 的 `test_v10_unhealthy_fixture_is_still_rejected`。
- 原有测试函数体逐字不变；不重命名、不移除任何测试。

## 只读依赖

现有 claim_protocol helper：

`stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_claim_protocol.py`

Git blob：`0e6b2746df08d56b4ef4537dfba232b72cd79b75`。复用 `_persist_plan_and_receipt`，不修改该文件。它在 `1ea193c…` 中已创建 synthetic 合同及真实临时包。

profile、admission_guard、regression_evidence、pipeline 生产源码、governance lock/relock、旧历史 lock、C2 selector、monitor/sampler 全部不改。尤其不能为了新 fixture 重签十成员生产闭包。

## 仓库外包文件

- `payload/pipeline_fixture.py`：已实现的唯一替换函数与新增测试。
- `tools/apply_fixture_patch.py`：固定 HEAD/blob、check/apply、单文件输出及 recovery。
- `tools/run_targeted.sh` / `check_targeted_junit.py`：受监护八文件定向与实体/JUnit检查。
- `tools/run_bound_regression.sh` / `probe_evidence.py`：原 v3 包逐字沿用的后续验证脚本。
- `tests/` / `references/` / `local_validation/`：本地包级测试及其支持文件，只用于验证包，不安装到生产 runner。

## 原包身份

原 v3 ZIP SHA-256：`db14d06284beea8ddb460a3c21c4e00dcdea2e37b2978021fd46d96f514b9f59`。

本包中 `references/guard_v3_unmodified.py` 是该 ZIP 内已实现 guard 的不改字节副本，用于本地真实临时 Git C→E 验证，SHA-256：`daf603e6a4ca207373f3034ed518a32535810cc327dce356f075244bba0d3a04`。不会写入仓库或替换部署 guard。

## 新证据白名单

仅使用现有 v3 根下、在本次 C 中尚不存在的 `continuation_v3a/`。旧 v3 根的既有文件全部只读。不要用平级新根触发既有 evidence-only 守卫误拒，也不要改该守卫。
