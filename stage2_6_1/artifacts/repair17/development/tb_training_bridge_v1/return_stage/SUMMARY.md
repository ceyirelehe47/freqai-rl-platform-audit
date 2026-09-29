# SUMMARY — RouteC_QualifiedInput_TrainingBridge_v1

任务:新版资格输入到训练的最小工程桥接(消费侧纵向切片)。
本包执行补充指令 `RouteC_RemoveRoundTimeLimit_Supplement_v1`(取消 8
小时单轮总时长上限;全部运行配额、独立验收与交付要求保持原样)。

## 1. 结论总览

- **工程接入结论**:已接通。新版资格输入身份(plan/digest/PASS result/
  one-shot exposure/parameter pack/冻结 V2 bundle/Cq-Ct 共同执行语义/
  目录外授权锚)→ 统一输入锁 → 锁定 pack 参数驱动的原生 bank → V2
  outer space 训练环境 → 恰好 256 环境步真实 PPO optimizer 更新 →
  全绑定 checkpoint → 新进程冷读对拍,全部在工程沙箱用真实公共组件走通。
- **256 步参数更新是否实际发生**:是。`eng_ppo_smoke.json`:
  `env_steps_exactly_256=true`(来自环境实际计数器),1 次 optimizer
  update(DiagnosedPPO train() 内捕获,绑定 env_step<=256),losses
  有限,参数摘要前后不同(`e262pp-81be0a93…` → `e262pp-db2cfb5b…`),
  模型 `eng_ppo_smoke_256.zip`(sha256 `11bc9a99…`)。
- **真实资格状态**:NOT_RUN。工程夹具的 PASS 是结构自洽性(绑定一致),
  不是课程资格判定;qualification=NOT_RUN。
- **正式研究/教学运行状态**:NOT_RUN。formal scope 恒拒(空
  FORMAL_ADMISSION_REGISTRY);official s262_r0 FAIL 结论不变;
  正式 Level A/B 入口未实现(预设范围外)。
- **代码候选(最终 C2)**:`e565298dad8063df70775dfdd47e3bf682f29926`
  (C `803fe66e…` + 陈旧镜像同步:`stage2_6_1/src/rl_curriculum/
  ppo262_input_lock.py` 属 r21_sync import surface,R11 时代副本未随
  候选更新导致 v3 面校验 deploy_mismatch——测试本体 2534+7 全过,
  首轮 rc=3 原件保留 full_regression_v1;C2 镜像与候选字节一致,
  315 成员对拍后重跑 full_regression_v2);证据 HEAD:见 git_receipts。
- **时间限制**:按补充指令取消 8h 上限;本轮实际耗时与配额消耗见 §5。

## 1a. 返修轮(ChatGPT 终审 NOT_CLOSED → B1-B4 修复 → C4)

- **终审输入**:`RouteC_TrainingBridge_Review_c85eee4e_Evidence.zip`
  (REVIEW.md:阻塞 B1 路由/B2 来源与缓存/B3 冷读绑定/B4 配额异常计数
  + §6 reviewer 原件补件;16 受控反例)。逐项对账见 `B_FIXES.md`。
- **修复候选 C3** `611966b2`:B1 六入口共享 prepare 管线
  (`ppo262_entry_specs.py`,官方 cmd 实调点+哨兵消费边界);B2.1 装载
  交叉核验(source_iteration/exposure/producer)+N01 fit namespace
  隔离;B2.2 `verify_integrity` 消费边界重验;B3 冷读全绑定(五字段+
  授权重算+共同语义现场重算+bank/训练预算跨文件+冻结观察 binding_
  digest;v1 归档件走显式已核验迁移 sidecar);B4 配额预约+失败保守
  计数+中断不释放+attempt 实计;§6 `reviewer_originals/`(上轮原件
  原样复制,44 文件逐字节一致)。
- **复验**:`REVIEWER_CONTENT_REPORT_V2.md`(独立 glm-5.3-flash
  reviewer,零配额):B1-B4 全部 PASS,16 反例 9 翻正/7 控制保持,八类
  最低反例全过,矩阵 22 项复核通过。
- **C4** `dec94b85`(P2 闭合):generator/env 行为级身份进
  `_CONSUMER_CODE_MODULES`(pairs/c1/c2/c3/production_obs/../rl_platform/
  env.py,18 模块);迁移验证多根解析,v1 归档件不受影响;262 套件
  225 passed;`c4_verification/` 零配额四连(lock rc0/route rc0/
  formal-reject rc2/cold-read rc0)。绑定 C4 的 261 全收集见
  `full_regression_v4`。
- **C5** `7c5fcc4f`(reviewer delta FAIL→修复→PASS):env 模块迁移解析
  改 stage2_6_0* 家族展开(真归档根)+`_repo_root()` 公共解析;G2 未篡改
  对照入测试;262 套件 225 passed;绑定 C5 的 261 全收集见
  `full_regression_v5`;reviewer C5 delta PASS(6/6,零配额)。
- 返修全程零原生生成、零 fit、零新增 smoke(账本 replay 2/2、成功
  12/12、smoke 2/8、512/2048 步不变)。

