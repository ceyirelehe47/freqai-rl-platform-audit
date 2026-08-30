# 阶段 2.6.1 Repair Iteration(R1)报告:production ObservationSpec-v1 路径下的 C1/C2/C3 课程资格

- 结论:**FAIL**(如实;C2 的 D3 度量为负 + C1 的 pair integrity 0.9 < 1.0;其余全部通过,含三族难度排序)
- 日期:2026-08-30
- 基线 commit:`c6e37afe0e1845bc2c02bb79ae5cacab1125dbc1`(上一轮诚实 FAIL checkpoint,其全部证据原样保留于 `artifacts/`,未改动)
- vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(未漂移,clean)
- 本轮最终 qualification plan digest:`qp-cc44880c155ed61cdf3e1306bec7621531b303d320fde55d322e99bb19e6b6f1`
- 本轮第一次执行(含实现 bug,已存档)plan digest:`qp-262f1268601692f3c118eaca325ce3bcd4146eea1ae2702497d1a92e2432caa6`(证据:`artifacts/repair1_attempt1_archived/`,不删除)
- 治理豁免:延续上一轮(不重开 2.6.0j 防御性安全审计;见旧 artifacts/governance_waiver.json)

---

## 1. 上一轮为什么 FAIL

上一轮(第一轮 qualification,digest `qp-16792c…`,commit `c6e37af`)的表面失败项:

- C2(context gating)D3 难度度量为负(−0.2995%),且 D3 上 reference 输给 always_flat;
- C3(cost selectivity)出现 D2(0.1795%)< D3(0.5518%)的排序倒挂。

根因是**相邻 rung 的设计间隔小于跨语料抽样方差**:C2/C3 的 rung 间隔(<40bps)对着 ±40-60bps 的 corpus 方差,换一批 qualification seed 就可能翻转;同时 C2 每 episode 参考策略实际只有 2-3 笔交易,方差压不住;C2 的 always_long 在部分 episode 上有 ±2% 的水平残差(旧 banner 机制在 episode 末尾的边缘)。

## 2. curriculum-only observation bug 的根因

上一轮虽然验证了 `rl_platform.versions.OBSERVATION_SPEC_VERSION == "ObservationSpec-v1"` 且 `rl_platform` 代码树哈希未变,但课程 qualification 实际使用的 observation 是 `curriculum261_observation_schema()`(`curriculum261-obs-v1`,11 个课程自制特征:ret_1/ret_2/ret_4/vol_24/ma_dev_24/htf_1h_mom/htf_4h_mom/htf_4h_ma_dev + nuis_0/1/2)。也就是说:**验证的是冻结版本字符串,执行的是另一套观察**。上一轮证明的是"课程专属 observation 的可解性",不是"冻结生产 Route C observation 的可解性"。

生产路径的真实定义(本轮从代码中考证):

```
OHLCV
 -> RouteCStrategy.feature_engineering_standard(user_data/strategies/,生产代码本体)
    产出 8 特征:%-ret-1 / %-ret-4 / %-vol-24 / %-price-ma-ratio /
                %-raw_open / %-raw_high / %-raw_low / %-raw_close
 -> BaseReinforcementLearningModel.train 的 data_dictionary["train_features"]
    (列集合与顺序即策略赋值序;raw_* 同时被 build_ohlc_price_dataframes
    拆为环境 prices)
 -> AlignedLongFlatEnv(features=..., window_size=CONV_WIDTH=1)
 -> observation = [特征行, 仓位槽位](ObservationSpec-v1)
```

## 3. 如何保证现在实际走 production ObservationSpec-v1

新增 `curriculum261_production_obs.py`,五层保证:

