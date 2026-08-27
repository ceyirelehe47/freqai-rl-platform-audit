# 阶段 2.6.0g 收尾报告:Builder Runner 隔离、运行证据与全量复验闭环

- 生成时间:2026-08-28(UTC)
- 基线提交:9d79a5994b06a54e949680a1e2bd0dcf22553b77(提前提交的中间报告)
- 本轮定位:2.6.0g 最终收尾;不创建 2.6.0h,不进入 2.6.1,不开始正式课程训练
- 判定:PASS(全量回归零失败/零跳过/零 xfail;详见第十三节)

## 一、任务定位与中间报告遗留

提前提交的中间报告记录了:1169 passed / 1 failed(修复已落盘未复跑);
私有 Builder 仍在主评估进程内直接 import 和调用;无隔离 Builder Runner、
无 Builder Run Evidence、无确定性重放证明。本轮工作包 A-I 全部闭环。

## 二、工作包 A:遗留回归失败关闭(A1/A2/A3)

- A1 单项复跑:`tests/route_c_stage2_6_0e/test_pack_builder_manifest.py
  ::test_modifying_builder_package_file_changes_npb` → **1 passed**
  (`_module_source_within()` 的 candidates 列表修复真实生效);
- A2 三目录复跑:route_c_stage2_6_0e + 0f → **176 passed**;
  route_c_stage2_6_0g(改造前)→ **73 passed**;
- A3 报告纪律:本报告只有 PASS/FAIL 两种结论;不存在
  PASS_WITH_PENDING/PASS 附待复验/有条件 PASS。

## 三、工作包 B:隔离 Builder Runner(B1-B4)

**B1 主进程零私有代码执行**:主评估进程对私有 Builder 只做读取并哈希
文件、AST 静态检查、创建 Runner、发送规范化 request、接收规范化
result。`PrivateBuilderIdentityProvider` 构造期只执行 AST 静态验证
(`validate_builder_entrypoint` 静态版);`_import_entrypoint_callable`
与 `run_builder_entrypoint`(主进程直接调用形态)已从源码删除;
`verify_builder_provenance` 按 mode 分派,`builder_execution` 一律经
`run_isolated_builder_run` 子进程执行。测试:
`test_private_provider_construct_no_import` /
`test_validate_does_not_import_private_module`(构造与验证后
sys.modules 无私有模块;顶层副作用文件未产生)。

**B2 独立 Runner 进程**:新最小运行时 `rl_builder_runtime`
(与 rl_candidate_runtime 对称但**不同**):

- 独立进程:unshare --user --map-root-user --mount --pid
  --mount-proc --fork --net(独立 mount/pid/proc/user/net namespace);
- 只读 Builder staging:bootstrap 在 mount namespace 内把
  `<base>/runtime` 与 `<base>/builder_pkg` 重新 bind 只读;
- 独立临时输出目录:`<base>/scratch` tmpfs(64m);
- 固定工作目录:chdir scratch;
- 清洗环境变量:父进程与 exec 环境都是固定白名单(PATH/PYTHONPATH=
  staging/LANG/LC_ALL=C.UTF-8/TZ=UTC/PYTHONHASHSEED=0/
  PYTHONDONTWRITEBYTECODE=1/OMP/MKL/OPENBLAS_NUM_THREADS=1;
  HOME/TMPDIR=scratch);
- 资源限制:rlimits(cpu 900s/AS 4096MB/FSize 64MB/nofile 256/
  nproc 128)+ 执行超时 900s + 响应单行 32MB 上限;
- 网络禁用(netns 仅 down lo);/proc 独立 procfs(看不到父进程);
- fd:bootstrap closerange(3, 1<<16),只继承 0/1/2;
- 挂载集合与 Candidate 沙箱不同:无 checkpoint/sidecar bind-mount、
  无 model 目录、无 __CHECKPOINT__ 占位符。

**B3 staging 与 TOCTOU**:启动序列强制:复制到匿名 staging(拒
symlink/设备/额外不允许文件)→ 对 staging 实际副本重算 tree manifest
→ 与 Provider identity(npb- 绑定的 package_tree)逐字节对账 →
rl_builder_runtime 副本同样与当前源码 manifest(rtb-)对账 → 通过才
unshare/bootstrap;bootstrap 再把 staging bind 只读。攻击全部
fail closed(identity 哈希后修改源文件/复制后替换文件/删除文件/新增
helper/源码 A 执行 B)。Runner 不依赖主进程 sys.modules(隔离进程
内无缓存可污染;同名陈旧模块先弹出)。

