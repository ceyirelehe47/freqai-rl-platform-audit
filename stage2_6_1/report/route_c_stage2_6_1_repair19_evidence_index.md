# Route C R19 轮最小原件证据包索引(继 R18 证据包惯例)

- 终态锚: route_c_stage2_6_1_repair19_formal_iteration.md@a0466b20
  (cue-audit 统计 FAIL;报告与索引为公开面,不含原件内容)。
- 交付: `RouteC_R19_evidence_20260920.zip`(323 文件,5.4MB;
  sha256 `27dd28db9021c176d7953f2c894ff2a25a7048324babdc3fd1be70269ac5f4bb`)
  本地副本 `F:\trading\trading\goal_incoming\outgoing\`;
  **私有通道上传待执行**(本会话无 R18 轮上传凭据)。
  逐文件字节与 sha256 见包内 `00_MANIFEST.json`(程序化生成;
  打包时仓库 HEAD=a0466b20)。

## 目录与审查关注条目映射

| 包内目录 | 内容 | 对应关注条目 |
|---|---|---|
| 01_admission | r19 预注册(v2 全字段)/现行 v2 准入/签发日志(末条含 substance_digest)/消费日志/R18-r2 已消费残件(移除前保全) | 准入 v2 签发/消费原件;R18-r2 处置披露的实物 |
| 02_launches | 本请求目录全件(launch_evidence:launch_requested→admission_granted→chain_finished;chain_run.log) | 正式启动命令与输出 |
| 03_chain_terminal | state/(journal 11 事件、abort、chain_result、fail_closure_summary、consumed)/`_chain_logs/`/正式 artifacts(cue_contract_audit.json、cue_event_trace.jsonl、cue_audit_plan、code_freeze、workflow_plan、provenance-verify/reconciliation 等) | 终态全套 + 统计 FAIL 定位原件(validation_corpus_ok=False 的直接证据) |
| 04_rt_17_17_run | rt run 20260919T214411Z_1757 全件(17/17 ok=True;§15b 统一合同首次全规模运行:candidate_dedicated_semantic 160-block×6、conservative 双分区 FAIL 的机械不合格、selection c2l_historical_control@n=20) | 链路先证 + 开放门 4.1 行为证据 |
| 05_regression_v8 | junit(2296 直核)/evidence record v8(run 长度与 skips=HISTORICAL_SKIP_IDS)/run tail/bound commit;附 v6/v7 原件与首版证据 | 准入 substance 所引回归原件 |
| 06_probe | r19_formal_feasibility_probe.json(33 段:28 干净 + 5 final 设计内拒付,形态与 R18 一致)+ capture | 可行性探针原件 |
| 07_rt_engineering_fails | 两次 rt 工程失败 run 的 state(212107Z 短 SHA 冻结失配;212526Z 种子白名单拒绝派生 ns → 修复 7017add1) | 工程失败的诚实记录(对照 R18 的 rt 副作用残件条目) |
| 08_context | git_context(HEAD/branch/log/diff --stat 375c58ec..a0466b20)/四份执行记录(GATE_CLOSURE/R19_WIRING/R19_RT1/R19_FORMAL_TERMINAL) | 本轮全部工程提交链的语境 |

## 三点说明

1. **统计 FAIL 的最小定位集**:03/cue_contract_audit.json 的
   checks 叶子(validation_corpus_ok=False;p_contract=0.950432 vs
   验证语料 CI95 上界 0.949672)+ cue_event_trace.jsonl 可独立复算;
   MC/三路其余/逐位重放/global-K 均绿的叶子同文件可查。
2. **准入 v2 首次真实行使全记录**:01+02+03 构成
   签发(substance 实算)→入口只校验→CLI 单点消费→终态 的完整
   原件链;无双消费、无早耗、无未披露状态(移除残件在案)。
3. **与 R18 证据包的形态对齐**:目录结构按
   route_c_stage2_6_1_repair18_evidence_index.md 的审查映射惯例;
   R18 轮审查 §6 的最小收件诉求在本包全部有对应目录。
