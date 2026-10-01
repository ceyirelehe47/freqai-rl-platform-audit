# R8 运行标记重建说明
qprod_r8_r21_regress.sh 首版 EVD 误指 R6 轮目录(reviewer P3),R8 运行标记
(CANDIDATE.txt/r21_run.stdout.txt)落在了 repair_round6_notclosed/evidence/
regress_v6/ 并覆盖 tracked C17b 历史字节;处置时两文件被 git checkout 还原,
R8 标记按会话工具回执逐字节重建于本(R8)目录。run 本体原件
full_regression_v6_c18/(record f9e44621, 13 文件)未被触碰,已迁至本目录。
runner 脚本 EVD 已修正指向 R8 目录。
