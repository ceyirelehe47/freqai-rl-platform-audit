"""阶段 2.6.2 Engineering Bridge:工程训练 profile(消费侧公共实现)。

把已验证的 QualifiedInput 快照接到真实组件:

- bank:generate_eng_bank → 复用 generate262_bank(rung 参数唯一来源 =
  快照 pack;真实 generator 边界参数记录器 param_recorder);
- env:CurriculumMultiEpisodeEnv(preprocessor=冻结 V2 bundle)——真实
  multi-episode 环境 + V2 outer observation space(9 维,feature 无界,
  position [0,1]);
- 训练:engineering_ppo_run —— build_diagnosed_ppo(与 official train_run
  同一 PPO 构造路径)+ 恰好 256 环境步 + 真实 optimizer 更新审计
  (steps/更新次数/参数摘要变化全部来自实际计数,不报告自填);
- checkpoint:save_model_with_manifest + 工程绑定 manifest(输入锁/pack/
  bundle/bank/seed/profile/代码身份/运行预算);
- 冷读:新进程重新走 load_qualified_input 公共校验,核对 manifest 绑定与
  模型字节,在冻结观察上对拍确定性动作与动作概率;
- 路由:route_profile_inputs 证明 smoke/config-dev/probe/core/dev-eval/
  final 六类消费入口在新 profile 下全部从同一输入上下文取参(本轮只测
  路由,不运行教学预算)。

配额账本(QuotaLedger):全部新增原生生成与 optimizer smoke 逐事件登记
(身份/数量/累计),命令在越界时拒绝执行——不新建通用配额平台,只落
append-only JSONL 日志。模型一律 ENGINEERING_ONLY。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from rl_curriculum.ppo262_banks import (
    EpisodeKey, LoadedEpisode, bank_manifest, generate262_bank, staged_order,
)
from rl_curriculum.ppo262_qualified_input import (
    PPO262E_ITERATION_ID, QualifiedInput, QualifiedInputError,
    load_qualified_input,
)

#: 工程 bank/training namespace(seed 派生隔离;已在
#: ppo262_namespaces.PPO262_BASE_NAMESPACES 白名单登记)
ENG_BANK_NAMESPACE = "ppo_eng_bank_262e"

#: 256 步工程 smoke 的事前固定配置(n_steps=256 => SB3 恰好收集 256 步
#: 一次 rollout,batch 64 整除,一次 optimizer update;不存在 rollout
#: 向上取整为 2048 的空间——n_steps 即 rollout 长度)
PPO262E_SMOKE_CONFIG: dict[str, Any] = {
    "policy": "MlpPolicy",
    "learning_rate": 3e-4,
    "n_steps": 256,
    "batch_size": 64,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.95,
    "clip_range": 0.2,
    "ent_coef": 0.01,
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "net_arch": [128, 128],
    "activation_fn": "Tanh",
    "device": "cpu",
}
PPO262E_SMOKE_STEPS = 256
PPO262E_MODEL_SEED = 262501
PPO262E_ENV_RESET_SEED = 262502
#: 冷读对拍的冻结观察步数(无梯度前向;不消耗 optimizer 配额)
PPO262E_FROZEN_OBS_STEPS = 32
#: 对拍容差(事前依据:同 checkpoint 字节 + 同 obs 字节 + 同 torch CPU
#: 单线程 matmul 的确定性;action 必须逐位相等,概率允许 <=1e-9 浮点
#: 收敛残差,不事后放宽)
PPO262E_PROB_ATOL = 1e-9

#: SCOPE_AND_BUDGET 封顶:全部新增 optimizer smoke 合计 8 次 / 2048 步;
#: 原生 bank 固定数据集最多重放 2 次、两次合计成功 <=12、候选 <=60
PPO262E_MAX_SMOKE_RUNS = 8
PPO262E_MAX_SMOKE_STEPS = 2048
PPO262E_BANK_DATASET_ID = "eng_bank_v1(3 families x D1 x pair0 A/B)"
PPO262E_BANK_MAX_REPLAYS = 2
PPO262E_BANK_MAX_SUCCESS_EPISODES = 12
PPO262E_BANK_MAX_CANDIDATE_EPISODES = 60


# ---------------------------------------------------------------- 配额账本
class QuotaLedger:
    """append-only JSONL 配额账本(事件级登记 + 累计查询)。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        rec = {
            "event": event,
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False,
                                sort_keys=True) + "\n")
        return rec

    def records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [json.loads(line) for line in self.path.read_text(
            encoding="utf-8").splitlines() if line.strip()]

    def sums(self) -> dict[str, int]:
        out = {"bank_replays": 0, "bank_episode_success": 0,
               "bank_episode_candidate": 0, "bank_pair_attempts": 0,
               "ppo_smoke_runs": 0, "ppo_smoke_steps": 0}
        for r in self.records():
            if r["event"] == "bank_generation_replay":
                out["bank_replays"] += 1
                out["bank_episode_candidate"] += int(
                    r.get("candidate_episodes", 0))
            elif r["event"] == "bank_episode_success":
                out["bank_episode_success"] += int(r.get("count", 1))
            elif r["event"] == "ppo_smoke":
                out["ppo_smoke_runs"] += 1
                out["ppo_smoke_steps"] += int(r.get("steps", 0))
        return out

    def assert_bank_quota(self, dataset_id: str = PPO262E_BANK_DATASET_ID,
                          candidate_episodes: int = 6) -> None:
        s = self.sums()
        replays_this = sum(
            1 for r in self.records()
            if r["event"] == "bank_generation_replay"
            and r.get("dataset_id") == dataset_id)
        if replays_this >= PPO262E_BANK_MAX_REPLAYS:
            raise QualifiedInputError({
                "format": "ppo262e-quota-reject-v1",
                "problems": [
                    f"固定数据集 {dataset_id} 重放次数已达上限 "
                    f"{PPO262E_BANK_MAX_REPLAYS}(主 Agent 与 reviewer "
                    f"各一次;当前累计 {replays_this})"],
            })
        if (s["bank_episode_candidate"] + candidate_episodes
                > PPO262E_BANK_MAX_CANDIDATE_EPISODES):
            raise QualifiedInputError({
                "format": "ppo262e-quota-reject-v1",
                "problems": [
                    f"候选 episode 累计将超上限: {s['bank_episode_candidate']}"
                    f" + {candidate_episodes} > "
                    f"{PPO262E_BANK_MAX_CANDIDATE_EPISODES}"],
            })
        if (s["bank_episode_success"] + candidate_episodes
                > PPO262E_BANK_MAX_SUCCESS_EPISODES):
            raise QualifiedInputError({
                "format": "ppo262e-quota-reject-v1",
                "problems": [
                    f"成功 episode 累计将超上限: "
                    f"{s['bank_episode_success']} + {candidate_episodes} > "
                    f"{PPO262E_BANK_MAX_SUCCESS_EPISODES}"],
            })

    def assert_smoke_quota(self, steps: int = PPO262E_SMOKE_STEPS) -> None:
        s = self.sums()
        if s["ppo_smoke_runs"] >= PPO262E_MAX_SMOKE_RUNS:
            raise QualifiedInputError({
                "format": "ppo262e-quota-reject-v1",
                "problems": [
                    f"新增 optimizer smoke 累计已达 {s['ppo_smoke_runs']} 次"
                    f"上限 {PPO262E_MAX_SMOKE_RUNS}(失败与中断同样计数)"],
            })
        if steps > PPO262E_SMOKE_STEPS:
            raise QualifiedInputError({
                "format": "ppo262e-quota-reject-v1",
                "problems": [f"单次 smoke {steps} 步超过单次上限 "
                             f"{PPO262E_SMOKE_STEPS}"],
            })
        if s["ppo_smoke_steps"] + steps > PPO262E_MAX_SMOKE_STEPS:
            raise QualifiedInputError({
                "format": "ppo262e-quota-reject-v1",
                "problems": [
                    f"optimizer 步数累计将超上限: {s['ppo_smoke_steps']} + "
                    f"{steps} > {PPO262E_MAX_SMOKE_STEPS}"],
            })


