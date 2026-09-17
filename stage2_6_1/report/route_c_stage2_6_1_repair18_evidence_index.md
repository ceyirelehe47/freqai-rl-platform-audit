# Route C R18 轮最小原件证据包索引(回应外部审查 §6)

- 审查锚: RouteC_R18_Report_Review_4a5d2fd(对提交 4a5d2fd 三份报告的复核);
  本索引只描述已打包交付的只读原件,不改写、不补造任何原件。
- 交付: `RouteC_R18_evidence_20260918.zip`(483 文件,4.0MB;
  sha256 `85fe67c8326cee16763672e0e7b3be2359f342cd04aa5c4b51982528e496a54b`)
  已上传私有通道服务器 `/root/download/`(远端 sha256 复核一致);
  本地副本 `E:\trading\goal_incoming\outgoing\`。
  逐文件字节与 sha256 见包内 `00_MANIFEST.json`(程序化生成;
  打包时仓库 HEAD=4a5d2fd)。公开面仅本索引,不含任何原件内容。

## 目录与审查 §6 条目映射

| 包内目录 | 内容 | 对应审查条目 |
|---|---|---|
| 01_admission | 签发日志(2 条)/消费日志(2 条)/现行准入凭据/r1+r2 预注册原件/首签披露/预注册哈希口径核验 | 两次启动的命令与签发/消费记录、预注册对象 |
| 02_launches | 两次控制台输出(rc=96/rc=1)、`r17_formal_requests` 两个请求目录全件、首launch期间 4 个 rt 副作用残件 | 两次启动的 stdout/rc 与请求级证据 |
| 03_chain_terminal | journal(5 事件)/abort marker/chain_result/bootstrap_accepted/manifest/fail-closure 摘要/`_chain_logs/`(provenance-verify.err 即 PrerequisiteError 原文)/pending_abort_requests(2)/会话锁 | R18 journal、abort marker、chain_result、fail-closure/工作流记录(首launch=bootstrap 拒绝;第二次=step1 终态,两侧产物分开) |
| 04_rt9 | rt9 整 run(state/logs/artifacts;含 17/17 步 rc=0 的 journal 原件与 freeze=e9dadfa9 的 launch evidence) | rt9 运行结果及日志索引 |
| 05_regression_v4 | 16_collect/17_run/`full_run_v4` 完整受监护运行原件(含 junit 2258/0/0/7)/test_map_v4 全套/tools/prewarm + junit 直核 + `18_full_check_v2`(check_junit.py 陈旧期望 rc=1 证据) | v4 collection/JUnit/源码映射/候选来源 |
| 06_v2v3_incident | `full_run_v2`(junit.xml 与 junit.xml.v2_original 双件)/`full_run_v3` 残件(含 business/stdout.log 即 pytest 原始输出)/v3 全套映射 + incident_note | v2 JUnit 恢复凭据、v3 保留材料 |
| 07_probe | 探针报告/capture(19 行段记录 rc=0)/脚本两份(sh+py) + `namespace_intersection.json` + `probe_sections_summary.json` | 可行性探针的样本角色与实际调用索引 |
| 08_post_a5ea7b9 | 针对性受监护执行原件(2026-09-17T16:52Z,`test_r17_r18_attempt.py` 6 passed)+ 部署树/仓库测试文件 CR 归一比对 + note | a5ea7b9 之后已有验证材料 |
| 09_workdir | SUMMARY.md / WORK2 顶层清单 / 最新 30 条 mtime 排序 | 最后进度/预算/进程状态 |
| 10_context | 审查件原件副本 / git_context(HEAD、branch、log -12、status、diff --stat 08a7958..a5ea7b9 与 a5ea7b9..4a5d2fd) | 候选来源与增量佐证 |

## 四点澄清(均以包内程序化生成物背书)

1. **预注册哈希口径闭合**: 签发日志记录的是 canonical 重序列化哈希
   (`r17_admission_issue.py:106-108`:
   `sha256(json.dumps(preregistration, sort_keys=True, ensure_ascii=False))`),
   与盘面文件字节哈希本就是两个口径。期望值直接读自签发日志权威字节、
   与 r1/r2 现存原件复算**两条全部吻合**
   (01/`preregistration_sha256_verification.json`,all_match=true)。
   此前交接盘点中报告的"不匹配"系长十六进制串的单字符转录笔误。
2. **首次准入替换的三状态如实区分**: 原始时序(01/02/03 原件互证)=
   签发 15:29:34Z → 入口消费 15:29:42Z(pid 390)→ CLI 以
   admission_already_consumed 拒绝(rc=96,15:29:45Z)→ 该次**无 journal
   会话、无任何步骤、无 bootstrap_accepted** → 修复 a5ea7b9 → 移除
   已消费凭据文件 → r2 签发 15:41:16Z → CLI 单点消费 15:41:28Z
   (pid 460)→ 步 1 失败 → 终态 15:41:29Z。即替换时点:正式样本未曝光、
   迭代非终态、启动许可已消费——三者并存;合规性判定留给审查,
   全部原始时序证据在包内。
3. **v2 JUnit 恢复凭据**: `full_run_v2/junit.xml` 与
   `junit.xml.v2_original` 字节一致(备份在覆写发生前取得;
   两者均在包内可独立复核)。v3 junit 原件丢失,如实保留缺失、
   不以解析摘要冒充;v3 判定证据 = business/stdout.log(含 1 failed
   的 pytest 原始汇总)+ run_record/summary + 全套 collect/映射。
4. **探针样本角色**: 探针实际使用命名空间 15 个,全部属于 R18 正式族
   (16 个中唯一未触及 `fresh_holdout_r18`),与 rt4_* 工程族**零交集**;
   触及注册表正式资格面(CURRICULUM261_R17_FORMAL_NAMESPACES)的恰为
   R18 四件套且**全部被六要素 fail-closed 拒绝**(即 5 个 fatal 段:
   final_fit/final_c13/final_c2_ind/final_supervised/semantic_final;
   20 段=15 干净+5 fatal,pass=false)。生成经 envelope_sink + tempdir
   账本(进程内临时目录,随 TemporaryDirectory 销毁),唯一持久写入
   = 探针报告本身;正式 journal/准入/资格暴露零触碰(03 节 journal 仅
   5 条链事件可互证)。精确交集与逐段计数见 07/ 两个程序化 json。

## a5ea7b9 候选适用性(回应审查 §4.3)

v4 全量(2258/0/0/7)绑定父提交 08a7958;a5ea7b9 delta = runner 脚本
+ 1 个测试文件、无 src 变更(10_context/diff --stat 佐证);本轮补:
部署树与仓库测试文件 CR 归一字节一致 + 受监护针对性实际执行
(6 passed)。候选级差分验证协议已固化于
`route_c_stage2_6_1_repair19_prescription_erratum.md`(勘误三);
守卫与行为级测试工程提交(1cdfd06)的全量回归 v5 执行记录见该勘误末尾。
