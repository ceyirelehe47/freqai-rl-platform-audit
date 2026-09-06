# R17 阶段 C：历史中断归因框架（任务书 §5）

状态：框架+已知证据（来自 R17 中期报告与记忆）；"待核实"列在 E 盘
恢复后用原始日志/系统事件填充。不制造未发生的细节。

## 1. 历史尝试索引（待 E 盘恢复后重建）

来源（预期位置）：
- WSL: ~/projects/crypto_rl/ 下 r16/r17 各 run 的日志目录
  （rt_runs/artifacts/logs 的实际布局以真实文件系统为准）
- E: E:\\trading\\freqai-rl-audit\\stage2_6_1\\artifacts\\repair17\\
  （development/historical_recovered/wp0…）
- F: F:\\r17_diagnosis\\（本次）
- 中期报告称"22 次工程 rehearsal 尝试"——逐次索引以真实文件为准，
  无法恢复的记录为缺失，不补造。

## 2. 现象分类表（按任务书 §5 表格逐项判定）

| # | 现象 | 已有证据 | 归因方向 | 四类结论（当前） |
|---|---|---|---|---|
| C-1 | E 盘时代 WSL 崩溃 3 次（15-17 轮，design/calibrate 高 IO 段） | 中期报告：Windows 事件日志 disk Id=157 ×4（E:）| USB 机械盘高负载掉线 | CONFIRMED（磁盘事件+时刻对应，待恢复后引用原始事件 ID） |
| C-2 | Windows 可用物理内存 0.1GB 观测（48GB 配额时代） | 中期报告一次观测 | 配额 48/64GB 过度分配 + 宿主负载 | MITIGATED（已调 40GB；未做进程级峰值归因——本轮 B 观测补） |
| C-3 | 第 19/20 轮"崩溃"：nohup 脱离进程被杀 | 中期报告：真相=VM idle timeout（60s 无客户端自动关闭）；run_in_background 保活后未再复现 | vmIdleTimeout 默认 60000ms（官方文档已核实）关闭 VM | MITIGATED→需本轮 D03 受控实验补证（工具退出 vs VM 退出的区分证据） |
| C-4 | 宿主 bash.exe ENOENT（上轮一次 + 本轮开场持续） | 上轮自行恢复；本轮探测：bash.exe 存在、E 卷不可见、F 在线 | cwd=E:\\trading 的进程 spawn 因 E 卷失效失败 | CONFIRMED（本轮探测级证据：ENOENT 与 E 卷缺失同现；待系统事件佐证掉线原因） |
| C-5 | rt rehearsal 22 次未走通（最好到 design 进行中） | 中期报告 | 混合：C-1/C-3 环境中断 + 工程迭代缺陷（参数名/状态机时序/产物根/别名）| 工程缺陷部分 CONFIRMED（逐项已修复）；环境中断部分同 C-1/C-3 |

## 3. 关键澄清（任务书 §5"不成立的推断"自查）
- C-1 不能解释 F 盘时代的任何失败（迁移后现象，单独归类）。
- C-3 的"run_in_background 后未再复现"≠历史所有退出都由 idle timeout
  引起；本轮用 D03 受控实验给出区分证据。
- C-4 的 ENOENT ≠ 硬盘掉线本身，是"cwd 卷失效 → CreateProcess 失败"
  的机制链；掉线原因（电源/USB 链路/盘固件）待 Windows 事件核实。
- autoMemoryReclaim：上轮删除配置键 ≠ 禁用；官方默认 dropCache
  （立即回收缓存）仍生效。观测解读 vmmem 波动时须计入。

## 4. 本轮待归因的新现象
- N-1: 本轮开场 E 盘不可达（12:00-12:35Z 窗口）。
  **CONFIRMED（事件日志证据）**：System 日志 disk Id=157 "磁盘 5
  已被意外移除" 于 2026-09-06 07:56:27/10:19:54/11:44:03/12:00:14Z
  共 4 次；Ntfs Id=98 卷 E: 恢复健康于 12:35:36Z。用户确认移除/
  重接为手动操作。ENOENT 机制链：cwd=E:\trading 卷离线 →
  CreateProcess(lpCurrentDirectory 无效) 失败 → 工具 spawn 报
  ENOENT（bash.exe 本体在 C 盘完好，探测证实）。上轮"宿主 shell
  短暂 ENOENT+E: 瞬断自行恢复"（C-4 历史条目）同机制。
  附注：event 157 无法区分"用户主动拔出"与"链路意外掉线"，
  今日 4 次中至少最后一次为用户操作；上轮 E 盘时代 15-17 轮的
  disk 157 事件（迁移前已取证 ×4）当时无手动拔盘，仍维持
  "USB 机械盘高负载掉线"归因（C-1）不变。

## 5. 四类结论汇总（将随证据更新进主报告）
按任务书：CONFIRMED / MITIGATED / NOT_REPRODUCED / UNRESOLVED-BLOCKED。
