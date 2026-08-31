# Stage 2.6.1 Repair R2 — 课程稳健性门禁、Pair 合同闭环与 C2 上下文重构

- 阶段:2.6.1 Repair R2(独立迭代,非 R1 attempt3)
- 基线 commit:`a9fff65c01910e254564d7c96059a87fe56894a8`(R1 FAIL checkpoint,全部历史证据保留)
- vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- iteration:`r2`(全新 seed space,见 §3)
- **最终判定:PASS**(robustness gate 三族 PASS → plan 锁定 → 一次性 final qualification 120 pairs 全部检查通过;PPO smoke PASS)
- plan digest:`qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99`
- final ladder:
  - C1 机会识别:20.03% > 10.43% > 7.33% > 1.43%(integrity 1.0)
  - C2 上下文门控:2.79% > 1.89% > 1.65% > 0.72%(integrity 1.0)
  - C3 成本敏感:5.01% > 3.95% > 2.13% > 0.72%(integrity 1.0)
- artifacts:`artifacts/repair2/`(30 份;R0/R1 证据原样保留于 `artifacts/`、`artifacts/repair1/`、`artifacts/repair1_attempt1_archived/`)

---

## 0. 结果速览

| 项 | 结果 |
|---|---|
| robustness gate(双语料 v2 八条件) | 三族全 PASS(κ=1.5 预注册) |
| final qualification | PASS,120 pairs,`qualification_r2`(从未在 lock 前生成) |
| pair integrity | C1/C2/C3 全部 = 1.0(统一合同,accepted ⇒ final integrity 逻辑保证) |
| C2 local-only 捷径 | 深负 −4.6%~−4.8%(D3 reference +0.72%) |
| C2 上下文可观察性 | 方向 99.99% / 幅值 100%(observation-only 判定) |
| C2 local-cue 独立性 | 四象限 mean 差 2.4bps < 3×SE(6.7bps) |
| PPO 256-step smoke | PASS(obs 形状/有限 reward/SB3 plumbing) |
| full-cold | 见 §18(gate PASS + final PASS 后执行一次) |

---

## 1. R1 为什么失败?

R1 三个独立失败源(全部如实保留在 repair1 artifacts):

1. **协议缺陷**:robustness gate 的实现语义错误——`robustness_gate.pass == false` 时仍允许 `lock plan → run final qualification`,gate 沦为报告字段而非 Gate(R1 三族 gate FAIL 仍执行了 final)。
2. **两套结构判定不一致**:acceptance 用 generator 的 `structural_validator`(episode 级、只查段表标签),final 用 `_c1/_c2/_c3_construction_check`(pair 级、查实际挂载)——C1 first_pass=1.0 但 pair_integrity=0.90:第一段为水平归零不挂漂移,部分 episode 的全部机会段恰好落在首段,「latent 有机会而收益机制无机会」。
3. **C2 context carrier 结构性两难**:方向上下文由价格微漂移承载(经 `%-price-ma-ratio` 读取)——漂移强则 cue 脉冲的 `%-ret-1` 读数分布随 regime 平移(阈值触发率的选择效应使 local-only 隐式免费读出门控),漂移弱则 pmr 判定仅 ~2σ、reference 捕获不稳;R1 D3 reference 落到 Always Flat 以下(−0.15%)。

另有 C2 integrity 0.975 与 C3 的 calibration gap-vs-SE 边缘不足。

## 2. robustness gate protocol bug 如何修复?

三层 enforcement(不止 CLI 约定):

- **Layer A(calibration runner)**:`curriculum261_cli calibrate` 运行 calibration_r2 → calibration_holdout_r2 → generator stress(144 pairs)→ C2 双诊断 → seed namespace integrity → gate v2;`gate.pass=false` 时**非零退出**,不生成任何 plan;
- **Layer B(plan builder/locker)**:`build_plan()` 在 `robustness_gate is None or pass is not True` 时直接 `RuntimeError`——「gate FAIL 仍可 lock,由 final 裁决」的语义已从代码中删除;CLI `lock-plan` 分支在调用前另查 `robustness_gate.json` 存在且 `pass=true`,否则拒绝(rc=1);
- **Layer C(final runner)**:`run_final_qualification()` 入口在生成第一个 qualification pair 之前检查 `plan["robustness_gate"]["pass"] is True`,否则 fail closed——即使有人手工构造合法 digest 的 plan 也被拦截。

回归测试:`test_final_runner_fails_closed_on_gate_false` 给 final runner 一个 gate=false 的合法 digest plan,验证在访问任何 qualification seed 之前抛错且不生成 results。

