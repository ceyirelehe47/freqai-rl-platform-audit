# S6 提交后 full 冷验失败记录（NOT_ADMITTED）

时间：2026-09-12 12:0x CST。HEAD=`82deed8`（E）。命令与 RUNBOOK §6 逐字一致：

```
python r17_v2_c13_regression_evidence.py verify \
  --package <AR>/full_regression/healthy_package
```

结果：**rc=1，ok=false，scope=full**

```json
"errors": [["candidate_drift", "candidate_drift: evidence is not a regular Git blob"]]
```

## 根因

1. S5 `probe_evidence.py` 的 `nested_directory_symlink` 负例在副本包内创建真实目录 symlink（指向该副本自身 supervision 目录，绝对路径）。
2. RUNBOOK §5 `cp -a "$WORK"/. "$AR"/` 将该 symlink 原样归档；WSL 侧 `git add`/commit 使其以 **mode 120000（symlink blob）** 进入 E（Windows 侧 git add 该路径直接 "Function not implemented"，无法用于此证据）。
3. 新 guard `r17_v2_c13_admission_guard.verify_candidate_history()` 对 C..HEAD 每个 evidence-only 提交逐路径要求 `ls-tree` 模式 ∈ {100644,100755} blob；120000 触发 `candidate_drift: evidence is not a regular Git blob`（guard 305 行）。
4. 该读者规则同时拒绝删除（D）与类型替换（T），且禁止 amend/force-push；E 已推送 ⇒ 本根的 full 冷读**永久不可再通过**。

## 判定

S0–S5 与 C/E 全部真实完成且通过（定向 157/0/0/0；全量 1832/0/0/7；健康包 C 时 full verify rc=0；八负例全中）。唯完成条件之一"E 后 full 冷验 ok=true/rc=0"不成立 ⇒ **本轮续接工程按任务书 §11 记 FAIL**。修复需助手下发新包（候选方向：探针输出中 symlink 以普通文件记录物化后再归档；或读者放宽为允许 120000；并启用全新证据子根，因本根已不可恢复）。

本文件与 post_E_verify/ 三件原件为失败阶段证据；REPORT.md 首页已同步更正为 FAIL。
