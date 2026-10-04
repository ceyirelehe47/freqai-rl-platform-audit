# QAFv2 RC gate1 修复复验报告(第二轮:候选 9210cd24)

reviewer 线:dsv4.1f 独立验收线(同线续验)| 日期 2026-10-05
被审:Commit A `9210cd24bd8d424eb85186b96a28810f8d2f01f5`(parent 9a8d95f0;证据提交 fc165e16,src/tests/runner 零变化已核)
环境:自建 scratch 重建到 9210cd24(关键文件 vs git blob EXACT)+ 独立 sandbox 域(domA2/domB2/domC2/domPrep/domPrep2)
证据目录:`/f/trading/local/rc_review/`(本轮新增文件见下表)

## 0. 结论

**overall_correctness = incorrect(3 findings)**;F1、F3 修复经独立复验成立,新证据全集复核通过;但 **F2 未闭环**(快速路径仍崩溃)且 **F4 的 PREP 定义引入首门阻断**。confidence ≈ 0.90。

## 1. 复验实测

| # | 项 | 方法/脚本 | 结果 |
|---|---|---|---|
| 1 | 套件复跑 | run_suites_9210.sh(scratch@9210cd24) | 73 passed(guard25+closure6+launch42)=6/6 收口+67 受影响 ✓ |
| 2 | F1 反例(错批准计划) | probe_mismatch.py stale(domA2) | rc=96,phase=before_first_one_shot,one_shot_writes=0;authority/approval/permit/prereg/admission 全零落盘 ✓ |
| 3 | F1 反例(错候选) | probe_mismatch.py wrongcand(domB2) | rc=96,同上零写 ✓ |
| 4 | F1 正例控制 | probe_mismatch.py positive(domC2) | rc=0:identity/approval/permit/prereg/admission 各一,permit 消费 1 次,sentinel_stopped(链前),business_leaf_calls=0 ✓(不误拒) |
| 5 | F2 人工 bariexecr 交错 | rc04_ab_9210.json | init_new:双方 rc0、无回溯(败者经有界重读分类);旧版仍双写 ✓ |
| 6 | F2 自然并发 2×40 | init_natural_ab_9210.json | new:78 rc0+**2 rc1(2 轮 traceback,行 58 快速路径)**;old:0 traceback/14 轮双写 |
| 7 | F2 自然并发 4×15 | 同上 | 1/45 败者 traceback(行 58) |
| 8 | F2 快速路径确定性反例 | fastpath_demo.py(赢者 open 后暂停写) | 输者(快速路径)rc=1 + JSONDecodeError traceback(行 58)✓ 机制确证 |
| 9 | F4 PREP 放置 | prep_demo.json / prep_execute_stdout.txt | 批准置于 $PREP(=art root)后:preissue_gate ok=false("异物文件 ['approval_qaf_v2.json']");entry execute rc=96 同拒绝(零写);移除后 gate ok=true |
| 10 | F3 | PENDING §5 | 已改 9210cd24/qbpl-4bd63545,与 §1/附录一致 ✓ |
| 11 | 新 record | 直读+sha | 0e106730…;2943=2936P+7S/0F/0E;commit 9210cd24;cwd=D2;run r21_20261005_005619;junit f409c668 自洽 ✓ |
| 12 | 旧件归档 | 直读 | 7b4b2be2(rc_gate1_8c160d0a)/8436a1a7(a2r2_efb35552)均在,未改签 ✓ |
| 13 | 计划 | verify_9210.json | 重建=qbpl-4bd63545;payload==文件;与上一计划差异仅 /code_freeze_sha;invariants 等 ✓ |
| 14 | 快照 | snapshots_verify_9210.json | 9/9:git blob==快照字节==CR 投影==P2==D2 ✓ |
| 15 | 三方对拍 | verify_9210.json | 625 文件 all_equal,0 mismatch,18 pyc 分类 ✓ |
| 16 | substance | rerun 9210 | D2 rc=0(2caa542b/0e106730/2943);P2 错根 rc=2 ✓ |
| 17 | D2 非激活/新鲜度 | d2_now.sh + rc05 checks | config/admission/authority/state 全 absent;A 根 3 件(ready);freshness.fresh=true;P2==D2==候选字节 ✓ |
| 18 | 保护面 | protection_compare_now.json | 旧 P/D 与快照逐字节一致 ✓ |
| 19 | 262 适用 | git diff(9a8d95f0..9210cd24 不触 src/stage2_6_2) | 复用依据仍成立 ✓ |

## 2. Findings

### 1. [P2] init 快速路径仍对半写身份文件崩溃(F2 未闭环)
`qprod_formal_authority.py:57-58`(快速路径)未套用 F2 的有界重读;并发赢者 open 建档未写时,输者走快速路径读到空文件即未捕获 JSONDecodeError。实测:自然 2 并发 ×40 轮 → 2 轮败者 traceback(行 58);4 并发 ×15 → 1/45;确定性复现(赢者 open 后暂停、输者快速路径 → 崩溃)。修复:快速路径复用同一有界重读/分类助手。

### 2. [P2] PREP 指向 A artifact 根→按 E3 写入批准即阻断 execute 首门
`COMMANDS_APPENDIX.md:11` 定义 `PREP=D2/artifacts/formal_a_qaf_v2`(= guard 扫描的 A artifact 根);E3 令用户写 `$PREP/approval_qaf_v2.json`。按附录字面执行:preissue_gate 以"实际 A artifact 根存在异物文件 ['approval_qaf_v2.json']"拒绝,entry execute rc=96、零写(实测);移除文件后同一 gate ok=true。批准原件应落在 guard/freshness 不扫描的普通目录(如 `$D2/prep_qaf_v2`)。

### 3. [P3] CONTROL_FLOW/收口报告未随 9210cd24 同步
`CONTROL_FLOW.md:1` 仍标"(候选 8c160d0a)",执行序列(行 14-22)缺 F1 新增的"批准↔参数绑定门"(2 与 3 之间);`CLOSURE_REPORT_RC.md` RC03 行未含新门(被记入 RC04 行),RC06 行"8c160d0a 重新部署/624"、RC07 行"5/5+72/72"、快照节标题"候选 8c160d0a"、部署行"624"、PENDING §1"624 文件"均为旧值(应为 9210cd24/625/6+67/73)。
