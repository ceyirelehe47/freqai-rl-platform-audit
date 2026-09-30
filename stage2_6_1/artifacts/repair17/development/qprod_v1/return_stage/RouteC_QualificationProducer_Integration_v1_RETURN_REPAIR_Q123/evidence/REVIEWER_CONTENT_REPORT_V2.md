# QProd 返修轮 F1/F2 复验报告 v2(候选 C9=bcc908ae)

- Reviewer:OMP 已配置 reviewer(zhipu-coding-plan/glm-5.3-flash),与 V1 同一独立上下文、同一标准。
- 被审对象:**C9=bcc908ae**(HEAD,已 push;d4a4e73a→bcc908ae 单提交,5 文件:+277/-8)。
- 结论先行:**F1 已修复并实证通过;F2 交付件已修复,但残留 1 项 P2(证据索引对 repro_q123.py 的"不再硬编码"声明与提交版脚本矛盾)→ 本轮判定 FAIL(仅此一项收尾;修复成本=一次提交既有文件)。**
- 边界执行:零新增原生(维持 2/2)、零 fit、零 optimizer;单重型 WSL 作业;E01 legacy 容忍不变。

## 1. F1(P1)通用失败/中断记账 —— **已修复,实证通过**

| 核验点 | 结果 | 证据 |
|---|---|---|
| 结构:配额分支后独立 `except BaseException` 处理器(marker+账本 interrupted 行+raise),死代码消除 | 通过 | coordinate.py 622-649 区(工作树=提交=bcc908ae blob sha256 34b369c9…三方一致);原死代码体成为活处理器体,无重复/无残留 |
| 行为:非配额失败(RuntimeError 注入核心)→ marker 存在、账本恰 [start, interrupted] | 通过 | **reviewer 探针重跑**(v3_probe.sh 对 C9 部署树):raised=RuntimeError、interrupted_marker_exists=**true**、ledger=[start, **interrupted**];V1 时同探针为 marker=false、[start] |
| 配额路径不回归:QProdQuotaExceeded→marker+quota_exceeded 行 | 通过 | 同探针对照:raised=QProdQuotaExceeded、marker=true、[start, quota_exceeded](与 V1 一致) |
| 中断重入拒绝恢复 | 通过 | 新钉测试断言二次 run 抛 QProdContextError(match="中断");coordinate.py 568-571 行检查逻辑未动 |
| 新钉测试真实性 | 通过 | `test_f1_nonquota_failure_writes_interrupted_marker_and_ledger`:patch 公共核心注入 RuntimeError,断言 marker/账本序列/error 前缀/重入拒绝——正是 V1 finding 的复验面 |
| 早停启动拒绝不受影响 | 通过 | 启动守卫在 try 块之外(~575 行,try 起 617 行),不受新处理器影响;q123 钉测试 early_stop 启动守卫用例在 C9 通过(见下行) |
| 定向回归 | 通过 | **67 passed, RC=0**(q123 fixes 21 + coordinate + aggregate + permit + levela,WSL 部署树 reviewer 实跑) |
| 受影响面外零改动 | 通过 | `git diff d4a4e73a bcc908ae --name-only`:仅 5 文件(索引/两份复现 JSON/coordinate.py/钉测试);aggregate/permit/levela/export 与 V1 通过版逐字节相同,V1 已确认项不失效 |

## 2. F2(P2)复现原件与证据索引 —— **主体修复,残留 1 项 P2**

已修复部分(实证):
- 失实的 REPRO_Q123.json 已从候选移除(重命名为 REPRO_Q123_C9.json 并更正标签)。
- `REPRO_Q123_PREFIX_C7.json`:标签「C7 tree=691bd73a (git archive mirror; pre-fix)」,15 项全部 reproduced=true,用例清单与 reviewer V1 独立 V5 运行(15/15)完全一致——修复前原件已随候选保存。
- `REPRO_Q123_C9.json`:0/15,标签「C9 tree=(F1 fix pending commit; deploy synced)」——如实(deploy 树 coordinate.py 已核实=bcc908ae 字节);建议封包时按最终候选号重贴标签(PK01,非阻塞)。
- EVIDENCE_INDEX 增加勘误段与 F1/F2 修复记录,「复现」节改为两份原件分开保存。

