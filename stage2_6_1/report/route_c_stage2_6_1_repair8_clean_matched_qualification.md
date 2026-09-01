# Stage 2.6.1 Repair R8 — Corrected Cue Contract、Dedicated Semantic Power 与 Clean Matched Qualification(诚实 FAIL)

- 迭代:`curriculum_iteration = r8`
- 结论:**FAIL(§8.4 一次性硬规则:design plan 锁定后 evaluator import 错误 → R8 永久结束)**
- 本轮基线:`11951f6d9b2f5fa63b17e3857aba92b330da029e`(R7 诚实 FAIL checkpoint;其父提交 `7970d2096b6a5a93a85d32620b9b2b3a24826568` = R6 checkpoint,已验证)
- vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean,已验证)
- 执行环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / `~/projects/crypto_rl`
- 发布仓库:ceyirelehe47/freqai-rl-audit `stage2_6_1/artifacts/repair8/`

## 0. 结论摘要

R8 完成了全部 pre-plan 基础设施并首次拿到全绿的合同审计证据,但在
design plan 锁定后的 candidate 评估阶段触发 §8.4 一次性硬规则:

1. **Plan Digest Roundtrip 修复成功并经真实生产路径验证**:R7 的
   `design_plan_digest` 自引用缺陷修复(digest 复算排除
   `(locked_utc, design_plan_digest)` 双字段);CLI `plan-roundtrip`
   子命令在临时目录执行 build→lock→新进程 load→recompute→compare→
   不可覆盖→无 alternate loader,14/14 检查全部通过;
2. **Cue Semantic Contract v2 三路闭合 audit PASS**(修正 mirror
   边界 + exact noise replay + per-event K + 2×500 block direct
   generator corpora):corrected p_contract = 0.950476,MC 差
   0.000269,两个 direct corpus 实测 0.9499/0.9490 均落在解析值
   容差与双侧 95% cluster CI 内;重放误差 ~2.2e-16;
3. **Dedicated semantic corpus(160 blocks)方向被验证**:validation
   语料 gate 全过(unique 4153;point 0.950638;LCB 0.945783 ≥ floor
   0.930476;non-cue FP UCB 0.000984);main 语料 gate 同样通过
   (执行流推进到 candidate 生成可证),但其 artifact 因一个
   artifact-writer 缺陷被覆盖丢失(§6.3);
4. **FAIL 触发点**:candidate 评估的密度环节 `from
   curriculum261_r6_pairs import c2_density_summary` 抛 ImportError
   ——该函数实际位于 `curriculum261_r5_pairs`(R7 的潜在抄写缺陷,
   R7 因 shared gate 先失败从未执行到该行;R8 测试因 monkeypatch
   `_evaluate_candidate_matched_r8` 也未覆盖)。按 §8.4:plan 锁定后
   任何 import 错误 → R8 永久结束。aborted marker 与 ledger 已按
   合同写入,plan 保留未删未重锁,任何 R8 namespace 不得复用。

失败是工程缺陷(import 路径),不是统计方向问题;全部统计证据
(audit 三路闭合、semantic corpus gate、plan roundtrip)都在本轮
首次拿到且全绿,为 R8.1 提供了直接可复用的基础设施。

## 1. R7 为什么 FAIL?R7 shared cue 结果是什么?

R7 的 shared cue gate 在 40-block candidate design corpus 上计算
block-cluster LCB:

| corpus | point | LCB | floor | 判定 |
|---|---|---|---|---|
| design_r7_matched_main | 0.926033 | 0.912046 | 0.930399 | FAIL |
| design_r7_matched_validation | 0.947013 | 0.935515 | 0.930399 | PASS |

main 的 LCB 缺口 = 0.9304 − 0.9120 = 0.0183;40 blocks 的 bootstrap
SE ≈ 0.0069–0.0085,单侧 LCB 偶然失败概率过高(样本量不足的结构性
问题)。R8 承认该事实为硬输入:main FAIL 不是测试工具误报,也不是
可直接忽略的坏 seed。

