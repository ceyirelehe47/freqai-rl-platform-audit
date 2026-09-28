# eng_run_rcs.txt 补记说明(reviewer P3;报告层修正,不重跑)

独立 reviewer 内容验收(REVIEWER_CONTENT_REPORT.md)指出:runner 末尾
的 rcs 汇总只写 6 项 rc=0,漏记第 3b 步 G01 formal 拒绝的 rc=2。

事实与证据:

- 实际运行(2026-09-29,配额 replay#1/smoke#1)第 3b 步输出
  `rc_formal_reject(expect 2)=2`(运行时 stdout,见主 Agent 会话记录);
- 结构化拒绝原件完整存在:
  `eng_input_lock_formal_reject.json`(pass=false;problems 含
  "授权 scope = 'engineering' != 要求 'formal'" 与
  "formal 装载要求已注册的正式 admission 锚(注册表当前为空…)"两条,
  覆盖 G01 的两个目标分支);
- 本文件不改动任何运行产物字节;runner 脚本已修正为记录全部 7 项
  rc(commit 见证据补充提交),供未来重放使用。

完整 rc 清单(补记):fixture_v1=0 fixture_v2=0 input_lock=0 route=0
**formal_reject=2(预期拒绝)** eng_run=0 cold_read=0。
