# CLOSURE REPORT — RouteC_A2_RuntimeClosure_NewAttempt_v1（RD01–RD09）

日期：2026-10-06 | 出口：**A2_RUNTIME_READY_PENDING_USER_APPROVAL**
候选（分支 B）= `2f3e7faad5aca77aed29eec3e4b70d35484f84fb`（tree `f5931ebd27f3ce7b6a6bca742730d0d155ad96bd`；前候选 `61180756`/`8916ab9d`/`0cab6ec8` 为本轮迭代，保留为祖先）；证据+文档 HEAD=`6087776c`（纯 artifacts，src/tests/runner 相对 2f3e7faa 零变化）。

## RD01 失败保留
旧 P2/D2/qaf_v1/qaf_v2 零触碰（`evidence/w1_audit/old_scene_identity.txt` 前后实测；旧 P admission `b465e5f1` 未变）；新根 P3/D3/PIN 与旧域不重叠；本轮零签发/零消费/零 launch/零科学计算。

## RD02 完整静态输入
`evidence/w1_audit/RUNTIME_STATIC_DEPS.md`：A 表（开发根 10 项，含 freeze 六件套/r20 v4 对/repair10 计划/252a runtime config/runner 面）+ B 表（pinned 发布源身份+历史绑定件）+ C 表（D3 面）+ 生产者边界；全部来自冻结源码实读（读取函数/行号在表）。98 项旧 P 血统 extras 清单钉死（`runtime_extras_manifest.json` + guard `RUNTIME_TREE_ALLOWED_EXTRAS`）。

## RD03 候选与发布源
`_freeze_release_repo` 等全部 14 处 src 解析点接入 `release_repo_candidates()`（**pin `/home/cryptorl/release_pin_qaf_v3` 优先**，检出=Commit A 只读 worktree）；`write_r17_code_freeze` 严格性不变（HEAD==A+freeze 路径 clean）。成对实测：齐件+错 HEAD 拒、dirty 拒、非 pin 解析拒（`test_rd03/rd05` 三负例+工程隔离正例=真实写出冻结产物）。

## RD04 前置生效
`runtime_dependency_preflight`（真实 freeze 读取器子进程@P3 + 三面 vs 候选 CR 投影逐文件 + 原件字节）入 `preissue_gate`——operator execute 与直接 issue-permit **两入口同一前置**，首一次性写前；缺件/错字节/错 HEAD/dirty/非 pin 五类负例零 permit/admission/科学调用（gate 测试断言 authority 目录未创建）。qaf_v3+ 强制；v1/v2（已消费尝试）豁免并注记。

## RD05 消费边界
真实域：preflight_P3 ok=true（pin head==候选、572 dev files、零问题）+ `write_r17_code_freeze` 工程隔离写出成功（`evidence/runtime_verify/`）；隔离域 14 项正反例；科学依赖仍在真正叶处截停（哨兵位置未动）。

## RD06 新尝试无科学漂移
qaf_v3：26 全新 namespace（与 v1/v2 逐名不相交断言）、迭代 `qprod_a_formal_v3`、注册表单一来源（CLI choices 自动扩展）、api recorder 匹配表首项、262 `A2RC_V1` 登记（仅 api.py 新 sha）；quota/rules/stop_mode/gate_set 与旧 A2 全等（计划不变量断言+真实构建器 `qbpl-46bb0062…`）。v2 消费不恢复（freshness 面未动）。

## RD07 最终部署/证据
P3=668→765 文件（全 src 基座+候选投影+extras）、D3=完整部署根（runner/静态面/262 tests/report 65 件/历史 repair 面/vendor/data/configs）、PIN=worktree@2f3e7faa；三方对拍 **1190 全等**（`three_way_compare.json`）；**全收集 2986=2979P+7S/0F/0E**（run `r21_20261006_010707`，cwd=D3，record `ae203c41…`，verify ok=true）+ 同根 substance **rc=0**（plan digest `f5931ebd` claimed==recomputed）/错根 rc=2；262 适用=注册面变更（`A2RC_V1`，镜像两树同步），历史 240 passed 复用不重签。失败尝试 1–6 全归档（badprotocol/refused/collection_errors/3errors/103f/stale-record）。

## RD08 日志/用量
各次回归尝试唯一 out-dir+归档；执行器日志落证据根；无恢复件冒称现场日志（恢复件仅上一轮执行轮使用且已注明）。

## RD09 最终交付
COMMANDS_APPENDIX（E1–E4 实命令，tree/plan/admission-id 已绑终值）+ PENDING_APPROVAL_SUMMARY（批准建议文本）+ 本报告；reviewer 终审+冷读后封 RETURN。

## 结论
上轮失败根因（freeze dev root 缺件）与发布源 HEAD 漂移冲突已系统性闭合；两入口签发前防错就位；一次 A2 执行的全部事前静态输入已实装、对拍、回归证明。**未签发、未消费、未 launch——仅待用户批准。**
