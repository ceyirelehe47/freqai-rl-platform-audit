# tau_official_prep(2026-10-16,PREPARED_NOT_RUN)

## 唯一正式入口
launch_official.sh <attempt_root> <label> official <PY> <A_REPORT> <ANALYSIS_V2> <NEW_OUT>
- attempt 目录最先独占创建(拒存在 96);snapshot/ 固化 launcher/inner/τ/小测
  **完整源码副本**+sha256.manifest+argv+launcher 自身 SHA;
- 启动**保存的** inner 快照;τ/小测全用快照;真实 rc 落 rc.txt 同码退出;
- stage1=小测(快照 pytest),非零即止;stage2=同 Linux PY+快照 τ+
  A_REPORT+ANALYSIS_V2+独占 NEW_OUT,前缀 timeout 10 + time -v。
- 资源判终态:wall=外部硬限(timeout);CPU/RSS=事后内部检查+外部记录
  (无 OS 硬限,如实标注);rc 表:41 wall/42 cpu/43 rss/44 timeout 杀/
  45 资源解析失败(fail-closed)/98 解析错/95 NEW_OUT 已存在。

## 桩验证(不执行真实 stage2 τ;官方形状含 timeout+time 前缀)
v_syntax rc=2(语法错真实 rc,快照已存,计算 marker 无)·v_ok rc=0
(SCIENCE_OK+计算 marker 在)·v_gate rc=4(stage2 未启,marker 无)·
v_sci rc=9 透传·v_parse rc=98(双分隔符 PARSE_ERROR)·v_hang2 rc=44
(外部墙杀,resources 注明被杀)。旧 0/4/7 证据保留于 outer_v2 包。

## tau_sensitivity.py v2(生产终版)
report/rp 尽早初始化;输入 SHA 核验并写入报告;初次主报告写后
budget_final+after_initial_main_save,元数据重写后再查;通用 except
把已写主报告权威改 failed 保留 roots/pairs;收尾预算再抛错记
measurement_error 保留原错;主报告/FAIL_STATE/marker 各自
best-effort;最终 raise 原错。生产钉 SHA 不变;测试仅替换
verify_inputs。

## 测试(4 passed TAU2_TEST_RC=0)
两根不同 ε 确定值;生产 run 真调用(8 根/41 点/8 不同 proxy 手写
JSON;断言装配/来源(inputs.verified/budget_final/measurement_point)
/DONE);写后一般故障(主报告 failed+roots/pairs+FAILED+无 DONE);
收尾预算再故障(measurement_error+原错)。

## 弃用与备注
- 旧 outer(attempt_run_v2/gated_sequence_v2)被本包取代:其捕获
  仅 SHA 无源码、解析在捕获前——保留为历史证据不再使用。
- 旧 tau 包清单列 stub_ok/fail 但**其源码未入该包**——如实备注,
  不重建。
- 真实敏感性/A/B/DP/训练:零运行;course_gate=not_frozen。
