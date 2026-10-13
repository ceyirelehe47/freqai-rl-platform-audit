# R5 证据收口追加说明（R5_EVIDENCE_CLOSURE_ADDENDUM）

- 轮次：RouteC_PositionControl_R5_EvidenceClosure_v1（2026-10-13）
- 性质：**docs-only 追加文档**。本文件不改任何源码/测试/预算注册表/
  运行入口；不改写任何历史原件字节。
- 本补充轮零执行：未运行 pytest/探针/数学求解/模型加载/生成/经济
  env.step（与任务书"本轮严格零执行"一致）。

## 更正对象

`R5_ENGINEERING_REPORT.md`（本目录，SHA256
`c01c5128d9783ae40cf8293719088d5e17b9a1cd737c5d3cadeb5d4085d3c29b`，
原字节保留）L10–12 段：

> 预算面:本任务未开新真实账本。**真实 PPO learn/optimizer=0、
> BC=0、真实课程生成=0、真实经济 env.step=0**;全部复现用记录型
> 临时账本、工作边界替身与固定 horizon3 纯数学完成。

**该段自本追加文档起撤回/取代**，更正后口径：

1. **真实课程生成=0 不成立**：R5 轮全量回归（558 项，553 过/3 败/
   2 跳）与 economy 基线复跑中，通过节点无条件执行了真实
   `generate_episode`（一份全量记录静态推导下界 ≥67 次；主 Agent 与
   reviewer 各一份记录，合计 ≥134 次）。锚点节点
   `TestDPReferenceExactness::test_chain_matches_generator_empirical_transitions`
   的 range(60) 循环已由收口审查独立确认。
2. **真实经济 env.step=0 不成立**：同一批运行中通过节点在真实
   `HybridPositionEnv` 上保障执行步（一份全量记录 ≥89 次、一份
   economy 复跑 ≥24 次；两方合计 ≥226 次）。
3. **真实 PPO learn=0 成立但有边界**：`.learn()` 训练在两份全量记录中
   确为 0（仅有的两个 learn 测试 fail-closed 跳过）；但真实 SB3 PPO
   模型构造（含 Adam optimizer 构造、cuda 设备、策略前向）在 ≥5 个
   通过节点发生（console 的 SB3 GPU UserWarning 为直接痕迹）。
   "optimizer 调用=0"按构造面口径不成立。
4. **BC=0 成立**（静态扫描无执行面）。
5. 探针（8/19、19/19）与定向 25 项对上述零资源声明为真——错在把
   该声明扩大为对整个 R5 轮（含全量回归）的主张。旧测试属历史回归、
   生成规格为玩具合成、未设 POSCTL 账本，均不构成豁免；无账本只说明
   未被计量，不说明未发生。

## 现行有效状态

- **代码 A/B（BIND/P1、C4-EVIDENCE/P2）验收通过结论直接复用不变**
  （候选 `eec4b0c2b65bf68557e7ad883b8d455129e6ec43`；收口审查
  分层结论 A=PASS、B=PASS）。
- **R5 历史资源合规 = FAIL，保留不追认**：违反当轮零资源授权边界，
  已如实归档；不退款、不扩额、不补历史账本。
- **本补充轮 = 零执行**（仅文件读取/摘要/JUnit 解析/静态源码检查/
  追加文档/封包校验）。
- 出口状态（说明性）：`R5_EVIDENCE_CORRECTED_PENDING_ACCEPTANCE`。

## 完整材料

更正说明全文、逐次执行清点（E1–E14）、静态下界方法与节点级证据、
原件索引（路径+SHA256）、独立 reviewer 补充原文与新旧绑定，见补充包：
`F:/trading/acceptance/PosCtl_R5_EvidenceClosure_20261013/delivery/`
四件（RETURN ZIP + sidecar + 两回执）。旧四件
`F:/trading/acceptance/PosCtl_R5_20261013/delivery/` 原字节保留
（ZIP SHA256 `279d62c37c0aa1a213dda676a60424c27560c1a5ccb2835583dd72c04d01241a`）。

本追加不授权任何新训练、新正式运行、渐进课程提案实施或 R6 代码修复。
