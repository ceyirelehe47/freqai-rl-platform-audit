# R17 诊断会话开场现场记录：E 盘掉线（阶段 A3 现象）

## 现象
- 本轮诊断会话开始（2026-09-06，接手任务书《R17 开发阻塞定位与最小修复》）后，
  首批 Bash 工具调用全部失败：`spawn C:\Program Files\Git\bin\bash.exe ENOENT`。
- 与中期报告记录的宿主 shell 故障同款（该次数分钟后自行恢复）。

## 机制推断（本轮探测证据）
- Read 探测 `C:\Program Files\Git\bin\bash.exe` → 报"binary file"（文件存在，
  Git 安装完好）。
- Read 探测 `E:\trading\freqai-rl-audit\stage2_6_1\report\route_c_stage2_6_1_repair17_interim_status.md`
  与 `E:\trading\freqai-rl-audit\.git\HEAD` → 均"不存在"（E 盘卷不可见，
  非单文件缺失）。
- Read 探测 `F:\WSL\CryptoRL-Ubuntu-24.04\ext4.vhdx` → 存在（F 盘在线）。

结论（待 shell 恢复后用系统事件核实，当前为探测级）：
工具进程以 `E:\trading` 为 cwd spawn bash.exe；E 卷不可用使 CreateProcess
以 ENOENT 类错误失败。即 **bash.exe 本体无恙，ENOENT 的直接原因是 cwd
所在卷掉线**——这为上次"宿主 shell 故障 + E: 瞬断"提供了机制级解释，
但仍需 Windows 事件日志核实掉线原因（电源/USB 链路/盘故障）。

## 当前不可访问
- 发布仓库 `E:\trading\freqai-rl-audit`（git 现场/工作树核查被迫延迟）
- `E:\trading\.r17_wp0_inputs`（WP0 工具脚本暂存区）

## 在线资源
- F 盘：WSL VHDX（CryptoRL-Ubuntu-24.04）完好
- C 盘：Git 安装、ZCode 环境

## 处置
- 本记录写于 F 盘（任务书 §B2：Windows 侧证据不放在易掉线的 E 盘；
  注意 F 与 VHDX 同属 USB 外置故障域）。
- 不创建空目录冒充 E 盘仓库（§A3）。
- 周期重试 shell；若 E 盘恢复，先用系统事件日志核实掉线时刻与原因，
  再继续阶段 A。
- 若持续不恢复：构成 BLOCKED 项（发布仓库物理不可达，需用户重新连接
  E 盘）；WSL 侧工作同样被阻（wsl.exe 调用依赖 shell 工具）。
