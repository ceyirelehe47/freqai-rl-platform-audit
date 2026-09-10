# 勘误（验收 subagent ACCEPT-WITH-NOTES 三处 NOTES 的如实修正）

本勘误只修正文档表述与说明证据缺口；不修改、不补造任何原始证据。

1. **归档文件计数**：FINAL_REPORT §6 所称"875 文件"应为 **881**（380 个
   `__pycache__/*.pyc` + 501 个非 pyc；501 全部入库，380 由 .gitignore
   排除）。归档组装脚本的 `find | wc -l` 计数时点早于 task_pack/extracted
   补齐，造成 6 个文件的差。

2. **局部测试覆盖表述**：FINAL_REPORT §3 所称"A01-A22 覆盖"不准确。
   24 个用例实际覆盖 A01–A14、A16–A22；**缺 A15（canonical/legacy 区别）
   合成用例**。A15 的真实 canonical 等价验证本应发生在主实验
   （任务书 §6.4），因主实验首请求 fatal 未到达；该缺口与主实验失败
   一并留给下一轮。

3. **隔离顶层 stdout 未归档**：隔离脚本顶层的 `case1_rc=2 / case2_rc=2 /
   case3_rc=2`、`probe_*_exists_before/after` 与原根 hash 回显输出仅在
   会话 stdout 中出现，未保存为文件，**不可事后补造**。rc=2 数值可由
   以下原件间接佐证：`pipeline.py` verify 异常路径输出
   `invocation_failed` JSON 并 `return 2`，三个 case 的 `.err` 文件恰为
   该输出；探针文件在归档前后均存在（本勘误撰写时复核仍在）。下一轮
   隔离脚本应将顶层 stdout 一并落盘。

验收结论原文与核对细节见会话记录；本勘误随交付提交入库。