**残留 P2(本轮唯一 FAIL 项)**:
- EVIDENCE_INDEX(提交版)声明:`repro_q123.py`「候选标签经 REPRO_CANDIDATE/REPRO_OUT 环境变量注入(**不再硬编码**)」。但提交版 `repro_q123.py`(bcc908ae,自 bd6ed858 未改)仍硬编码 `OUT = Path("/mnt/f/trading/tmp_qprod2/REPRO_Q123.json")`(19 行)与 `"candidate_under_test": "C7=cda4e975 (deploy tree synced)"`(358 行)。参数化实现只存在于仓外草稿 `/f/trading/tmp_qprod2/repro_q123.py`(14:00 修改,diff 仅 2 处:OUT/标签 env 化),未入候选。
- 性质:与 V1 F2 同类(提交索引声明 vs 提交工件事实不符)——冷读者对包内核对索引与脚本即发现不实声明。两份 JSON 本身如实且可独立复验,故降为 P2 收尾项,但同标准下不能判 PASS。
- 修复:把草稿版参数化 repro_q123.py 原样提交入候选(diff 已由 reviewer 核验,仅 19 行与 358 行两处),使索引声明成真;若同时重贴 C9 标签为最终候选号更佳(可选)。

## 3. 复验运行记录(全部真实命令与 rc)

| # | 命令/检查 | 结果 |
|---|---|---|
| R1 | `git show bcc908ae` 全 diff 亲读(5 文件) | 与声称一致;coordinate.py 仅 +5 行(插入 except BaseException 头+注释,原死代码体转为处理器体) |
| R2 | 字节三方核对:bcc908ae blob=34b369c9…=repo 工作树=WSL 部署树(coordinate.py 与 q123 钉测试文件) | 一致 |
| R3 | v3_probe.sh(WSL,patch 公共核心;零生成)对 C9 部署树 | 非配额失败:marker=true、[start, interrupted];配额:marker=true、[start, quota_exceeded] |
| R4 | WSL 部署树 `pytest q123_fixes+coordinate+aggregate+permit+levela -q` | **67 passed, RC=0** |
| R5 | REPRO_Q123_PREFIX_C7.json / REPRO_Q123_C9.json 解析 | 标签如实;15/15 与 0/15;用例集与 V1 独立基线一致 |
| R6 | diff 提交版 vs 草稿版 repro_q123.py | 仅 OUT/标签参数化 2 处——即未入候选的残留差异 |
| R7 | EVIDENCE_INDEX.md 全文复读 | 勘误/F1/F2 段落实;「不再硬编码」一句与提交版脚本矛盾(§2 残留项) |

## 4. 打包前置提醒(非本轮判定项,封包前必须完成)
- R01/PK01:archive 中的 261 v7 / 262 v4 junit 绑定 C8 字节(12:41/13:25,早于 C9 提交 14:14)。若 C9 为最终候选,封包前需以 C9 字节重跑适用全量回归并归档新 junit(或在决定页给出适用性理由并留痕)。
- REPRO_Q123_C9.json 标签建议按最终候选号重贴(现标签如实但为提交前状态)。

## 5. 结论
- **判定:FAIL(工程,1 项 P2 残留)**——F1 通过;F2 的交付件与勘误成立,但提交版 EVIDENCE_INDEX 对 repro_q123.py 的参数化声明与提交版脚本矛盾(同 V1 证据自洽标准)。
- 修复方式:提交已就绪的参数化 repro_q123.py(2 处 diff)即可转 PASS,无需其他代码改动;修复后 reviewer 复验点=提交版脚本含 REPRO_CANDIDATE/REPRO_OUT 且索引声明为真。
- 零新增原生维持;最终 CLOSED 由 ChatGPT 独立终验。
