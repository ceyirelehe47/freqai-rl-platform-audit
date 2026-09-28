# 必需验收矩阵结论 — RouteC_QualifiedInput_TrainingBridge_v1

候选 C:`e565298dad8063df70775dfdd47e3bf682f29926`。
原路径均相对仓库根;`TB=stage2_6_1/artifacts/repair17/development/tb_training_bridge_v1`,
`ENG=stage2_6_2/artifacts/eng_training_bridge_v1`。

| ID | 结论 | 检查方法 | 直接原件 |
|---|---|---|---|
| B01 | PASS | git branch/HEAD/工作树核对;R25 已闭合(5ac420a1);变更限定桥接直接依赖 | git_receipts/(push/ls-remote);候选 C diffstat 41 files 全在 stage2_6_2 |
| I01 | PASS | 工程夹具走完整公共正路径(38 项测试 + CLI eng-input-lock rc=0);正式无资格/无授权零生成零更新拒绝 | ENG/eng_input_lock_v1.json;test_ppo262e_qualified_input.py::test_i01* |
| I02 | PASS | 缺件/非 PASS/错 plan/错 exposure/错 pack/错 bundle/自授权/R2 冒充全部拒(测试逐项) | 同上测试 test_i02_*;G01 组 |
| I03 | PASS | 校验后替换 pack => 新装载拒、内存快照稳定;同字节移位不误拒 | test_i03_* |
| I04 | PASS | R2 默认/digest/黄金派生不变(钉死断言);新 profile 实读新输入(v2≠R2) | test_i04_* |
| K01 | PASS | 两套 pack(v1=R2 拷贝/v2=扰动)在真实 generator 边界被观察到选定值(中止型 recorder,零生成);真实运行 6 条边界记录 + episode spec.params 产物对拍 | test_k01_*;ENG/eng_bank_smoke.json generator_boundary_params |
| K02 | PASS | staged/mixed 同多重集不同序;A/B 身份;reset 隔离;bank 边界;标签只进 info 不进 obs | test_k02_* |
| V01 | PASS | 复用 V2 实现(envelope 重载逐位一致;eval 改变不 refit;同 scaler 不同 fit manifest => bundle 不同且装载拒) | test_v01_* |
| V02 | PASS | SB3 实见 9 维 V2 outer space(构造期+reset);超界有限值不 clip;缺列按合同拒 | test_v02_*;ENG/eng_ppo_smoke.json checks |
| V03 | PASS | 相同 OHLCV+动作,缩放与否 reward/fee/仓位逐步一致(价格列 raw) | test_v03_ledger_invariant_under_scaling |
| N01 | PASS | ppo_eng_bank_262e 进隔离枚举;fit 标签 namespace 与全部 seed namespace 不相交;植入同 seed 探测无重合;262 黄金种子钉死 | test_n01_*;test_i04_262_seed_golden_unchanged |
| M01 | PASS | manifest 绑定输入锁/pack/bundle/bank/seed/profile/代码身份;错输入冷读拒;模型字节篡改拒 | test_m01_*;ENG/eng_cold_read.json |
| M02 | PASS | 六类入口(smoke/config-dev/probe/core/dev-eval/final)新 profile 路由同源(eng-route-check);官方默认仍 R2 | ENG/eng_route_check.json;test_m02_* |
| E01 | PASS | 6 成功 episodes 实际生成+特征+参数来源+身份;first-pass 无重试(明细=零重试,账本候选=成功=6);配额未超 | ENG/eng_bank_smoke.json;ppo262e_quota_ledger.jsonl |
| E02 | PASS | 真实 256 步(env 计数器)+1 次真实 optimizer 更新+有限 loss+参数摘要变化+checkpoint;非 mock | ENG/eng_ppo_smoke.json;eng_ppo_smoke_256.zip(+manifest) |
| E03 | PASS | 新进程冷读:绑定核对+冻结观察对拍(动作逐位相等,概率残差 0.0<=先验 1e-9);无重训练/refit | ENG/eng_cold_read.json;eng_frozen_probe.json |
| G01 | PASS | formal scope 请求 rc=2(空 admission 注册表;工程授权 scope 不匹配);工程字节入 R2 链 => digest 复算抛错;未验证快照零生成 | ENG/eng_input_lock_formal_reject.json;test_g01_* |
| R01 | PASS | 261 R17-first 全收集(collection/JUnit/source map/auditor/lifecycle)于 C2 树 + 262 全套 JUnit;首轮 v1 因陈旧镜像 surface mismatch rc=3(测试 2534+7 全过)如实保留,C2 修复后 v2 全绿;无新 skip/xfail/缩集合 | TB/full_regression_v2/;TB/full_regression_v1/(失败原件);TB/regression_262_v2/(204 passed);regression_262_v1 |
| P01 | PASS | R25 三树/plan/claim/终态未触碰(git diff 限定);配额可重算(账本 JSONL);无正式研究/教学/交易 | git diff 候选 C 范围;ENG/ppo262e_quota_ledger.jsonl |
| D01 | PASS | README 已实现/未实现/资格与教学状态分开;不重复旧 K=11 待办 | stage2_6_2/README.md 工程桥接章节 |
| A01 | 见 REVIEWER_CONTENT_REPORT | 独立 reviewer(glm-5.3-flash)全矩阵核验 | REVIEWER_CONTENT_REPORT.md(包内) |
| A02 | 见 REVIEWER_FINAL_RECEIPT | 最终 ZIP 冷读+内部清单+模型重载证据+git 回执对拍 | 包外 REVIEWER_FINAL_RECEIPT.md |

reviewer 最低独立反例集落点:1=>G01(formal 注册表+scope);
2=>K01(边界+产物对拍);3=>V01(fit manifest => bundle);4=>V02
(SB3 实见空间+不 clip);5=>I03(替换/缓存);6=>M01(错绑冷读拒);
7=>N01(隔离枚举+同 seed 探测);8=>E02(env 计数器+update 记录+
参数摘要,非报告自填)。
