# 阶段 2.6.0e:Null 经济摩擦、功效证明与 Pack 完整性最终闭环

> **2.6.0d 独立审查发现的四组剩余问题在本目录全部修复。**
> ① Null margin 公式与冻结账本真实往返摩擦不一致(0.001999 vs
> 0.002/1.001 = 0.001998002);② power analysis 经验分布未中心化且
> required targets 只覆盖 Always Long;③ 正式执行器只检查
> `public_summary.targets_met`,从不重跑完整 power report;④ actual
> pack 只查 flags 集合、Oracle/Rule 降级为点估计、npb- 只哈希
> validator 文件。
>
> **本阶段只做修复闭环,未开始正式课程训练;不自动进入 2.6.1。**
> **Agent 自判 PASS;已通过独立验收 subagent 审查(ACCEPT);等待
> 独立审查确认。**

- 判定:**PASS**(report/route_c_stage2_6_0e_null_economic_power_pack_
  integrity.md;验收 subagent:ACCEPT,31/31 PASS 条件满足、22 项 FAIL
  条件无一成立、冻结合同与上游逐字节核对未改动)
- 测试:2.5 → 2.6.0e 全量回归 **1030 项全部通过,零失败零跳过零
  xfail**(artifacts/regression_test_summary.md);本阶段新增
  tests/route_c_stage2_6_0e 共 109 项
- 上游:Freqtrade 2026.7(`52bc96f`)clean,零修改;冻结六合同未变

## 本阶段实现(工作包 A-F)

| 项 | 实现 |
|---|---|
| A 摩擦合同 | 新单一来源 `null_friction.py`(null-friction-contract-v2):**retention = [(1-f)/(1+f)]×[(1-s)/(1+s)],margin = 0.002/1.001 = 0.001998001998...**(simple-return 单位,与 net_return 同尺度);price_tick 保守下界由**真实 LongFlatLedger/market_fill 执行**在预注册网格(665 可采纳组合 × 市场卖出/终端清算 = 1330 次真实往返)实证并进入 spec 验证(非注释);摩擦合同哈希 nfc- 入 spec;旧公式在数值/字符串/校验三层被明确区分 |
| A2 单一实现 | margin 推导不复制交易公式:round_trip_friction → null_friction(与账本/执行交叉验证 + 平价往返 parity);spec v2 绑定公式/单位/tick 语义/摩擦合同哈希 |
| B1 中心化 | `sample = resample(empirical − mean) + target_absolute_edge`;target 是真实绝对经济优势;逐场景记录经验中心/残差中心/target/超出量/模拟中心 |
| B2 场景 | 预注册 `POWER_SCENARIO_MANIFEST`(入 spec hash,npss-):valid_zero_edge / inside_half_tolerance / boundary_diagnostic / **violation_plus_1x_margin(=容差+1×margin)** / violation_plus_2x_margin;"1×margin 功效" = 超容差一个完整 margin 的违规优势 |
| B3 四块硬门 | always_long / oracle / rule_trend / high_turnover 全部进入 required targets(每 family × block × 场景);targets_met 不再只看 Always Long |
| B4 零方差 | 解析确定性分支(平移后常数序列;stochvol oracle 恒 flat),不标记 skipped;54 个 required 场景全覆盖,`skipped_required_scenarios = []` |
| B5 置信界 | Wilson score 双侧 95% 保守界(坏率上界/好率下界),不用 MC 点估计;MC=1600(由精度需求决定:HFT 容差 0 边界检验名义误判 ~2.5%,400 次的 Wilson 上界噪声越 5% 线);bootstrap 向量化,索引流与 paired_bootstrap_ci 逐位一致(parity 测试) |
| B6 cluster 校准 | 预注册阶梯 32/64/96/128 × 两层规则(升序):(a)全部功效硬目标;(b)该档 namespace 前缀上三族四块经济等价检验通过。**实测 32 档功效达标但前缀资格 INSUFFICIENT(sign/volstate long 块 CI 上界 +0.00324/+0.00269 > margin)→ 不可选;选定 64**;选定值入 spec hash |
| C 重跑验证 | 新 `null_power_reverification.py`:执行器在候选 checkpoint 加载前**从承诺绑定的完整报告 payload 确定性重跑完整 power analysis**,重算 npa- 对账、重派生 targets_met(与摘要逐项比对)、核验场景清单/MC 配置/置信方法/cluster 数/代码哈希;**public summary 不再是信任源**;可信缓存(键覆盖 spec/family/power code/generator/EvalConfig/timeframe/duration/MC/scenario;命中后验证内容哈希);重跑失败(材料不一致)同样 fail-closed 拒绝;14 类攻击全部 EXAM_INVALID |
| D1/D2 pair | 每 seed **恰好**一个 original + 一个 flip(Episode 计数,非 flags 集合);缺一/多一/同 flag/≥3 条/重复 spec 全拒;pair 参数除 flip 外全同(family/version/seed/timeframe/resolved duration/行数/实现指纹) |
| D3 镜像 | 对**实际被承诺绑定的每一对**验证:逐步 log return 反对称(1e-12)/绝对收益一致/pair 累计 drift 抵消(1e-9)/volume 逐位/hidden volatility-regime 逐位/时间戳一致/特征因果重算;预注册容差入报告哈希 |
| D4 nuisance | 生成器侧 `antithetic_flip` 不再进入 nuisance counter-hash(与 derive_seed 对称);实际 pack 内所有 pair 的 nuisance 槽位逐位一致;flip/pair id/base seed 不进 observation |
| D5 四块硬门(pack) | Oracle/Rule 恢复与 AlwaysLong/HFT 相同的**中心 ≤ tolerance 且单侧 CI 上界 ≤ tolerance**;实际 mock pack 以完整检验通过(最高 CI 上界 +0.00149 < margin),不依赖降级;11 类 antithetic 负例全拒 |
| D6 builder manifest | **null-pack-builder-manifest-v1**:npb- 绑定真实 builder(assemble_mock_hidden_pack/qualification_seeds/pack_construction_seeds/pack_order_seed/attempt 循环/匿名拒绝日志/validate_null_pack/参数规范/family 列表/pair 数量);签名禁止 candidate/checkpoint/model/policy(fail closed);改 builder 或 validator 任一 → npb- 变化;正式私有 builder 只公开 hash,评估环境对实际 builder 重算 |
| E 协议 | **sealed-exam-commitment-v5**(v1-v4 显式拒绝)/ **null-qualification-v4** / **null-qualification-spec-v2** / **null-power-analysis-v2** / **null-pack-validity-v2** / **null-pack-builder-manifest-v1** / **hidden-exam-cli-v6**;语义未变不升级(checkpoint-manifest-v3 / training-attestation-v1 / candidate-runtime-manifest-v1 / sealed-exam-context-v3);旧公式 spec、validator-only npb-、v1 power/pack 报告全部拒绝(artifact:legacy_v4_material_rejection.json) |
| F mock v6 | 摩擦合同 parity → Spec v2 → 64×16 三族资格(全 QUALIFIED)→ 中心化四块 power v2(选 64;54 场景全)→ mock pack(32 pair/族;逐对镜像+nuisance 逐位;四块硬门)→ builder manifest → issuer + 256-step PPO smoke + attestation → **v5 承诺 → 执行器重跑完整 power(npa- 对账)→ pack validity 现算对账 → 系统级沙箱 → G4/Null/反作弊 → smoke 正常 FAIL → 幂等重试 → --detailed 披露退休**;256-step PPO 仍仅用于 provenance/接口/沙箱/协议闭环 |

