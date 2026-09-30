#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QProd Level A 入口(新迭代资格链工程排练 + 导出 + 消费冷读)。

用法(部署树):
  python stage2_6_1_runner/qprod_level_a_entry.py rehearse \
      --base-dir <隔离目录> --authority-dir <authority目录> \
      --pack-variant v1_r2_reference|v2_perturbed
  ... export / consumption-cold-read --auth <授权锚>

rehearse = 许可消费 → 会话 → 数据前运行计划 → 17 步账本(真实控制
路径 + 明确标注替身/NOT_RUN)→ 资格计划冻结 → exposure 一次性窗口 →
公共判定核心 → 终态封口。export = 262 导出适配器验证原件产六件套。
consumption-cold-read = 新进程 load_qualified_input → EntrySpec 共享
消费准备 → 冻结 V2 环境 reset/step(零生成/零 fit/零 optimizer;
bank=标注夹具替身)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEPLOY_SRC = Path(__file__).resolve().parents[1] / "src"
if DEPLOY_SRC.is_dir():
    sys.path.insert(0, str(DEPLOY_SRC))

from rl_curriculum.curriculum261_qprod_context import (  # noqa: E402
    QProdContextError, QProdRunSession, build_engineering_context,
)
from rl_curriculum.curriculum261_qprod_permit import (  # noqa: E402
    acquire_live_permit,
)

ITERATION_ID = "qprod_a_eng_v1"
CONSUMPTION_PROFILE = "ppo262_qprod_engineering_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _code_freeze_sha() -> str:
    from rl_curriculum.curriculum261_qprod_levela import (
        levela_code_identity,
    )
    blob = json.dumps(levela_code_identity(), sort_keys=True).encode(
        "utf-8")
    return "qprod-eng-" + hashlib.sha256(blob).hexdigest()[:16]


def _context(args: argparse.Namespace):
    return build_engineering_context(
        level="level_a", iteration_id=ITERATION_ID,
        base_dir=args.base_dir, code_freeze_sha=_code_freeze_sha(),
        authority_dir=args.authority_dir)


def _build_fixture_inputs(args: argparse.Namespace,
                          workdir: Path) -> dict:
    """工程原件夹具(明确标记):pack 双预定变体 + V2 bundle fit 样例。

    V2 工程 producer fit 使用固定手工 fit 样例并保留来源(消费侧
    fit 调用为 0);raw 业务输入为夹具,判定/锁定/导出逻辑真实。
    """
    from rl_curriculum.ppo262_eng_fixture import (
        _engineering_pack, build_frozen_v2_preprocessor,
    )
    pack = _engineering_pack(args.pack_variant)
    preproc, _records = build_frozen_v2_preprocessor()
    envelope_path = workdir / "fixture_v2_envelope.json"
    preproc.serialize_envelope(envelope_path)
    return {
        "gate_topology": {
            "format": "cur261-qprod-fixture-gate-topology-v1",
            "engineering_fixture": True,
            "nodes": ["determinism", "audit", "cue-audit", "design",
                      "calibrate", "lock-plan", "qualify"],
        },
        "determinism_contract": {
            "format": "cur261-qprod-fixture-determinism-v1",
            "engineering_fixture": True,
            "note": "原生确定性由 Level B 坐标原生面覆盖",
        },
        "cue_audit_report": {
            "format": "cur261-r17-cue-contract-audit-v1",
            "pass": True,
            "audit_digest": "r15ca-" + "0" * 64,
            "p_contract": 0.9504,
            "engineering_fixture": True,
        },
        "preplan_smoke": {
            "format": "cur261-qprod-fixture-preplan-v1",
            "pass": True, "engineering_fixture": True,
        },
        "design_plan": {
            "format": "cur261-qprod-design-plan-v1",
            "grid": "engineering fixture(R2 参照拷贝/合法扰动)",
            "pack_variant": args.pack_variant,
        },
        "parameter_pack": pack,
        "calibration_artifacts": {
            "preprocessor_bundle_calibration.json": {
                "format": "cur261-qprod-fixture-cal-v1",
                "engineering_fixture": True,
                "preprocessor_bundle_hash": preproc.bundle_hash,
                "source": "V2 工程 producer fit(固定手工样例,来源"
                          "保留于 envelope fit manifest)",
            },
            "preprocessor_bundle_holdout.json": {
                "format": "cur261-qprod-fixture-cal-v1",
                "engineering_fixture": True,
                "preprocessor_bundle_hash": preproc.bundle_hash,
            },
        },
        "robustness_gate": {
            "format": "cur261-qprod-fixture-robustness-v1",
            "pass": True, "engineering_fixture": True,
        },
        "calibration_evidence": {
            "format": "cur261-qprod-fixture-cal-evidence-v1",
            "engineering_fixture": True,
        },
        "c2_marginal": {
            "format": "cur261-qprod-c2-independent-marginal-v1",
            "engineering_fixture": True,
            "metrics": {"non_cue_false_positive_max": 0.001},
        },
        "c2_marginal_thresholds": {
            "non_cue_false_positive_max": 0.01},
        "v2_envelope_path": envelope_path,
    }


