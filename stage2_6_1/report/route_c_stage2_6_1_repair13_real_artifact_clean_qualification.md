# Stage 2.6.1 Repair R13 — Real-Artifact CLI Round-Trip Closure + Immutable Implementation Freeze + One-Shot Clean Qualification

**最终判定:R13 = FAIL(诚实;final qualification 一次性判定 FAIL,唯一失败检查 c2_semantics_pass)**
**Stage 2.6.1 = FAIL(final qualification 未过;接口闭环目标本轮已达成)**
**Stage 2.6.2 = 未开始(C3 PPO Branch D 仍为独立 blocker;本轮不自动进入)**

## 1. 精确起点与分支

- baseline(R12 Commit B / R13 唯一允许起点):
  `960dbe19701901f9262614aadf8b7f97742fab4d`
- 分支:`route-c-stage2-6-1-repair13`(merge-base == baseline,机器验证)
- Commit A(实现冻结):
  `47d3f22f4df97855423ee748f3aa2df5497422a6`
- Commit B(仅 results/artifacts/report):见 git log(本提交)
- 工作树:Commit A 后源码/测试/依赖/配置语义零修改(freeze 复验:
  source tree digest r13src-f8e5c52…;final qualify 内复验通过)
- vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(verified)

## 2. R12 失败的机械绑定(不可重解释)

- R12 提交链:96446f2(R11 B)→ 75a66dd(R12 A/冻结)→ 960dbe1
  (R12 B/结果);git 机器验证 B 的父提交即 A —— R12 无 A′/A2/hotfix,
  干净双提交链(R13 historical binding 新增 r12_clean_two_commit_chain
  检查)。
- R12 失败定性:lock-plan 阶段 producer/consumer artifact 接口不一致
  (冻结源码读 `preprocessor_bundle_{calibration,holdout}.json` 的
  `'bundle_hash'`,实际键 `'preprocessor_bundle_hash'`;KeyError at
  curriculum261_r12_cli.py:1717)。统计链全 PASS 但不进入 R13。
- R12 治理缺口(非硬失败):pre-freeze rehearsal 用 synthetic 输入,
  未覆盖真实落盘 artifact 读取 —— R13 直接动因。
- R13 接口审计另发现 R12 潜伏缺陷:sealed preflight 证据文件名错配
  (R3/R4 时代文件名;R12 未活到该步未触发;已绑定于
  r12_iteration_failure_binding.json 的 latent_defect_2 字段)。

## 3. 本轮接口修复(Commit A 前;§四)

1. **canonical artifact interface(§四-1)**
   - 唯一合法键名 `preprocessor_bundle_hash`(producer
     RouteCPreprocessorV2.identity());
   - fail-closed accessor `read_preprocessor_bundle_hash`
     (curriculum261_r13_plan.py):artifact 缺失 / canonical 字段缺失 /
     非法值全部报错;错误信息含 artifact 路径、缺失字段名、consumer
     command;旧键名 `'bundle_hash'` 不得冒充(回归锁测试
     test_legacy_bundle_hash_key_cannot_impersonate);禁止同时宽松
     接受两种键名;
   - cmd_lock_plan 经 accessor 读取 main/holdout bundle。
2. **sealed preflight 证据文件名对齐(§四-2)**
   - 检查清单改为真实 producer 产物:preprocessing_v2_requalification
     .json / robustness_gate.json / supervised_learnability_main.json /
     supervised_learnability_holdout.json / prelock_static_preflight
     .json(R12 潜伏缺陷的修复;测试 TestSealedPreflightEvidence
     Filenames 锁定)。
3. **cleanliness 读取修复**
   - write_path_cleanliness_r13 从无 producer 的
     calibration_report_{main,holdout}.json 改为真实产物;
     calibration_state 由 bundle identity + calibration_evidence 机械
     派生(本轮 fail_path_cleanliness.json 实测输出 main/holdout
     executed)。
4. **producer → artifact → consumer 全仓库审计(§四-2)**
   - artifact_interface_audit():14 条边,逐边记录 producer/consumer
     命令、关键字段、canonical identity 含义、R12 缺陷状态与
     rehearsal 覆盖步骤;rehearsal 运行后回填
     covered_by_rehearsal(14/14 全覆盖)。

## 4. R13RealArtifactCliRoundTrip-v1(§四-4;Commit A 前 PASS)

- 最终判定:**PASS**(chain rc 全 0 / boundary True / purity True /
  coverage True);rehearsal plan digest
  qp12-9c14137b1d650ac24c4e432db5e4563adfb4cac07e0267da5689067ee4e2c801;
  bundle_hash_consistent=True;exposure one-shot enforced。
