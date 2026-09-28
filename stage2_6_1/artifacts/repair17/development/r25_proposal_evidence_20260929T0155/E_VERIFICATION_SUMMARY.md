# E01/E02/E03 原件核验总览 — RouteC_R25_ProposalEvidence_SelfAcceptance_v1

核验时间：2026-09-29（本地）。全部只读。解释器与 rc 逐项列于 §4。

## 1. E01 实际 RETURN 原件

| 对象 | 实测 | 声明 | 结论 |
|---|---|---|---|
| `RouteC_R25_FinalClosure_TrainingReadiness_v1_RETURN_TO_CHATGPT.zip`（outgoing/ 原件 + input_return/ 只读副本） | sha256 `87d7c88b1c8725e72fe2975d7baacc26060027931f1382bf1f47853a0ecc9320`，811531 B | 同 | 一致 |
| 成员数/解压字节 | 123 文件 / 3,222,154 B（0 目录项，无重复，CRC 全过） | 123 / 3,222,154 | 一致 |
| 内层 `previous_round/RouteC_R25_BindingAndDescendantClosure_v1_RETURN_TO_CHATGPT.zip` | sha256 `8aab7aa768aa75885866ee8c8ca8097abd75c2fc890929769bdd27a7120bf85a`，530,428 B，124 成员，CRC 全过 | 同 | 一致；且 outgoing/ 独立原件同 SHA（双源对拍） |
| 包内 SHA256SUMS.txt 覆盖 | 122/122 精确匹配，清单不自哈希，123 文件全覆盖（122+清单自身） | selfcheck PASS 声明 | 复核成立 |
| 逐成员清单 | `E01_MEMBER_MANIFEST.json`（外层 123 + 内层 124，逐成员 size/sha256，嵌套定位 `outer::previous_round/…zip::member`） | — | 已产出 |

危险成员检查：全部普通文件，无 symlink/gitlink/设备/穿越/大小写冲突/重复名。

## 2. E02 完整回归（7e9e547，双通道）

**通道 1：独立复算**（`e02_verify_regression.py`，Windows CPython 3.13，repo 工作树）：record sha256 复算=611b234d…c2819d ✓；record 12 项字节锚（junit/audit_manifest/两 run 的 stdout/stderr/audit/lifecycle 引用）逐一重哈希一致 ✓；命令/解释器（/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python）/cwd（/home/cryptorl/projects/crypto_rl）/rc=0/commit_a=7e9e547 ✓；stdout 汇总行 `2534 passed, 7 skipped, 10 warnings in 2619.25s (0:43:39)` ✓；JUnit 逐 testcase 2541/0/0/7，collection stdout 逐行 multiset==JUnit ✓；counts/summary.json/aggregate 三方一致 ✓；7 个历史 skip 具体 ID record==JUnit ✓；r24 collection-audit verdict=pass、violations=0、stages 齐全 ✓；lifecycle JSONL 44/45 事件全可解析（event/monitor/register_guard）✓；audit_manifest 零批准生成测试 ✓；import_surface 315 成员 + test_files 148 与候选树 CR 规范化字节全等 ✓。

**通道 2：仓库权威核验器**（`curriculum261_r17_admission_substance.verify_regression_evidence`，WSL conda freqtrade-rl Python，deploy_root=/home/cryptorl/projects/crypto_rl，含部署面字节对拍）：

| 记录 | 候选 | 结果 |
|---|---|---|
| r25_final_closure full_regression_v1 | 7e9e547 | **VERIFY_OK**（aggregate 2541/0/0/7；collection 2541/static 2060/files 148） |
| r25_binding full_regression_v2 | 990dbcf | deploy 面对拍 mismatch（部署树已随 7e9e547 前进到最新 registry 测试——时序漂移，非记录缺陷；同轮 7e9e547 的 deploy 对拍全过即为其证据）；**repo 侧（deploy_root=None）VERIFY_OK**（2522/0/0/7；static 2041） |
| r25_binding full_regression_v1_FAILED_c07scope | 721b314 | **VERIFY_FAIL `regression_not_green`** —— 1×C07 失败真实保留（历史失败证据，不修绿） |

