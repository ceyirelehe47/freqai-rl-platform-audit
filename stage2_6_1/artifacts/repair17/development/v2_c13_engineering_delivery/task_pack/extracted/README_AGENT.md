# Agent 接手入口：R17 V2 + C1/C3 工程校准

**这是实现任务书包，不是已经写好的生产补丁。** 按 `TASKBOOK.md` 实现，按 `ACCEPTANCE_MATRIX.md` 验收；不要声称本包已经跑过新主实验或本轮全量测试。

## 接手身份

```text
repo：ceyirelehe47/freqai-rl-platform-audit
branch：route-c-stage2-6-1-repair17
baseline：3e377add6f6b3ba68c24a50ccfffe7534983ca9b
parent：5607876b213af825d618868ba89cb0705cfdc472
profile：R17V2C13EngineeringCalibration-v1
```

环境、原始证据与 vendor 规则见任务书第 1 节。上一轮 raw 统计桥已通过工程验收，main/validation 小样本统计 FAIL 保持；不要再修旧桥或重读旧 JSON 冒充 V2 运行。

## 本轮要真正跑通什么

两个三课程统一 fit bank → 原 V2 拟合/保存/重载/冻结 → 两分区 C1/C3 全尺寸工程语料 → 显式 bundle 路由 → 实际 scaled evaluator → 原 R4/R5 strict 统计 → 监护与隔离交付。

这里不包含 C2 正式校准、supervised 资格、formal qualification 或新 PPO/BC 训练实验；“全尺寸”仅指 C1/C3 的 10 pair/rung。

## 已锁定的预算

- 每个分区 fit：C1/C2/C3 × D0–D3 × 6 pair；C3 每层可用 p6、p7 两项备援。
- 每个分区 eval：C1/C3 × D0–D3 × 10 pair；C3 每层可用 p10、p11 两项备援。
- 两 bank 共 144 个 fit pair；两 eval 分区共 160 个评估 pair。
- 全实验最多 336 次 pair 请求、1680 个 pair attempt。每请求内部仍最多 5 次。
- C1/C2 不获得备援权；C3 只有既有五类、证据完整的内容拒绝可消耗同层备援。
- 四个新 namespace 与 C1/C3-D3 的 R4 继承参数见任务书，不使用旧 raw 小试的 C3-D3 默认参数。

## 执行顺序

1. 先读 `TASKBOOK.md`、`ACCEPTANCE_MATRIX.md` 与 `SOURCE_MAP.md`。
2. 实现 profile-aware records 装配和最小 V2 工程接线，复用旧数值/统计实现，不复制一套框架。
3. 先跑局部测试、合成矩阵与零生成接口检查；保留每次失败。
4. 锁定完整主计划、参数、候选身份与一次性工程 claim。
5. 只执行一次固定主实验，经现有 `r17_monitored_entry.sh engineering`。
6. 对现存输出做组合验证、实际隔离；统计 FAIL 不变成工程错误，也不能被提升为资格通过。
7. 做一次包含全部测试的常规 R17-first 回归。既有 1913 项是核对基线，不是凑数目标。
8. 归档原始字节，普通 commit、push，回报远端完整 SHA。

主实验开始后失败不自动修代码重跑同一 profile，不换 namespace、不扩备援，不通过重新生成补证据。

## 交付位置与 Git 要求

```text
stage2_6_1/artifacts/repair17/development/v2_c13_engineering_delivery/
```

**本轮必须提交并推送，不是在本地做完就停止。** 这是 Agent 的交付步骤，不意味着应用脚本要自动 push。按实际文件逐项暂存，审阅 staged diff 和字节一致性，不使用 `git add -A`，不 amend、不 force-push。

```bash
git push origin HEAD:route-c-stage2-6-1-repair17
git rev-parse HEAD
git ls-remote origin refs/heads/route-c-stage2-6-1-repair17
```

结果不佳也可按真实状态提交诊断交付；不得把统计 FAIL、工程故障或缺失日志包装成 PASS。

最终首先列出：工程路径是否完成、C1/C3 各自 main/validation 的 strict 结果、完整 calibration/Stage 2.6.1 尚未签发。然后列实际预算、两个 V2 三层身份、回归/隔离证据和 Git SHA。
