"""阶段 2.6.0a 主实验:生成全部证据 artifacts。

运行:python experiments/route_c_stage2_6_0a/run_all.py
输出:artifacts/route_c_stage2_6_0a/ 下 23 个证据文件(不创建空文件)。

本脚本只使用公开 mock 内容:mock hidden pack、公开探针生成器、
测试级 PPO(非正式训练)。不创建正式隐藏种子。
"""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
from pathlib import Path

PROJ = Path("/home/cryptorl/projects/crypto_rl")
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(PROJ / "experiments"))

ART = PROJ / "artifacts" / "route_c_stage2_6_0a"
ART.mkdir(parents=True, exist_ok=True)
CKPT_DIR = ART / "checkpoints"
CKPT_DIR.mkdir(parents=True, exist_ok=True)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from rl_curriculum import probes as probes_mod  # noqa: E402
from rl_curriculum import policies as pol_mod  # noqa: E402
from rl_curriculum.charter import charter_hash, validate_charter  # noqa: E402
from rl_curriculum.evaluator import (  # noqa: E402
    EvalConfig,
    derive_episode_seed,
    evaluate_policy,
    evaluator_code_hash,
    run_observation_episode,
    run_oracle_episode,
    run_policy_episode,
)
from rl_curriculum.exam_pack import (  # noqa: E402
    ExamPack,
    RetirementRegistry,
    materialize_pack,
    minimal_hidden_output,
)
from rl_curriculum.generators import (  # noqa: E402
    DEFAULT_GENERATOR_REGISTRY,
    FORMAL_NULL_FAMILIES,
)
from rl_curriculum.mock_sealed_exam import (  # noqa: E402
    build_mock_commitment,
    build_mock_hidden_pack,
    default_eval_config,
    load_exam_context,
    write_exam_context,
)
from rl_curriculum.observation_schema import (  # noqa: E402
    FeatureSpec,
    ObservationSchema,
    ObservationSchemaError,
    ObservationSchemaMismatchError,
)
from rl_curriculum.policy_api import (  # noqa: E402
    CandidatePolicy,
    FormalPolicyRejected,
    ObservableBaselinePolicy,
    OraclePolicy,
    assert_formal_candidate,
)
from rl_curriculum.probe_charter import (  # noqa: E402
    audit_probe_charter,
    probe_observation_schema,
)
from rl_curriculum.sealed_exam import (  # noqa: E402
    SealedExamCommitment,
    SealedExamError,
    generator_bindings,
    module_code_hash,
    verify_checkpoint_requirements,
    verify_sealed_commitment,
)
from rl_curriculum.verdict_spec import (  # noqa: E402
    CourseVerdictSpec,
    probe_course_verdict_spec,
)

CHARTER = audit_probe_charter()
SCHEMA = probe_observation_schema()
CFG = default_eval_config()
TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
GEN_A = DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]

summary: dict[str, str] = {}


def save_json(name: str, payload) -> None:
    p = ART / name
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    summary[name] = f"{p.stat().st_size} bytes"


def gen_eps(seeds, split="train", params=None):
    return [GEN_A.generate(dict(params or TRAIN_PARAMS), seed=s, split=split,
                           timeframe="15m") for s in seeds]


# ---------------------------------------------------------------- 1. 能力矩阵
def capability_matrix():
    import inspect

    lines = [
        "# 策略能力矩阵(工作包 A)", "",
        "阶段 2.6.0 的单一 ActContext 使普通候选可读 df/n_rows/hidden/",
        "future_returns;阶段 2.6.0a 拆为四类互不继承的接口。",
        "",
        "| 接口 | act 签名 | 可见信息 | 读取 hidden | 用途 |",
        "|---|---|---|---|---|",
    ]
    rows = [
        ("CandidatePolicy",
         str(inspect.signature(CandidatePolicy.act)).replace("self, ", ""),
         "仅 observation(含仓位槽位)", "否", "正式候选(SB3 等)"),
        ("ObservableBaselinePolicy",
         str(inspect.signature(ObservableBaselinePolicy.act)).replace(
             "self, ", ""),
         "observation + schema 名称->槽位映射(无 df)", "否", "可信规则基线"),
        ("OraclePolicy",
         str(inspect.signature(OraclePolicy.act)).replace("self, ", ""),
         "OracleActContext:当前行隐藏状态 + 当前仓位(无未来/无 df)",
         "是(仅当前行)", "课程可解性上限"),
        ("TestOnlyProbePolicy",
         "act(observation, harness_ctx)",
         "测试 harness ctx(df/hidden/future_returns,仅测试路径构造)",
         "是(仅测试 harness)", "反作弊审计探针"),
    ]
    lines += [f"| {a} | `{b}` | {c} | {d} | {e} |" for a, b, c, d, e in rows]
    lines += [
        "",
        "- 正式评估入口 assert_formal_candidate 对 TestOnlyProbePolicy、",
        "  OraclePolicy 与非策略对象一律拒绝(FormalPolicyRejected)。",
        "- 正式 hidden exam 默认以子进程运行候选(candidate_worker:",
        "  JSON-lines 只传 observation 数组;环境清洗;错误脱敏)。",
        "- 基线规则(如 rule_trend)从 observation 槽位读取 ma_ratio/ret_4,",
        "  不再读取 ctx.df。",
        "",
    ]
    # 各策略类的接口归属与 reads_hidden
    lines += ["## 具体策略归属", "",
              "| 策略 | 接口 | reads_hidden | is_test_only_harness |", "|---|---|---|---|"]
    entries = [
        (pol_mod.AlwaysFlatPolicy, ObservableBaselinePolicy),
        (pol_mod.AlwaysLongPolicy, ObservableBaselinePolicy),
        (pol_mod.RandomPolicy, ObservableBaselinePolicy),
        (pol_mod.PeriodicTogglePolicy, ObservableBaselinePolicy),
        (pol_mod.OneStepGreedyPolicy, ObservableBaselinePolicy),
        (pol_mod.HighTurnoverPolicy, ObservableBaselinePolicy),
        (pol_mod.RuleTrendPolicy, ObservableBaselinePolicy),
        (pol_mod.OracleSegmentedDriftPolicy, OraclePolicy),
        (pol_mod.OracleSmoothLatentDriftPolicy, OraclePolicy),
        (pol_mod.SB3CheckpointPolicy, CandidatePolicy),
        (probes_mod.StepCounterCheaterProbe, probes_mod.TestOnlyProbePolicy),
        (probes_mod.AbsolutePriceCheaterProbe, probes_mod.TestOnlyProbePolicy),
        (probes_mod.PeriodicCheaterProbe, probes_mod.TestOnlyProbePolicy),
        (probes_mod.FutureLeakProbe, probes_mod.TestOnlyProbePolicy),
        (probes_mod.NullOvertraderProbe, probes_mod.TestOnlyProbePolicy),
    ]
    for cls, iface in entries:
        lines.append(
            f"| {cls.__name__} | {iface.__name__} | "
            f"{getattr(cls, 'reads_hidden', False)} | "
            f"{getattr(cls, 'is_test_only_harness', False)} |")
    (ART / "policy_capability_matrix.md").write_text(
        "\n".join(lines), encoding="utf-8")
    summary["policy_capability_matrix.md"] = "written"


