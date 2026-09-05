# Stage 2.6.1 Repair R16 主报告:发布入口一致性、执行所有权与正式数据授权闭环

**日期**:2026-09-05
**迭代**:R16(route-c-stage2-6-1-repair16)
**基线**:R15 Commit B `c0da37a498740201c42898ea9b743ecfb54990da`
**状态**:工程验证阶段(本节以下内容随各阶段完成填充;不预先声明任何 PASS)

---

## 0. 本报告的证据边界

本报告区分 development/rehearsal 与 formal 证据。正式结论只来自
Commit A 之后的新正式链。工程测试或 rehearsal PASS 只表示工程验证
通过,不能单独获得 iteration PASS 或 Stage 2.6.1 PASS(§13)。

## 1. 身份和冻结

| 项目 | 值 |
|---|---|
| 仓库 | ceyirelehe47/freqai-rl-platform-audit |
| R16 分支 | route-c-stage2-6-1-repair16(自 c0da37a 创建) |
| exact baseline | c0da37a(R15 Commit B;本地=远端核验一致) |
| vendor pin | 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5 |
| R16 Commit A | (待 Commit A 后填入真实 SHA) |
| R16 Commit B | (待 Commit B 后填入真实 SHA) |
| 执行面行尾 | .gitattributes 固定 runner/src/tests 为 LF;全 r16_*.sh 字节级验证 LF |
| freeze surface | R16_FREEZE_REPO_PATHS(src/tests/runner 递归)+ dev 单文件;digest 前缀 r16fs- |
| code identity | PLAN_CODE_MODULES_R16 = R15 清单 + 31 个 r16 模块 |
| R15 失败绑定 | r15_governance_binding(CRLF 启动失败;永久 FAIL 不追认) |

R15 历史失败绑定证据:historical_evidence_binding 的
r15_governance_binding 块(分支/两提交链/失败分类/四个治理缺口:
CRLF 字节门缺失/runner 在 drvfs/激活失败被吞/bootstrap 误归属)。

## 2. 实际启动

- 外层命令:`bash r16_formal_chain.sh <commit_a_sha>`(WSL 本地
  PROJECT_ROOT 解析;执行面经 r16_sync.sh 同步,不再从 /mnt/e 执行);
- LF 自检:grep -q $'\r' "$0" 位于 set -euo pipefail 之前(R15 实证
  全 CRLF 死于 set 解析,后置自检执行不到;测试断言行序);
- 启动请求证据:r16_launch_evidence.jsonl(bash 原生追加,先于任何
  python 调用);
- 会话接受证据:r16_bootstrap_accepted.json(chain 执行器在第一步
  之前写入;与启动请求证据分开,被拒绝的请求不写正式 manifest);
- bootstrap 失败封口:--failed-step bootstrap(workflow 前缀为空;
  首个未执行节点 provenance-verify 未开始);
- rehearsal 覆盖:real-artifact-rehearsal 经同一
  execute_workflow_chain_r16,同一 CLI 模块,同一 17 步。

## 3. 所有权和授权(执行治理内核 curriculum261_r16_execgov)

- 唯一正式会话:R16FormalSession.acquire(flock 非阻塞 + 锁内重查
  iteration/exposure/孤儿状态);会话 token 为 256-bit 随机,磁盘只
  存 sha256;
- 竞争请求零副作用:acquire 失败只记录 session_rejected
  (durable=False 尽力而为),不写 exposure/abort/traceback/manifest;
  CLI 的 cmd_qualify 对 R16OwnershipError 直接传播,不 dump failure
  evidence、不写 iteration aborted(R15 无差别 except 缺口的修复);
- exposure 先行:record_exposure_started 在 issue_generation_grant
  之前持久化(journal append + fsync 文件与目录);exposure 写入失败
  时会话释放、资格不消耗;
- 生成授权:grant token + executor 委派(受控环境变量
  CURRICULUM261_R16_EXECUTOR_TOKEN);验证 = journal 重放(token
  hash 匹配/未撤销/未释放/未 abort)+ 会话互斥探测(LOCK_SH 非阻塞;
  owner 消失且无锁继承者时残留 token 失效)+ namespace 范围 +
  exposure running;
