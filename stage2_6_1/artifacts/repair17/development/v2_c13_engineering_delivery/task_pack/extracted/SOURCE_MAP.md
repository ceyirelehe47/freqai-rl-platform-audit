# 本任务的仓库依据与实现导航

## 固定来源

仓库：`ceyirelehe47/freqai-rl-platform-audit`  
本轮编写时核对的分支 HEAD：`3e377add6f6b3ba68c24a50ccfffe7534983ca9b`  
分支：`route-c-stage2-6-1-repair17`

本文列出的来源是现有实现依据，不表示这些文件全都需要修改。新增预算、工程 profile 和分区名字是本任务的设计决定，不是声称仓库已经实现。

| 固定基线文件 | 本轮使用/注意点 |
|---|---|
| `stage2_6_1/runner/r17_c3_reserve_batch.py` | 已验收的固定v1：2+2、特定namespace、C3-D3默认46；不能猴子补丁改成新profile。可复用小型字节/摘要原语和调度思路，保持旧产物合同。 |
| `stage2_6_1/runner/r17_c3_reserve_adapter.py` | 现有生成器、EnvelopeRecorder、PairRecord/完整性与评估的薄接线；新profile必须传入正确参数而非复制旧默认。 |
| `stage2_6_1/runner/r17_c3_calibration_bridge.py` | 已验收的raw结果统计消费端；固定旧manifest、2pair/rung，不直接承接本轮新语料。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r17_calibration.py` | `generate_fit_bank_r17` / `fit_preprocessor_v2_from_bank_r17` 常规6pair/rung；C1/C3 corpus委托R6，旧循环会自行生成。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r6_calibration.py` | 三课程统一fit bank、显式records的V2拟合、C1/C3消费`rung_report_r4`的路径。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r17_orchestrator.py` | C1/C3常规10pair/rung，已有role/profile语义及reference等价检查。整个orchestrator还含本轮未授权的其他工作，不可直接全开。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r17_param_pack.py` | C1/C3-D3继承R4；C2三候选；不要用小规模fit控制配置伪装正式design选择。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r6_param_pack.py` | `R4_SELECTED_C1_D3`、`R4_SELECTED_C3_D3`与R4摘要；`r6_family_rung_params`/override原语。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r4_preprocessing.py` | V2三层identity、原envelope字段、load/recompute、位置槽和真实空间声明；`verify()`需与冻结值额外对照。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r17_routing.py` | 既有main/holdout路由、`R17BundleRouting`/ledger；新profile必须明确期望，不能只信复制的缓存hash。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r17_reference.py` | `PolicyVisibleReferenceCanonicalization-v1`、已选records的等价性入口；runtime float32与数学逆/legacy诊断区分。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r4_pairs.py` | `evaluate_pair_corpus_r4(preproc=...)`、`rung_report_r4`、pair-cluster统计；无需重写收益或bootstrap。 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r5_pairs.py` | `corpus_conditions_r5`，κ=1.5，strict逐corpus，pooled只诊断。 |
| `stage2_6_1/runner/r17_required_bytes.py` | 全部monitor required字节核验，直接复用。 |
| `stage2_6_1/runner/r17_monitored_entry.sh` / `r17_sync.sh` | 单例监护、固定环境与双树同步；不在本轮改停止协议。 |

## 直接链接

- [R17 参数包](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/src/rl_curriculum/curriculum261_r17_param_pack.py)
- [R4 继承常量与 override](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/src/rl_curriculum/curriculum261_r6_param_pack.py)
- [R17 当前校准编排与规模](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/src/rl_curriculum/curriculum261_r17_orchestrator.py)
- [V2 预处理与原生 envelope](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/src/rl_curriculum/curriculum261_r4_preprocessing.py)
- [现有 bundle 路由](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/src/rl_curriculum/curriculum261_r17_routing.py)
- [policy-visible reference](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/src/rl_curriculum/curriculum261_r17_reference.py)
- [R4 scaled evaluator 与 pair 统计](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/src/rl_curriculum/curriculum261_r4_pairs.py)
- [R5 strict 条件](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/src/rl_curriculum/curriculum261_r5_pairs.py)
- [上轮完整交付报告](https://github.com/ceyirelehe47/freqai-rl-platform-audit/blob/3e377add6f6b3ba68c24a50ccfffe7534983ca9b/stage2_6_1/artifacts/repair17/development/c3_calibration_bridge_delivery/FINAL_REPORT.md)

## 关键差异防误用

1. 旧 raw bridge 完成 ≠ V2完整路径完成。
2. 旧小试D3默认值 ≠ 现有校准的R4继承值。
3. 新工程控制profile ≠ 新正式parameter pack；不伪造design资格。
4. V2对象`.bundle_hash` ≠ JSON键名；实际键是`hashes.preprocessor_bundle_hash`。
5. `verify()`可重算 ≠ 等于本run冻结值；路由必须验证实际对象。
6. engineering validation ≠ frozen holdout；其fit数据与eval数据仍须隔离。
7. 历史source_lock ≠ 自动跟随最新代码的全局锁；不回写旧证据。
8. 函数名含calibration，不代表运行它就只执行本轮授权的C1/C3子流程。

## 包内声明

此包仅生成任务书、执行入口说明、验收矩阵和来源导航；没有新生产代码、没有应用器、没有本轮业务执行结果。文件的SHA256SUMS只校验本任务书包的字节，不构成工程实现或统计验收证据。
