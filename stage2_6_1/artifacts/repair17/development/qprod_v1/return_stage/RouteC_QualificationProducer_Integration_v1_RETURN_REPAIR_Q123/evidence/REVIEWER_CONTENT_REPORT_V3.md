# QProd 返修轮 F2 残留关闭 + 封包前置复验报告 v3(最终内容验收)

- Reviewer:OMP 已配置 reviewer(zhipu-coding-plan/glm-5.3-flash),与 V1/V2 同一独立上下文、同一标准。
- 候选链:bcc908ae(V2 复验)→ **a834cbc5**(仅 repro_q123.py +8/-2)→ **6afa31ac**(HEAD,仅 EVIDENCE_INDEX + 两份新 junit;src/tests 相对 bcc908ae 零改动,`git diff bcc908ae 6afa31ac -- stage2_6_1/src stage2_6_2/src stage2_6_1/tests stage2_6_2/tests` 为空)。

## 总判定:**PASS(内容验收;适用候选=6afa31ac)**

## (a) F2 残留关闭:**通过**
- a834cbc5 提交版 `repro_q123.py` 与 V2 已核验的参数化草稿**逐字节一致**(reviewer diff 实证 IDENTICAL):OUT 经 `REPRO_OUT` env 注入、标签经 `REPRO_CANDIDATE` env 注入(默认 "unlabeled(candidate injected via REPRO_CANDIDATE env)")。
- EVIDENCE_INDEX「不再硬编码」声明自 a834cbc5 起对提交版成真;V2 唯一 FAIL 项关闭。
- 单提交无其他改动(`git show a834cbc5 --stat`:1 文件,+8/-2)。

## (b) F1 修复在最终候选仍成立:**通过(身份确认)**
- src/tests 相对 bcc908ae 零改动(见上);coordinate.py 的 `except BaseException` 通用处理器、q123 钉测试 21 条与 V2 实证状态逐字节相同。
- V2 行为实证(探针 marker=true/账本 [start,interrupted]/配额路径不回归/重入拒绝/67 passed RC=0)对 6afa31ac 继续有效。

## (c) 新 junit 绑定 C9 字节:**通过**
| 项 | 261 v8 | 262 v5 |
|---|---|---|
| 统计(testsuite 头) | tests=2635, failures=0, errors=0, skipped=7(=2628 passed),time=2714.575s | tests=240, failures=0, errors=0, skipped=0,time=136.709s |
| 时间戳 | 2026-09-30T14:22:28+08:00(晚于 a834cbc5 提交 14:22:10) | 2026-09-30T15:07:11+08:00 |
| 相对 C8 期 v7/v4 | 2634→2635(+1);增量含 `test_f1_nonquota_failure_writes_interrupted_marker_and_ledger`(grep=1);q123_fixes 恰 21 条;无 262 classname(261 收集口径不变) | 240=240,无变化 |
| 字节 | 工作树=提交(b8cdd108…一致) | 工作树=提交(e3d12d6c…一致) |
- EVIDENCE_INDEX 追加「C9(最终候选)适用全量回归(V3 前置)」段,声明 v7/v4(C8 字节)被取代——与事实相符。
- 注:索引正文 2714.88s 为 pytest 墙钟口径,junit time 属性 2714.575s 为用例耗时合计,同源不矛盾。

## 观察(非阻塞,封包时对齐即可)
1. 索引新增段标题写「最终候选 a834cbc5」,Main 声明适用候选=6afa31ac(仅追加证据工件,代码字节相同)。封包 RETURN/manifest 请统一以 6afa31ac 为最终候选号,避免双候选号歧义。
2. `REPRO_Q123_C9.json` 标签保持「F1 fix pending commit; deploy synced」——如实(生成时点真实);按 Main 计划在 RETURN 说明中标注候选映射即可。
3. 索引主标题仍为「证据索引 — C8=bd6ed858」,后续段落已覆盖 C9/F1/F2;属历史沿革命名,封包目录可加一行指向说明(可选)。

## 复验运行记录
- R1 `git log -4` / `git show a834cbc5 --stat` / 双 `git diff --name-only`:链与范围与声称一致。
- R2 提交版 repro_q123.py vs V2 草稿:逐字节一致。
- R3 EVIDENCE_INDEX@6afa31ac 全文复读:参数化声明、勘误、F1/F2、C9 全量回归段均在且与工件相符。
- R4 两份 junit:头部统计/时间戳/F1 用例增量/字节三方核对(§表)。
- 零新增原生(维持 2/2)、零 fit、零 optimizer;本轮未运行任何生成路径。

## 结论
- **最终内容 PASS,适用候选=6afa31ac**。Q1/Q2/Q3 修复主体(V1 实证)、F1(V2 实证)、F2 残留与封包前置(本轮实证)全部关闭。
- 后续:Main 按此封包;reviewer 从最终 ZIP 新目录冷读并签包外 `REVIEWER_FINAL_RECEIPT.md`;最终 CLOSED 由 ChatGPT 独立终验。冷读时将核对:ZIP 成员与 SHA256SUMS、本报告引用的全部工件(PREFIX_C7/C9 两份复现 JSON、v8/v5 junit、E01 复算、E02 链 rc、REVIEWER_ADDENDUM 原文)。
