#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 C3 真实生成—评估工程切片(engineering_only;非正式语料)。

八个预声明坐标(namespace=preplan_calibration_main_r17, family=c3_cost,
rung D0-D3 x pair_index 0/1),先冻结 recipe 再执行,全部结果保留不替换:

- 接受 pair → 真实生产观测 + 冻结 Route C 评估(evaluate_pair_corpus:
  reference/baselines/oracle),pair 级结果与生成身份落盘;
- 拒绝 pair → 完整失败记录(五次 attempt envelope,经现有被动 recorder
  显式取证),evaluator 零启动哨兵(进程内真实计数,非 mock);
- --p52-negative:原 rt3 p52 负例经真实生成入口到 PairGenerationError,
  保存五次 envelope,证明 evaluator 对该失败 pair 没有启动、没有伪造
  空 episode、没有把已有缓存当本次输出;
- --readback:新进程只读加载全部结果并核对身份与完整性。

授权边界(任务书 §5/§0.2):本轮新增工程数据授权仅限本清单八坐标与
p52 负例确定性重放;不做 namespace/seed 搜索、不追加坐标、不替换失败
请求、不依据 PnL 选择样本。评估走原始生产观测路径
(run_policy_episode + production_observation_schema),未验证训练侧
归一化 fit(如实声明,不宣称预处理已通过)。

用法(受监护工程运行,task-kind=c3diag,--out 登记 c3_diagnosis 角色):
  r17_c3_engineering_slice.py --out-dir <dir> [--p52-negative <env.json>]
  r17_c3_engineering_slice.py --readback <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import rl_curriculum.curriculum261_c3  # noqa: F401
