# REVIEWER_CONTENT_REPORT — RouteC_QualifiedInput_TrainingBridge_v1

- Reviewer:OMP task agent `reviewer`(独立子代理,未参与实现)
- 配置模型:`zhipu-coding-plan/glm-5.3-flash`(`C:/Users/15027/.omp/agent/config.yml`
  `task.agentModelOverrides.reviewer`,本审查时实读核验);运行时后端模型元数据:
  **未提供**(平台工具不暴露该字段,按原要求如实记录,不作阻塞)
- 审查时间:2026-09-29 06:35–07:50 (+08:00);审查期间未修改任何被审产物/候选
- 被审对象(固定后才开工):
  - 候选 C `803fe66e0cffd05a52cb13106be6dc2c9ab333f8` → C2 `e565298dad8063df70775dfdd47e3bf682f29926`
  - 证据 HEAD `9c848fbb2d3decf027b7903c8013b5d363b854e6`
  - 分支 `route-c-stage2-6-1-repair17`;远端 ls-remote 实测 = `9c848fbb…`(与本地 HEAD、
    `git_receipts/push_receipt.txt` 一致;push 回执含 "Everything up-to-date" + ls-remote 双段)
- 验收依据:REVIEWER_PROMPT.md、NEXT_GOAL.md、SCOPE_AND_BUDGET.md、
  ACCEPTANCE_MATRIX.md、RETURN_REQUIREMENTS.md、START_GOAL.txt、context/*、
  SUPPLEMENT_RemoveRoundTimeLimit_v1.txt(sha256 dbb4784e…,时间规则覆盖已并入验收)

## 0. 判定

**内容验收:PASS**(全部必需 ID B01..A02 见下;A02 属封包后第二阶段,前置条件=本内容 PASS)。
 qualification=NOT_RUN、teaching_experiment=NOT_RUN、formal 恒拒为预设真实状态,非缺件。

## 1. 逐 ID 核验结论

版本口径:src/tests 认 C2 `e565298d`(部署树 11 个桥接文件与 C2 逐字节一致,CR 规范化后
sha256 对拍通过,含 `stage2_6_1/src/rl_curriculum/ppo262_input_lock.py` 镜像);回归原件
认 full_regression_v2(绑定 commit_a=e565298d)。TB=stage2_6_1/artifacts/repair17/development/
tb_training_bridge_v1,ENG=stage2_6_2/artifacts/eng_training_bridge_v1。

| ID | 结论 | 实际方法(含 reviewer 独立部分) | 直接原件 |
|---|---|---|---|
| B01 | PASS | git ls-remote=本地 HEAD=回执;5ac420a1 为祖先(R25 已闭合);候选 C diff 41 文件全部位于 stage2_6_2;在飞未提交变更(T/D/M 11 项 + 62 untracked)保留未动 | git_receipts/push_receipt.txt;`git diff --name-status 5ac420a1..803fe66e` |
| I01 | PASS | **独立**:以候选代码自建 v1/v2 夹具走完整公共正路径(20/20 断言);**独立复算**已提交 plan/pack/授权三摘要(自实现 canonical+sha256,与工件一致);committed 夹具重建逐字节一致 | ENG/eng_input_lock_v1.json;tmp_reviewer_tb_v1 probe A1-A3,B1-B3 |
| I02 | PASS | **独立反例**:非 PASS verdict、自洽重算摘要的 plan 伪造(result 不再绑定)、exposure 非 terminal、缺授权、自授权、pack 换包、envelope 篡改、R2 目录冒充 —— 全部结构化拒绝 | 同上 probe C1-C5;test_i02_*(38 项实测 38 passed) |
| I03 | PASS | **独立反例**:同字节移位可装载(digest 定身份);校验后换 pack => 新装载拒 + 内存快照不受影响;envelope 换包拒 | probe C8-C9;test_i03_* |
| I04 | PASS | **独立**:R2 锁 digest=`qp-8f64a1b5…` 实测未变;官方缺省 rung 参数仍出自 R2;262 黄金种子 2721149688598171913 钉死;新 profile 实读新输入(v2≠R2) | probe G1-G4;test_i04_* |
| K01 | PASS | **独立**:v2 pack(45.0/50.0/0.20)在**真实 generator 边界**(param_recorder 于 spec.generator.generate 前触发,中止零生成)三族逐一观察到选定值;**复验重放**边界记录与已提交原件逐位一致;两套合法 pack 对照成立 | probe I1-I3;ENG/eng_bank_smoke.json;test_k01_* |
| K02 | PASS | staged=C1→C2→C3、A/B 身份、同多重集 mixed 序、episode reset 不串扰、预算边界、标签只进 info 不进 obs(38 项测试含盖) | test_k02_* |
| V01 | PASS | **独立**:envelope 重载 transform 逐位一致;eval 数据改变不 refit 不改身份;**同 scaler 数值+不同 fit manifest => bundle_hash 不同**且错绑装载拒 | probe D1-D4;test_v01_* |
| V02 | PASS | **独立**:SB3 model.observation_space 与 env 的 V2 outer space 逐元素相等(9 维;feature ±inf;position [0,1]);5e6 价格尺度超界有限值不 clip(|obs|max>10);NaN 观察按合同 RuntimeError 拒;无预处理旧路径空间不变 | probe E1-E5;test_v02_*;ENG/eng_ppo_smoke.json checks |
| V03 | PASS | **独立**:raw vs V2 缩放双环境同动作 285 步,逐点 reward/fee_paid/new_target_position/终止一致,终态 cash/position 一致(价格列 raw,无课程费率) | probe F1;test_v03_* |
| N01 | PASS | **独立**:植入式同 seed 探测 —— eng namespace 4320 派生 vs 全部 11 个 262 + 806 个 261 seed namespace × 4320 坐标(3,529,440 派生)零交集;fit 标签 namespace 不在任何 seed 面;隔离枚举显式含 ppo_eng_bank_262e | probe H1-H3;test_n01_* |
| M01 | PASS | **独立**:自建未训练 checkpoint(零 learn)+ manifest 全绑定字段核验;错输入(v2)冷读在预测前拒(manifest digest);模型字节 +b"\x00tamper" 拒 | probe J1-J3;test_m01_*;ENG/eng_ppo_smoke_256.manifest.json |
| M02 | PASS | eng-route-check(v2)六类入口全部 `rung_params_source=qualified_input.pack` 且 pack_differs_from_r2=true;**代码走查**:eng-run/eng-cold-read 全链只消费 QualifiedInput 快照,`_locked_*` 仅路由对照引用;官方缺省路径不变 | ENG/eng_route_check.json;test_m02_* |
| E01 | PASS | **复验重放(消耗第 2/2 次)**:6 成功 episodes、bank manifest=`1c60269e…`、边界参数、episode keys 与已提交原件**逐位一致**;first-pass 零重试;配额未超 | ENG/eng_bank_smoke.json;ledger(见 §3) |
| E02 | PASS | **复验重放**:env 审计 steps_taken=256;1 次 optimizer 更新(DiagnosedPPO train() 真实记录,机制为既有 `diag_update_records`);loss 有限;参数摘要 `e262pp-81be0a93…`→`e262pp-db2cfb5b…` 与原件一致;非报告自填(n_steps=256 事前强校验) | 我的重放 eng_ppo_smoke.json(tmp_reviewer_tb_v1/eng_run_reviewe/);ENG/eng_ppo_smoke.json |
| E03 | PASS | **独立双份**:新进程冷读我自己的新 checkpoint(pass,动作逐位一致,残差 0.0);新进程冷读**已提交原件** checkpoint(sha `11bc9a99…`,pass,残差 0.0 ≤ 先验 1e-9);无重训练/refit 字段如实 | 我的 cold_read_orig/;ENG/eng_cold_read.json;eng_frozen_probe.json(32×9 obs+概率,action∈{0,1}) |
| G01 | PASS | committed formal 拒绝件(rc=2,理由=scope 不匹配+空注册表,非格式/陈旧 SHA);**独立**:重算全部摘要并伪造 formal 授权仍被空 FORMAL_ADMISSION_REGISTRY 拒;工程字节入 R2 锁目录 => digest 复算抛错;未验证快照零生成零事件 | ENG/eng_input_lock_formal_reject.json;probe C6-C7;test_g01_* |
| R01 | PASS | full_regression_v2:ok=true,commit_a_sha=e565298d,**315 成员 import surface 与候选字节逐一相符**(我逐一重算);JUnit 2541=2534 passed+7 skipped,0 fail 0 err;auditor verdict=pass 零 violations(collection+execution);lifecycle JSONL 44/45 行;262 JUnit 204 passed(=基线 166+新增 38,集合未缩);7 skips 全为 R12-R16 历史 id;首轮失败原件 full_regression_v1(rc=3 陈旧镜像 surface mismatch,测试本体 2541 全过)如实保留;ALL_RC 261_rc=0 262_rc=0 | TB/full_regression_v2/*;TB/full_regression_v1/*;TB/regression_262_v1|v2/* |
| P01 | PASS | R25 冻结树(plan df7d04de/smoke 3ef2fc55/study 96df8ff9)在 5ac420a1 与 9c848fbb 同 tree hash(我实测);候选 diff 不含旧 plan/claim/终态;无正式研究/教学/交易;配额账本可重算(见 §3);R25_BASELINE 登记独立复核:`git diff 92818db2..5ac420a1 -- …api.py` 恰 +13/-1 dev-namespace 白名单,5ac420a1 blob=ec020337… 与登记一致(非守卫弱化) | git ls-tree;PROTECTION.md;ledger |
| D01 | PASS | README 末章:已实现消费面/未实现 Level A/B/qualification=NOT_RUN/engineering smoke 与科学学习分离/无 K=11 重做 —— 与实际状态一致 | stage2_6_2/README.md |
| A01 | PASS(本文) | 本审查即 A01 执行:真实独立 task→reviewer 调用;原要求完整传入并逐条核验;配置证据=config.yml reviewer override;运行时后端模型元数据**未提供**(平台不暴露,如实记录);无主 Agent 代签 | 本文件;config.yml(2026-09-29 实读) |
| A02 | PENDING(第二阶段) | 按 REVIEWER_PROMPT 时序,最终 ZIP 冷读在内容 PASS 之后执行;当前 return_stage 仅 assemble_return.py,**RETURN ZIP 尚未封包**,不构成缺件;封包后须签包外 REVIEWER_FINAL_RECEIPT.md(绑定最终 SHA-256/大小/成员数/候选与证据 HEAD/本报告身份) | return_stage/assemble_return.py(待执行) |

## 2. 八类最低反例的独立验证(均与正确正例配对)

| # | 反例 | reviewer 独立验证 | 配对正例 |
|---|---|---|---|
| 1 | 工程 PASS 夹具移正式目录+重算摘要,无正式授权 | C6:重算 plan digest/pack digest/binding digest 并伪造 formal 授权 JSON+admission_anchor => 空注册表拒(problems 含 "admission");C7:scope=formal 拒 | B1 同夹具 engineering scope 装载通过;committed G01 拒绝件 rc=2 |
| 2 | 新参数包过锁,bank 偷用旧 R2 参数 | I1/I2:v2 pack(45.0/50.0/0.20)在真实 generator 边界三族逐一观察到选定值(非 42.0 等 R2 值);eng-run 产物 spec.params 对拍在代码内强制 | K01 v1 边界值=42.0=R2 拷贝预期;我的重放边界记录与原件逐位一致 |
| 3 | 同 scaler 数值、不同 fit 来源清单 | D3:伪造 entries => parameter_state_hash 相同而 bundle_hash 不同;D4:错绑 envelope 换入目录 => 装载拒("bundle") | D1:原 envelope 重载逐位一致、bundle_hash 稳定 |
| 4 | env 文档写 V2,SB3 实拿旧 Box / reset 后 clip | E1/E2:SB3 model.observation_space 与 V2 outer space 逐元素相等(±inf/[0,1]);E3:5e6 尺度 |obs|>10 不 clip;E4:旧缺省路径仍为有界旧空间(证明分支真实存在) | E02 checks.sb3_obs_space_is_v2=true(env 计数器同源) |
| 5 | 验证后替换 bundle/pack、污染缓存 | C9:装载后磁盘换 pack => 重装拒 + 内存快照不变;D4:envelope 换包拒;C2:自洽摘要伪造拒 | C8:同字节合法移位(digest 定身份)装载通过 |
| 6 | 元数据指对、checkpoint 实绑另一输入 | J2:v2 输入冷读 v1 绑定 checkpoint => 预测前拒("manifest …digest");J3:字节篡改拒(非仅存在性) | J1/A5:正确绑定冷读 pass;committed 模型 sha=manifest 绑定 |
| 7 | 新 namespace 植入同 seed | H1:eng 4320 派生 vs 11×262+806×261 namespace 全坐标 3,529,440 派生零交集(隔离面=实际派生整数) | H2:eng namespace 在 262 隔离枚举内;G3:旧黄金种子不变 |
| 8 | 报告 256 步、实际 rollout 取整/无更新 | 我的重放:env.steps_taken=256(环境计数器)、num_timesteps 语义 env_step=256、更新记录=1(真实 train() 钩子)、参数前后摘要变化;config 强制 n_steps=256 | E02 committed 记录与我的重放逐位一致(update record 相等) |

核验器拒绝原因均对应目标分支(scope 不匹配 / 注册表为空 / digest 绑定不一致 /
manifest 绑定不一致 / 非有限值),非无条件拒绝、格式错误或陈旧 SHA。

## 3. reviewer 独立运行清单与配额消耗(共享账本已更新)

环境:WSL CryptoRL-Ubuntu-24.04,deploy /home/cryptorl/projects/crypto_rl,
Python 3.11.16 / pytest 9.1.1 / sb3 2.9.0 / torch 2.13.0+cu130,vendor pin 52bc96f4…;
隔离目录 `/mnt/f/trading/tmp_reviewer_tb_v1/`(脚本+输出;未改被审产物)。

| 运行 | 结果 | 配额影响 |
|---|---|---|
| 部署树↔C2 同步对拍(11 文件) | 全 OK | 无 |
| 38 项桥接单测 | 38 passed(16.7s) | 无(测试零生成零 optimizer;共享账本零追加实测) |
| probe#1 输入锁静态+反例 | 20/20 PASS | 无 |
| probe#2 V01/V02/V03/I04/N01 | 17/17 PASS | 无 |
| probe#3 K01 边界中止+M01 冷读反例 | 6/6 PASS | 无(中止发生在真实生成前;事件落我隔离账本,共享账本零追加实测) |
| **eng-run 复验重放**(E01+E02,committed v1 夹具,同参数同坐标) | pass=true;256 步/1 更新/参数变化;语义面与原件逐位一致 | **bank 重放 2/2(已用尽)**;成功 12/12;候选 12/60;smoke 2/8;512/2048 步 |
| eng-cold-read(我的模型) | pass,残差 0.0 | 无(纯前向) |
| eng-cold-read(committed 原件,新进程) | pass,残差 0.0 | 无(纯前向) |

共享账本 `ENG/ppo262e_quota_ledger.jsonl` 本次净增 3 行(2026-09-28T23:40:48Z/23:40:48Z/
23:40:55Z):replay#2、bank_episode_success+6、ppo_smoke#2(256 步,模型
7b713fb0…)。重放额度已用尽(2/2);optimizer smoke 余 6 次/1536 步。审查前快照
(3 行,sha256 f7d7034e…)存 tmp_reviewer_tb_v1/ledger_before.jsonl。
模型 zip 跨运行字节不同属预期(zip 内 system_info 含时间戳);每次保存的 manifest
绑定各自的模型字节,冷读对拍以 sha256+冻结观察为准。

## 4. 补充指令(时间规则)核验

- 全局 AGENTS.md(2026-09-29 05:15 备份 `.bak_20260929_remove_round_time_limit`):
  实测 diff 恰为第 48 行插入一段"默认无单轮总时长上限"规则,措辞与补充指令 §5
  要求一致,无其他改动,未触碰 reviewer 配置/工具权限;`global_agents_diff.txt` 与实测一致。
- SUMMARY.md 已注明取消 8h 上限、保留运行配额与实际消耗;未把补充生效时间倒填旧记录。

## 5. 边界与如实声明

- qualification=NOT_RUN;teaching_experiment=NOT_RUN;formal 恒拒(空注册表)为预期。
- 工程夹具 PASS=结构自洽性,不是课程资格;E01 数值不进入任何资格判断。
- 未重跑 261/262 全量重型回归(按 REVIEWER_PROMPT 以 C2 树 ok=true 原件为准);
  未重复 R25 旧反例;未审计历史轮次。
- 运行时后端模型元数据未提供;本审查由配置为 glm-5.3-flash 的独立 reviewer agent 执行。
- A02 待封包后第二阶段冷读;若封包字节与候选不一致,本报告结论不自动延伸至新字节。

## 6. 最终判定

**PASS** —— 全部必需 ID 内容通过;八类最低反例独立验证成立;配额与保护条款合规。
下一步:主 Agent 依 RETURN_REQUIREMENTS 封包(内容 PASS 前提已满足),reviewer
另做最终 ZIP 冷读并签包外 REVIEWER_FINAL_RECEIPT.md。
