# SUMMARY — RouteC_AdmissionIntegrity_G5cVerification_NextGoal_v1(2026-09-20)

仓库:ceyirelehe47/freqai-rl-platform-audit @ route-c-stage2-6-1-repair17
观察锚 b2c345e → **本轮推送后远端 HEAD = a135031**
(b2c345e..271c77f..429f30a..a135031,4 个提交,Windows git 推送)。
R19 永久终态保持原样;R20 未启动;审计阈值与坐标零改动。

## A. 准入完整性收敛(工程,提交 271c77f)

外部审查确认的三个缺口(F1 完整集合 / F2 差分父证据 / F3 多文件
重复累计)已在签发/消费**同源唯一实现**收口,审查 probe 三负例
迁移为真实项目层测试:

- **record 格式升 v2**(`cur261-r17-candidate-regression-evidence-v2`):
  新必填 test_files(候选 Git 测试源树清单,验证方 ls-tree 自行
  重算)、collection(收集 node-ID)、execution(command/interpreter/
  cwd/rc==0)。v1 fail closed(核查:仓库无任何生产 v1 record)。
- **F1**:从候选树 Git blob 以 ast 静态推导应执行全集;要求
  base(collection)==静态全集、Counter(collection)==Counter(junit
  实际 testcase)、文件覆盖精确。计数一致但 ID 替换、遗漏根目录
  测试、集合不对应均拒。
- **F2**:差分父 record 递归经过同一完整核验(部署面除外——父为
  历史提交);父 JUnit 缺失/失败/被替换/未全量覆盖 ⇒ 子差分拒;
  parent==commit_a 显式拒。
- **F3**:同 resolve 路径(含 ../ 别名)、同 sha256 内容、跨文件
  testcase 重叠均拒;空 junit 拒;**合法分片(不重叠并集=全集)
  通过**(专项测试)。
- **部署面维度**:签发器子进程传 --deploy-root;消费端
  validate_admission 转发;部署 tests/route_c_stage2_6_1 扁平面
  字节须等于候选映射(与 guard.deployment_test_errors 同规则)。
- **测试**:admission substance 面 42 项全绿(6 个新测试类,含
  签发/消费沙箱端到端:合法完整证据签发→消费→二次拒;证据替换
  消费前拒;F1 证据签发器拒且零副作用;真实部署面零触碰);
  受影响消费方(supervision_unit/r17_r18_attempt/r17_r19_attempt/
  r18_launch_behavioral)全绿;parse_junit 元素级原负例全保留。
- **真实数据活体行使**(提交 429f30a):提交 271c77f 后全量回归
  (261: 2326 收集 = 2319 passed + 7 历史 skip,rc=0,52:59;
  262: 166 passed,rc=0),用**真实运行**构建 v2 record 并通过
  verify_regression_evidence(**含 deploy_root**):multiset
  2326==2326 精确、base(collection)==静态 1863 精确、部署面字节
  相等、skip 名单==HISTORICAL_SKIP_IDS。证据:
  artifacts/repair17/development/admission_regression_evidence_v2_
  closure/full_regression_20260920/(junit/collected/record/
  verify_summary)。
- **A4 计划内容职责**:沿实际调用链核对,现有合同已承担
  (audit/design plan create-only 锁+执行前重算、qualification
  六要素解锁、exposure/checkpoint 绑定、G5c 运行时 code sha ==
  部署字节本轮实测)——位置与验证表见
  stage2_6_1/report/route_c_stage2_6_1_admission_regression_evidence_v2.md §5。

## B. G5c 原件回收核验(只读;原件在部署机,副本已入 Git)

- 计划锁 digest 复算一致(g5cdp-e55e6100…);计划先于训练
  (plan mtime 08:38:13Z < 完成 08:42:31Z,lock 一次性);
- 代码身份:plan 内 code sha == 部署树 ppo262_g5c.py 字节;
  HEAD blob 差异仅为行尾(LF/CRLF,归一后逐字节相等);12 个
  依赖模块部署树==HEAD(事后闭包;运行时未逐依赖记录=如实
  报告的限制);
- 9 BC + 9 微调完整、全 run_pass、n_update_records=48/臂/seed、
  checkpoint verify 全过;**verdicts/arm_stats/sanity 从机读结果
  独立重算与存储值完全相等**;drops 0.396/0.481/0.427、
  0.044/−0.004/−0.001、0.067/0.255/0.168 与报告一致;
- 36 checkpoint 清单(逐文件 sha256)+ torch 只读重载 spot-check;
- **MISSING(如实)**:运行命令原文/解释器/cwd/stdout/rc 未存档
  (无日志文件、无 history)→ UNKNOWN;模型仅在部署机,不声称
  外部已取得;
- **结论收窄**(关联补充,原文不追改):高预算 CE 3/3 保留、
  "hinge 必要"不成立成立;但 epochs×lr 共变未分离,边际宽度是
  训练后相关量非已识别中介,B4 组合未被 G5c 直接否定,三 seed
  非正式。原件+清单+机读核验入
  stage2_6_2/artifacts/g5_ppo_damage_g5c/(g5/g5b 同入)。

## C. R19 卡点待审研究决定包(未启动任何新实验)

stage2_6_1/report/route_c_stage2_6_1_r20_research_decision_package.md:

- 冻结规则(双语料 CI95 包含叶,程序 FAIL 原样保留)与归因
  解释(边界涨落 vs 小系统分量)明确分离;两假设各自的证据
  边界与剩余缺口写明(确定性复现与权重重算不重做);
- 种子派生调用链定位:plan digest **不在**种子 payload
  (derive261_seed = stage/namespace/family/rung/pair/attempt);
  语料随生成代码身份变化(r15ap- 计划锁 7 模块闭包)= 隐蔽重抽
  面,现有防线是可见性+治理;建议 R20 处方加 redraw-intent
  自文档字段(不耦合 digest 进种子);
- **推荐方向**:预注册 K=5 显式坐标审计叶复制(判定阈值
  ≥4/≤2/3 抽前锁定;停止规则封顶;零科学暴露、分钟级),
  优于直接校准 analytic;
- 待拍板 D1-D4(设计批准/解释边界/redraw-intent/R19 终态确认);
  本轮未实施任何阈值/坐标/身份变更。

## 回归与边界

- 定向:admission substance 42 passed;受影响面 73+5 passed;
- 全量(绑定 271c77f,提交后跑):261 = 2319 passed + 7 skipped
  (0F/0E),262 = 166 passed;
- 上一轮 2296/161 等数字属历史记录,本轮真实收集数由树决定
  (2303→2326 = +23 个新测试);
- 未删/未弱化任何测试;R19/journal/冻结面/18 .pyc/trading/packs
  全部原样;归档 E 不追加 E2/E3。

## 存活进程与续跑点

- 无存活重型任务;WSL 部署树已同步本轮 7 文件(CR 已按 r17_sync
  规范剥离);/tmp 脚本性中间物已随 VM 清理,仓库内证据齐备;
- tmp 脚本(F:/trading/tmp_*.sh|py)用完可删;
- 外部阻塞不变:R20 决定=审查方;上传=用户;G6/G7=依赖 G4。