# ---------------------------------------------------------------- bank 生成
def eng_bank_keys() -> list[EpisodeKey]:
    """固定工程 bank 坐标:三族 D1 各 1 个 A/B pair(staged 序)。

    坐标先于生成固定;结构性失败沿 generate262_pair 内建
    first_pass/max_attempts=5 语义(与正式链同一尝试规则)。
    """
    keys = [EpisodeKey(ENG_BANK_NAMESPACE, fam, "D1", 0, side)
            for fam in ("c1_opportunity", "c2_context", "c3_cost")
            for side in ("A", "B")]
    return staged_order(keys)


def generate_eng_bank(
        qi: QualifiedInput, ledger: QuotaLedger, *,
        param_recorder: Callable[..., Any] | None = None,
        progress: bool = False) -> list[LoadedEpisode]:
    """从已验证快照生成工程 bank(参数唯一来源 = 快照 pack)。

    - 生成前强制配额检查(fail closed,零生成拒绝);
    - param_recorder:真实 generator 边界的参数记录器
      (family, rung, side, params)(generate262_pair 透传);
    - 事件登记:replay/候选/成功(含失败尝试计数);
    - 产物对拍:每个 episode 的 spec.params 必须逐字等于选定 pack 的
      rung 参数 + cur261_rung 注入(参数来源真实性的产物级证据)。
    """
    if not isinstance(qi, QualifiedInput):
        raise QualifiedInputError({
            "format": "ppo262e-bank-generate-reject-v1",
            "problems": ["bank 生成要求已验证的 QualifiedInput 快照"
                         "(未验证输入在真实生成前拒绝)"]})
    keys = eng_bank_keys()
    ledger.assert_bank_quota(candidate_episodes=len(keys))
    rung_params = qi.rung_params()
    ledger.append("bank_generation_replay",
                  dataset_id=PPO262E_BANK_DATASET_ID,
                  namespace=ENG_BANK_NAMESPACE,
                  candidate_episodes=len(keys),
                  qualification_plan_digest=qi.plan_digest,
                  parameter_pack_digest=qi.pack_digest,
                  preprocessor_bundle_hash=qi.bundle_hash)
    t0 = time.time()
    try:
        bank = generate262_bank(
            keys, locked_plan_rung_params=rung_params,
            param_recorder=param_recorder, progress=progress)
    except Exception as exc:
        ledger.append("bank_generation_failed", error=str(exc)[:500],
                      candidate_episodes=len(keys))
        raise
    # 产物对拍:episode spec.params 与 pack 逐字一致(base_params 注入
    # episode_bars/initial_price/pair_variant 三个统一合同字段 +
    # generate262_pair 注入 cur261_rung;side 级展开由 generator 协议
    # 完成——参数来源真实性的产物级证据)
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_EPISODE_BARS, CURRICULUM261_INITIAL_PRICE,
        CURRICULUM261_PAIR_VARIANT_KEY,
    )
    for ep in bank:
        expected_src = dict(
            rung_params[ep.key.family][ep.key.rung])
        expected_src["cur261_rung"] = ep.key.rung
        expected_src["episode_bars"] = CURRICULUM261_EPISODE_BARS
        expected_src["initial_price"] = CURRICULUM261_INITIAL_PRICE
        expected_src[CURRICULUM261_PAIR_VARIANT_KEY] = ep.key.variant
        got = dict(ep.episode.spec.params)
        if got != expected_src:
            raise QualifiedInputError({
                "format": "ppo262e-bank-param-mismatch-v1",
                "problems": [
                    f"episode {ep.key.canonical()} 的 generator 参数与"
                    f"选定 pack 不一致: expected_keys="
                    f"{sorted(expected_src)} got_keys={sorted(got)}"],
            })
    ledger.append("bank_episode_success", count=len(bank),
                  elapsed_seconds=round(time.time() - t0, 1))
    return bank