def cmd_rehearse(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_qprod_levela import (
        run_level_a_rehearsal,
    )

    ctx = _context(args)
    workdir = ctx.artifact_root.parent / "fixture_workspace"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        live = acquire_live_permit(ctx.permit_path, context=ctx)
    except QProdContextError as exc:
        print(f"[rehearse] 许可拒绝: {exc}")
        return 96
    session = QProdRunSession(
        ctx.state_root, level="level_a", iteration_id=ctx.iteration_id)
    try:
        session.acquire({"entry": "qprod_level_a_entry.rehearse",
                         "pack_variant": args.pack_variant})
    except QProdContextError as exc:
        print(f"[rehearse] 会话拒绝: {exc}")
        return 96
    session.record_permit_consumed(live.permit["permit_id"])
    try:
        out = run_level_a_rehearsal(
            ctx, session,
            _build_fixture_inputs(args, workdir))
        session.release()
        print(json.dumps({
            "verdict": out["verdict"],
            "qualification_plan_digest":
                out["qualification_plan_digest"],
            "ledger_steps": len(out["ledger"]),
            "artifact_root": str(ctx.artifact_root),
            "state_root": str(ctx.state_root),
        }, ensure_ascii=False))
        return 0 if out["verdict"] == "PASS" else 1
    except BaseException as exc:
        print(f"[rehearse] 中断/失败(已封口): "
              f"{type(exc).__name__}: {exc}")
        return 3


def cmd_export(args: argparse.Namespace) -> int:
    from rl_curriculum.ppo262_qprod_export import (
        QProdExportError, export_qualification_delivery,
    )

    ctx = _context(args)
    out_dir = (ctx.artifact_root.parent
               / f"delivery_{args.pack_variant}")
    try:
        receipt = export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, out_dir,
            expected_scope="engineering")
    except QProdExportError as exc:
        print(f"[export] 拒绝: {exc}")
        return 2
    print(json.dumps({
        "qualification_dir": receipt["qualification_dir"],
        "bindings": receipt["bindings"],
        "receipt": str(Path(receipt["qualification_dir"])
                       / "qprod_export_receipt.json"),
    }, ensure_ascii=False))
    return 0


