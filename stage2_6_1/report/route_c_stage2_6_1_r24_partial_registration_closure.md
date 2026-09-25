# Route C R24:注册异常与部分安装收敛(工作 A 收口)

任务包:`RouteC_PartialRegistration_AClosure_NextGoal_v1`
(外层 zip sha256 `31994164da6575e1f0d63e1833db37df930c42aaf46fb9923e3df828a3b37674`;
审查原件 zip 逐字节匹配 `b5490ee78a4d311ad4d4319171ead54f4b6d5940b35e16254717c9b3f6c87126`)。
基线 HEAD:`d872f412cde39fbd814e39f051acc8153d8ebb73`(接手核验一致,
工作区仅 9 个历史 symlink typechange 噪音,无在飞进程)。

## 1. 修复的问题

独立审查(第3节)证明的唯一实质阻塞:同一插件经公开 `register()`
注册时,filter(specname 别名 `pytest_pycollect_makeitem`)+
release(`pytest_collection_finish`)两个 hookimpl 先按 `dir()` 序装入,
后置非法签名(`pytest_configure` spec 不支持的参数)触发
`PluginValidationError`;宿主捕获异常后,过滤真实生效、收集/执行一致
缩减,再公开 `unregister` 清场。v5 审计器只依赖成功返回后的
`pytest_plugin_registered` 通知——该路径对此零事件,三阶段快照在
collection_finish(tryfirst release 先于审计器回调)后已干净,
verdict=pass。

目标环境机制锚定(`probe_v1/mechanism_anchor.json`,裸管理器实测,
不经审计器):

- Python 3.11.16 / pytest 9.1.1 / pluggy 1.6.0;
- `pluggy.PluginManager.register` 先写 `_name2plugin[plugin_name]`
  再逐个 parse/verify/`_add_hookimpl`,verify 抛出时先前安装与
  注册表项不回滚;
- `PytestPluginManager.register` 只在 `super().register()` 正常
  返回后 `call_historic(pytest_plugin_registered)`;
- 部分安装后异常:`is_registered=true`,
  `get_hookcallers=[pytest_collection_finish,
  pytest_pycollect_makeitem]`(公开 API,按 `impl.plugin is plugin`
  对象归属),filter 真实参与调用;公开 `unregister` 清干净;
- 首个方法即非法:在册、零装入(`zero_installed_hooks=[]`);
- 重名 `ValueError` 在写注册表**前**抛出(对象从未进入)。

## 2. 实现(v6:审计格式 v3 / record v6)

**审计器第三层防线**(`runner/r21_collection_auditor.py`,
`AUDIT_FORMAT=cur261-r24-collection-audit-v3`):注册操作边界窄适配
`_install_register_guard`——在监测建立时(本模块自身注册的第一个
通知回调,先于任何 conftest 加载)对**本次运行的实际管理器实例**
包一层 `register`(实例属性;不打全局类补丁,测试自建的独立
`PytestPluginManager` 不受影响),异常退出后按实际对象核查
(`is_registered`/`get_hookcallers`/`impl.plugin is plugin`)并
append-only 落盘,原异常原样上抛,不吞、不改写为成功:

- 未获准对象部分装入任意 hook(含 specname 别名)⇒
  `lifecycle_registration_exception_partial_install`;
- 未获准对象异常后残留注册表(零装入)⇒
  `lifecycle_registration_exception_unclean`;
- 确无任何装入且未入册的前置失败(重名 ValueError)⇒
  `classification=rejected` 事件留痕(不伪造参与,不阻断);
- 捕获方随后的注销/回滚/末尾干净不消除已落盘事实;
- 守卫证明段 `register_guard`(manager_class/wrapped_hook/
  installed_utc)进入审计文档与 JSONL 流水(各恰一行,核验器按
  严格相等比对);守卫不可装/未建立
  (`register_guard_not_installable`/`register_guard_not_established`)
  、监测自身缺陷、记录写失败一律 fail closed。

**核验器**(`curriculum261_r17_admission_substance.py`):
`REGRESSION_EVIDENCE_FORMAT_V6`;record 版本→审计格式映射
`_AUDIT_FORMAT_BY_RECORD`(v6→审计 v3、v5→v2、v4/v3→v1,历史
核验面不变,新候选只认当代);`_verify_lifecycle` v6 另要求
register_guard 证明段在场且与流水严格一致;`rejected` 事件仅接受
严格形状(phase=registration_exception、未入册、零装入)。

**执行器**(`r21_full_collection_regression.py`):record v6;
`_audit_ok_collection` 另要求 register_guard 段,缺任一 ⇒
summary fail-closed(rc=3/4)。

**签发器**(`r17_admission_issue.py`):新签发要求 record v6;
v5 及更早不可为新候选供证(历史核验面保留)。

## 3. 变体验证(A01-A06)

沙箱反例树(`r17_admission_substance_test_support.py`,
`git_repo_with_candidate(partial=...)`;测试类
`TestPartialRegistrationR24`,12 项;探针 `runner/
r24_partial_registration_probe.py`,probe_v1 rc=0):

