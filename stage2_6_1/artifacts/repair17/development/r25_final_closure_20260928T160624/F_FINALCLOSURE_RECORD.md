# F 出口记录:登记异常必须拒绝(RouteC_R25_FinalClosure_TrainingReadiness_v1)

候选代码:7e9e5470889884bad296a2dbb4b3e55ca38bc151
(`stage2_6_1/runner/r25_worker_probe.py` 重写 + 
`stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r25_probe_registry.py` 重写)。
旧版身份:blob 21c74292…/sha256 29e985be…(=随包参考源码,逐字节一致,见 §0)。

## 0. 旧缺陷在本机 WSL 的重现(随包复现脚本,未改一字)

- 命令:`/usr/bin/python3 $PACK/evidence/reproduce_registry_boundary.py
  --source $PACK/reference_source/r25_worker_probe.py --out
  <全新目录>`(部署 conda Python 3.11.16 无 os.pidfd_open,故用系统
  Python 3.12.3;脚本仅标准库,未修改)。
- 输出:`work/r25_final_closure_20260928/repro_old_baseline/RESULT.json`,
  `result=BASELINE_DEFECTS_REPRODUCED`:
  - valid_live_control:checker rc=3 leaked_alive(正确对照);
  - permission_at_registration / not_found_at_registration /
    child_record_omitted:checker 全部 rc=0 clean(缺陷确认)。
- driver rc=0 = 旧缺陷按预期复现,不是任何新候选 PASS。

## 1. 修复行为合同(行为是合同,内部字段不是)

producer(`_write_registry`/`_confirm_identity`):
- 身份来源优先级:子/孙握手自报(子读 /proc/self 与自有孙 stat)
  → writer 对**同一已拥有 pid** 的有界直读(3 次×0.05s,只观测
  同一实例,失败事实进 .failed.json);两来源冲突即拒绝。
- 任何 root/child/grandchild 身份无法确认 → RegistrationError:
  不发布登记(原子写 tmp+os.replace,无半写)、自有句柄收尾、
  退出码 6、失败事实写 `<registry>.failed.json`(不可写则 stderr)。
- 已创建后代但握手不可用(grandchild 身份来源缺失)→ 拒绝,
  绝不发布缺记录登记;绝无 -1/布尔/占位身份。

consumer(`_check_registry`,format r25-worker-registry-v2):
- v1 一律 rc=4(历史缺陷格式;修复不靠换格式——见 §2 F03 同格式
  变异负例)。
- 结构与关联:created_roles 与 instances 角色多重集一致;pid 唯一;
  恰一 root 且 root_pid 相等;grandchild 蕴含 child;无后代声明须
  verified+非空 basis 且 created_roles=[root];已创建后代却带无
  后代声明=矛盾。
- 每实例身份:pid 严格正 int、start_ticks 严格 int 且 ≥1
  (布尔/浮点/缺值/负数/0 全拒,reason 指明身份字段)。
- 身份有效后才逐实例:dead_gone/zombie_unreaped/alive/
  pid_reused_old_dead(仅有效登记身份可获此解释)/unobservable。
- 退出码不变:0/2/3/4/5;新增工作者登记失败码 6。

## 2. 验收矩阵映射(全部真实执行,WSL 部署树)

| ID | 测试(28 项之一) | 结果 |
|---|---|---|
| F01 | TestRegistrationRefusalF01×4:root/descendant × PermissionError/FileNotFoundError,真实 main 控制流,注入边界=`_read_proc_stat`/握手载荷;rc=6、无登记文件、.failed.json 有因、子/孙收尾、不进长任务;另握手存活正例:直读故障下握手身份发布成功且真实可比 | 全过 |
| F02 | TestIdentityInvalidF02×2:活实例上 -1/True/False/1.5/0 与 pid 布尔/0/负/str;完整 CLI rc=4,reason 含身份字段,输出无 pid_reused | 全过 |
| F03 | TestMutatedCopyF03×6:orphan 真根退出+子/孙存活,同格式副本缺 child/grand/root、重复 child、roles 矛盾、root_pid 失联 → 全 rc=4;检查前后同实例存活,finally 身份匹配清理 | 全过 |
| F04 | TestNoDescendantsBasisF04×3:空/缺/空白 basis、无后代声明矛盾、缺 created_roles → rc=4;合法无后代正例=C01 sleep | 全过 |
| F05 | C02/C03 保留:根退子活/子退孙活 → rc=3 leaked_alive | 全过 |
| F06 | C05 模拟 PID 错配(有效身份)→ pid_reused_old_dead+clean+不发信号;TestZombieF06:僵尸 rc=2,checker 不回收,waitpid 收尾 | 全过 |
| F07 | TestWriteFailureF07:父路径被文件占据 → rc=6、不发布、不进长任务、stderr 含失败事实与 failed_facts_write_error、自有句柄收尾 | 全过 |
| A01 | 入口 42 项(binding/锚/plan 关联)零改动全过;C01–C05/C07 保留于 v2 夹具 | 全过 |

定向命令(部署树):
`/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -m pytest
tests/route_c_stage2_6_1/test_curriculum261_r25_probe_registry.py -q`
→ **28 passed**;同解释器 entry 测试 → **42 passed**。

## 3. I01 真实集成(监护)

run `20260928T160626_7004_367`(engineering,business_rc=0,
incidents=0):`r25_batch_launcher_v2.sh probe` + 新 probe:
- w1(burn+子/孙)worker rc=0,checker rc=0 clean;
- w2(burn 无子)worker rc=0,checker rc=0 clean;
- w3(sleep 短超时)worker 原始 rc=124 保留,checker rc=0 clean;
- 三份登记全 v2、ticks 实测正整数、子/孙身份源=handshake_self_report。
原件:`i01_probe/logs/`(registry/identity/heartbeat/check/binding
note + `logs.monitored_rc.txt`)与 run_supervision 全 required。

## 4. 未做与边界

- 不改 A 绑定入口/统计门槛/旧数据;不重跑旧 11 坐标;未跑任何
  正式链;rc=5 unobservable 分支保留代码路径(无法在不注入的完整
  CLI 中制造,与上轮相同缺口,如实说明)。
- 旧缺陷注入是测试观测边界,不证明历史 WSL run 实际泄漏;
  R19/历史终态不变。