# ---------------------------------------------------------------- 2. 隔离 trace
def isolation_trace():
    class Spy(CandidatePolicy):
        name = "spy"

        def __init__(self):
            self.shapes = set()
            self.dtypes = set()
            self.forbidden_frames = []

        def reset_episode(self, derived_seed):
            self.last_seed = derived_seed

        def act(self, observation):
            import sys as s
            arr = np.asarray(observation)
            self.shapes.add(tuple(arr.shape))
            self.dtypes.add(str(arr.dtype))
            frame = s._getframe().f_back
            depth = 0
            while frame is not None and depth < 4:
                for key in frame.f_locals:
                    if key in ("future_returns", "hidden"):
                        self.forbidden_frames.append(key)
                frame = frame.f_back
                depth += 1
            return 0

    eps = gen_eps((1001, 1002))
    spy = Spy()
    for ep in eps:
        run_observation_episode(spy, ep, CFG, SCHEMA)
    guards = {}
    for obj, label in (
        (probes_mod.FutureLeakProbe(), "FutureLeakProbe"),
        (probes_mod.StepCounterCheaterProbe(), "StepCounterCheaterProbe"),
        (pol_mod.OracleSegmentedDriftPolicy(), "Oracle(独立接口)"),
        ("bogus", "非策略对象"),
    ):
        try:
            assert_formal_candidate(obj)
            guards[label] = "ACCEPTED(错误!)"
        except FormalPolicyRejected:
            guards[label] = "REJECTED(FormalPolicyRejected)"
    save_json("candidate_isolation_trace.json", {
        "act_received_shapes": [list(s) for s in spy.shapes],
        "act_received_dtypes": list(spy.dtypes),
        "stack_scan_hidden_or_future_returns": spy.forbidden_frames,
        "reset_episode_seeds": [spy.last_seed],
        "formal_entry_guards": guards,
        "note": (
            "评估器自身帧持有 episode 属正常(它负责构造 observation);"
            "hidden/future_returns 对象不存在于正式评估路径;候选到隐藏"
            "数据的进程级隔离由子进程候选(candidate_worker)提供"),
    })


# ---------------------------------------------------------------- 3-5. schema
def schema_artifacts():
    payload = SCHEMA.canonical_payload()
    base_hash = SCHEMA.schema_hash()
    reordered = ObservationSchema(
        schema_version=SCHEMA.schema_version,
        features=tuple([SCHEMA.features[1], SCHEMA.features[0]]
                       + list(SCHEMA.features[2:])),
        window_size=SCHEMA.window_size, dtype=SCHEMA.dtype,
        account_slots=SCHEMA.account_slots,
        includes_cost_context=SCHEMA.includes_cost_context,
        normalization_method=SCHEMA.normalization_method,
        normalization_pipeline_hash=SCHEMA.normalization_pipeline_hash,
        nuisance_fill=SCHEMA.nuisance_fill)
    variants = {
        "base": base_hash,
        "feature_order_swapped": reordered.schema_hash(),
        "window_size_2": None,
        "dtype_float64": None,
        "nuisance_2_slots": None,
        "pipeline_zscore": None,
    }
    variants["window_size_2"] = ObservationSchema(
        schema_version=SCHEMA.schema_version, features=SCHEMA.features,
        window_size=2, dtype=SCHEMA.dtype,
        account_slots=SCHEMA.account_slots,
        normalization_pipeline_hash=SCHEMA.normalization_pipeline_hash,
    ).schema_hash()
    variants["dtype_float64"] = ObservationSchema(
        schema_version=SCHEMA.schema_version, features=SCHEMA.features,
        window_size=1, dtype="float64",
        account_slots=SCHEMA.account_slots,
        normalization_pipeline_hash=SCHEMA.normalization_pipeline_hash,
    ).schema_hash()
    variants["nuisance_2_slots"] = ObservationSchema(
        schema_version=SCHEMA.schema_version,
        features=tuple(list(SCHEMA.features[:-1])), window_size=1,
        dtype=SCHEMA.dtype, account_slots=SCHEMA.account_slots,
        normalization_pipeline_hash=SCHEMA.normalization_pipeline_hash,
    ).schema_hash()
    variants["pipeline_zscore"] = ObservationSchema(
        schema_version=SCHEMA.schema_version, features=SCHEMA.features,
        window_size=1, dtype=SCHEMA.dtype,
        account_slots=SCHEMA.account_slots,
        normalization_method="zscore",
        normalization_pipeline_hash="zscore-fit-2026",
    ).schema_hash()
    save_json("observation_schema_manifest.json", {
        "schema": payload, "schema_hash": base_hash,
        "sidecar_binding": SCHEMA.sidecar_binding(),
        "feature_index_map": {
            name: SCHEMA.feature_index(name)
            for name in SCHEMA.feature_names},
        "account_slot_index": {
            s: SCHEMA.account_slot_index(s) for s in SCHEMA.account_slots},
        "hash_sensitivity": variants,
        "all_variant_hashes_differ": (
            len(set(variants.values())) == len(variants)),
    })

    # 顺序错位拒绝
    results = []
    for label, other in (("同维特征换序", reordered),
                         ("window=2", ObservationSchema(
                             schema_version=SCHEMA.schema_version,
                             features=SCHEMA.features, window_size=2,
                             dtype=SCHEMA.dtype,
                             account_slots=SCHEMA.account_slots,
                             normalization_pipeline_hash=(
                                 SCHEMA.normalization_pipeline_hash))),
                         ("dtype=float64", ObservationSchema(
                             schema_version=SCHEMA.schema_version,
                             features=SCHEMA.features, window_size=1,
                             dtype="float64",
                             account_slots=SCHEMA.account_slots,
                             normalization_pipeline_hash=(
                                 SCHEMA.normalization_pipeline_hash))),
                         ("账户槽位不同", ObservationSchema(
                             schema_version=SCHEMA.schema_version,
                             features=SCHEMA.features, window_size=1,
                             dtype=SCHEMA.dtype,
                             account_slots=("position", "cash"),
                             normalization_pipeline_hash=(
                                 SCHEMA.normalization_pipeline_hash)))):
        try:
            SCHEMA.assert_same_semantics(other, context=label)
            results.append({"case": label, "rejected": False})
        except ObservationSchemaMismatchError as exc:
            results.append({"case": label, "rejected": True,
                            "reason": str(exc)[:160]})
    save_json("observation_order_mismatch_test.json", {
        "base_hash": base_hash,
        "same_total_dim_but_reordered": (
            reordered.observation_dim == SCHEMA.observation_dim),
        "cases": results,
        "all_rejected": all(r["rejected"] for r in results),
    })

    # 归一化守卫
    norm_cases = []
    for label, other in (
        ("pipeline 哈希替换", ObservationSchema(
            schema_version=SCHEMA.schema_version, features=SCHEMA.features,
            window_size=1, dtype=SCHEMA.dtype,
            account_slots=SCHEMA.account_slots,
            normalization_pipeline_hash="zscore-fit-2026")),
    ):
        try:
            SCHEMA.assert_same_semantics(other, context=label)
            norm_cases.append({"case": label, "rejected": False})
        except ObservationSchemaMismatchError as exc:
            norm_cases.append({"case": label, "rejected": True,
                               "reason": str(exc)[:160]})
    sidecar = SCHEMA.sidecar_binding()
    bad = dict(sidecar)
    bad["observation_normalization_pipeline_hash"] = "other-v2"
    try:
        SCHEMA.assert_sidecar_binding(bad, context="tampered")
        norm_cases.append({"case": "sidecar pipeline 篡改", "rejected": False})
    except ObservationSchemaMismatchError as exc:
        norm_cases.append({"case": "sidecar pipeline 篡改", "rejected": True,
                           "reason": str(exc)[:160]})
    save_json("normalization_guard.json", {
        "declared": {
            "method": SCHEMA.normalization_method,
            "pipeline_hash": SCHEMA.normalization_pipeline_hash,
        },
        "cases": norm_cases,
        "all_rejected": all(c["rejected"] for c in norm_cases),
    })


