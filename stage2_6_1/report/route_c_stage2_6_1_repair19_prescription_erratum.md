# R19 处方勘误(时序统一 / 行为级前置 / 候选验证协议)

- 锚: `route_c_stage2_6_1_repair19_prescription.md`@4a5d2fd;
  外部审查 `RouteC_R18_Report_Review_4a5d2fd` §3/§4。
- 原处方与审查冲突之处以本勘误为准;未提及条目维持原文。
- 本勘误只统一协议与前置,不创设任何 r19 命名空间/目录/入口。

## 勘误一: provenance-lock 时序(原 §1.3 与 §2 验证序列作废)

原处方 §1.3"准入签发后、链启动前运行 provenance-lock"与 §2 把 lock
放在签发前的序列互相矛盾,且均违反权威合同。权威合同
(`curriculum261_r17_workflow.py` provenance-verify 步注记 +
`R17_EXTERNAL_ARTIFACTS`"链外产物(Commit A 前一次性锁定;运行时
存在性照常检查)")规定的唯一有效顺序:

1. 候选工程验证闭合(rt 全绿 + 适用于该候选的回归绑定,见勘误三);
2. **链外一次性 provenance-lock**
   (`python -m rl_curriculum.curriculum261_r17_cli provenance-lock
   --out-dir <正式 artifacts 根>`)生成 gate_topology_reconciliation.json
   (create-only;内容绑定 R6/R13/R14 历史 blob 与 R17 gate topology
   digest,**不绑定未来 Commit A 身份**,因此不存在后验身份回填问题;
   若未来某链外产物确需绑定 Commit A 身份,必须走既有 checkpoint
   规则连接,不倒填历史);
3. 冻结 Commit A;
4. 准入签发(绑定 Commit A;§4.2 实质绑定闭合前不得签发);
5. 入口预检(存在性检查,纵深防御层;见勘误二);
6. 链步 1 provenance-verify 恒执行(重算 digest 比对;不重新 lock、
   不静默跳过)。

R18 r2 的失败 = 第 2 步被整体跳过,缺陷拖到第 6 步才暴露且已消费
一次性准入。rt 排练链不暴露此问题,因为 real-artifact-rehearsal
前置步骤自动执行了第 2 步。

## 勘误二: 入口预检升级为行为级验证前置(原 §1.3 存在性检查仅保留为纵深防御)

存在性检查挡不住"文件存在但内容无效/身份错位";源码字符串测试
不足以证明可启动(审查 §3.2)。准入签发前必须全绿的前置:

**沙箱行为级隔离验证**(真实 `r18_formal_chain.sh` + 真实签发器/
闸门/一次性消费/provenance-verify 代码;`R17_PROJECT_ROOT` 指向
沙箱根,真实部署面哈希快照全程比对),覆盖:
- (a) 链外前置缺失 → 入口零消费早拒(不消耗一次性准入);
- (b) 前置存在但内容无效(`{"pass": false}`)→ 单次消费全流程、
  链步 1 内容强制失败、沙箱 journal 终态(R18 r2 行为的定向复现);
- (c) 准入文件缺失/冻结 SHA 不匹配 → 零消费早拒、零链状态;
- (d) 双消费回归(入口只校验;CLI formal 分支为唯一消费点;第二次
  启动与直调消费点均拒绝且消费日志/journal 不增);
- (e) 各拒绝路径对真实部署面(请求根/正式状态根/签发与消费日志)
  零触碰。

执行记录: 本轮已落地——`r18_formal_chain.sh` 新增链外前置存在性
守卫(位于 FREEZE_SHA 解析后、准入闸门前;零消费早拒 rc=96,拒绝
记录携带真实 freeze_sha;存在性不替代内容校验),
`test_r18_launch_behavioral.py` 上述 (a)-(e) 四场景全部通过;影响面
审查 subagent 放行(断言切片/插入点可用性/沙箱隔离途径均核)。

## 勘误三: 候选验证协议(回应审查 §4.3)

下一次 Commit A 必须携带适用于**该提交本身**的验证,二者取一:

- 完整回归绑定该提交(先提交后跑,test mapping 锚定 HEAD);或
- 协议认可的差分验证 = (i) 父提交全量绿 + (ii) delta 仅执行面/测试
  (无 src/统计面变更,`git diff --stat` 佐证)+ (iii) delta 新增/变更
  测试在该提交树实际执行通过 + (iv) delta 行为面由勘误二 harness
  真实执行覆盖。

"src 未改"本身不构成验证。纯报告/文档类增量(不触执行面)不使
既有回归失效。08a7958→a5ea7b9 的教训(准入绑定的提交缺乏适用验证)
不得重现。

## 勘误四: 新轮次身份不构成修复证明(维持原 §3.3 并强化)

r19 命名空间/状态根/入口脚本的创建,不得先于勘误一/二/三与
§4.1/§4.2 两个开放门的闭合;禁止"换名—排练绿—正式第一步失败"
循环再现。R18 journal 终态不可复活;下次正式尝试须经治理预注册
以全新身份进行。

## 开放门(本勘误不解决;正式设计/签发前必须闭合)

- §4.1 cue 语义来源统一: 正式 cmd_design 的 matched-block 候选评估
  路径与 dedicated 合同构成双路径,不得因阈值字面相同视为同一实验
  合同;须统一并用行为测试证明 matched 诊断不暗中影响候选合格与排序;
- §4.2 准入实质绑定: 签发端须读取并重算真实计划、核验候选回归证据
  (而非仅复制 preregistration 字段);消费端核验同源。

## 本轮执行记录(证据索引的工程侧对应)

- 提交 1cdfd06: 入口守卫 + 行为级测试 + governance SHELLS 纳入
  r18_formal_chain.sh(LF + bash -n 冒烟补缺);定向 44 passed
  (行为级 4 + r18_attempt 6 + 治理 34)。
- 全量回归 v5 绑定 1cdfd06:2265 tests / 0 failures / 0 errors /
  7 skipped(全部在 HISTORICAL_SKIP_IDS 允许表内,越界为空);
  collect 与 junit 计数一致(2265=2265,直核 pass=true);相对 v4 的
  2258 = a5ea7b9 新增测试 1 + 行为级 4 + SHELLS 参数化 2。
