#!/usr/bin/env bash
# 补齐规范证据文件:stage1_second_run_summary + model_manifest
set -euo pipefail
PROJ="$HOME/projects/crypto_rl"
ART="$PROJ/artifacts/freqai_rl_platform_audit"
MDIR="$PROJ/user_data/models/freqai-rl-platform-audit-2026-7"
exec > >(tee -a "$HOME/projects/crypto_rl/logs/freqai_rl_platform_audit/12_evidence.log") 2>&1
echo "===== 12_evidence 开始 $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
source "$PROJ/activate-freqtrade.sh"

cat > "$ART/stage1_second_run_summary.md" <<'EOF'
# 阶段一第二次/第三次运行摘要(模型保存与重载机制验证)

同一 identifier/config/timerange/strategy/freqaimodel/数据,新进程分别再跑两次:

## 第二次运行(预测缓存分支)
- 日志:logs/freqai_rl_platform_audit/07_reload.log
- 行为:5× "Found backtesting prediction file" → 直接复用 backtesting_predictions feather;
  全程无 "Starting training"、无模型加载。
- 耗时 49s(对比首跑训练 107s);回测结果与首跑一致(7 trades / −2.13%)。
- 文件级对比(vs 首跑基线):新增 0、删除 0、变更 1(仅 run_params.json)。
  → "第二次更快"的原因是预测缓存,不是模型重载。

## 第三次运行(删除预测缓存、保留模型 → 模型重载分支)
- 事先删除 backtesting_predictions/*.feather(本任务自己生成的文件)。
- 行为:5× "Could not find backtesting prediction file" → 模型文件存在
  (无任何 "Could not find model" / "Starting training")→ data_drawer.load_data()
  从 sub-train-*/cb_btc_<ts>_model.zip 以 SB3 MODELCLASS.load 重载 → 重新推理并
  重建预测缓存。
- 耗时 16s;结果仍为 7 trades / −2.13%。
- 文件级对比:5 个预测 feather 重新生成(mtime/sha 变化),全部模型 zip 的
  SHA-256 与首跑完全一致(零字节级未变),证明是"重载"而非"重训练"。

## 机制结论(源码 freqai_interface.py:329-340, 366-400;data_kitchen.py:928-959)
FreqAI 回测优先复用预测缓存(不看模型);缓存失效才考虑模型;模型在才重载;
模型不在才训练。缓存有效性只校验"文件存在 + 行数一致 + 含 date 列",
不校验策略/奖励/seed —— 跨实验复用同一 identifier 有静默复用旧预测的风险。
EOF
echo "written stage1_second_run_summary.md"

python - <<'PYEOF'
import glob
import hashlib
import os
from datetime import datetime, timezone

MDIR = os.path.expanduser(
    "~/projects/crypto_rl/user_data/models/freqai-rl-platform-audit-2026-7"
)
lines = ["# 模型清单(3ac 审计 identifier)", "",
         "- identifier: freqai-rl-platform-audit-2026-7",
         f"- 生成: {datetime.now(timezone.utc).isoformat()}",
         "", "| 文件 | 大小(bytes) | mtime(UTC) | SHA-256(完整) |", "|---|---|---|---|"]
for p in sorted(glob.glob(f"{MDIR}/**/*", recursive=True)):
    if os.path.isfile(p):
        st = os.stat(p)
        sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
        mt = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")
        lines.append(f"| {os.path.relpath(p, MDIR)} | {st.st_size} | {mt} | `{sha}` |")
with open(os.path.expanduser(
    "~/projects/crypto_rl/artifacts/freqai_rl_platform_audit/model_manifest.md"), "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"model_manifest.md: {len(lines) - 4} files")
PYEOF
echo "===== 12_evidence 完成 ====="