注：static_tests=2060 的运行期语义=候选 Git 树静态推导（`static_collection_ids`），与"参数行启发式计数"不同；权威核验器已按其语义闭合（2060）。

## 3. E03 监护与集成（5 run，required 逐成员）

`e03_verify_supervision.py`（Windows CPython 3.13，repo 工作树）：每 run 9 个 required 成员（telemetry_guest/win、alerts、business_stdout/stderr、native_sampler identity/terminal/confirmation、summary）**逐成员存在+大小+SHA 全对账**；record/summary schema（r17-run-record-v2 / r17-supervision-summary-v1）、run_id 三处一致、policy sha 一致、finalized/evidence_complete/无 missing_roles/无 control_failures；遥测 JSONL 全可解析、采样序列零异常（parse_errors/invalid/duplicate/regressions 全 0）；incidents 与 business rc 一致（rc=4 的 worker_exit incident 属真实失败记录）。

真实集成 run 20260928T160626_7004_367 深核：stdout `probe end w1 rc=0 / w2 rc=0 / w3 rc=124` + `checker w1/w2/w3 rc=0` + 3 份 verdict=clean JSON（root/child/grandchild dead_gone）✓；三份 registry（i01_probe/logs/w{1,2,3}_registry.json）format=r25-worker-registry-v2、created_roles 多重集=instances、pid 唯一且>0、start_ticks≥1、恰一 root 且=root_pid、identity_sources 在场 ✓（w1/w3 各 3 实例，w2=1 实例真无后代正例）。

包内↔repo 对拍：FinalClosure RETURN 内 run_supervision_runs/ 26 成员与 repo 原件**逐字节相同** ✓。

## 4. 执行记录（命令/解释器/cwd/rc）

| # | 命令 | 解释器 | cwd | rc |
|---|---|---|---|---|
| 1 | `python e02_verify_regression.py` | Windows CPython 3.13.x | repo/stage2_6_1/artifacts/.../r25_proposal_evidence_20260929T0155 | 0（ALL PASS；stdout 存档于本文件 §2 与 E02_REGRESSION_VERIFICATION.json） |
| 2 | WSL `verify_regression_evidence`×3（final_closure+deploy / binding_v2+deploy / binding_v1_FAILED+deploy） | /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python（模块身份 wt==候选 blob 57f0425d 前置校验） | /mnt/f/trading/freqai-rl-audit | 0；结果 E02_WSL_AUTHORITATIVE_VERIFY.json |
| 3 | WSL `verify_regression_evidence`（binding_v2, deploy_root=None） | 同上 | 同上 | 0；结果 E02_WSL_BINDING_V2_REPOONLY.json |
| 4 | `python e03_verify_supervision.py` | Windows CPython 3.13.x | 同 #1 | 0（ALL PASS；E03_SUPERVISION_VERIFICATION.json） |
| 5 | `git rev-parse HEAD:<tree>`（冻结树×3）+ vendor rev-parse | git / Windows+WSL | repo / vendor | 全部匹配（P01） |

stderr：#1/#4 无错误输出；#2/#3 WSL 侧仅 .wslconfig 警告（与核验无关）。

## 5. 证明类型的区分（不互相冒充）

- 本文件完成：包内 SHA 全匹配（E01/E03 包内↔repo 对拍）、**repo 侧逐文件与 Git HEAD 树的源面核验**（E02 通道 1+2 的 repo 部分）、源码级接线走查（提案附表 A）。
- **未进行**：部署树逐 blob 全量对拍只覆盖权威核验器 deploy 面（315 import surface + 148 test files + 配置面），未做全远端逐 blob 对拍；未重跑任何 pytest/研究/训练（复用条件=B01 执行面零变更 + 本文件原件核验成立，核验日期 2026-09-29 与原运行日期/候选身份分别记录于各 JSON）。
