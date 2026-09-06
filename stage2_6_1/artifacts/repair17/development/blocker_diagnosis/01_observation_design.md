# R17 阶段 B 观测设计（任务书 §4 B1-B4 落地方案）

状态：设计稿（E 盘掉线期间先行起草；实施在 shell 恢复后，按本设计落地）
写入位置：F:\r17_diagnosis\（Windows 侧）；WSL 内 run 目录（guest 侧）

## 1. 双侧采样器

### Windows 侧（PowerShell，独立进程，不依赖 WSL）
- 脚本：`F:\r17_diagnosis\win_sampler.ps1`，输出 `F:\r17_diagnosis\windows_samples.jsonl`
- 频率：每 5s 一条；低频字段（进程明细）每 30s
- 每条记录（UTC 时间戳 Get-Date -AsUTC）：
  - `os`: FreePhysicalMemory/TotalVisibleMemorySize（KB）、
    TotalVirtualMemorySize/FreeVirtualMemory（KB）→ commit 上限/已用
  - `vm`: vmmem/vmmemWSL/WslService 进程存在性 + WorkingSet64/PrivateMemorySize64
  - `heavy`: 目标重任务进程（python/wsl/bash 相关）按 Name 聚合的
    WorkingSet 总量（低频，带实例数）
  - `vols`: C/E/F 盘符可见性（Test-Path 根目录，bool）
  - `sampler_self`: 采样器自身 CPU/内存（记录开销）
- 自身开销约束：单次采样 < 200ms；不用 Get-Process 全表展开

### WSL/Linux 侧（bash 脚本，目标任务同 VM 内，独立于业务进程）
- 脚本：随 run 目录部署 `guest_sampler.sh`，输出 run 目录内
  `guest_samples.jsonl`
- 频率：每 5s；PSS/线程明细低频（每 60s，smaps_rollup）
- 每条记录（date -u +%Y-%m-%dT%H:%M:%SZ + 单调时钟）：
  - `meminfo`: MemTotal/MemAvailable/MemFree/AnonPages/Cached/SReclaimable/
    Dirty/Writeback/SwapTotal/SwapFree/SwapIn(out 累计)
  - `psi`(存在时): /proc/pressure/{memory,io} 的 avg10/avg60/full
  - `tasks`: 目标任务树（按 run 目录登记的 PID 集合 + 其子进程）：
    pid/ppid/stat(state)/etimes/rss_kb/threads/comm/cmdline 截断
  - `pss`(低频): 主要进程 /proc/<pid>/smaps_rollup 的 Pss/Private
  - 不可获取字段写 `"unavailable"`，不填 0
- 采样器不持有业务锁/token/pipe；只读 /proc 与自身输出文件

### 协调者/worker 进度（B1 第 4 行）
- 复用现有 r17 chain journal（append-only，单写者）+ 各步骤 raw log
  的 mtime/size 增长——不新增业务侧写入者
- 需要阶段级进度时（D2）：design 侧独立 sidecar（诊断用，预登记，
  不进权威 journal）

## 2. B3 约束的落地
- **不用 wsl.exe 周期探测 VM 存活**（探测=客户端连接，会改变 idle
  判定）。Windows 侧只看 vmmem/WslService 进程（宿主对象，不触碰
  guest）。
- VM idle 行为的验证用受控实验：低负载测试进程 + 已知启动方式，
  记录现有工具超时；不修改 .wslconfig（vmIdleTimeout 默认 60000ms
  已由官方文档确认，见 00 号记录）。
- 采样器不向业务 worker 继承任何句柄（独立进程树启动）。

## 3. B4 保护线（写进采样器与运行前置检查）
- 启动重任务前：Windows 可用物理内存 ≥ 8GiB 且 commit < 上限 95%
  且无旧重任务（采样器最近一条记录判定）。
- 运行中：Windows 可用 < 4GiB 连续 3 次，或 commit ≥ 95% 连续 3 次
  → 记录 `protection_stop` 事件 → 按任务级停止路径终止本次工程负载
  （只处理本次任务树）。
- WSL：MemAvailable < 2GiB 连续 3 次且 SwapFree 持续下降/PSI memory
  full avg10 上升 → 同上。
- I/O 错误 / 卷失联 / 关键证据写失败 / 300GB 上限 → 立即停止新增
  子进程，保留现场，标记"诊断保护中止"（≠统计 FAIL，≠历史 OOM 证明）。
- 不杀其他程序制造余量。

## 4. 时间与缺失
- 全部 UTC；进程内耗时用单调时钟；报告时钟偏差。
- 采样间隙/缺失区间显式记录；空白=缺测，不解释为 0。
- 日志体积预算：采样 JSONL 单文件 ≤ 50MB，超预算降频或结束（预声明，
  不静默删除失败证据）。

## 5. 已核实的配置事实（2026-09-06 官方文档）
- vmIdleTimeout 默认 60000ms（Windows 11+）。
- autoMemoryReclaim 默认 **dropCache**（立即回收缓存）——上轮从
  .wslconfig 删除该键 ≠ 禁用；当前生效行为仍是 dropCache。
- 配置变更需发行版完全停止后重启生效（8 秒规则）；核验生效值以
  wsl.exe --version + VM 内 /proc/meminfo MemTotal 为准。
