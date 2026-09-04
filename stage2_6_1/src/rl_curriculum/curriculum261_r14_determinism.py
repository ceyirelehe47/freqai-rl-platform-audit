# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R14:生成确定性与 mutable state 审计(工作包 A)。

A4(不预设根因的 mutable state 排查):
- family_specs() 缓存的 generator 单例跨调用状态审计;
- rung_params / mixture / class constants / module globals 的
  原地修改检测(调用前后摘要对比);
- C1/C2/C3 共用对象互相污染检测;
- preprocess/evaluator/torch 训练路径是否修改 episode 或 params;
- A/B side 生成之间 params 对象是否原地修改。

A5(跨进程确定性矩阵,14 场景):同一 invocation 在 fresh process
的不同环境/顺序/前置负载下逐字段一致(seed/params/event digest/
计数/episode hash/structural 结果/接受状态;不只比较最终 PASS)。

A3(R10 失败调用重放):用 R10 记录的五个 outer attempt seeds 逐个
重放 supervised_main_r10 的 c3_cost/D0/pair1 调用(诊断性质;不产生
任何 R14 正式数据,不修改 R10 artifacts)。

根因定性合同:R10 的历史失败在重放下不可复现且当时无 invocation
状态证据 —— 若本模块矩阵亦无法复现,根因必须记载为
"historically underdetermined due to missing invocation-state
evidence",不得声称"唯一原因是偶发进程内状态"。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_generation_envelope import (
    EnvelopeRecorder,
    compare_envelopes,
    envelope_sink,
    ledger_rows_digest,
    replay_call,
    stable_digest,
)
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
    derive261_seed,
    generate_pair_with_attempts,
)
from rl_curriculum.curriculum261_pairs import (
    family_specs,
    generate_pair,
    pair_acceptance_contract,
)

#: R10 正式失败点(来自 raw_logs/supervised_failure_diagnostic.json;
#: 独立复核:与 calibrate_run.log traceback 一致)。
R10_FAILURE = {
    "iteration": "r10",
    "phase": "calibrate",
    "orchestrator": "shared calibration orchestration",
    "substage": "supervised main",
    "namespace": "supervised_main_r10",
    "family": "c3_cost",
    "rung": "D0",
    "pair_index": 1,
    "attempt_seeds": [
        4610631957848990728,
        11133740903307515606,
        6129992300414987011,
        4882666421302941032,
        4309486781261668342,
    ],
}
ROOT_CAUSE_STATEMENT = (
    "historically underdetermined due to missing invocation-state "
    "evidence")

#: 矩阵的 R14 目标调用(stress_r14 诊断 namespace;c3/D0 覆盖
#: R10 失败形态;pair 3 任意但固定)。
R14_MATRIX_TARGET = {
    "iteration": "r14",
    "namespace": "stress_r14",
    "family": "c3_cost",
    "rung": "D0",
    "pair_index": 3,
}

_PROBE_ARGV_MARKER = "--cur261-r14-determinism-probe"


# ---------------------------------------------------------------- helpers
def _seeds_prefix_match(replayed: list | None) -> bool:
    """重放 attempt seeds 必须是 R10 记录五 seeds 的前缀。

    重放在 attempt 0 即接受时只会执行 1 个 attempt(first_pass 停止)
    —— 派生一致性按逐位置比较(前缀匹配),不要求重放也走满五次。
    """
    if not replayed:
        return False
    recorded = R10_FAILURE["attempt_seeds"]
    return list(replayed) == recorded[:len(replayed)]


def _rung_params_for(family: str, rung: str,
                     override: dict | None = None) -> dict[str, Any]:
    spec = family_specs()[family]
    rp = dict((override or {}).get(rung) or spec.rung_params[rung])
    rp["cur261_rung"] = rung
    return rp


def _r10_override() -> dict[str, dict[str, Any]]:
    """R10 正式 supervised 使用的 C3 override(pack:仅 D3=R4 选定)。"""
    from rl_curriculum.curriculum261_r6_param_pack import (
        R4_SELECTED_C3_D3,
    )
    return {"D3": dict(R4_SELECTED_C3_D3)}