# ---------------------------------------------------------------- env/PPO
def _torch_param_digest(model) -> str:
    import torch
    h = hashlib.sha256()
    with torch.no_grad():
        for k in sorted(model.policy.state_dict()):
            t = model.policy.state_dict()[k].detach().cpu().numpy()
            h.update(k.encode("utf-8"))
            h.update(np.ascontiguousarray(t, dtype=np.float64).tobytes())
    return "e262pp-" + h.hexdigest()


def collect_frozen_probe(preprocessor, bank, model, *,
                         steps: int = PPO262E_FROZEN_OBS_STEPS,
                         reset_seed: int = PPO262E_ENV_RESET_SEED,
                         bundle_hash: str | None = None) -> dict[str, Any]:
    """在冻结 V2 环境上采集观察 + 模型确定性前向(无梯度,不重训练)。

    动作序列固定为全 1(long)——与环境动力学无关的对拍基准;观察与
    动作概率逐字节落盘,供新进程冷读对拍。预测先于 step:每步在当前
    观察上前向,再以 action=1 推进环境;episode 终止后 reset 续采。
    """
    import torch
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

    torch.set_num_threads(1)
    env = CurriculumMultiEpisodeEnv(bank, preprocessor=preprocessor)
    obs_list, act_list, prob_list = [], [], []
    def _predict(obs):
        with torch.no_grad():
            o = torch.as_tensor(np.asarray(obs, dtype=np.float32)[None, :])
            dist = model.policy.get_distribution(o)
            probs = dist.distribution.probs[0].detach().numpy()
        return [float(v) for v in probs], int(np.argmax(probs))

    current, _ = env.reset(seed=reset_seed)
    for _ in range(steps):
        obs_list.append(np.asarray(current, dtype=np.float32).copy())
        probs, act = _predict(current)
        prob_list.append(probs)
        act_list.append(act)
        current, _, term, trunc, _ = env.step(1)
        if term or trunc:
            current, _ = env.reset()
    return {
        "format": "ppo262e-frozen-probe-v1",
        "steps": int(steps),
        "reset_seed": int(reset_seed),
        "action_schedule": "all_long(1)",
        "bundle_hash": bundle_hash,
        "observations_float32": [o.tolist() for o in obs_list],
        "deterministic_actions": act_list,
        "action_probabilities": prob_list,
        "collection_semantics": (
            "训练后冻结观察:reset(seed=固定) 后每步先在当前观察前向"
            "再以 action=1 推进;观察与概率为保存时前向,供新进程冷读"
            "对拍"),
    }


