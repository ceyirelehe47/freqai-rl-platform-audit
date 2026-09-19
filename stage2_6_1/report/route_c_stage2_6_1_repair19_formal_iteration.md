# Route C 阶段 2.6.1 — R19 正式迭代报告(终态:cue-audit 统计 FAIL)

- 迭代: route_c_stage2_6_1_repair19(一次性正式尝试;journal 永久终态)
- Commit A = 7017add177c113ed47297fbea0d65a29682ca6cc(tree f3c0efb338b3…)
- 准入: cur261-r17-formal-admission-v2,admission_id
  route-c-r19-attempt-20260920-7017add1-r1(签发 2026-09-19T23:12:47Z,
  substance:plan digest 实算一致 + 回归证据 v8 = 2296/2289/0/0/7,
  record sha256 d6977c13…)
- 前置链: 开放门 §4.1/§4.2 闭环(7776aa9d)→ R19 命名空间族接线
  (1d20705b)→ 种子守卫修复(7017add1);链外 provenance-lock 落位
  (r17gtrec-3112e5de…);入口自检双场景通过(前置缺失/准入缺失
  均零副作用早拒)

## 终态事实

- 链步 1 provenance-verify:**通过**(R17/R18 两次尝试均死于此步;
  本轮链外前置义务首次完整履行)
- 链步 2 determinism-matrix:通过
- 链步 3 cue-audit:**FAIL(统计)** → 迭代终态(§12;不修代码继续)

## cue-audit FAIL 定位(artifacts/cue_contract_audit.json)

- p_contract(analytic)= 0.950432;MC = 0.950253(|diff| 0.000179 ✓)
- model corpus = 0.949237,CI95 [0.945558, 0.952843] → ✓
- **validation corpus = 0.945931,CI95 [0.942102, 0.949672] → ✗
  (analytic 高于 CI 上界 0.00076;validation_corpus_ok=False)**
- 其余叶子全过:once/attempts 逐位一致(n=50)、k_mean 容差、
  三路 MC 闭合、aggregate 重算、tail mirror、global-K(非不定)

即:三路闭合审计在"analytic ∈ 双 corpus CI95"上被验证语料拒绝。
这是该组审计坐标下的真实统计事实;按合同统计 FAIL 不可救援,
design plan 未锁定,零科学 exposure(design/calibration/final
namespace 未访问,fail_closure 已封口)。

## 工程面结论(与统计面分开)

- 准入 v2 首次真实行使:签发(实质验证)→ 入口只校验 → CLI 单点
  消费 → 链步执行 → 终态写面,全链零缺陷(无双消费/无早耗/
  无守卫误拒);
- 开放门 §4.1 统一合同未达设计步(轮次止于 audit);§4.2 实质绑定
  在真实签发/消费中工作正常;
- rt(r19 工程族)17/17 ok=True(run 20260919T214411Z_1757)先证链路,
  探针(calibration 全过 + final 设计内拒付)形态与 R18 一致;
- 失败模式归类:**统计 FAIL**(非工程 FAIL;对照 R17/R18 = 工程
  FAIL 于第 1 步)。

## 处置边界

- R19 journal/abort/归档原样永久终态;不复活、不换坐标重抽救援;
- 预注册时披露事项:签发前移除 R18-r2 已消费 v1 准入残件
  (终态迭代;原件保全 work/gate_closure_20260920/
  removed_r18r2_admission_20260917.json);
- 下一轮(R20 处方)属于外部审查方;p_contract/审计坐标的统计
  处置(如 p_contract 点估计与语料 CI 的相容性问题)不在本轮
  自主权限内。

## 证据索引

- 终态: artifacts/route_c_stage2_6_1_repair19/state/(journal 11 事件、
  abort marker、chain_result、fail_closure_summary)
- 审计原件: 同目录 cue_contract_audit.json / cue_event_trace.jsonl /
  cue_audit_plan.json(+digest)
- 启动/请求: r17_formal_requests/(本请求 launch_evidence、
  admission_granted、chain_run.log);链外锁 gate_topology_
  reconciliation.json
- 签发/消费: r17_admission_issued.jsonl(末条)、
  state/r17_admission_consumed.jsonl
- 工程前置: rt run r17_rt_runs/20260919T214411Z_1757(17/17)、
  探针 work/r19_formal_feasibility_probe.json、回归 v8 证据
  work/gate_closure_20260920/regression_evidence_v8.json
