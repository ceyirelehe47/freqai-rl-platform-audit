# 阶段 2.6.1 主报告:C1/C2/C3 课程生成器、难度阶梯与 Qualification 闭环

| 项 | 值 |
|---|---|
| 阶段 | stage2_6_1 |
| 基线 commit | `cd585f4acff6170a2b592d11418066b0c0714b02`(2.6.0j) |
| Freqtrade vendor pin | `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`,clean = true |
| WSL 环境 | CryptoRL-Ubuntu-24.04,conda `freqtrade-rl`(CPython 3.11.16 / numpy 2.4.6 / pandas 3.0.3 / gymnasium 1.3.0 / SB3 2.9.0) |
| Qualification plan digest | `qp-16792c93299170bf7f4e1b41b056c9734ea3aaf913bf8a7acbe2c5074ae0a8b2` |
| **最终判定** | **FAIL**(见 §0) |

## 0. 结论摘要

最终 qualification(一次性、锁定计划 `qp-16792c…`、qualification seed namespace、120 pairs)**如实失败**:

| 判定项 | 结果 | 失败证据 |
|---|---|---|
| 冻结合同未修改 / vendor 未漂移 | PASS | `frozen_contract_integrity.json` / `upstream_integrity.json` |
| pair integrity(120/120) | PASS | `pair_integrity_summary.json`(三族通过率 1.00) |
| 因果矩阵(obs 变异/HTF resample/参考因果) | PASS | `causality_matrix.json` 全部通过 |
| 复现性 / 新 seed 有效性(10/10) | PASS | `generator_reproducibility.json` |
| latent 隔离 | PASS | `latent_isolation_matrix.json` |
| 尝试策略(first_pass, max=5) | PASS | 直方图:{0: 38/40/38, 1: 2/0/2, ≥2: 0} |
| PPO 256-step plumbing smoke | PASS | `curriculum_ppo_256step_smoke.json` |
| **难度排序 D0>D1>D2>D3** | **FAIL** | C3:qualification 语料 D2=+0.18% < D3=+0.55% |
| **D3 仍为正** | **FAIL** | C2:D3 M = **−0.30%**(ref −0.06% < always_flat=0) |
| **参考优于必胜基线(全部 rung)** | **FAIL** | C2 D3:reference −0.06% < always_flat 0.00% |

失败纪律:按任务书 §12,最终 qualification 失败后**未做任何参数修改或重跑**;失败证据完整保留,本阶段如实报告 FAIL,修复留给下一轮任务。

失败机理(详见 §9/§18):
- **C2**:qualification 语料的 D3 rung 上参考策略净收益为 −0.06%(calibration 语料同 rung 为 +0.68%)。C2 参考每 episode 仅约 2-3 笔交易、单笔 edge = α−F = 34−20 = 14bps,参考优势的语料级标准差(约 ±40-60bps)大于 D2/D3 间的设计间隔;该 rung 的 seed 抽样使可交易对齐象限(cue ∧ calm ∧ 1h 趋势可读)出现次数偏少,叠加 always_long 残差 +0.24%,度量转负。**oracle 在同一 rung 上 +1.75%,证明世界结构存在、参考策略捕获不足。**
- **C3**:qualification 语料的 D2 rung 弱于 D3(+0.18% vs +0.55%;calibration 上为 +0.54% vs +0.45%)。同样属于 rung 间设计间隔(<40bps)小于跨语料抽样方差的统计薄边际问题,而非结构缺失(D2 oracle +1.00% > 0)。
- **C1 在 qualification 语料上全部通过**(ladder 34.97 > 10.74 > 4.94 > 3.46,全部判定项 PASS)。

下一轮修复方向(不在本阶段实施):扩大 C2/C3 rung 间设计间隔(α 阶梯与机会密度的更大对比、每 episode 交易数加倍以降低语料方差)、修复 C2 always_long 在个别 episode 的 ±2% 水平残差(banner 截断边界情形)、或采用逐 episode 配对的度量口径。