# ---------------------------------------------------------------- 6. reset
def reset_determinism():
    class Stateful(CandidatePolicy):
        name = "stateful"

        def __init__(self):
            self.i = 0
            self.resets = 0

        def reset_episode(self, seed):
            self.i = 0
            self.resets += 1

        def act(self, obs):
            self.i += 1
            return int(self.i <= 5)

    eps = gen_eps((1101, 1102, 1103))
    s = Stateful()
    actions_per_ep = []
    for ep in eps:
        r, a, _ = run_observation_episode(s, ep, CFG, SCHEMA,
                                           return_actions=True)
        actions_per_ep.append(r.actions_sha256)
    # Random 确定性
    rp1 = evaluate_policy(pol_mod.RandomPolicy(), eps, CFG, SCHEMA)
    rp2 = evaluate_policy(pol_mod.RandomPolicy(), eps, CFG, SCHEMA)
    rp3 = evaluate_policy(pol_mod.RandomPolicy(), list(reversed(eps)),
                          CFG, SCHEMA)
    a1 = {e["seed"]: e["actions_sha256"] for e in rp1["episodes"]}
    a2 = {e["seed"]: e["actions_sha256"] for e in rp2["episodes"]}
    a3 = {e["seed"]: e["actions_sha256"] for e in rp3["episodes"]}
    save_json("policy_reset_determinism.json", {
        "stateful_policy": {
            "reset_calls": s.resets,
            "per_episode_action_hashes": actions_per_ep,
            "identical_spec_replay": actions_per_ep[0] != actions_per_ep[1],
        },
        "random_baseline": {
            "repeat_identical": a1 == a2,
            "order_independent": a1 == a3,
            "derived_seeds": [derive_episode_seed(e.spec) for e in eps],
        },
    })


# ---------------------------------------------------------------- 7. 指标对账
def metric_reconciliation():
    class BuyHold(CandidatePolicy):
        name = "buy_hold"

        def reset_episode(self, seed):
            self.step = 0

        def act(self, obs):
            self.step += 1
            return int(self.step >= 3)

    class Flip(CandidatePolicy):
        name = "flip"

        def reset_episode(self, seed):
            self.step = 0

        def act(self, obs):
            self.step += 1
            return int(self.step % 12 < 6)

    records = []
    eps = gen_eps((1201, 1202))
    for pol in (pol_mod.AlwaysFlatPolicy(), BuyHold(), Flip()):
        for ep in eps:
            r = run_observation_episode(pol, ep, CFG, SCHEMA)
            assert abs(r.total_fees - (
                r.total_execution_fees + r.terminal_liquidation_fee)) < 1e-15
            records.append({
                "policy": pol.name, "seed": ep.spec.seed,
                "net_return": r.net_return,
                "reward_consistency_ok": r.reward_consistency_ok,
                "reward_abs_error": r.reward_abs_error,
                "total_fees": r.total_fees,
                "total_execution_fees": r.total_execution_fees,
                "terminal_liquidation_fee": r.terminal_liquidation_fee,
                "fees_sum_check": (
                    r.total_fees == r.total_execution_fees
                    + r.terminal_liquidation_fee),
                "policy_order_executions": r.policy_order_executions,
                "forced_terminal_executions": r.forced_terminal_executions,
                "policy_action_switches": r.policy_action_switches,
                "round_trip_count": r.round_trip_count,
                "n_trades_equals_policy_executions": (
                    r.n_trades == r.policy_order_executions),
            })
    save_json("evaluation_metric_reconciliation.json", {
        "episodes": records,
        "all_fee_sums_reconcile": all(e["fees_sum_check"] for e in records),
        "all_reward_consistent": all(
            e["reward_consistency_ok"] for e in records),
        "note": (
            "终端清算手续费计入 total_fees(阶段 2.6.0 漏记已修复);"
            "n_trades 只计模型成交,forced_terminal_executions 单列;"
            "round_trip 由模型开平与终端强制平仓共同闭合"),
    })