1. **特征构造 = 生产代码本体**:`attach_production_features` 直接调用真实 `RouteCStrategy.feature_engineering_standard`(importlib 加载 `user_data/strategies/RouteCStrategy.py`,免实例化,函数不触碰 self);课程不重新实现任何特征公式。暖机 NaN 以 fillna(0) 处理(生产为丢暖修行;t ≥ 24 后两者逐位一致——口径差异记录在案)。
2. **schema 逐列同名**:`production_observation_schema()` 的 8 特征与生产 train_features 同名同序;qualification 模块的模块级 `SCHEMA` 即此 schema。
3. **执行路径对拍**:`assert_production_observation_binding` 把 episode 的 8 列与"独立重跑生产特征函数"逐位比对(不是字符串比较);`check_production_feature_equivalence`(进入 causality matrix 与 final qualification)另验证 observation 数组由冻结 `AlignedLongFlatEnv.reset()` 构造且在 `observation_space` 内。
4. **身份入 plan 并在 final 复核**:`RouteCStrategy.py` 文件哈希 + `feature_engineering_standard` 源码哈希 + schema hash 进入 plan 的 `production_observation_identity` 与 `code_identity`;final 运行时复算比对(`production_observation_identity`、`plan_code_identity_matches_tree` 两个检查项,顺带堵住"旧 plan 目录配新代码静默混跑"的缺口)。
5. **防回退测试**:`test_curriculum261_production_obs.py`(17 项)断言 qualification 的 SCHEMA hash 必须等于 production hash、源码中不得再定义旧 schema、三族 episode 全部通过生产路径对拍;若有人切回任何课程自制 schema,测试立即失败。

两点如实记录的口径差异(不属于 ObservationSpec-v1 观察构造合同):(a) FreqAI feature_pipeline 的 MinMaxScaler 是训练窗统计的数据准备步骤,单 episode 内全序列缩放会引入未来信息,课程以未缩放因果特征进环境(与 2.6.0 泛化审计 evaluator 同一惯例);(b) `initial_price` 100→1.0,使 raw_* 特征落在冻结环境 `Box(-10, 10)` 内。

## 4. C1/C2/C3 在 production observation 下各自在教什么

- **C1(机会识别)**:分段机会世界——opp/neg 段的每 bar 漂移(58→24bps/bar 随 rung 递减),neg 漂移按挂载段总量精确平衡。策略用 `%-price-ma-ratio`(close/MA24−1,pmr)读趋势位置、`%-ret-4` 做动量确认。能力:识别"何时 Long 有期望价值、何时 Flat 更合理"。
- **C2(上下文门控)**:同一局部脉冲信号在不同持久上下文下的成立性。G1 方向上下文 = 等长成对状态链上的微漂移(±12bps/bar,由 pmr 符号读取,稳态 ±138bps);G2 波动率体制 = calm/turbulent 链(vol 12↔130bps,噪声尺度 24-bar 平滑过渡,由 `%-vol-24` 读取)。cue 脉冲(±90bps)后单 bar 注入 d×gate×α。能力:局部信号必须与两个正交上下文同时对齐才值得交易。
- **C3(成本敏感择时)**:事件强度可见(单 bar 脉冲 s×k,k=600bps,由 `%-ret-1` 读到)而强度-收益耦合在 A/B 间改变的世界。A:毛 edge G(s)=α·s 随强度单调;B:G 恒 0.3×F(亚成本常数)。能力:只有估计毛 edge 超过冻结摩擦才交易;摩擦常数唯一来自 `null_friction.ledger_round_trip_retention`(0.001998)。

## 5. reference policy 实际能看到哪些信息

只看当前 observation 的生产特征槽位(window=1,无历史堆叠、无递归状态):

- C1 reference:`%-price-ma-ratio > k·σ(pmr)` 且 `%-ret-4 > 0`(k=1.0,σ 闭式 = vol×√(4853/576)≈2.9×vol);
- C2 reference:`%-ret-1 > cue_thr` 且 `%-price-ma-ratio > 0` 且 `%-vol-24 < vol_thr`;
- C3 reference:`%-ret-1 > k×s*`(s* = margin×F/α,由冻结摩擦公式推导)。

全部经 `ObservableBaselinePolicy.read(observation, feature_name)`——`policy_api` 对不在 whitelist 的特征名 fail closed;参考策略拿不到 sidecar/latent/旧特征列。

## 6. latent truth 为什么没有泄漏

- sidecar(hidden)列与 observation 列零交集,`FORBIDDEN_OBSERVATION_PATTERNS` 对 8 个生产列名零命中(latent isolation 检查通过);
- 清零 sidecar 不改变 observation(环境只用 df 特征列);
- production 特征由生产特征函数从 OHLCV 计算,课程无法在特征层注入 latent;
- pair A/B 的价格只在因果映射上不同,latent 不经过任何课程专属通道进入 observation。

## 7. C2 如何解决 D3 negative(以及本轮为何仍未通过)

做了什么(结构层):

