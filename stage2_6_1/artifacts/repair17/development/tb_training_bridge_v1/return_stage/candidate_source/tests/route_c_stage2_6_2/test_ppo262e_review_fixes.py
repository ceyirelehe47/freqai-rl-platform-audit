"""Engineering Bridge 返修测试:ChatGPT 终审 REVIEW.md B1-B4 反例复现。

对应 probes/RESULT.json 16 个受控用例与 QUOTA_RESULT.json 的语义,
全部在仓库内以公共实现复现(零原生生成、零 optimizer 更新、零 fit):
- B2.1:source_iteration_mismatch / exposure_iteration_mismatch /
  missing_producer_identity;
- N01:declared_fit_training_namespace_overlap(同源注入拒绝对照);
- B2.2:bank_cached_pack_mutation(消费边界重验);
- B1:route_report_no_consumers(真实 prepare 管线 + 哨兵消费边界);
- B3:cold_wrong_source_iteration / cold_missing_authorization_binding /
  cold_wrong_bank_and_seed;
- B4:配额预约-失败保守计数(注入 learn 异常,零真实训练)+ bank
  attempt 实计(注入派生重试)。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rl_curriculum.ppo262_qualified_input import (
    QualifiedInputError,
    authorization_binding_digest,
    load_qualified_input,
    parameter_pack_digest,
    qualification_plan_digest,
)


@pytest.fixture(scope="module")
def fixture_v1(tmp_path_factory):
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture
    return build_eng_fixture(tmp_path_factory.mktemp("rv_fx1"),
                             variant="v1_r2_reference", verbose=False)


@pytest.fixture(scope="module")
def fixture_v2(tmp_path_factory):
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture
    return build_eng_fixture(tmp_path_factory.mktemp("rv_fx2"),
                             variant="v2_perturbed", verbose=False)


def _reload(out, scope="engineering"):
    return load_qualified_input(
        out["qualification_dir"],
        authorization_path=out["authorization_path"],
        expected_scope=scope)


def _mutate(v1, tmp_path, filename, mutate):
    """复制夹具并改写一个 JSON 文件(保持其余原件不动)。"""
    new_root = tmp_path / "mut"
    shutil.copytree(v1["qualification_dir"], new_root)
    p = new_root / filename
    data = json.loads(p.read_text(encoding="utf-8"))
    mutate(data)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False,
                            sort_keys=True), encoding="utf-8")
    out = dict(v1)
    out["qualification_dir"] = str(new_root)
    return out


def _rebind_plan(v1, tmp_path, plan_mutator):
    """改 plan 后一致重算外层绑定(plan digest 文件 + 授权锚)。"""
    new_root = tmp_path / "rebind"
    shutil.copytree(v1["qualification_dir"], new_root)
    plan = json.loads(
        (new_root / "qualification_plan.json").read_text(encoding="utf-8"))
    plan_mutator(plan)
    (new_root / "qualification_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    digest = qualification_plan_digest(plan)
    (new_root / "qualification_plan_digest.txt").write_text(
        digest + "\n", encoding="utf-8")
    pack = json.loads(
        (new_root / "parameter_pack.json").read_text(encoding="utf-8"))
    auth_path = Path(str(v1["authorization_path"]))
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    auth["bindings"]["qualification_plan_digest"] = digest
    auth["bindings"]["parameter_pack_digest"] = parameter_pack_digest(pack)
    auth["binding_digest"] = authorization_binding_digest({
        **auth["bindings"], "profile": auth["profile"],
        "scope": auth["scope"]})
    new_auth = tmp_path / "auth_rebind.json"
    new_auth.write_text(json.dumps(auth), encoding="utf-8")
    out = dict(v1)
    out["qualification_dir"] = str(new_root)
    out["authorization_path"] = str(new_auth)
    return out


# ---------------------------------------------------------------- B2.1
def test_b21_result_source_iteration_mismatch_rejected(fixture_v1, tmp_path):
    """反例 source_iteration_mismatch:result 换源仍装载 => 已修:拒绝。"""
    out = _mutate(fixture_v1, tmp_path, "qualification_result.json",
                  lambda d: d.update(source_iteration="another_source"))
    with pytest.raises(QualifiedInputError) as ei:
        _reload(out)
    assert any("source_iteration" in p for p in ei.value.report["problems"])


def test_b21_exposure_iteration_mismatch_rejected(fixture_v1, tmp_path):
    out = _mutate(fixture_v1, tmp_path, "qualification_exposure.json",
                  lambda d: d.update(iteration="s999_r9"))
    with pytest.raises(QualifiedInputError) as ei:
        _reload(out)
    assert any("exposure iteration" in p
               for p in ei.value.report["problems"])


def test_b21_missing_producer_identity_rejected(fixture_v1, tmp_path):
    """反例 missing_producer_identity:删 producer 并一致重算外层绑定
    (plan digest/授权)——共同契约版本标签不能替代来源证据。"""
    def _drop_producer(plan):
        plan["code_identity"].pop("producer", None)
    out = _rebind_plan(fixture_v1, tmp_path, _drop_producer)
    with pytest.raises(QualifiedInputError) as ei:
        _reload(out)
    assert any("producer" in p for p in ei.value.report["problems"])


# ---------------------------------------------------------------- N01
def test_n01_declared_fit_training_namespace_overlap_rejected(
        fixture_v1, tmp_path):
    """反例 declared_fit_training_namespace_overlap:fit_namespace 改成
    实际训练 namespace 并一致重算绑定——同源串用必须在装载拒绝。"""
    def _overlap(plan):
        plan["preprocessing"]["fit_namespace"] = "ppo_eng_bank_262e"
    out = _rebind_plan(fixture_v1, tmp_path, _overlap)
    with pytest.raises(QualifiedInputError) as ei:
        _reload(out)
    assert any("fit namespace" in p for p in ei.value.report["problems"])


def test_n01_fit_namespace_261_collision_rejected(fixture_v1, tmp_path):
    """fit 标签兼作 261 正式 seed namespace => 同样拒绝。"""
    def _collide(plan):
        plan["preprocessing"]["fit_namespace"] = "qualification_r2"
    out = _rebind_plan(fixture_v1, tmp_path, _collide)
    with pytest.raises(QualifiedInputError):
        _reload(out)


# ---------------------------------------------------------------- B2.2
def test_b22_cached_pack_mutation_rejected_before_generation(
        fixture_v1, tmp_path):
    """反例 bank_cached_pack_mutation:装载后污染缓存 _pack,原实现在
    generator 边界观察到 999 且不拒;已修:verify_integrity 在真实
    生成前拒绝,零 recorder 调用、账本零事件。"""
    from rl_curriculum.ppo262_eng_profile import (
        QuotaLedger, generate_eng_bank,
    )
    qi = _reload(fixture_v1)
    ledger = QuotaLedger(tmp_path / "ledger.jsonl")
    calls = []

    def recorder(family, rung, side, params):
        calls.append((family, params))

    qi._pack["families"]["c1_opportunity"]["rung_params"]["D1"][
        "opp_drift_bps"] = 999.0
    with pytest.raises(QualifiedInputError) as ei:
        generate_eng_bank(qi, ledger, param_recorder=recorder)
    assert any("pack 缓存完整性" in p for p in ei.value.report["problems"])
    assert calls == []          # generator 边界零触达
    assert ledger.records() == []  # 零事件 = 零生成


def test_b22_returned_copy_mutation_safe(fixture_v1):
    """正例(原有行为保持):改 rung_params() 返回副本不影响缓存与
    后续消费。"""
    from rl_curriculum.ppo262_eng_profile import QuotaLedger  # noqa: F401
    qi = _reload(fixture_v1)
    params = qi.rung_params()
    params["c1_opportunity"]["D1"]["opp_drift_bps"] = 777.0
    qi.verify_integrity()  # 不抛
    assert qi.rung_params()["c1_opportunity"]["D1"][
        "opp_drift_bps"] == 42.0


def test_b22_authorization_cache_mutation_rejected(fixture_v1, tmp_path):
    from rl_curriculum.ppo262_eng_profile import (
        QuotaLedger, generate_eng_bank,
    )
    qi = _reload(fixture_v1)
    qi.authorization["bindings"]["parameter_pack_digest"] = "forged"
    ledger = QuotaLedger(tmp_path / "l2.jsonl")
    with pytest.raises(QualifiedInputError) as ei:
        generate_eng_bank(qi, ledger)
    assert any("authorization" in p for p in ei.value.report["problems"])


# ---------------------------------------------------------------- B1
def test_b1_route_check_drives_real_consumers(fixture_v1):
    """反例 route_report_no_consumers:原实现写报告字典、消费者零调用;
    已修:六入口走真实 prepare 管线,哨兵在 generate262_bank /
    build_261_policy_set 边界实测捕获 pack 参数。"""
    from rl_curriculum.ppo262_eng_profile import route_profile_inputs
    art = route_profile_inputs(_reload(fixture_v1))
    assert art["pass"] is True
    for cls in art["entry_classes"]:
        assert art["routes"][cls]["consumer_boundary_hits"][
            "generate262_bank"] >= 1
    assert art["default_context_official_r2"] is True
    assert art["cached_pack_tamper_rejected"] is True


def test_b1_default_context_keeps_official_r2(fixture_v1):
    """无 profile 上下文:共享 prepare 返回官方 R2 参数与官方 namespace。"""
    from rl_curriculum.ppo262_entry_specs import (
        PROFILE_BANK_NAMESPACE, prepare_config_dev_inputs,
        prepare_smoke_inputs,
    )
    from rl_curriculum.ppo262_cli import _locked_rung_params
    for prep, official_ns in ((prepare_smoke_inputs, "ppo_smoke_262"),
                              (prepare_config_dev_inputs,
                               "ppo_config_dev_262")):
        spec = prep()
        assert spec.namespace == official_ns
        assert spec.rung_params == _locked_rung_params()
        assert spec.namespace != PROFILE_BANK_NAMESPACE


def test_b1_context_switches_to_pack():
    """有 profile 上下文:同一 prepare 返回 pack 参数与工程 namespace。"""
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture
    from rl_curriculum.ppo262_entry_specs import (
        PROFILE_BANK_NAMESPACE, prepare_smoke_inputs,
    )
    from rl_curriculum.ppo262_qualified_input import (
        activated_profile_input, load_qualified_input,
    )
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = build_eng_fixture(td, variant="v2_perturbed", verbose=False)
        qi = load_qualified_input(
            out["qualification_dir"],
            authorization_path=out["authorization_path"],
            expected_scope="engineering")
        with activated_profile_input(qi):
            spec = prepare_smoke_inputs()
        assert spec.namespace == PROFILE_BANK_NAMESPACE
        assert spec.rung_params["c1_opportunity"]["D1"][
            "opp_drift_bps"] == 45.0


def test_b1_cli_official_commands_use_shared_resolver(
        fixture_v1, fixture_v2):
    """官方 cmd 的实调点确实经共享解析器(_locked_rung_params 的
    profile 上下文分支):v2 pack 与 R2 可区分——上下文内 45.0,
    退出后 42.0(旧默认不变)。"""
    from rl_curriculum.ppo262_cli import _locked_rung_params
    from rl_curriculum.ppo262_qualified_input import (
        activated_profile_input, load_qualified_input,
    )
    qi = load_qualified_input(
        fixture_v2["qualification_dir"],
        authorization_path=fixture_v2["authorization_path"],
        expected_scope="engineering")
    with activated_profile_input(qi):
        assert _locked_rung_params()["c1_opportunity"]["D1"][
            "opp_drift_bps"] == 45.0
    assert _locked_rung_params()["c1_opportunity"]["D1"][
        "opp_drift_bps"] == 42.0


# ---------------------------------------------------------------- B3


def _make_ckpt(fixture_v1, tmp_path):
    """最小零训练 checkpoint + 跨文件原件(与本文件测试自洽)。"""
    from rl_curriculum.ppo262_qualified_input import load_qualified_input
    from rl_curriculum.ppo262_eng_profile import (
        PPO262E_MODEL_SEED, PPO262E_SMOKE_CONFIG, PPO262E_SMOKE_STEPS,
        collect_frozen_probe, engineering_manifest,
    )
    from rl_curriculum.ppo262_train import save_model_with_manifest
    from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    from rl_curriculum.generator_api import EpisodeSpec, GeneratedEpisode
    from rl_curriculum.ppo262_banks import EpisodeKey, LoadedEpisode
    from rl_curriculum.curriculum261_api import episode_content_hash
    from rl_curriculum.ppo262_eng_fixture import synthetic_ohlcv
    from rl_curriculum.curriculum261_production_obs import (
        attach_production_features,
    )
    qi = load_qualified_input(
        fixture_v1["qualification_dir"],
        authorization_path=fixture_v1["authorization_path"],
        expected_scope="engineering")
    df = attach_production_features(synthetic_ohlcv({
        "start": 100.0, "drift": 0.0002, "amp": 0.003, "period": 24.0,
        "phase": 0.0, "wick": 0.0015, "bars": 96}))
    ep = GeneratedEpisode(
        spec=EpisodeSpec(family="eng_synthetic", params={"k": 0},
                         seed=9000, split="train", timeframe="15m"),
        df=df, hidden=df.iloc[:0].copy(), family_version="eng-synth-v0",
        timeframe="15m", is_null=False,
        generator_fingerprint="ppo262e-synthetic-fixture-v1")
    bank = [LoadedEpisode(
        key=EpisodeKey("ppo_eng_bank_262e", "c1_opportunity", "D1", 0, "A"),
        episode=ep, content_hash=episode_content_hash(ep)),
        LoadedEpisode(
            key=EpisodeKey("ppo_eng_bank_262e", "c2_context", "D1", 0, "B"),
            episode=ep, content_hash=episode_content_hash(ep))]
    env = CurriculumMultiEpisodeEnv(bank, preprocessor=qi.preprocessor)
    model = build_diagnosed_ppo(dict(PPO262E_SMOKE_CONFIG),
                                PPO262E_MODEL_SEED, env)
    out = tmp_path / "ckpt"
    out.mkdir()
    manifest = engineering_manifest(
        qi, bank=bank, steps=PPO262E_SMOKE_STEPS, updates=0,
        config=PPO262E_SMOKE_CONFIG, model_seed=PPO262E_MODEL_SEED)
    saved = save_model_with_manifest(
        model, out / "eng_ppo_smoke_256", manifest=manifest)
    probe = collect_frozen_probe(
        qi.preprocessor, bank, model, bundle_hash=qi.bundle_hash)
    import hashlib
    probe["binding_digest"] = "e262pb-" + hashlib.sha256(json.dumps(
        [saved["model_sha256"], qi.bundle_hash, probe["steps"],
         probe["reset_seed"]],
        sort_keys=True, separators=(",", ":")).encode(
        "utf-8")).hexdigest()
    (out / "eng_frozen_probe.json").write_text(
        json.dumps(probe), encoding="utf-8")
    (out / "eng_bank_smoke.json").write_text(json.dumps({
        "episodes": manifest["bank"]["keys"],
        "bank_manifest": {"manifest_sha256": manifest["bank"][
            "manifest_sha256"]},
        "synthetic_binding_fixture": True}), encoding="utf-8")
    (out / "eng_ppo_smoke.json").write_text(json.dumps({
        "steps": PPO262E_SMOKE_STEPS, "optimizer_update_records": [],
        "model_sha256": saved["model_sha256"],
        "bank_manifest_sha256": manifest["bank"]["manifest_sha256"],
        "synthetic_binding_fixture": True}), encoding="utf-8")
    return out, manifest


def test_b3_cold_read_positive_control(fixture_v1, tmp_path):
    from rl_curriculum.ppo262_eng_profile import cold_read_checkpoint
    out, _ = _make_ckpt(fixture_v1, tmp_path)
    result = cold_read_checkpoint(
        fixture_v1["qualification_dir"],
        fixture_v1["authorization_path"], out, tmp_path / "cr",
        expected_profile="ppo262_engineering_v1")
    assert result["pass"] is True


def _tamper_manifest(out_dir, mutate):
    p = Path(out_dir) / "eng_ppo_smoke_256.manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    mutate(m)
    p.write_text(json.dumps(m, indent=2, ensure_ascii=False),
                 encoding="utf-8")


def test_b3_cold_wrong_source_iteration_rejected(fixture_v1, tmp_path):
    from rl_curriculum.ppo262_eng_profile import cold_read_checkpoint
    out, _ = _make_ckpt(fixture_v1, tmp_path)
    _tamper_manifest(out, lambda m: m["qualified_input"].update(
        qualification_source_iteration="forged_src"))
    with pytest.raises(QualifiedInputError) as ei:
        cold_read_checkpoint(
            fixture_v1["qualification_dir"],
            fixture_v1["authorization_path"], out, tmp_path / "cr")
    assert any("qualification_source_iteration" in p
               for p in ei.value.report["problems"])


def test_b3_cold_missing_authorization_binding_rejected(
        fixture_v1, tmp_path):
    from rl_curriculum.ppo262_eng_profile import cold_read_checkpoint
    out, _ = _make_ckpt(fixture_v1, tmp_path)
    _tamper_manifest(
        out, lambda m: m["qualified_input"].pop(
            "authorization_binding_digest", None))
    with pytest.raises(QualifiedInputError) as ei:
        cold_read_checkpoint(
            fixture_v1["qualification_dir"],
            fixture_v1["authorization_path"], out, tmp_path / "cr")
    assert any("authorization_binding_digest" in p
               for p in ei.value.report["problems"])


def test_b3_cold_wrong_bank_and_seed_rejected(fixture_v1, tmp_path):
    """反例 cold_wrong_bank_and_seed:manifest 篡改 bank namespace/keys/
    数量/hash + model_seed=123 + steps=2048 => 模型 SHA 正确也拒绝。"""
    from rl_curriculum.ppo262_eng_profile import cold_read_checkpoint
    out, _ = _make_ckpt(fixture_v1, tmp_path)

    def _mutate(m):
        m["bank"]["namespace"] = "ppo_forge_262"
        m["bank"]["n_episodes"] = 999
        m["bank"]["keys"] = []
        m["bank"]["manifest_sha256"] = "f" * 64
        m["training"]["model_seed"] = 123
        m["training"]["total_timesteps"] = 2048
    _tamper_manifest(out, _mutate)
    with pytest.raises(QualifiedInputError) as ei:
        cold_read_checkpoint(
            fixture_v1["qualification_dir"],
            fixture_v1["authorization_path"], out, tmp_path / "cr")
    problems = " ".join(ei.value.report["problems"])
    assert "bank" in problems or "训练绑定" in problems



def test_b3_probe_binding_digest_tamper_rejected(fixture_v1, tmp_path):
    from rl_curriculum.ppo262_eng_profile import cold_read_checkpoint
    out, _ = _make_ckpt(fixture_v1, tmp_path)
    pp = Path(out) / "eng_frozen_probe.json"
    probe = json.loads(pp.read_text(encoding="utf-8"))
    probe["binding_digest"] = "e262pb-" + "0" * 64
    pp.write_text(json.dumps(probe), encoding="utf-8")
    with pytest.raises(QualifiedInputError) as ei:
        cold_read_checkpoint(
            fixture_v1["qualification_dir"],
            fixture_v1["authorization_path"], out, tmp_path / "cr")
    assert any("binding_digest" in p for p in ei.value.report["problems"])


# ---------------------------------------------------------------- B4
def test_b4_failed_smoke_counts_conservatively(fixture_v1, tmp_path,
                                                monkeypatch):
    """注入 learn 异常(零真实训练):每次失败都预约+终结计数;
    累计 8 次后第 9 次在额度检查处拒绝。"""
    from rl_curriculum import ppo262_eng_profile as prof
    from rl_curriculum.ppo262_qualified_input import load_qualified_input
    import rl_curriculum.ppo262_diag_train as diag
    import rl_curriculum.ppo262_env as envmod

    class _FakePolicy:
        def state_dict(self):
            return {}

    class _FakeModel:
        def __init__(self, env=None):
            self.diag_update_records = []
            self.policy = _FakePolicy()
            self.observation_space = getattr(
                env, "observation_space", None)

        def learn(self, **kw):
            raise RuntimeError("injected failure")

    class _FakeEnv:
        def __init__(self, *a, **kw):
            import gymnasium as gym
            import numpy as np
            low = np.full(9, -np.inf, dtype=np.float32)
            high = np.full(9, np.inf, dtype=np.float32)
            low[-1], high[-1] = 0.0, 1.0
            self.observation_space = gym.spaces.Box(
                low=low, high=high, dtype=np.float32)

        def audit(self):
            return {"steps_taken": 0, "exhausted_cycles": 0}

    monkeypatch.setattr(diag, "build_diagnosed_ppo",
                        lambda cfg, seed, env: _FakeModel(env))
    monkeypatch.setattr(envmod, "CurriculumMultiEpisodeEnv",
                        lambda bank, preprocessor=None: _FakeEnv())
    qi = load_qualified_input(
        fixture_v1["qualification_dir"],
        authorization_path=fixture_v1["authorization_path"],
        expected_scope="engineering")
    ledger = prof.QuotaLedger(tmp_path / "l.jsonl")
    for i in range(8):
        with pytest.raises(RuntimeError):
            prof.engineering_ppo_run(
                qi, [], ledger, tmp_path / f"run{i}")
    s = ledger.sums()
    assert s["ppo_smoke_runs"] == 8
    assert s["ppo_smoke_steps"] == 8 * 256  # 保守:预约全额
    with pytest.raises(QualifiedInputError):
        prof.engineering_ppo_run(qi, [], ledger, tmp_path / "run9")


def test_b4_unresolved_reservation_counted(tmp_path):
    """进程中断(无终结事件):预约残留保守计入,不当作零消费释放。"""
    from rl_curriculum.ppo262_eng_profile import QuotaLedger
    ledger = QuotaLedger(tmp_path / "l.jsonl")
    ledger.reserve_smoke("run_killed", 256)
    s = ledger.sums()
    assert s["ppo_smoke_runs"] == 1 and s["ppo_smoke_steps"] == 256
    ledger.append("ppo_smoke", run_id="run_killed", steps=256)
    s2 = ledger.sums()
    assert s2["ppo_smoke_runs"] == 1 and s2["ppo_smoke_steps"] == 256


def test_b4_bank_attempt_actual_counting(tmp_path, monkeypatch):
    """结构性重试实计:注入 5 次派生尝试后失败 => pair_attempts=5、
    候选=计划6+超出(10-6)=10(episode 级,不低估)。"""
    from rl_curriculum import ppo262_banks as banks
    from rl_curriculum import ppo262_eng_profile as prof
    from rl_curriculum.generator_api import GeneratorError

    def _retrying_pair(family, rung, pair_index, *, namespace,
                       locked_rung_params, derive_seed_fn=None,
                       param_recorder=None):
        for attempt in range(5):
            derive_seed_fn(namespace, family, rung, pair_index, attempt)
        raise GeneratorError("structural fail injected")

    monkeypatch.setattr(banks, "generate262_pair", _retrying_pair)
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = build_eng_fixture(td, variant="v1_r2_reference",
                                verbose=False)
        qi = load_qualified_input(
            out["qualification_dir"],
            authorization_path=out["authorization_path"],
            expected_scope="engineering")
        ledger = prof.QuotaLedger(tmp_path / "l.jsonl")
        with pytest.raises(GeneratorError):
            prof.generate_eng_bank(qi, ledger)
        recs = ledger.records()
        fail = [r for r in recs if r["event"] == "bank_generation_failed"]
        assert fail and fail[0]["pair_attempts"] == 5
        assert ledger.sums()["bank_episode_candidate"] == 10
        assert ledger.sums()["bank_episode_success"] == 0


def test_p2_consumer_identity_covers_generator_and_env_modules():
    """P2 闭合:family generator 与 env core 模块进消费代码哈希面;
    记录哈希被改 => 迁移路径拒绝(行为级漂移可检测)。"""
    from rl_curriculum.ppo262_eng_profile import (
        _CONSUMER_CODE_MODULES, _consumer_code_identity,
        _verify_identity_at_commit,
    )
    ids = _consumer_code_identity()
    for name in ("curriculum261_pairs.py", "curriculum261_c1.py",
                 "curriculum261_c2.py", "curriculum261_c3.py",
                 "curriculum261_production_obs.py",
                 "../rl_platform/env.py"):
        assert name in _CONSUMER_CODE_MODULES
        assert len(ids.get(name, "")) == 64
    # G2 未篡改对照:构造 C4 时刻的 18 键身份(活树身份中把 C6 相对
    # C4 改过的模块逐个替换为 dec94b85 blob 哈希),对产出候选 C4
    # 的迁移验证必须通过;env 键经 stage2_6_0* 家族根解析
    import hashlib as _hl
    import subprocess as _sp
    recorded = dict(ids)
    from rl_curriculum.ppo262_eng_profile import _repo_root
    for mod in ("ppo262_eng_profile.py", "ppo262_qualified_input.py"):
        blob = _sp.run(
            ["git", "-C", str(_repo_root()), "show",
             "dec94b8593fcd3233dea1958db0da2b1692165a2:"
             f"stage2_6_2/src/rl_curriculum/{mod}"],
            capture_output=True, check=True).stdout
        recorded[mod] = _hl.sha256(
            blob.replace(b"\r\n", b"\n")).hexdigest()
    assert _verify_identity_at_commit(
        recorded, "dec94b8593fcd3233dea1958db0da2b1692165a2") is True
    forged = {"ppo262_env.py": "0" * 64}
    assert _verify_identity_at_commit(
        forged, "e565298dad8063df70775dfdd47e3bf682f29926") is False


def _c2_recorded_identity():
    """C2 时刻 10 模块身份(全部取自 e565298d 归档 blob)。"""
    import hashlib as _hl
    import subprocess as _sp
    from rl_curriculum.ppo262_eng_profile import (
        _repo_root, _required_consumer_modules)
    repo = _repo_root()
    commit = "e565298dad8063df70775dfdd47e3bf682f29926"
    required = _required_consumer_modules(repo, commit)
    assert required and len(required) == 10
    out = {}
    for name in required:
        blob = _sp.run(
            ["git", "-C", str(repo), "show",
             f"{commit}:stage2_6_2/src/rl_curriculum/{name}"],
            capture_output=True, check=True).stdout
        out[name] = _hl.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()
    return out


def test_r1_migration_contract_rejects_empty_subset_invalid_commit():
    """R1:空记录/任意子集/非法 commit 不能自证完整;必需集合由
    候选归档源码合同确定;合法 C2 完整迁移仍通过。"""
    from rl_curriculum.ppo262_eng_profile import _verify_identity_at_commit
    c2 = _c2_recorded_identity()
    # 正例:完整 C2 身份对 e565298d 通过
    assert _verify_identity_at_commit(
        c2, "e565298dad8063df70775dfdd47e3bf682f29926") is True
    # 空记录 + 有效 commit => 拒
    assert _verify_identity_at_commit(
        {}, "e565298dad8063df70775dfdd47e3bf682f29926") is False
    # 空记录 + 非法 commit => 拒(commit 真实性独立于记录校验)
    assert _verify_identity_at_commit({}, "not-a-commit") is False
    # 非空记录 + 非法 commit => 拒
    assert _verify_identity_at_commit(c2, "not-a-commit") is False
    # 任意子集(缺任一必需键) => 拒
    for drop in ("ppo262_qualified_input.py", "ppo262_train.py"):
        subset = {k: v for k, v in c2.items() if k != drop}
        assert _verify_identity_at_commit(
            subset, "e565298dad8063df70775dfdd47e3bf682f29926") is False
    # 错模块字节(合法键集合,伪造哈希) => 拒
    forged = dict(c2)
    forged["ppo262_env.py"] = "0" * 64
    assert _verify_identity_at_commit(
        forged, "e565298dad8063df70775dfdd47e3bf682f29926") is False


def test_r1_cold_read_rejects_empty_code_identity_before_load(tmp_path,
                                                              monkeypatch):
    """R1 冷读层:清空 code_identity_consumer 的迁移 manifest 必须在
    PPO.load 边界之前被拒绝(sentinel 证明未到达模型反序列化)。"""
    import json
    import shutil
    from rl_curriculum import ppo262_eng_profile as prof
    from rl_curriculum.ppo262_qualified_input import QualifiedInputError
    from rl_curriculum.ppo262_eng_profile import _repo_root
    eng = (_repo_root()
           / "stage2_6_2/artifacts/eng_training_bridge_v1")
    qd = tmp_path / "qualified"
    shutil.copytree(eng / "qualified_input_v1_r2_reference", qd)
    auth = tmp_path / "auth.json"
    shutil.copy2(eng / "eng_authorization_v1_r2_reference.json", auth)
    modeldir = tmp_path / "model"
    modeldir.mkdir()
    for f in ("eng_ppo_smoke_256.zip", "eng_ppo_smoke_256.manifest.json",
              "eng_ppo_smoke_256.manifest.v2.json",
              "eng_frozen_probe.json", "eng_bank_smoke.json",
              "eng_ppo_smoke.json"):
        if (eng / f).is_file():
            shutil.copy2(eng / f, modeldir / f)
    mp = modeldir / "eng_ppo_smoke_256.manifest.v2.json"
    if not mp.exists():
        mp = modeldir / "eng_ppo_smoke_256.manifest.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["code_identity_consumer"] = {}
    m["candidate_commit"] = "e565298dad8063df70775dfdd47e3bf682f29926"
    mp.write_text(json.dumps(m, indent=2), encoding="utf-8")

    class _StopBeforeLoad(Exception):
        pass

    def _sentinel(*a, **k):
        raise _StopBeforeLoad("PPO.load reached")

    import stable_baselines3 as _sb3
    monkeypatch.setattr(_sb3.PPO, "load", staticmethod(_sentinel))
    with pytest.raises(QualifiedInputError):
        prof.cold_read_checkpoint(
            qd, auth, modeldir, tmp_path / "out",
            expected_profile="ppo262_engineering_v1")


def test_r2_fit_source_declaration_must_match_envelope(tmp_path):
    """R2:plan 声明的 fit namespace/fixture records 与 envelope 实际
    fit manifest 逐项关联;改名/换 episode_hash 且外层摘要自洽仍拒;
    未改声明的正例继续装载。零生成零 fit。"""
    import json
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture
    from rl_curriculum.ppo262_qualified_input import (
        QualifiedInputError, authorization_binding_digest,
        load_qualified_input, qualification_plan_digest)

    out = build_eng_fixture(str(tmp_path), variant="v1_r2_reference",
                            verbose=False)
    qd = Path(out["qualification_dir"])
    auth_p = Path(out["authorization_path"])

    def _rebind_and_load(mut):
        plan = json.loads((qd / "qualification_plan.json").read_text(
            encoding="utf-8"))
        mut(plan)
        (qd / "qualification_plan.json").write_text(
            json.dumps(plan, indent=2), encoding="utf-8")
        pd = qualification_plan_digest(plan)
        (qd / "qualification_plan_digest.txt").write_text(
            pd, encoding="utf-8")
        for f in ("qualification_result.json",
                  "qualification_exposure.json"):
            x = json.loads((qd / f).read_text(encoding="utf-8"))
            x["plan_digest"] = pd
            (qd / f).write_text(
                json.dumps(x, indent=2), encoding="utf-8")
        a = json.loads(auth_p.read_text(encoding="utf-8"))
        a["bindings"]["qualification_plan_digest"] = pd
        a["binding_digest"] = authorization_binding_digest(
            {**a["bindings"], "profile": a["profile"],
             "scope": a["scope"]})
        auth_p.write_text(json.dumps(a, indent=2), encoding="utf-8")
        load_qualified_input(qd, authorization_path=auth_p,
                             expected_scope="engineering")

    # 反例 1:fit_namespace 改为另一个不在禁止集合中的名字
    with pytest.raises(QualifiedInputError):
        _rebind_and_load(lambda p: p["preprocessing"].update(
            fit_namespace="invented_not_actual_fit"))
    # 反例 2:fit_fixture_records episode_hash 虚构
    with pytest.raises(QualifiedInputError):
        _rebind_and_load(lambda p: p["preprocessing"]
                         ["fit_fixture_records"][0].update(
                             episode_hash="e262fx-INVENTED"))
    # 正例:重新构建未改声明的夹具,装载通过
    out2 = build_eng_fixture(str(tmp_path / "pos"),
                             variant="v1_r2_reference", verbose=False)
    load_qualified_input(
        out2["qualification_dir"],
        authorization_path=out2["authorization_path"],
        expected_scope="engineering")