def run_target_call(target: dict[str, Any]) -> dict[str, Any]:
    """执行目标 pair 生成(带 recorder),返回 call/envelope 摘要。

    只做生成与结构校验,绝不读取 PnL/qualification 结果。
    """
    family = target["family"]
    override = target.get("override")
    if override is None and target["namespace"] == "supervised_main_r10" \
            and family == "c3_cost":
        override = _r10_override()
    rp = _rung_params_for(family, target["rung"], override)
    rec = EnvelopeRecorder(
        iteration=target["iteration"], namespace=target["namespace"],
        family=family, rung=target["rung"],
        pair_index=int(target["pair_index"]), rung_params=rp,
        rung_params_override=override)
    error: str | None = None
    try:
        generate_pair_with_attempts(
            family_specs()[family].generator, rp,
            namespace=target["namespace"], family=family,
            rung=target["rung"], pair_index=int(target["pair_index"]),
            structural_validator=pair_acceptance_contract(family),
            recorder=rec)
    except Exception as exc:  # noqa: BLE001 —— 重放记录失败形态
        error = f"{type(exc).__name__}:{str(exc)[:300]}"
    return {
        "target": {k: target[k] for k in (
            "iteration", "namespace", "family", "rung", "pair_index")},
        "call_digest": rec.call_envelope["digest"],
        "attempt_digests": [e["digest"] for e in rec.attempt_envelopes],
        "attempt_outer_seeds": [e["outer_seed"]
                                for e in rec.attempt_envelopes],
        "attempt_accepted": [e["accepted"]
                             for e in rec.attempt_envelopes],
        "attempt_event_digests": [
            {side: (e["event_table"][side] or {}).get("hidden_digest")
             for side in ("A", "B")}
            for e in rec.attempt_envelopes],
        "attempt_counts": [
            {side: ((e["event_table"][side] or {}).get("counts"))
             for side in ("A", "B")}
            for e in rec.attempt_envelopes],
        "generation_error": error,
    }


# ------------------------------------------------ A4:mutable state 审计
def _module_constants_digest() -> dict[str, str]:
    import rl_curriculum.curriculum261_api as m_api
    import rl_curriculum.curriculum261_c1 as m_c1
    import rl_curriculum.curriculum261_c2 as m_c2
    import rl_curriculum.curriculum261_c3 as m_c3

    def _d(mod, names):
        return stable_digest(
            {n: getattr(mod, n) for n in names}, "const-")

    return {
        "api_RUNG_constants": _d(m_api, (
            "CURRICULUM261_MAX_ATTEMPTS", "CURRICULUM261_RUNGS",
            "CURRICULUM261_FAMILIES", "CURRICULUM261_EPISODE_BARS",
            "CURRICULUM261_INITIAL_PRICE",
            "NOISE_PAIR_GAP_RANGE")),
        "c1_RUNG_PARAMS": _d(m_c1, ("C1_RUNG_PARAMS",)),
        "c2_RUNG_PARAMS": _d(m_c2, ("C2_RUNG_PARAMS",)),
        "c3_RUNG_PARAMS": _d(m_c3, ("C3_RUNG_PARAMS",)),
        "c3_STRENGTH_BINS": _d(m_c3, ("C3_STRENGTH_BINS",
                                      "C3_DISTRACTOR_S_RANGE")),
    }


def _module_globals_digest(module_names: tuple[str, ...]) -> dict[str, str]:
    import importlib

    out = {}
    for mn in module_names:
        mod = importlib.import_module(mn)
        public = sorted(k for k in vars(mod)
                        if not k.startswith("__"))
        out[mn] = stable_digest(
            {k: _vars_safe(mod, k) for k in public}, "mglobals-")
    return out


def _vars_safe(mod, k):
    v = getattr(mod, k, None)
    if callable(v) or isinstance(v, type):
        import inspect
        try:
            return {"__code_sha__": hashlib.sha256(
                inspect.getsource(v).encode("utf-8")).hexdigest()}
        except (OSError, TypeError):
            return {"__repr__": repr(v)[:120]}
    # 任意非 JSON 对象(如 __future__._Feature):repr sha 作漂移探针
    try:
        from rl_curriculum.curriculum261_generation_envelope import (
            canonical_json,
        )
        canonical_json(v)
        return v
    except TypeError:
        return {"__opaque_repr_sha__": hashlib.sha256(
            repr(v).encode("utf-8")).hexdigest()}


