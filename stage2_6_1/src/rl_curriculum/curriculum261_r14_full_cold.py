"""R14 full-cold 证据 reader(正式入口;rehearsal 与正式共用)。

R13 缺口(§九-5):rehearsal 的 smoke 步骤被静态声明"同时覆盖
full-cold reader",但 full-cold 使用的 artifact loader 与字段访问
从未被实际执行。R14 将 full-cold 的证据读取实现为独立正式模块:

- full-cold(最终验收)消费 qualification/final artifacts 的方式
  = 本模块的 read_full_cold_evidence(同函数,无第二实现);
- rehearsal 通过 subprocess CLI 子命令 full-cold-reader-check
  调用同一函数,读取真实 rehearsal qualification + smoke
  artifacts(§九要求);
- 正式链 full-cold 步骤同样先经本函数(读取真实正式 artifacts)
  再进入回归套件。

只读:不生成任何语料、不触碰任何 namespace。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FULL_COLD_READER_FORMAT = "cur261-r14-full-cold-reader-v1"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"full-cold reader: 必需 artifact 缺失: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_full_cold_evidence(artifacts_dir: Path) -> dict[str, Any]:
    """full-cold 消费的 final 证据读取(字段级;fail closed)。

    与正式 full-cold 使用完全相同的 artifact loader 与字段访问
    (本函数即唯一实现)。检查:
    - qualification_result.json:verdict/checks/final_bundle_hash/
      plan_digest/gate_topology/gate_evidence 字段;
    - qualification_preprocessor_bundle.json:canonical
      preprocessor_bundle_hash(r4pb- 前缀);
    - ppo_256step_smoke.json:pass + preprocessor_bundle_hash 绑定;
    - exposure marker:存在且 terminal(completed;rehearsal 目录
      中为 rehearsal 终态文件)。
    """
    artifacts_dir = Path(artifacts_dir)
    result = _read_json(artifacts_dir / "qualification_result.json")
    bundle = _read_json(
        artifacts_dir / "qualification_preprocessor_bundle.json")
    smoke = _read_json(artifacts_dir / "ppo_256step_smoke.json")

    checks = result.get("checks", {})
    verdict = result.get("verdict")
    bundle_hash = bundle.get("preprocessor_bundle_hash")
    smoke_bundle_bound = (
        smoke.get("checks", {}).get("preprocessor_bundle_hash_bound")
        if isinstance(smoke.get("checks"), dict)
        else smoke.get("preprocessor_bundle_hash_bound"))
    exposure_terminal = False
    exposure_status = None
    for marker_name in ("qualification_exposure_r14.json",
                        "rehearsal_exposure.json"):
        marker = artifacts_dir / marker_name
        if marker.is_file():
            exposure_status = json.loads(
                marker.read_text(encoding="utf-8")).get("status")
            exposure_terminal = exposure_status in (
                "completed", "failed", "crashed", "PASS", "FAIL")
            break
    if not exposure_terminal:
        # rehearsal final(R13 语义)把终态写在 result 自身
        exposure_status = exposure_status or result.get(
            "exposure_status")
        exposure_terminal = exposure_status in (
            "rehearsal-terminal",)

    topology = result.get("gate_topology", {})
    gate_evidence = result.get("gate_evidence", {})
    failed_binding = gate_evidence.get("failed_binding_checks")

    reader_checks = {
        "qualification_verdict_present": verdict in ("PASS", "FAIL"),
        "qualification_checks_present": bool(
            isinstance(checks, dict) and checks),
        "final_bundle_hash_present": bool(
            result.get("final_bundle_hash")),
        "plan_digest_present": bool(result.get("plan_digest")),
        "gate_topology_digest_present": bool(
            topology.get("digest", "").startswith("r14gt-")),
        "gate_evidence_present": bool(gate_evidence.get("gates")),
        "preprocessor_bundle_hash_canonical": bool(
            isinstance(bundle_hash, str)
            and bundle_hash.startswith("r4pb-")),
        "ppo_smoke_pass_recorded": isinstance(smoke.get("pass"), bool),
        "ppo_smoke_bundle_bound": bool(smoke_bundle_bound),
        "exposure_terminal": exposure_terminal,
    }
    return {
        "format": FULL_COLD_READER_FORMAT,
        "artifacts_dir": str(artifacts_dir),
        "verdict": verdict,
        "plan_digest": result.get("plan_digest"),
        "final_bundle_hash": result.get("final_bundle_hash"),
        "preprocessor_bundle_hash": bundle_hash,
        "ppo_smoke_pass": smoke.get("pass"),
        "exposure_status": exposure_status,
        "gate_topology_digest": topology.get("digest"),
        "failed_binding_checks": failed_binding,
        "reader_checks": reader_checks,
        "pass": bool(all(reader_checks.values())
                     and verdict == "PASS"
                     and smoke.get("pass") is True),
    }
