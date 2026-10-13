"""PSC_P0_v1 SEED_LEDGER 生成(纯哈希枚举;零资源消耗)。

枚举口径 = 实现实际调用点(p0spec.p0_seed 全部使用处):
- bank:每 purpose×pair 两个种子(spec=j0 / gen=j0,k1)
- sampler:8 内部目标
- bc_manual / bc_teacher:i=0,part∈{0,1}(两表 train/val;全部
  fit 复用同一表,不新增种子行)
- evalsample:6 模型 seed × 3 评估域(dev=1,1 / confirm=2,1 /
  horizon=3,1)
- bootstrap:ord(arm)∈{65,66} × k∈1..10(5 基线×2 模式)
"""

import json
from pathlib import Path

from rl_posctl.skill_p0.p0spec import (
    BANK_SIZES, BC_SEEDS, PPO_SEEDS, p0_seed)

used = {}
for purpose in BANK_SIZES:
    pairs = BANK_SIZES[purpose][0]
    for i in range(pairs):
        used[f"{purpose}[{i}].spec"] = p0_seed(purpose, i, 0)
        used[f"{purpose}[{i}].gen"] = p0_seed(purpose, i, 0, 1)
for ti in range(8):
    used[f"sampler[{ti}]"] = p0_seed("sampler", ti)
for part in (0, 1):
    used[f"bc_manual[0,{part}]"] = p0_seed("bc_manual", 0, part)
    used[f"bc_teacher[0,{part}]"] = p0_seed("bc_teacher", 0, part)
for ms in PPO_SEEDS:
    used[f"evalsample[{ms},1,1]"] = p0_seed("evalsample", ms, 1, 1)
    used[f"evalsample[{ms},2,1]"] = p0_seed("evalsample", ms, 2, 1)
    used[f"evalsample[{ms},3,1]"] = p0_seed("evalsample", ms, 3, 1)
for arm_ord in (ord("A"), ord("B")):
    for k in range(1, 11):
        used[f"bootstrap[0,{arm_ord},{k}]"] = p0_seed(
            "bootstrap", 0, arm_ord, k)

values = {}
for k, v in used.items():
    values.setdefault(v, []).append(k)
internal_collisions = {v: ks for v, ks in values.items() if len(ks) > 1}

old = {20261012, 3001, 0, 1, 2, 3, 5, 6, 7, 8, 11, 123, 20261014}
old |= set(range(270101, 270104))
old |= set(range(270201, 270204))
for tag in (1, 2, 3):
    ds = 20261012 * 1000 + tag
    old.add(ds)
    for i in range(4096):
        old.add(ds * 100000 + 3 * i + 7)

inter = sorted(set(used.values()) & old)
doc = {
    "p0_seed_formula": 'int(sha256("PSC_P0_v1|{purpose}|{i}|{j}|'
                       '{k}").hexdigest()[:16], 16)',
    "enumeration_basis": "实现调用点逐处(p0spec/p0bc/psc_p0_repr/"
                         "psc_p0_eval/psc_p0_confirm)",
    "n_named_seeds": len(used),
    "n_distinct_values": len(values),
    "internal_value_collisions": internal_collisions,
    "old_domain_description": (
        "MASTER_SEED=20261012 派生域(banks.domain_seed/episode_seed,"
        " 3 域×4096 索引)+ 仓库字面量(3001,20261012,"
        "270101-3/270201-3,小整数)"),
    "n_old_seeds": len(old),
    "intersection": inter,
    "zero_collision": not inter,
    "named_seeds_detail": used,
}
out_dir = Path("/mnt/f/trading/acceptance/PSC_P0_v1/plan")
(out_dir / "SEED_LEDGER.json").write_text(
    json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
lines = [
    "# PSC_P0_v1 SEED_LEDGER(事前冻结;零资源枚举生成)",
    "",
    "- 公式:`int(sha256('PSC_P0_v1|{purpose}|{i}|{j}|{k}')"
    ".hexdigest()[:16], 16)`",
    "- 枚举口径 = 实现调用点(bank spec/gen 各 1/pair、sampler 8、"
    "bc_manual 与 bc_teacher 各 i=0×part{0,1} 全 fit 复用、"
    "evalsample 6 seed×3 域、bootstrap ord(arm)×k1..10)",
    f"- P0 命名种子 {len(used)} 个,去重 {len(values)} 个;",
    "  值内重复组:" + json.dumps(internal_collisions,
                                  ensure_ascii=False),
    f"- 旧域种子 {len(old)} 个(MASTER_SEED=20261012 派生+字面量)",
    f"- 交集:{inter or '空'};零碰撞:{not inter}",
    "- 固定字面 seed:BC 270101/270102/270103;PPO "
    "270201/270202/270203(包固定,已并入旧域检查)",
    "",
    "完整明细(键→值)见 SEED_LEDGER.json named_seeds_detail。",
]
(out_dir / "SEED_LEDGER.md").write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")
print(json.dumps({k: doc[k] for k in (
    "n_named_seeds", "n_distinct_values", "zero_collision",
    "intersection")}, ensure_ascii=False))
