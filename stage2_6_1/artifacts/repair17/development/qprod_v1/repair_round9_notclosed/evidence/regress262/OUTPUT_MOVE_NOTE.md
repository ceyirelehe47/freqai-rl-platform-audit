# R9 262 输出迁移说明
本轮 262 复用 R6 轮脚本时 sed 替换未命中(源脚本变量名仍为
regress262_v11_c17/repair_round6_notclosed),R9 运行产物
(junit/meta/stdout/stderr,240 passed RC=0,C19 字节)先落在 R6 轮
目录并覆盖 tracked 同名文件;已整组迁移至本(R9)目录并重命名为
regress262_v14_c19*(内容字节未改,仅文件名与位置),R6 轮目录以
git checkout 还原为提交历史字节。junit 内容为 C19 实跑原件。