## 2. 变更面(候选 C)

新增:`ppo262_qualified_input.py`(统一输入锁/授权锚/formal 注册表
防线)、`ppo262_eng_fixture.py`(确定性合成 fit 夹具 + 两套合法工程
pack)、`ppo262_eng_profile.py`(配额账本/快照驱动 bank/精确 256 步
训练/绑定 manifest/冷读/路由检查)。
小改(增量、缺省行为不变):`ppo262_env.py`(可选冻结 V2
preprocessor,构造期与 reset 都走 V2 outer space;价格列 raw 保账本
语义)、`ppo262_banks.py`(param_recorder 观察钩子)、
`ppo262_namespaces.py`(`ppo_eng_bank_262e` 工程namespace,隔离枚举
自动覆盖)、`ppo262_cli.py`(eng-* 显式命令族)、
`ppo262_input_lock.py`(R25_BASELINE 登记,见 §6)。
测试:`test_ppo262e_qualified_input.py` + `test_ppo262e_env_bank.py`
共 38 项(零原生生成、零 optimizer)。

## 3. 工程验证证据

| 面 | 原件(相对仓库根) |
|---|---|
| 工程资格输入夹具 v1/v2 | `stage2_6_2/artifacts/eng_training_bridge_v1/qualified_input_*/` |
| 授权锚(目录外) | 同上 `eng_authorization_*.json` |
| 输入锁正/负例(含 G01 formal 拒) | 同上 `eng_input_lock_v1.json`、`eng_input_lock_formal_reject.json`(rc=2) |
| 路由检查(六类入口) | 同上 `eng_route_check.json` |
| E01 原生 bank | 同上 `eng_bank_smoke.json`(6 eps/6 边界参数记录/spec.params 产物对拍) |
| E02 256 步 smoke | 同上 `eng_ppo_smoke.json`、`eng_ppo_smoke_256.zip`、`eng_ppo_smoke_256.manifest.json` |
| E03 冷读 | 同上 `eng_cold_read.json`(动作逐位一致,概率残差 0.0,atol 先验 1e-9)、`eng_frozen_probe.json` |
| 配额账本 | 同上 `ppo262e_quota_ledger.jsonl` |
| 全部 rc | 同上 `eng_run_rcs.txt` |
| runner | `stage2_6_2/runner/eng_training_bridge_v1.sh`(部署树根同步) |

## 4. 回归(候选 C 803fe66e)

- 261 R17-first 全收集回归(collection/JUnit/source map/auditor/
  lifecycle):`stage2_6_1/artifacts/repair17/development/
  tb_training_bridge_v1/full_regression_v1/`(结果见 MATRIX R01)。
- 262 全套 JUnit:`…/tb_training_bridge_v1/regression_262_v1/`
  (204 passed;详见 junit.xml)。
- 数量由候选树实际收集决定;无新增 skip/xfail、无集合缩减、无守卫弱化。

## 5. 运行配额(实际消耗)

- 原生 bank 固定数据集重放:1/2(主 Agent;reviewer 复验可用第 2 次)。
- 成功 episodes:6/12;候选 episodes:6/60(全部 first-pass,无失败重试)。
- 新增 optimizer smoke:1/8 次,256/2048 环境步(单次恰 256,rc 见账本)。
- 无正式生成/资格/exposure 消费;无研究/教学/交易;原有仓库回归按既定
  工程预算运行,未借道塞入新训练。

## 6. 预存问题修复(如实说明)

262 套件在本轮之前已存在 3 项 FAIL(input-lock 面):根因 =
`curriculum261_api.py` 在 R17 登记锚之后至 R25 收口之间的**已提交**
演进(R25 dev namespaces,commit 5849accc)未同步登记到 262 侧
`REGISTERED_261_CODE_CHANGES`(R25 轮未跑 262 套件,缺口未暴露)。
修复 = 按既有迭代登记机制新增 `R25_BASELINE_REGISTERED_CODE_CHANGES`
(登记当前树实际哈希 `ec020337…`;diff 内容仅为 R25 dev namespace
白名单追加 +13/-1;黄金 seed 向量不变;再漂移仍 fail)。非本轮引入、
非守卫弱化,登记项可经 git 历史(92818db2..5ac420a1)独立复核。

## 7. 未实现/未运行(边界)

正式 Level A/B 生成入口、正式资格链、真实资格、正式教学/研究实验、
config-dev 选参、probe/core/final:均未实现或未运行。工程模型一律
ENGINEERING_ONLY。待 ChatGPT 独立终验;本包不代签 CLOSED PASS。

## 8. 全局 AGENTS.md 时间规则更新(补充指令 §5)

- 实际生效文件:`C:\Users\15027\.omp\agent\AGENTS.md`;
- 备份:`AGENTS.md.bak_20260929_remove_round_time_limit`;
- 差异:仅在"预算与停止"节插入一段默认无单轮总时长上限规则
  (diff 见 RETURN 内 global_agents_diff.txt);其余规则/ reviewer
  配置/工具权限未动。
