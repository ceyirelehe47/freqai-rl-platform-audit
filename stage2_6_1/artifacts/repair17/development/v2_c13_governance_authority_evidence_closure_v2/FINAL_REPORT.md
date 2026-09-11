# R17 V2 C1/C3 治理 Authority/Evidence/Lock 与 C2 Prep 行为封口（v2）最终报告

Task: R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2
Baseline: 685d2c9b9a5c2c812ae75b23e2050c5383b38e7b
Candidate commit C: 706614f6fdb3cbc2d74cdd139f165e987bd8ab14 (attempt 1,保留)
Candidate commit C2: 2ef1b29b2f126825e7cdbc74093c42ca03c0fb40 (attempt 2,保留)
Candidate commit C3: 19bd26fdff4aae44e0b4823836508d0c57a71cec (最终候选)
Evidence commit E: da3e606b468471e269f94364f24c5ba3e6d8d29c

governance_authority_evidence_closure: PASS
c2_fixed_design_values_verified: true
c2_selector_behavior_verified: true
c2_launch_authorized: false

production generator calls: 0
production fit calls: 0
production eval calls: 0
production canonical calls: 0
production policy calls: 0
production claim writes: 0
production exposure writes: 0

targeted: attempt3(六文件,C3 字节) 117/117/0 rc=0;official(C 字节) 124/124/0 rc=0;reader_binding 于全量回归 7/7
full regression: 2037 tests / 2030 passed / 7 skipped / entry rc 0
historical protected bytes: unchanged (3442 文件零变化;run_supervision 遥测区 +84 run 目录/1 追加单列)
old v2 engineering verdict: FAIL
statistics this round: NOT_RUN
formal qualification: NOT_ISSUED

---

## 1. 五个 blocker 的关闭方式

### B1 完整回归回执可伪造 → 机器验证 preclaim gate
- `r17_v2_c13_regression_evidence.py`（新增,候选冻结入 lock）:`collect`
  把受监护全量回归组装为内容寻址证据包（18 个必需文件、supervisor
  run_record 双锚、required 角色文件逐字节、测试集合、双树 import
  身份、治理闭包、候选 commit）;`verify_package` 只读 fail-closed 校验
  16 项事实,每个负例命名错误键（§5.4 全部 17+2 项在
  `regression_evidence_verifier/negative_cases/` 与单元测试双覆盖）。
- `prepare_authoritative_plan` 删除 `full_regression_ref` 参数与
  `path=unspecified / entry_rc=0` 伪绿色缺省;证据包只从 authority 推导
  的固定路径读取,机器验证失败在创建任何 plan/receipt 之前拒绝(F11)。
- `run()` 在任何生成之前重新机器验证证据包并对拍 receipt 锚定的包
  digest(F09/F10/F11;合成链篡改/重签测试 e11 两例)。
- receipt 形状:`plan_file_sha256` 必填;`full_regression_evidence`
  必须是 {path≠unspecified, package_sha256=64hex, entry_rc=0,
  business_rc=0};claim payload 绑定合同/plan digest/plan 文件字节/
  source closure/回归包 digest/消费时间(§4.3,A08)。

### B2 production authority 可改写 → 不可变 Authority
- `profile.py`:废除 `RELEASE_REPO_ROOT`/`CLAIM_ROOT` 可变全局与
  `set_test_authority()`;frozen dataclass `Authority` +
  `production_authority()`(每次调用从字面常量重建)+ 
  `synthetic_authority()`(限系统临时目录、不得与生产根重叠)。
- `enforce_authority_combination`:RealBackend/生产合同 × 合成
  authority 在任何写入/claim/生成前拒绝;生产 authority × fixture
  backend/注入合同同样拒绝(A04)。
- 所有路径/持久化/claim 函数 authority 参数化,落点只由 authority
  推导(A06);`consume_production_claim()` 零 caller 输入(A07)。
- 负例:env/cwd/out/run-id/第二 checkout/模块属性 monkeypatch 均不
  改变生产入口推导(A02/A03 测试)。

