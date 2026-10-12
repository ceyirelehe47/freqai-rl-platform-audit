# 回归尝试史（E6 全过程如实披露）

终版证据 = `/home/cryptorl/regress_posctl_final_v1`（绑定候选
8379d33b，261 全量 3084/0F/0E/7S rc=0）。到达该结果的全部尝试：

| # | 时间(本地) | 结果 | 原因/处置 |
|---|---|---|---|
| 1 | 06:22 | SIGTERM(存储 CRITICAL 311G) | 全量套件 tmp ~270G 叠加 /tmp 残留 225G 破 300G 上限；清 /tmp |
| 2 | 06:49 | r21 秒退 rc=1 | out-dir 残留首轮工件（git-bash rm 对 WSL 路径无效）；WSL 内清理 |
| 3 | 06:52 | r21 秒退 rc=1 | #2 的外层脚本幸存并重建 out-dir 文件；确认杀全部包装进程 |
| 4 | 06:58 | SIGTERM(304G) | 干净 /tmp 后套件自身 tmp 仍 ~270G+28G 基线；改 TMPDIR→/mnt/f |
| 5 | 07:35 | r21 拒绝 | PYTEST_* 环境污染守卫拒 PYTEST_ADDOPTS（正确语义）；改符号链接 |
| 6 | 07:35 | 1645 errors | pytest 拒符号链接 tmpdir（安全检查）；改回真实 /tmp+清缓存 |
| 7 | 08:03 | r21 拒绝 | TMPDIR→9P 破坏 pytest capture（TemporaryFile 语义）；回根卷方案 |
| 8 | 08:22 | SIGTERM(313G) | 清 pip/conda 缓存 4.2G 后仍不够（实测 tmp 需求 285G+）；改 r21 原生 --shard |
| 9 | 08:4x | 手动终止 | 分片发现单文件 test_curriculum261_qaf_v2_reviewclosure.py 每测试建 ~29G 假仓夹具（全树 11G 比例放大），单分片 269G；**改用 A9 同构精简树** |
| 10 | 09:0x | 17 非通过(13F+4E) | 精简树完成跑；分析＝我的 F2 链测试在 pytest 进程内留下 ~391 后台线程 → 后续 r17 Supervisor 测试 unshielded_threads→rc7（同进程夹具 dump 证实）；隔离复现 F2+冷读=4E |
| 11 | 10:5x | 预检拒绝 | 修复(#1c0e0194 子进程隔离)后精简树残留 .pytest_cache；清 |
| 12 | 11:0x | 预检拒绝 | #11 的 posctl 段（未加 no:cacheprovider）重建 .pytest_cache；脚本补 -p no:cacheprovider |
| 13 | 11:1x | 预检拒绝 | .pytest_cache 在 tests/route_c_stage2_6_1 **内部**——F2 子进程 helper cwd 指向测试目录；修(#8379d33b) |
| 14 | 11:2x | 1F | 精简树缺 r17_win_sampler*.ps1(3 个)；补齐 |
| 15(终) | 11:3x | **3084/0F/0E/7S rc=0** | 全绿；posctl 70/70；262 240/3F(既有) |

存储保护从未放宽；PYTEST_* 污染守卫、部署面只读预检、监督 SIGTERM
均为正确 fail-closed 语义，本次只是适配执行环境。A9 精简树自身
(crypto_rl_cue_ci) 全程只读未动；本轮精简树为其副本
(crypto_rl_posctl_ci)+候选文件同步+缺件补齐。
