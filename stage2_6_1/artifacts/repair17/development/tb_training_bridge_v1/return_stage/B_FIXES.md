# B1–B4 返修说明(ChatGPT 终审 REVIEW.md 对账)

依据:`RouteC_TrainingBridge_Review_c85eee4e_Evidence.zip` 的 REVIEW.md
(NOT_CLOSED_ENGINEERING)。修复候选:C3 `611966b28bc0d2baeff396e8f42e91ddb1729e4e`。
全部组件反例零原生生成、零 optimizer、零 fit(账本未动:replay 2/2、
成功 12/12、smoke 2/8、512/2048 步)。

## B1 六类入口报告 ≠ 实际路由(修复)

- 新模块 `ppo262_entry_specs.py`:smoke/config_dev/probe/core/dev_eval/
  final 六入口的 `prepare_*_inputs()` = 官方 cmd_* **实际调用**的输入
  解析实现;`EntrySpec.build_bank/build_reference` = 真实 generator/
  评估消费边界(缺省即 `generate262_bank`/`build_261_policy_set` 本体,
  哨兵可注入)。
- `cmd_config_dev/cmd_probe/cmd_core/cmd_dev_eval/cmd_final_run/
  run_ppo262_smoke` 全部改为经 prepare 管线取参与坐标;
  `_locked_rung_params/_locked_reference_thresholds`(cli+smoke)上下文
  感知:profile 上下文 = 已验证 pack + `ppo_eng_bank_262e`;缺省 R2
  逐字节不变。
- `route_profile_inputs` v2:激活上下文 → 六个真实 prepare → 哨兵在
  generate262_bank/build_261_policy_set 边界**实测捕获** pack 参数 →
  退出上下文断言官方默认 → 缓存污染负对照。反例 route_report_no_
  consumers 语义消除(消费者调用计数 6/6)。

## B2 输入来源/缓存失配(修复)

- 3.1 装载交叉核验:`result.source_iteration == plan.source_iteration`;
  `exposure.iteration == plan.iteration`(可选 source 一致);
  `code_identity.producer` 必填(模块+哈希)。
- 3.2 `QualifiedInput.verify_integrity()` 消费边界重验:pack digest /
  authorization binding digest / bundle hash / Ct 共同语义(现场重算),
  在 generate_eng_bank、engineering_ppo_run、cold read、prepare 解析
  全部强制。反例 bank_cached_pack_mutation(改 `_pack` 为 999)现在
  真实生成前拒绝,recorder 零调用、账本零事件;副本修改保持无害。

## B3 冷读绑定(修复)
`cold_read_checkpoint` 在 PPO.load 前核验:plan/pack/bundle/profile/
**source_iteration** 五字段 + **authorization_binding_digest 重算** +
共同语义**现场重算** + **bank 绑定跨文件**(namespace/keys/数量/manifest
hash vs eng_bank_smoke/eng_ppo_smoke 原件)+ **训练预算钉死 profile
常量**(steps=256、seed=262501、updates=len(records))+ 冻结观察
binding_digest(保存时写入,冷读复算)。反例 cold_wrong_source_
iteration/cold_missing_authorization_binding/cold_wrong_bank_and_seed
全部在模型加载前拒绝。
旧 checkpoint(C2 产物)经**显式已核验迁移**支持:`…manifest.v2.json`
sidecar(逐字段保留 v1 + candidate_commit=e565298d;迁移时逐模块对
git blob 复算通过后写入;冷读重新复算;v1 原件零改写)。


## 复验发现的非阻塞项处置(C4)

- **P2(Cq/Ct 契约面未覆盖 generator/env 行为级身份)**:`_CONSUMER_CODE_MODULES` 扩展加入
  `curriculum261_pairs.py`、`curriculum261_c1/c2/c3.py`、
  `curriculum261_production_obs.py`、`../rl_platform/env.py`(相对路径)。新
  生成的 manifest/冷读/verify_integrity 均重算完整 18 模块哈希;v1 归档件走
  recorded-keys-only 迁移路径不受影响(blob 对拍仍绑 e565298d)。行为级篡改
  由 `test_p2_consumer_identity_covers_generator_and_env_modules` 固定。
- **P3(部署树测试文件 CRLF)**:同步脚本统一 `sed -i 's/\r$//'` 归一化。
## B4 配额(修复)

- `reserve_smoke` 于 learn 前预约(run_id);异常路径 `fail_smoke`
  终结(实际步数或保守全额);进程中断 = 未终结预约保守计入
  (sums 不释放)。隔离故障注入(learn 立即抛错,零真实训练):8 次
  失败计满后第 9 次在额度检查拒绝。
- bank attempt 实计:派生入口包装计数,失败/成功事件携带
  pair_attempts;候选数 = 计划 + 重试超出(不低估)。注入 5 次派生
  重试 → pair_attempts=5、候选 10。

## §6 补件:reviewer 原始脚本与输出

`return_stage/reviewer_originals/`(= 主 Agent 工作区 `tmp_reviewer_tb_v1`
**原样复制**,985K):probe1/2/3 脚本 + 运行 shell + reviewer 重放/
冷读原始输出(eng_run_reviewe、cold_read_orig、coldread_final_pkg)+
账本前值 ledger_before.jsonl。本轮新 reviewer 的独立脚本/输出将由其
写入自己的隔离目录并原样入包。

## 运行证据(C3,零配额)

`eng_training_bridge_v1/c3_verification/`:input-lock rc=0、route-check
rc=0(真实管线+哨兵,pass=true)、cold-read rc=0(全绑定 + 迁移路径,
动作逐位一致)、G01 formal 拒绝 rc=2。