### B3 历史 lock 被覆盖 → 字节恢复 + 新治理闭包
- `r17_v2_c13_source_lock.py` 恢复 d3cdf3d1 精确字节
  (blob 3376fca56cda561c8d8033cb5bdd2ba4d4218501,
  sha256 c9152b62192a93571c16ba62e0ef2e70522f108726f3eb83fd25d48007a77c55,
  P01 双核对通过,git 对象与文件字节一致)。
- 新增 `r17_v2_c13_governance_source_lock.py`:角色声明明确"非 v2
  主 run 执行闭包"(591b1f35... 源字节不可用,永不重构);9 成员
  (4 runner 治理模块 + launch_prep + 4 个 rl_curriculum 依赖),全部
  在发布库与部署树可复算;成员集固定校验(validate_member_set)。
- source_guard 与 RealBackend 切换治理 lock(P03);再签工具
  `r17_v2_c13_governance_relock.py` 要求双树字节一致才写回。

### B4 完整回归未绑定最终候选 → 候选-证据-闭包绑定
- 完整回归在最终候选 C3 的 clean 部署上经 r17_monitored_entry 运行;
  证据包 run_meta 记录 candidate_commit=19bd26f、采集时 HEAD、argv、
  cwd、env;verifier full 模式核对 git 对象存在、HEAD 无 runner/src/
  tests 漂移、worktree clean、治理 lock 文件字节、双树成员复算、
  部署 import 身份逐文件一致。

### B5 C2 selector 源码字符串当证明 → 行为差分
- r6_design §22 排序循环纯代码搬移为 `mechanical_selection()`
  (run_design_stage 调用同一函数;语义逐位不变,AST 验证定义顺序与
  调用点)。
- `curriculum261_r17_c2_launch_prep.py`:
  `verify_mechanical_selection_behavior()` 用合成结果表调用真实
  selector,10 个场景全部通过:最小合格 n 压过更高 score、同 n
  maximin、距离、稳定 id、不合格排除、全不合格 (None,None) 不回退
  control、输入顺序不变、diagnostic 键不影响 verdict、固定输入三
  候选/n 恰好 {10,15,20}。
- 零调用哨兵:generator/fit/eval/policy/canonical/claim/namespace
  十个入口计数全 0,哨兵安装失败即 fail-closed(C09);源码字符串
  扫描降级为诊断。

## 2. 候选链(attempt 全部保留)

| attempt | commit | 内容 | 结果 |
|---|---|---|---|
| C | 706614f | 主实现 | 定向 124/0/0;全量回归绿;采集包被 verifier 拒绝(collector 未写 required_files.json)— 证据 verify_rejected_attempt1.json |
| C2 | 2ef1b29 | collector 写 required_files.json | 定向绿;全量回归绿;采集包被 verifier 拒绝(测试文件双树重算过严:发布库旧测试文件磁盘 CRLF)|
| C3 | 19bd26f | verifier 测试文件 live 复算限定部署树 | 定向绿;全量回归绿;采集包生产级校验通过 |

每一步失败证据完整保留(失败即按 §8.2 保留 candidate+证据,普通提交,
不 amend)。

## 3. 受保护原件不变性

protected_snapshots/diff_summary.json:五个受保护根 3442 文件 changed/added/removed 全空;run_supervision 遥测区 base 4914 → after 4998(+84,受监护 run 目录追加;1 文件 rejected.jsonl 追加),按 SOURCE_MAP §3 单列,不计入历史原件变化。

## 4. 零生产副作用

- 全程未调用生产 generator/fit/eval/canonical/policy(合成链仅部署
  Fixture 替身;C2 prep 哨兵计数 0)。
- 生产 claim 状态与接手时逐字节相同(claim_state 快照对照)。
- 权威 plan/receipt/evidence/回归包只写测试临时目录与工作目录;
  生产 authority 根零写入。
- 未注册任何 namespace;未触碰 v1/v2 claim;未重签历史 lock。

## 5. 不能升级的结论(重申)

- 旧 v2 engineering = FAIL(不可追认)
- C2 calibration = NOT_RUN;c2_launch_authorized = false
- Stage 2.6.1 formal qualification = NOT_ISSUED
- Stage 2.6.2/2.6.3 = NOT_STARTED;BC/PPO = NOT_STARTED

C2 fixed design and selector behavior verified for future taskbook drafting
NOT_AUTHORIZED
