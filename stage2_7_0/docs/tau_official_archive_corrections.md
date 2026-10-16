# ARCHIVE_CORRECTIONS + 终版说明(2026-10-16)

## 归档更正(如实)
- 上版摘要称"桩已归档"不准确:**六个新桩与语法错桩源码未入包**
  (仅日志在)——本包补齐全部 st_*.sh 现存原件;snapshot 仍只含
  官方四文件(launcher/inner/τ/小测)——**桩不进 snapshot 属设计**
  (桩是验证输入,非被验对象),非遗漏。
- 旧 hang(v_hang)**实录 rc=45**(fail-closed 资源解析失败),
  上版消息摘要"43"有误——以 attempt 目录 rc.txt=45 为准。
- 证据映射:旧矩阵 v_syntax/ok/gate/sci/parse + 旧 hang 使用旧
  inner(703bf0d7…);hang2 使用当时终版。**本包 stub_attempts_final2/
  全部条目(含 syntax/gate/parse 重跑)对应本包终版 inner/launcher**
  (SHA 见 tau_final_sha.txt);旧目录与日志全部保留。

## 终版桩矩阵(stub_attempts_final2,全部真实 rc 落 rc.txt)
| 桩 | rc | 说明 |
|---|---|---|
| f_ok | 0 | SCIENCE_OK+计算 marker 在 |
| f_sci | 9 | 科学 rc 透传 |
| f_gate | 4 | 小测失败中止,计算 marker 无 |
| f_syntax | 2 | 语法错真实 rc,快照已存 |
| f_parse | 98 | 双分隔符 PARSE_ERROR |
| f_hang | 44 | TERM@10s(time 无统计,resources 注明) |
| f_kill | 44 | 同上:**桩实际仍 124**(timeout TERMs GNU time 本体,
  trap-TERM 子脚本未及生效)——**137/SIGKILL 分支未获桩证**,
  代码路径存在但无证据,如实声明 |
| d2_res_missing/dup/nan/bad | 45 | 缺项/重复/NaN/非数字 fail-closed |
| d2_res_hours | 41 | "1:00:05"→wall 3605s 超限(含小时解析验证) |

## 三组落实摘要
1. launcher:目录创建后**立即 exec 捕获+EXIT trap(rc/UTC)**,一切
   检查/失败(参数/NEW_OUT/cp/hash)在捕获内 fail-closed(FAIL_
   REASON.txt);目录创建失败=无法留盘如实注明。
2. inner:time -v 严格解析(grep -cF 恰一次+逐字段数值正则;缺/
   重/NaN/非数字→45,禁止当 0);wall 完整 h:mm:ss;RSS KiB
   131072;timeout -k 1 10=TERM@10s+KILL 宽限,124/137 在解析前
   判定→44(137 仅陈述被杀);外部终态超限不因 rc=0 豁免(41/42/43)。
3. τ:空 roots/pairs 创建即挂 report+增量更新(中途失败 partial
   由 FAIL_STATE 权威保留,测试实证);初次写失败但文件存在→尽力
   改 failed;except 保留首个 fail_reason(setdefault);5 小测
   TAU3_TEST_RC=0(新增中途失败 fixture)。
