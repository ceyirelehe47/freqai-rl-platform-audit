# SUMMARY — formal_freeze_binding_v1(RouteC_FormalFreeze_ApprovalBinding_v1)

状态: **FREEZE_READY_PENDING_USER_APPROVAL**(工程冻结/绑定面全部
就绪;等待用户选择 A1/A2 与 B 批准)。真实 Level A / Level B /
正式教学: **NOT_RUN**;正式许可签发/消费 0;生产 exposure 0。

## 1. 基线与 Commit A(实读)

- 基线: R4 CLOSED PASS 候选 `04d1020800794df35bd1618f9b3ffb0d21d63adf`
  + 证据树 `c3cba8b20ebd1633be05c9858c9db7ebeca7e6e9`(开工时
  本地=远端 HEAD,0/0 分叉;两者均为 Commit A 祖先)。
- **Commit A = `de81aba2b3cdcc2c0febe2b3c439027496ab9d05`**
  (tree `851c883b2b017ccdfa748b4f8d718a3c61d3f1e2`,
  parent `c3cba8b2`,author/commit 2026-10-04T02:47:06+08:00,
  已推送,origin/branch 已回读同一 SHA)。
- 冻结面: 相对 04d10208 仅 `stage2_6_1/artifacts/` 下 20 个文件
  (6 个本轮 Commit A 新增 + 14 个 R4 证据件);src/tests/runner
  diff = 0 文件。无自引用(Commit A 内容不含自身 SHA;SHA 提交后
  读取)。链外 provenance-lock 文件 mtime(02:45:05 +0800)早于
  Commit A author/commit date(2026-10-04T02:47:06+08:00);
  本地时钟口径,文件内容不含时间戳字段。
- provenance digest:
  `r17gtrec-3112e5deb863a810392bbaae0e4e21d9f7017c97d0fd172d6e66eb6551bf4e9d`
  (隔离目录 provenance-verify 复算一致,rc=0)。

## 2. 部署对拍(非激活)

- 部署树 `/home/cryptorl/projects/crypto_rl`(无 .git;解释器
  `/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python` 3.11.16)
  vs Commit A:src 325 / tests 172 / runner 124 文件 CR 规范化
  sha256 逐成员相等,漂移 0,CRLF 成员 0;补齐缺失成员
  `regression_selection_rules.md`(自 Commit A blob,LF)。
  部署侧 67 个 deploy-only src 模块文件(generator_api 等,+1 个
  __pycache__ 目录项)与 R4 record deploy_extra_modules 面同集
  (口径见 evidence/deploy_sync/COUNT_CLARIFICATION.md)。报告:
  `evidence/deploy_sync/report.json`。
- 生产保护面前后快照逐字节稳定:
  `qprod_deploy_config.json` 缺席(未激活,fail closed);
  `.r17_formal_admission.json`(历史 r19 一次性准入,2026-09-19
  消费)与签发日志零变化;旧正式根
  `artifacts/route_c_stage2_6_1_repair{17,18,19}` 文件清单与
  sha256 前后一致(零写)。正式根环境重定向变量全部未设置。

## 3. 计划快照(真实构建器,Commit A 绑定)

| 计划 | digest | 停止/授权 |
|---|---|---|
| A1(qualify 后停) | `qbpl-4426355c398b590302f0ff7efc67cfa8612a6b376446ad1bc41f676c23ba95fc` | model_update=False;内嵌 preflight-static PPO smoke 显式包含(1/256/≤40) |
| A2(完整链) | `qbpl-dca8ee032cf7f806ab2001ea265ce02b1ec3a2c0c3e0e8c6bae8fbfe5c8e43ee` | model_update=True;内嵌+第 14 步资格后 smoke(2/512/≤80) |
| B_UNAPPROVED | `qbpl-e513676848877b8b914cc88cf6432bdad845b2a0f950621bed6d5926fcf03586` | K=11 机械刷新;B_NOT_APPROVED(见目录内标记) |

- 全部三份 code_freeze_sha == de81aba2;code_identity 15/15 成员
  == Commit A blobs;digest 独立复算与公共函数复算均一致
  (`evidence/plan_identity/report.json`,37 检查全 PASS)。
