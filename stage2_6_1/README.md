# Stage 2.6.1 报告索引

- 阶段:2.6.1 — C1/C2/C3 Curriculum R&D、难度阶梯与 Qualification 闭环
- 基线 commit:`cd585f4acff6170a2b592d11418066b0c0714b02`(阶段 2.6.0j)
- Freqtrade 上游 pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- 主报告(第一轮,FAIL,历史证据):[route_c_stage2_6_1_curriculum_rd_qualification.md](route_c_stage2_6_1_curriculum_rd_qualification.md)
- Repair R1 报告(FAIL,历史证据):[route_c_stage2_6_1_repair1.md](route_c_stage2_6_1_repair1.md)
  - production ObservationSpec-v1 实际路径切换完成;最终 qualification verdict **FAIL**(C2 D3 为负、C1 pair integrity 0.9;三族难度排序全部成立,C3 完整通过);plan digest `qp-cc44880c…`;第一次执行(含 C1 构造检查实现 bug)已存档于 `artifacts/repair1_attempt1_archived/`
- **Repair R2 报告(PASS,历史证据)**:[route_c_stage2_6_1_repair2.md](route_c_stage2_6_1_repair2.md)
  - robustness gate 三层 enforcement(A/B/C)+ R2 全新 seed space + pair 统一结构合同(accepted ⇒ final integrity=1.0)+ C2 上下文载体重构(wick 几何纹理,close 路径零污染)+ C1 固定段表 + C3 加固 + production preprocessing boundary 正式声明;robustness gate 三族 PASS → plan 锁定 `qp-8f64a1b5…` → 一次性 final qualification **PASS**(120 pairs,三族 integrity=1.0、排序全过、D3 全正);PPO smoke PASS
- **Repair R3 报告(FAIL,历史证据)**:[route_c_stage2_6_1_repair3_preprocessing_qualification.md](route_c_stage2_6_1_repair3_preprocessing_qualification.md)
  - RouteCFeaturePreprocessing-v1 预处理合同:直接复用 pinned vendor `IFreqaiModel.define_data_pipeline`(`VarianceThreshold(0)+MinMaxScaler(-1,1)`,逐位等价证明),统一 offline corpus fit/freeze(三族共享、行序不敏感、position 不缩放、纯参数序列化/重载);reference/baseline 经 inverse-transform wrapper **逐 bar 等价**;conditioning(raw OHLC 贡献 0.636→0.505)与 supervised(W/B 三族 6/6)gate PASS;PPO smoke PASS
  - **curriculum robustness gate FAIL**:§23 pair-cluster 统计口径修复(去掉 episode 假独立 SE 低估)后,C1 的 D3 余量 0.00265 < κ×SE 0.00694、C3 holdout D3 翻负(reference −0.00165 < always_flat 0)——C1/C3 的 D3 设计余量与采样不确定性同量级(R2 的 PASS 在诚实口径下余量并不稳健);按 §22 停止规则未 lock plan、未访问 qualification_r3/preprocess_fit_qualification_r3(final qualification 未执行)
  - 技术债修复:qualification_r3 完整四要素守卫(plan+digest 重算+gate)、CLI/lock 目录统一、重复 `_derive261_seed_raw` 删除、pair-cluster 口径全量生效;2.6.2 输入锁按 R3 登记变更更新(api.py 白名单扩展,R2 seed 派生黄金向量锁定不变)
- **Repair R4 报告(FAIL,历史证据)**:[route_c_stage2_6_1_repair4_d3_qualification.md](route_c_stage2_6_1_repair4_d3_qualification.md)
  - **Preprocessing V2(RouteCFeaturePreprocessing-v2)正式合同闭环**:真无界 outer observation space(`RouteCPreprocessingEnvV2`,feature (-inf,+inf) + position [0,1],SB3/PPO/check_env 全见 outer space,零 clip,对抗探针 ±13 接受);三层 identity(parameter state `r4ps-` / fit manifest multiset `r4fm-` / bundle `r4pb-`,行序不敏感、multiset 敏感、篡改拒绝、envelope 重载 identity 不变);统一 pair 证据表 + 难度=reference−always_flat + 逐固定基线 margin(废除 episode 级 hindsight max)+ bootstrap;全部资格证据 PASS(含 final 全 240 episode 逐 bar reference 等价)
  - **D3 统计功效设计(design_r4,30 pairs/candidate,6+6 预注册候选)**:C1 选定 `c1_a_edge_up`(opp 21→24.5bps,效应比 4.58,gate 通过概率 1.000)、C3 选定 `c3_c_alpha_strong`(α 46→50 + strong 0.14→0.20,效应比 4.70,gate 概率 1.000);pack `r4pk-eca9ed55…` 版本化锁定(C2 与 D0-D2 逐位冻结,历史 namespace 黄金哈希不变)
  - calibration 双 robustness gate **PASS**(C1-D3 0.0203/0.0294、C3-D3 0.0064/0.0084 双语料全正且过 κ×SE;supervised 三族 6/6);plan 锁定 `qp4-72b3a7e8…` → 一次性 final qualification **FAIL(34/36)**:**本轮授权修复的 C1(0.0244 ≥ κ×SE 0.0104)与 C3(0.0084 ≥ 0.0037)全部条件通过;唯无授权修改的冻结族 C2 在 fresh 语料上 D2 0.0070 < D3 0.0085 排序翻转**(其 D2-D3 设计间距 ~1.7×SE 本就功效不足);语料已暴露,证据完整;两次 governance waiver 登记(gate 口径对齐 R3 预注册规则 + final 崩溃于 corpus 生成前的路径 bug 恢复)
  - 回归:targeted 196 + affected 1631(含 2.6.2 输入锁 150)全绿;full-cold 依 §36 不执行;C3 PPO Branch D 仍开放;Stage 2.6.2 仍 FAIL

