# Stage 2.6.1 报告索引

- 阶段:2.6.1 — C1/C2/C3 Curriculum R&D、难度阶梯与 Qualification 闭环
- 基线 commit:`cd585f4acff6170a2b592d11418066b0c0714b02`(阶段 2.6.0j)
- Freqtrade 上游 pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- 主报告(第一轮,FAIL,历史证据):[route_c_stage2_6_1_curriculum_rd_qualification.md](route_c_stage2_6_1_curriculum_rd_qualification.md)
- Repair R1 报告(FAIL,历史证据):[route_c_stage2_6_1_repair1.md](route_c_stage2_6_1_repair1.md)
  - production ObservationSpec-v1 实际路径切换完成;最终 qualification verdict **FAIL**(C2 D3 为负、C1 pair integrity 0.9;三族难度排序全部成立,C3 完整通过);plan digest `qp-cc44880c…`;第一次执行(含 C1 构造检查实现 bug)已存档于 `artifacts/repair1_attempt1_archived/`
- **Repair R2 报告(PASS,历史证据)**:[route_c_stage2_6_1_repair2.md](route_c_stage2_6_1_repair2.md)
  - robustness gate 三层 enforcement(A/B/C)+ R2 全新 seed space + pair 统一结构合同(accepted ⇒ final integrity=1.0)+ C2 上下文载体重构(wick 几何纹理,close 路径零污染)+ C1 固定段表 + C3 加固 + production preprocessing boundary 正式声明;robustness gate 三族 PASS → plan 锁定 `qp-8f64a1b5…` → 一次性 final qualification **PASS**(120 pairs,三族 integrity=1.0、排序全过、D3 全正);PPO smoke PASS
- **Repair R3 报告(当前轮,FAIL,诚实 FAIL)**:[route_c_stage2_6_1_repair3_preprocessing_qualification.md](route_c_stage2_6_1_repair3_preprocessing_qualification.md)
  - RouteCFeaturePreprocessing-v1 预处理合同:直接复用 pinned vendor `IFreqaiModel.define_data_pipeline`(`VarianceThreshold(0)+MinMaxScaler(-1,1)`,逐位等价证明),统一 offline corpus fit/freeze(三族共享、行序不敏感、position 不缩放、纯参数序列化/重载);reference/baseline 经 inverse-transform wrapper **逐 bar 等价**;conditioning(raw OHLC 贡献 0.636→0.505)与 supervised(W/B 三族 6/6)gate PASS;PPO smoke PASS
  - **curriculum robustness gate FAIL**:§23 pair-cluster 统计口径修复(去掉 episode 假独立 SE 低估)后,C1 的 D3 余量 0.00265 < κ×SE 0.00694、C3 holdout D3 翻负(reference −0.00165 < always_flat 0)——C1/C3 的 D3 设计余量与采样不确定性同量级(R2 的 PASS 在诚实口径下余量并不稳健);按 §22 停止规则未 lock plan、未访问 qualification_r3/preprocess_fit_qualification_r3(final qualification 未执行)
  - 技术债修复:qualification_r3 完整四要素守卫(plan+digest 重算+gate)、CLI/lock 目录统一、重复 `_derive261_seed_raw` 删除、pair-cluster 口径全量生效;2.6.2 输入锁按 R3 登记变更更新(api.py 白名单扩展,R2 seed 派生黄金向量锁定不变)

## 目录

| 内容 | 位置 |
|---|---|
| C1/C2/C3 生成器与资格基础设施 | `src/rl_curriculum/curriculum261_*.py`(19 个模块,含 production_obs 与 8 个 r3 模块) |
| 阶段测试(153 项,含 production obs 守卫、R2/R3 协议测试) | `tests/route_c_stage2_6_1/` |
| 回归 runner(含 2.6.1 目录与 RouteCStrategy 规则) | `runner/` |
| 第一轮 artifacts(FAIL 历史证据,未改动) | `artifacts/`(顶层) |
| Repair R1 artifacts(calibration/holdout/gate/plan/final/smoke) | `artifacts/repair1/` |
| Repair R1 第一次执行存档(实现 bug,保留) | `artifacts/repair1_attempt1_archived/` |
| Repair R2 artifacts(gate/stress/C2 诊断/plan/final/smoke/exposure,30 份) | `artifacts/repair2/` |
| **Repair R3 artifacts(audit/等价/合同身份/双 fit bank/conditioning/supervised/双 gate/回归,26 份;qualification 产物依 §22 未生成)** | `artifacts/repair3/` |
| 治理 waiver(2.6.0j 安全审计不再投入) | `artifacts/governance_waiver.json` |

## 一句话语义

三个能力维度不同的课程族(C1 机会识别 / C2 上下文门控 / C3 成本敏感择时),每族四档难度(D0 sanity → D3 stretch),pair 级 nuisance 控制 + 因果映射换位;policy observation 一律经生产 RouteCStrategy 特征构造 + 冻结 AlignedLongFlatEnv(repair R1 起);全部收益经冻结 Route C 账本计算;calibration(双语料+robustness gate)与 qualification seed 隔离;计划锁定后一次性最终资格运行,失败如实报告。