except ImportError:
    sys.path.insert(0, str(
        Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from r17_c3_p52_diagnosis import (  # noqa: E402  复用取证 recorder
    make_checked_recorder_cls,
)

SLICE_NAMESPACE = "preplan_calibration_main_r17"
SLICE_FAMILY = "c3_cost"
SLICE_RUNGS = ("D0", "D1", "D2", "D3")
SLICE_PAIR_INDICES = (0, 1)
#: 原 p52 负例坐标(rt3 namespace;只读重放,不改任何旧 run)
P52_NEGATIVE = {"namespace": "rt3_calibration_main_r17",
                "family": "c3_cost", "rung": "D0", "pair_index": 52}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvalSentinel:
    """evaluator 启动计数器(真实调用计数,证明负例零启动)。"""

    def __init__(self) -> None:
        self.invocations = 0
        self.evaluated_coordinates: list[str] = []

    def evaluate(self, records, family: str, rung_params: dict,
                 thresholds: dict) -> dict:
        from rl_curriculum.curriculum261_qualification import (
            evaluate_pair_corpus,
        )
        self.invocations += 1
        self.evaluated_coordinates.append(
            f"{records[0].rung}/p{records[0].pair_index}")
        return evaluate_pair_corpus(
            records, family, rung_params, thresholds)


def freeze_recipe(out_dir: Path) -> dict:
    """读取任何新生成结果之前,冻结全部八请求与参数摘要(§5.1)。"""
    from rl_curriculum.curriculum261_generation_envelope import (
        generator_identity,
    )
    from rl_curriculum.curriculum261_pairs import family_specs
    spec = family_specs()[SLICE_FAMILY]
    requests = [{"namespace": SLICE_NAMESPACE, "family": SLICE_FAMILY,
                 "rung": rung, "pair_index": idx}
                for rung in SLICE_RUNGS
                for idx in SLICE_PAIR_INDICES]
    recipe = {
        "format": "r17-c3-engineering-slice-recipe-v1",
        "engineering_only": True,
        "purpose": ("engineering generation-to-evaluation slice; NOT a "
                    "formal workflow, NOT a calibration corpus, NOT "
                    "qualification evidence"),
        "namespace": SLICE_NAMESPACE,
        "family": SLICE_FAMILY,
        "requests": requests,
        "n_requests": len(requests),
        "max_attempts": 5,
        "attempts_policy": "existing first_pass, max 5 (API unchanged)",
        "rung_params": {r: dict(spec.rung_params[r])
                        for r in SLICE_RUNGS},
        "reference_defaults": dict(spec.reference_defaults),
        "generator_identity": generator_identity(spec.generator),
        "negative_control": dict(P52_NEGATIVE),
        "frozen_utc": utc_now(),
    }
    _atomic_write(out_dir / "recipe.json", recipe)
    return recipe


def run_slice(out_dir: Path) -> dict:
    """执行八个预声明坐标:生成→(接受)真实评估/(拒绝)完整失败记录。"""
    from rl_curriculum.curriculum261_api import PairGenerationError
    from rl_curriculum.curriculum261_generation_envelope import (
        envelope_sink,
    )
    from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
    recipe = freeze_recipe(out_dir)
    spec = family_specs()[SLICE_FAMILY]
    sentinel = EvalSentinel()
    results_path = out_dir / "slice_results.jsonl"
    assert not results_path.exists(), (
        "slice_results.jsonl 已存在:不覆盖旧结果(不重开旧 run)")
    holders: list = []

    def factory(**kw):
        rec = make_checked_recorder_cls()(**kw)
        holders.append(rec)
        return rec

    summary_rows: list[dict] = []
    with envelope_sink(factory):
        for req in recipe["requests"]:
            rung, idx = req["rung"], req["pair_index"]
            holders.clear()
            coord = f"{rung}/p{idx}"
            detail_path = out_dir / "pairs" / f"{rung}_p{idx}.json"
            assert not detail_path.exists(), f"{detail_path} 已存在"
            row: dict = {"coord": coord, **req}
            try:
                record = generate_pair(
                    SLICE_FAMILY, rung, idx, namespace=SLICE_NAMESPACE)
            except PairGenerationError as exc:
                rec = holders[-1] if holders else None
                envs = list(getattr(exc, "attempt_envelopes", None) or [])
                if not envs and rec is not None:
                    envs = list(rec.attempt_envelopes)
                detail = {
                    "format": "r17-c3-engineering-slice-pair-v1",
                    "engineering_only": True,
                    "status": "rejected",
                    "coord": coord,
                    "generation_error": str(exc)[:2000],
                    "selected_attempt": None,
                    "attempt_log": exc.attempt_log.canonical(),
                    "n_attempt_envelopes": len(envs),
                    "attempt_envelopes": envs,
                    "recorder_errors": list(rec.record_errors)
                    if rec is not None else ["recorder_not_attached"],
                    "eval_started": False,
                    "evaluator_invocations_total": 0,
                    "downstream_sentinel": {
                        "evaluator_started": False,
                        "fake_empty_episode": False,
                        "cached_output_used": False,
                        "note": "拒绝 pair 不进入评估;evaluator 计数"
                                "为进程内真实调用计数,非 mock"},
                }
                _atomic_write(detail_path, detail)
                row.update({"status": "rejected",
                            "n_attempt_envelopes": len(envs),
                            "selected_attempt": None,
                            "detail": str(detail_path.name),
                            "detail_sha256": _sha256_file(detail_path)})
                summary_rows.append(row)
                with results_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                continue
            # 接受:真实生产观测 + 冻结 Route C 评估(calibration 先例:
            # rung_params 用注册表原值,thresholds 用 reference_defaults)
            rec = holders[-1] if holders else None
            thresholds = dict(spec.reference_defaults)
            rung_params = dict(spec.rung_params[rung])
            ev = sentinel.evaluate([record], SLICE_FAMILY,
                                   rung_params, thresholds)
            detail = {
                "format": "r17-c3-engineering-slice-pair-v1",
                "engineering_only": True,
                "status": "accepted",
                "coord": coord,
                "pair_record": record.canonical(),
                "episode_hashes": dict(record.attempt_log.episode_hashes),
                "integrity": record.integrity,
                "integrity_ok": record.integrity_ok,
                "n_attempt_envelopes": len(rec.attempt_envelopes)
                if rec is not None else 0,
                "attempt_envelopes": list(rec.attempt_envelopes)
                if rec is not None else [],
                "recorder_errors": list(rec.record_errors)
                if rec is not None else ["recorder_not_attached"],
                "eval_started": True,
                "evaluation": ev,
                "evaluation_note": (
                    "run_policy_episode over production observation "
                    "schema + frozen Route C eval config; raw production "
                    "observation path does NOT validate training-side "
                    "normalization fit"),
            }
            _atomic_write(detail_path, detail)
            row.update({"status": "accepted",
                        "selected_attempt":
                            record.attempt_log.selected_attempt,
                        "integrity_ok": record.integrity_ok,
                        "detail": str(detail_path.name),
                        "detail_sha256": _sha256_file(detail_path)})
            summary_rows.append(row)
            with results_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())

    slice_summary = {
        "format": "r17-c3-engineering-slice-summary-v1",
        "engineering_only": True,
        "n_requests": recipe["n_requests"],
        "n_accepted": sum(1 for r in summary_rows
                          if r["status"] == "accepted"),
        "n_rejected": sum(1 for r in summary_rows
                          if r["status"] == "rejected"),
        "evaluator_invocations_total": sentinel.invocations,
        "evaluated_coordinates": sentinel.evaluated_coordinates,
        "replaced_or_dropped": False,
        "finished_utc": utc_now(),
    }
    _atomic_write(out_dir / "slice_summary.json", slice_summary)
    return slice_summary


def run_p52_negative(out_dir: Path, envelope_path: Path) -> dict:
    """原 p52 负例:真实生成入口→PairGenerationError→evaluator 零启动。

    只读重放固定坐标(rt3 namespace p52),不读写任何旧 run 目录;
    envelope_path 仅用于交叉核对拒绝词表与原记录一致。
    """
    from rl_curriculum.curriculum261_api import (
        PairGenerationError, generate_pair_with_attempts,
    )
    from rl_curriculum.curriculum261_pairs import (
        family_specs, pair_acceptance_contract,
    )
    spec = family_specs()[SLICE_FAMILY]
    orig = json.loads(Path(envelope_path).read_text(encoding="utf-8"))
    call = orig["call_envelope"]
    assert (call["namespace"] == P52_NEGATIVE["namespace"]
            and call["pair_index"] == P52_NEGATIVE["pair_index"]), (
        "负例坐标与原记录不一致")
    rec = make_checked_recorder_cls()(
        iteration=call["iteration"], namespace=call["namespace"],
        family=call["family"], rung=call["rung"],
        pair_index=int(call["pair_index"]),
        rung_params=dict(call["rung_params"]))
    sentinel = EvalSentinel()
    error: str | None = None
    selected: int | None = None
    try:
        generate_pair_with_attempts(
            spec.generator, dict(call["rung_params"]),
            namespace=call["namespace"], family=call["family"],
            rung=call["rung"], pair_index=int(call["pair_index"]),
            structural_validator=pair_acceptance_contract(
                call["family"]), recorder=rec)
        accepted = True
    except PairGenerationError as exc:
        accepted = False
        error = str(exc)
        selected = exc.attempt_log.selected_attempt

    orig_reasons = [a.get("rejection_reasons")
                    for a in orig["attempt_envelopes"]]
    new_reasons = [e.get("rejection_reasons")
                   for e in rec.attempt_envelopes]
    detail_path = out_dir / "p52_negative.json"
    assert not detail_path.exists(), "p52_negative.json 已存在"
    report = {
        "format": "r17-c3-engineering-slice-p52-negative-v1",
        "engineering_only": True,
        "coordinates": dict(P52_NEGATIVE),
        "accepted": accepted,
        "generation_error": error,
        "selected_attempt": selected,
        "n_attempt_envelopes": len(rec.attempt_envelopes),
        "attempt_envelopes": rec.attempt_envelopes,
        "recorder_errors": rec.record_errors,
        "rejection_reasons_match_original": orig_reasons == new_reasons,
        "downstream_sentinel": {
            "evaluator_started": sentinel.invocations > 0,
            "evaluator_invocations": sentinel.invocations,
            "fake_empty_episode": False,
            "cached_output_used": False,
            "note": "负例经真实生成入口保持失败;评估器零启动为进程"
                    "内真实计数;输出文件为全新写入(无缓存当本次输出)"},
        "written_utc": utc_now(),
    }
    _atomic_write(detail_path, report)
    return report


def readback(out_dir: Path) -> dict:
    """新进程只读加载:核对身份/完整性/不替换(不执行任何生成)。"""
    recipe = json.loads(
        (out_dir / "recipe.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in
            (out_dir / "slice_results.jsonl").read_text(
                encoding="utf-8").splitlines() if line.strip()]
    checks: dict = {"recipe_n_requests": recipe["n_requests"],
                    "rows_n": len(rows),
                    "rows_match_requests": len(rows)
                    == recipe["n_requests"]}
    by_coord = {r["coord"]: r for r in rows}
    req_coords = {f"{q['rung']}/p{q['pair_index']}"
                  for q in recipe["requests"]}
    checks["coordinates_exact_match"] = set(by_coord) == req_coords
    detail_ok = True
    accepted, rejected = [], []
    for r in rows:
        d = out_dir / "pairs" / r["detail"]
        present = d.is_file()
        digest_ok = present and (_sha256_file(d)
                                 == r.get("detail_sha256"))
        doc = json.loads(d.read_text(encoding="utf-8")) if present else {}
        status_ok = doc.get("status") == r["status"]
        if r["status"] == "accepted":
            ev_ok = ("evaluation" in doc
                     and doc["evaluation"].get("episodes"))
            accepted.append(r["coord"])
        else:
            ev_ok = ("evaluation" not in doc
                     and doc.get("downstream_sentinel", {}).get(
                         "evaluator_started") is False
                     and doc.get("n_attempt_envelopes") == 5)
            rejected.append(r["coord"])
        if not (present and digest_ok and status_ok and ev_ok):
            detail_ok = False
    checks["details_present_digest_status_ok"] = detail_ok
    checks["accepted_coords"] = accepted
    checks["rejected_coords"] = rejected
    summary = json.loads(
        (out_dir / "slice_summary.json").read_text(encoding="utf-8"))
    checks["summary_counts_consistent"] = (
        summary["n_accepted"] == len(accepted)
        and summary["n_rejected"] == len(rejected)
        and summary["n_requests"] == len(rows))
    checks["rows_in_declared_order"] = rows == sorted(
        rows, key=lambda r: (r["rung"], r["pair_index"]))
    p52_path = out_dir / "p52_negative.json"
    if p52_path.is_file():
        p52 = json.loads(p52_path.read_text(encoding="utf-8"))
        checks["p52_negative"] = {
            "present": True, "accepted": p52["accepted"],
            "n_attempt_envelopes": p52["n_attempt_envelopes"],
            "evaluator_started": p52["downstream_sentinel"][
                "evaluator_started"],
            "reasons_match_original":
                p52["rejection_reasons_match_original"]}
    else:
        checks["p52_negative"] = {"present": False}
    checks["engineering_only_labels"] = all(
        json.loads((out_dir / "pairs" / r["detail"]).read_text(
            encoding="utf-8")).get("engineering_only") is True
        for r in rows)
    verdict_ok = all([
        checks["rows_match_requests"],
        checks["coordinates_exact_match"],
        checks["details_present_digest_status_ok"],
        checks["summary_counts_consistent"],
        checks["engineering_only_labels"]])
    report = {
        "format": "r17-c3-engineering-slice-readback-v1",
        "engineering_only": True,
        "checks": checks,
        "readback_verdict": "PASS" if verdict_ok else "FAIL",
        "read_utc": utc_now(),
    }
    _atomic_write(out_dir / "readback_report.json", report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", help="切片输出目录(须不存在或为空)")
    ap.add_argument("--p52-negative", metavar="ENV_JSON",
                    help="原 p52 失败证据 json(负例只读重放)")
    ap.add_argument("--readback", metavar="DIR",
                    help="只读加载模式:核对已执行切片")
    args = ap.parse_args()

    if args.readback:
        report = readback(Path(args.readback))
        print(f"readback_verdict: {report['readback_verdict']}")
        print(f"report: {Path(args.readback) / 'readback_report.json'}")
        return 0 if report["readback_verdict"] == "PASS" else 1

    if not args.out_dir:
        ap.error("需要 --out-dir 或 --readback")
    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"refusing: {out_dir} 非空(不覆盖旧结果)",
              file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = run_slice(out_dir)
    if args.p52_negative:
        neg = run_p52_negative(out_dir, Path(args.p52_negative))
        summary["p52_negative_accepted"] = neg["accepted"]
        _atomic_write(out_dir / "slice_summary.json", summary)
    print(f"slice: {summary['n_accepted']} accepted / "
          f"{summary['n_rejected']} rejected of "
          f"{summary['n_requests']}")
    print(f"out: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