def cmd_consumption_cold_read(args: argparse.Namespace) -> int:
    """新进程消费冷读:load → EntrySpec 共享准备 → V2 env reset/step。

    bank 生成叶 = 明确标注夹具替身(本轮零新增原生生成;真实 bank
    生成属未来授权运行);reset/step/无梯度前向真实执行。
    """
    import numpy as np

    from rl_curriculum.ppo262_qualified_input import (
        activated_profile_input, load_qualified_input,
    )
    from rl_curriculum.ppo262_entry_specs import prepare_smoke_inputs

    ctx = _context(args)
    delivery_dir = (ctx.artifact_root.parent
                    / f"delivery_{args.pack_variant}")
    auth_path = Path(args.auth)
    qi = load_qualified_input(
        delivery_dir, authorization_path=auth_path,
        expected_scope="engineering",
        expected_profile=CONSUMPTION_PROFILE)
    with activated_profile_input(qi):
        spec = prepare_smoke_inputs()
        spec.assert_from_profile(qi)
        rung = spec.rung_params
        # 消费准备边界可见的真实参数(两套预定 pack 在此可区分)
        probe_params = {
            fam: {r: rung[fam][r] for r in ("D0", "D3")}
            for fam in ("c1_opportunity", "c3_cost")}

        # bank = 标注夹具替身(零生成;真实生成边界属未来授权)。
        # 合成 episode 与 262 测试面同款(synthetic_ohlcv +
        # attach_production_features,SYNTHETIC_ONLY)。
        from rl_curriculum.curriculum261_api import episode_content_hash
        from rl_curriculum.curriculum261_production_obs import (
            attach_production_features,
        )
        from rl_curriculum.generator_api import (
            EpisodeSpec, GeneratedEpisode,
        )
        from rl_curriculum.ppo262_banks import (
            EpisodeKey, LoadedEpisode,
        )
        from rl_curriculum.ppo262_eng_fixture import synthetic_ohlcv

        def _fixture_episode(k: int) -> GeneratedEpisode:
            df = attach_production_features(synthetic_ohlcv({
                "start": 100.0 * (1.0 + 0.2 * k),
                "drift": 0.0002 * (k + 1), "amp": 0.003,
                "period": 24.0 + 6.0 * k, "phase": 0.7 * k,
                "wick": 0.0015, "bars": 288}))
            return GeneratedEpisode(
                spec=EpisodeSpec(
                    family="eng_synthetic",
                    params={"fixture_k": k, "bank_double": True},
                    seed=9000 + k, split="train", timeframe="15m"),
                df=df, hidden=df.iloc[:0].copy(),
                family_version="qprod-bank-fixture-v1",
                timeframe="15m", is_null=False,
                generator_fingerprint="qprod-bank-double-v1")

        bank = [
            LoadedEpisode(
                key=EpisodeKey(spec.namespace, spec.bank_keys[0].family,
                               spec.bank_keys[0].rung,
                               spec.bank_keys[0].pair_index,
                               spec.bank_keys[0].variant),
                episode=_fixture_episode(k),
                content_hash=episode_content_hash(
                    _fixture_episode(k)))
            for k in range(2)]
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

        env = CurriculumMultiEpisodeEnv(
            bank, preprocessor=qi.preprocessor)
        obs, info = env.reset(seed=20260930)
        stepped = 0
        rng = np.random.default_rng(20260930)
        for _ in range(4):
            action = int(rng.integers(0, env.action_space.n))
            obs, reward, terminated, truncated, info = env.step(action)
            stepped += 1
        forward_ready = (obs is not None and stepped == 4)
    print(json.dumps({
        "cold_read": "ok",
        "profile": qi.profile,
        "scope": qi.scope,
        "bundle_hash": qi.bundle_hash,
        "namespace": spec.namespace,
        "probe_params": probe_params,
        "reset_step": {"stepped": stepped,
                       "forward_ready": bool(forward_ready)},
        "bank_double": "fixture(replace native generate262_bank;"
                       "zero native generation this round)",
        "optimizer_updates": 0,
    }, ensure_ascii=False, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("rehearse", "export", "consumption-cold-read"):
        p = sub.add_parser(name)
        p.add_argument("--base-dir", required=True)
        p.add_argument("--authority-dir", required=True)
        p.add_argument("--pack-variant", default="v1_r2_reference",
                       choices=("v1_r2_reference", "v2_perturbed"))
        if name == "consumption-cold-read":
            p.add_argument("--auth", required=True)
        p.set_defaults(fn=globals()[f"cmd_{name.replace('-', '_')}"])
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
