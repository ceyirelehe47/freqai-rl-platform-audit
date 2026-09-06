# R17 阶段 E 修复设计：E1 请求日志隔离 + E2 rehearsal 全隔离（任务书 §7）

状态：设计稿（E 盘掉线期间起草；实施时以真实源码为准修正行号/细节）
依据：任务书 R3（formal launcher 在会话准入前 `>` 截断固定 chain_run.log）、
R4（rehearsal 仅 RT_STATE 随机，ART/LOGD 固定，provenance_lock.log /
chain_run.log 固定）。

## 共同基础设施：请求级 RUN_ID + 独立请求目录

两个 launcher（r17_formal_chain.sh / r17_rt_rehearsal.sh）开头统一：

```bash
RUN_TS=$(date -u +%Y%m%dT%H%M%SZ)
RUN_ID="${RUN_TS}_$$"          # 秒级时间戳+PID；不进任何 seed 派生
REQ_DIR="<root>/requests/${RUN_ID}"   # root: formal=固定正式证据根;
                                      #       rt=rt_runs 根
mkdir -p "$REQ_DIR"
```

- 所有"会话准入前"的 shell 层输出只写 `$REQ_DIR`：
  launch_evidence.jsonl（>> 追加，仅本请求）、chain_run.stdout.log、
  chain_run.stderr.log、workflow_plan.log、fail_closure.log、
  storage_check.log 等——`>` 只可能截断本请求自己的文件。
- emit_launch 的"先于任何 python"语义保留（R16 §5.4），只是目标文件
  从共享固定路径改为请求目录。
- 两个 launcher 的重复段落（LF 自检 / emit_launch / 激活 / 解释器验证 /
  RUN_ID+请求目录）提取为 `r17_entry_common.sh`，各自 source——消除
  双脚本漂移（§E2"最小共享入口"）。profile 差异留在各自脚本：
  - formal：部署 state root 绑定、freeze SHA 必填、正式证据根
  - rt：rt_runs 隔离根 + provenance-lock 前置 + --rehearsal + small profile

## E1：formal launcher（runner/r17_formal_chain.sh）

问题行为（现状）：
1. `LOGD=$PROJECT_ROOT/r17_formal_logs` 固定；chain-run 调用
   `> "$LOGD/chain_run.log" 2>&1` —— 第二个请求在锁拒绝之前已把
   第一个请求的日志截断为 0（bash 在命令执行前打开重定向，[S2]）。
2. workflow_plan.log / fail_closure.log 同理（若同为 `>`）。

修复后行为：
1. 请求期全部输出 → `requests/${RUN_ID}/`（见上）。
2. 获得会话所有权后，权威证据由 python 内部管理（execgov journal 为
   单写者、会话绑定；rejected_requests/ 区已实现）——shell 层不写
   任何跨请求共享文件。
3. 被拒绝请求：python chain-run exit≠0 + rejected_requests 记录；
   shell 只传播 rc，不改写 owner 的 abort/报告/日志。
4. 失败且 plan 未生成时 fail-closure --failed-step bootstrap 的输出
   也写 `$REQ_DIR/fail_closure.log`（不写共享文件）。

验收反例（D06，governance_unit 新增真实进程测试）：
- 进程 A 启动 chain（rt/小模式，持锁运行中）；barrier 确认 A 已写入
  chain_run.stdout.log ≥ N 字节；进程 B 同 state root 启动第二请求。
- 断言：(a) A 的 stdout.log 字节数不减少、内容前缀不变；(b) B 的
  全部输出仅存在于 requests/<id_B>/；(c) 权威 journal 无 B 的写入
  （B 仅出现在 rejected_requests/）；(d) A 正常完成，rc 与无竞争
  基线一致。

## E2：rehearsal launcher（runner/r17_rt_rehearsal.sh）

问题行为（现状）：RT_STATE=$(mktemp -d) 随机，但 ART、LOGD 固定于
PROJECT_ROOT，provenance_lock.log / chain_run.log 固定 → 跨次覆盖、
旧证据丢失。

修复后行为：
```bash
RT_ROOT="$PROJECT_ROOT/r17_rt_runs"
RUN_DIR="$RT_ROOT/${RUN_ID}"
ART="$RUN_DIR/artifacts"; LOGD="$RUN_DIR/logs"; RT_STATE="$RUN_DIR/state"
```
1. state/artifacts/logs/manifest 全部按 run 隔离（D07）。
2. 旧 run 目录保留原始字节，不删除不复用；新 run ID 不改变预登记
   seed 流（seed 坐标由 profile 冻结，run ID 仅影响路径与元数据）。
3. 最终 rehearsal 必须经同一共享启动实现（r17_entry_common.sh +
   本脚本），工程/正式差异仅来自合法 profile 与隔离路径。
4. 本次不跑 formal 真实分支（§E2）；formal 防线用"不消耗数据的输入
   拒绝测试"验证：空/非法 FREEZE_SHA 触发 bootstrap 失败路径，断言
   请求目录隔离与 fail-closure 落点正确、无共享文件写入、无任何
   namespace 消费。

验收反例（D07）：
- 连续两次 rt rehearsal 启动（可用极小 profile 让其快速失败于受控
  步骤），断言两次 run 目录完全独立、第一次目录文件哈希不变。

## 不变项（明确不做）
- 不改 execgov journal 协议/状态机（上轮已实现并测试）。
- 不改任何统计/seed/样本量配置。
- 不新建消息中间件/调度系统。
- formal launcher 的正式编排语义（部署绑定、300GB 天花板、唯一
  chain-run 调用点）不变，只动"输出落点与请求隔离"。