- **水平精确归零**:全部价格分量(方向链漂移、噪声、cue 脉冲、收益注入)按对构造并在 [1,n) 内抵消,且 bar 0 收益恒 0(修复了"配对跨可交易边界"导致的 always_long 百 bps 级残差)。qualification 语料上 always_long 恒 = −0.1998%(= −摩擦,精确);
- **消灭 v3 选择效应**:中间版本(v3)用 ±35bps/bar 漂移承载 G1,被诊断出 cue 读数分布随 regime 方向平移 → local-only 基线"免费"读出门控(A 侧 +11%/集)。v8 定稿把漂移降到 ±12bps(pmr 判定与选择效应的两难折衷),local-only 在全部 rung 上转负(qualification:−2.3% ~ −6.0%);
- **噪声尺度 24-bar 平滑过渡 + 暖机强制 calm**:消灭"vol-24 读数 calm、实际 σ turbulent"的过渡窗假触发窗口(该窗口曾以每笔 −68~−109bps 吃掉参考收益);
- **事件密度**:cue_rate 0.82/步进 gap+5/镜像 gap 2-3,参考交易数从 2-3 笔/集升到 10-13 笔/集。

为什么仍未通过:D3 的 α=34bps,每笔净 edge 只有 14bps;qualification 语料上 D3 参考度量 = −0.15%(D3 的参考没有稳定捕获残存的正 edge,oracle 在全部 rung 为正证明结构存在)。**深因是 C2 世界里"每笔净 edge"与"pmr 判定可靠性/选择效应"存在结构性两难:漂移强则 pmr 可判但局部信号隐式解决门控;漂移弱则门控独立但参考判定噪声大。**在 8 特征/window=1 的冻结观察下,该两难没有完全消除——这是本轮如实保留的核心未解问题。

## 8. C3 如何解决 D2/D3 inversion

三重结构差替代薄边际差:

- α ladder 66/60/54/47(旧 57→54 只差 3bps;新相邻差 6-7bps);
- strong 混合占比 0.60→0.20(大幅递减);
- distractor 率 0.015→0.060;
- 脉冲可见度 k=160→600bps,使参考阈值读数(200-280bps)与 payoff bar 读数(≤125bps+4σ)完全分离(旧 k 下参考被 payoff bar 假触发拖入无信号 bar);
- 事件密度上升(cue_rate 0.10→0.13,步进 gap+4)压低 D3 方差。

qualification 结果:C3 = 3.24% > 2.03% > 1.31% > 0.69%,**严格单调且 D3 为正,reference 全 rung 压过 cost-ignorant 与常数基线,pair integrity 1.0**——C3 完整通过。

## 9. calibration robustness 如何防止再次翻转

新增 lock 前双语料流程(`calibration` + 独立 `calibration_holdout` namespace,均不触碰 qualification seed):`calibration_robustness_gate` 要求每族在两个语料上同时满足 ordering、D3>0、reference>必胜基线,且相邻 rung 间隔与 D3 度量 ≥ 1.5×合并 per-episode 标准误(κ=1.5 预注册)。本轮 gate 结果如实:三族 FAIL(C1 双语料 D2<D3 倒挂、C2 holdout 上 D3 转负、C3 结构通过但 D0-D1/D1-D2 间隔未达 1.5σ)。gate 结果连同两份 calibration 全文一起被锁进 plan(`robustness_gate` 字段)——final qualification 在 gate FAIL 的已知风险下按任务书流程执行,由其一次性结果裁决。

## 10/11. 新 qualification 结果与失败项

第二次执行(最终,digest `qp-cc44880c…`):**verdict = FAIL**。

| 检查项 | 结果 |
|---|---|
| frozen_contracts_unchanged | PASS |
| vendor_pin_unchanged_and_clean | PASS |
| production_observation_identity | PASS(新) |
| plan_code_identity_matches_tree | PASS(新) |
| pair_integrity_all | **FAIL**(C1 0.90;C2 0.975;C3 1.0) |
| causality_all(含 production 特征对拍) | PASS |
| reproducibility_all | PASS |
| latent_isolation | PASS |
| fresh_seed_validity | PASS(8/10) |
| difficulty_ordering_all(三族) | **PASS** |
| d3_positive_all | **FAIL**(C2 D3 = −0.146%) |
| reference_beats_required_all | **FAIL**(C2 D3 上 ref −0.146% < flat 0) |
| oracle_positive_all | PASS |