## 关键数值

- 正确 friction:0.001998001998...(0.002/1.001);旧公式值 0.001999 已废除
- qualification margin:= friction(simple-return 单位);不大于真实摩擦(tick=0 相等,tick>0 由 parity 实证为其下界)
- selected minimum cluster count:64(两层规则;32 档因前缀资格不充分被排除)
- required scenarios:54/54 完整;三族 family qualification 全 QUALIFIED
- actual pack:PACK_VALID;96 对 antithetic pair 全部镜像通过
- builder manifest hash:npb-397b55a9…;power report hash:npa-1cdf2a58…

## 关键证据(artifacts/,任务书清单逐名对齐)

| 文件 | 结论 |
|---|---|
| null_friction_contract_parity.json | 冻结账本公式 + 1330 次真实执行往返 parity 全过 |
| null_qualification_spec_v2.json | spec v2(公式/单位/tick/摩擦合同哈希/分块容差/场景清单/MC 配置/阶梯) |
| null_power_analysis_v2.json | 中心化四块功效 v2 完整报告(targets_met;Wilson 界) |
| power_centering_parity.json | 注入 target 后样本中心 == target;向量化 bootstrap 逐位一致 |
| power_required_scenario_coverage.json | 54 required 场景全覆盖;零方差走解析分支;无跳过 |
| power_cluster_count_selection.json | 阶梯 32/64/96/128 两层规则;选 64 |
| power_report_reverification_attack_matrix.json | 14 类攻击全部拒绝(摘要不是信任源) |
| actual_antithetic_pair_validation.json | 96 对逐对验证全过 |
| antithetic_pair_negative_matrix.json | 11 类负例全部 PACK_INVALID |
| pair_nuisance_identity_audit.json | nuisance 逐位一致;flip 不入 observation |
| pack_oracle_rule_equivalence.json | 四块中心+CI 上界双门全过 |
| null_pack_builder_manifest.json | npb- 绑定真实 builder |
| null_pack_validity_v2.json | 实际 pack 完整 validity 报告 |
| legacy_v4_material_rejection.json | v4 承诺/旧公式 spec/validator-only npb- 拒绝 |
| sealed_exam_tamper_matrix_v5.json | 结构层 + 值层篡改全拒 |
| mock_sealed_exam_v6_summary.json | 全链路 #1 FAIL/#2 幂等/#3 披露退休 |
| regression_test_summary.md | 2.5 → 2.6.0e 全量回归 1030/0/0/0 |
| upstream_integrity.txt | vendor clean @ 52bc96f;冻结六合同未变 |

## 已知限制

1. 阶梯 >64 档在 64-cluster 经验基座下不可评估前缀资格(需先扩展生成);
2. power 重验证缓存位于评估环境(仅加速;键与内容哈希双重校验);
3. 正式私有 builder manifest 由评估环境对实际 builder 重算(公开侧仅 hash);
4. parity 网格排除"价格低于一个 tick"的不可采纳组合(该配置下执行合同本身 fail-closed);
5. HFT 零优势场景 ~2.5% 名义误判率是容差 0 时单侧 97.5% 检验的边界固有率(MC=1600 使 Wilson 上界稳定低于 5%)。

不得提交:真实 issuer 私钥、正式隐藏 seed、正式私有生成器/builder 源码、
模型二进制、真实行情、数据库、API Key、代理认证、私人凭证。
