# 阶段 2.6.0b:密封执行、可信训练来源与评估统计最终修复

> **阶段 2.6.0a 的全局 PASS 已被重新审查。**
> 原因是:实际时长未物化(duration_hours 只进哈希、生成器退回 96 行
> 默认)、正式候选缺少系统级沙箱(仅 JSON-lines 子进程,共享文件系统/
> PID/网络,且 --no-subprocess 可绕过)、nuisance 检验单边(大幅恶化
> 仍可通过)、反作弊重复证据不真实(单 Episode + 考试包总数冒充
> 复制数,缺崩溃证据时默认成立)、正式资格可自我声明(sidecar 自填
> formal_eligible 即生效)、block shuffle 被误当完全无信号 Null。
>
> **本目录只完成最终评估基建修复,未开始正式课程训练。**

- 判定:**PASS**(详见 report/route_c_stage2_6_0b_final_sealed_execution.md)
- 测试:2.5 → 2.6.0b 全量回归通过(数字见报告与
  artifacts/regression_test_summary.md)
- 上游:Freqtrade 2026.7(commit 52bc96f)clean,零修改
- RouteCEnvCore-v1.0.0 冻结未修改

## 本阶段修复(工作包 A-J)

| 工作包 | 修复 |
|---|---|
| A 真实时长物化 | 统一参数解析:duration_hours/regime 时长范围/特征窗口/决策间隔等真实时间字段 → resolved bars 注入生成器;实际行数强校验;禁止静默默认 |
| B 移除候选身份 token | reset_episode() 无参数;worker reset 消息逐字节 {"op":"reset"};随机基线确定性迁移到 episode_instance 工厂 |
| C 系统级密封沙箱 | unshare(user+mount+pid+proc+net)+ Landlock(ABI v4,deny-by-default)+ 只读中性 checkpoint 路径 + rlimits + 协议限制;--no-subprocess 删除;最小候选运行时(rl_candidate_runtime);十类攻击探针全部失败 |
| D nuisance 双边等价 | 预注册等价区间 [-δ,+δ]/动作一致率/换手与仓位容差;显著改善与显著恶化均 FAIL |
| E 真实多 seed 反作弊证据 | 逐作弊原因独立聚合实际 Episode/seed 计数;共同前缀 3 Episode × 3 切割点;缺崩溃证据 → EXAM_INVALID(不默认成立) |
| F 生成器实现绑定 | 逐族 implementation hash(实际类源码/模块/MRO/依赖/资源/版本);不再是共享 generators.py 哈希 |
| G 可信训练 attestation | Ed25519 签名;sidecar 只证明 format_compatible;formal_eligible 唯一来源是受信签发方;十项篡改矩阵全拒 |
| H Null 重新资格审查 | block shuffle 降级为 partial_dependency_destruction 诊断族;新增第三机制 probe_null_stochvol;三族通过五项资格审查并绑定进承诺 |
| I 版本升级 | candidate-worker-v2 / checkpoint-manifest-v3 / training-attestation-v1 / sealed-exam-commitment-v2 / course-verdict-spec-v2 / hidden-exam-cli-v3;旧版本显式拒绝 |
| J mock 全链路 | 评估方准备 → 受控训练 + 签发 → 沙箱评估 → 冻结判定 → 幂等;十四项篡改矩阵全部 EXAM_INVALID |

## 目录

- `report/` 主报告
- `src/` rl_curriculum(评估侧)+ rl_candidate_runtime(最小候选
  运行时,沙箱内唯一项目代码)+ rl_platform(冻结环境核心,未修改)
- `experiments/` run_all.py(全部证据生成)与 run_regression.sh
- `tests/` 阶段 2.6.0b 新增测试(32 个文件)
- `artifacts/` 24 项证据
- `logs/` 回归日志

## 声明

本目录包含 mock 沙箱 profile、mock issuer 公钥、mock attestation、
mock sealed commitment、严格 Null 探针、拒绝测试结果与聚合统计;
不包含任何真实签发私钥、正式隐藏考试种子、私有生成器、正式
sealed commitment、模型二进制、真实行情、数据库或 API Key。
