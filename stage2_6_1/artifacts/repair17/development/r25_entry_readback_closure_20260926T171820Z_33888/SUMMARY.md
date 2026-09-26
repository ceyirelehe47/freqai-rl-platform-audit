# SUMMARY — RouteC_R25_EntryProvenance_ReadbackClosure_v1

轮次:R25 入口来源与既有数据复验收敛(发包基线 f66e6f5)。
代码候选:**48939c0ab73b160464f677f826fbfb2a6cc2ac98**(已提交,待 push)。
Work 目录:`stage2_6_1/artifacts/repair17/development/r25_entry_readback_closure_20260926T171820Z_33888/`。

## 一、四出口结果(分别签收,不合并)

### A. 正常入口与真实执行来源 — 已修,定向实测通过

- `cmd_plan_create` 未定义变量(p0/margin/alpha/r_analysis/
  planned_k_plan + 重复键)修复;真实 CLI `plan-create` 在新沙箱路径
  创建→同一加载路径读取;重复目标拒绝、写后 digest 复验、篡改拒绝;
  `--engineering` 标记计划永不启动 c01—c11(守卫实测)。
- 三角色区分:creator(plan 声明)/ execution(运行时实测入口+加载
  模块字节,manifest v2)/ reader(读取时实测,不倒填)。
- `execution-binding` 子命令运行前实测冻结(入口+7 生成模块+启动器,
  有界名单,注明非全传递闭包);`run-coordinate` 首次生成前核验;
  不符 → refusal 日志 + rc=3 + **零生成边界计数**(模块计数器 +
  进程内哨兵双重证明)+ 无坐标目录/无封存。

### B. reader 全链核对与推断隔离 — 已修,定向实测通过

- 链条:固定计划 → 封存成员集/安全路径/字节哈希 → manifest↔计划
  交叉关联(坐标/namespace/digest/块数/角色) → 双语料 block 覆盖与
  唯一性 → model seed 日程 + validation attempt first-pass/≤5 语义 →
  纯派生公式核算 seed(不触发生成)→ 事件类型/有限值/唯一身份/
  detected↔cue_read → 统计由事件累计(summary 仅交叉对拍)。
- 负例实测拒绝:c01 复制他坐标(含重封存)、语料交换、错 namespace、
  错 seed/attempt、缺块/缺成员/重复事件、非法数值/检出不符。
- 三类行为:无效→CLI 失败且**无主分类**;不足 K→仅描述;有效完整但
  来源未证明→**条件数值复算**标注 + 来源限制保留。
- v4 数学不变(P0=0.950431552876822,bootstrap 20000/seed 20270102,
  r=1.5,α=0.05,±0.003;B08 与 v4 直算逐字段相等)。

### C. 历史来源回收与子进程监测 — 双对象 MISSING(有界);监测已修+实测

- **C1**:`6aa456…` 创建入口与 `/mnt/f/trading/tmp_r25_batch.sh` 在
  原位置/F 盘全域(1829 py/sh 哈希扫)/Git 全对象(872 候选 blob)/
  WSL home+部署树+/tmp(8630 文件)/回收站/.bash_history 均未找到;
  未从聊天重建;新启动器不冒名旧脚本。时间关联推断:创建版本存活于
  部署树 11:xx–12:39Z,被最终回归 v2 同步覆盖,无备份。
- **C2 根因(证据链)**:task_tree 后代走查被 `if cur in out:
  continue` 短路(根恒被 pgid 命中→子进程永不展开→枚举退化 pgid-
  only;617b61a 与 HEAD 同字节=运行时实况);工作者被置于新进程组
  (与 GNU timeout 默认建组一致[推断,脚本字节缺失])→ 11 生成 PID
  0 次出现。修复:后代无条件展开(+合成回归测试);新启动器
  `r25_batch_launcher_v2.sh`(timeout --foreground 组内工作者+
  每坐标执行绑定)。
- **探针(经真实 r17_monitored_entry,非研究生成)**:run
  `20260926T174233_6232_1072`(business_rc=0,incidents=0,20 样本):
  w1 8 样本/7 次 CPU>0/RSS、w2 6/5、子+孙各 3 样本、w3 短超时 rc=124
  + `/proc` 子树核验 clean、无存活后代。旧 534 样本覆盖缺口与
  5,977/1,504/1 三种计数口径如实保留,不补写旧遥测。

### D. 旧数据只读复验 — 11/11 逐位一致

- 候选 reader(4e983c…)读原 plan+study(输入前后 79 文件哈希不变):
  integrity=valid、complete_k=true、problems=[];11 坐标 recall/SE 与
  独立复核参照一致(差<5e-10);聚合逐位复现 delta_bar=6.1466796774e-05、
  S_raw=0.0005675046775357165、S_analysis=0.0008512570163035747、
  CI90=[-0.001338726393960762,+0.0014616599875088836];事件计数
  285,225/142,597(val)/135,520(检出)/142,628(model) 对拍一致。
  primary 带条件复算标注;来源限制 not_established 如实保留。

## 二、验证与回归

- 定向:R25 测试文件 30/30 绿(部署树,WSL,Python 3.11);task_tree
  回归 + 既有 pgid 测试 2/2 绿。
- 全量:受监护 r21_full_collection_regression(commit-a=48939c0,
  run `20260926T174530_2562_390`,2026-09-26T17:45:33–18:35:56Z,
  business_rc=0,incidents=0):**2501 tests = 2494 passed + 7 skipped
  (历史允许表),0 failures/0 errors**;junit/audit/record 全件入库
  (`full_regression_v1/`,record sha 18a2007c…)。

## 三、Git

- 候选提交 48939c0(代码面:入口/sampler/launcher/worker/sync/测试)。
- 证据提交:<<待填>>(work 目录+监护 runs+回归产物;不含代码变更)。
- push/ls-remote 回执:见 `git_receipts/`。

## 四、明确不做/保留

不重采 c01–c11、不加研究坐标、不启动 R20/资格/训练;MC/global-K/
tail/非劣效保持 NOT_RUN;R24 CLOSED PASS、C 数学、R19 终态不重开;
旧 plan/manifest/研究原件零字节改动;旧 run 遥测不补写。历史来源
缺失为明确遗留限制;R25 整轮终态由独立审查决定,本轮不自判
CLOSED PASS。