## 2. R7 plan loader 为什么无效?R8 如何修复 digest roundtrip?

R7 writer:先对 payload 算 digest,再把 `design_plan_digest` 写回
plan;R7 loader 复算时只排除 `locked_utc`,不排除被写回的 digest
字段 → 任何 R7 lock 产物上 `load_locked_design_plan_r7` 必然
mismatch → 正式 `r7-cli design` 子命令不可用,R7 实际由未入库的
临时 driver(`/mnt/e/trading/r7_drive_design.py`)执行。

R8 修复(§8):

- `design_plan_digest_r8` 复算排除 `(locked_utc, design_plan_digest)`
  双字段(与 pack digest 的正确模式一致);
- `lock_design_plan_r8` / `load_locked_design_plan_r8` / digest
  recompute / code identity verify / design execution 全部使用同一份
  仓库内实现(`curriculum261_r8_design.py`),CLI `design` 子命令为
  唯一正式入口;
- 禁止临时 driver:本轮全程零临时驱动(R8 的正式执行只使用
  `python3 -m rl_curriculum.curriculum261_r8_cli <cmd>` 与 pytest);
- §8.3 真实生产路径 roundtrip 验证:CLI `plan-roundtrip` 子命令在
  临时目录对 design plan(真实 payload)与 qualification plan(合成
  合法 payload)分别执行 build→lock→**新进程 load**→recompute→
  compare→no-data validation(candidate grid/formal options/semantic
  blocks=160)→已存在不可覆盖→digest 文件一致→无 alternate loader
  (源码扫描 plan 文件名字面量只出现在权威模块)→digest 不自引用,
  **14/14 检查通过**(`plan_roundtrip_validation.json`);
- `design-plan-lock` 强制要求 roundtrip 证据存在且 PASS,否则拒绝
  锁 plan(测试 `test_design_plan_lock_requires_roundtrip` 锁定该行为)。

## 3. R7 p_contract 的尾部边界错在哪里?正确的 mirror source 上界?

真实 `paired_noise()` 只有 `source_t + 16 < n` 时才生成 source pair
(尾部 break:`t + 16 >= n` 整体跳过),因此 **source bar 最大值是
`n − 17`,不是 `n − 1`**(n=288 → 最后 source = 271)。

cue bar t 的历史 mirror source 候选(R8 权威实现
`curriculum261_r8_noise_replay.mirror_candidate_positions`):

```
lo = max(1, t - 16)
hi = min(t - 8, n - 17)      # R7 错误:min(hi, n - 1)
只有 hi >= lo 时才存在候选
```

影响(n=288):t=280 处 R7 高估 C(t)=9(正确 8);t=287 处 R7 高估
9(正确 1)。高估 C(t) → 高估混合方差 → q(t) 偏低 → p_contract 偏低
→ recall floor 偏宽松(R7 的 0.9304 略低于真实解析口径)。

## 4. exact noise replay 如何实现?per-event K 如何落盘?

`curriculum261_r8_noise_replay.py`(audit-only,零修改 api/c2/r6_tape):

- **noise seed 重建**:以与 `generate_matched_block_once` 完全相同的
  路径(matched_tape 实例的 `derive_seed({**params, "_noise":
  "market"}, block_seed)`)重建 noise seed——alpha/wick_kappa/rung/
  pair_variant 均被派生剔除,noise seed 只依赖 block_seed 与结构参数;
- **RNG 调用顺序逐位复刻**:逐 source bar `t=1..(t+16<n)` 依次消耗
  3 个抽签 `standard_normal → random(sign) → integers(8,17)(gap)`;
  相同 sign/gap/累加(`col[t]+=amp; col[t+gap]-=amp`)/尾部 break;
- **对拍基准**:`replayed_noise == actual_returns − pulse − payoff`
  (R6 冻结的 `_reconstruct_eps` 反解);实测最大绝对误差
  **2.22e-16(audit model corpus)/ 2.20e-16(validation)**,远优于
  合同容差 1e-12;真实 `paired_noise()` 与 replay 的直接对拍为
  **逐位相等(差 = 0.0)**;
