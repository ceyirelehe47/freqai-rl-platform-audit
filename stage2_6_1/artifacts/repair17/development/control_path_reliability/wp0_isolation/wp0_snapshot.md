# WP0 只读隔离快照（2026-09-07T00:28Z）

## 起点
- 接手 SHA = 0d53be6e8101f9ccb34f3eae205f3fc195b157dc（parent 45d073a），fetch 后无新提交，工作树 clean。
- 分支 route-c-stage2-6-1-repair17。boot_id=4da5bf99-96aa-40e3-808c-3630d9698335。

## 正式面（只读核验，无新增活动）
- 部署 state 根（~/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair17/state）：journal 5 行
  （REQ1 会话 freeze_sha=全零 → provenance-verify rc=2 PrerequisiteError → aborted → released，
  writer=chain_session_owner 全程）；aborted marker 227B 在场；rejected_requests/ 与
  pending_abort_requests/ 在场。全部 mtime = 2026-09-06T16:00-16:51Z（上轮 WP0 误触时刻），与上轮归档一致。
- r17_formal_requests/：6 个请求目录（18312/19556/20800/22112/35851/44919），与上轮报告 6 次请求一致。
- .r17_formal_admission.json 与 r17_admission_consumed.jsonl 均不存在 → 本轮无许可，正式入口全关。
- 结论：本轮开始时无新增正式写入/数据/许可/会话。

## 残留进程（B4 活证据，已处置并记录）
- WSL PID 402：/init interop 桥，绑定 run m07_154304_299 的 r17_win_sampler.ps1（-MaxSeconds 300）。
  已运行 08:54:30（远超 300s）。Windows 侧对应 powershell 已不存在（按 CommandLine 过滤核验）；
  桥 fd0=pipe:[71737]、1/2=/dev/null，父 /init 298 已孤儿化（ppid=1）。
- 机制：MaxSeconds 只约束 Windows 侧 powershell；powershell 退出后 WSL 侧 interop 桥悬挂，
  上轮 Supervisor 未在收尾时核验/回收该后代 → 父正常退出+后代残留 8h54m 的现成反例（B4）。
- 处置：身份可确认（fd/命令行绑定 m07 run，上轮测试自建任务），SIGTERM 402 → 已终止（(402 terminated)）。
  原始观察记录于本目录 raw_snapshot_*.txt。

## 资源
- /：919G 可用；/mnt/f：1.2T 可用（300GiB 计量口径远未触顶）。guest 内存 38G 可用。
- 存活 r17 监护/采样进程：处置后 (none)。
