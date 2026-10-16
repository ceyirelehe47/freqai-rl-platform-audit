# EVIDENCE_INDEX_20261016.md — 已验成果证据索引(校验引用,原件不入库)

> 白名单归档配套索引:原始日志/模型/输出 zip 保留本地
> F:/trading 与 Slack 线程,仓库仅以 SHA-256 引用;大型原件
> 不盲目提交。**course_gate=not_frozen(全线)。**

## 一、运行证据 zip(本地原件+SHA256)
| 证据 | 本地路径 | SHA256 |
|---|---|---|
| root_reference a1 | root_reference_a1_run_20261016.zip | 2eba47d6ad239c590a10d688621ba13c1a8734f31c0e30e6622275b34efd664b |
| root_reference a1 补件 | root_reference_a1_addendum_20261016.zip | d9373d4869caa03c8270a7803c7dc4c56eb70cf007ebaa8f9616fb44fe1c7a27 |
| five_point a1 | five_point_a1_run_20261016.zip | c9cb525fe9062643638bb1f0196b6b147493bdaca8715f72b1a41936b1efdbeb |
| teaching pilot a1 | unified_teaching_a1_run_20261016.zip | 4ce3ea8ff13d8f800c4171c05796bee0ecb067b5060a8fab0e7bd8728266b881 |
| diag panel a1 | diag_panel_a1_run_20261016.zip | 530c7745896c30efde73847bcdad06b80bbbb74fcff583ff354ca02b5e39080a |

## 二、外部输入依赖(不入库,复现须在位)
- unified_flat_calib_official_attempt2_20261016/tier_L2.json
  = 124eb67c5f63cd3cc8fd5dfe83ac8e71fab54dd1e907755202413de0fa3277c7
- 同目录 V_L2.npy(7,112,288B)
  = 35ef5480c97508752f16fcddd0960d82a6e5b38ac950aac45fc78cf221b40515
- teaching pilot a1 checkpoint(完整 64 位):
  initial.zip = f87005f35210c64c117f247afdc984bd1244cda8e3da8690c45e87a2c7184dba
  final.zip   = 9cb6113387716f3b76f9f198aedd0ac284b199d94363f79f7830bbe347b7b7d1
- teaching pilot run_spec.json
  = 23ce189231b3359765d05af1df1d4403d682ce598d17067e952b7d9595b82b47

## 三、复现命令(**仅说明复现,不构成执行授权**)
以下在 repo checkout 内执行;依赖源码即白名单件+repo src:
```
export PILOT_REPO_SRC=<checkout>/stage2_7_0/src
```
- root_reference(冻结校准输入在位):
  `bash launch_rootref.sh <attempt_root> <label> official <PY> <EVID_DIR> <LOCKED_MANIFEST.json> <NEW_OUT>`
- five_point(同上输入+LOCK_FIVEPOINT.json):
  `bash outer_run.sh <root> <label> -- bash launch_fivepoint.sh <root> <label> official <PY> <EVID_DIR> <LOCK_FIVEPOINT.json> <NEW_OUT>`
- teaching pilot(**从头训练**;NEW_OUT 为参数,a1 ckpt 非其固定输入):
  `bash outer_teach.sh <root> <label> -- bash launch_teach.sh <root> <label> official <PY> <NEW_OUT>`
  预检 stage1 限定此前 5 个零 env stub 选择器(实际值):
  `PYTEST_ADDOPTS='-k "test_stub_flow_identity_compare or test_stub_fail_and_budget or test_real_evaluate_function or test_official_template_stub or test_status"'`
- diag panel(执行**前 unset PYTEST_ADDOPTS**;panel 源码固定的真正绝对输入
  为 SPEC_FILE/CKPTS 三条原路径,复现须在位):
  - SPEC_FILE = /mnt/f/trading/teaching_pilot_prep_20261016/run_spec.json
  - CKPTS[initial] = /mnt/f/trading/unified_teaching_pilot_a1_20261016_output/initial.zip
  - CKPTS[final]   = /mnt/f/trading/unified_teaching_pilot_a1_20261016_output/final.zip
  `bash outer_teach.sh <root> <label> -- bash launch_diag.sh <root> <label> official <PY> <NEW_OUT>`

## 四、结论口径(最终)
- **有 s 条件响应;方向翻号能力未建立**(负 s 确定性 mode 仍正仓)。
- REBAL0 四态增加;解析 effective_flat 仅正 s 升≈11.67pp,负 s 降
  2.23/2.51pp;两侧内部形状共同偏正——**形状指标≠精确执行正
  概率/最优仓位**;256 抽样频率不代替精确概率;episode 收益的
  初末行情不配对(收益变化不能单归因训练)。
- **文档覆盖**:DIAGSPEC 旧"6 项测试/Z 称谓"由已验 v2 **7 项/
  beta_survival_Z 与 interior_category_mass 分列**口径覆盖。
- **范围限定**:root-reference/five-point 仅**冻结 V 条件/单区间
  局部**诊断,未认证总误差(not_certified);teaching pilot 单
  seed 观察级;全线不追加训练。


## 五、checkout 使用说明(命令仅说明复现,不构成执行授权)
```
CHECKOUT=<repo 检出目录>
F=$CHECKOUT/stage2_7_0/runner/unified_flat_calibration
P=$CHECKOUT/stage2_7_0/runner/teaching_pilot
D=$CHECKOUT/stage2_7_0/runner/diag_panel
export PILOT_REPO_SRC=$CHECKOUT/stage2_7_0/src
```
- root-reference / five-point:在 **F** 目录调用(launch_rootref.sh /
  outer_run.sh+launch_fivepoint.sh,参数见上节);
- teaching pilot:在 **P** 目录调用,且**必须**先
  `export PYTEST_ADDOPTS='-k "test_stub_flow_identity_compare or test_stub_fail_and_budget or test_real_evaluate_function or test_official_template_stub or test_status"'`;
- diag panel:**先 unset PYTEST_ADDOPTS**,完整包装:
  `bash "$P/outer_teach.sh" ROOT LABEL -- bash "$D/launch_diag.sh" ROOT LABEL official PY NEW_OUT`
  (三条绝对输入按本索引第二节恢复在位)。