## 1. 三个课程族各教什么(问题 1-4)

三族是**能力维度正交**的课程,不是同一任务的三个难度:

- **C1(c1_opportunity,机会识别)**:教"什么时候市场存在值得承担 Long 风险的机会,什么时候应该保持 Flat"。世界为分段 regime 链(opp 正漂移 / neut 零 / neg 负漂移),机会的可识别性来自 regime 持续性——局部趋势特征(ma_dev_24)在机会段内持续为正。pair 的 variant B 为"假机会孪生":与 A 共享同一噪声流/段边界/wick/nuisance,唯一差别是 opp/neg 段漂移全部置零——特征看起来仍会因噪声出现"机会样"形态,但动量不再预测任何后续漂移。C1 的资格关系:observation-aware 参考(ma_dev 超 3σ 门限 + 动量确认)必须优于 Always Long / Always Flat,而常数策略恒输摩擦。
- **C2(c2_context,上下文门控)**:教"同一个局部 15m 信号,在不同高周期上下文下是否仍然成立"。世界含两个**正交**上下文:G1 = 1h 尺度方向上下文(等长成对交替链 + 每段中部的单调 banner,由 htf_1h_mom 读取)与 G2 = 4h 尺度波动率体制(calm 12bps / turbulent 100bps 持久链,由 vol_24 读取——方向无关,与 G1 的方向性印记零串扰)。cue 事件以 ± 镜像配对调度(脉冲与收益注入对价格水平成对抵消),单 bar 收益注入 = d × gate × α:局部 cue 与门控同号(d×gate>0)时下一 bar 有正漂移,异号时为负漂移。**pair 机制:variant A 的门控绑 G1(方向),variant B 绑 G2(波动率体制)**——同一局部 cue,在 A 中"1h 趋势向上才有效",在 B 中"calm 体制才有效",因果映射换位而 nuisance 全同。
- **C3(c3_cost,成本敏感择时)**:教"有预测 edge 不代表应该交易;扣除真实 Route C 摩擦后仍值得才交易"。世界为信号事件流(强度三档:strong/marginal/weak + distractor),事件以 ± 镜像配对;单 bar 脉冲(160bps,单 bar 完成,open[t+1] 成交无法免费捕获)使强度可见,收益注入为单 bar d × α × s。可交易判据 G(s) = α·s > F,F 唯一取自 `null_friction.ledger_round_trip_retention`(冻结账本,fee=0.001/slip=0 时 F = 0.001998002);参考阈值 s* = margin×F/α 由冻结摩擦公式推导,**不存在课程专用成本模型**。**pair 机制:variant B 的收益注入为与强度无关的常数(0.3F,亚成本)且强度-收益相关为零**——"gross signal 看似有利但扣费后不值得交易"的直接实现。

为什么不是同一任务的三个难度:三族的可利用信息通道不同(C1 局部趋势持续性 / C2 双正交通文的对齐 / C3 强度对摩擦的相对大小),参考策略读取的特征组不同,失败模式不同(C1 防常数捷径,C2 防 local-only 与单上下文捷径,C3 防无成本意识的 churn)。三者共享统一 observation schema(11 特征)与统一 episode 合同(288 bar @ 15m),难度阶梯各自独立定义。

## 2. D0-D3 的定义与排序证明(问题 5-7)

- **D0(sanity)**:生成器/观察/参考策略链路的最明显可解点(C1 漂移 55bps/bar、C2 α=110bps、C3 strong 档 G≈4.5F)。用于确认"观察真的包含相关信息、参考策略能明显利用它"。
- **D1(teaching)**:主教学区,信号仍清晰但不能依赖最简单捷径。
- **D2(qualification)**:真正要求使用 family 对应能力(C2 双门控对齐、C3 强度阈值选择),是 2.6.2 的重要候选训练难度。
- **D3(stretch)**:接近当前 family 可合理支持的难度边缘(C1 漂移 21bps、C2 α=34bps、C3 strong 稀少 + marginal 跨成本线),可难但不得无信息——D3 的 oracle 诊断在最终语料上全部为正(C1 +14.4%、C2 +1.75%、C3 +1.19%),即世界仍含可利用结构,失败的是参考策略的捕获余量,不是 edge 消失。

