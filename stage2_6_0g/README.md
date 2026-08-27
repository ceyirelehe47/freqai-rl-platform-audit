# 阶段 2.6.0g:Builder 产物来源证明与私有 EntryPoint 验证闭环(最终收尾)

- 基线提交:`9d79a5994b06a54e949680a1e2bd0dcf22553b77`(提前提交的中间版本)/ 初始基线 `2a07811c`
- 判定:**PASS**(全量回归 **1246 passed / 0 failed / 0 skipped / 0 xfailed**;独立验收 ACCEPT;等待独立审查,不自动进入 2.6.1)
- 最终报告:[report/route_c_stage2_6_0g_builder_runner_isolation_completion.md](report/route_c_stage2_6_0g_builder_runner_isolation_completion.md)
- 中间版报告(提前提交,历史保留):[report/route_c_stage2_6_0g_builder_provenance.md](report/route_c_stage2_6_0g_builder_provenance.md)

## 收尾轮完成的工作(工作包 A-I)

- **A 遗留失败关闭**:test_modifying_builder_package_file_changes_npb
  单项复跑 1 passed;0e/0f/0g 三目录复跑 176 + 73 passed;报告纪律
  只保留 PASS/FAIL(无 CONDITIONAL PASS)。
- **B 隔离 Builder Runner**:新最小运行时 `rl_builder_runtime`
  (unshare user+mount+pid+proc+net + Landlock deny-by-default +
  rlimits + staging 只读 bind + tmpfs scratch;与 Candidate 沙箱
  **不同挂载集**:无 checkpoint/sidecar/model 挂载)。主评估进程对
  私有 Builder 只做哈希/AST 静态检查/启动 Runner/收发规范化消息
  ——零私有代码执行。staging TOCTOU 五态攻击(哈希后改源码/复制后
  替换/删除/新增 helper/源码 A 执行 B)全部启动前对账拒绝。
- **C EntryPoint 精确合同**:`build_pack(request)` 恰好一个位置参数;
  第二位置参数/可选参数/`*args`/`**kwargs`/keyword-only/候选别名
  参数名全部拒绝(AST 静态 + Runner 运行时双重强制)。独立
  attempt-loop entrypoint 废除(attempt 循环由规范化 attempt log
  运行证据证明)。
- **D Request/Result 精确协议**:mode 驱动白名单
  (builder_execution / mock_payload_assembly,Provider 派生 + manifest
  绑定,不再靠 isinstance);未知字段/路径值/候选字段/伪造 format 或
  protocol 一律拒绝;attempt log 规范化合同
  (builder-attempt-log-v1,nal- 哈希绑定)。
- **E Builder Run Evidence**:builder-run-evidence-v1 绑定
  npb-/pcf-/rtb-/brp-/staged-tree/nbr-/nrl-/nap-/nal-/np- 哈希链;
  precommit 双跑(BuilderUncertain fail closed)+ 考试期第三次重放
  三组 hash 对账;公开承诺只带 bre- 摘要,执行器读取完整 evidence
  重算逐项验证(detail 篡改同样被拒)。
- **F Identity 自洽重算**:canonical hash/protocol/tree digest/
  file_count/entrypoint 报告 source_sha256/run_mode 深层自洽
  (完全自签攻击全部拒绝)。
- **G 运行时依赖锁**:Runner 内 sys.modules 审计 → distribution
  映射 → 版本 + RECORD 哈希;静态 AST 闭包降级为预检;动态
  importlib/函数级/条件 import 全覆盖;`<missing:...>` 拒绝;每次
  Runner 运行后立即对账。
- **H Checkpoint 前访问守卫**:主进程 audit hook(4b 期间
  checkpoint/sidecar/attestation 零 open,违规 EXAM_INVALID)+ Runner
  内访问审计;inspect.stack 与 argv/env/fs 扫描两个主动攻击 Builder
  全部失败;哨兵文件验证。
- **I 完整 Private 正式链路**:自包含测试私有 Builder(pair_count=40
  / max_attempts=5/train+dev+null 全 split),双跑 evidence → 承诺
  v8 → 第三次重放 → duration/power/pack validity 全对账 → 受信
  attestation + Candidate 沙箱 → 256 步 PPO smoke 正常 FAIL。

## 协议升级

sealed-exam-commitment v7→**v8**(builder_run_evidence 绑定,v7 显式
拒绝)/ null-pack-builder-manifest v3→**v4**(run_mode;静态验证语义)/
builder-runner-protocol v1→**v2** / build-request v1→**v2** /
build-result v1→**v2** / builder-run-evidence **v1(新增)** /
hidden-exam-cli v8→**v9**(--builder-evidence 必填)。语义未变的协议
(duration-contract-v1/friction-v2/qualification-spec-v2/power-v2/
qualification-v4/checkpoint-manifest-v3/attestation-v1/candidate-
runtime-v1/context-v3)不升级。

## 回归

12 目录逐目录执行:**38+74+78+81+182+169+159+83+57+112+64+149 =
1246 passed / 0 failed / 0 skipped / 0 xfailed**。证据:
artifacts/route_c_stage2_6_0g_completion/(19 项)+ logs/regression_raw.log。

## 冻结确认

Route C 六项冻结合同、LongFlatLedger、fee/slippage/tick rounding、
reward、terminal liquidation、Long-Flat 动作、Observation、Freqtrade
上游(52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,clean)均未修改;
模型路线保持 SB3 PPO/普通 MLP/单资产现货/Long-Flat;未开始 2.6.1
与正式课程训练。