- **per-event K 落盘**(§11):每个 positive cue event 一行
  `cue_event_trace.jsonl`(block index / cue bar / primary 是否存在 /
  K_actual / mirror source positions / mirror_candidates / effective
  sigma(bps)/ actual noise / cue read / detected)——audit 两个 corpus
  共 25,924 行;aggregate(K histogram、位置分布、recall、tail)由
  `summarize_events` 从 event table 复算,audit 内置复算一致性校验
  (`aggregate_recompute_ok = True`);
- **逐位置 exact bound check**:每个事件的全部实际 mirror source 落
  在修正后候选集合内(零统计噪声的边界验证)。

## 5. 三路独立闭合(audit)结果

| 路 | 结果 |
|---|---|
| A. Analytic(修正 q(t) × model corpus 位置直方图) | **p_contract = 0.9504755515680544**;recall_floor = max(0.90, p−0.02) = **0.9304755515680544** |
| B. Event MC(1,000,000 events,seed 20261008) | p_hat = 0.950207;\|MC − analytic\| = **0.000269 ≤ 0.001** ✓ |
| C1. Direct generator `cue_contract_model_r8`(500 blocks,once-mode,sentinel) | 12,974 unique 正 cue;empirical = **0.949900**;analytic(条件权重)= 0.950476;\|diff\| = 0.000576 ≤ max(3×SE,0.005)=0.005288 ✓;双侧 95% CI [0.946391, 0.953350] **包含 analytic p_contract** ✓ |
| C2. Direct generator `cue_contract_validation_r8`(500 blocks) | 12,950 unique 正 cue;empirical = **0.948958**;analytic(条件权重)= 0.950399;\|diff\| = 0.001442 ≤ 0.006077 ✓;双侧 95% CI [0.944912, 0.952855] **包含 analytic p_contract** ✓ |

tail-position 专项(最后 24 bars):model corpus 819 tail 事件、
validation 793 tail 事件,pooled 实测 vs 条件解析差均在
max(3×cluster SE, 0.005) 内 ✓;逐位置 K 均值 vs Binomial(C(t),1/9)
检查:226/213 个 gated 位置(≥30 事件)全部通过(阈值 z=4.0,
Bonferroni 校正——3σ 在 ~250 个位置的多重比较下联合假警报率约
50%,不可用)✓;无未解释模型偏差 ✓。**audit PASS。**

## 6. Dedicated semantics(§14/§15)

- **样本量预注册**:semantic_blocks_per_corpus = **160**(40→160
  使 block-cluster SE 理论减半;在任何 R8 design data 生成前锁定;
  禁止数据后 160→240 扩样/第三 corpus/合并/删除——本轮未发生任何
  扩样);min unique positive cues = **3600**;
- **语料**:`cue_semantic_design_main_r8` / `cue_semantic_design_validation_r8`,
  各 160 matched blocks(sentinel ladder = 冻结 cur261-c2-v9 默认
  D0-D3,candidate-independent;attempts-mode,first_pass_rate = 1.0);
- **validation 语料结果(artifact 保留)**:4153 unique 正 cue(≥3600 ✓);
  point 0.950638;**LCB 0.945783 ≥ floor 0.930476**(余量 +0.0153);
  non-cue FP UCB 0.000984 ≤ 0.01 ✓;per-event K 完整 ✓;noise replay
  完整 ✓;canonical consistency ✓;coverage 完整 ✓;tail 诊断(259
  事件,recall 0.9691,报告性)——8/8 检查全过;
- **main 语料**:gate 同样通过(其结果使流程推进到 candidate 生成,
  §7 的执行流可证),**但其落盘 artifact 因 artifact-writer 缺陷
  丢失**(见 §6.3)。

### 6.3 两项工程缺陷的完整披露(诚实 FAIL 的根因)

