# P01 历史保护核对 — RouteC_R25_ProposalEvidence_SelfAcceptance_v1

核对时间：2026-09-29（本地）；全部只读命令，原件零改动。

## 1. 冻结研究树（现时 HEAD 复算 = 上轮 before/after 记录 = Binding 轮 old_data_freeze）

| 对象 | tree hash（三方一致） |
|---|---|
| r25_cue_bias_dev/plan | df7d04de195fe634bbee7cfc4c63ad824177d2a1 |
| r25_cue_bias_dev/smoke | 3ef2fc551161b02b243df55420743164e24d300 |
| r25_cue_bias_dev/study | 96df8ff992f5cda4d9abd62fc4c85527cb29ff97 |

依据：`git rev-parse HEAD:<path>`（本轮实测）＝ `r25_final_closure_20260928T160624/protection_{before,after}.txt` ＝ `r25_binding_descendant_20260926T210941Z_33888/old_data_freeze.txt`。

## 2. vendor 冻结

WSL 只读实测：`/home/cryptorl/projects/crypto_rl/vendor/freqtrade` HEAD = `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`（= 声明 pin），工作树 clean。未升级、未改动。

## 3. 历史失败与终态原样

- 旧失败回归 `full_regression_v1_FAILED_c07scope`（721b314，1×C07）：权威核验器现时复核 = `regression_not_green`（真实失败保留，未被修绿）；对应监护 run 20260926T212354_1984_392 business rc=4 + worker_exit incident 原样（E03）。
- R19 正式统计 FAIL 终态、R25 开发研究条件结论、历史 creator 源码 MISSING/not_established：未触碰、未重跑、未补写（本轮命令清单见 §5）。
- 旧 RETURN 原件（outgoing/ 的 FinalClosure 87d7c88b… 与 Binding 8aab7aa7…）：SHA 实测一致（E01），未改一字节。

## 4. 本轮零新研究/训练/许可消费

无正式 R20 注册/namespace claim、无正式 cue-audit/audit 数据生成、无 qualification/exposure 消费、无 BC/PPO 训练、无 11 坐标重跑、无 c12、无联网 dry-run、无交易/采购。研究生成模块零调用。

## 5. 本轮实际执行面（全部只读 + 授权清理）

- Git 只读：status/log/diff/ls-tree/rev-parse/grep/show/hash-object。
- 只读核验器（本目录）：e02_verify_regression.py（Windows，repo 侧）、e03_verify_supervision.py（Windows，repo 侧）、WSL 侧调用仓库自带 `verify_regression_evidence`（含 deploy 只读对拍）×4、vendor rev-parse。
- E01 复制件入 input_return/（新增副本，不改原件）。
- 用户授权的工作区清理（2026-09-29）：goal_incoming 旧轮残留归档至 `F:/trading/archive/goal_incoming_history_20260929/`（账目 `REORG_MANIFEST_F_20260929.tsv`）；git 删除 repair11–16 分支（本地+远端，均为 HEAD 祖先，提交仍可达）。不触及任何仓库内原件/在飞未提交变更/packs/outgoing。
- 本轮新增文件仅位于 `r25_proposal_evidence_20260929T0155/` 与 `report/route_c_stage2_6_1_qualification_to_training_proposal_v2.md`（新文件）+ `stage2_6_1/README.md` 末尾追加索引行（不改旧条目）。

## 6. 工作树已知状态（非本轮造成、未触碰）

- `D r25_final_closure_20260928T160624/candidate_C_push_receipt.txt`：HEAD 在册、工作树缺失（在飞轮次状态）；本轮读取一律走 `git show HEAD:`。
- 9 个 typechange（c3_entry/v2_c13 历史证据 symlink 型成员呈现差异）与 49 个 untracked（r24 尝试脚本、历史 run_supervision run、return_stage）：属在飞轮次，保留不动。