新硬合同流程:Calibration → Holdout → Gate →(FAIL ⇒ `R2 calibration qualification = FAIL` 停止 / PASS ⇒ Lock → Final Qualification)。本轮 gate 三族 PASS 后才 lock、才执行 final。

## 3. 为什么 R2 qualification seeds 不会复用 R0/R1?

- iteration 身份 `r2` 进入全部正式 namespace:`calibration_r2 / calibration_holdout_r2 / qualification_r2 / fresh_holdout_r2 / training_r2 / stress_r2`;seed 派生 payload 含 namespace 字符串,新 namespace 的派生流天然与 R0/R1(`calibration/qualification/...`)不相交;
- `seed_namespace_integrity.json` 枚举 11 个 namespace × 3 family × 4 rung × 40 pair × 5 attempt = 198,000 个 seed 值,显式验证两两无碰撞、`qualification_r2` 与其它任何 namespace 无交集、calibration/holdout/stress 与 qualification_r2 不相交(pass=true);
- `qualification_r2` 在 lock 前对任何代码路径不可访问:`derive261_seed` 对该 namespace 检查锁定 marker(`qualification_plan.json` 存在),lock 前派生即抛 `GeneratorError`;calibration/诊断/stress 一律使用各自 namespace,由 `seed_namespace_integrity.qualification_r2_locked_before_use` 记录 lock 前状态。唯一例外是 integrity 报告自身的碰撞枚举走 `_derive261_seed_raw`(纯哈希值,不生成 episode——corpus 暴露以生成为准);
- 测试:`test_qualification_r2_blocked_before_lock`(lock 前派生被拦)、`test_qualification_r2_unlocked_after_lock`、`test_r2_seeds_disjoint_from_r0_r1`。

## 4. pair structural validator 如何与 final integrity 统一?

定义**唯一**的 pair 结构接受合同 `pair_structural_contract(a, b, family)`(pairs.py):

- acceptance(attempt 循环)与 final(`compute_pair_integrity`)调用**同一批底层判定函数**(`_nuisance_checks` + `_c1/_c2/_c3_construction_check` 的 causal/shared 项 + `c1/c2/c3_structural_issues` 生成时结构检查);
- `generate_pair_with_attempts` 的 validator 由 episode 级改为 pair 级合同入口 `pair_acceptance_contract`(A/B 各跑 episode 级快速预检 + pair 级统一合同);
- 确定性生成器下同一输入必然得出同一结论,因此 **accepted pair ⇒ final_structural_integrity == true 是逻辑保证**(同一函数的确定性推论),不是概率上「通常成立」;
- §11 pre-qualification generator stress:stress_r2 namespace 下 family × rung × 12 pairs = 144 pairs,accepted 的 144/144 全部通过 final integrity 检查(`accepted_implies_integrity=true`,低概率退化的经验证据);
- final 实证:C1/C2/C3 `pair_integrity_pass_ratio = 1.0`(120/120 × 3),first_pass_rate C1 1.0 / C2 1.0 / C3 0.925。

## 5. C1 degeneracy 如何消除?

R1 根因:第一段(含 t=0,为水平合同不挂漂移)保留 opp/neg 标签——当全部机会段恰好落在首段时标签与收益机制脱节。R2 修复(三重):

1. 生成器:段表改为**固定模式** `[neut, opp, neut, neg] × 3`(段长 24,首段恒 neut)——任何 opp/neg 段必然在挂载区 `[1, n)` 内,标签必然伴随真实收益机制;
2. validator:新增 `no_mounted_opportunity / no_mounted_neg` 拒绝原因(挂载机会 bar 数 ≥ 12 / 挂载 neg ≥ 8,只对 variant A 生效——B 的 drift 恒 0 是假机会孪生合同);
3. 统一合同把上述检查纳入 acceptance(生成时闸门而非 final 才发现)。

水平归零合同未动:`sum(returns[1:]) = 0` 精确(final 前多轮实测 0.000000bps),Always Long 恒 −0.20%。

## 6. C2 integrity 为什么 R1 只有 0.975,如何修?

R1 C2 的 final construction check 要求 payoff 与两个上下文载体(g1 漂移/vol 体制)的绑定/非绑定关系逐点成立;载体由价格路径承载,个别 accepted episode 在 vol 体制切换边界附近出现注入窗口与体制表错位,acceptance(只查 cue 结构)未拦截。R2 的修复是结构性的:**v9 的上下文载体(wick)与 close 收益路径完全解耦**,construction check 只需验证注入方向 = `sign(gate) × sign(cue)`(gate 从 sidecar 链表读取,与收益实现无耦合路径),统一合同在生成时即执行同一判定——120 pairs + 144 stress pairs 全部通过,不再存在「accepted 后 final 才发现」的窗口。