**B4 Candidate 不可见**:Runner 的 argv 只有 python -m
rl_builder_runtime.runner + staging 路径 + module/qualname;
env 为固定白名单;stdin 只有冻结构建请求(精确字段白名单,无任何
路径/候选字段,值级路径扫描拒绝 a/b 形态字符串);cwd 是 scratch;
mounts 只有 staging 只读 + tmpfs;/proc 独立;fd 只 0/1/2。
`test_runner_argv_env_request_no_candidate_material` 捕获全部 launch
入参逐项断言无 checkpoint/sidecar/attestation 材料。

## 四、工作包 C:精确冻结 EntryPoint 合同(C1-C3)

**C1 精确单参数**:`build_pack(request)`——恰好一个位置参数
(POSITIONAL_ONLY/POSITIONAL_OR_KEYWORD),除此之外不得有其他参数。
拒绝矩阵(静态 AST 预检 + 隔离 Runner 运行时 inspect 双重强制):
第二个位置参数、可选额外参数(含单参数默认值)、`*args`、
`**kwargs`、keyword-only 附加参数、candidate/candidate_path/
checkpoint/checkpoint_path/model/policy/score/scores/result/
exam_result/verdict/outcome/prediction/ranking 全部候选别名参数名。
v3 的"`*args` 形态可接收 request"放行已删除。

**C2 attempt loop**:独立 attempt-loop entrypoint 已废除(manifest
v4 的 package_tree 不再有 attempt_loop_module/qualname;
provider_config 的 attempt_loop 字段显式报错带迁移提示)。attempt
循环是 build 入口内部的构建循环,其真实执行由规范化 attempt log
(builder-attempt-log-v1,经 result 携带、nal- 哈希绑定、进入
evidence)证明——不存在"manifest 声明一个从未执行的函数"。

**C3 禁止主进程受控 import**:AST 静态检查保留在主进程(零执行);
运行时 callable 类型/签名/返回值验证全部移入隔离 Runner
(rl_builder_runtime.runner:callable/非类构造器/类型白名单/
inspect 精确单参)。私有模块顶层代码不在主评估进程执行。

## 五、工作包 D:Request/Result 精确协议(D1-D4)

**D1 Private request**:`builder-build-request-v2` 精确字段白名单
(mode 驱动):未知字段拒绝(不再只用候选字段黑名单)、缺失字段拒绝、
候选相关键名递归黑名单(深度防御)、值级路径扫描(纯 ASCII 路径样式
字符串拒绝:pack payload/EpisodeSpec 列表字面/seed/外部 pack path/
任意文件路径/未注册扩展字段均无法进入)。

**D2 Mock request 双通道**:`builder_run_mode` ∈
{builder_execution, mock_payload_assembly} 由 Provider 派生、被
manifest v4 的 run_mode 字段绑定(npb- 覆盖)、进入冻结构建请求与
evidence;不再依赖 isinstance(provider, MockBuilderIdentityProvider)。
硬闸:builder_execution 请求携带 mock_pack_payload 一律拒绝;
mock_payload_assembly 请求必须携带载荷(mode 与载荷自洽);正式
private hidden pack 的 evidence.mode 与请求 mode 必须一致
(from_json/verify 12e 双层强制)。

**D3 Result**:`builder-build-result-v2` 精确字段集合
{format, runner_protocol, status, pack, attempt_log, error};缺
format/错误 format/缺 runner protocol/错误 protocol/未知字段/
伪造 status/error 非空/pack 缺失或不可解析一律失败(Runner 侧
干净子进程验证矩阵 8/8 拒绝)。

**D4 Attempt log**:`builder-attempt-log-v1` 规范化合同——attempt
序号/最大 attempt/每次结果(verdict + 匿名拒绝原因,accept 不得带
原因、reject 必须带)/最终选中 attempt(必须指向 accept 条目)/
输出 pack hash(主进程解析 pack 后回填并哈希绑定)。canonical hash
nal- 进入 evidence。"只记录条目数量"的旧形态被字段集合精确性拒绝。

## 六、工作包 E:Builder Run Evidence 与确定性(E1-E4)

**E1 evidence-v1**:绑定 Builder manifest hash(npb-)/Provider
config hash(pcf-)/Builder 协议/Runner code hash(rtb-,rl_builder_
runtime 逐文件)/Runner sandbox/profile hash(brp-)/staged Builder
tree hash(npb- tree)/frozen request hash(nbr-)/runtime dependency
lock hash(nrl-)/attempt policy hash(nap-)/attempt log hash(nal-)/
output canonical pack hash(np-)+ pack schema/version/run status/
确定性结论。

