# CLOSURE REPORT — RouteC_A2_RuntimeClosure_NewAttempt_v1（RD01–RD09）

日期：2026-10-10（证据终验日；首轮编制 2026-10-06）| 出口：**A2_RUNTIME_READY_PENDING_USER_APPROVAL**
最终候选（Commit A）= `85a879a46d0a20831644eb9aae52e0537436713f`（tree `06827b7d1534e136fd2b65347ec0f7ce392c0c3e`）。演进链：`0cab6ec8`(W1–W4 主体)→`8916ab9d`→`61180756`→`2f3e7faa`→`b3e3bffd`(RcwGate1 P0–P3 修复)→`c0801c56`(R2 修复：release_repo_candidates import 等)→`afc7d82e`/`8da55a52`/`34d7f7c8`/`45a47547`/`85a879a4`(活 audit 探针暴露的 qaf_v3 注册补丁:框架迭代/26 namespace 双注册表/api 正式面/测试计数)。其后提交均为纯 artifacts 证据,src/tests/runner 相对 85a879a4 零变化。

## RD01 失败保留
旧 P2/D2/qaf_v1/qaf_v2 保护原件逐字节未变(轮初 `evidence/w1_audit/old_scene_identity.txt` ↔ 2026-10-10 后置 `old_scene_identity_after_20261010.txt`:旧 P admission `b465e5f1…`、issued `956178b2…`、P2/D2/旧 P 全部单件同 SHA;P2 仍缺 env 两件=失败根因原样保留;P2/D2 零新文件)。如实披露:标准部署树 crypto_rl 内有工程哨兵链负例探针目录(r17_rt_runs,~30 个,全部 dummy-sha 被 HEAD==A 检查拒绝、exposure=not_exposed)与 2 个 src 文件按既往惯例同步为候选版本——详见 `evidence/w1_audit/old_scene_disclosure_20261010.md`。本轮零签发/零消费/零 launch/零科学调用;唯一 preissue 调用只读且因 E1 未装而正确拒绝。

## RD02 完整静态输入
`evidence/w1_audit/RUNTIME_STATIC_DEPS.md`:A 表(开发根 10 项,含 freeze 六件套/r20 v4 对/repair10 计划/252a runtime config/runner 面)+ B 表(pinned 发布源身份+历史绑定件)+ C 表(D3 面)+ 生产者边界;全部来自冻结源码实读(读取函数/行号在表)。98 项旧 P 血统 extras 清单钉死(`runtime_extras_manifest.json` + guard `RUNTIME_TREE_ALLOWED_EXTRAS`)。

## RD03 候选与发布源
`_freeze_release_repo` 等全部 14 处 src 解析点接入 `release_repo_candidates()`(**pin `/home/cryptorl/release_pin_qaf_v3` 优先**;PIN=独立 clone,`route-c-stage2-6-1-repair17` 分支态、HEAD=85a879a4、porcelain 干净);`write_r17_code_freeze` 严格性不变(HEAD==A+freeze 路径 clean)。成对实测(2026-10-10 终验):工程隔离正例=真实写出冻结产物(`freeze_engineering_P3.json`:r17fs-c4b5818c、missing=[]);活 audit 步反例=dummy sha 拒(`prefix_probe_85a879a4/audit_step_refused.stderr`:HEAD=85a879a4≠传入 0000…);detach 破坏 ancestry 分支名检查亦拒(`ancestry_refused_detached_head.json`);旧 P r17_rt_runs 历史探针跨候选全程同类拒绝(见披露 §2.1)。

## RD04 前置生效
`runtime_dependency_preflight`(真实 freeze 读取器子进程@P3 + 三面 vs 候选 CR 投影逐文件 + 原件字节)入 `preissue_gate`——operator execute 与直接 issue-permit **两入口同一前置**,首一次性写前;五类负例零 permit/admission/科学调用(隔离 14 项 RD03-RD06 测试,gate 断言 authority 目录未创建)。qaf_v3+ 强制;v1/v2(已消费尝试)豁免并注记。真实域终验(2026-10-10):`preflight_P3.json` ok=true(572 dev files 零问题);完整 preissue gate 在 E1 配置未装时 fail-closed 拒绝(`preissue_gate_P3_preconfig_refused.json`,one_shot_writes=0)——符合"配置仅批准轮激活"边界,全绿 gate 正例由批准轮 E1 后首写前强制执行。

