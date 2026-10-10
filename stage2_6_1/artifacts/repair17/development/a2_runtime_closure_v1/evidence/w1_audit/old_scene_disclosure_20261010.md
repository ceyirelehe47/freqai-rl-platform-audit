# 旧现场保护披露 — 2026-10-10 后置核查(RD01)

本文为 RD01 的完整如实披露:保护面原件逐字节未变;同时如实列出本轮在标准部署树(crypto_rl)内发生的两类工程动作。前值对照 = `old_scene_identity.txt`(轮初只读留存,2026-10-05);后值对照 = `old_scene_identity_after_20261010.txt`(2026-10-10T04:08Z 只读复查)。

## 1. 保护面原件:逐字节未变(PASS)

| 原件 | 轮初 SHA-256 | 2026-10-10 复查 | 结论 |
|---|---|---|---|
| 旧 P(qaf_v1 现场)`/home/cryptorl/projects/crypto_rl/.r17_formal_admission.json` | `b465e5f17a651d0a…`(e0 快照/上轮审查一致) | `b465e5f17a651d0aee7f9a10fbb406448a37e1eae414c541aef7861db668ab6c` | 未变 |
| 旧 P `r17_admission_issued.jsonl` | (轮内在案) | `956178b282e42ae73be1cdd3ade0772af53cf7eb2682fe8b9d02a20411fdcb6f` | 未变 |
| P2 冻结单件 RouteCStrategy.py / activate-freqtrade.sh | `dc5deab4…` / `6c43ec58…` | 同左 | 未变 |
| P2 `requirements-lock.txt` / `environment.yml` | MISSING(失败根因) | 仍 MISSING | 未修补(按"不修补旧现场"保留) |
| D2 三单件 environment.yml / requirements-lock.txt / activate-freqtrade.sh | `e7a0850e…` / `4e727d3d…` / `6c43ec58…` | 同左 | 未变 |
| 旧 P 四单件(RouteCStrategy/reqs/env/activate) | `dc5deab4…`/`4e727d3d…`/`e7a0850e…`/`6c43ec58…` | 同左 | 未变 |
| P2/D2 新文件(2026-10-05 19:00 后) | — | 零新文件 | 未变 |

qaf_v1/qaf_v2 一次性资源不恢复、无新签发/无新消费/无 launch(本轮全程零 permit/admission/科学调用;唯一 gate 调用为只读 preissue,因 E1 配置未装而正确拒绝,见 `runtime_verify/preissue_gate_P3_preconfig_refused.json`)。

## 2. 如实披露:标准部署树 crypto_rl 内的两类工程动作

旧 P 根 `/home/cryptorl/projects/crypto_rl` 同时是历史标准部署/测试树(既往惯例:候选代码同步入该树跑工程测试)。本轮在该树内发生:

### 2.1 工程哨兵链探针写 r17_rt_runs(2026-10-05 04:27Z–10-06 07:09 本地时段)

52 个 `r17_rt_runs/2026100[56]*` 运行目录(R3 复核勘正:reviewer 实数 52,初稿误写约 30;逐目录清单见 `rehearsal_inventory_20261010.txt`),全部为 `--rehearsal` 模式、dummy freeze sha(`0000…`/`1111…`)的**负例探针**:每一个都在 audit 步被 `write_r17_code_freeze` 的 HEAD==Commit A 检查正确拒绝(报错样例:`code_freeze_sha 与 repo HEAD 不一致——冻结必须绑定Commit A 提交(HEAD=85a879a4…,传入=1111…)`),`exposure=not_exposed`、fail-closed 封口。报错中的 HEAD 值随当时候选演进而变(eca28ea1→d705c494→af5c9d86→71da73a6→61180756→2f3e7faa→b3e3bffd→45a47547→85a879a4),与提交时间线一致——这正是 RD03"齐件但错 HEAD 拒"的活运行证据。全部产物仅落 r17_rt_runs 运行目录(历史惯例的测试副产物位置),未触碰任何保护原件;不入提交。

### 2.2 部署树候选同步(2 个 src 文件,2026-10-06 07:33 本地)

`crypto_rl/src/rl_curriculum/curriculum261_r17_admission_substance.py` 与 `__init__.py` 被同步为最终候选 85a879a4 版本(逐字节=候选 git blob:`57f0425dbe3f152b0ad66c3961289f77d45e2eb0` / `7aa2541d…`),属既往惯例的部署树测试同步;非保护原件,不影响任何身份/账本。

## 3. 附注:PIN checkout 状态与 worktree 显示差异(不影响消费者)

PIN(`/home/cryptorl/release_pin_qaf_v3`)为独立 clone(`.git` 为目录),保持在 `route-c-stage2-6-1-repair17` 分支、HEAD=85a879a4、porcelain 干净。**分支名本身是 ancestry 检查的输入**(historical binding 的 r16/r17_branch_name_ok):2026-10-10 曾试验性 `checkout --detach 85a879a4`,活 audit 前缀探针立即在 ancestry 项拒绝(`r16_branch_name_ok=False`、`current_branch=""`,见 `runtime_verify/prefix_probe_85a879a4/ancestry_refused_detached_head.json`),随即恢复分支 checkout 并重跑全绿前缀——该次拒绝留档为"PIN 必须以分支态绑定 Commit A"的负例证据。HEAD==Commit A 由冻结函数与 preissue 前置实时强制(分支被 pull 前移即 fail-closed),无需 detach。

主仓 `git worktree list` 中残留 `release_pin_qaf_v3 … detached@45a47547` 过期 admin 条目(创建期 worktree 登记残留,消费者不读取该条目;实际解析按 pin 根路径)。preflight 实证 `repo_root=/home/cryptorl/release_pin_qaf_v3`、`repo_head_commit=85a879a4…`(`runtime_verify/preflight_P3.json`)。
