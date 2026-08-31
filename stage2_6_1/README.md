# Stage 2.6.1 报告索引

- 阶段:2.6.1 — C1/C2/C3 Curriculum R&D、难度阶梯与 Qualification 闭环
- 基线 commit:`cd585f4acff6170a2b592d11418066b0c0714b02`(阶段 2.6.0j)
- Freqtrade 上游 pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- 主报告(第一轮,FAIL,历史证据):[route_c_stage2_6_1_curriculum_rd_qualification.md](route_c_stage2_6_1_curriculum_rd_qualification.md)
- Repair R1 报告(FAIL,历史证据):[route_c_stage2_6_1_repair1.md](route_c_stage2_6_1_repair1.md)
  - production ObservationSpec-v1 实际路径切换完成;最终 qualification verdict **FAIL**(C2 D3 为负、C1 pair integrity 0.9;三族难度排序全部成立,C3 完整通过);plan digest `qp-cc44880c…`;第一次执行(含 C1 构造检查实现 bug)已存档于 `artifacts/repair1_attempt1_archived/`
- **Repair R2 报告(当前轮,PASS)**:[route_c_stage2_6_1_repair2.md](route_c_stage2_6_1_repair2.md)
  - robustness gate 三层 enforcement(A/B/C)+ R2 全新 seed space + pair 统一结构合同(accepted ⇒ final integrity=1.0)+ C2 上下文载体重构(wick 几何纹理,close 路径零污染)+ C1 固定段表 + C3 加固 + production preprocessing boundary 正式声明;robustness gate 三族 PASS → plan 锁定 `qp-8f64a1b5…` → 一次性 final qualification **PASS**(120 pairs,三族 integrity=1.0、排序全过、D3 全正);PPO smoke PASS

## 目录

| 内容 | 位置 |
|---|---|
| C1/C2/C3 生成器与资格基础设施 | `src/rl_curriculum/curriculum261_*.py`(11 个模块,含 production_obs) |
| 阶段测试(106 项,含 production obs 守卫与 R2 协议测试) | `tests/route_c_stage2_6_1/` |
| 回归 runner(含 2.6.1 目录与 RouteCStrategy 规则) | `runner/` |
| 第一轮 artifacts(FAIL 历史证据,未改动) | `artifacts/`(顶层) |
| Repair R1 artifacts(calibration/holdout/gate/plan/final/smoke) | `artifacts/repair1/` |
| Repair R1 第一次执行存档(实现 bug,保留) | `artifacts/repair1_attempt1_archived/` |
| **Repair R2 artifacts(gate/stress/C2 诊断/plan/final/smoke/exposure,30 份)** | `artifacts/repair2/` |
| 治理 waiver(2.6.0j 安全审计不再投入) | `artifacts/governance_waiver.json` |

## 一句话语义

三个能力维度不同的课程族(C1 机会识别 / C2 上下文门控 / C3 成本敏感择时),每族四档难度(D0 sanity → D3 stretch),pair 级 nuisance 控制 + 因果映射换位;policy observation 一律经生产 RouteCStrategy 特征构造 + 冻结 AlignedLongFlatEnv(repair R1 起);全部收益经冻结 Route C 账本计算;calibration(双语料+robustness gate)与 qualification seed 隔离;计划锁定后一次性最终资格运行,失败如实报告。
