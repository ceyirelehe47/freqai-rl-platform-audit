# Stage 2.6.1 报告索引

- 阶段:2.6.1 — C1/C2/C3 Curriculum R&D、难度阶梯与 Qualification 闭环
- 基线 commit:`cd585f4acff6170a2b592d11418066b0c0714b02`(阶段 2.6.0j)
- Freqtrade 上游 pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- 主报告:[route_c_stage2_6_1_curriculum_rd_qualification.md](route_c_stage2_6_1_curriculum_rd_qualification.md)
- **最终判定:FAIL**(最终 qualification 语料上 C2 的 D3 度量为负、C3 的 D2<D3 排序翻转;详见主报告 §0 与 `artifacts/qualification_result.json`)

## 目录

| 内容 | 位置 |
|---|---|
| C1/C2/C3 生成器与资格基础设施 | `src/rl_curriculum/curriculum261_*.py`(10 个新模块) |
| 阶段测试(69 项) | `tests/route_c_stage2_6_1/` |
| 回归 runner(含 2.6.1 目录) | `runner/` |
| 校准 / 计划锁定 / 最终资格 / PPO smoke / 因果 / 完整性 artifacts | `artifacts/` |
| 治理 waiver(2.6.0j 安全审计不再投入) | `artifacts/governance_waiver.json` |

## 一句话语义

三个能力维度不同的课程族(C1 机会识别 / C2 上下文门控 / C3 成本敏感择时),每族四档难度(D0 sanity → D3 stretch),pair 级 nuisance 控制 + 因果映射换位;全部收益经冻结 Route C 账本计算;calibration 与 qualification seed 隔离;计划锁定后一次性最终资格运行,失败如实报告。