| 变体 | 形状 | 裸 pytest | 真实执行器 | 审计 |
|---|---|---|---|---|
| late | 审查原形状:捕获→过滤生效→finish 注销 | rc=0,10 项全绿(3 passed+7 skip,含 1 个被滤失败参数) | rc=3,summary audit_verdict_not_pass | violations: partial_install(hooks={makeitem,collection_finish},error_type=PluginValidationError);事件 unapproved/remains=true/installed=2 钩子 |
| immediate | 同一故障,捕获后立即注销 | rc=1(失败参数在场,无过滤) | rc=4(run_returncode_nonzero) | violations: partial_install 粘住(清理不撤销) |
| zero | 首个方法即非法,零装入残留 | rc=0 全绿 | rc=3 | violations: unclean(remains_registered=true);事件 installed_hooks=[] 不伪造参与 |
| rejected | 重名前置失败(canonical 树) | rc=0 全绿 | rc=0,**summary ok=true** | pass;rejected 事件(未入册/零装入)如实留痕 |

正例/隔离面(A04):canonical 运行全绿(record v6,每段审计
register_guard 文档+流水一致);R23 scoped 成功注册后注销负例仍拒;
合法 plain/parametrize/fixture 参数化/已批准 pytest_generate_tests/
核心后期注册不变;测试内自建独立 `PytestPluginManager` 的预期
`PluginValidationError` 不污染父收集管理器(受监护全量中父审计
零违规即为该测试通过前提)。

守卫失效面(A05):从文档删 register_guard ⇒ 核验拒
(register_guard_invalid);流水补写第二条 guard 行 ⇒ 拒
(stream_mismatch);R21_AUDIT_OUT 指向不存在目录 ⇒ 无 pass 文档、
rc≠0;守卫不可装(管理器拒绝属性写)⇒ register_guard_not_installable
违规;v5 形状(record v5+审计 v2)仍可历史核验但签发器拒
("evidence format v6")。

签发/消费(A06):late 坏材料(真实执行器 rc=3 产物)→ 真签发器
拒,零 admission 文件/零签发日志;v5 形状 → 拒 "evidence format v6",
零副作用;合法 canonical 链:真实签发 rc=0 → validate ok → 消费
None → 重复消费 `admission_already_consumed`(probe_v1/legal_chain)。

## 4. 证据

- `artifacts/repair17/development/r24_partial_registration_closure/
  probe_v1/`(探针,index.json + mechanism_anchor.json + 四变体
  executor run 目录 + 合法链;各原件 sha256 入 index);
- 同目录 `smoke_v1`…`smoke_v6` + `attempt_*.sh`:全部迭代尝试
  (含失败:v1 zero 误丢 canonical conftest、v2/v3 rejected 重名
  构造两次错误、v4 发现并修复 `_document()` 丢 stages 行、
  v5 修正 rejected 为 pytestconfig 重名;失败原件与结果 json 保留);
- 定向测试面 36/36、substance 套件全文件 107/107(WSL 部署树,
  freqtrade-rl 解释器,PYTHONDONTWRITEBYTECODE=1)。

## 5. 边界与不做

- 证据级别:组件+项目级(真实执行器/核验器/签发器/消费端沙箱);
  不是任意 Python 代码不可绕过的证明;信任前提仍为已绑定候选/
  执行器/解释器/配置,不防掌握全部源码与内存的恶意方。
- 未修改 r20_design_calc_v4.py/JSON/研究提案;C 保持 R23 限定接受;
  R19 终态不变;R20 未注册未启动;无新研究语料/训练/许可消费。
- 修复前对照 = 审查 ZIP 原件(9.0.2 环境)与本项目
  `test_no_defense_baseline_reproduced`(9.1.1 环境,裸 pytest
  复刻 remains_registered/active_filter/filter_called/unregistered
  事件形状);未重跑审查组件脚本(其解析面按 PROBE_GUIDE 不适配
  新防线,夹具已迁入项目测试面)。

## 6. 结果

受监护适用全量回归(`full_regression_20260926_v1/`,候选
`d085590d00c6214c2f33d56a6f861f57e284faea`,真实收集,不硬编码
总数):

- **GREEN:2470 passed / 0 failed / 0 errors + 7 skipped(恰历史
  skip 身份,r12-r16 ancestry/wrapper 系),两段 rc=0,ok=true**;
  verify(collection_tests=2470,static_tests=1989,test_files=146);
  较 R23 的 2456 增 14 = 本轮 TestPartialRegistrationR24 新增
  14 项测试;
- record v6(`cur261-r17-candidate-regression-evidence-v6`),
  record sha256
  `5b1bc98ee5401158b92c4db3d408faa5f53387a1bc007a14f2070bc5e9dccbaa`;
  每段审计 format v3、verdict=pass、register_guard 证明段在场;
- 监护 run `20260925T221421_6579_1058`(engineering,42m05s):
  incidents=0,business_rc=0;record.supervision.present=false 为
  事实(监护记录在业务退出后落盘),外部 argv token 交叉绑定见
  `supervision_crossref.json`(out-dir token 精确匹配);
- 只读复验:同源核验器以 deploy_root 重放 record 通过
  (2470/1989/146);probe_v1 index 复核(late rc=3、合法链
  issue rc=0、重复消费拒)。