难度旋钮(按任务书 §11 允许项组合,不是单纯加噪):C1 = 漂移幅值↓ + 段长↓ + 噪声↑;C2 = 收益注入 α↓ + 机会密度先升后降;C3 = strong 占比↓ + marginal(跨成本线档)占比↑ + distractor 率↑ + α 微降。

度量与排序:M_rung = mean(ref_net) − max(0, mean(always_long_net))(corpus 级口径,对应任务书"跨 pair 稳定胜出"的语义;always_flat 恒 0);排序要求 M_D0 > M_D1 > M_D2 > M3 严格。该定义在锁定计划中冻结。

**排序在 calibration 语料上三族全部成立**(C1 43.8>14.8>6.2>2.4 / C2 1.66>0.92>0.83>0.48 / C3 2.09>1.65>0.54>0.45,百分比),但在最终 qualification 语料上 C3 的 D2/D3 翻转、C2 的 D3 转负——**rung 间设计间隔小于跨语料方差**,这是本阶段 FAIL 的直接原因,也是下一轮必须修复的校准不足(校准阶段应使用双语料交叉验证 rung 间隔)。

## 3. Pair 机制(问题 8)

每个 family × rung × pair_index:A/B 两 episode 由**同一 seed**派生(seed 公式不含 side),`pair_variant` 不进入生成器 seed 派生与 nuisance counter-hash(沿 antithetic_flip 先例)——A/B 逐位共享:收益噪声流(间隔配对反对称噪声)、OHLCV wick 噪声、nuisance 槽位、段/banner/体制/事件时间表、episode 长度与初始价。唯一差别是因果映射(C1 漂移有无 / C2 门控绑定对象 / C3 强度-收益耦合)。

逐 pair 自动验证两层:
1. **确定性构造审计(主判定)**:C1 断言 A 的 opp/neg 段漂移符号正确且 B 的 regime 漂移恒零 + 段表逐位一致;C2 断言 A 的收益注入符号 = sign(g1)×sign(cue) 且与 vol 无关、B 反之 + banner/体制/cue 表逐位一致;C3 断言 A 的毛 edge 随强度严格单调且存在超成本档、B 为亚成本常数且强度相关为零 + 事件表逐位一致。
2. **nuisance 相似 + 已实现统计(报告)**:长度/初始价/volume/nuisance 逐位一致、vol_24 中位数比值 ∈ [0.75,1.35]、A/B 已实现因果指标(如 C2 的 next-bar 收益按门控对齐性分组差)。

"不是两个随机 seed"由共享表逐位断言直接证明。120/120 pair 全部通过(qualification 语料)。

## 4. 捷径防御与基线矩阵(问题 9-11)

- **Always Long 不稳定胜出**:三族世界的所有水平漂移源按构造成对抵消(C1 opp/neg 段总量精确平衡,C2/C3 banner/cue/噪声配对),always_long 语料均值收敛到 −F±小量;最终语料均值 −0.07% ~ +0.24%(C2 D3 的 +0.24% 残差是下一轮要修的边界情形)。
- **Always Flat 恒 0**:被参考策略的正度量压制(C1 全 rung、C2 D0-D2、C3 全 rung 成立;C2 D3 失败)。
- **C2 local-only**(只看 ret_1):两个 variant 上 E[payoff] = 0,只输摩擦——最终语料全部 rung 显著为负(−3.1% ~ −2.4%),受限符合预期。
- **C2 单上下文基线**(只看 htf_1h_mom 或只看 vol_24,与参考同构):报告用(非必胜基线),最终语料上 h1-only −1.3% ~ +0.2%、vol-only +0.1% ~ +1.4%,均不稳定。
- **C3 cost-ignorant**(追一切可见信号):亚成本 weak/marginal 档与 distractor 持续放血,最终语料全部 rung 为负(−0.0% ~ −3.8%),cost-aware 参考全 rung 优于它(此关系在最终语料成立)。
- **C1 朴素动量捷径**(ret_4>0):在 D0-D1 与参考相当(38-47% vs 35-44%),D3 被参考压过(+2.1% vs +3.5%);C1 的资格门是常数策略,朴素动量本身即"机会识别"能力的粗实现,如实报告。

