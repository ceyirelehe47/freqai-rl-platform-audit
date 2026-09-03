# Stage 2.6.1 Repair R13 — Real-Artifact CLI Round-Trip Closure + Immutable Implementation Freeze + One-Shot Clean Qualification

> 状态:进行中(本文件在 Commit B 时定稿;以下为执行中骨架,最终数值以
> artifacts 为准)。

## 1. 精确起点与分支

- baseline(R12 Commit B / R13 唯一允许起点):
  `960dbe19701901f9262614aadf8b7f97742fab4d`
- 分支:`route-c-stage2-6-1-repair13`(merge-base == baseline,已验证)
- 工作树:clean(实现期间的全部修改均在本分支上)
- vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(WSL
  `~/projects/crypto_rl/vendor/freqtrade`,verified)

## 2. R12 失败的机械绑定(不可重解释)

- R12 提交链:96446f2(R11 B)→ 75a66dd(R12 A/冻结)→ 960dbe1
  (R12 B/结果);git 机器验证 B 的父提交即 A —— R12 无 A′/A2/hotfix,
  是干净双提交链(R13 historical binding 的 r12_clean_two_commit_chain)。
- R12 失败定性:lock-plan 阶段 producer/consumer artifact 接口不一致
  (冻结源码读 preprocessor_bundle_{calibration,holdout}.json 的
  `'bundle_hash'`,实际键 `'preprocessor_bundle_hash'`;KeyError at
  curriculum261_r12_cli.py:1717)。统计链(cue audit p=0.950442/global K
  T_obs=3.2329 p=0.511770/tail integrity/design/calibration/holdout)
  全部 PASS 但不进入 R13。
- R12 治理缺口(非硬失败):pre-freeze rehearsal 用 synthetic 输入,
  未覆盖真实落盘 artifact 读取 —— R13 直接动因。
- R13 接口审计另发现的 R12 潜伏缺陷:sealed preflight 证据文件名错配
  (R3/R4 时代文件名 vs 实际 producer 文件名;R12 未活到该步未触发)。

## 3. 本轮接口修复(Commit A 前)

1. **canonical artifact interface(§四-1)**
   - 唯一合法键名 `preprocessor_bundle_hash`(producer
     RouteCPreprocessorV2.identity());
   - fail-closed accessor `read_preprocessor_bundle_hash`
     (curriculum261_r13_plan.py):artifact 缺失/canonical 字段缺失/
     非法值全部报错;错误信息含 artifact 路径、缺失字段名、consumer
     command;旧键名 `'bundle_hash'` 不得冒充(单元测试含 R12 缺陷
     回归锁);禁止同时宽松接受两种键名。
   - lock-plan(cmd_lock_plan)经 accessor 读取 main/holdout bundle。
2. **sealed preflight 证据文件名对齐(§四-2)**
   - 检查清单从
     `preprocessing_robustness_gate.json / curriculum_robustness_gate.json
     / supervised_learnability.json`(R3/R4 时代,无 producer)
     改为 calibrate/preflight-static 实际产物
     `preprocessing_v2_requalification.json / robustness_gate.json /
     supervised_learnability_main.json / supervised_learnability_holdout.json
     / prelock_static_preflight.json`。
3. **cleanliness 读取修复**
   - `write_path_cleanliness_r13` 从无 producer 的
     `calibration_report_{main,holdout}.json`(导致 calibration_state
     恒 absent)改为读取真实产物;calibration_state 由 bundle
     identity artifact + calibration_evidence 机械派生。
4. **producer → artifact → consumer 全仓库审计(§四-2)**
   - `artifact_interface_audit()`(curriculum261_r13_cli):14 条边
     (calibrate→lock-plan、calibrate-gate→lock-plan、
     calibration-evidence→lock-plan、preprocessing-robustness→
     lock-plan+sealed、supervised→sealed、static-preflight→sealed、
     lock-plan→sealed+qualify、sealed→qualify-init、pack→四消费方、
     qualify-outputs→smoke+downstream、smoke-outputs→downstream、
     cue-audit→design-plan-lock、design-plan→design+calibrate、
     determinism→audit),逐边记录 producer/consumer 命令、关键字段、
     canonical identity 含义、R12 缺陷状态与 rehearsal 覆盖步骤;
     rehearsal 运行后回填 covered_by_rehearsal。