## RD05 消费边界
真实域 2026-10-10 终验四件:preflight ok + `write_r17_code_freeze` 工程隔离写出成功 + **活链前缀 3 步全绿@85a879a4**(`prefix_probe_85a879a4/`:provenance-verify pass(stored==recomputed r17gtrec-3112e5de)→determinism A4/A5/A6 pass→audit rc0 anchored r17fs-c4b5818c、ancestry ok、全 binding pass、determinism_contract=bound)+ substance verify 同根 rc=0(plan digest 06827b7d claimed==recomputed、record 2989 绿)/错根 rc=2。隔离域 14 项正反例;科学依赖仍在真正叶处截停。

## RD06 新尝试无科学漂移
qaf_v3:26 全新 namespace(与 v1/v2 逐名不相交断言)、迭代 `qprod_a_formal_v3`、注册表单一来源(CLI choices 自动扩展)、api recorder 匹配表首项、262 `A2RC_V1` 登记;活 audit 探针逐层暴露并补齐:R17_FRAMEWORK_ITERATIONS、CURRICULUM261_R17_NAMESPACES(种子派生白名单)、r17_registry 双注册表、api CURRICULUM261_R17_FORMAL_NAMESPACES(afc7d82e→45a47547,5 提交)。quota/rules/stop_mode/gate_set 与旧 A2 全等(计划不变量断言+真实构建器 `qbpl-2c65de6fe59a03b817ee3653d744a8c05ccdaf35dac6bba02cf66a20179330e4`,draft==rebuilt 实测)。v2 消费不恢复(freshness 面未动)。

## RD07 最终部署/证据
P3/D3/PIN 三新根与旧域不重叠;三方对拍(CR 规范化投影,pycache 排除,共享文件逐对):**P3-D3 698/698、P3-PIN 597/597、D3-PIN 660/660 全等**(`evidence/three_way_compare.json` 带 meta 绑定候选);全收集 **2989 tests(2982P+7S)/0F/0E**(run `r21_20261006_073405`,cwd=D3,record `de43964e7ebe476f5ce2e3a88800d157278aa8a99d092a0bb496445a7784e994`,verify ok)由 substance verify 同根 rc0 复核;262 适用=注册面变更(`A2RC_V1`,镜像两树同步),历史 240 passed 复用不重签。失败尝试 1–10 全归档(9=b3e3bffd 绿 2987 归档、10=063257 单失败归档);2026-10-10 终验证据(preflight/freeze/substance/three-way/prefix_probe/preissue 拒绝/旧现场后置+披露)随本提交入库。

## RD08 日志/用量
各次回归尝试唯一 out-dir+归档;2026-10-10 各项终验唯一日志文件(`/f/trading/local/a2rc_w5/w5_rerun_20261010T0400Z.log` 等+wsl tmp_a2rc_w5 探针域);工程计算如实记账:determinism-matrix 前缀探针 ×2 次工程跑(detached 失败次+全绿次,各 ~76s,属既有工程确定性电池,非科学资格计算);无恢复件冒称现场日志。

## RD09 最终交付
COMMANDS_APPENDIX(E1–E4 实命令,tree/plan/admission-id 绑终值)+ PENDING_APPROVAL_SUMMARY(批准建议文本)+ 本报告;reviewer 终审+冷读后封 RETURN(包外双回执绑定实算 SHA)。

## 结论
上轮失败根因(freeze dev root 缺件)与发布源 HEAD 漂移冲突已系统性闭合;两入口签发前防错就位;一次 A2 执行的全部事前静态输入已实装、对拍、活链前缀与全量回归证明。**未签发、未消费、未 launch——仅待用户批准。**