1. **主因(evaluator import 错误)**:`_evaluate_candidate_matched_r8`
   内 `from rl_curriculum.curriculum261_r6_pairs import
   c2_density_summary` ——该函数实际定义于
   `curriculum261_r5_pairs`(r7_design L508 同样写错;R7 的 design
   在 shared gate 即 FAIL,从未执行到该行,故未暴露)。R8 的 45 项
   测试中 candidate 评估函数被 monkeypatch 替换,该 import 路径无
   测试覆盖 → preplan 工程验证(§20)未拦截。plan 锁定
   (03:46:58)→ design_data_started(03:47:00)→ semantic 双语料
   生成并 gate 通过 → candidate blocks 生成 → 评估阶段 ImportError
   → §8.4 `write_r8_iteration_aborted`(03:49:58)→ R8 永久结束;
2. **次因(artifact writer 缺陷)**:semantic 语料落盘文件名判定使用
   `namespace.endswith("main")`,而 namespace 为
   `cue_semantic_design_main_r8`(以 `_r8` 结尾)→ 两个语料都写入
   `semantic_design_validation.json`,main 的数值被 validation 覆盖。
   main gate PASS 的事实由执行流证明(semantic 阶段的 FAIL 短路分支
   未触发,流程进入 candidate 生成),但其数值证据落盘丢失。

两项均属 §8.4 明列的 "import 错误 / artifact writer bug";按合同
不得在同一 iteration 修复后继续。

## 7. 候选网格与 matched 设计(锁定于 plan,仅部分执行)

- 候选 grid 恰好 **3 个**(§17;禁止第四个):
  A `c2l_historical_control`(α 68/54/40/32;κ 0.80/0.55/0.38/0.25)、
  B `c2l_conservative`(α 74/56/40/28;κ 0.82/0.60/0.40/0.26)、
  C `c2l_midpoint`(α 71/55/40/30;κ 0.81/0.575/0.39/0.255)——
  覆盖 D3 α ∈ {28, 30, 32};
- formal block options {10,15,20};candidate design corpus = 40
  blocks/candidate/corpus;selection rule(min n → maximin → min
  distance → id)锁定于 plan;
- matched-ladder 核心模块(`curriculum261_c2.py` /
  `curriculum261_r6_tape.py` / `curriculum261_r6_pairs.py`)与 R7
  baseline 的 SHA256 **逐位一致**(plan 内 `matched_core_identity_r7`
  对拍,pass=True;R8 对 api.py 的改动仅限 R8 namespace 白名单与
  守卫追加,`paired_noise` 行为由 exact replay 测试逐位锁定);
- **执行进度**:3 candidate × 2 corpus 的 blocks 已生成(执行流到达
  评估阶段),但评估在第一个 candidate 的密度环节即中断 →
  **无 candidate 评估结果、无 power 分析、无 formal n 选择、无
  parameter pack、无 independent marginal guard**。
  选定 formal n / 选定 ladder / design gate probability:**未产生**。

## 8. Governance(§8.4/§25/§32)

| 项 | 状态 |
|---|---|
| design plan 锁定 | `r8dp-60bb85d5481054b619188fb5a97209acd054e9e110da26710458ecaf2ef0db9d`(保留,未删未重锁) |
| design_data_started | 2026-09-01T19:47:00Z(ledger) |
| iteration_aborted | 2026-09-01T19:49:58Z(marker O_CREAT\|O_EXCL + ledger;reason = ImportError) |
| plan 锁后异常 | **是**(ImportError,§8.4 主因) |
| 是否删除/重锁 plan | 否 |
| 是否使用临时 driver | 否(全程 `r8-cli` 与 pytest) |
| marginal/calibration/final namespace 访问 | 否(fail_path_cleanliness.json:21 项禁产 artifact 全部不存在) |
| exposure marker / ledger | 未写 |
| full-cold | 未运行 |
| R8 namespace 复用 | 禁止(下一轮必须 R8.1/R9 + 全新 seed space) |
| 历史证据 | R0-R7 artifacts 零改动;R7 plan/loader 事件/shared gate 结果/audit/ledger/raw logs 完整保留 |

## 9. 测试与回归

