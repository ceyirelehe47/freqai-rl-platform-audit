"""Generate PSC_P0_v1 resource table + RUN_COMMANDS from ledger(零资源)。"""

import json
from collections import Counter
from pathlib import Path

RUNS = Path("/mnt/f/trading/acceptance/PSC_P0_v1/runs")
commit = Counter()
by_tag = Counter()
n_events = 0
for line in (RUNS / "psc_p0_v1_ledger.jsonl").read_text(
        encoding="utf-8").splitlines():
    if not line.strip():
        continue
    n_events += 1
    r = json.loads(line)
    if r.get("event") == "commit":
        for k, v in r.get("amounts", {}).items():
            commit[k] += v
            by_tag[(k, r.get("tag", "?").split(":")[0])] += v

BUDGET = {
    "ppo_steps_main": 786_432, "ppo_steps_smoke": 2_048,
    "ppo_steps_techretry": 65_536, "ppo_learn_main_attempts": 6,
    "ppo_learn_smoke_attempts": 4,
    "ppo_learn_techretry_attempts": 2,
    "ppo_optimizer_steps": 33_360, "eval_steps": 524_288,
    "gen_calls": 2_048, "episodes": 1_024, "bc_fits": 14,
    "bc_epochs": 8_192, "bc_minibatch_updates": 8_192,
    "supervised_rows": 8_192, "dist_sample_actions": 1_048_576,
    "bootstrap_draws": 1_000_000, "evidence_kib": 524_288,
    "ppo_steps_total": 854_016, "ppo_learn_total": 12,
    "economic_total": 1_378_304,
}

rows = []
for k in ("ppo_steps_main", "ppo_steps_smoke", "ppo_steps_techretry",
          "ppo_learn_main_attempts", "ppo_learn_smoke_attempts",
          "ppo_learn_techretry_attempts", "ppo_optimizer_steps",
          "eval_steps", "gen_calls", "episodes", "bc_fits",
          "bc_epochs", "bc_minibatch_updates", "supervised_rows",
          "dist_sample_actions", "bootstrap_draws", "evidence_kib"):
    rows.append((k, commit.get(k, 0), BUDGET[k]))
ppo_total = sum(commit.get(k, 0) for k in (
    "ppo_steps_main", "ppo_steps_smoke", "ppo_steps_techretry"))
learn_total = sum(commit.get(k, 0) for k in (
    "ppo_learn_main_attempts", "ppo_learn_smoke_attempts",
    "ppo_learn_techretry_attempts"))
econ_total = ppo_total + commit.get("eval_steps", 0)
rows += [("ppo_steps_total(derived)", ppo_total, BUDGET[
    "ppo_steps_total"]),
         ("ppo_learn_total(derived)", learn_total, BUDGET[
             "ppo_learn_total"]),
         ("economic_total(derived)", econ_total, BUDGET[
             "economic_total"])]

lines = [
    "# PSC_P0_v1 资源总表(账本 JSONL 全量重放实数)",
    "",
    f"- 账本事件总数:{n_events}(含 pytest 计量与主/辅全部消费)",
    "- 上限=包 SCOPE_AND_BUDGET;实耗=commit 合计;派生总项按分项复算",
    "",
    "| 指标 | 实耗 | 上限 |", "|---|---:|---:|",
]
for k, v, cap in rows:
    lines.append(f"| {k} | {v:,} | {cap:,} |")
lines += ["", "## 按来源粗分(tag 前缀,同账本)", ""]
for (k, tag), v in sorted(by_tag.items()):
    lines.append(f"- {k} ← {tag}: {v:,}")
out = Path("/mnt/f/trading/acceptance/PSC_P0_v1/evidence/"
           "RESOURCE_TABLE.md")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines[:40]))
