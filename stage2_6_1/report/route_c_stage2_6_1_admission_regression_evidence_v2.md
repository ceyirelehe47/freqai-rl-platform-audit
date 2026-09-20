# 准入回归证据 v2:完整集合/差分父链/多文件唯一性收敛(工作 A 轮)

任务:RouteC_AdmissionIntegrity_G5cVerification_NextGoal_v1 工作 A。
外部审查锚:`RouteC_Latest_Push_Review_b2c345e.md` §二(F1/F2/F3)
与随包 probe(函数摘录负例)。本轮把三个已确认缺口收口进
签发/消费**同源唯一实现**,并把 probe 迁移为真实项目测试。

## 1. 变更概览

| 文件 | 变更 |
|---|---|
| `src/rl_curriculum/curriculum261_r17_admission_substance.py` | 回归证据 record 升 v2;新增候选树映射/静态全集推导/清单/收集/执行溯源/部署面核验;差分父证据递归同规则;多文件唯一性 |
| `runner/r17_admission_issue.py` | 签发子进程传 `--deploy-root`(部署面字节核验在签发端生效) |
| `src/rl_curriculum/curriculum261_r17_admission.py` | 消费端 `validate_admission` 转发 `deploy_root` 给同源实质复验 |
| `tests/.../r17_admission_substance_test_support.py` | 沙箱仓携带真实测试源树(sandbox 模块 + conftest + 由 HISTORICAL_SKIP_IDS 生成的 7 个历史 skip 桩模块);构造完整 v2 证据 |
| `tests/.../test_curriculum261_r17_admission_substance.py` | 新增 6 个测试类(见 §3) |
| `tests/.../test_curriculum261_r17_supervision_unit.py` | 合法路径夹具改带测试树 + 部署面同步 |
| `tests/.../test_r18_launch_behavioral.py` | 沙箱发布仓带测试树 + 部署面同步 |

未建第三套证据框架;复用既有严格链的规则语义
(`r17_v2_c13_admission_guard.candidate_test_map/junit_nodeid/
deployment_test_errors` 的同规则镜像,零漂移由交叉断言暴露);
未硬编码任何历史运行总数(2296/2303 等仅出现在文档叙述);
未改任何历史源码锁(governance source lock 成员未触碰)。

## 2. record v2 合同(行为定义)

格式串 `cur261-r17-candidate-regression-evidence-v2`;v1 无完整性
字段,fail closed(核查:仓库内无任何生产 v1 record,无迁移对象)。

新必填字段与核验(全部 fail closed,错误词可测):
- `test_files`:候选 Git 测试源树清单。验证方用
  `git ls-tree`(stage2_6_1/tests/ 递归 .py,basename 展平,
  CR 删除规范化,casefold 碰撞拒绝)**自己重算**映射,与清单
  逐行精确相等——调用方自选子集无效。
- `collection`:收集 node-ID 列表。验证方从候选树 Git blob 用
  `ast` **静态推导应执行全集**(模块级 test_* 函数 + Test* 类一级
  test_* 方法);要求 base(collection)==静态全集(参数化
  `[...]` 后缀保留在 multiset 内)、无重复、文件覆盖==候选
  test 文件集、Counter(collection)==Counter(junit 实际 testcase
  经 classname→node-ID 转换)。**计数一致但 ID 替换、遗漏根目录
  测试、集合不对应均拒**。
- `execution`:command(非空 argv)/interpreter/cwd/returncode==0。
  缺失或 rc≠0 拒(执行来源与返回码进入记录并由 record sha256 绑定;
  离线验证方不重放执行,只强制其在场与形状)。
- junit 列表(F3):同 resolve 路径重复(含 `../` 别名)拒;同
  sha256 内容重复拒;跨文件 testcase ID 重叠拒;空 junit 拒。
  **合法分片 = 不重叠 ID 的并集 = 全集**(分片测试通过)。
  不同完整运行的相同测试属不同 record,分别判定;协议内合法重复
  必须进入身份显式验证,不静默去重。
- 差分(F2):parent 为祖先且 ≠ commit_a;边界检查(无
  src/rl_curriculum 变更、声明清单、未声明文件拒)后,父 record
  **递归经过同一完整核验**(部署面除外——父是历史提交,部署面
  只对当前候选执行)。父 JUnit 缺失/失败/被替换/未全量覆盖 ⇒
  子差分证据拒。
- 部署面(可选维度):`deploy_root` 提供时(签发端与消费端都在
  部署机上运行,均提供),`tests/route_c_stage2_6_1` 扁平面成员
  与字节必须等于候选映射。离线核验(无 deploy_root)不执行该
  维度,其余维度始终执行。

新关键测试被 skip/xfail 算通过的组合防线:skip 集合必须恰为
HISTORICAL_SKIP_IDS(既有规则)+ 新测试函数静态存在于树必然进入
全集(漏跑即 collection 失配)。

## 3. 测试矩阵(真实项目层,非函数摘录)

`test_curriculum261_r17_admission_substance.py` 42 项全绿(部署树):

- **probe 迁移(三个审查负例到真实校验层)**:
  F1 `incomplete_set_mislabeled_full` → `regression_collection_
  static_mismatch`;F2 `differential_accepts_invalid_parent` →
  `differential_parent_evidence_rejected:…`;F3 `same_junit_counted_
  twice` → `regression_junit_duplicate_path`。
