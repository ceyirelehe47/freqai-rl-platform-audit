# C2 子进程监测覆盖修复记录(RouteC_R25_EntryProvenance_ReadbackClosure_v1)

## 根因(证据链,不预设)

1. **源码事实**:`r17_guest_sampler.task_tree` 的根后代走查被
   `if cur in out: continue` 短路——supervisor 注册的根(business
   leader)恒先被 pgid 集合命中,其子进程永不展开。任务枚举实际退化为
   pgid-only。该 bug 在 617b61a 与 HEAD 同字节(f62198…),即 2026-09-26
   研究批次运行时的实际执行面。
2. **原件事实**(run `20260926T132814_7514_448`):534 条 guest sample
   的 tasks 仅出现 pid 502(bash,pgrp 502,533 次)与 pid 1117
   (python,pgrp 502,末次 1 次);11 个坐标 manifest 生成 PID
   (505/555/600/648/695/738/781/831/897/980/1072)出现次数均为 0。
   business stdout 严格顺序;末尾 cold-read 为裸前台 python(组内)故
   可见。
3. **机制闭合[推断部分]**:旧批次脚本(字节缺失,C1 记录 MISSING)将
   每个工作者置于新进程组——与 GNU `timeout` 默认建组行为一致;在
   pgid-only 枚举下整体不可见。无法确证具体包装器,但唯一同时满足
   全部观测的最小机制 = "工作者脱离 pgid 502"+"后代走查失效"。

## 修复(最小改动,双层)

1. `r17_guest_sampler.task_tree`:根后代无条件展开(seen 防重复);
   回归测试 `test_task_tree_root_in_pgid_still_expands_descendants`
   (合成表:根在 pgid 集内时子/孙仍入选,组外进程不入选)。
2. 新启动器 `runner/r25_batch_launcher_v2.sh`(本轮代码候选;不是
   旧 tmp_r25_batch.sh 的复原):工作者用 `timeout --foreground`
   留在启动器进程组内——pgid 口径直接覆盖,同时保证监护停止保护的
   组信号可达;每个 run-coordinate 前经 `execution-binding` 实测冻结
   执行绑定,不符零生成拒绝;不放宽任何阈值/停止保护/历史策略。

## 工程探针(经真实启动链,非研究生成)

- 启动链:`r17_monitored_entry.sh engineering --max-seconds 600 --
  bash r25_batch_launcher_v2.sh probe r25_worker_probe.py <logdir>`
  (R17_PROJECT_ROOT=部署树;conda freqtrade-rl python)。
- 监护 run:`20260926T174233_6232_1072`(2026-09-26T17:42:33Z 起,
  business_rc=0,incidents=0,20 条 guest sample)。
- 替身工作者 `r25_worker_probe.py`:无研究生成模块 import;burn 模式
  ~30% 单核 + 1Hz 心跳;--spawn-child 派生子(子再派生孙);SIGTERM
  责任清理契约(timeout --foreground 语义:工作者负责终止子进程)。

### C02 结果(任务级覆盖)

| 对象 | 采样出现 | cpu_sec_delta>0 | RSS | pgrp |
|---|---:|---:|---|---|
| w1(burn 45s,含子/孙) | 8/20 | 7 | 有 | 1114(启动器组) |
| w2(burn 30s) | 6/20 | 5 | 有 | 1114 |
| w3(sleep) | 3/20 | 0(睡眠,预期) | 有 | 1114 |
| 子进程 | 3/20 | 0(睡眠,预期) | 有 | 1114 |
| 孙进程 | 3/20 | 0(睡眠,预期) | 有 | 1114 |

实际工作者实例在多个采样周期出现且带真实 CPU/RSS——与旧 run
"工作者 0 次出现、只见 shell"的签名形成对照;该旧覆盖缺口(534 条
样本、11 生成 PID)永久保留为历史事实,本轮不补写旧遥测。

### C03 结果(短超时/停止正反例)

- 正例:w3(sleep 300s,带子/孙)经 `timeout --foreground 12` →
  rc=124;`--check-subtree-gone` 独立核验 `/proc` 子树 →
  `{"subtree_check":"clean","target_pid":1139}`(工作者 SIGTERM →
  终止子 → 子终止孙;无存活后代,非仅"shell 已返回")。
- 反例(正常完成):w1 rc=0(45s,子/孙自然退出)、w2 rc=0;
  `R25BATCH DONE fail=0`。
- 只操作本探针拥有的进程;无资源耗尽;单监护单例(flock)全程独占。

### 边界

- 告警口径勘误(按任务书):旧 run `20260926T132814_7514_448` 的
  alerts.jsonl 有 5,977 条 alert_delivered / 1,504 个不同
  incident_id 字符串(kind 均为 progress_stall)/ summary 最终保留
  1 条 incident。三者不是同一计数,不得再写成"只有一次坐标切换
  误报";也未证明是 5,977 个独立故障。本轮未重制告警风暴。
- 探针是新工程验证,不追认旧 run 遥测完整。