**E2 precommit 双重运行**:承诺创建前在两个全新独立 Runner 进程
运行同一 Builder;run1 与 run2 的 pack hash/attempt log hash/
runtime lock hash 三组必须完全一致,不一致 → BuilderUncertainError,
不创建承诺(mock 通道同构:两次确定性重组装)。

**E3 考试期第三次重放**:formal D1 4b 启动全新 Runner 重放,要求
exam replay == commitment == precommit run1 == run2;同时对账
request(nbr-)/attempt log(nal-)/runtime lock(nrl-)/runner code
(rtb-)/sandbox profile(brp-)/builder staging identity(npb- tree)。

**E4 证据绑定**:公开承诺只携带 evidence hash(bre-)+ 非敏感摘要;
完整 evidence(含 runtime lock 逐条目、attempt log 全文、access
摘要)保存在评估方私有目录(CLI --builder-evidence);正式执行器
读取完整 evidence、重算 bre- 并逐项验证——detail 内的 attempt_log/
runtime_lock 重算 nal-/nrl- 与核心字段对账(篡改 detail 绕过 bre-
的攻击被拒绝),不信任单一 deterministic 布尔值。

## 七、工作包 F:Builder Identity 自洽验证

`require_builder_identity` 重算并验证:canonical manifest hash ==
identity.manifest_hash(manifest A + hash B 拒绝)/manifest.
builder_protocol == identity.builder_protocol(protocol A + B 拒绝)/
package_tree 逐文件 digest 重放 == tree_hash 且 file_count 一致
(文件清单被改但 tree hash 未改拒绝)/entrypoints_validated 报告的
source_file 在文件清单内且 source_sha256 与该文件一致(报告与
staged 文件不一致拒绝)/signature_policy.enforced/ run_mode 预注册
且与 commitment 一致。攻击矩阵以"完全自签"(重算 npb-)形态验证
深层防线独立兜底(16/16)。

## 八、工作包 G:实际运行时依赖锁(G1-G4)

**G1 静态预检**:AST import 闭包保留为预检/allowlist 候选/诊断
(不再称为完整运行时 lock);rl_platform 以 tree hash、python 运行时
版本单独绑定。

**G2 Runner 实际 import 审计**:Runner 内 sys.modules 快照差集 →
非 stdlib/非 staging/非 rl_builder_runtime 的顶级模块 →
importlib.metadata 映射 distribution → 绑定 distribution 名/版本/
安装元数据 RECORD 哈希/实际 import 的模块清单/Python 实现与版本。
无法映射/版本缺失/RECORD 缺失 fail closed。

**G3 config 不得覆盖实际证据**:provider_config 的
external_dependencies 只是静态 allowlist;实际 lock 由 Runner 重新
派生并对账(实际加载未注册依赖拒绝——动态 importlib.import_module
新包/函数级 import/条件 import 全覆盖;版本漂移拒绝;
`<missing:package>` 拒绝)。对账在每次 Runner 运行后立即执行
(不只考试期)。

**G4 动态 import 测试**:importlib.import_module('pytest')(不在静态
闭包)→ 运行时锁对账 fail closed;函数级 import numpy(在闭包)→
允许且出现在锁中(证明函数级 import 被审计覆盖);条件 import 分支
触发 → 同样进入锁。

## 九、工作包 H:Checkpoint 前访问守卫

- 主进程:`BuilderStageAccessGuard`(sys.addaudithook)在 formal
  D1 步骤 1-4b 期间记录全部 open 事件,受保护前缀(checkpoint/
  sidecar/attestation)触碰 → EXAM_INVALID fail closed;审计结果
  (`builder_stage_access_audit`)进入成功/幂等/失败输出;
- Runner 进程:audit hook 记录 Builder 阶段全部 open 路径,
  allowlist(staging + python prefix)之外且实际可 stat 到的访问
  上报并拒绝采信(Landlock deny-by-default 兜底;editable 安装
  finder 的被拒探测不构成泄露);
- 两个主动攻击 Builder:inspect.stack() 搜索调用方局部变量 pack
  (Runner 内调用方局部只有 request → 拿不到且构建失败);
  sys.argv/os.environ/os.listdir 扫描 checkpoint(固定白名单 env
  无候选变量、argv 无路径、cwd=scratch → 拿不到且被拒);