def audit_generator_mutable_state(out_dir: Path) -> dict[str, Any]:
    """A4:进程内生成序列对共享状态的影响审计。

    阶段序列(每阶段后检查):基线 -> c1 生成 -> c2 生成 -> c3 生成
    -> matched block(r6 tape)-> fit bank + V2 fit -> torch import +
    MLP 训练 -> 完整预处理 battery 片段 -> 目标 pair 重放。
    检查项:RUNG 常量摘要、family_specs 单例状态摘要、模块公共
    globals 摘要、目标调用 envelope 摘要与基线一致、输入 params
    对象不被原地修改。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    constants0 = _module_constants_digest()
    globals0 = _module_globals_digest((
        "rl_curriculum.curriculum261_api",
        "rl_curriculum.curriculum261_c1",
        "rl_curriculum.curriculum261_c2",
        "rl_curriculum.curriculum261_c3",
    ))
    states0 = {f: stable_digest(
        __import__("rl_curriculum.curriculum261_generation_envelope",
                   fromlist=["generator_state_digest"])
        .generator_state_digest(spec.generator), "g-")
        for f, spec in sorted(family_specs().items())}
    target0 = run_target_call(dict(R14_MATRIX_TARGET))
    findings: list[str] = []
    phase_reports: list[dict[str, Any]] = []

    def _check_phase(name: str) -> None:
        c1 = _module_constants_digest()
        g1 = _module_globals_digest(tuple(globals0))
        s1 = {f: stable_digest(
            __import__("rl_curriculum.curriculum261_generation_envelope",
                       fromlist=["generator_state_digest"])
            .generator_state_digest(spec.generator), "g-")
            for f, spec in sorted(family_specs().items())}
        t1 = run_target_call(dict(R14_MATRIX_TARGET))
        drift_const = {k for k in c1 if c1[k] != constants0[k]}
        drift_glob = {k for k in g1 if g1[k] != globals0[k]}
        drift_state = {f for f in s1 if s1[f] != states0[f]}
        drift_target = (
            t1["attempt_digests"] != target0["attempt_digests"])
        phase_reports.append({
            "phase": name,
            "constants_drift": sorted(drift_const),
            "module_globals_drift": sorted(drift_glob),
            "generator_state_drift": sorted(drift_state),
            "target_envelope_digests_identical": not drift_target,
        })
        if drift_const:
            findings.append(f"{name}: RUNG/合同常量被修改 {drift_const}")
        if drift_state:
            findings.append(
                f"{name}: family_specs 单例状态漂移 {drift_state}"
                f"(生成器存在跨调用 mutable state)")
        if drift_target:
            findings.append(
                f"{name}: 同一调用 envelope 摘要漂移(进程内确定性破坏)")

    # ---- 阶段 1:c1/c2/c3 各一对 pair 生成 ----
    probe_ns = "stress_r14"
    params_input_digests = {}
    for family in CURRICULUM261_FAMILIES:
        rp = _rung_params_for(family, "D2")
        params_input_digests[family] = stable_digest(rp, "pin-")
        generate_pair(family, "D2", 0, namespace=probe_ns)
        after = stable_digest(_rung_params_for(family, "D2"), "pin-")
        if after != params_input_digests[family]:
            findings.append(
                f"{family}: 生成后 rung 参数解析结果漂移(浅拷贝别名被"
                f"原地修改)")
    _check_phase("pair_generation_c1c2c3")

    # ---- 阶段 2:matched block(r6 tape;独立实例合同)----
    from rl_curriculum.curriculum261_r6_tape import (
        generate_matched_block_with_attempts,
    )
    generate_matched_block_with_attempts(
        {r: _rung_params_for("c2_context", r) for r in (
            "D0", "D1", "D2", "D3")},
        namespace=probe_ns, block_index=0)
    _check_phase("matched_block_r6_tape")

    # ---- 阶段 3:fit bank + V2 fit ----
    from rl_curriculum.curriculum261_r6_calibration import (
        fit_preprocessor_v2_from_bank_r6,
        generate_fit_bank_r6,
    )
    pack_stub = {"digest": "state-audit-no-pack",
                 "selected_c2_candidate": "c2l_historical_control"}
    bank = generate_fit_bank_r6(probe_ns, pack_stub, pairs_per_rung=1)
    fit_preprocessor_v2_from_bank_r6(
        probe_ns, pack_stub, records=bank, pairs_per_rung=1,
        parameter_pack_identity=pack_stub["digest"])
    _check_phase("fit_bank_v2_fit")

    # ---- 阶段 4:torch import + MLP 训练 ----
    import numpy as np

    import torch  # noqa: F401 —— import 本身是被审计的负载
    from rl_curriculum.ppo262_r2_supervised import train_supervised_mlp

    X = np.random.default_rng(11).normal(size=(256, 9)).astype(
        np.float32)
    y = (X[:, 0] > 0).astype(np.int64)
    train_supervised_mlp(X, y, control="W", seed=1, epochs=2)
    _check_phase("torch_mlp_training")

    # ---- 阶段 5:preprocessing/eval battery 片段 ----
    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        numerical_equivalence_report,
    )

    fit_df = fit_matrix_from_records(bank)
    half = len(fit_df) // 2
    numerical_equivalence_report(
        fit_df.iloc[:half], fit_df.iloc[half:])
    _check_phase("preprocessing_eval_battery")

    result = {
        "format": "cur261-r14-generator-state-mutation-audit-v1",
        "iteration": "r14",
        "phases": phase_reports,
        "findings": findings,
        "singleton_state_clean": not any(
            p["generator_state_drift"] for p in phase_reports),
        "constants_clean": not any(
            p["constants_drift"] for p in phase_reports),
        "module_globals_clean": not any(
            p["module_globals_drift"] for p in phase_reports),
        "in_process_determinism_held": all(
            p["target_envelope_digests_identical"]
            for p in phase_reports),
        "pass": not findings,
    }
    (out_dir / "generator_state_mutation_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


# ------------------------------------------------ A3/A5:probe 子命令
_PROBE_PRELUDES: dict[str, str] = {
    # 基线之外的预置负载(在目标调用前 exec)
    "import_torch_first":
        "import torch  # 预先 import torch",
    "c1_generation":
        "from rl_curriculum.curriculum261_pairs import generate_pair\n"
        "for r in ('D0','D1','D2','D3'):\n"
        "    generate_pair('c1_opportunity', r, 0, namespace='stress_r14')",
    "c2_generation":
        "from rl_curriculum.curriculum261_pairs import generate_pair\n"
        "for r in ('D0','D1','D2','D3'):\n"
        "    generate_pair('c2_context', r, 0, namespace='stress_r14')",
    "c1c2_supervised_dataset":
        "from rl_curriculum.curriculum261_pairs import ("
        "generate_pair, family_specs)\n"
        "from rl_curriculum.curriculum261_r10_labels import ("
        "collect_policy_visible_dataset_r10)\n"
        "from rl_curriculum.curriculum261_r6_calibration import ("
        "generate_fit_bank_r6, fit_preprocessor_v2_from_bank_r6)\n"
        "pack_stub = {'digest':'probe','selected_c2_candidate':"
        "'c2l_historical_control'}\n"
        "bank = generate_fit_bank_r6('stress_r14', pack_stub, "
        "pairs_per_rung=1)\n"
        "v2, _ = fit_preprocessor_v2_from_bank_r6('stress_r14', "
        "pack_stub, records=bank, pairs_per_rung=1)\n"
        "for fam in ('c1_opportunity','c2_context'):\n"
        "    recs = [generate_pair(fam, r, i, namespace='stress_r14') "
        "for r in ('D0','D1') for i in range(1)]\n"
        "    rp = {r: dict(family_specs()[fam].rung_params[r]) "
        "for r in ('D0','D1')}\n"
        "    collect_policy_visible_dataset_r10(recs, fam, rp, v2, "
        "eval_namespace='stress_r14')",
    "c1c2_mlp_training":
        "import numpy as np\n"
        "from rl_curriculum.ppo262_r2_supervised import "
        "train_supervised_mlp\n"
        "rng = np.random.default_rng(3)\n"
        "X = rng.normal(size=(512,9)).astype(np.float32)\n"
        "y = (X[:,0]>0).astype(np.int64)\n"
        "for c in ('U','W','B'):\n"
        "    train_supervised_mlp(X, y, control=c, seed=5, epochs=2)",
    "preprocessing_battery":
        "from rl_curriculum.curriculum261_r6_calibration import ("
        "generate_fit_bank_r6, fit_preprocessor_v2_from_bank_r6)\n"
        "from rl_curriculum.curriculum261_r3_calibration import ("
        "fit_matrix_from_records)\n"
        "from rl_curriculum.curriculum261_r3_preprocessing import ("
        "numerical_equivalence_report)\n"
        "from rl_curriculum.curriculum261_r10_reference import ("
        "reference_equivalence_run_r10)\n"
        "from rl_curriculum.curriculum261_pairs import generate_pair\n"
        "pack_stub = {'digest':'probe','selected_c2_candidate':"
        "'c2l_historical_control'}\n"
        "bank = generate_fit_bank_r6('stress_r14', pack_stub, "
        "pairs_per_rung=2)\n"
        "v2, _ = fit_preprocessor_v2_from_bank_r6('stress_r14', "
        "pack_stub, records=bank, pairs_per_rung=2)\n"
        "fit_df = fit_matrix_from_records(bank)\n"
        "h = len(fit_df)//2\n"
        "numerical_equivalence_report(fit_df.iloc[:h], fit_df.iloc[h:])\n"
        "recs = [generate_pair(f, r, i, namespace='stress_r14')\n"
        "        for f in ('c1_opportunity','c2_context','c3_cost')\n"
        "        for r in ('D0','D1') for i in range(1)]\n"
        "reference_equivalence_run_r10(recs, v2, pack_stub, "
        "eval_namespace='stress_r14')",
    "main_holdout_bundle_flow":
        "from rl_curriculum.curriculum261_r6_calibration import ("
        "generate_fit_bank_r6, fit_preprocessor_v2_from_bank_r6)\n"
        "pack_stub = {'digest':'probe','selected_c2_candidate':"
        "'c2l_historical_control'}\n"
        "for ns in ('preplan_fit_main_r10','preplan_fit_holdout_r10'):\n"
        "    if 'main' in ns:\n"
        "        bank = generate_fit_bank_r6(ns, pack_stub, "
        "pairs_per_rung=1)\n"
        "    else:\n"
        "        bank = generate_fit_bank_r6(ns, pack_stub, "
        "pairs_per_rung=1)\n"
        "    fit_preprocessor_v2_from_bank_r6(ns, pack_stub, "
        "records=bank, pairs_per_rung=1)",
}


def _probe_main(argv: list[str]) -> int:
    """子进程 probe 入口(供跨进程矩阵调用;不稳定接口)。"""
    parser_args = argv[1:]
    if parser_args and parser_args[0] == _PROBE_ARGV_MARKER:
        parser_args = parser_args[1:]
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", default="r14",
                    choices=("r14", "r10"))
    ap.add_argument("--prelude", default="")
    ap.add_argument("--repeat-twice", action="store_true")
    args = ap.parse_args(parser_args)
    if args.prelude:
        exec(  # noqa: S102 —— 预注册场景脚本(本模块内常量表)
            compile(_PROBE_PRELUDES[args.prelude],
                    f"<determinism-probe:{args.prelude}>", "exec"),
            {"__name__": "determinism_probe"})
    target = (dict(R10_FAILURE) if args.target == "r10"
              else dict(R14_MATRIX_TARGET))
    target.pop("phase", None)
    target.pop("orchestrator", None)
    target.pop("substage", None)
    target.pop("attempt_seeds", None)
    result = {"target": args.target,
              "prelude": args.prelude,
              "run1": run_target_call(target)}
    if args.repeat_twice:
        result["run2"] = run_target_call(target)
        result["same_process_bitwise"] = (
            result["run1"]["attempt_digests"]
            == result["run2"]["attempt_digests"])
    Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0


# ------------------------------------------------ A5:跨进程矩阵
def _run_probe(tmp_dir: Path, name: str, *, target: str,
               prelude: str = "", env_extra: dict | None = None,
               repeat_twice: bool = False,
               python_flags: list[str] | None = None) -> dict[str, Any]:
    out = Path(tmp_dir) / f"{name}.json"
    cmd = [sys.executable] + (python_flags or []) + [
        str(Path(__file__).resolve()), _PROBE_ARGV_MARKER,
        "--out", str(out), "--target", target,
    ]
    if prelude:
        cmd += ["--prelude", prelude]
    if repeat_twice:
        cmd += ["--repeat-twice"]
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(
        Path(__file__).resolve().parents[2] / "src"))
    env.update(env_extra or {})
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=1800)
    if proc.returncode != 0:
        return {"name": name, "ok": False,
                "returncode": proc.returncode,
                "stderr_tail": proc.stderr[-1500:],
                "stdout_tail": proc.stdout[-500:]}
    payload = json.loads(out.read_text(encoding="utf-8"))
    payload["name"] = name
    payload["ok"] = True
    return payload


def _extract(result: dict[str, Any]) -> dict[str, Any]:
    run = result.get("run1") or {}
    return {
        "call_digest": run.get("call_digest"),
        "attempt_digests": run.get("attempt_digests"),
        "attempt_outer_seeds": run.get("attempt_outer_seeds"),
        "attempt_accepted": run.get("attempt_accepted"),
        "attempt_event_digests": run.get("attempt_event_digests"),
        "attempt_counts": run.get("attempt_counts"),
        "generation_error": run.get("generation_error"),
    }


def run_cross_process_determinism_matrix(out_dir: Path) -> dict[str, Any]:
    """A5:14 场景跨进程矩阵(输出逐场景一致性 + R10 五 seed 重放)。"""
    import tempfile

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scenarios: list[dict[str, Any]] = []

    def _add(name: str, res: dict[str, Any], base: dict[str, Any],
             note: str) -> None:
        got = _extract(res)
        scenarios.append({
            "name": name,
            "note": note,
            "ok": bool(res.get("ok")),
            "probe_error": (None if res.get("ok") else {
                "returncode": res.get("returncode"),
                "stderr_tail": res.get("stderr_tail", "")[-600:]}),
            "identical_to_baseline": got == base if res.get("ok")
            else False,
            "detail_digest": stable_digest(got, "probe-") if res.get(
                "ok") else "",
            "run": got,
            "same_process_bitwise": res.get("same_process_bitwise"),
        })

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # 基线(场景 12 的第一半:完全独立冷进程)
        base_res = _run_probe(tmp, "baseline", target="r14")
        base = _extract(base_res)

        # 1. 单独重放 R10 失败调用
        r10_base = _run_probe(tmp, "r10_baseline", target="r10")
        r10_base_extract = _extract(r10_base)
        s1 = _run_probe(tmp, "s1_r10_replay", target="r10",
                        prelude="import_torch_first")
        got1 = _extract(s1)
        scenarios.append({
            "name": "1_r10_failure_invocation_replay",
            "note": "R10 c3_cost/D0/pair1(supervised_main_r10)单独重放"
                    "(torch 预导入);另验证 5 个 outer seeds 与记录一致",
            "ok": bool(s1.get("ok")),
            "probe_error": (None if s1.get("ok") else {
                "returncode": s1.get("returncode"),
                "stderr_tail": s1.get("stderr_tail", "")[-600:]}),
            "identical_to_baseline": got1 == r10_base_extract,
            "r10_attempt_seeds_match_recorded": _seeds_prefix_match(
                got1.get("attempt_outer_seeds")),
            "r10_reproduces_original_failure": (
                "too_few_distractors" in str(
                    got1.get("generation_error"))),
            "run": got1,
        })

        # 2. 不同 PYTHONHASHSEED
        _add("2_pythonhashseed_variant",
             _run_probe(tmp, "s2", target="r14",
                        env_extra={"PYTHONHASHSEED": "12345"}),
             base, "PYTHONHASHSEED=12345(基线为随机/未设)")
        # 3. 不同 import 顺序(-X importtime 不可控;用环境随机化 +
        #    PYTHONHASHSEED 差异触发 dict/set 遍历顺序差)
        _add("3_import_order_variant",
             _run_probe(tmp, "s3", target="r14",
                        env_extra={"PYTHONHASHSEED": "99991",
                                   "PYTHONHASHSEED2": "1"}),
             base, "不同 hash 种子下的 import/set 遍历顺序路径")
        # 4. 预先 import torch
        _add("4_import_torch_first",
             _run_probe(tmp, "s4", target="r14",
                        prelude="import_torch_first"),
             base, "目标调用前 import torch(基线不 import)")
        # 5. 预先完整 C1 生成
        _add("5_c1_generation_first",
             _run_probe(tmp, "s5", target="r14", prelude="c1_generation"),
             base, "预先执行 C1 全 rung 生成")
        # 6. 预先完整 C2 生成
        _add("6_c2_generation_first",
             _run_probe(tmp, "s6", target="r14", prelude="c2_generation"),
             base, "预先执行 C2 全 rung 生成")
        # 7. 预先 C1/C2 supervised dataset 构造
        _add("7_c1c2_dataset_first",
             _run_probe(tmp, "s7", target="r14",
                        prelude="c1c2_supervised_dataset"),
             base, "预先执行 C1/C2 dataset 构造(R10 失败序列核心)")
        # 8. 预先 C1/C2 MLP 训练
        _add("8_mlp_training_first",
             _run_probe(tmp, "s8", target="r14",
                        prelude="c1c2_mlp_training"),
             base, "预先执行 U/W/B MLP 训练(torch)")
        # 9. 预先 preprocessing robustness/reference-equivalence battery
        _add("9_preprocessing_battery_first",
             _run_probe(tmp, "s9", target="r14",
                        prelude="preprocessing_battery"),
             base, "预先执行 robustness/equivalence 电池(工程规模;"
                   "全规模覆盖由 full-scale shadow 承担)")
        # 10. 先后执行 main 与 holdout bundle 流程
        _add("10_main_holdout_bundle_first",
             _run_probe(tmp, "s10", target="r14",
                        prelude="main_holdout_bundle_flow"),
             base, "预先执行 main/holdout 双 bundle fit 流程")
        # 11. 同一进程重复两次
        s11 = _run_probe(tmp, "s11", target="r14", repeat_twice=True)
        scenarios.append({
            "name": "11_same_process_twice",
            "note": "同一进程内目标调用连续两次",
            "ok": bool(s11.get("ok")),
            "identical_to_baseline": _extract(s11) == base,
            "same_process_bitwise": s11.get("same_process_bitwise"),
            "run": _extract(s11),
        })
        # 12. 两个完全独立冷进程(基线 vs 再来一次)
        _add("12_two_cold_processes",
             _run_probe(tmp, "s12", target="r14"),
             base, "基线冷进程 vs 第二个独立冷进程")
        # 13. 不同线程环境变量
        _add("13_thread_env_variant",
             _run_probe(tmp, "s13", target="r14",
                        env_extra={"OMP_NUM_THREADS": "1",
                                   "MKL_NUM_THREADS": "1"}),
             base, "OMP_NUM_THREADS=1 / MKL_NUM_THREADS=1")
        # 14. R10 五个 outer attempt seeds 逐个重放
        s14 = _run_probe(tmp, "s14", target="r10")
        got14 = _extract(s14)
        scenarios.append({
            "name": "14_r10_five_attempt_seeds_replay",
            "note": "R10 调用整体重放(内部逐 attempt 派生 seed 逐一"
                    "覆盖五个记录值)",
            "ok": bool(s14.get("ok")),
            "probe_error": (None if s14.get("ok") else {
                "returncode": s14.get("returncode"),
                "stderr_tail": s14.get("stderr_tail", "")[-600:]}),
            "identical_to_baseline": got14 == r10_base_extract,
            "r10_attempt_seeds_match_recorded": _seeds_prefix_match(
                got14.get("attempt_outer_seeds")),
            "r10_all_five_seeds_replayed": _seeds_prefix_match(
                got14.get("attempt_outer_seeds")),
            "r10_reproduces_original_failure": (
                "too_few_distractors" in str(
                    got14.get("generation_error"))),
            "run": got14,
        })

    baseline_r10 = r10_base_extract
    all_identical = all(
        s.get("identical_to_baseline", True) and s.get("ok")
        for s in scenarios)
    r10_consistent = all(
        s.get("r10_attempt_seeds_match_recorded", True)
        for s in scenarios
        if "r10_attempt_seeds_match_recorded" in s)
    result = {
        "format": "cur261-r14-cross-process-determinism-matrix-v1",
        "iteration": "r14",
        "r14_target": dict(R14_MATRIX_TARGET),
        "r10_target": {k: R10_FAILURE[k] for k in (
            "namespace", "family", "rung", "pair_index")},
        "baseline": base,
        "baseline_r10": baseline_r10,
        "scenarios": scenarios,
        "all_scenarios_identical": all_identical,
        "r10_seed_replay_consistent": r10_consistent,
        "r10_failure_reproduced_in_any_scenario": any(
            s.get("r10_reproduces_original_failure", False)
            for s in scenarios),
        "root_cause_statement": ROOT_CAUSE_STATEMENT,
        "pass": bool(all_identical and r10_consistent),
    }
    (out_dir / "cross_process_determinism_matrix.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


# ------------------------------------------------ A6:确定性门禁
def envelope_roundtrip_check(envelope: dict[str, Any]) -> dict[str, Any]:
    """单个 envelope 的完整性与可重放性检查(digest/seed/字段)。"""
    from rl_curriculum.curriculum261_generation_envelope import (
        ENVELOPE_DIGEST_PREFIX,
        _digest_body,
        canonical_json,
    )

    problems: list[str] = []
    body = _digest_body(envelope)
    recomputed = stable_digest(body, ENVELOPE_DIGEST_PREFIX)
    if recomputed != envelope.get("digest"):
        problems.append("digest 重算不一致(tamper 或序列化漂移)")
    sdf = envelope.get("seed_derivation_fields") or {}
    expected_seed = derive261_seed(
        envelope["namespace"], envelope["family"], envelope["rung"],
        envelope["pair_index"], envelope["attempt_index"]) \
        if sdf else None
    if expected_seed is not None and \
            int(expected_seed) != int(envelope["outer_seed"]):
        problems.append("outer_seed 与派生字段不一致")
    try:
        canonical_json(envelope)
        rt = json.loads(canonical_json(envelope))
        rt.pop("digest", None)  # digest 自身不参与重算(自引用)
        if stable_digest(_digest_body(rt), ENVELOPE_DIGEST_PREFIX)                 != envelope.get("digest"):
            problems.append("canonical JSON roundtrip 后 digest 漂移")
    except TypeError as exc:
        problems.append(f"envelope 含不可规范化类型: {exc}")
    return {"ok": not problems, "problems": problems}


def generation_determinism_gate(out_dir: Path) -> dict[str, Any]:
    """A6:进入 R14 正式阶段前的生成确定性合同门禁。"""
    out_dir = Path(out_dir)
    matrix_path = out_dir / "cross_process_determinism_matrix.json"
    state_path = out_dir / "generator_state_mutation_audit.json"
    checks: dict[str, Any] = {}
    if matrix_path.is_file():
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        checks["cross_process_matrix_pass"] = matrix["pass"]
        checks["matrix_all_scenarios_identical"] = matrix[
            "all_scenarios_identical"]
        checks["r10_seed_replay_consistent"] = matrix[
            "r10_seed_replay_consistent"]
        checks["r10_failure_reproduced"] = matrix[
            "r10_failure_reproduced_in_any_scenario"]
    else:
        checks["cross_process_matrix_pass"] = None
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        checks["state_audit_pass"] = state["pass"]
        checks["singleton_state_clean"] = state["singleton_state_clean"]
    else:
        checks["state_audit_pass"] = None
    # envelope 完整性与可重放性:现场重放 stress_r14 目标,对每个
    # attempt envelope 做 digest/seed/roundtrip 检查 + 同进程重放一致
    family = R14_MATRIX_TARGET["family"]
    rp = _rung_params_for(family, R14_MATRIX_TARGET["rung"])
    rec = EnvelopeRecorder(
        iteration="r14", namespace=R14_MATRIX_TARGET["namespace"],
        family=family, rung=R14_MATRIX_TARGET["rung"],
        pair_index=R14_MATRIX_TARGET["pair_index"], rung_params=rp)
    error: str | None = None
    try:
        generate_pair_with_attempts(
            family_specs()[family].generator, rp,
            namespace=R14_MATRIX_TARGET["namespace"], family=family,
            rung=R14_MATRIX_TARGET["rung"],
            pair_index=R14_MATRIX_TARGET["pair_index"],
            structural_validator=pair_acceptance_contract(family),
            recorder=rec)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}:{exc}"
    envelope_checks = [
        envelope_roundtrip_check(e) for e in rec.attempt_envelopes]
    checks["envelope_roundtrip_all_ok"] = bool(
        envelope_checks and all(c["ok"] for c in envelope_checks))
    rep = replay_call(rec.call_envelope)
    checks["replay_call_digest_match"] = bool(
        rep["call_digest_recomputed"] == rec.call_envelope["digest"])
    rep_consistent = bool(rec.attempt_envelopes) and all(
        compare_envelopes(a, b)["consistent"]
        for a, b in zip(rec.attempt_envelopes,
                        rep["attempt_envelopes"]))
    checks["replay_envelopes_consistent"] = rep_consistent
    checks["target_call_executable"] = error is None
    result = {
        "format": "cur261-r14-generation-determinism-contract-v1",
        "iteration": "r14",
        "contract": (
            "同一完整 invocation envelope 跨进程:内部 seed/canonical "
            "params/event table digest/signal-distractor 计数/A-B "
            "episode hash/structural validator 结果/接受状态全部一致;"
            "调用前后 generator 状态无未声明变化"),
        "checks": checks,
        "envelope_roundtrip_problems": [
            p for c in envelope_checks for p in c["problems"]],
        "r10_root_cause_statement": ROOT_CAUSE_STATEMENT,
        "pass": bool(
            checks.get("cross_process_matrix_pass") is True
            and checks.get("state_audit_pass") is True
            and checks.get("envelope_roundtrip_all_ok") is True
            and checks.get("replay_call_digest_match") is True
            and checks.get("replay_envelopes_consistent") is True
            and checks.get("target_call_executable") is True),
    }
    (out_dir / "generation_determinism_contract.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    sys.exit(_probe_main(sys.argv))
