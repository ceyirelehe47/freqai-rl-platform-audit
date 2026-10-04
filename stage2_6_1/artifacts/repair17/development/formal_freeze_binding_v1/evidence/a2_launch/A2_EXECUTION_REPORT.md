# FFAB v1 批准轮 A2 执行报告(失败封口)

日期:2026-10-04 | 出口状态:`A2_ITERATION_FAILED_CLOSED_AT_STEP_1`(零业务计算)
授权链:用户 2026-10-04 对话批准原文「批准 A2,B 和正式课程教学暂不批准」(sha256 `b6f154bec4e36050b378eea0ba41f015f4b3368e8fd52495d8057eb1f4edafd5`)

## 1. 执行时间线(UTC)

| 时刻 | 事件 | 消耗 |
|---|---|---|
| 01:04:23–01:08:50 | 签发链五步逐项:authority init 01:04:23 → record-approval 01:04:24 → issue-permit 01:04:24(issued_utc) → prereg 落盘 01:05:46(mtime) → **一次性 admission 签发 01:08:50**(`qaf-v1-de81aba2-a2`,substance `r17sub-fde6d6b0…`,绑定 d3 record `baf441b4…`/plan `851c883b…`/A `de81aba2`) | admission 资格就位 |
| 01:09:57 | launch 尝试1:rc=96 拒绝(`before_first_controlled_side_effect`)——主 Agent 手动 export `PYTHONPATH=D/src`+state-root env 使 D 成为保护基(附录 B5 明示入口自装 env) | **零消耗**(拒绝先于一切受控写) |
| 01:12:55 | launch 尝试2(附录 B5 正确形态:P 入口/零手动 env):全部门禁通过(qfap/permit/admission 校验→run-plan 冻结→**permit 一次性消费** 01:12:56→链会话获取) | permit 消耗 |
| 01:15:33 | 链步1 `provenance-verify` 启动;**admission 消耗**(01:15:33) | admission 消耗 |
| 01:15:35 | 步1 rc=1:stored=`r15gtrec-11a43168…` vs 重算=`r17gtrec-3112e5de…` → **链停止,迭代 fail-close** | 迭代封口 |

## 2. 根因(主 Agent 安装错误,非冻结面缺陷)

B2 前置装错源:主 Agent 安装了 `stage2_6_1/artifacts/repair15/gate_topology_reconciliation.json`
(R15 时代件,stored digest `r15gtrec-11a43168…`),而 R1 交付的 COMMANDS_APPENDIX B2 明示源为
`…/formal_freeze_binding_v1/provenance/gate_topology_reconciliation.json`
(stored digest `r17gtrec-3112e5deb863a810392bbaae0e4e21d9f7017c97d0fd172d6e66eb6551bf4e9d`)。

验证器按当前树重算结果 = `r17gtrec-3112e5de…`,**与正确源文件的 stored 字段逐字符一致**
(本报告证据 `d_side_originals/artifacts_formal_a_qaf_v1_gate_topology_provenance_verify.json`
+ 附录 §B2 原文)。装对文件即通过步1。错误定性:执行时凭记忆猜 git 路径,未逐字照抄自己
在 R1 写定的附录。

## 3. fail-closure 现状(D 侧原件,冷拷见 evidence/a2_launch/d_side_originals/)

- `r17_fail_closure_summary.json`:verdict=**FAIL**,failed_step=provenance-verify,
  phase=pre-provenance,stopped_at_index=0,executed_prefix=[],九项证据状态全 not_started,
  exposure=not_exposed。「零业务」由该九项 not_started + budget gate consumed={} +
  exposure=not_exposed 共同支撑(business_leaf_calls=0 一值见于尝试1 拒绝面
  launch_attempt1_refused_env_override.log,此处不作为独立证据引用)。
- `r17_iteration_aborted.json`:iteration=r17,utc=01:15:36Z。
- 封口政策(原件原文):「只读原始 artifacts;不得重生成 qualification_r17 语料;不得创建新
  代码;下一轮必须 R17 + 全新 namespace」。
- 预算实际值:全部 0(链未达任何计算步;caps 见 `chain_budget_gate.json`)。

## 4. 为什么不在本轮内重试

Commit A 冻结代码 `--formal-namespace-attempt` choices=**("qaf_v1",)**
(curriculum261_qprod_formal_levela.py:738,repo/P/D 三处一致);封口政策要求下一轮全新 namespace 且禁止本轮
创建新代码。合法重试=新一轮修复轮(代码扩展 qaf_v2 → 新差分 → 新计划 digest → 新批准 →
新签发链),属新授权任务,不在本轮自行决断范围。

## 5. 保护面核对(P 零写确认)

P 生产面 4 件实测 sha256/mtime(见 evidence/a2_launch/post_run):
admission `b465e5f1…`(mtime 2026-09-20 前后,与九月基准一致)、wf_plan `8ff550d7…`、
chain_result `b749296f…`、abort `bde8f2d4…`(mtime 2026-09-06 前后)。
本轮全部受控 artifact 写入仅落在 D 的授权根(config/authority/formal_a_qaf_v1/state);
另 D/src 的 __pycache__ 有 66 个解释器缓存 .pyc(mtime 01:03:32–01:03:42Z,早于首个受控写
01:04:23,属非受控缓存,不计入写入面)。

## 6. 证据清单(evidence/a2_launch/)

- `launch_stdout.log`(尝试2 全输出)、`launch_attempt1_refused_env_override.log`(尝试1 拒绝面)
- `d_side_originals/`(14 件 D 原件冷拷含 chain_budget_gate.json+SHA256SUMS;清单为显式文件列表,含 dotfile)
- `post_run/`(P 保护面实测)
- 本报告

## 7. 结论

A2 执行按已验程序真实走完签发链与门禁,链在步1 因 B2 安装错误停止并封口;
一次性授权(permit/admission/迭代)已消耗,零业务计算发生。
B/正式教学保持未批准。修复轮(A2-R2)待用户/ChatGPT 决策。