- 哨兵文件:评估工作区放置哨兵 checkpoint,Runner 运行后哨兵
 未被触碰、access 审计 outside 为空;
- provenance 失败场景:monkeypatch 沙箱启动/checkpoint manifest
  加载为 spy(计数为零)+ audit hook + 结构性证据(checks 空 dict,
  4b 先于 verify)。

## 十、工作包 I:完整 Private 正式链路

真测试私有 Builder(自包含,不依赖 rl_curriculum、不复制外部 pack、
不读取 mock 载荷,seeds 全部从自身冻结 namespace
`private-builder-a/pack-construction/v1` 派生):

- 非默认参数:pair_count_per_family=40(每族 80 null episodes,
  三族 240)+ max_attempts=5;
- 完整 split:train/dev_seed_holdout/param_extrapolation/
  family_holdout(各 3 episodes)+ null_control;
- 真实 attempt log(结构自检循环 + 选定条目);
- 两次 precommit 确定性运行(独立 Runner 进程,evidence);
- commitment v8(绑定私有 npb-/nbr-/bre- 摘要);
- 正式考试第三次重放(CLI v9 --builder-provider private
  --builder-evidence):exam replay == run1 == run2 == commitment;
- duration/power/pack validity 全链对账(私有 pack PACK_VALID);
- 受信 training attestation + 系统级 Candidate 沙箱;
- 256-step PPO smoke 最终**正常 FAIL**(不是用不存在 checkpoint
  证明 gate 通过);
- 攻击闭环:缺 --builder-evidence → CLI 拒绝(exit 2);evidence
  文件被改写 → bre-/detail 对账 EXAM_INVALID。

duration contract 语义说明:全局合同从 pack 的全部 required Null
Episode 派生,含 episodes_per_family/n_null_episodes——私有链路
先做一次探路构建取得最终 pack 形态,再以该 pack 派生的正式合同
发起 precommit(评估方流程两步,与上一致收敛)。

## 十一、协议升级

| 协议 | 新版本 | 语义变化 |
|---|---|---|
| sealed-exam-commitment | v7→**v8** | builder_run_evidence 摘要绑定;v7 显式拒绝 |
| null-pack-builder-manifest | v3→**v4** | run_mode 字段;entrypoint 静态验证语义;attempt-loop 声明废除 |
| builder-runner-protocol | v1→**v2** | 隔离 Runner 执行;mode 绑定 |
| builder-build-request | v1→**v2** | mode 驱动精确字段白名单 + 路径值扫描 |
| builder-build-result | v1→**v2** | 精确字段 + format/protocol 值强制 |
| builder-run-evidence | **v1(新增)** | bre-/nal-/nrl-/nap-/pcf-/rtb-/brp- 哈希链 |
| hidden-exam-cli | v8→**v9** | --builder-evidence 必填 |
| null-duration-contract-v1 / friction-v2 / qualification-spec-v2 / power-v2 / qualification-v4 / checkpoint-manifest-v3 / attestation-v1 / candidate-runtime-v1 / context-v3 | 不变 | 语义未变,不无理由升级 |

新执行器拒绝:sealed-exam-commitment-v7 及更早/builder manifest
v3/runner protocol v1/无 Run Evidence 材料/无隔离 Runner profile
材料/只有 AST 依赖清单无 runtime lock 的材料。

## 十二、攻击测试矩阵汇总(tests/route_c_stage2_6_0g,13 文件)

Runner 隔离:inspect.stack 读取 caller pack / sys.argv 读
checkpoint / os.environ 候选变量 / 扫描工作目录 / checkpoint 哨兵 /
访问网络(netns)/ parent /proc(procfs)/修改 evaluator module·
registry·commitment(主进程材料不进 Runner)/主进程模块缓存污染 /
源码 hash 后替换文件(TOCTOU 五态)。
EntryPoint:`*args`/`request, *args`/`request, **kwargs`/
keyword-only/默认值/第二位置参数/候选别名×14/顶层 import 副作用。
Request/Result:未知字段/路径值/嵌套候选字段/mode 缺失或未知/
payload 注入 private mode/mode 无载荷/result 缺 format/错 format/
缺 protocol/错 protocol/attempt log 非法×8/篡改/output pack hash
篡改。
Identity:manifest A+hash B/protocol A+B/清单改 tree 不改/
file_count/报告 stale sha/外部 source_file/public digest 伪造/
run_mode 缺失·未注册·与承诺不符/signature_policy/完全自签深层
防线×7。
Determinism:读取系统时间等不确定性来源由双跑一致性证明拒绝
(BuilderUncertain);两次 attempt log/pack hash 不一致即不确定。
Dependency lock:动态 import 新包/函数级/条件 import/missing 占位
/版本漂ift/unmapped。
Evidence:bre- 篡改/detail 篡改/nbr- 不符/deterministic 伪造/
runs 不一致/文件缺失。
Formal:mock CLI v9 全链/私有 CLI 全链/缺 evidence/坏 evidence/
幂等带审计/4b 失败零接触。

