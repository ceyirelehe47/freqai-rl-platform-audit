# C 出口记录:根退出后的已登记后代核验

轮次:RouteC_R25_BindingAndDescendantClosure_v1;候选 721b314。
被修复反例 = 独立审查 §4.2(C3-orphan-check:根 PID 890 退出、
子 PID 900 存活,旧 checker 返回 clean)。

## 机制(登记→核验→清理,三者分离)

1. **退出前登记**(`r25_worker_probe.py`):创建子/孙后立即把本任务
   实际拥有的实例身份(pid + /proc stat field22 starttime ticks)
   写入持久 registry 文件(可靠持有者,不随根退出消失);先握手
   (子输出 child/grandchild pid)后登记,不靠 sleep 抢竞态。
   registry 含 created_descendants / no_descendants_verified 显式
   声明(未创建后代时由创建者记录依据;空登记不默认成功)。
2. **只读核验**(`--check-registry`,永不发信号):逐实例判定,不依赖
   根存在:
   - /proc 消失 → dead_gone;
   - 存活且 starttime 一致 → alive(任何一例 → verdict=leaked_alive,
     rc=3,逐实例列出);
   - state Z → zombie_unreaped(rc=2,已终止待回收,不算仍在计算,
     也不写成已回收);
   - starttime 不一致 → pid_reused_old_dead(旧实例必已结束;不向
     新实例发信号、不当作旧存活;clean 但显式标注);
   - 无法读取 → unobservable(rc=5);
   - registry 缺失/坏 JSON/instances 空/条目缺 pid 或 start_ticks/
     无后代声明缺依据 → rc=4,不 clean。
3. **驱动器清理**:测试/launcher 的 finally 只对 (pid, start_ticks)
   双匹配的自有实例发信号;不按进程名/裸 PID/宽泛 PGID;无全局
   killall。

## 验收映射(定向测试 9/9 绿;全部真实 Linux 进程)

| ID | 测试 | 结果 |
|---|---|---|
| C01 | burn 3s 带子/孙 → 全 dead_gone clean(root+child+grandchild 三实例);sleep 无子 → clean(created_descendants=false + verified 依据) | rc=0 |
| C02 | orphan 根退出,子/孙仍活(检查前后同实例存活握手)→ checker rc=3 leaked_alive,alive={child,grandchild},root=dead_gone;检查后两实例仍存活同 ticks(证 checker 未自己清理) | rc=3 |
| C03 | 同夹具:SIGKILL 中间父,孙成孤儿仍活 → rc=3,alive={grandchild},child=dead_gone | rc=3 |
| C04 | 登记文件缺失/坏 JSON/instances 空/条目无 start_ticks/无后代声明缺依据 → 五变体全 rc=4 | rc=4 |
| C05 | 活进程登记错误 starttime(确定性实例错配夹具,非内核级真实复用,已注明)→ clean + pid_reused_old_dead;checker 后该进程仍存活同 ticks(只读证明) | rc=0 |
| C07 | fixture finally 按 (pid,start_ticks) 清理 child/grandchild;收尾 /proc 直读无本测试未回收直接子进程(直读避免 ps 自观察伪影) | 通过 |
| C06 | 真实 launcher+监护(run 20260926T212149_1124_424) | 见下 |

## C06 集成证据(run 20260926T212149_1124_424,business_rc=0,
incidents=0,19 条 guest_sample)

- launcher probe 三工作者均带 --registry-out;w1(burn45s+子/孙)→
  checker clean(root 473/child 474/grandchild 475 全 dead_gone);
  w2(burn30s 无子)→ clean;w3(sleep+子/孙,timeout --foreground 12)
  → **原始 rc=124 保留**,checker clean(494/495/496 全 dead_gone)
  ——不只凭 124,登记实例逐一确认。
- 运行中采样覆盖:w1 8 样本(CPU>0×7)、w2 6 样本(×5)、
  w1-child/grandchild 各 8 样本、w3 及其子/孙各 2 样本(12s 窗口
  预期);工作者真实 CPU/RSS 进入任务级遥测。
- checker 输出原件:`c06_probe/logs/w{1,2,3}_check.json`;
  监护 run 全件(27 required 成员)在 run_supervision/runs/。

## 边界

- 本轮工程探针不是旧批次遥测;旧 run 534 样本覆盖缺口与
  5,977/1,504/1 告警计数口径保持上轮勘误,不补写。
- C05 为确定性观察夹具(明确非内核级真实 PID 复用实测)。
