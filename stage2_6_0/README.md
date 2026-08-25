# 阶段 2.6.0:Route C 课程资格审查、泛化审计与反作弊基础设施

> **本阶段只建立课程和泛化审计基础设施;未开始正式人工课程训练;
> mock-hidden pack 不具备正式考试资格。**

- 判定:**PASS**(30 项 PASS 条件全部成立,13 项 FAIL 条件零命中)
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / Python 3.11.16
- 上游:Freqtrade 2026.7(commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,clean)
- 测试:438 项全部通过(2.5 38 / 2.5.1 74 / 2.5.2 78 / 2.5.2a 81 / 2.6.0 167);
  未修改、删除、skip、xfail 任何旧测试
- 基准提交:阶段 2.5.2a ce4913b019f38f315dc99665b8ea64f69f9f2d39

## 内容

| 目录 | 说明 |
|---|---|
| `report/` | 主报告(28 节:冻结/修复/时间尺度/章程/生成器/基线/评估器/泛化等级/反事实/Null/作弊检测/隐藏考试/退休/迁移协议/统计/回归/限制/复现命令/证据索引) |
| `src/rl_curriculum/` | 课程审计基础设施(timebase/charter/generator_api/generators/policies/evaluator/counterfactual/grades/verdicts/exam_pack/checkpoints/transfer/hidden_exam_cli/probe_charter) |
| `src/rl_platform/` | 环境核心冻结版本(versions.py,RouteCEnvCore-v1.0.0)与终端观察修复后的 env.py |
| `experiments/` | run_audit.py(全部 artifacts 入口,幂等可重复执行);run_experiment_stage2_5_2a_modified.py(缺失预测目录致命化后的 runner,供复现对照) |
| `tests/route_c_stage2_6_0/` | 22 个测试文件 167 项(任务书指定清单全覆盖) |
| `artifacts/` | 23 个关键证据 JSON/MD/TXT(无模型二进制;测试级 checkpoint 已排除) |
| `logs/` | 全量回归与审计运行的原始输出 |

## 核心结论

1. **RouteCEnvCore-v1.0.0 已冻结**(含两项冻结前修复:终端观察仓位归零 /
   freqtrade 成功但预测目录缺失致命化);版本进入指纹、manifest 与
   checkpoint sidecar,不兼容 checkpoint 拒绝加载。
2. **时间尺度系统**:课程参数以真实时间表达,gamma =
   exp(log(0.5)×step/half_life),5m/15m/1h 折扣等价(最大误差 2.3e-14)。
3. **课程章程**可规范化+哈希(22 必填字段);示例为审计探针课程
   (非正式趋势课程)。
4. **探针课程资格 QUALIFIED**:Oracle(+5.9%) > 可观察规则(+2.2%) >
   trivial(<=0);Always Long 中位 -8.5% 且 q10 深亏。
5. **Null Control** 切断全部可预测优势(Oracle 超额中位 -0.05%,
   bootstrap CI 含 0);NullOvertrader 高换手+扣费亏损挂科。
6. **五类故意作弊策略全部被识别**:StepCounter / AbsolutePrice /
   Periodic / FutureLeak -> SUSPECTED_CHEATING(细分原因);
   NullOvertrader -> 普通挂科。
7. **评估器完全确定**:重复运行与输入顺序无关;正式评估 deterministic。
8. **隐藏考试隔离**:mock-hidden pack 聚合输出脱敏;详细结果公开即退休,
   复用被拒(EXAM_INVALID);公开仓库不含任何隐藏种子(本阶段未创建)。
9. **G5 Warm/Cold 迁移协议**已定义并可运行空白演示(NEUTRAL)。

## 红线遵守

- 未修改 Freqtrade 核心;上游 clean;
- 未修改 market_open_causal 成交、费用、奖励或终端清算合同
  (冻结前修复只涉终端观察字段与 runner 失败路径);
- 未开始正式趋势课程训练、多 seed PPO 或真实市场训练;
- 极短测试级 PPO(128 步)仅用于确认评估器能读取 SB3 模型;
- 公开材料不含:正式隐藏考试种子/生成器、模型二进制、真实行情、
  SQLite、API Key、代理认证、私密路径。

## 复现

```bash
# WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl
python -m pytest tests/route_c_stage2_6_0/ -q                    # 167 passed
python experiments/route_c_stage2_6_0/run_audit.py               # 全部 artifacts(幂等)
python -m rl_curriculum.hidden_exam_cli --help                   # 隐藏考试 CLI
```
