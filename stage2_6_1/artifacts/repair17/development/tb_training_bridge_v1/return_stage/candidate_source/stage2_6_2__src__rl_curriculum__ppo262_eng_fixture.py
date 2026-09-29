"""阶段 2.6.2 Engineering Bridge:工程资格输入夹具构建器(ENGINEERING_ONLY)。

构造一个**结构完整、逐字段绑定一致**的新版资格输入目录,用于在工程沙箱
走通公共正路径(load_qualified_input 的全部校验):

- qualification plan(+digest)/result(PASS)/exposure(completed,one_shot);
- parameter pack v1(R2 rung_params/thresholds 的工程只读拷贝)与
  v2(合法小幅扰动对照)——两套事前构造的合法工程参数(K01 参数来源
  对照的正反例基础);
- V2 preprocessing bundle:手工合成 OHLCV(确定性公式,源码即文档)→
  attach_production_features(真实生产特征构造)→ RouteCPreprocessorV2
  fit 一次并冻结(消费侧零 refit);fit manifest 全部标 SYNTHETIC/
  ENGINEERING_ONLY,fit namespace 与训练/评估 namespace 分离。

本夹具不是真实资格:scope=engineering、全部工件带 engineering_only/
synthetic 标记、不含任何真实 exposure 消费。它不能(也不应)通过
expected_scope="formal" 的装载(见 ppo262_qualified_input.G01 语义)。
授权锚写在资格目录**外**,由本构建器以工程沙箱身份签发(ENGINEERING_ONLY)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.ppo262_qualified_input import (
    AUTHORIZATION_FORMAT,
    PARAMETER_PACK_FORMAT,
    PPO262E_ITERATION_ID,
    QUALIFICATION_EXPOSURE_FORMAT,
    QUALIFICATION_PLAN_FORMAT,
    QUALIFICATION_RESULT_FORMAT,
    _AUTH_BINDING_KEYS,
    authorization_binding_digest,
    parameter_pack_digest,
    qualification_plan_digest,
)

#: 工程 profile 身份(进入授权锚与 manifest)
ENG_PROFILE_ID = "ppo262_engineering_v1"
#: V2 bundle fit 来源标签 namespace(仅 manifest 标签;不派生任何 seed)
ENG_FIT_NAMESPACE = "ppo_eng_fit_262e"
#: 合成 fit 夹具身份(进入 FitManifestEntry.generator_identity)
ENG_FIT_FIXTURE_ID = "ppo262e-synthetic-fit-fixture-v1"
#: 夹具 source iteration 身份
ENG_FIXTURE_SOURCE_ITERATION = "s262e_fixture_v1"

#: 固定构建时间戳(字节确定性重建;非真实资格时间)
ENG_FIXTURE_CREATED_UTC = "2026-09-29T00:00:00Z"

#: pack v2 的合法扰动(相对 R2 rung_params;只动数值漂移类参数,
#: 不动结构参数 seg/state/mixture/distractor,保证生成合法性)
PACK_V2_DELTAS: dict[str, dict[str, dict[str, float]]] = {
    "c1_opportunity": {
        "D1": {"opp_drift_bps": 45.0, "vol_bps": 27.0}},
    "c2_context": {
        "D1": {"alpha_bps": 50.0, "cue_rate": 0.80}},
    "c3_cost": {
        "D1": {"alpha_bps": 58.0, "cue_rate": 0.20}},
}

#: 合成 OHLCV 夹具公式参数(3 个 fit episode;确定性,无 RNG)
ENG_FIT_FIXTURE_SPECS: tuple[dict[str, float], ...] = (
    {"start": 100.0, "drift": 0.0004, "amp": 0.0028,
     "period": 48.0, "phase": 0.0, "wick": 0.0016, "bars": 288},
    {"start": 250.0, "drift": -0.0003, "amp": 0.0042,
     "period": 36.0, "phase": 1.1, "wick": 0.0022, "bars": 288},
    {"start": 60.0, "drift": 0.0001, "amp": 0.0019,
     "period": 64.0, "phase": 2.3, "wick": 0.0011, "bars": 288},
)


def synthetic_ohlcv(spec: dict[str, float]) -> pd.DataFrame:
    """确定性合成 OHLCV(公式即文档;无随机源,逐字节可重建)。

    ret_t = drift + amp * sin(2π(t+phase)/period)
            + 0.35*amp * sin(2π(t+phase)/(period/3))
    open_t = close_{t-1};high/low 由当期振幅包络加 wick;volume 常数。
    """
    n = int(spec["bars"])
    t = np.arange(n, dtype=np.float64)
    ret = (
        spec["drift"]
        + spec["amp"] * np.sin(2 * np.pi * (t + spec["phase"])
                               / spec["period"])
        + 0.35 * spec["amp"] * np.sin(
            2 * np.pi * (t + spec["phase"]) / (spec["period"] / 3.0)))
    close = spec["start"] * np.cumprod(1.0 + ret)
    open_ = np.concatenate([[spec["start"]], close[:-1]])
    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    high = body_hi * (1.0 + spec["wick"])
    low = body_lo * (1.0 - spec["wick"])
    volume = np.full(n, 1000.0)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume})


def _fixture_episode_hash(df: pd.DataFrame) -> str:
    payload = df.to_csv(index=False, float_format="%.17g")
    return "e262fx-" + hashlib.sha256(
        payload.encode("utf-8")).hexdigest()


def build_frozen_v2_preprocessor():
    """合成夹具 fit -> 冻结 RouteCPreprocessorV2(一次性,消费侧零 refit)。

    返回 (preproc_v2, fixture_records)。fit 输入 = 3 个合成 episode 的
    8 生产特征列拼接(行置换不变;position 不参与 fit)。
    """
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS, attach_production_features,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        RouteCPreprocessor,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        FitManifestEntry, RouteCPreprocessorV2, episode_feature_matrix_hash,
    )

    dfs = [attach_production_features(synthetic_ohlcv(spec))
           for spec in ENG_FIT_FIXTURE_SPECS]
    fit_df = pd.concat(
        [df[list(PRODUCTION_FEATURE_COLUMNS)] for df in dfs],
        ignore_index=True)
    inner = RouteCPreprocessor.build_and_fit(fit_df)

    class _Ep:
        """episode_feature_matrix_hash 兼容的最小 episode 视图。"""

        def __init__(self, df: pd.DataFrame):
            self.df = df

    entries = [
        FitManifestEntry(
            namespace=ENG_FIT_NAMESPACE,
            family="eng_synthetic",
            rung="D1",
            pair_index=k,
            side="A",
            episode_hash=_fixture_episode_hash(df),
            feature_matrix_hash=episode_feature_matrix_hash(_Ep(df)),
            generator_identity=ENG_FIT_FIXTURE_ID,
        )
        for k, df in enumerate(dfs)]
    preproc = RouteCPreprocessorV2(inner, entries, ENG_FIT_NAMESPACE)
    return preproc, [
        {"pair_index": k, "bars": int(len(df)),
         "episode_hash": e.episode_hash,
         "generator_identity": e.generator_identity,
         "synthetic": True}
        for k, (df, e) in enumerate(zip(dfs, entries))]


def _engineering_pack(variant: str) -> dict[str, Any]:
    """工程参数 pack:variant v1=R2 只读拷贝;v2=合法扰动对照。"""
    from rl_curriculum.curriculum261_api import (
        qualification_r2_lock_marker,
    )
    from rl_curriculum.curriculum261_plan import load_locked_plan

    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    families = {
        fam: {
            "rung_params": json.loads(json.dumps(fp["rung_params"])),
            "reference_thresholds": json.loads(
                json.dumps(fp["reference_thresholds"])),
            "family_version": fp["family_version"],
        }
        for fam, fp in plan["families"].items()}
    if variant == "v2_perturbed":
        for fam, per_rung in PACK_V2_DELTAS.items():
            for rung, deltas in per_rung.items():
                families[fam]["rung_params"][rung] = {
                    **families[fam]["rung_params"][rung], **deltas}
    pack = {
        "format": PARAMETER_PACK_FORMAT,
        "iteration": PPO262E_ITERATION_ID,
        "variant": variant,
        "scope": "engineering",
        "engineering_only": True,
        "source": (
            "R2 qualification plan families rung_params/reference_thresholds"
            " 的工程只读拷贝" if variant == "v1_r2_reference" else
            "R2 拷贝 + PACK_V2_DELTAS 合法扰动(仅 D1 数值漂移类参数)"),
        "r2_plan_digest_reference": qualification_plan_digest_r2_note(),
        "families": families,
        "created_utc": ENG_FIXTURE_CREATED_UTC,
    }
    pack["digest"] = parameter_pack_digest(pack)
    return pack


def qualification_plan_digest_r2_note() -> str:
    from rl_curriculum.ppo262_input_lock import R2_EXPECTED_PLAN_DIGEST
    return R2_EXPECTED_PLAN_DIGEST


def _fixture_producer_identity() -> dict[str, str]:
    import rl_curriculum.ppo262_eng_fixture as mod

    return {
        "module": "ppo262_eng_fixture.py",
        "module_sha256": hashlib.sha256(
            Path(mod.__file__).read_bytes()).hexdigest(),
        "fixture_id": ENG_FIT_FIXTURE_ID,
    }


def build_eng_fixture(out_root: Path | str, *, variant: str = "v1_r2_reference",
                      verbose: bool = True) -> dict[str, Any]:
    """构建完整工程资格输入目录 + 目录外授权锚。

    输出:
      out_root/qualified_input_{variant}/  六件资格工件
      out_root/eng_authorization_{variant}.json  授权锚(目录外)
    """
    if variant not in ("v1_r2_reference", "v2_perturbed"):
        raise ValueError(f"未知 pack variant {variant!r}")
    out_root = Path(out_root)
    qual_dir = out_root / f"qualified_input_{variant}"
    auth_path = out_root / f"eng_authorization_{variant}.json"
    qual_dir.mkdir(parents=True, exist_ok=True)

    preproc, fixture_records = build_frozen_v2_preprocessor()
    preproc.serialize_envelope(
        qual_dir / "preprocessor_envelope.json")
    pack = _engineering_pack(variant)

    plan = {
        "format": QUALIFICATION_PLAN_FORMAT,
        "iteration": PPO262E_ITERATION_ID,
        "source_iteration": ENG_FIXTURE_SOURCE_ITERATION,
        "scope": "engineering",
        "engineering_only": True,
        "synthetic_fixture": True,
        "stage": "stage2_6_2",
        "created_utc": ENG_FIXTURE_CREATED_UTC,
        "robustness_gate": {
            "pass": True,
            "note": ("ENGINEERING_ONLY fixture: 结构完整的新版资格输入"
                     "工程样例,不是真实资格运行;不构成任何正式资格"),
        },
        "parameter_pack": {
            "digest": pack["digest"],
            "variant": variant,
            "format": pack["format"],
        },
        "preprocessor_bundle_hash": preproc.bundle_hash,
        "preprocessing": {
            "contract_version": "RouteCFeaturePreprocessing-v2",
            "fit_namespace": ENG_FIT_NAMESPACE,
            "fit_sources": "synthetic engineering fixtures(SYNTHETIC_ONLY)",
            "fit_fixture_records": fixture_records,
            "consumer_refit_forbidden": True,
        },
        "families": {
            fam: {
                "family_version": fp["family_version"],
                "rung_params_source": "parameter_pack",
            }
            for fam, fp in pack["families"].items()},
        "code_identity": _fixture_code_identity(preproc),
        "notes": (
            "工程沙箱输入:证明消费侧桥接(bank/env/训练/冷读)可用同一"
            "公共验证逻辑接通;真实正式资格仍需未来正式资格链签发"),
    }
    digest = qualification_plan_digest(plan)
    (qual_dir / "qualification_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    (qual_dir / "qualification_plan_digest.txt").write_text(
        digest + "\n", encoding="utf-8")
    (qual_dir / "qualification_result.json").write_text(
        json.dumps({
            "format": QUALIFICATION_RESULT_FORMAT,
            "iteration": PPO262E_ITERATION_ID,
            "source_iteration": ENG_FIXTURE_SOURCE_ITERATION,
            "plan_digest": digest,
            "verdict": "PASS",
            "engineering_only": True,
            "synthetic": True,
            "verdict_semantics": (
                "工程夹具自洽性 PASS:plan/result/exposure/pack/bundle "
                "绑定一致;不是课程资格判定,不进入正式证据目录"),
            "created_utc": ENG_FIXTURE_CREATED_UTC,
        }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (qual_dir / "qualification_exposure.json").write_text(
        json.dumps({
            "format": QUALIFICATION_EXPOSURE_FORMAT,
            "iteration": PPO262E_ITERATION_ID,
            "plan_digest": digest,
            "status": "completed",
            "one_shot": True,
            "contract": (
                "工程夹具无真实 exposure 消费;terminal 状态为夹具构建"
                "自洽语义,一次性不可重放"),
            "engineering_only": True,
            "written_utc": ENG_FIXTURE_CREATED_UTC,
        }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (qual_dir / "parameter_pack.json").write_text(
        json.dumps(pack, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    (qual_dir / "SYNTHETIC_ONLY.md").write_text(
        "# SYNTHETIC / ENGINEERING_ONLY\n\n"
        "本目录是工程资格输入夹具(非真实资格):scope=engineering,"
        "全部工件可由 ppo262 eng-fixture-build 重建,"
        "不得移动/改名/重哈希后冒充正式资格。\n",
        encoding="utf-8")

    bindings = {
        "qualification_plan_digest": digest,
        "parameter_pack_digest": pack["digest"],
        "preprocessor_bundle_hash": preproc.bundle_hash,
    }
    auth = {
        "format": AUTHORIZATION_FORMAT,
        "profile": ENG_PROFILE_ID,
        "scope": "engineering",
        "bindings": bindings,
        "binding_digest": authorization_binding_digest({
            **bindings, "profile": ENG_PROFILE_ID, "scope": "engineering"}),
        "authorized_consumption": (
            "工程 profile 的 bank 生成、V2 env 训练 256 步 smoke 与"
            " checkpoint 冷读;不解锁任何正式 probe/core/dev-eval/final"),
        "issued_by": (
            "engineering fixture builder(用户授权的工程沙箱;"
            "ENGINEERING_ONLY,非正式 admission 链)"),
        "engineering_only": True,
        "created_utc": ENG_FIXTURE_CREATED_UTC,
    }
    auth_path.write_text(
        json.dumps(auth, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")

    out = {
        "format": "ppo262e-eng-fixture-build-v1",
        "variant": variant,
        "qualification_dir": str(qual_dir),
        "authorization_path": str(auth_path),
        "qualification_plan_digest": digest,
        "parameter_pack_digest": pack["digest"],
        "preprocessor_bundle_hash": preproc.bundle_hash,
        "fit_fixture_records": fixture_records,
        "engineering_only": True,
    }
    if verbose:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def _fixture_code_identity(preproc: Any) -> dict[str, Any]:
    """Cq:资格(夹具)生产侧记录的共同执行语义 + 生产者身份。"""
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_identity,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.ppo262_input_lock import (
        PPO262_EXPECTED_VENDOR_SHA, vendor_status,
    )

    identity = {
        "producer": _fixture_producer_identity(),
        "cq_ct_semantics": "Cq(本计划记录)与 Ct(消费现场)允许不同"
                           " commit;以下共同执行语义字段必须逐字一致",
        "production_observation_identity": {
            k: v for k, v in production_observation_identity().items()
            if k in ("schema_hash", "feature_columns", "observation_dim",
                     "window_size", "strategy_file_sha256",
                     "feature_engineering_standard_sha256",
                     "env_core_version", "observation_spec_version")},
        "family_versions": {
            fam: spec.generator.family_version
            for fam, spec in family_specs().items()},
        "preprocessing_v2_contract_digest": (
            preprocessing_v2_contract_digest()),
        "vendor_sha": vendor_status()["sha"],
        "expected_vendor_sha": PPO262_EXPECTED_VENDOR_SHA,
    }
    return identity