- **R8 测试套件**:7 个文件 / **45 项测试全部通过**:
  - `test_curriculum261_r8_noise_replay.py`(9):mirror 边界逐位置
    (episode 开头/内部/n-17/n-16/最后 8-16/最后一根)+ R7 高估对照
    + primary 边界(含 bar0 无主项)+ exact replay 逐位一致 +
    overlapping 累加 + 真实生成链路对拍 + per-event K/aggregate 复算
    + tail 窗口;
  - `test_curriculum261_r8_cue_contract.py`(6):floor 公式冻结 /
    合同身份稳定(v2、160、3600)/ 修正后 q 解析值(尾部 C(t))/
    手工混合复算 / 双侧 CI bootstrap / 小规模 audit 可复现 + 落盘
    完整(per-event 字段全集);
  - `test_curriculum261_r8_cue_eval.py`(7):LCB/UCB sanity / 规则
    身份 / 真实链路 semantic gate(去重 + K 完整 + replay 完整)/
    3600 绑定 / floor 绑定 / candidate 解耦 / marginal 点护栏;
  - `test_curriculum261_r8_param_pack.py`(5):恰好 3 候选 / 第四
    候选拒绝 / digest roundtrip + 篡改拒绝 / 160 强制 / 距离;
  - `test_curriculum261_r8_design.py`(7):digest 不自引用(R7 缺陷
    回归)+ 正式 loader roundtrip + 篡改 fail-closed + 不可覆盖 +
    matched 核心身份 vs R7 + semantic FAIL 短路(不评估 candidate)
    + §8.4 异常→aborted + min-n/maximin/tie-break;
  - `test_curriculum261_r8_namespaces.py`(7):24 namespace 声明 /
    隔离 / final namespace 锁前不可访问 / exposure 原子与单向状态机
    / aborted 阻断一切 / 无删除重置 API / R7-R8 seed 不相交;
  - `test_curriculum261_r8_preflight.py`(4):prelock static(含
    replay 探针)/ sealed digest 不自引用 + 零 final seed 篡改检测
    / CLI plan-roundtrip 全 14 检查 / 无 roundtrip 拒绝锁 plan;
- **回归**(raw logs 见 `raw_logs/`):targeted_r8 / affected_261 /
  affected_262 结果见 `regression_summary.json`;**full-cold 未执行**
  (仅 PASS 允许);
- **已知覆盖缺口(诚实披露)**:`_evaluate_candidate_matched_r8` 的
  密度 import 路径无测试覆盖(测试 monkeypatch 了整个评估函数),
  这是 import 缺陷未被 preplan 拦截的直接原因;R8.1 须补真实小规模
  candidate 评估冒烟测试。

## 10. §38 问答复盘(节选)

1. **R7 为什么 FAIL?** shared cue gate main LCB 0.9120 < floor
   0.9304(40-block SE 过大)。
2. **R7 plan loader 为什么无效?** digest 自引用(§2)。
3. **R8 如何修复 digest roundtrip?** 复算排除双字段 + 唯一正式
   loader + CLI roundtrip 子命令真实生产路径验证 14/14(§2)。
4. **正式执行是否完全使用仓库内 entrypoint?** 是;零临时 driver。
5. **正确 mirror source 上界?** `hi = min(t-8, n-17)`(§3)。
6. **corrected p_contract / recall floor?** 0.9504755515680544 /
   0.9304755515680544(新算,未复用 R7 的 0.950399 常数)。
7. **analytic/MC/direct generator 三者是否一致?** 是(§5)。
8. **为什么 semantic sample 固定 160?** 40→160 SE 减半,LCB 余量
   明确;数据生成前锁定;未扩样。
9. **semantic main/validation 各自结果?** validation 全过(LCB
   0.9458);main gate 通过但 artifact 丢失(§6.3)。
10. **unique cue 事件数?** audit:12,974 + 12,950;semantic
    validation:4153;semantic main:落盘丢失。
11. **候选 grid 为何只有 3 个?** R6/R7 development evidence 足够,
    扩网格只增选择偏差;三候选覆盖 D3 28/30/32。
