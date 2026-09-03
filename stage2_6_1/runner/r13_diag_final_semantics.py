# -*- coding: utf-8 -*-
"""R13 final qualification 失败诊断:重算 c2 三语义诊断,定位失败子项。"""
import json
from pathlib import Path

from rl_curriculum.curriculum261_qualification import (
    check_c2_context_observability,
    check_c2_local_cue_independence,
)
from rl_curriculum.curriculum261_r6_pairs import (
    check_c2_cue_payoff_separation,
)
from rl_curriculum.curriculum261_r13_calibration import (
    run_c2_matched_corpus_r13,
)
from rl_curriculum.curriculum261_r13_param_pack import (
    load_selected_pack,
)

ART = (Path.home() / "projects/crypto_rl/artifacts/"
       "route_c_stage2_6_1_repair13")

# final 的 c2_semantics 输入 = final matched blocks 的全部 pair records
# (namespace=qualification_r13;n=20)。六要素解锁后 qualification_r13
# 可访问(plan 已锁 + sealed 有效;复算只读,不再生成新 corpus —— 与
# final 相同坐标确定性重生成)。
plan = json.loads((ART / "qualification_plan_r13.json").read_text())
n_blocks = int(plan["final_sample_counts"]["c2_matched_blocks"])
pack = load_selected_pack(ART)

# 需要一个 final-role bundle:从 qualification_preprocessor_state.json
# 反序列化(serialize_envelope 的正式落盘)。
from rl_curriculum.curriculum261_r4_preprocessing import (
    RouteCPreprocessorV2,
)

v2 = RouteCPreprocessorV2.load_envelope(
    ART / "qualification_preprocessor_state.json")
from rl_curriculum.curriculum261_r13_routing import build_routing_r13

routing = build_routing_r13("final", v2)
final_v2 = routing.bundle(expected_role="final", context="diag")

matched = run_c2_matched_corpus_r13(
    final_v2, pack, "qualification_r13", n_blocks=n_blocks)
records = [blk.pair_records[rung] for blk in matched["blocks"]
           for rung in ("D0", "D1", "D2", "D3")]

for name, fn in (
        ("local_cue_independence", check_c2_local_cue_independence),
        ("context_observability", check_c2_context_observability),
        ("cue_payoff_separation", check_c2_cue_payoff_separation)):
    r = fn(records)
    body = {k: v for k, v in r.items()
            if isinstance(v, (bool, int, float))}
    print(f"{name}: pass={r.get('pass')} detail={body}")
    for k, v in r.items():
        if isinstance(v, dict):
            for k2, v2 in list(v.items())[:6]:
                if isinstance(v2, (bool, int, float, str)):
                    print(f"   {k}.{k2} = {v2}")
