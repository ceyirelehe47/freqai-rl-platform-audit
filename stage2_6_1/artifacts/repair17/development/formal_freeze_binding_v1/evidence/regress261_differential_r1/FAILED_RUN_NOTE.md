# 并发双跑失败记录(保留原件)

bg_16/bg_17 两个后台作业在同一秒启动同一脚本,同时向 diff_v1_d(现
diff_v1_d_failed_concurrent)写入:r21 的 out-dir 非空守卫在并发建目录
竞态下未拦住,两 run 交错(stdout/audit tmp 互踩:audit_execution_5.json.tmp
FileNotFoundError 即竞态症状),aggregates 166/3F/1E 与 178/16F 均不可信。
两次原始输出与 record(c9e0c8d4…/23e96dd6…)全量保留于本目录;不作为
候选证据使用。根因=主 Agent 重复启动同一脚本(首次 bg_16 在脚本落盘前
发起,补写脚本后又发起 bg_17,前者实际读到文件并运行)。修复:扩展 D
依赖面(report/r20_design_calc_v4.py、artifacts/route_c_stage2_6_1_repair10/
r10_design_plan.json、user_data/strategies/RouteCStrategy.py,均按包位置
parents[2] 解析的静态输入,字节拷贝自 P)后在 diff_v1_d2 单跑重采。
