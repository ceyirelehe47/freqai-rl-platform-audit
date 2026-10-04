# QAFv2 RC gate1 第三轮复验报告(候选 513e75e3)

reviewer 线:dsv4.1f 独立验收线(同线续验)| 日期 2026-10-05
被审:Commit A `513e75e35f05ed18a5ebd9db76834de938e44113`(parent fc165e16;仅 runner/qprod_formal_authority.py + 文档;证据
cd9acbf3+e5191881,src/tests/runner 相对 513e75e3 零变化已核)
环境:scratch 重建到 513e75e3(关键文件 vs git blob EXACT)+隔离 sandbox 域(domD/domA3/domB3/fastpath)
证据目录:`/f/trading/local/rc_review/`

## 0. 结论

**gate1 收口 PASS(全 P 项修复经独立复验);唯一遗留为非阻断 P3 文档 nit。**
R2→R3 变更:init 快速路径改用共享 `_read_identity_bounded`(两读点同源)+ PREP 改 `D2/prep_qaf_v2`(普通目录)+ 文档 rebase。

## 1. 复验实测(全部自跑)

| # | 项 | 结果 |
|---|---|---|
| 1 | 套件复跑(guard25+closure6+launch42) | **73 passed** ✓ |
| 2 | F2 自然并发 2×40 | 80 rc0,**0 traceback**,40 轮各一 creator+一分类败者(无双写) ✓ |
| 3 | F2 自然并发 4×15 | 60 rc0,**0 traceback**,45 分类败者 ✓ |
| 4 | F2 barrier 交错 | init 双方 rc0 无回溯;record-approval 一胜一拒无回溯 ✓ |
| 5 | F2 快速路径确定性(子例 1:赢者暂停至败者超时) | 败者 rc=1、无回溯、输出"并发 authority 身份仍在写入(concurrent-loser 稍后重试)" ✓ |
| 6 | F2 快速路径确定性(子例 2:重试窗口内放行) | 败者 rc=0、"already-initialized(create-only)" ✓ |
| 7 | PREP 正例(批准写 `<deploy>/prep_qaf_v2/`,即新 $PREP 同形) | **rc=0 全链**:identity/approval/permit/prereg/admission 各一+消费 1 次+哨兵(链前,leaf=0);首门不再异物 ✓ |
| 8 | F1 反例重跑(stale/wrongcand) | rc=96、phase=before_first_one_shot、零落盘 ✓ |
| 9 | record 864cc48e | sha/计数 2943=2936P+7S/0F/0E/commit 513e75e3/cwd=D2/run r21_20261005_020425/junit 1e8188c3 自洽 ✓ |
| 10 | 归档链 | r2fix_9210cd24→0e106730、rc_gate1_8c160d0a→7b4b2be2、a2r2_efb35552→8436a1a7 均在未改签 ✓ |
| 11 | 计划 | 重建=qbpl-d10885c1;payload==文件;与上一计划差异仅 /code_freeze_sha;tree e2769ea1 ✓ |
| 12 | 快照 | 9/9:git blob==快照字节(INDEX commit=513e75e3)✓ |
| 13 | 三方对拍 | 625 文件 all_equal,0 mismatch,18 pyc 分类 ✓ |
| 14 | substance | D2 rc=0(e2769ea1/864cc48e/2943);P2 错根 rc=2 ✓ |
| 15 | D2 非激活/新鲜度 | config/admission/authority/state 全 absent;target ready、foreign=[];freshness.fresh=true ✓ |
| 16 | 保护面 | 旧 P/D 与快照逐字节一致 ✓ |
| 17 | 262 适用 | 本轮变更不触 src/stage2_6_2(仅 runner)→复用依据成立 ✓ |
| 18 | 文档 rebase | COMMANDS_APPENDIX(513e75e3/qbpl-d10885c1/e2769ea1/864cc48e/PREP+mkdir -p)、CLOSURE_REPORT(RC03 含 F1 门;F1@9210cd24/F2@513e75e3 分注;625/6+73)、PENDING(513e75e3/625)✓;CONTROL_FLOW 含"2b 绑定门"步骤 ✓,但标题候选标记仍为 9210cd24(见 Finding) |

## 2. Findings(1,非阻断)

### 1. [P3] CONTROL_FLOW 标题候选标记未随 513e75e3 更新
`CONTROL_FLOW.md:1` 仍写"(候选 9210cd24)";内容(2b 绑定门等)对当前候选仍准确,但封包引用面标题标记应指 513e75e3(或改为"≥9210cd24")。文档-only 提交即可修(不影响 Commit A 绑定)。