- **Repair R5 报告(当前轮,FAIL,诚实 FAIL)**:[route_c_stage2_6_1_repair5_c2_ladder_qualification.md](route_c_stage2_6_1_repair5_c2_ladder_qualification.md)
  - **治理修复**:唯一 strict per-corpus PASS 口径(`r5sg-` identity,数据前冻结;pooled 仅诊断且测试锁定不可救援);exposure marker 硬合同(原子 O_EXCL 创建/单向状态机 running→terminal/append-only ledger 兜底删除检测/无 delete API/flock 并发互斥);qualification_r5 六要素守卫(plan+digest+gate+pack+sealed preflight attestation);两级 preflight(static 用非 final namespace,sealed 零 final seed 访问);Tier B namespace 机械授权守卫(tier A 全部不合格才解锁)
  - **C2 两级预注册 design(design plan `r5dp-0c1eb69f…` 先于数据锁定;每候选双开发语料 × 40 pairs)**:Tier A(D3-only,6 候选:α 24-27 / vol 13-20 / κ 0.25-0.30)0/6 合格 → 机械触发 Tier B(D2+D3 joint,3 候选:D2 α≤44)0/3 合格 → 按预注册规则 **R5 = FAIL,停止于 design,不进 calibration**;未生成 parameter pack,final namespace 零访问、exposure 零消耗
  - **根因标定**:C2 功效不足是 ladder 全局性质——冻结的 D0-D1 间距(0.0054-0.0061)< κ×SE(n=10)(0.0063-0.0070),单条件通过概率仅 0.38-0.51,封顶全部 strict 条件联合概率 ≤0.25(门槛 0.90);Tier B 上调 D2 拉开 D2-D3(ratio 2.10-4.02)但压缩 D1-D2(0.34-0.64);密度门槛全部通过(median trades 10-14 ≥ 8,label rate 2.0-2.4% ≥ 1.5%),非"机会删除"型伪难度
  - 基础设施:V2 逐位复用(R5 不改数值,C1/C3 R4 继承值经 `r4pk-eca9ed55…` artifact digest 复算黄金绑定);55 项 R5 测试 + 2.6.1 全套 251 + 2.6.2 全套 150 全绿;PPO smoke PASS;full-cold 依 §32 不执行;C3 PPO Branch D 仍开放

## 目录

| 内容 | 位置 |
|---|---|
| C1/C2/C3 生成器与资格基础设施 | `src/rl_curriculum/curriculum261_*.py`(41 个模块,含 production_obs、8 个 r3 模块、11 个 r4 模块与 10 个 r5 模块) |
| 阶段测试(251 项,含 production obs 守卫、R2/R3/R4 协议与统计测试) | `tests/route_c_stage2_6_1/` |
| 回归 runner(含 2.6.1 目录与 RouteCStrategy 规则) | `runner/` |
| 第一轮 artifacts(FAIL 历史证据,未改动) | `artifacts/`(顶层) |
| Repair R1 artifacts(calibration/holdout/gate/plan/final/smoke) | `artifacts/repair1/` |
| Repair R1 第一次执行存档(实现 bug,保留) | `artifacts/repair1_attempt1_archived/` |
| Repair R2 artifacts(gate/stress/C2 诊断/plan/final/smoke/exposure,30 份) | `artifacts/repair2/` |
| Repair R3 artifacts(audit/等价/合同身份/双 fit bank/conditioning/supervised/双 gate/回归,26 份;qualification 产物依 §22 未生成) | `artifacts/repair3/` |
| **Repair R4 artifacts(design/power/pack/V2 合同/manifest/bundle/pair 表/双 gate/final qualification(FAIL 证据)/smoke/回归,69 份)** | `artifacts/repair4/` |
| 治理 waiver(2.6.0j 安全审计不再投入) | `artifacts/governance_waiver.json` |
| **Repair R5 artifacts(启动审计/design plan+digest/Tier A+B results/decision/selection/power 汇总/smoke,16 份;calibration 及后续依 §17/§35 未生成)** | `artifacts/repair5/` |

## 一句话语义

三个能力维度不同的课程族(C1 机会识别 / C2 上下文门控 / C3 成本敏感择时),每族四档难度(D0 sanity → D3 stretch),pair 级 nuisance 控制 + 因果映射换位;policy observation 一律经生产 RouteCStrategy 特征构造 + 冻结 AlignedLongFlatEnv(repair R1 起);全部收益经冻结 Route C 账本计算;calibration(双语料+robustness gate)与 qualification seed 隔离;计划锁定后一次性最终资格运行,失败如实报告。