12. **选定 formal n / ladder?** **未产生**(评估中断)。
13. **independent marginal / V2 新 fit banks / C1/C3 新语料 /
    calibration / holdout?** **未到达**(design 中断后禁止)。
14. **是否 pooled 救援?** 否(也未到达该阶段)。
15. **plan 锁后是否出现任何异常?** **是**(ImportError → §8.4)。
16. **是否删除/重锁 plan?是否临时 driver?** 否;否。
17. **sealed preflight / exposure / final 执行?** 未到达;未写;0 次。
18. **core pairs / independent pairs / semantic blocks?** 未产生
    (final 未执行)。
19. **PPO smoke?** prelock static preflight 内的 PPO plumbing smoke
    通过(测试链路);正式 `smoke` 子命令未运行(final 未到达)。
20. **C3 Branch D 是否仍开放?** **是**——R8 不解决 C3 scratch PPO /
    BC 被 PPO fine-tune 破坏 / critic-value-advantage 动力学。
21. **Stage 2.6.2 正式状态?** **FAIL**(未变)。
22. **建议下一步?** 见 §11。

## 11. 建议下一步:R8.1(工程修复 + 全新 seed space 重跑)

预注册范围(R8.1 只做工程修复,统计合同不变):

1. 修复 evaluator import(`c2_density_summary` 从
   `curriculum261_r5_pairs` 导入;r7_design 同源缺陷仅记录不改 R7);
2. 修复 semantic artifact 文件名判定(按 namespace 精确匹配而非
   `endswith("main")`),main/validation 分落两文件;
3. 新增真实小规模 candidate 评估冒烟测试(1-2 blocks × 1 candidate
   × 1 corpus 走完整 `_evaluate_candidate_matched_r8` 含密度/语义/
   bootstrap),封死本次覆盖缺口;
4. 全部 R8 统计合同沿用:Cue Semantic Contract v2(修正边界/exact
   replay/per-event K)、三路闭合 audit 判据、160-block dedicated
   semantic corpus、3 候选网格、{10,15,20}、noninferiority
   delta=0.02 / floor=0.90;
5. 全新 R8.1 namespace(`*_r81` 后缀);R8 namespace 永久封存。

R8 已产出的可复用资产:plan-roundtrip 基础设施(14/14)、noise
replay 模块、v2 合同审计全绿证据、semantic gate 实现、45 项测试。

## 12. 已知限制

- R8 的 cue 合同数值(p_contract/floor)来自 sentinel ladder 语料;
  R8.1 沿用时须在新 audit namespace 重新生成(不得复用 R8 corpus);
- main semantic corpus 的数值证据丢失,无法事后复算(aborted 后
  禁止再生成);R8.1 的 main 语料在新 namespace 重新产生;
- 本轮 24 个 R8 namespace 已全部封存(含已消耗的 audit/semantic/
  design 前缀种子);
- `regression_runner` 的 full-cold 基线未刷新(FAIL 路径不跑
  full-cold),R8.1 的 full-cold 仍以 R7 时代基线对比。

## 13. Artifacts 清单(stage2_6_1/artifacts/repair8/)

baseline_integrity / historical_binding / route_c_integrity /
production_preprocessing_audit / preprocessing_v2_contract(+digest)/
production_equivalence / seed_namespace_integrity_pre_design /
cue_contract_audit / cue_semantic_contract(+digest)/ cue_event_trace
(.jsonl)/ cue_k_distribution / tail_mirror_validation /
noise_replay_validation / preplan_engineering_smoke /
plan_roundtrip_validation / r8_design_plan(+digest)/
r8_iteration_events(.jsonl)/ r8_iteration_aborted /
semantic_design_validation(.json/.jsonl)/ fail_path_cleanliness /
seed_namespace_integrity(.json = post_design snapshot)/
regression_summary / raw_logs/{regression_targeted_r8,
regression_affected_261, regression_affected_262}.log

(semantic_design_main.* 因 §6.3 缺陷缺失——诚实记录,不事后伪造。)
