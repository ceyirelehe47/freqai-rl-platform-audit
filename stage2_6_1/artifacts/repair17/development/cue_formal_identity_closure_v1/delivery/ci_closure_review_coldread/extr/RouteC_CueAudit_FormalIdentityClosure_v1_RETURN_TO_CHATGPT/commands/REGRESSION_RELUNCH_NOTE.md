# 全量回归首次启动失败与重启记录(如实)

- 13:50:20Z 首次分离启动 run_full_regression.sh:FATAL 守卫拒绝——df / 已用 389GB ≥ 300GB 天花板(r17_entry_common.sh r17_check_storage_ceiling;口径 df -BK used)。
- 复核轨迹:约 13:58Z df 显示 131G;14:0xZ 显示 44G/45G。期间无本任务写入;ps 显示 WSL 发行版于 21:49–21:52(本地)重启(systemd/snapd/unattended-upgrades 启动时刻),389GB 为重启前瞬时占用,重启后消失,根因不可进一步观测(unattended-upgrade/前次会话残留候补;无证据指向本任务)。
- 当前 df / used≈44GB,低于天花板;无重型进程。按守卫语义(先清理后重试)重新启动回归;本记录保留首次拒绝原件(r21_launch.stderr.log 77B)。

## 补记(第 4 次运行被监护终止)

- 第 4 次启动(13:57:36Z 业务开始)在执行开始约 40 秒后(13:58:16Z)被 r17 监护策略主动 SIGTERM:stop_requested_reasons=[storage_ceiling: WSL 根卷已用 312.6GiB ≥ 上限 300GiB](监护 summary: run_supervision/runs/20261011T135732_4477_5775/summary.json,business rc=-15 SIG15,protector term 确认,无幸存者)。
- 与首次拒绝(389GB)同型:df 瞬态高占用后自行回落(44G 稳定,/ 分解: /var/tmp/rl-regression 21G 为 2026-09-01 旧轮遗留 scratch,非本轮产物,未动;其余无大件)。根因(宿主侧 VHDX/系统事件)在 WSL 内不可进一步观测,如实保留。
- 处置:按守卫语义等待占用回落后重启;残件目录归档为 /home/cryptorl/regress_cue_identity_v1_attempt4_killed_by_storage_guard;第 5 次启动 15:52:26Z,业务 15:54Z 起存活。

## 逐次台账(全量 261 回归启动沿革;补记至第 9 次)

| 次 | 启动(UTC) | 终态 | 记录位置 |
|---|---|---|---|
| L1 | 2026-10-11T13:50:20Z | 启动即拒(df 389GB≥300G 天花板;宿主瞬态,后自行回落) | first_launch_stderr.saved |
| L2 | 13:53:49Z | 拒启(out-dir 非空:L1 残留日志) | run_supervision 检查于入口前 |
| L3 | 13:55:40Z | 拒启(out-dir 非空:launcher 把启动日志重定向入 out-dir——脚本失误,修至目录外) | 同上 |
| L4 | 13:57:36Z | 40s 后监护 SIGTERM(312.6GiB≥300G) | runs/20261011T135732_4477_5775/summary.json |
| L5 | 15:52:33Z | 17min 后监护 SIGTERM(303.6GiB) | runs/20261011T155230_8355_408/summary.json |
| L6 | 16:56:34Z | 手动停止(经 kill→监护记录 SIG15;目的=插桩定位写入者) | runs/20261011T165639_2173_412/ |
| L7 | 18:33:37Z | 18min 后监护 SIGTERM(315.0GiB;磁盘观察器定位 /tmp/pytest-of-cryptorl RD 夹具×29G) | runs/20261011T183337_8108_467/summary.json |
| L8 | 19:16:43Z | 跑完 rc=1:3049 collected/102F+37E/10S,全部=精简树环境缺件(树后来补齐) | regress_cue_identity_v1_attempt8_envfail_lean_tree_incomplete/{junit.xml,summary.json,regression_evidence_v3_record.json} |
| L9 | 20:03:44Z | 运行中(补齐树 2.1G) | runs/20261011T200344_*/ + /home/cryptorl/regress_cue_identity_v1/ |

合计:存储天花板 SIGTERM×3(L4/L5/L7)、手动停止×1(L6)、launcher 失误拒启×2(L2/L3)、守卫启动拒绝×1(L1)、环境缺件完成×1(L8)、进行中×1(L9)。
环境修复台账:21G /var/tmp/rl-regression(2026-09-01 遗留)tar 归档 F 盘 local/rl-regression-sept01.tar(sha256 c16654d0…)后移除;主部署树 crypto_rl 的 27G .regression_state 为 RD 夹具膨胀根因,未删(历史数据),以新建 crypto_rl_cue_ci 精简投影树规避(=crypto_rl 除 .regression_state/__pycache__ 外全量+仓库候选代码);L8 后补齐 artifacts 全部子目录(增量拷贝目录级跳过失误修正)。