- A1/A2 预算面与 R4 已验值逐项相等(28,798/113,030 与
  28,944/113,176;V2 9/10;MLP 85;MC 1e6;bootstrap 7.5e6;
  Global-K 50k/200k;子进程 19)。互斥候选:同 A、digest/quota
  不同;未来最多选一签发一次。
- 旧草案(R3 双哈希+空 SHA)→ 新:逐成员差异恰为
  coordinate(81fdede7→e470ac1b)与 aggregate(b21ce082→ea9bb967)
  + code_freeze_sha(''→A);旧 digest 可从旧 payload 复算复现,
  但其身份不匹配 Commit A(拒绝对照成立);旧≠新 digest。
- B 草案语义零变更:P0=0.950431552876822、margin 0.003、
  alpha 0.05、r_analysis 1.5、K=11、500 blocks×2 语料、
  8 eps/block、MC 1e6、collect_all_k。

## 4. 候选证据适用(FB07)与身份分层(FB05)

- 差分回归(现有 r21 执行器,differential 协议):
  run_id `r21_20261004_025733`,**178 tests / 0 failures /
  0 errors / 0 skipped**(FLP formal_launch+repair1-5+aggregate
  七文件),record sha256
  `4d088717f58148377e1fa2412b1733842d037aee62b663a581f0ddea92bb4e9c`,
  v6,绑定 de81aba2,parent=04d10208(全量绿件 2912/0F/0E/7skip,
  record 73e56d37…),delta_scope other_files=20、tests/runner=0。
- 只读实质核验(同源 admission substance verify,未签发任何
  admission):plan_digest(git_tree_digest)claimed==recomputed
  == `851c883b…`,回归证据链(含父件递归)核验通过 rc=0,
  substance digest `r17sub-627b4b…`
  (`evidence/fb05_substance_verify/`)。
- 身份分层:commit sha ≠ tree sha ≠ 三个 qbpl 计划摘要,互不混用;
  admission `git_tree_digest` 的定义即 Commit A 的 git tree 对象
  id(与 tree sha 相等是构造事实);admission 侧只接受该口径、
  qbpl 校验只接受 qbpl 前缀摘要,两核验器口径互斥;
  `qualification_plan_r17.json` 在正式状态根内不存在(未来链内
  lock-plan 产物;_rt 工程彩排根历史件已分类记录,不作补位)。
- 262:候选面 04d10208→de81aba2 零 diff;v25(240 passed,绑
  04d10208)按历史口径复用标注(`evidence/stage262_applicability.md`)。

## 5. 只读预检与非激活分类(FB08)

`evidence/preflight_fb08/summary.json` 8 例全 PASS:
- parser 对拍:preflight 无 --model-update;draft-plan/launch 有;
- 错组合 rc=2 零写(完整链无 model-update;qualify 带 model-update);
- 真实部署根 preflight:rc=1,FINDINGS_PRESENT,deployment_ok=false
  (配置缺失=预期未激活),business_leaf_calls=0;
- 错 SHA 反例:不同 code_freeze_sha → 不同 plan_digest;
- 隔离正例(formal_ready+admission 尾形):PREPENDING,
  admission_shape_ok=true,admission_present=false(如实未签发);
  沙盒 plan_digest == A1 草案 digest(构建器确定性);
- 错根反例(尾形不符)与旧状态反例(预置 run-plan)均 FINDINGS。

## 6. 边界遵守

零 formal_ready 激活;零许可签发/消费(r17_admission_issue 未
调用);零 launch/chain-run/qualify/smoke;零业务生成/MC/fit/
PPO/模型加载;零 seed/坐标锁/预算账本/exposure。生产保护面前后
快照逐字节一致。本轮新增计算 = 既有测试套件夹具(差分 178 项,
遵从原合同)。

## 7. 等待用户的操作(不预签、不代批)

1. A1 或 A2 二选一(互斥;批准即绑定 de81aba2 与对应 qbpl 摘要);
2. B 是否单独纳入批准(现 B_NOT_APPROVED);
3. 批准后的正式激活(生产配置/外部可信签发/一次性业务执行)由
   后续授权任务处理;本包不预授权该阶段。
