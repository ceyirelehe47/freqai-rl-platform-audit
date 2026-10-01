# E 盘桥接说明(2026-10-01 R6 轮)
- E: 物理盘已不可用(vol E: 找不到路径;/mnt/e 为 08-25 空 drvfs 残根)。
- 仓库历史冻结面(29 文件硬编码 E:/trading/freqai-rl-audit + 测试 fallback
  /mnt/e/trading/...)因此在 c16 r21 首跑(20261001_202247)出现 9 个环境性
  失败(r11/r12 R10 marker、r14/r15 allowlist tmp、r15 governance root
  NoneType、r15 workflow runner 路径),失败原件保留于
  full_regression_v6_c16_envfail_e_drive/(record 3a5976e1, rc=4)。
- 环境修复(不改任何代码/冻结测试面): /mnt/e/trading/freqai-rl-audit ->
  符号链接 /mnt/f/trading/freqai-rl-audit(git 同源仓库, remote 一致)。
  桥接后 9 失败面单测复跑 120 passed/1 skipped 全绿。
- 桥接后全量重跑即 full_regression_v6_c16/(正式 C16 record)。