- 13 步 subprocess 正式 CLI 全链:determinism-matrix → audit(freeze
  +R8-R12 绑定)→ cue-audit --rehearsal(500+500,rt namespace,pass
  p_contract=0.95048)→ preplan-smoke → plan-roundtrip →
  design-plan-lock --rehearsal → design(40×2×3 + semantic 160×2 +
  marginal,rt namespace,机械选择 historical n=15)→ calibrate
  --rehearsal(正式生成规模 + 全量 supervised 3 seeds)→
  preflight-static → lock-plan(canonical accessor 实证)→
  preflight-sealed(证据文件名对齐实证)→ qualify --rehearsal(治理
  外壳全量:plan/pack/attestation 加载 + exposure marker + 文件锁 +
  freeze 复验;rt final namespace 缩小样本;verdict 不作资格判定)→
  smoke;随后独立进程字段级边界探针 + 正式 namespace 纯净性(ledger
  扫描零命中)+ 接口覆盖回填。
- 工程重试(诚实披露,全部记录于 real_artifact_cli_roundtrip.json
  与逐步 argv/rc/digest):
  - 第 1 抽(rt_):supervised 配置缺陷(1 seed + epochs=2 无法满足
    正式 gate 的 min 2/3 seeds —— 工程 bug,已修复为 3 独立 rt seeds
    + 正式训练配置)+ c13 c3 两处统计边缘(main c3_cost_ignorant/D0
    margin 0.00098 vs κ·SE 0.00244;holdout D0-D1 gap 0.00695 vs
    0.00770;对照 R12 正式同项 ratio 1.23-1.58,属已知结构性偏紧
    条件上的抽样运气);
  - 第 2 抽(rt2_):nonformal 前缀表缺 "rt2_" 条目被路由合同拒绝
    (工程 bug,已修复);
  - 第 3 抽(rt2_ + c13 评估扩样 60/rung,rehearsal-only 规模;SE 缩
    ~√6 使真实效应主导 gate;正式链 CALIBRATION_PAIRS_PER_RUNG=10
    冻结不变):**PASS**。

## 5. 测试(§四-5)

- Commit A 前全量:781 passed / 1 skipped / 0 failed(skipped =
  r12 governance 分支名断言在非 repair12 分支按设计跳过;R13 等价
  断言由 test_curriculum261_r13_governance 承担);
- 新增 test_curriculum261_r13_roundtrip.py(accessor 正/负路径 +
  真实 producer 输出 + subprocess 独立读取 + R12 缺陷回归锁 + CLI
  独立进程 namespace-integrity rc0 / audit 缺 freeze rc1 + design
  payload rehearsal 覆盖 + exposure one-shot + 接口审计表)+
  test_curriculum261_r13_governance.py(historical binding / R12
  abort binding / freeze 治理 / rt 路由合同 / sealed 证据文件名 /
  cleanliness 读取 / api 注册与 qualification 守卫 / rt profiles)。
- Commit A 后未运行任何测试修改(冻结;失败路径不运行 full-cold)。

## 6. 正式链结果(Commit A 后;§八顺序)

| 步骤 | 结果 | 关键数值 |
|---|---|---|
| audit | PASS | freeze 锚定 47d3f22(tree r13src-f8e5c52…);ancestry/R11/R12 绑定/依赖/入口/确定性合同全过 |
| cue audit(500+500) | PASS | p_contract=0.950444;model recall 0.950374 CI95[0.946777,0.953865];validation 0.950667;once/attempts bitwise 一致(n=50) |
| TailMirrorBoundIntegrity-v2 | PASS | 确定性硬 gate |
| C2MirrorCountGlobalAudit-v1 | PASS | 528 eligible cells;T_obs=3.0732(argmax=model/position/t=148);tier1 B=50,000;p_global=0.699686;CP99 下界≫α=0.05 |
| design(3 候选机械选择) | PASS | semantic gate PASS(160×2);合格组合 1 个;selected=c2l_historical_control,n=20;maximin=0.0696;pack r13pk-b68280456e1f6b0cd624748ba4cfaec28de9aa95d1d922003ed76a6f41ada3e1a |
| calibration main | PASS | preprocessing/routing/supervised/curriculum/density/conditioning 全 True |
| calibration holdout(独立) | PASS | 同上;pooled_rescue_used=False |
| generation evidence | PASS | expected=observed=792 调用;missing/orphan/bad=0;block 问题 0 |
| preflight-static | PASS | vendor pin/imports/PPO smoke 静态 |
| **lock-plan** | **PASS** | qualification plan 锁定 qp12-2934cc579ef1a6566d697ae68f23383021f914aadd99cc53448c65316e05d466 —— **R12 崩溃点正式闭合**(canonical accessor 实读真实 calibration artifacts) |
| sealed preflight | PASS | attestation r13fa-f02266a51f147933b440cc23030e7b3f201f29cb8958409f73c04740e7102aa0(证据文件名对齐实证) |
| **final qualification(一次性)** | **FAIL** | exposure 1 次(marker terminal=failed);verdict=FAIL;160 core pairs + 80 independent + 160 semantic blocks + 1760 episodes;reference equivalence unexplained=0;**唯一失败检查 c2_semantics_pass** |
| PPO smoke | 未执行 | §八顺序解锁:final FAIL ⇒ 不解锁 |
| full-cold | 未执行 | 同上 |