- 终态持权提交:commit_qualification_terminal 要求 owns();终态后
  的 smoke/full-cold 失败走 iteration_aborted 封口,不覆写资格终态;
- 孤儿处置:无 exposure 无授权的孤儿会话允许接管
  (session_superseded);exposure running 的孤儿只能显式
  orphan_running_closure 失败封口(锁可获取前置;不接管重跑);
- 权威状态源:r16_execution_journal.jsonl(闭合 12 种事件;seq 连续
  强校验;损坏 fail closed R16JournalCorruption);exposure marker
  是投影(marker 删除不影响 journal 判定;测试覆盖)。

### 授权矩阵(§7.1 强制行为的实测)

| 状态 | 允许正式 seed 派生? | 测试 |
|---|---|---|
| plan 未锁定 | 否(六要素拒绝) | test_formal_namespace_rejected_without_unlock |
| 无会话无 grant | 否 | test_no_grant_no_session_rejected |
| grant 活动窗口 | 是(限授予范围) | test_grant_active_allows / namespace_scope |
| grant 撤销后 | 否 | test_revoked_grant_rejected |
| 终态后(残留 token) | 否 | test_terminal_state_rejects_new_grant |
| 复制 token+会话已释放 | 否 | test_copied_token_rejected_after_release |
| owner 消失(互斥失效) | 否 | test_env_token_from_delegated_subprocess |
| 伪造 token | 否 | test_forged_token_rejected |
| journal 损坏 | fail closed | test_corrupt_journal_fails_closed |

## 4. 事实和产物

- 生命周期事件序(测试断言):session_acquired → exposure_started →
  grant_issued → executor_delegated → (final core) → grant_revoked
  → qualification_terminal → session_released;
- 异常分支:core 异常 → crashed 封口 + 释放(崩溃日志先落盘);
  exposure 持久化失败 → 释放且资格不消耗;grant 发放失败 → crashed
  封口;
- 阶段精确失败封口:build_phase_accurate_fail_closure_r16(bootstrap
  边界 + qualification 三细分从权威 journal 机械判定 + 四值证据
  状态;journal 损坏如实记录 journal_integrity_ok=False);
- R15 启动失败反例的回归期望(bootstrap closure):
  executed_prefix=[] / next=provenance-verify(未开始) / 全部证据
  not_started / qualification 未授权未 exposure(测试覆盖)。

## 5. 课程与统计

- workflow:AuthoritativeWorkflow-v1 继承,17 步,digest
  r16wg-bbaa8b23b3b5cd08c1cb90ac9d4beaf27302da586b5050875bd04ddfa353754a;
- gate topology:GateTopologyReconciliation-v2 继承,digest 前缀
  r16gtrec-(正式值待正式链 provenance-lock 后填入);
- 领域合同全部冻结(§3.3):C2 三 candidate 数值、global K
  (B=50,000 起步/99% CP/边界规则)、tail t≥264、dedicated 160-block、
  max_attempts=5、cue audit 500+500;
- 正式 design/calibration/qualification 结果:(待正式链执行后如实
  填入;统计 FAIL 则诚实 FAIL,不调整规则)。

## 6. 工程验证

- 测试:R16 新增 4 个测试文件(execgov/governance/final_lifecycle/
  governance 发布仓库级),含真实双进程竞争(barrier 精确控制)、
  授权矩阵 9 反例、journal 损坏、phase 准确性、reader 纯净性;
- 全量回归:(最新数字待 freeze 前最终全量后填入;中途全量
  1251 过/1 失败/3 跳——唯一失败为 R15 分支名断言,按 R14→R15
  先例以 skipif 处置,由 R16 governance 测试承担等价断言);
- 发布布局 rehearsal:(待最终 rehearsal 完成后填入 17 步结果);
- 历史证据未修改:R15 artifacts/原始失败证据原样保留(r15 wrapper
  的 CRLF 是原始失败证据,不清理、不改写)。

## 7. 结论

(待全部阶段完成后按 §13 矩阵填写。)
