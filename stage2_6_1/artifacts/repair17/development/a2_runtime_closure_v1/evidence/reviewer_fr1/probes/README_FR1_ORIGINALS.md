# FR1 reviewer 探针原件归档(上游 R2 REVIEW §5 要求)

来源目录(本机临时,已按上游要求收编不可变仓库路径):
/home/cryptorl/tmp_fr1_review/(2026-10-10 FR1 内容验收运行现场)

- fr1_probe_driver.py:FR1 主探针驱动(vendor/历史/分支/入口断言)。
- residual_probe.py:残余离差探针(删除 r13_iteration_aborted.json /
  cue_event_trace.jsonl 后 preflight 仍 ok 的两反例——上游 R2 FAIL
  的直接依据)。
- preflight_rerun_P3.json / threeway_sample.json:真实 P3/PIN 活体
  复跑与三方抽样结果。
- outputs/fr1_probe_results.json:REVIEW 报告引用的主结果集。
- outputs/residual_probe.json:残余反例结果。
- outputs/zip_integrity.json:FR1 冷读完整性输出。
- outputs/r11b_probe_binding_out.json:隔离域 binder 输出件样例。
- outputs/dom_approval.json / dom_prereg.json:入口探针域配置件。
- 现场缺失如实说明:入口子进程完整 stdout/stderr 未逐条落盘
  (结论记录于 REVIEW_REPORT_FR1.md 正文与 fr1_probe_results.json
  的 entry 断言块);r13b_*/r11b_* 其余 fixture 克隆目录属临时
  环境,按上游"不复制整个临时环境"边界未收编。