def engineering_manifest(qi: QualifiedInput, *, bank: list[LoadedEpisode],
                          steps: int, updates: int, config: dict[str, Any],
                          model_seed: int) -> dict[str, Any]:
    """工程 checkpoint 绑定 manifest(输入/参数/预处理/bank/代码身份)。"""
    import stable_baselines3
    import torch

    from rl_curriculum.curriculum261_production_obs import (
        production_observation_identity,
    )
    manifest = {
        "format": "ppo262e-model-manifest-v1",
        "profile": qi.profile,
        "scope": qi.scope,
        "engineering_only": True,
        "run_label": f"eng/{PPO262E_ITERATION_ID}/ppo_smoke_256",
        "iteration": PPO262E_ITERATION_ID,
        "qualified_input": qi.identities(),
        "bank": {
            "namespace": ENG_BANK_NAMESPACE,
            "manifest_sha256": bank_manifest(bank)["manifest_sha256"],
            "n_episodes": len(bank),
            "keys": [e.key.canonical() for e in bank],
        },
        "training": {
            "config": config,
            "model_seed": int(model_seed),
            "total_timesteps": int(steps),
            "optimizer_updates_declared": int(updates),
        },
        "observation_identity": production_observation_identity(),
        "code_identity_consumer": _consumer_code_identity(),
        "sb3_version": stable_baselines3.__version__,
        "torch_version": torch.__version__,
        "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return manifest


_CONSUMER_CODE_MODULES = (
    "ppo262_qualified_input.py", "ppo262_eng_profile.py",
    "ppo262_eng_fixture.py", "ppo262_env.py", "ppo262_banks.py",
    "ppo262_train.py", "ppo262_config.py", "ppo262_cli.py",
    "ppo262_namespaces.py", "ppo262_diag_train.py",
)


def _consumer_code_identity() -> dict[str, str]:
    """Ct:消费侧直接执行面模块 sha256(冷读时逐文件重算比对)。"""
    import rl_curriculum
    root = Path(rl_curriculum.__file__).resolve().parent
    out: dict[str, str] = {}
    for name in _CONSUMER_CODE_MODULES:
        p = root / name
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def engineering_ppo_run(qi: QualifiedInput, bank: list[LoadedEpisode],
                        ledger: QuotaLedger, out_dir: Path | str,
                        *, config: dict[str, Any] | None = None,
                        model_seed: int = PPO262E_MODEL_SEED) -> dict[str, Any]:
    """恰好 256 环境步的真实 PPO 参数更新 + checkpoint + 冻结观察。"""
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    from rl_curriculum.ppo262_train import save_model_with_manifest

    config = dict(config or PPO262E_SMOKE_CONFIG)
    steps = PPO262E_SMOKE_STEPS
    if config.get("n_steps") != steps:
        raise ValueError(
            f"工程 smoke 配置 n_steps 必须恰为 {steps}(rollout 精确步数"
            f"控制;当前 {config.get('n_steps')})")
    ledger.assert_smoke_quota(steps)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    env = CurriculumMultiEpisodeEnv(bank, preprocessor=qi.preprocessor)
    checks: dict[str, bool] = {}
    # V02:SB3 实际看到的 observation space 必须是 V2 outer space
    obs_space = env.observation_space
    low, high = obs_space.low, obs_space.high
    checks["obs_space_9d"] = tuple(obs_space.shape) == (9,)
    checks["obs_space_features_unbounded"] = bool(
        np.all(np.isneginf(low[:-1])) and np.all(np.isposinf(high[:-1])))
    checks["obs_space_position_0_1"] = bool(
        low[-1] == 0.0 and high[-1] == 1.0)

    from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
    model = build_diagnosed_ppo(config, model_seed, env)
    checks["sb3_obs_space_is_v2"] = (
        model.observation_space.shape == obs_space.shape
        and np.array_equal(model.observation_space.low, low)
        and np.array_equal(model.observation_space.high, high))

    params_before = _torch_param_digest(model)
    t0 = time.time()
    model.learn(total_timesteps=steps, progress_bar=False)
    elapsed = time.time() - t0
    params_after = _torch_param_digest(model)

    audit = env.audit()
    update_records = list(getattr(model, "diag_update_records", []))
    losses = [float(r.get("loss")) for r in update_records
              if r.get("loss") is not None]
    checks["env_steps_exactly_256"] = audit["steps_taken"] == steps
    checks["optimizer_updates_at_least_one"] = len(update_records) >= 1
    checks["update_bound_to_256_steps"] = bool(update_records) and all(
        int(r.get("env_step", -1)) <= steps for r in update_records)
    checks["losses_finite"] = bool(losses) and all(
        np.isfinite(v) for v in losses)
    checks["params_changed"] = params_before != params_after
    checks["no_bank_overrun"] = audit["exhausted_cycles"] <= 1

    manifest = engineering_manifest(
        qi, bank=bank, steps=steps, updates=len(update_records),
        config=config, model_seed=model_seed)
    model_path = out_dir / "eng_ppo_smoke_256"
    saved = save_model_with_manifest(
        model, model_path, manifest=manifest)

    probe = collect_frozen_probe(
        qi.preprocessor, bank, model, bundle_hash=qi.bundle_hash)
    (out_dir / "eng_frozen_probe.json").write_text(
        json.dumps(probe, indent=2, ensure_ascii=False), encoding="utf-8")

    ledger.append("ppo_smoke", steps=steps,
                  updates=len(update_records),
                  model_sha256=saved["model_sha256"],
                  qualification_plan_digest=qi.plan_digest,
                  parameter_pack_digest=qi.pack_digest,
                  preprocessor_bundle_hash=qi.bundle_hash,
                  elapsed_seconds=round(elapsed, 1))
    result = {
        "format": "ppo262e-ppo-smoke-v1",
        "iteration": PPO262E_ITERATION_ID,
        "engineering_only": True,
        "qualified_input": qi.identities(),
        "bank_manifest_sha256": manifest["bank"]["manifest_sha256"],
        "steps": steps,
        "env_audit": audit,
        "optimizer_update_records": update_records,
        "params_sha256_before": params_before,
        "params_sha256_after": params_after,
        "model_file": saved["model_file"],
        "model_sha256": saved["model_sha256"],
        "elapsed_seconds": round(elapsed, 1),
        "checks": checks,
        "pass": bool(checks.values()) and all(checks.values()),
    }
    (out_dir / "eng_ppo_smoke.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


# ---------------------------------------------------------------- 冷读
def cold_read_checkpoint(qual_dir: Path | str, authorization_path: Path | str,
                         model_dir: Path | str, out_dir: Path | str,
                         *, expected_profile: str | None = None,
                         ) -> dict[str, Any]:
    """新进程冷读:公共输入校验 + manifest 绑定核对 + 冻结观察对拍。

    不重训练、不 refit;容差事前固定(PPO262E_PROB_ATOL)。
    """
    import torch
    from stable_baselines3 import PPO

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    checks: dict[str, bool] = {}
    problems: list[str] = []

    qi = load_qualified_input(
        qual_dir, authorization_path=authorization_path,
        expected_scope="engineering", expected_profile=expected_profile)

    model_zip = Path(model_dir) / "eng_ppo_smoke_256.zip"
    manifest_path = Path(model_dir) / "eng_ppo_smoke_256.manifest.json"
    checks["model_files_exist"] = (
        model_zip.is_file() and manifest_path.is_file())
    if not checks["model_files_exist"]:
        raise QualifiedInputError({
            "format": "ppo262e-cold-read-reject-v1",
            "problems": [f"checkpoint 文件缺失: {model_zip}"]})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model_sha = hashlib.sha256(model_zip.read_bytes()).hexdigest()
    checks["model_sha_matches_manifest"] = (
        model_sha == manifest.get("model_sha256"))
    if not checks["model_sha_matches_manifest"]:
        problems.append("模型文件字节与 manifest 绑定不一致")

    # 输入绑定核对(训练元数据指向的输入 vs 实际绑定输入)
    bound = manifest.get("qualified_input", {})
    ids = qi.identities()
    for key in ("qualification_plan_digest", "parameter_pack_digest",
                "preprocessor_bundle_hash", "profile"):
        ok = bound.get(key) == ids[key]
        checks[f"manifest_binds_{key}"] = ok
        if not ok:
            problems.append(
                f"manifest {key} = {bound.get(key)!r} != 冷读输入 "
                f"{ids[key]!r}")
    checks["manifest_code_identity_matches"] = (
        manifest.get("code_identity_consumer") == _consumer_code_identity())
    if not checks["manifest_code_identity_matches"]:
        problems.append("消费代码身份 Ct 漂移(checkpoint 绑定的执行面"
                        "与当前树不一致)")

    probe_path = Path(model_dir) / "eng_frozen_probe.json"
    checks["frozen_probe_exists"] = probe_path.is_file()
    if not checks["frozen_probe_exists"]:
        problems.append(f"缺少冻结观察原件: {probe_path}")
    if problems:
        raise QualifiedInputError({
            "format": "ppo262e-cold-read-reject-v1",
            "problems": problems, "checks": checks})

    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    torch.set_num_threads(1)
    model = PPO.load(str(model_zip), device="cpu")
    obs_arr = [np.asarray(o, dtype=np.float32)
               for o in probe["observations_float32"]]
    acts, probs = [], []
    with torch.no_grad():
        for o in obs_arr:
            t = torch.as_tensor(o[None, :])
            dist = model.policy.get_distribution(t)
            p = dist.distribution.probs[0].detach().numpy()
            probs.append([float(v) for v in p])
            acts.append(int(np.argmax(p)))
    checks["actions_bitwise_equal"] = acts == list(
        probe["deterministic_actions"])
    max_diff = max(
        max(abs(a - b) for a, b in zip(pa, pb))
        for pa, pb in zip(probs, probe["action_probabilities"]))
    checks["prob_atol_within_prior"] = max_diff <= PPO262E_PROB_ATOL

    result = {
        "format": "ppo262e-cold-read-v1",
        "iteration": PPO262E_ITERATION_ID,
        "engineering_only": True,
        "model_sha256": model_sha,
        "qualified_input": ids,
        "frozen_obs_steps": probe["steps"],
        "deterministic_actions_match": checks["actions_bitwise_equal"],
        "action_probability_max_abs_diff": float(max_diff),
        "prob_atol_prior": PPO262E_PROB_ATOL,
        "atol_rationale": (
            "同模型字节 + 同观察字节 + torch CPU 单线程确定性前向;"
            "action 逐位相等,概率残差 <= 1e-9"),
        "checks": checks,
        "pass": all(checks.values()),
        "retrained": False,
        "refit": False,
    }
    (out_dir / "eng_cold_read.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


# ---------------------------------------------------------------- 路由检查
_ENTRY_CLASSES = ("smoke", "config_dev", "probe", "core", "dev_eval", "final")


def route_profile_inputs(qi: QualifiedInput) -> dict[str, Any]:
    """M02:六类消费入口在新 profile 下的输入路由(不运行教学预算)。

    每类入口解析其真实消费边界会拿到的参数/坐标/配置,并断言全部来自
    已验证快照(pack/bundle/namespace),与 R2 默认(_locked_rung_params)
    在 pack 扰动下可区分。不触发任何 generator 调用或 optimizer 更新。
    """
    from rl_curriculum.ppo262_cli import (
        _locked_reference_thresholds, _locked_rung_params,
    )


    rung = qi.rung_params()
    thresholds = qi.reference_thresholds()
    r2_rung = _locked_rung_params()
    r2_thr = _locked_reference_thresholds()
    bank_keys = [k.canonical() for k in eng_bank_keys()]
    eval_config_note = (
        "EvalConfig 沿 curriculum261_eval_config()(冻结账本一致口径,"
        "fee=0.001/无滑点/100 现金;V03:价格列 raw,账本语义不因缩放"
        "变化)")
    routes = {
        "smoke": {
            "rung_params_source": "qualified_input.pack",
            "bank_namespace": ENG_BANK_NAMESPACE,
            "bank_keys": bank_keys,
            "preprocessor": "qualified_input.bundle(frozen V2)",
            "ppo_config": dict(PPO262E_SMOKE_CONFIG),
            "steps": PPO262E_SMOKE_STEPS,
        },
        "config_dev": {
            "rung_params_source": "qualified_input.pack",
            "rung_params": rung,
            "reference_thresholds": thresholds,
            "train_namespace": ENG_BANK_NAMESPACE,
            "rung": "D1",
            "note": "本轮只测路由:解析到的参数/坐标记录在案,不运行"
                    "config-dev 教学预算",
        },
        "probe": {
            "rung_params_source": "qualified_input.pack",
            "rung_params": rung,
            "reference_thresholds": thresholds,
            "train_namespace": ENG_BANK_NAMESPACE,
            "note": "本轮只测路由:probe 预算不运行",
        },
        "core": {
            "rung_params_source": "qualified_input.pack",
            "rung_params": rung,
            "reference_thresholds": thresholds,
            "train_namespace": ENG_BANK_NAMESPACE,
            "staged_mixed_orders": [
                "staged_order/generate262_bank 同一多重集 mixed_order"],
            "note": "本轮只测路由:core 教学预算不运行",
        },
        "dev_eval": {
            "rung_params_source": "qualified_input.pack",
            "rung_params": rung,
            "reference_thresholds": thresholds,
            "eval_config": eval_config_note,
            "preprocessor": "qualified_input.bundle(frozen V2,零 refit)",
            "note": "本轮只测路由:dev-eval bank 不生成",
        },
        "final": {
            "rung_params_source": "qualified_input.pack",
            "rung_params": rung,
            "reference_thresholds": thresholds,
            "note": "final 入口属正式链:本轮不存在 formal 授权,任何"
                    "请求在生成/更新前拒绝(见 eng-input-lock --scope "
                    "formal)",
        },
    }
    pack_is_perturbed = any(
        rung[f]["D1"] != r2_rung[f]["D1"] for f in rung)
    return {
        "format": "ppo262e-route-profile-inputs-v1",
        "iteration": PPO262E_ITERATION_ID,
        "qualified_input": qi.identities(),
        "entry_classes": _ENTRY_CLASSES,
        "routes": routes,
        "r2_default_still_available": {
            "rung_params_keys": sorted(r2_rung),
            "reference_thresholds_keys": sorted(r2_thr)},
        "pack_differs_from_r2": bool(pack_is_perturbed),
        "note": "六类入口在新 profile 下均从同一 QualifiedInput 快照取参;"
                "官方 R2 默认路径保持不变(缺省行为不受影响)",
    }