## 4. R13RealArtifactCliRoundTrip-v1(§四-4;Commit A 前必须 PASS)

- 语义:隔离 rehearsal 目录(lock dir 下 real_artifact_rehearsal/)+
  rehearsal-only namespace;每步 subprocess 正式 CLI
  (`python -m rl_curriculum.curriculum261_r13_cli ...`,
  `CURRICULUM261_R13_LOCK_DIR` 指向隔离目录);上一步真实写出的
  artifact 是下一步真实读取的输入;记录逐步 argv/rc/stdout 尾部/
  输入输出 artifact sha256;禁 monkeypatch/synthetic dict 冒充。
- 链(13 步):determinism-matrix → audit(含 freeze+R12 绑定)→
  cue-audit --rehearsal(500+500,rt namespace)→ preplan-smoke →
  plan-roundtrip → design-plan-lock --rehearsal → design(40×2×3 +
  semantic 160×2 + marginal,rt namespace)→ calibrate --rehearsal
  (正式生成规模 + rt2 namespace + 全量 supervised 3 seeds)→
  preflight-static → lock-plan(canonical accessor)→
  preflight-sealed(证据文件名对齐)→ qualify --rehearsal
  (治理外壳全量 + rt2 final namespace 缩小样本;verdict 不作资格
  判定)→ smoke;随后:独立进程字段级边界探针(plan loader/sealed
  attestation/qualification outputs/PPO smoke reader/exposure one-shot
  探针)+ 正式 namespace 纯净性(ledger 扫描零命中)+ 接口审计覆盖
  回填。
- 工程重试记录(诚实披露):
  - 第 1 抽(rt_ namespace):calibrate FAIL —— (a) supervised 配置
    缺陷(1 seed + epochs=2 无法满足正式 gate 的 min 2/3 seeds;工程
    bug,已修复为 3 独立 seeds + 正式训练配置);(b) c13 c3 两处
    统计边缘(main c3_cost_ignorant/D0 margin 0.00098 vs κ·SE 0.00244;
    holdout D0-D1 gap 0.00695 vs 0.00770)—— 对照 R12 正式同 margin
    ratio 1.23-1.58,属已知结构性偏紧条件上的抽样运气,非代码缺陷。
  - 第 2 抽(rt2_ namespace 前缀登记):calibrate 因 nonformal 前缀表
    缺 "rt2_" 条目被路由合同拒绝(工程 bug,已修复)。
  - 第 3 抽:结果见 §4.1。

## 5. 测试(§四-5)

- 全量 Stage 2.6.1 / Route C 套件:781 passed, 1 skipped
  (r12 governance 的分支名断言在非 repair12 分支按设计跳过;
  r13 等价断言由 test_curriculum261_r13_governance 承担);
- 新增:test_curriculum261_r13_roundtrip.py(accessor 正/负路径 +
  真实 producer 输出 + subprocess 独立读取 + R12 缺陷回归锁 +
  CLI 独立进程 + design payload rehearsal 覆盖 + exposure one-shot +
  接口审计表)+ test_curriculum261_r13_governance.py(historical
  binding/R12 abort binding/freeze 治理/rt 路由合同/sealed 证据
  文件名对齐/cleanliness 读取/api namespace 注册与守卫/rt profiles)。
- 最终 Commit A 前全量重跑:见 §5.1。

## 6-19. 正式链结果(Commit A 后;定稿时填写)

(占位:audit / cue audit / global K / tail integrity / design /
selection / pack / calibration / holdout / lock-plan digest /
sealed preflight / exposure / final qualification / PPO smoke /
full-cold / evidence completeness / cleanliness)

## 20. 三层结论

(占位:R13 verdict / Stage 2.6.1 verdict / Stage 2.6.2 verdict)