- **F1 面**:v1 格式拒;三新字段缺失各拒;计数一致 ID 替换拒
  (`regression_collection_execution_mismatch`);根目录级新测试
  未覆盖拒;清单行篡改拒;新增模块测试被 skip 拒(越出允许表);
  完整证据通过(aggregate/collection==static 断言)。
- **F3 面**:同文件×2 拒;路径别名拒;同内容异名文件拒;跨文件
  testcase 重叠拒;合法分片通过。
- **F2 面**:形状合法但无 junit 的父拒;绿但不完整的父拒;父
  junit 被替换拒;doc-only delta 完整差分通过。
- **部署面**:字节漂移拒→复原过;同步助手写出的面与映射精确相等。
- **同源零漂移**:candidate_test_map 与 guard 逐字段相等;
  junit_nodeid 与 guard 转换相等(含参数化名);未知 classname
  双侧同拒。
- **parse_junit 元素级**:原 6 负例/兼容全部保留通过。
- **沙箱端到端(真实签发器子进程 + 真实消费闸门)**:合法完整
  证据 → 签发成功 → `validate_admission` 过 → `enforce` 消费 →
  二次消费拒;证据原件替换(消费前)→ 消费端同源复验拒
  (`regression_junit_sha_mismatch`);F1 证据 → 签发器拒且零
  文件副作用。沙箱用 tmp 部署根与 tmp git 仓,真实部署面
  (r17_formal_requests/repair18/repair19 状态根/签发消费日志)
  零触碰;未为本验证签发任何真实正式运行许可。

受影响消费方回归:`test_curriculum261_r17_supervision_unit.py`
(含 TestFormalAdmissionUnit 合法路径重构)、`test_r17_r18_
attempt.py`、`test_r17_r19_attempt.py`、`test_r18_launch_
behavioral.py`(真实 r18_formal_chain.sh + 签发器全流程)全绿。

## 4. 真实树活体验证(静态推导的适用性证据)

2026-09-20 在 b2c345e 真实树(WSL 部署面)实测:`pytest
--collect-only` 2303 个收集 ID;静态推导 1840 个基 ID;
**base(collected)==static 精确相等(零幻影/零遗漏)**,139 个
test 文件覆盖精确,无重复收集。旧历史包
(v2_c13_admission_boundary_closure_v3/continuation_v3a,候选
16c45dae)属双布局时代(stage2_6_1/tests 根下亦有 test_*.py,
98 部署 vs 129 递归),不能锚定当前 v3b 映射语义——该包上
junit↔collection multiset 仍精确相等(1832=1832),仅映射口径
随代际变化;本轮不追改历史包。

## 5. A4:计划内容职责的实际调用链核对(回应审查 §三)

结论:**现有链已承担**实验计划内容绑定,准入 substance 的
plan_digest==tree 只承担代码身份——与 4c3bd59 澄清一致,且
各职责有代码位置与验证:

| 职责 | 承担位置(代码/合同) | 验证 |
|---|---|---|
| 预注册/审计计划在启动前锁定 | audit plan lock:create-only + digest 复算(`curriculum261_r15_cue_contract.py` `lock/load_locked_cue_audit_plan_r15`;r10/r11 同构);R17 正式链最小序列 determinism-matrix → provenance-lock → audit(freeze 只能建一次) | 链步 1/2 机械重算;重锁即拒(测试覆盖) |
| 执行前重算 | 各 `load_locked_*` 在 run 入口重算 digest + 代码身份(如 `ppo262_g5c.load_g5c_plan`;qualification plan `curriculum261_plan.verify_plan`);G5c 本轮 B 面实测:运行时锁定的 code sha == 部署树字节 | B 轮 `g5c_verification.json` |
| 参数/候选/许可引用 | R15+ qualification 六要素解锁(plan+digest+gate+pack 绑定+preflight attestation;`curriculum261_api.py` namespace 守卫);许可 = admission v2(绑定 Commit A+substance) | 签发/消费同源复验(本轮沙箱端到端) |
| design/fit 后对象关联 | R2CheckpointStore tag 校验(`checkpoint_verification` 入结果);exposure marker/ledger 终态绑定 plan digest | G5c 36 checkpoint 清单+spot 重载;R15/R16/R17 exposure 合同测试 |
| 不要求签发器提前绑定未产生对象 | 签发器只要求 preregistration 既存字段;未来资格计划不进 admission(澄清报告 4c3bd59) | — |

无发现需要新增的工程断链;本轮不借此增加科学决定。

## 6. 兼容与边界

- 消费端外部契约(`validate_admission`/`consume_admission`/
  `enforce_formal_admission`/CLI)签名与拒绝词不变;新增维度只在
  证据 record 与内部核验层。
- 旧 v1 record 一律拒绝(无生产件);测试夹具全部升 v2。
- 部署面核验只在 deploy_root 可达处执行;纯离线审计(如 CI)不
  因此误拒——其余维度自足。
- 完整面回归见 SUMMARY;本轮代码改动全部在 stage2_6_1
  (262 无代码变更,B/C 为报告与工件)。