难度阶梯(qualification corpus,120 pairs):

- C1:20.05% > 11.27% > 10.58% > 5.88%(严格单调 ✓)
- C2:1.42% > 0.27% > 0.20% > **−0.15%**(单调 ✓,D3 负 ✗)
- C3:3.24% > 2.03% > 1.31% > 0.69%(严格单调 ✓)

C1 的 4/40 个 D0 pair integrity 失败的原因:「opp 段全部落在不挂载漂移的第一段」的退化情形(第一段不挂是本轮水平归零合同的一部分;structural validator 只数状态段数、未数挂载段数,未拒绝该退化)。属下一轮修复项。

第一次执行(存档,`artifacts/repair1_attempt1_archived/`):其 FAIL 含一个实现 bug——`_c1_construction_check` 的"opp 段漂移恒正"断言未跟上"第一段不挂"的新合同,把第一段为 opp/neg 的正常 episode 判为失败(C1 integrity 崩至 0.375、fresh_seed 7/10)。修复该检查(参数/阈值未动)后重新 lock(新 code identity → 新 digest)并第二次执行;两次证据都保留。

## 12. full-cold 结果

从零冷缓存重新执行(不复用旧结果):**1643 passed / 0 failed / 0 skipped / 0 xfailed / 0 error,all_green=True**(wall 4963s;较上一轮 1625 项净增 18 项 = 阶段测试 69→87,其中 17 项为 production observation 守卫)。证据:`artifacts/repair1/regression_fullcold_totals.json`、`regression_fullcold_summary.json` 与逐目录日志(`regression_fullcold_logs/`)。

---

## 主要改动文件

| 文件 | 改动 |
|---|---|
| `src/rl_curriculum/curriculum261_production_obs.py` | 新增:生产特征构造(schema/身份哈希/防回退守卫) |
| `src/rl_curriculum/curriculum261_api.py` | 删除自制 schema/特征/OU 回拉;initial_price=1.0;paired_noise 从 t=1 起(水平合同);calibration_holdout namespace |
| `src/rl_curriculum/curriculum261_c1.py` | pmr 阈值公式修正(σ=2.9×vol);vol 统一 26;第一段不挂漂移;特征名切换 |
| `src/rl_curriculum/curriculum261_c2.py` | 重写(v3→v8):微漂移承载 G1、噪声尺度平滑过渡、cue 镜像 gap 2-3、payoff/阈值分离、水平精确归零 |
| `src/rl_curriculum/curriculum261_c3.py` | k=600、bins/mixture/α ladder 重设计、事件密度上调 |
| `src/rl_curriculum/curriculum261_pairs.py` | nuisance 槽位移除;C1 构造检查适配新水平合同 |
| `src/rl_curriculum/curriculum261_qualification.py` | production schema;production 特征对拍检查(替代 htf resample);calibration holdout + robustness gate |
| `src/rl_curriculum/curriculum261_plan.py` | format v2;production identity + RouteCStrategy 哈希入 code_identity;calibration_evidence/robustness_gate 入 plan |
| `src/rl_curriculum/curriculum261_final.py` | production identity 与 plan code_identity 复核(新检查项) |
| `src/rl_curriculum/curriculum261_smoke.py` / `curriculum261_cli.py` | production schema;baseline=c6e37af;calibrate 产双语料+gate |
| `tests/route_c_stage2_6_1/` | 新增 `test_curriculum261_production_obs.py`(17 项守卫);4 个既有文件更新(共 87 项) |
| `regression_runner.py` | RouteCStrategy.py 入 manifest 与 RULES(→ 2.6.1 + 2.5.2a) |

## 下一轮修复清单(不属本轮)

1. C2 的「每笔净 edge vs pmr 判定/选择效应」两难:需要新的上下文承载机制(不经过 bar 收益漂移的方向上下文),或在 ref 侧引入允许的确认结构;
2. C1 structural validator 增加「挂载机会段数 ≥1」检查(消除退化 pair);
3. C2 D3 的 α 与事件密度的联合重标定(在两难解除后);
4. C3 的 gap-vs-SE 边缘(D0-D1/D1-D2 间隔拉大到 ≥1.5σ)。

本轮未进入 Stage 2.6.2,等待独立审查。