## 7. C2 context carrier 做了什么结构性 redesign?

**从「价格漂移承载、pmr 读取」重构为「wick 几何纹理承载、raw OHLC 读取」**:

- G1(方向纹理):wick 偏斜方向 s∈{+1,−1} 等长成对交替块——s=+1 块内每 bar 上影长/下影短(`high+low−open−close > 0`),s=−1 反向;偏斜度 κ 随 rung 递减;
- G2(wick 幅值):wide(110bps)/narrow(30bps)等长成对交替块(`(high−low)−|close−open|`);
- close 收益 = 间隔配对噪声(常数 vol)+ cue 脉冲(镜像)+ 收益注入(镜像)——**上下文载体完全不进入 close 收益**:local cue 分布匹配、水平归零(沿用 R1 已证合同)、上下文即时可读(无 24-bar 窗口冲刷/体制切换读数滞后/暖机假触发——R1 G2 的三类 notcue 假触发根源一并消除);
- payoff 注入 `d × gate × α`:A 绑方向纹理(s)、B 绑幅值(w),镜像 span 检查保证注入按对精确抵消;
- 难度:κ ladder [0.80, 0.55, 0.38, 0.25](判定 SNR 渐降)与 α ladder [68, 54, 42, 32] bps 双 knob;
- 判定特征 body-clean:`score = raw_high+raw_low−raw_open−raw_close`(恒等式 `max+min = o+c` 精确消除 bar body 相位项,cue 脉冲进入 close 而非 wick,score 对脉冲免疫)、`span = (raw_high−raw_low)−|raw_close−raw_open|`。

为什么这解决了 R1 的两难:漂移承载时「cue 读数污染」与「pmr 判定强度」共享同一个价格路径自由度,二者只能取舍;wick 承载把「上下文可见性」移到 OHLC 的另一组自由度(影线),close 收益路径保持纯噪声+镜像事件——两个需求不再冲突。

## 8. 如何证明 local cue 不泄漏 context?

三层证据(`c2_local_cue_context_independence.json` + gate 条件 7 + final 复验):

1. **构造级**:cue bar 的 `%-ret-1` 读数 = pulse(150bps) + 独立配对噪声;G1/G2 只改写 high/low,不进入 close——读数分布与 (s, w) 无任何耦合路径;
2. **统计级**(预注册判定,calibration_r2 + holdout_r2 共 160 episodes):cue bar 读数按四象限 (s±, w±) 分组——象限间 mean 差 2.39bps ≤ 3×pooled SE(6.68bps)、std 比值 ∈ [0.8,1.25]、正号率差 ≤ 0.10、cue 事件率比 ∈ [0.75,1.35],四项全部通过;
3. **行为级**:local-only 基线(只读 `%-ret-1`)在全部 rung 深负(qualification:D0 −4.81%、D3 −4.65%,每集 ~37 次触发全部只输摩擦),reference 在同语料 +2.79%/+0.72%——如果 cue 分布泄漏 gate,local-only 不可能稳定深负。

final qualification 上同款诊断复验通过(`checks.c2_local_cue_independence = true`)。

## 9. 如何证明当前 observation 能看到 context?

`c2_context_observability.json`(observation-only 判定器,latent 仅作评估 label):

- 方向判定 `sign(raw_high+raw_low−raw_open−raw_close)` vs 真值 s:逐 bar 准确率 99.99%(final qualification 全部 120 episodes);
- 幅值判定 `(raw_high−raw_low)−|raw_close−raw_open| > 0.0120` vs 真值 w:100.0%;
- margin = 2×acc−1 ≥ κ×SE(方向 3839×κSE、幅值更大)——「稳定辨认」远超统计门槛;
- 判定器只读 8 个生产特征槽位中的 4 个(`%-ret-1` + raw 三列),与参考策略同源;不访问 sidecar。

这正是 §13.B 的口径:不能只证明 latent 存在——观察行本身足以区分上下文。

## 10. C2 D3 是否有显著 positive margin?

是。final qualification:

