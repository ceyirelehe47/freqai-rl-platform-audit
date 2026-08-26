# 阶段 2.6.0a:正式评估隔离、密封考试与 Observation 合同加固

> **阶段 2.6.0 的全局 PASS 已被重新审查。**
> 原因是普通策略接口可访问隐藏/未来数据,且隐藏考试未被密封绑定:
> 单一 ActContext 把完整 df/n_rows/hidden/future_returns 交给每一个
> 候选;隐藏 CLI 无预承诺,考试条件可命令行改写,PASS 只看总体收益
> 中位数,脱敏输出泄漏生成器族/参数桶,无关特征注入改变 observation
> 维度,常数动作可被误判周期作弊。
>
> **本目录只加固正式评估基础设施,未开始正式课程训练。**
> **公开 mock hidden pack 不具备正式考试资格。**

- 判定:PASS(619 项测试全部通过;主报告见 `report/`)
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / Python 3.11.16
- 上游:Freqtrade 2026.7,commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,
  工作树 clean;RouteCEnvCore-v1.0.0 未修改
- 是否允许进入阶段 2.6.1:允许

## 目录

| 目录 | 内容 |
|---|---|
| `report/` | 主报告 `route_c_stage2_6_0a_sealed_evaluation_hardening.md` |
| `src/rl_curriculum/` | 本阶段全部实现(observation schema / 策略接口 / 探针 / 评估器 / 反事实 / 密封考试 / 判定器 / attempt registry / 子进程候选 / CLI / mock 基础设施) |
| `src/rl_platform/` | env.py 与 versions.py(冻结核心,未修改,供阅读对照) |
| `tests/route_c_stage2_6_0/` | 阶段 2.6.0 测试的更新版(错误隔离语义的断言已替换为更严格断言;差异清单见主报告第 24 节) |
| `tests/route_c_stage2_6_0a/` | 本阶段 33 个新测试文件(166 项) |
| `experiments/` | `run_all.py`(证据生成)与 `run_regression.sh`(全量回归) |
| `artifacts/` | 23 个证据文件(能力矩阵/隔离 trace/篡改矩阵/作弊-挂科矩阵/多 Null 报告/固定维度 G4 烟雾/密封流程闭环/回归汇总/上游完整性) |
| `logs/` | 回归逐目录日志 |

## 本阶段建立的核心合同

1. 候选策略只收 observation(`act(observation)`),子进程隔离 + 错误脱敏;
2. Oracle 独立上下文(当前行隐藏状态+仓位);作弊探针独立测试协议,
   正式入口拒绝;
3. 课程级 observation schema:有序特征/维度/window/dtype/归一化
   pipeline/账户槽位/预注册 nuisance 槽位,可哈希并绑定 checkpoint
   sidecar v2 与密封承诺;同维度特征换序拒绝;
4. sealed exam commitment:pack(含 timeframe 与解析时长)/章程/
   schema/规范版本/generator+evaluator+counterfactual+verdict 代码哈希/
   完整 EvalConfig 逐项预承诺;CLI 必须提供 --sealed-manifest,
   无忽略哈希通道;
5. formal_eligible 守卫(v1/legacy/smoke checkpoint 拒绝);
6. 冻结判定器:G4 硬门组合 -> PASS/FAIL/SUSPECTED_CHEATING/
   EXAM_INVALID;median>0 不足以 PASS;
7. 默认隐藏输出最小化 + attempt registry 幂等可审计;详细披露立即
   退休考试包;
8. 固定维度 nuisance 槽位考试(shape 恒定;vol_24 不再被当无关特征);
9. 作弊四门证据(原始有效成绩+依赖禁止变量+优势崩溃+多 Episode
   重复);常数动作/未学习模型判 FAIL;
10. generate() 自动执行精确 observation whitelist 与特征因果前缀校验;
11. 多类 Null(符号随机化/分块重排/波动状态条件随机化)跨族一致;
    Fourier 相位替身经验证保留线性自协方差被否决(记录见报告第 21 节)。

## 复现

```bash
source ~/projects/crypto_rl/activate-freqtrade.sh
cd ~/projects/crypto_rl
python experiments/route_c_stage2_6_0a/run_all.py       # 全部证据
bash   experiments/route_c_stage2_6_0a/run_regression.sh # 619 项回归
```

## 不包含

- 正式隐藏种子/正式隐藏生成器/真实考试 commitment(仅公开 mock);
- 模型二进制(测试 checkpoint 留在 WSL 工作区,不进公开仓库);
- 真实行情、SQLite 数据库、API Key、代理认证、私密路径。
