# QProd R2 返修轮独立内容验收报告(reviewer v2 — C11 复验)

- 前序: local://q123_r2_review_report_v1.md(C10,a2d546f3)判 FAIL 两项(F1/P1 gate fail-open、F2/P2 探针前提漂移)。
- 被审候选: **C11 = 8f92a985**(36d66c28→8f92a985 单提交,HEAD 已确认,已 push)。
- 复验结论: **PASS(F1/F2 均已修复并经我独立实测;无新缺陷引入)**。

## 1. 改动范围与身份(V1 已确认项的适用性确认)

- `git diff --stat 36d66c28..8f92a985`: 恰 4 文件——runner(+5)、repro_round2.py(+35/-10)、REPRO_Q123_ROUND2_C11.json(新 92 行)、EVIDENCE_INDEX.md(+16 勘误段)。**src/tests diff = 0 行**→V1 已确认的 Q1/Q3 行为面与 261 v9(2652/0F/8S)/262 v6(240/0/0)junit 判定继续适用。
- 部署树 runner = C11 git 字节(sha256 前 16: 4bc4b39f4b8f5ba7);coordinate.py/钉测试与 C10 字节一致(cdac1668…/e0234e6e…)。
- 零新增原生/零 fit/零 optimizer: 本轮我的全部复验为读侧/合成/缺失文件拒绝路径,预算 2/2 未动。

## 2. F1(P1)复验 — PASS

修复=我 V1 建议的最小修复原样落地: heredoc 后 `GATE_RC=$?` + 非零 `exit "$GATE_RC"`(stderr 附 fail-closed 说明)。

用**提交版脚本**(非副本)三场景实测(全部在 deploy runner 路径):

| 场景 | rc | REFUSED/fail-closed 输出 | 是否到达"run2 目录已存在"守卫 |
|---|---|---|---|
| A 预算文件缺失(QPROD_NATIVE_BUDGET=/tmp/nonexistent_reviewer_probe.json) | **97** | 有(2 处) | **否(0 次)** |
| B 2/2 耗尽(默认路径真实 qprod_native_budget.json) | **97** | 有(2 处) | **否(0 次)** |
| C gate python 崩溃(cwd=/tmp 无 src) | **1** | 有(1 处) | 未达 |

三场景均在任何生成/许可/目录逻辑之前终止;"run2 目录存在"偶然守卫已不再参与防线。V1 的失效场景(产物目录缺失的树上无视拒绝继续生成)已消除;cwd 错误也转为 fail-closed。原件: 会话执行记录,gate 输出语义已录上表。

## 3. F2(P2)复验 — PASS

- case8 重写为**自带无 audit_budgets 声明的完整载荷**,不再 import tc/依赖 fixture(我核读 diff;freeze_research_plan 依赖一并移除)。
- 我独立重跑提交版探针(C11 字节,deploy 树): **REPRODUCED 0/14**,case8 detail="无audit_budgets声明结构问题=['rules.audit_budgets 缺(逐坐标审计预算必须事前声明:blocks_per_corpus/mc_events/episodes_per_block)']"——前提真实、拒绝真实、语义正确。
- 归档 `REPRO_Q123_ROUND2_C11.json`(label 如实标注 pending-commit/deploy synced/case8 self-contained): 14/14 reproduced=false;与我独立运行**逐 case detail 全同**(程序化比对 0 差异)。原件: F:/trading/reviewer_q123_r2/c11/REPRO_Q123_ROUND2_C11_REVIEWER.json。
- EVIDENCE_INDEX 勘误段如实: C10 件 case8 来自混合部署态、已被 C11 件取代、其余 13 项不受影响——与 V1 我的实测结论一致,接受该更正记录。

## 4. 冒烟复跑(C11 部署树,我执行)

- 钉测试: 16 passed, 1 skipped(E01 原件用例环境性 skip,仓库树跑;V1 已证 17/17)。
- 全 qprod 面 9 文件: **122 passed, 1 skipped**。

## 5. 判定汇总

| 项 | V1 | V2 |
|---|---|---|
| Q1(7 反例+正例) | PASS | PASS(身份确认,src/tests 零改动) |
| Q2(逐动作计数/预占/三方对账/反例保留) | PASS | PASS |
| Q2 原生硬门 runner 集成 | **FAIL(F1)** | **PASS**(三场景实测 fail closed) |
| Q3(6 项+E01 如实) | PASS | PASS(身份确认) |
| 证据件(repro/junit/E02/原件) | **FAIL(F2)** | **PASS**(C11 件可复现,勘误如实) |
| 22 项矩阵 | 见 v1 §7 | 维持;R01/P01 补 C11 冒烟证据 |

**总判定: PASS**。遗留事项(不阻塞内容验收,按既定流程): 最终增量包(基包 972d0c0f… + 本轮成员)封包后 reviewer 新目录 ZIP 冷读与包外 SHA/DELIVERY/REVIEWER_FINAL_RECEIPT;ChatGPT 独立终验与 CLOSED 由其自行签发。非阻塞备注: gate 崩溃场景 rc=1(非 97)但同样中止,语义可接受;C11 JSON label 的"pending commit"措辞如实,无需更正。

## 6. V2 复验原件位置

- F:/trading/reviewer_q123_r2/c11/REPRO_Q123_ROUND2_C11_REVIEWER.json(我独立 0/14)
- gate 三场景: 会话执行(rc=97/97/1,输出语义录于 §2 表)
- 冒烟: 钉 16+1、qprod 面 122+1(会话记录)
- V1 全部原件维持有效: F:/trading/reviewer_q123_r2/(e02_run/、e02/、E01 复算、V1 repro 1/14 实证、gate fail-open 实证)
