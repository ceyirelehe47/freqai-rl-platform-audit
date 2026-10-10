# DECISION_SUMMARY — RouteC_A2_RuntimeClosure_NewAttempt_v1(≤2 页)

出口:`A2_RUNTIME_READY_PENDING_USER_APPROVAL`(2026-10-10)。本轮=工程修复与下一尝试准备,**未签发任何正式 permit/admission、零消费、零 launch、零科学资格计算**。

## 1. 最终身份(待批准的一次 A2 执行绑定)

| 面 | 值 |
|---|---|
| Commit A | `0f494d27bad2ed0de6876ff32f4cb7d656a19c98` |
| A tree | `7a2fecbbea921181562720b07e5b87ca6c4e5f7a` |
| 尝试/迭代 | qaf_v3 / qprod_a_formal_v3(26 全新 namespace) |
| 研究计划(qbpl) | `qbpl-c2dd9bb802ca890cc6aa2ef2b9ae4ffbb8f5f1788ee7e87dd7854816aabe8a36`(真实构建器,draft==rebuilt;含 run_scope.attempt_identity 显式注册) |
| 回归 record | sha256 `2e9fccfb14ab9c67992a1031302b690d2af28c6c56f8c0d05d412fb2ce4d5548`(run r21_20261010_160557,2990=2983P+7S/0F/0E,cwd=D3) |
| P3 / D3 / PIN | `/home/cryptorl/projects/crypto_rl_qaf_v3` / `/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3` / `/home/cryptorl/release_pin_qaf_v3`(branch route-c-stage2-6-1-repair17 @ Commit A) |
| admission-id(未来) | `qaf-v3-0f494d27-a2` |
| 预算 | 与原 A2 全等(生成 ≤113176/MC 1e6/bootstrap ≤7.5e6/V2 fit 10/MLP 85/PPO learn 2+rollout 512+step≤80/验证 100/check_env 20/save-load 2 对/Global-K 50000→≤200000/原子子进程 ≤19)——零扩张 |

执行步骤:E1 配置激活→E2 prepare→E3 批准原件→E4 operator execute,完整实命令见包内 COMMANDS_APPENDIX.md(E4 关键参数:--admission-id qaf-v3-0f494d27-a2 --plan-digest 7a2fecbb…(git_tree_digest) --code-freeze-sha 0f494d27… --stop-after verify-formal-logs --model-update --attempt qaf_v3)。

## 2. 本轮闭合要点

- **上轮失败根因**(P2 freeze dev root 缺 environment.yml/requirements-lock.txt):P3 实装全 src+全静态依赖,preflight 真实消费者实测 ok。
- **发布源 HEAD 漂移**(E0 记录 37c5c164 vs 候选 a96bedea):pinned clone PIN+`release_repo_candidates()` pin 优先接入全部 14 处 src 解析点;HEAD==A+clean+分支名 ancestry 全部活测(错 HEAD/dirty/detach 全拒,旧 P 52 个历史负例目录同证)。
- **签发前防错**:runtime_dependency_preflight 入 preissue_gate,operator execute 与直接 issue-permit 两入口首一次性写前同一前置;E1 未装时全门 fail-closed(one_shot_writes=0)。
- **授权身份贯通**(reviewer R3 两轮修复 F-1/F-1R):计划全部身份文本随 qaf_attempt_family 参数化+attempt_identity 显式注册,payload 扫查零 v1/r17 namespace 残留;v1↔v2↔v3 深度 diff=纯身份键,科学语义/quota/rules 全等。
- **活链证据@0f494d27**:provenance→determinism(A4/A5/A6)→audit 三步前缀全绿(freeze anchored r17fs-5f36c3ca,ancestry ok,全 binding pass);substance 同根 rc0/错根 rc2;三方对拍 698/597/660 全等;全量回归 2990 全绿。
- **旧现场**:P2/D2/qaf_v1/qaf_v2 保护原件逐字节未变(P2 仍缺 env 两件=根因原样保留);标准部署树 crypto_rl 内工程动作(52 个 dummy-sha 负例探针+2 文件候选同步)如实披露。
- **独立验收**:dsv4.1f 后端额度不足→用户授权换用→reviewer(glm-5.3-flash:max,配置解析)三轮内容审查(R3 全矩阵+两次复验),RD01–RD05/RD07–RD09 PASS,RD06 经 F-1/F-1R 修复后由 reviewer v3 终报告全矩阵 PASS 并签发结论行;报告原件在包内 evidence/reviewer_r3/。

## 3. 仍未批准的动作

B、正式课程教学、C3 优化、额外选参、实盘/资金操作均未批准;新正式签发/消费/launch=0。**批准文字模板见 PENDING_APPROVAL_SUMMARY.md——仅用户实际发送才生效**;发出后操作员按 COMMANDS_APPENDIX E1–E4 连续完成一次执行。