- D3 度量 **+0.715%**(R1 为 −0.146%);
- calibration gate:D3 = 0.864% ≥ κ×SE = 1.5×0.084% = 0.126%(6.9×);
- reference vs 必胜基线:always_flat 0 / always_long −0.20% / **c2_local_only −4.65%**——D3 reference 在全部必胜基线之上;
- oracle(D3)+3.40% 确认世界确实含有可捕获的因果结构;
- 相邻 rung gap(final):0.91%/0.24%/0.93%;calibration gate 的 gap-κSE:2.4×–6.5×(双语料各自 > 0 检查 + 合并 SE)。

## 11. C3 robustness margin 是否真正通过?

是(gate v2 八条件,双语料同时):

- ladder:calibration 5.40% > 3.53% > 1.91% > 0.52%,holdout 同向单调;
- gap vs κ×SE:D0-D1 1.87%/1.89% vs 1.66%、D1-D2 1.62%/1.26% vs 1.20%、D2-D3 1.40%/1.21% vs 0.73%——全部通过(R1 的边缘失败来自 α 相邻差 6-7bps + strong 占比差 14pp 小于跨语料方差);
- R2 加固:α 相邻差拉开到 8bps [70,62,54,46]、事件密度 ×1.7(cue_rate 0.20-0.23,独立事件更多 → SE 下降)、D1/D2 strong 占比差 12pp、D2/D3 差 20pp([62,46,34,14]%);
- final qualification 复验:5.01% > 3.95% > 2.13% > 0.72%,D3 = 0.72% > 0 且 reference 压过 cost_ignorant 全 rung。

C1 同样真正通过(见 §5 的固定段表修复后):calibration 双语料 gap D0-D1 8.6%/9.3%、D1-D2 3.7%/3.6%、D2-D3 6.3%/5.8%,全部 ≥ κ×SE;final 20.03% > 10.43% > 7.33% > 1.43%。C1 的关键方差修复见 §5——v4 校准暴露 opp 段数的抽样方差主导度量(oracle D1/D2 重合),固定段模式使 n_opp_bars 恒 72 bar。

## 12. production PPO 实际 feature/preprocessing path 是什么?

从真实 runtime config 与 vendor 源码逐项确认(`production_runtime_config.json`,不假设):

```
OHLCV
→ RouteCStrategy.feature_engineering_standard(8 列:%-ret-1/%-ret-4/
  %-vol-24/%-price-ma-ratio/%-raw_open/%-raw_high/%-raw_low/%-raw_close)
→ feature_pipeline.fit_transform(train_features)
   = ds.VarianceThreshold(threshold=0)
   + SKLearnWrapper(MinMaxScaler(feature_range=(-1,1)))
   (fit 于 train_features;PCA/SVM/DI 在正式 config 中全部关闭)
→ AlignedLongFlatEnv(df=scaled_features, prices=raw OHLC,
   window_size=CONV_WIDTH=1)
→ observation = [特征行, 仓位槽位](dim=9,Box(-10,10))
```

正式 config(最新正式 run `stage252a-rc-e9b373b3c9_smoke-reload`,sha256 入 plan):`drop_ohlc_from_features=false`、`add_state_info=false`、`model_type=PPO`、`policy_type=MlpPolicy`;`SUPPORTED_CONV_WIDTH=1`(guards.py)。identity 绑定 config 文件哈希 + `define_data_pipeline` 源码哈希 + RL 训练路径源码哈希,final 复核一致。

## 13. curriculum 与完整 FreqAI preprocessing 是否完全等价?

**不等价,且 R2 起正式如此声明**(`production_preprocessing_boundary.json`):

课程预处理边界(正式命名):

```
Curriculum = real RouteCStrategy feature semantics
           + frozen Route C observation layout
           + causal unscaled curriculum feature values
```

- **特征语义**:真实生产源码调用(`RouteCStrategy.feature_engineering_standard`,非课程重实现;文件/函数哈希进 plan 与 final 复核);
- **observation layout**:ObservationSpec-v1 冻结 window=1 滑窗 + 仓位槽 + Box(-10,10)——spec 只冻结 layout,不冻结数值缩放;
- **特征值**:causal unscaled(单 episode 全序列无未来信息;**不经** VarianceThreshold/MinMaxScaler)。

明确声明「不是完整 FreqAI production preprocessing equivalence」:生产训练在 env 之外对 train_features 施加 scaler(fit 于训练窗、episode 间重拟合,含全窗统计);若在单 episode 课程内复刻会引入 lookahead,与课程因果合同冲突。

## 14. domain gap 在哪里、何时验证?