## 十三、全量回归

逐目录执行(12 测试目录;freqai_rl_platform_audit 无测试文件):

| 目录 | passed | failed | 耗时 |
|---|---|---|---|
| tests/freqai_rl_stage2_5 | 38 | 0 | 2.80 |
| tests/freqai_rl_stage2_5_1 | 74 | 0 | 7.20 |
| tests/freqai_rl_stage2_5_2 | 78 | 0 | 46.80 |
| tests/freqai_rl_stage2_5_2a | 81 | 0 | 17.51 |
| tests/route_c_stage2_6_0 | 182 | 0 | 342.02 |
| tests/route_c_stage2_6_0a | 169 | 0 | 489.95 |
| tests/route_c_stage2_6_0b | 159 | 0 | 223.35 |
| tests/route_c_stage2_6_0c | 83 | 0 | 265.38 |
| tests/route_c_stage2_6_0d | 57 | 0 | 270.02 |
| tests/route_c_stage2_6_0e | 112 | 0 | 426.74 |
| tests/route_c_stage2_6_0f | 64 | 0 | 189.91 |
| tests/route_c_stage2_6_0g | 149 | 0 | 165.46 |
| **合计** | **1246** | **0** | |

failed = 0 / error = 0 / skipped = 0 / xfailed = 0(全部满足; 完整输出见 artifacts/regression_raw.log)。

## 十四、判定

**PASS**——工作包 A-I 全部闭环;全量回归零失败、零跳过、零 xfail;
PASS 条件 30 项逐项满足(见任务书十七节):遗留失败真实复跑通过、
私有 Builder 不在主评估进程 import 或执行、隔离 Runner 执行、
staging 逐字节对账、无 sys.modules/TOCTOU 绕过、inspect.stack 与
checkpoint 攻击全部失败、EntryPoint 精确单参数、request/result
白名单、attempt log 规范化并哈希绑定、evidence 进承诺、precommit
双跑一致、exam 第三次重放一致、runner/sandbox/runtime lock 绑定、
实际 import lock 取代自报、缺失/动态依赖 fail closed、identity
自洽重算、不自洽攻击拒绝、完整私有链路 + attested PPO smoke 运行、
provenance 失败时 checkpoint/sidecar/attestation/沙箱零接触、
v7 拒绝、0f duration/0e friction·power·pair/issuer·attestation·
反作弊继续通过、六项冻结合同未修改、Freqtrade 上游 clean 且
HEAD 不变(52bc96f4480b1a0da6a9b455bd00b17fbb6786a5)、未开始
正式课程训练。

## 十五、已知限制

1. mock 通道的"运行时锁"是确定性伪锁(主进程公开组装,无第三方
   import 面),mode 明确标注 mock_payload_assembly——公开基础设施
   组装不产生第三方依赖面;
2. Runner 内 audit hook 的 outside 判定以"路径实际可 stat 到"为准
   (Landlock 已拒绝的 import finder 探测不构成信息泄露,不计违规);
   stat 类访问的完整覆盖由配套 monkeypatch 测试保证;
3. duration contract 含 episodes_per_family,私有链路需两步(探路
   构建 → 以最终 pack 派生正式合同)——这是合同的既有语义
   (2.6.0f 冻结),本轮未修改;
4. 测试私有 Builder 是受控测试资产(真实私有 Builder 由评估方在
   受信目录独立实现);资产已自包含(不依赖 rl_curriculum)。

## 十六、冻结确认

- Route C 六项冻结合同未修改(spec_versions 原值,artifacts
  frozen_contracts_untouched.json);
- LongFlatLedger/fee/slippage/tick rounding/reward/terminal
  liquidation/Long-Flat 动作/Observation 未修改;
- Freqtrade 上游 clean 且 HEAD = 52bc96f4480b1a0da6a9b455bd00b17f
  bb6786a5;
- 模型路线保持 SB3 PPO/普通 MLP/单资产现货/Long-Flat;
- 未开始 2.6.1 与正式课程训练;等待独立审查。