全部 PnL 经冻结 `AlignedLongFlatEnv`(market_open_causal)与冻结账本计算——C3 的摩擦常数直接取自 `null_friction`(问题 11)。

## 5. Latent oracle 与因果观察参考(问题 12-13)

- **latent oracle(诊断专用)**:读 sidecar 当前行(C1:处于 opp 段且距段尾≥2;C2:cue bar 上 d×激活门控>0;C3:信号 bar 上 d>0 且 G>F)。用途:证明世界确实含目标因果结构、测量可解性上限、诊断坏课程。最终语料 oracle 全 rung 为正(含 FAIL 的 C2 D3 = +1.75%)——**失败被定位为参考策略捕获不足/边际过薄,而非世界无结构**。oracle 永不进入候选/PPO 可见面。
- **因果观察参考(资格证明)**:只读当前 ObservationSpec-v1 observation(C1:ma_dev_24/ret_4;C2:ret_1/htf_1h_mom/vol_24;C3:ret_1),无隐藏状态、无未来、无 episode 身份;无状态单 bar 规则(C2/C3 收益注入为单 bar,α 低于 cue 阈值,无再触发)。参考与 oracle 的差 = "冻结观察足以解决该能力"的余量度量。

## 6. 因果与泄漏测试(问题 13)

强制 metamorphic 测试(全部通过,`causality_matrix.json`):
- **observation causality**:市场噪声使用独立派生流,变异按"噪声配对"粒度从指定 bar 起改由盐化 RNG 重抽——变异起点前的 observation 与价格逐位不变,其后实际改变(三族 × cut=150 验证)。
- **HTF causality**:全部特征为因果滚动窗口;generator 的前缀重算校验(截断重建逐位一致)+ 显式验证 htf_1h_mom 在整点对齐处与 pandas `resample("1h")` 的 6-bar 因果等价(≥20 个对齐点)。
- **reference causality**:相同 observation 向量跨 episode/跨 bar 得到相同动作;参考策略接口只接收 observation(policy_api 能力隔离)。
- **latent isolation**:sidecar 列与 observation 列零交集、FORBIDDEN_OBSERVATION_PATTERNS 零命中、observation 构造只依赖 df(清零 sidecar 不改变 observation)。

## 7. Calibration 与 Qualification 隔离(问题 14)

- 两阶段流程:`calibrate`(CLI,calibration namespace,10 pairs/rung,可迭代)→ `lock-plan`(参数/阈值/seed 表/度量/代码身份全部冻结,digest `qp-…` 落盘)→ `qualify`(一次性,qualification namespace)。
- seed 公式 sha256([stage, namespace, family, rung, pair, attempt])[:8] 按 namespace 天然隔离;training namespace 本阶段仅 PPO smoke 使用。fresh_holdout 新 seed 有效性 10/10。
- 校准迭代记录(calibration_summary/raw):包括 C2 的参数网格选择(α 阶梯 × cue 密度,在 calibration 语料上按锁定判据择优)。
- 最终 qualification 在锁定计划下运行一次,FAIL 后**未调参重跑**;`qualification_result.json` 绑定计划 digest,篡改计划会被 `load_locked_plan` 拒绝(有测试)。

## 8. 120 pairs 的真实结果(问题 15-17)

见 §0 表与下表(全部来自 `qualification_result.json`,百分比):