### 6.1 失败项精确诊断(机械重放;runner/r13_diag_final_semantics.py)

- c2_semantics_pass = local_cue_independence(PASS)AND
  context_observability(PASS)AND cue_payoff_separation(**FAIL**);
- cue_payoff_separation 四子项:
  - cue_recall_ge_min=**False**:cue recall 点估计 **0.948571 <
    cue_recall_min 0.95**(4200 正 cue 命中 3984;差 6 个事件;
    二项 SE≈0.0034,约 0.4 SE 的抽样噪声级边缘);
  - cue_precision_ge_min=True(0.965351≥0.85);
  - non_cue_fp_le_max=True(0.000546≤0.01);
  - payoff_bar_false_cue_le_max=True(0.015119≤0.06);
- 对照:dedicated semantic corpus(160 blocks)的 cluster-bootstrap
  LCB gate(≥recall_floor 0.9304)**PASS**(qualification_cue_
  semantics.json pass=True)—— 失败仅发生在 final 语料 20 个 matched
  block 上按 R6 冻结口径的**点估计**阈值(cue_recall_min=0.95);
- 定性:一次性 final 语料的纯统计边缘失败;非接口缺陷(全部接口
  边界含 R12 崩溃点已通过);非阈值/统计合同缺陷(R6 冻结口径
  逐位未动);禁止以任何方式"救援"(§六/§九)。

## 7. 失败处置(§九;全部执行)

1. 正式流程在 qualify 后立即停止(smoke/full-cold 未解锁未执行);
2. 源码零修改(冻结;Commit A 后无任何变更);
3. 无 A′/replacement freeze;
4. 全部 raw logs 保留(raw_logs/*.log = 13 个正式链步骤日志 +
   rehearsal/determinism 日志)+ 全部 invocation envelopes(
   generation_invocation_ledger.jsonl);
5. r13_iteration_aborted.json 已写(机械 reason;含全部通过项与
   唯一失败项数值);
6. fail_path_cleanliness.json 已写(机械读取:plan locked、
   exposure 1 次 terminal=failed、final namespace 执行 1 次、
   calibration main/holdout executed、pooled rescue False、
   source_changed_after_freeze=False);
7. r13_fail_closure_summary.json:ppo_smoke_executed=False、
   full_cold_executed=False;
8. 本提交 = results-only Commit B。

## 8. R12 → R13 对比结论

- R12 失败于 lock-plan 的 artifact 接口缺陷(calibration 完成后);
- R13 同一位置(lock-plan)成功,且全部 producer/consumer 读写边界
  在 Commit A 前经真实 CLI round-trip rehearsal 实证覆盖;
- R13 前进到 final qualification 并在**统计层面**诚实 FAIL(cue
  recall 点估计 0.948571 < 0.95,差 6 个事件);
- 两轮失败模式完全不同:R12 = 工程接口;R13 = 一次性统计边缘。
  Stage 2.6.1 的剩余风险不再是工程接口,而是 final 语料的统计边缘
  (c2_semantics 点估计口径;dedicated semantic corpus 的 cluster
  LCB 口径通过,两口径在同一语料族上的不一致值得 R14 审视 —— 仅
  作为观察记录,本轮不修改任何口径)。

## 9. 三层结论

- **R13 = FAIL**(final qualification;唯一失败检查 c2_semantics_
  pass;不可追认/撤销;下一轮必须 R14 + 全新 namespace);
- **Stage 2.6.1 = FAIL**(final qualification 未通过;本轮达成了
  R13 的工程目标:接口闭环 + 真实 CLI rehearsal + lock-plan/sealed/
  qualify 链路全部打通);
- **Stage 2.6.2 = 未开始**(C3 PPO Branch D 仍为独立 blocker;
  不因本轮结果自动进入;须独立审查后决定)。

## 10. 复核路径

- Git 链:960dbe1 → 47d3f22(Commit A)→ 本提交(Commit B);
- artifacts:stage2_6_1/artifacts/repair13/(audit/cue/global K/
  design/calibration/lock-plan/sealed/final/abort/cleanliness +
  real_artifact_rehearsal/ + determinism/ + raw_logs/);
- 复算:全部 digest 从 git 对象与文件内容机器读取;qualification_
  plan_digest_r13.txt 与 plan 内自报一致;fail 诊断脚本
  runner/r13_diag_final_semantics.py 可独立重放(六要素解锁后
  qualification_r13 坐标确定性重生成,与 final 逐位一致)。