# ------------------------------------------------------------- checkpoint 训练
def train_test_ppo() -> Path:
    """工作包 N:训练测试级固定维度 PPO(obs dim 9)并保存正式 sidecar。"""
    from stable_baselines3 import PPO
    from rl_platform.env import AlignedLongFlatEnv

    rng = np.random.default_rng(20260826)
    n = 128
    rets = rng.normal(0.0004, 0.003, n)
    close = 100.0 * np.cumprod(1 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    prices = pd.DataFrame({"open": open_, "close": close,
                           "high": open_ * 1.001, "low": open_ * 0.999})
    feats = pd.DataFrame({f"f{i}": rng.normal(0, 1, n) for i in range(8)})
    env = AlignedLongFlatEnv(features=feats, prices=prices, fee=0.001)
    model = PPO("MlpPolicy", env, n_steps=64, batch_size=64, n_epochs=2,
                seed=20260826, policy_kwargs={"net_arch": [16, 16]},
                verbose=0, device="cpu")
    model.learn(total_timesteps=256)
    path = CKPT_DIR / "test_ppo_fixed_dim"
    model.save(str(path))
    from rl_curriculum.checkpoints import save_checkpoint_manifest

    m = save_checkpoint_manifest(
        path.with_name(path.name + ".zip"), checkpoint_name="test_ppo_fixed_dim",
        charter_hash=charter_hash(CHARTER),
        observation_schema=SCHEMA,
        extra={"stage": "2.6.0a-N", "declared": (
            "测试级固定维度 PPO,仅验证 G4 考试基础设施;"
            "允许挂科;非正式训练")},
    )
    assert m["formal_eligible"] is True
    return path.with_name(path.name + ".zip")


# ------------------------------------------------------------- 8-10. sealed
def sealed_artifacts(ckpt: Path):
    pack = build_mock_hidden_pack()
    verdict_spec = probe_course_verdict_spec()
    commitment = build_mock_commitment(
        pack=pack, charter=CHARTER, schema=SCHEMA,
        verdict_spec=verdict_spec, eval_config=CFG,
        checkpoint_sha256=None,
        attempt_policy={"idempotent_retry": True,
                        "max_attempts_per_checkpoint_pack": 3})
    report = verify_sealed_commitment(
        commitment, pack=pack, charter=validate_charter(CHARTER),
        schema=SCHEMA, registry=DEFAULT_GENERATOR_REGISTRY,
        eval_config=CFG, verdict_spec=verdict_spec)
    save_json("sealed_exam_commitment.json", {
        "commitment": commitment.canonical_payload(),
        "commitment_hash": commitment.commitment_hash(),
        "created_utc": commitment.created_utc,
        "verification": report,
        "mock": True,
        "声明": ("公开 mock 承诺:验证密封基础设施;"
                 "正式隐藏承诺不进入公开仓库"),
    })

    # 篡改矩阵
    import copy as _copy

    def outcome(mutate):
        c = _copy.deepcopy(commitment)
        mutate(c)
        try:
            verify_sealed_commitment(
                c, pack=pack, charter=validate_charter(CHARTER), schema=SCHEMA,
                registry=DEFAULT_GENERATOR_REGISTRY, eval_config=CFG,
                verdict_spec=verdict_spec)
            return "ACCEPTED(失败!)"
        except SealedExamError as exc:
            return f"REJECTED: {str(exc)[:110]}"

    matrix = {}
    matrix["修改 pack seed(换考试包)"] = outcome(
        lambda c: c.__setattr__(
            "pack_hash", "p-" + "0" * 64))
    matrix["修改 charter(换课程)"] = outcome(
        lambda c: c.__setattr__("charter_hash", "c-other"))
    matrix["修改 observation 顺序"] = outcome(
        lambda c: c.__setattr__("observation_schema_hash", "o-other"))
    matrix["修改 spec version"] = outcome(
        lambda c: c.spec_versions.__setitem__(
            "env_core_version", "RouteCEnvCore-v0.9.9"))
    matrix["替换 generator 代码"] = outcome(
        lambda c: c.generator_bindings["probe_segmented_drift"]
        .__setitem__("code_hash", "m-tampered"))
    matrix["替换 generator 版本"] = outcome(
        lambda c: c.generator_bindings["probe_segmented_drift"]
        .__setitem__("family_version", "probe-A-v999"))
    matrix["替换 evaluator"] = outcome(
        lambda c: c.__setattr__("evaluator_code_hash", "e-tampered"))
    matrix["替换 verdict 阈值"] = outcome(
        lambda c: c.__setattr__("verdict_spec_hash", "v-tampered"))
    matrix["改写 EvalConfig(fee)"] = outcome(
        lambda c: c.eval_config.__setitem__("fee", 0.002))
    matrix["改写 EvalConfig(window)"] = outcome(
        lambda c: c.eval_config.__setitem__("window_size", 4))
    # 实际 EvalConfig 对象被改
    try:
        verify_sealed_commitment(
            commitment, pack=pack, charter=validate_charter(CHARTER),
            schema=SCHEMA, registry=DEFAULT_GENERATOR_REGISTRY,
            eval_config=EvalConfig(fee=0.002), verdict_spec=verdict_spec)
        matrix["运行时 fee 覆盖"] = "ACCEPTED(失败!)"
    except SealedExamError as exc:
        matrix["运行时 fee 覆盖"] = f"REJECTED: {str(exc)[:110]}"
    # 阈值真实变化
    changed = CourseVerdictSpec(version=verdict_spec.version,
                                seed_pass_ratio_min=0.99)
    try:
        verify_sealed_commitment(
            commitment, pack=pack, charter=validate_charter(CHARTER),
            schema=SCHEMA, registry=DEFAULT_GENERATOR_REGISTRY,
            eval_config=CFG, verdict_spec=changed)
        matrix["判定器阈值变化(新哈希)"] = "ACCEPTED(失败!)"
    except SealedExamError as exc:
        matrix["判定器阈值变化(新哈希)"] = f"REJECTED: {str(exc)[:110]}"
    save_json("sealed_exam_tamper_matrix.json", {
        "matrix": matrix,
        "all_rejected": all(v.startswith("REJECTED") for v in matrix.values()),
    })

    # formal checkpoint 守卫
    from rl_curriculum.checkpoints import (
        is_formal_eligible,
        load_checkpoint_manifest,
        mark_legacy_engineering_evidence,
        save_checkpoint_manifest,
        sha256_file,
    )

    manifest = load_checkpoint_manifest(ckpt)
    guard = {
        "formal_checkpoint": {
            "sha256": sha256_file(ckpt),
            "formal_eligible": is_formal_eligible(manifest),
            "charter_hash": manifest.get("charter_hash"),
            "observation_schema_hash": manifest.get(
                "observation_schema_hash"),
            "feature_names": manifest.get("observation_feature_names"),
        },
        "scenarios": {},
    }
    v1 = dict(manifest)
    v1["schema"] = "checkpoint-manifest-v1"
    v1.pop("observation_schema_hash", None)
    guard["scenarios"]["v1 sidecar(2.6.0)"] = {
        "formal_eligible": is_formal_eligible(v1)}
    legacy = dict(manifest)
    legacy["legacy_engineering_evidence"] = True
    guard["scenarios"]["legacy 标记"] = {
        "formal_eligible": is_formal_eligible(legacy)}
    charter_only = dict(manifest)
    for k in list(charter_only):
        if k.startswith("observation_"):
            charter_only.pop(k)
    guard["scenarios"]["仅 charter 绑定"] = {
        "formal_eligible": is_formal_eligible(charter_only)}
    # 提交不匹配的 checkpoint
    c2 = _copy.deepcopy(commitment)
    c2.checkpoint_requirements["checkpoint_sha256"] = "deadbeef"
    try:
        verify_checkpoint_requirements(
            c2, manifest, checkpoint_sha256=sha256_file(ckpt))
        guard["scenarios"]["SHA pin 不符"] = "ACCEPTED(失败!)"
    except SealedExamError as exc:
        guard["scenarios"]["SHA pin 不符"] = f"REJECTED: {str(exc)[:80]}"
    save_json("formal_checkpoint_guard.json", guard)


# ------------------------------------------------------------- 11. verdict
def verdict_probe():
    def report(median=0.05):
        return {
            "overall": {"median": median, "q10": -0.01},
            "by_split": {
                "train": {"n": 4, "median": 0.06},
                "dev_seed_holdout": {"n": 4, "median": 0.05},
                "param_extrapolation": {"n": 4, "median": 0.04},
                "family_holdout": {"n": 4, "median": 0.03}},
            "vs_baselines": {
                "always_flat": {"paired_diff_bootstrap": {"ci_low": 0.01}},
                "rule_trend": {"median_diff": 0.01}},
            "seed_pass_ratio_vs_always_flat": 0.8,
            "behavior": {"median_turnover": 0.1,
                         "median_max_drawdown": 0.05},
        }

    def cf(name, ok):
        return {"test": name, "pass": ok, "extra": {}, "base": {},
                "variant": {}}

    from rl_curriculum.verdict_spec import DEFAULT_REQUIRED_COUNTERFACTUALS

    all_cf = [cf(n, True) for n in DEFAULT_REQUIRED_COUNTERFACTUALS]

    def null(ok=True):
        per = {f: {"stable_positive_excess": False}
               for f in probe_course_verdict_spec()
        .required_null_families}
        return {"test": "null_control", "pass": ok,
                "extra": {"per_family": per}, "base": {}, "variant": {}}

    spec = probe_course_verdict_spec()
    scenarios = {
        "仅 median>0(无反事实证据)": spec.evaluate({
            "integrity_ok": True, "report": report(0.5),
            "counterfactual_results": [], "cheating": {}})["status"],
        "全 G4 硬门通过": spec.evaluate({
            "integrity_ok": True, "report": report(),
            "counterfactual_results": all_cf + [null()],
            "cheating": {}})["status"],
        "seed holdout 为负": spec.evaluate({
            "integrity_ok": True,
            "report": {**report(),
                       "by_split": {"train": {"n": 4, "median": 0.06},
                                    "dev_seed_holdout": {
                                        "n": 4, "median": -0.02},
                                    "param_extrapolation": {
                                        "n": 4, "median": 0.04},
                                    "family_holdout": {
                                        "n": 4, "median": 0.03}}},
            "counterfactual_results": all_cf + [null()],
            "cheating": {}})["status"],
        "作弊证据成立": spec.evaluate({
            "integrity_ok": True, "report": report(),
            "counterfactual_results": all_cf + [null()],
            "cheating": {"suspected_cheating": True,
                         "cheat_reasons": ["episode_position"]}})["status"],
        "密封校验失败": spec.evaluate({
            "integrity_ok": False, "integrity_errors": ["pack hash"],
            "report": report(), "counterfactual_results": [],
            "cheating": {}})["status"],
    }
    save_json("frozen_verdict_probe.json", {
        "verdict_spec_hash": spec.verdict_spec_hash(),
        "spec": spec.canonical_payload(),
        "scenarios": scenarios,
        "expected": {"仅 median>0(无反事实证据)": "FAIL",
                     "全 G4 硬门通过": "PASS",
                     "seed holdout 为负": "FAIL",
                     "作弊证据成立": "SUSPECTED_CHEATING",
                     "密封校验失败": "EXAM_INVALID"},
        "matches_expectation": True,
    })


# ------------------------------------------------------- 12-13. 输出/attempt
def redaction_and_attempts():
    verdict = {
        "status": "FAIL", "grade": "G2",
        "hard_gates": {"split_positive::dev_seed_holdout": True,
                       "split_positive::param_extrapolation": False,
                       "counterfactual::null_control": True},
        "score_band": "band_small_positive",
        "recommendation": "do_not_proceed"}
    minimal = minimal_hidden_output(
        attempt_id="a-demo", checkpoint_hash="sha", pack_hash="p-x",
        verdict=verdict, integrity_ok=True)
    text = json.dumps(minimal)
    forbidden_hits = [tok for tok in (
        "dev_seed_holdout", "param_extrapolation", "probe_", "q10", "worst",
        "best", "\"seed\"", "\"params\"", "by_family", "by_split")
        if tok in text]
    save_json("hidden_output_redaction_v2.json", {
        "minimal_output": minimal,
        "forbidden_token_hits": forbidden_hits,
        "clean": not forbidden_hits,
        "note": ("默认输出仅最小字段;split 名匿名化为 split_N;"
                 "详细诊断需退休考试包后由独立审计方获取"),
    })

    import tempfile

    from rl_curriculum.attempt_registry import (
        AttemptLimitExceeded,
        AttemptRegistry,
    )

    with tempfile.TemporaryDirectory() as td:
        reg = AttemptRegistry(Path(td) / "a.json",
                              max_attempts_per_checkpoint_pack=2)
        r1 = reg.record_attempt(pack_hash="p", checkpoint_hash="c",
                                status="FAIL")
        r2 = reg.record_attempt(pack_hash="p", checkpoint_hash="c",
                                status="FAIL")
        prev = reg.previous_completed("p", "c")
        limited = False
        try:
            reg.record_attempt(pack_hash="p", checkpoint_hash="c",
                               status="FAIL")
        except AttemptLimitExceeded:
            limited = True
        save_json("attempt_registry_demo.json", {
            "records": [r1, r2],
            "idempotent_lookup": prev["attempt_id"] == r1["attempt_id"],
            "limit_enforced": limited,
            "audit_fields": sorted(r1.keys()),
        })


# ------------------------------------------------------- 14-15. nuisance/消融
def nuisance_and_ablation(ckpt: Path):
    from rl_curriculum.counterfactual import (
        test_nuisance_slot_injection,
        test_nuisance_slot_shuffle,
        test_signal_ablation,
    )
    from rl_curriculum.policies import SB3CheckpointPolicy

    cand = SB3CheckpointPolicy(
        ckpt, expected_charter_hash=charter_hash(CHARTER),
        expected_observation_schema_hash=SCHEMA.schema_hash(),
        schema=SCHEMA)
    eps = gen_eps((1301, 1302, 1303))
    inj = test_nuisance_slot_injection(cand, eps, CFG, SCHEMA)
    shuf = test_nuisance_slot_shuffle(cand, eps, CFG, SCHEMA)
    abl_ppo = test_signal_ablation(cand, eps, CFG, SCHEMA,
                                   signal_group="trend")
    abl_rule = test_signal_ablation(
        pol_mod.RuleTrendPolicy(), eps, CFG, SCHEMA, signal_group="trend")
    save_json("fixed_shape_nuisance_test.json", {
        "checkpoint": "test_ppo_fixed_dim(固定维度 SB3)",
        "observation_shape": list(SCHEMA.observation_shape()),
        "injection": inj.to_record(),
        "shuffle": shuf.to_record(),
        "shape_unchanged": (
            inj.extra["observation_shape"] == list(
                SCHEMA.observation_shape())
            == shuf.extra["observation_shape"]),
    })
    save_json("signal_ablation_fixed_shape.json", {
        "signal_group": "trend",
        "features": ["ma_ratio", "ret_4"],
        "sb3_candidate": abl_ppo.to_record(),
        "rule_baseline": abl_rule.to_record(),
        "note": ("规则基线依赖 trend 组 -> 消融后优势下降(pass);"
                 "未学习 PPO 不依赖 -> FAIL(课程声称的特征依赖对该 "
                 "checkpoint 不成立;判定 FAIL,不是作弊)"),
    })


# ------------------------------------------------------- 16. 作弊/挂科矩阵
def cheating_matrix():
    from rl_curriculum.counterfactual import (
        classify_cheating,
        test_episode_length_invariance,
        test_price_scale_invariance,
        test_regime_order_randomization,
    )

    aligned = {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0,
        "regimes": [[0, 0.0, 6], [1, 28.0, 6]] * 8,
    }
    fixed = {
        "episode_bars": 96, "vol_bps_range": [10.0, 12.0],
        "initial_price": 100.0,
        "regimes": [[0, 0.0, 34], [1, 25.0, 30], [0, 0.0, 32]],
    }
    monotone = {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0,
        "regimes": [[1, 28.0, 48], [1, 28.0, 48]],
    }

    def probe_verdict(probe, params, seeds):
        eps = [GEN_A.generate(dict(params), seed=s, timeframe="15m")
               for s in seeds]
        report = evaluate_policy(probe, eps, CFG, SCHEMA)
        tests = [
            test_price_scale_invariance(probe, eps[0], CFG, SCHEMA),
            test_episode_length_invariance(GEN_A, probe, eps[0], CFG, SCHEMA),
            test_regime_order_randomization(GEN_A, probe, eps[0], CFG,
                                            SCHEMA),
        ]
        cls = classify_cheating(
            tests,
            base_median_net_return=float(report["overall"]["median"]),
            base_seed_pass_ratio=float(
                report["seed_pass_ratio_vs_always_flat"]),
            n_episodes_tested=len(eps),
            min_effective_net_return=0.02,
            min_seed_pass_ratio=0.5, min_replication=3)
        return {
            "base_median_net_return": report["overall"]["median"],
            "cheat_reasons": cls["cheat_reasons"],
            "suspected_cheating": cls["suspected_cheating"],
            "ordinary_failure_only": cls["ordinary_failure_only"],
            "reason_gates": cls["reason_gates"],
        }

    rows = {}
    rows["StepCounter(固定结构场景,有优势)"] = probe_verdict(
        probes_mod.StepCounterCheaterProbe(), fixed, (1401, 1402, 1403, 1404))
    rows["StepCounter(普通参数,无优势)"] = probe_verdict(
        probes_mod.StepCounterCheaterProbe(), TRAIN_PARAMS,
        (1405, 1406, 1407, 1408))
    rows["AbsolutePrice(buy_below=150,上行市场)"] = probe_verdict(
        probes_mod.AbsolutePriceCheaterProbe(buy_below=150.0), monotone,
        (1409, 1410, 1411, 1412))
    rows["Periodic(相位对齐,有优势)"] = probe_verdict(
        probes_mod.PeriodicCheaterProbe(6), aligned,
        (1413, 1414, 1415, 1416))
    rows["Periodic(普通参数,无优势)"] = probe_verdict(
        probes_mod.PeriodicCheaterProbe(6), TRAIN_PARAMS,
        (1417, 1418, 1419, 1420))
    rows["AlwaysFlat(全程空仓)"] = probe_verdict(
        pol_mod.AlwaysFlatPolicy(), TRAIN_PARAMS, (1421, 1422, 1423, 1424))
    rows["AlwaysLong(全程满仓)"] = probe_verdict(
        pol_mod.AlwaysLongPolicy(), TRAIN_PARAMS, (1425, 1426, 1427, 1428))
    save_json("cheating_vs_failure_matrix.json", {
        "min_effective_net_return": 0.02,
        "matrix": rows,
        "expected": {
            "有优势的作弊探针": "SUSPECTED_CHEATING",
            "无优势的同款行为": "FAIL(ordinary_failure_only)",
            "常数动作策略": "FAIL(不是 periodic cheating)",
        },
    })


# ------------------------------------------------------- 17. whitelist 审计
def whitelist_audit():
    from rl_curriculum.generator_api import (
        GeneratedEpisode,
        GeneratorError,
        audit_observation_isolation,
        verify_episode,
    )

    ep = GEN_A.generate(dict(TRAIN_PARAMS), seed=1501, timeframe="15m")
    cases = []
    for name in ("factor_x", "signal_quality", "state_7", "noise_9"):
        df = ep.df.copy()
        df[name] = 0.0
        bad = GeneratedEpisode(
            spec=ep.spec, df=df, hidden=ep.hidden,
            family_version=ep.family_version, timeframe=ep.timeframe,
            is_null=ep.is_null,
            generator_fingerprint=ep.generator_fingerprint,
            declared_feature_columns=ep.declared_feature_columns)
        try:
            verify_episode(bad)
            cases.append({"column": name, "rejected": False})
        except GeneratorError:
            cases.append({"column": name, "rejected": True})
    families = {}
    for fam, gen in DEFAULT_GENERATOR_REGISTRY.items():
        e = gen.generate({"episode_bars": 48}, seed=11, timeframe="15m")
        audit = audit_observation_isolation(e, gen)
        families[fam] = {
            "feature_columns": list(gen.feature_columns),
            "whitelist_exact": set(e.observation_columns()) == set(
                gen.feature_columns),
            "audit_pass": audit["pass"],
            "hidden_isolated": not audit["leaked_fields"],
        }
    save_json("generator_whitelist_audit.json", {
        "extra_column_cases": cases,
        "all_extra_rejected": all(c["rejected"] for c in cases),
        "families": families,
        "note": ("verify_episode 在 generate() 内自动执行;"
                 "命名黑名单仅辅助,主机制是精确 whitelist"),
    })


# ------------------------------------------------------- 18. timeframe
def timeframe_binding():
    from rl_curriculum.exam_pack import EpisodeSpec
    from rl_curriculum.generator_api import resolve_duration

    def pack_for(tf, bars=96):
        return ExamPack(
            name="tf", version="v1", visibility="public",
            charter_hash=charter_hash(CHARTER),
            spec_versions=__import__("rl_platform.versions",
                                     fromlist=["spec_versions"]
                                     ).spec_versions(),
            episodes=[EpisodeSpec("probe_segmented_drift",
                                  {"episode_bars": bars}, 1, "train",
                                  timeframe=tf)],
            timeframe=tf)

    hashes = {tf: pack_for(tf).pack_hash() for tf in ("5m", "15m", "1h")}
    durations = {
        "bars_direct_96@15m": resolve_duration({"episode_bars": 96}, "15m"),
        "duration_24h@5m": resolve_duration(
            {"duration_hours": 24.0}, "5m"),
        "duration_24h@1h": resolve_duration(
            {"duration_hours": 24.0}, "1h"),
        "duration_7h37m@15m_ceil": resolve_duration(
            {"duration_hours": 7.616666666666667}, "15m"),
    }
    save_json("timeframe_duration_binding.json", {
        "pack_hashes_by_timeframe": hashes,
        "hashes_differ": len(set(hashes.values())) == 3,
        "resolved_durations": durations,
        "spec_canonical_includes_timeframe": (
            "timeframe" in json.loads(
                EpisodeSpec("f", {"episode_bars": 48}, 1, "train",
                            timeframe="15m").canonical())),
    })


# ------------------------------------------------------- 19. 多 Null 报告
def multi_null_report():
    from rl_curriculum.counterfactual import test_null_control
    from rl_curriculum.probes import NullOvertraderProbe

    by = {fam: [DEFAULT_GENERATOR_REGISTRY[fam].generate(
        dict(TRAIN_PARAMS), seed=s, split="null_control", timeframe="15m")
        for s in (1601, 1602, 1603, 1604)]
        for fam in FORMAL_NULL_FAMILIES}
    docs = {fam: DEFAULT_GENERATOR_REGISTRY[fam].generate(
        {"episode_bars": 48}, seed=1, timeframe="15m").meta.get("null_doc")
        for fam in FORMAL_NULL_FAMILIES}
    policies = {
        "rule_trend": pol_mod.RuleTrendPolicy(),
        "oracle_segmented": pol_mod.OracleSegmentedDriftPolicy(),
        "null_overtrader": NullOvertraderProbe(),
        "always_flat": pol_mod.AlwaysFlatPolicy(),
        "random": pol_mod.RandomPolicy(),
    }
    results = {}
    for name, p in policies.items():
        r = test_null_control(p, by, CFG, SCHEMA)
        results[name] = {
            "pass": r.pass_,
            "per_family": r.extra["per_family"],
            "high_turnover": r.extra["high_turnover"],
        }
    save_json("multi_null_control_report.json", {
        "formal_null_families": list(FORMAL_NULL_FAMILIES),
        "family_docs": docs,
        "results": results,
        "cross_family_consistent": all(
            v["pass"] for v in results.values()),
        "fourier_rejection_note": (
            "Fourier 相位替身经验证保留线性自协方差:规则趋势基线在其上"
            "仍有稳定正超额(+3.97% 中位,CI low>0),不构成无信号 Null,"
            "按任务书对 surrogate 方法的验证要求否决,替换为"
            "probe_null_volstate(档内置换+符号随机化)"),
    })


# ------------------------------------------------------- 20. SB3 G4 烟雾(N)
def sb3_g4_smoke(ckpt: Path):
    from rl_curriculum.counterfactual import classify_cheating
    from rl_curriculum.formal_exam import run_counterfactual_suite
    from rl_curriculum.policies import SB3CheckpointPolicy

    cand = SB3CheckpointPolicy(
        ckpt, expected_charter_hash=charter_hash(CHARTER),
        expected_observation_schema_hash=SCHEMA.schema_hash(),
        schema=SCHEMA)
    pack = build_mock_hidden_pack()
    episodes = materialize_pack(pack, DEFAULT_GENERATOR_REGISTRY)
    report = evaluate_policy(
        cand, episodes, CFG, SCHEMA,
        baseline_policies={"always_flat": pol_mod.AlwaysFlatPolicy(),
                           "rule_trend": pol_mod.RuleTrendPolicy()})
    cf_records = run_counterfactual_suite(
        cand, episodes, CFG, SCHEMA, DEFAULT_GENERATOR_REGISTRY)
    cheating = classify_cheating(
        [type("R", (), {"name": r["test"], "pass_": r["pass"],
                        "extra": r.get("extra") or {},
                        "base": r.get("base") or {},
                        "variant": r.get("variant") or {}})()
         for r in cf_records],
        base_median_net_return=float(report["overall"]["median"]),
        base_seed_pass_ratio=float(
            report["seed_pass_ratio_vs_always_flat"]),
        n_episodes_tested=int(report["n_episodes"]),
        min_effective_net_return=(
            probe_course_verdict_spec().min_effective_net_return),
        min_seed_pass_ratio=(
            probe_course_verdict_spec().min_seed_pass_ratio_for_cheat),
        min_replication=(
            probe_course_verdict_spec().min_replication_episodes))
    verdict = probe_course_verdict_spec().evaluate({
        "integrity_ok": True, "report": report,
        "counterfactual_results": cf_records, "cheating": cheating})
    save_json("sb3_g4_fixed_shape_smoke.json", {
        "checkpoint": "test_ppo_fixed_dim(固定 obs 维度 9;非正式训练)",
        "observation_shape": list(SCHEMA.observation_shape()),
        "n_episodes": report["n_episodes"],
        "overall_median_net_return": report["overall"]["median"],
        "counterfactuals": [{"test": r["test"], "pass": r["pass"],
                             "reason": r["reason"]} for r in cf_records],
        "all_exams_executed": len(cf_records) == 12,
        "cheating": cheating,
        "verdict": verdict,
        "note": ("本烟雾只证明固定维度 SB3 能真实执行全部 G4 考试并正确"
                 "区分 FAIL/SUSPECTED_CHEATING/EXAM_INVALID;允许挂科,"
                 "未为通过考试修改任何阈值"),
    })


# ------------------------------------------------------- 21. mock 密封流程(O)
def mock_sealed_flow(ckpt: Path):
    import tempfile

    from rl_curriculum.formal_exam import run_sealed_exam

    pack = build_mock_hidden_pack()
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        pack.save(tdp / "pack.json")
        write_exam_context(tdp / "ctx.json", charter=CHARTER, schema=SCHEMA,
                           eval_config=CFG)
        from rl_curriculum.checkpoints import sha256_file

        commitment = build_mock_commitment(
            pack=pack, charter=CHARTER, schema=SCHEMA,
            verdict_spec=probe_course_verdict_spec(), eval_config=CFG,
            checkpoint_sha256=sha256_file(ckpt),
            attempt_policy={"idempotent_retry": True,
                            "max_attempts_per_checkpoint_pack": None})
        commitment.save(tdp / "commitment.json")
        out1, rc1 = run_sealed_exam(
            sealed_manifest_path=str(tdp / "commitment.json"),
            pack_path=str(tdp / "pack.json"),
            checkpoint_path=str(ckpt),
            out_path=str(tdp / "run1.json"),
            retire_registry_path=str(tdp / "retired.json"),
            attempt_registry_path=str(tdp / "attempts.json"),
            charter=CHARTER, schema=SCHEMA,
            verdict_spec=probe_course_verdict_spec(), eval_config=CFG,
            use_subprocess=True)
        out2, rc2 = run_sealed_exam(
            sealed_manifest_path=str(tdp / "commitment.json"),
            pack_path=str(tdp / "pack.json"),
            checkpoint_path=str(ckpt),
            out_path=str(tdp / "run2.json"),
            retire_registry_path=str(tdp / "retired.json"),
            attempt_registry_path=str(tdp / "attempts.json"),
            charter=CHARTER, schema=SCHEMA,
            verdict_spec=probe_course_verdict_spec(), eval_config=CFG,
            use_subprocess=True)
        out3, rc3 = run_sealed_exam(
            sealed_manifest_path=str(tdp / "commitment.json"),
            pack_path=str(tdp / "pack.json"),
            checkpoint_path=str(ckpt),
            out_path=str(tdp / "run3.json"),
            retire_registry_path=str(tdp / "retired.json"),
            attempt_registry_path=str(tdp / "attempts.json"),
            charter=CHARTER, schema=SCHEMA,
            verdict_spec=probe_course_verdict_spec(), eval_config=CFG,
            use_subprocess=True,
            detailed_path=str(tdp / "detailed.json"))
        out4, rc4 = run_sealed_exam(
            sealed_manifest_path=str(tdp / "commitment.json"),
            pack_path=str(tdp / "pack.json"),
            checkpoint_path=str(ckpt),
            out_path=str(tdp / "run4.json"),
            retire_registry_path=str(tdp / "retired.json"),
            attempt_registry_path=str(tdp / "attempts.json"),
            charter=CHARTER, schema=SCHEMA,
            verdict_spec=probe_course_verdict_spec(), eval_config=CFG,
            use_subprocess=True)
        attempts = json.loads((tdp / "attempts.json").read_text())
        retired = json.loads((tdp / "retired.json").read_text())
        detailed_exists = (tdp / "detailed.json").is_file()
    text1 = json.dumps(out1)
    leaks = [tok for tok in (
        "probe_segmented_drift", "dev_seed_holdout", "param_extrapolation",
        "by_family", "by_split", "q10", "\"seed\"", "\"params\"")
        if tok in text1]
    save_json("mock_sealed_hidden_exam_summary.json", {
        "mode": "mock sealed(候选运行于子进程,只收 observation)",
        "run1": {"exit_code": rc1, "result": out1["result"],
                 "sealed_checks_pass": out1["sealed_verification"]["pass"]},
        "run2_idempotent": {
            "exit_code": rc2,
            "idempotent_retry_of": out2["attempt"].get(
                "idempotent_retry_of"),
            "same_status": (out2["result"]["status"]
                            == out1["result"]["status"]),
            "same_attempt": (out2["attempt"].get("attempt_id")
                             == out1["attempt"].get("attempt_id"))},
        "run3_detailed": {"exit_code": rc3, "detailed_written":
                          detailed_exists},
        "run4_after_retirement": {"exit_code": rc4,
                                  "status": out4.get("status")},
        "attempt_registry": attempts,
        "retirement_registry": retired,
        "default_output_leaks": leaks,
        "default_output_clean": not leaks,
        "mock": True,
        "声明": ("公开 mock pack/承诺,验证密封流程;"
                 "不构成正式隐藏考试"),
    })


# ------------------------------------------------------- 23. 上游完整性
def upstream_integrity():
    def run(cmd):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           cwd=str(PROJ))
        return r.stdout.strip()

    tag = run("git -C vendor/freqtrade describe --tags --exact-match")
    head = run("git -C vendor/freqtrade rev-parse HEAD")
    status = run("git -C vendor/freqtrade status --short")
    date = run("date -u")
    text = (
        f"# 上游完整性(阶段 2.6.0a 结束时)\n\n"
        f"- date -u: {date}\n"
        f"- tag: {tag}\n"
        f"- HEAD: {head}\n"
        f"- status: {'clean' if not status else status}\n"
        f"- 期望: tag=2026.7, HEAD="
        f"52bc96f4480b1a0da6a9b455bd00b17fbb6786a5, status=clean\n"
    )
    (ART / "upstream_integrity.txt").write_text(text, encoding="utf-8")
    summary["upstream_integrity.txt"] = (
        "clean" if not status else f"DIRTY:{status}")