| family | D0 | D1 | D2 | D3 | 排序 | 判定 |
|---|---|---|---|---|---|---|
| C1 M(ref−max(0,long)) | +34.97 | +10.74 | +4.94 | +3.46 | ✓ | PASS |
| C2 M | +1.39 | +1.21 | +0.42 | **−0.30** | ✓(但 D3<0) | FAIL |
| C3 M | +1.79 | +1.13 | +0.18 | +0.55 | **✗(D2<D3)** | FAIL |

- first-pass rate:C1 0.95 / C2 1.00 / C3 0.95;尝试直方图全部 ≤1 次重试;拒绝原因全部结构性(词表内)。
- 256-step PPO smoke(问题 17):PASS——SB3 PPO(MlpPolicy)在 qualified C1 D1 生成器(training namespace seed)上 256 步运行完整,observation shape 12、reward 全有限、无 crash;**其 reward(−0.166)只作 plumbing 证据,不参与任何课程选择**。

## 9. 冻结边界与治理(问题 18-19)

- Route C 六项冻结合同经 `frozen_contract_integrity.json` 确认**完全未修改**(六项版本串逐一比对 + rl_platform 代码树哈希);fee/slippage(0.001/0)/tick rounding/成交时序/terminal liquidation 全部经冻结 env 复用,无课程旁路。
- Freqtrade vendor:`52bc96f4480b…` 未漂移,clean = true。
- 2.6.0j 治理 waiver 见 `governance_waiver.json`(用户决定不再投入其独立安全攻击审计;本阶段不重新打开)。

## 10. Stage 2.6.1 判定(问题 20)

**FAIL。**

按任务书 §24:任何核心 family qualification 不成立即 FAIL——C2 的 D3 度量为负(参考输给 Always Flat)与 C3 的难度排序翻转均属核心不成立。失败证据完整保留于 artifacts;本阶段未做任何失败后的参数修改或重跑;下一轮修复方向见 §0。

## 11. 回归

- 阶段测试:`tests/route_c_stage2_6_1/` 69 项全部通过(覆盖任务书 §21 全部类别:复现/冻结合同/因果/latent 隔离/pair 完整性/三族语义/难度度量数学/尝试策略/计划锁/PPO smoke)。
- 最终 full-cold(`regression_fullcold_summary.json`):16 个目录全部真实 pytest exit 0,**1625 passed / 0 failed / 0 skipped / 0 xfailed / 0 error,all_green = true**,wall = 5041s(含 2.6.1 新目录 69 项与全部历史目录;2.6.0h/0i/0j 独占串行)。

## 12. 工程说明与已知限制

- 新模块:`curriculum261_{api,c1,c2,c3,pairs,qualification,plan,final,smoke,cli}.py`;复用 generator_api/ObservationSchema/param_resolution/evaluator/policies/null_friction/AlignedLongFlatEnv,未修改任何既有模块(新增文件触发保守的 affected 选择规则,已同步 runner)。
- 噪声合同:市场噪声为间隔配对反对称噪声(镜像间隔 U[8,16] bar,配对内同尺度,尾部不可完整放置的配对整体跳过)——这是 always_long 净收益收敛到 −F 的构造基础,也是未来变异测试的粒度单位;相邻配对会产生"完美 1-bar 反转"伪结构,故强制间隔 ≥8。
- C2 的水平残差:个别 episode always_long 达 ±2%(banner 在 episode 末尾状态对不完整时的边界情形),是下一轮修复项之一。
- 已知限制:(1) C2/C3 的 rung 设计间隔未超过跨语料方差,校准阶段应加双语料交叉验证;(2) C2 参考每 episode 交易数偏少(~2-3 笔),语料级方差大;(3) 难度度量未做逐 episode 配对(可降低方差);(4) 120 qualification pairs 不得用作未来训练集,2.6.2 须用 training namespace 新 seed 生成(fresh_holdout 已证明生成器对语料外 seed 正常)。
