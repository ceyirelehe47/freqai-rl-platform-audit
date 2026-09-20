# R19 audit 机械面确定性复现证据(工程坐标,2026-09-20)

- `head_reproduction_cue_contract_audit.json` / `..._cue_audit_plan.json`:
  HEAD(e07da67 前工作树,代码同 7bbb033+)上以正式机械面
  (`curriculum261_r17_cli cue-audit`,前置 determinism-matrix /
  provenance-lock / audit)重跑的完整产物。计划 digest 与正式运行
  同为 `r15ap-0da8dc45fe38…`。
- 与正式件(`../route_c_stage2_6_1_repair19/cue_contract_audit.json`)
  的逐键比对:p_contract / monte_carlo / analytic_terms /
  model 与 validation 的 block_cluster 与 aggregate recall
  **全部深度相等**;唯一 top-level 差异键 = `audit_utc`(时间戳)。
- 结论:固定代码下 audit 完全确定;原样重跑复现 FAIL(z=+2.32)。
  归因报告见
  `stage2_6_1/report/route_c_stage2_6_1_repair19_cueaudit_attribution.md`
  「历史抽取散布的真实机制」节。
- 产生方式:工程坐标(CURRICULUM261_R17_STATE_ROOT 指向
  r17_audit_redraws/state;未触碰正式 design/semantic namespace、
  admission 面、正式 state root)。部署树完整重抽序列在
  `/home/cryptorl/projects/crypto_rl/r17_audit_redraws/`
  (draw_1..7 = r10 机械面 7 次全同,证单态确定性;draw_head =
  本件;draw_1b = r10 机械面另一产物)。