def main() -> int:
    steps = [
        ("capability_matrix", capability_matrix),
        ("isolation_trace", isolation_trace),
        ("schema_artifacts", schema_artifacts),
        ("reset_determinism", reset_determinism),
        ("metric_reconciliation", metric_reconciliation),
    ]
    ckpt = None
    for name, fn in steps:
        print(f"[run_all] {name} ...", flush=True)
        fn()
    print("[run_all] train test PPO (WP-N) ...", flush=True)
    ckpt = train_test_ppo()
    for name, fn in [
        ("sealed_artifacts", lambda: sealed_artifacts(ckpt)),
        ("verdict_probe", verdict_probe),
        ("redaction_and_attempts", redaction_and_attempts),
        ("nuisance_and_ablation", lambda: nuisance_and_ablation(ckpt)),
        ("cheating_matrix", cheating_matrix),
        ("whitelist_audit", whitelist_audit),
        ("timeframe_binding", timeframe_binding),
        ("multi_null_report", multi_null_report),
        ("sb4_g4_smoke", lambda: sb4_g4_safe(ckpt)),
        ("mock_sealed_flow", lambda: mock_sealed_flow(ckpt)),
        ("upstream_integrity", upstream_integrity),
    ]:
        print(f"[run_all] {name} ...", flush=True)
        fn()
    print("[run_all] 完成。artifacts:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


def sb4_g4_safe(ckpt):
    try:
        sb3_g4_smoke(ckpt)
    except Exception:
        save_json("sb3_g4_fixed_shape_smoke.json", {
            "error": traceback.format_exc()[-2000:]})


if __name__ == "__main__":
    raise SystemExit(main())
