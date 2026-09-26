# SUMMARY — RouteC_R25_BindingAndDescendantClosure_v1

轮次:R25 执行绑定与后代退出检查收敛(发包基线 4bbb31c)。
代码候选:**990dbcfc247d2f3eda107fb3c257c561a3aac748**(721b314 实现 +
C07 断言口径修正;已提交,待 push)。

修复审查 §2.2/§2.3 两组复现反例:

- **强制**:直接 CLI 与批次 launcher 同一规则;缺参数/空值/文件不
  存在/不可读/不可解析 → rc=3 + refusal 日志(原因/实测身份/
  generation_boundary_calls=0),不创建坐标目录、不写 manifest/
  事件/成功 seal。工程 smoke 同样必须绑定;`--allow-smoke`/
  `engineering_use` 无任何免检通道(A06)。
- **锚定当前计划**:绑定创建端 `--plan` 必填(锚=经 digest 复验的
  plan_digest);运行端比对锚与本次实际加载计划——甲计划的合法
  绑定用于乙计划拒绝(A02,绑定文件自身完全自洽);伪造无锚绑定
  (重算 binding_sha256)拒绝(A03);计划移位同字节通过(A05)。
- **不自动重签**:失败不重签/不覆盖/不补锚;launcher 预存绑定 →
  rc=3 不覆盖(A07);坏坐标零生成、DONE fail=1、绑定保留。
- 既有入口/模块/启动器身份防线保持(A04);真实旧研究计划只读
  副本 + c01 + 缺绑定 → 零生成拒绝(A01,refusal 记录
  boundary_calls.total=0)。
- 测试:入口测试 42 项全绿(含新增 A01-A08 矩阵);细节见
  `A_BINDING_RECORD.md`。

## 二、C 出口:根退出后核验已登记后代 — 完成

修复审查 §4.2 复现反例(根 PID 消失 → checker 把后代当空判 clean):

- **登记**:worker 创建子/孙后立即把自有实例身份(pid+/proc
  starttime ticks)写入持久 registry(先握手后登记;无后代须显式
  声明依据,空登记不默认成功)。
- **只读核验** `--check-registry`:逐实例、不依赖根存在;alive
  rc=3 / zombie rc=2 / 登记缺失不完整 rc=4 / unobservable rc=5 /
  clean rc=0;pid 复用按 starttime 区分(不向新实例发信号)。
- **检测与清理分离**:checker 永不发信号;驱动器 finally 只按
  (pid, start_ticks) 双匹配清理自有进程;无全局 kill。
- 真实进程正反例 9/9 绿:C01 干净正例(含子/孙逐实例 dead_gone);
  C02 根死子/孙活(检查前后同实例存活握手)拒绝;C03 子死孙活拒绝;
  C04 五类坏登记拒绝;C05 确定性实例错配(标注非内核级真实复用)
  不误杀不误判;C07 收尾无自有子进程残留(/proc 直读)。
- 细节见 `C_DESCENDANT_RECORD.md`。

## 三、C06 集成(真实 launcher + 监护)

run `20260926T212149_1124_424`(business_rc=0,incidents=0,
19 guest_sample):w1 8 样本(CPU>0×7)/w2 6(×5)/子/孙各 8 或 2
样本可见;w3 短超时**原始 rc=124 保留**;三工作者 checker 全
clean(w1:473/474/475;w2:486;w3:494/495/496 全 dead_gone)。
checker 原件 `c06_probe/logs/w*_check.json`;监护 run 全件入库。

## 四、验证与回归

- 定向:入口+registry 测试 51/51 绿(WSL 部署树,Python 3.11);
  task_tree 回归 2/2 绿。
- 全量(v1,失败原件保留):run `20260926T212354_1984_392`(候选
  721b314)rc=4 —— 唯一失败 = C07 断言口径过强(断言 pytest 进程
  无任何直接子进程,被共享套件其他模块的自有子进程打破;
  2514 passed + 7 skipped);`full_regression_v1_FAILED_c07scope/`
  保留原件。修正 = C07 收窄为本模块自有实例追踪(990dbcf)。
- 全量(v2,最终):run `20260926T220905_5450_537`(候选 990dbcf,
  2026-09-26T22:09–22:53Z,business_rc=0,incidents=0):
  **2522 tests = 2515 passed + 7 skipped(历史允许表),
  0 failures/0 errors**;record sha 9defe5a2…,全件入库
  (`full_regression_v2/`)。

## 五、旧件保护

旧 plan/study/smoke/回归/监护原件零改动(轮初 freeze 对照:
plan df7d04d/study 96df8f/smoke 3ef2fc 与 BASELINE 一致);不重跑
c01-c11;历史来源 not_established 与 MISSING 限制保留;不追认旧
任务级监护;不启动正式 R20/资格/训练。

## 六、Git 与回传

- 候选提交 721b314(代码面);证据提交:<<待填>>;push 回执:
  见 `git_receipts/`。
- 回传 ZIP:`RouteC_R25_BindingAndDescendantClosure_v1_RETURN_TO_CHATGPT.zip`
  (SHA-256 见同目录 .sha256.txt)。
