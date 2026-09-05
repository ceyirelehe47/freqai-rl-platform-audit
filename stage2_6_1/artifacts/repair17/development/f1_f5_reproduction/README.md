# development/f1_f5_reproduction — F1–F5 真实模块反例

性质：**development**（R17 实现前缺陷对照;全部探针使用隔离临时
state root 与探针专用 namespace,零正式/holdout/final 数据访问）。

| 缺陷 | 证据文件 | 类型 | 结果 |
|---|---|---|---|
| F1 全链所有权缺失 | `f1_f4_f5_static_counterexamples.json` | 静态+已发布 journal 事实 | 成立:launcher 无会话;journal 仅 2 事件无 session_*;会话嵌套于 qualify 单步;2 个 pid 写 journal |
| F2 执行者身份未闭合 | `f2_executor_identity_counterexample.json` | 行为(真实 fork/spawn) | 成立:fork 子进程 owns/verify/release 全通过;spawn 凭复制 env token 通过(bearer) |
| F3 journal 拒绝污染/无串行/缺迁移校验 | `f3_journal_pollution_counterexample.json` | 行为(多进程 barrier) | 成立:拒绝写入权威 journal;并发 append 真实产生重复 seq([1,1,1,1,5,5] 等);parser 接受孤立 grant_issued 与 exposure 前 terminal;重复 seq 令 owner fail closed |
| F4 组包路径缺陷 | `f1_f4_f5_static_counterexamples.json` | 静态(d2ee974 blob 比对) | 成立:组包目录少一层 artifacts/;`|| true` 静默;已提交 raw_logs 缺逐步日志(执行机原件已由 ../historical_recovered 找回) |
| F5 rehearsal 未穿外层入口 | `f1_f4_f5_static_counterexamples.json` | 静态 | 成立:rehearsal 由 python -m 驱动;R16 无 r16_rt_rehearsal.sh(R13-R15 均有);head_at_rehearsal≠Commit A(仅记录,不断定 A′) |

被测模块:`rl_curriculum.curriculum261_r16_execgov@d2ee974`
（探针源脚本在仓库根 `.r17_wp0_inputs/`,Commit A 时随冻结清单收录）。

R17 修复后,同一反例集合将在 r17 模块上复跑（T 矩阵要求),预期
全部反例转为拒绝。
