# FR2 reviewer 探针原件归档(FiniteRepair R2 独立验收,2026-10-11)

来源目录(本机工作区,按主 Agent 收编指令移入不可变仓库路径):
- /f/trading/local/fr2_review/(脚本与 JSON 输出)
- /home/cryptorl/tmp_fr2_review/fr2_dom/(隔离 fixture 克隆域——按"不复制整个临时环境"边界未收编;域构造逻辑完整内联于 fr2_review_probe.py,可原样重建)

## 脚本(probes/)

- fr2_review_probe.py:隔离域驱动 + 13 场景主探针。probe 0=真实根(REAL PIN/P3)unpatched preflight(与 evidence/runtime_verify/preflight_P3.json 对拍);随后 --shared 克隆真实 PIN@sparse(HEAD==A、分支 route-c-stage2-6-1-repair17)+候选字节 project+vendor@VENDOR_PIN 构成隔离域,monkeypatch guard.R17_PIN_EXPECTED_ROOT 指向克隆(与 P3 定向套件同法),逐场景单条件突变 → runtime_dependency_preflight → 断言 bind_states/单标记/HEAD==A。
- fr2_extra_scenarios.py:上游 17 场景矩阵余下行补测(r13 result 文件缺失、r13 abort marker 字节改变、r11 abort marker 缺失)+ 恢复正例。
- fr2_entry_child.py + fr2_entry_probe.py:入口级历史突变注入实验。child 在子进程内、runpy 前 monkeypatch 同一 PIN 常量(等价 pytest monkeypatch 测试夹具技术;不改任何被审文件;生产 env 白名单不变),再以 __main__ 运行真实 stage2_6_1_runner/qprod_formal_authority.py issue-permit;parent 构造 deploy 脚手架(install_to_target+qprod_deploy_config.json+authority init),执行三例:合法域穿全部前置至批准原件边界截停 / r13 abort 缺失(隔离域内删除)注入后实跑 / vendor 缺失同 gate 对照。
- fr2_wrapper_probe.py:binder wrapper 语义行为探针(override dep.R17_RELEASE_PIN_ROOT 指向隔离域克隆):r11 hard-missing 写前抛原消息 / r11 trace 缺失先写 binding.json 再抛 fail-closed / r13 损坏 JSON 原 JSONDecodeError 直传零写 / r13 有效篡改先写再抛 / 健康域写盘+pass=true。

## 运行命令(WSL, /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python;export PYTHONDONTWRITEBYTECODE=1)

- 定向套件:cd /home/cryptorl/projects/crypto_rl_qaf_v3 && python -m pytest tests/route_c_stage2_6_1/test_curriculum261_qaf_v3_finite_repair_r1.py tests/route_c_stage2_6_1/test_curriculum261_qaf_v3_finite_repair_r2.py -q -p no:cacheprovider → outputs/pytest_r1r2.log(27 passed,67.85s)
- 隔离域主探针:python /mnt/f/trading/local/fr2_review/fr2_review_probe.py(注意:脚本内 OUT 常量指向 reviewer 工作目录;自归档路径重跑时需同步调整 OUT 落点)
- 其余三个驱动同理;child 由 entry_probe 以子进程调用,不单独运行。

## 输出(outputs/)

- fr2_probe_results.json:12 场景逐项结果(含 real_roots 活体复跑逐字段值、每场景 bind_states/problems/断言明细);fr2_probe_run.log=运行摘要(VERDICT ALL_PASS)。
- fr2_extra_results.json:3 补测+恢复正例(ALL_PASS)。
- fr2_entry_probe_results.json:3 例入口实验断言明细(rc=96/historical_bindings/zero_writes/no_permits/approval_boundary 全 true);fr2_entry_probe_run.log=运行摘要。
- fr2_wrapper_probe_results.json:5 例 wrapper 语义结果(ALL_PASS)。
- pytest_r1r2.log:P3 真实部署环境定向套件输出(27 passed / RC=0)。

## 缺失边界(如实)

1. 入口子进程的完整 stdout/stderr 未逐字节落盘:parent 驱动捕获进内存,仅把断言字段落 JSON(rc、标记命中、one_shot_writes、permit 存在性);结论与 REPORT 一致,但原始全文未存——同型披露见 FR1 probes README。
2. 隔离域克隆环境(/home/cryptorl/tmp_fr2_review/fr2_dom)未收编(含 pin sparse 克隆、project 候选字节副本、vendor 克隆、entry_deploy 脚手架、wrapper_out 诊断件);域处于全部恢复后的健康态,可用 fr2_review_probe.py 原样重建。
3. 补测脚本第一版存在自证判定 bug(把预期 ok=false 计入 is True 判定),已修正为当前入档版本后重跑;bug 版未保留(无归档价值,且两版中被审对象行为一致)。
4. git diff 提取件(diff_guard/cli/tests.patch)未收编:可由 git diff c0fb6858~1 c0fb6858 -- <path> 在仓内机械重建。
5. WSL 启动时的 .wslconfig 乱码告警属本机环境噪音,与探针无关。