- gap:**FreqAI scaler / production preprocessing transfer**(VarianceThreshold 零方差列删除 + MinMaxScaler((-1,1)) 的数值变换及其 episode 间重拟合);
- 登记:`registered_domain_gap.verification_stage = "后续 transfer / G5 阶段验证"`,`not_this_stage = true`;
- 未来合同:若 2.6.2 使用课程 adapter,必须使用与本边界**完全相同**的 adapter(`production_observation_identity` 绑定);
- `initial_price=1.0` 明确登记为 synthetic generator 的数值约定(raw 价格特征落入 Box(-10,10)),**不**被用于宣称与真实行情 preprocessing 等价。

## 15. robustness gate 最终 PASS/FAIL?

**PASS(三族全部)**。gate v2 八条件在 calibration_r2 AND calibration_holdout_r2 双语料同时满足:

| 族 | ordering | D3>0 | ref>基线 | integrity=1.0 | gap≥κSE | D3≥κSE | C2 双诊断 | attempts |
|---|---|---|---|---|---|---|---|---|
| C1 | ✓ | ✓ | ✓ | ✓(双语料+stress) | ✓ | ✓ | — | ✓ |
| C2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| C3 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ |

κ=1.5(R1 预注册沿用,未看结果调整);seed namespace integrity 同时通过并入 gate。

## 16. final qualification 是否 PASS?

**PASS**。一次性执行(120 pairs = 3 families × 4 rungs × 10 pairs × A/B,`qualification_r2` seed space,lock 前从未生成)。全部 17 项 checks 通过:robustness gate 前置通过、production observation/runtime config/preprocessing boundary/code identity 四重身份、frozen contracts、vendor pin clean、pair integrity 1.0、causality、latent isolation、reproducibility、fresh seed、ordering、D3 positive、reference beats required、oracle positive、C2 local-cue independence、C2 context observability。PPO 256-step smoke PASS(不构成训练,不参与课程参数选择)。

## 17. 若 final FAIL,失败后是否停止而没有重用 test corpus?

本轮 final PASS,该分支未触发。但协议与实现均已就位:final runner 开始即写 exposure marker(`qualification_exposure_r2.json`,plan digest 绑定,本轮 status=completed);再次调用任何 final(无论上次 PASS/FAIL)在生成任何 pair 之前被拒——继续必须换迭代身份 R2.1/R3 + 全新 seed space。回归测试 `test_exposure_marker_blocks_second_run` 验证。

## 18. full-cold 是否执行、结果是什么?

执行(条件满足:gate PASS + final PASS + 代码稳定,按 §28 跑一次;首轮 full-cold 暴露 1 项**测试隔离缺陷**——`test_final_runner_fails_closed_on_gate_false` 未把 marker 目录指向 tmp,真实 final 执行后 exposure marker 存在使该测试先撞一次性守卫而非被测的 gate 检查;修复(仅测试文件加 monkeypatch,src 未动、code_identity 不变、final 结果不受影响)后重跑)。结果:`failed=0, skipped=0, xfailed=0, error=0`。

| full-cold | 值 |
|---|---|
| passed | 1662 |
| failed / skipped / xfailed / error | 0 / 0 / 0 / 0 |

wall=5212s(summary:`full-cold-20260831-070840`,基线已刷新;证据:`regression_summary.json` + 分目录日志)。

开发期间回归策略遵守 §27:targeted(families/causality/reproducibility/production_obs/r2_protocol)→ stage2_6_1(106 项全绿)→ 未反复 full-cold。

---

## 附 A:C1 v5 段表确定性的合理性论证

固定段模式产生的周期结构(period=96 bar)是否可被策略利用:policy 为 MLP + window=1(冻结 ObservationSpec-v1),无 recurrent/记忆组件,单行观察不含 bar 计数;pmr/vol-24 等特征的锯齿形态在随机段表下同样存在。确定性去随机化的收益(n_opp_bars 恒定 → 度量方差只剩触发时机)是 v4 校准诊断(oracle D1/D2 重合)的直接解;latent isolation 检查确认段表不进 observation。

## 附 B:迭代记录(诚实过程)

- calibration v1(pairs=10):三族 ordering 单调,C1/C3 gap-SE 不足(SE 过大),C2 gate PASS;
- v2(pairs=12):C1 段长收窄实验失败(D1<D2 inversion,段过短破坏触发结构)——回退;C3 差一点;
- v3(pairs=20):C2/C3 gate PASS;C1 main corpus D1/D2 完全重合——oracle 对照定位根因为 opp 段数抽样方差;
- v4(C1 固定段模式,pairs=20):三族 gate PASS → lock → final PASS。
全部迭代使用 calibration_r2/holdout_r2 namespace(qualification_r2 在 lock 前从未生成,守卫 + integrity 记录)。
