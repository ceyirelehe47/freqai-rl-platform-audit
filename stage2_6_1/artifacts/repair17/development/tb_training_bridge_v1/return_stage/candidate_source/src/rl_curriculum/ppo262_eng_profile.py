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
        """累计查询(B4:失败/中断保守计数)。

        - ppo_smoke 计数 = 已确认(ppo_smoke)+ 已失败(ppo_smoke_failed)
          + **未终结预约**(ppo_smoke_reserved 无同 run_id 终结事件——
          进程被杀时预约残留,按保守口径全额计入,不当作零消费释放);
        - 步数 = 确认事件 steps + 失败事件 max(steps_actual, 预约 steps)
          + 未终结预约 steps;
        - bank 候选 = replay 事件计划数 + 终结事件实际 attempt 数超出
          计划的差额(重试实计,不低估)。
        """
        out = {"bank_replays": 0, "bank_episode_success": 0,
               "bank_episode_candidate": 0, "bank_pair_attempts": 0,
               "ppo_smoke_runs": 0, "ppo_smoke_steps": 0}
        resolved: set[str] = set()
        reserved_open: dict[str, int] = {}
        planned_candidates = 0
        for r in self.records():
            ev = r["event"]
            if ev == "bank_generation_replay":
                out["bank_replays"] += 1
                planned_candidates = int(r.get("candidate_episodes", 0))
                out["bank_episode_candidate"] += planned_candidates
            elif ev in ("bank_episode_success", "bank_generation_failed"):
                actual_attempts = int(r.get("pair_attempts", 0))
                out["bank_pair_attempts"] += actual_attempts
                if ev == "bank_episode_success":
                    out["bank_episode_success"] += int(r.get("count", 1))
                over = max(0, actual_attempts * 2 - planned_candidates)
                out["bank_episode_candidate"] += over
                planned_candidates = 0
            elif ev == "ppo_smoke_reserved":
                reserved_open[str(r.get("run_id"))] = int(
                    r.get("steps", 0))
            elif ev == "ppo_smoke":
                rid = str(r.get("run_id", ""))
                resolved.add(rid)
                reserved_open.pop(rid, None)
                out["ppo_smoke_runs"] += 1
                out["ppo_smoke_steps"] += int(r.get("steps", 0))
            elif ev == "ppo_smoke_failed":
                rid = str(r.get("run_id", ""))
                resolved.add(rid)
                reserved = reserved_open.pop(rid, 0)
                actual = int(r.get("steps_actual", 0))
                out["ppo_smoke_runs"] += 1
                out["ppo_smoke_steps"] += max(actual, reserved)
        for rid, steps in reserved_open.items():
            if rid not in resolved:
                out["ppo_smoke_runs"] += 1
                out["ppo_smoke_steps"] += steps
        return out

    def reserve_smoke(self, run_id: str,
                      steps: int = PPO262E_SMOKE_STEPS) -> dict[str, Any]:
        """B4:learn 前预约(可核验运行身份;中断时保守保留)。"""
        return self.append("ppo_smoke_reserved", run_id=run_id,
                           steps=steps)

    def fail_smoke(self, run_id: str, steps_actual: int,
                   error: str) -> dict[str, Any]:
        """B4:失败终结(实际步数已知则记实际,否则预约全额保守)。"""
        return self.append("ppo_smoke_failed", run_id=run_id,
                           steps_actual=int(steps_actual),
                           error=error[:300])

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
    # B2.2:消费边界完整性重验(缓存污染在真实生成前拒绝)
    qi.verify_integrity()
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
    # B4:attempt 实计——包装派生入口统计真实尝试次数(结构性重试
    # 每次派生都计数;零行为改变,仅观察)
    from rl_curriculum.ppo262_namespaces import derive262_seed
    attempts = {"n": 0}

    def _counting_derive(namespace, family, rung, pair_index, attempt):
        attempts["n"] += 1
        return derive262_seed(namespace, family, rung, pair_index, attempt)

    try:
        bank = generate262_bank(
            keys, locked_plan_rung_params=rung_params,
            derive_seed_fn=_counting_derive,
            param_recorder=param_recorder, progress=progress)
    except Exception as exc:
        ledger.append("bank_generation_failed", error=str(exc)[:500],
                      candidate_episodes=len(keys),
                      pair_attempts=attempts["n"])
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
                  pair_attempts=attempts["n"],
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
    "ppo262_eng_fixture.py", "ppo262_entry_specs.py", "ppo262_env.py",
    "ppo262_banks.py", "ppo262_train.py", "ppo262_config.py",
    "ppo262_cli.py", "ppo262_smoke.py",
    "ppo262_namespaces.py", "ppo262_diag_train.py",
    # P2 闭合(REVIEWER_CONTENT_REPORT_V2):generator/env 行为级身份进
    # 消费代码哈希面——共同语义版本标签不再单独承担行为漂移检测
    "curriculum261_pairs.py",
    "curriculum261_c1.py", "curriculum261_c2.py", "curriculum261_c3.py",
    "curriculum261_production_obs.py",
    "../rl_platform/env.py",
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


def _verify_identity_at_commit(recorded: dict[str, str],
                               candidate_commit: str) -> bool:
    """记录的模块哈希逐一对该候选 commit 的 git blob 复算(CR 规范化)。

    迁移路径语义:checkpoint 由候选 X 的执行面产出;当前树已前进时,
    只要记录哈希与 X 的归档 blob 一致,绑定仍有效(执行面 = 已归档
    候选),不要求等于当前树、也不把旧 manifest 重签成新运行。
    """
    import os
    import subprocess
    import rl_curriculum
    repo_candidates = []
    env_repo = os.environ.get("PPO262E_REPO_ROOT")
    if env_repo:
        repo_candidates.append(Path(env_repo))
    repo_candidates.append(
        Path(rl_curriculum.__file__).resolve().parents[2])
    repo_candidates.append(Path("/mnt/f/trading/freqai-rl-audit"))
    repo = next((r for r in repo_candidates if (r / ".git").exists()), None)
    if repo is None:
        return False
    for name, expected in (recorded or {}).items():
        # 记录键决定候选树根:262 消费模块/261 共享模块/相对路径 env core
        roots = ["stage2_6_2/src/rl_curriculum",
                 "stage2_6_1/src/rl_curriculum", "src/rl_curriculum"]
        rels = [f"{r}/{name}" for r in roots]
        if name.startswith("../"):
            rels = ["stage2_6_2/src/rl_platform/env.py",
                    "stage2_6_1/src/rl_platform/env.py",
                    "src/rl_platform/env.py",
                    "stage2_5_2/src/rl_platform/env.py"]
        blob = None
        for rel in rels:
            try:
                blob = subprocess.run(
                    ["git", "-C", str(repo), "show",
                     f"{candidate_commit}:{rel}"],
                    capture_output=True, check=True).stdout
                break
            except subprocess.CalledProcessError:
                continue
        if blob is None:
            return False
        got = hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()
        if got != expected:
            return False
    return True

def engineering_ppo_run(qi: QualifiedInput, bank: list[LoadedEpisode],
                        ledger: QuotaLedger, out_dir: Path | str,
                        *, config: dict[str, Any] | None = None,
                        model_seed: int = PPO262E_MODEL_SEED) -> dict[str, Any]:
    """恰好 256 环境步的真实 PPO 参数更新 + checkpoint + 冻结观察。"""
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    from rl_curriculum.ppo262_train import save_model_with_manifest

    qi.verify_integrity()  # B2.2:消费边界完整性重验
    config = dict(config or PPO262E_SMOKE_CONFIG)
    steps = PPO262E_SMOKE_STEPS
    if config.get("n_steps") != steps:
        raise ValueError(
            f"工程 smoke 配置 n_steps 必须恰为 {steps}(rollout 精确步数"
            f"控制;当前 {config.get('n_steps')})")
    ledger.assert_smoke_quota(steps)
    # B4:learn 前预约(失败/中断保守计数;进程被杀时预约残留按全额)
    import uuid
    run_id = f"ppo262e_{uuid.uuid4().hex[:16]}"
    ledger.reserve_smoke(run_id, steps)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    env = CurriculumMultiEpisodeEnv(bank, preprocessor=qi.preprocessor)
    checks: dict[str, bool] = {}
    try:
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
        # B3:冻结观察与保存时身份绑定(模型字节摘要+bundle+步数/种子)
        probe["binding_digest"] = "e262pb-" + hashlib.sha256(
            json.dumps([saved["model_sha256"], qi.bundle_hash,
                        probe["steps"], probe["reset_seed"]],
                       sort_keys=True, separators=(",", ":")).encode(
                "utf-8")).hexdigest()
        (out_dir / "eng_frozen_probe.json").write_text(
            json.dumps(probe, indent=2, ensure_ascii=False),
            encoding="utf-8")

        ledger.append("ppo_smoke", run_id=run_id, steps=steps,
                      updates=len(update_records),
                      model_sha256=saved["model_sha256"],
                      qualification_plan_digest=qi.plan_digest,
                      parameter_pack_digest=qi.pack_digest,
                      preprocessor_bundle_hash=qi.bundle_hash,
                      elapsed_seconds=round(elapsed, 1))
    except BaseException as exc:
        try:
            steps_actual = int(env.audit()["steps_taken"])
        except Exception:
            steps_actual = steps
        ledger.fail_smoke(run_id, steps_actual, repr(exc))
        raise
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
    v2_path = Path(model_dir) / "eng_ppo_smoke_256.manifest.v2.json"
    if v2_path.is_file():
        manifest_path = v2_path  # 显式已核验迁移件(v1 原件不改写)
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
                "preprocessor_bundle_hash", "profile",
                "qualification_source_iteration"):
        ok = bound.get(key) == ids[key]
        checks[f"manifest_binds_{key}"] = ok
        if not ok:
            problems.append(
                f"manifest {key} = {bound.get(key)!r} != 冷读输入 "
                f"{ids[key]!r}")

    # B3:authorization 绑定摘要必须存在且与冷读输入重算一致
    # (反例 cold_missing_authorization_binding)
    from rl_curriculum.ppo262_qualified_input import (
        authorization_binding_digest as _abd,
    )
    expected_binding = _abd({
        **(qi.authorization.get("bindings", {})),
        "profile": qi.authorization.get("profile"),
        "scope": qi.authorization.get("scope")})
    checks["manifest_binds_authorization_digest"] = bool(
        bound.get("authorization_binding_digest")) and (
        bound.get("authorization_binding_digest") == expected_binding)
    if not checks["manifest_binds_authorization_digest"]:
        problems.append(
            "manifest 缺失或错配 authorization_binding_digest(授权绑定"
            "未经冷读核验)")

    # B3:共同执行语义现场重算(不能只信 manifest 记录)
    from rl_curriculum.ppo262_qualified_input import (
        consumer_common_contract_now as _ccc,
    )
    checks["manifest_common_contract_live_match"] = (
        bound.get("consumer_common_contract") == {
            k: qi.contract_now[k] for k in (
                "production_observation_identity", "family_versions",
                "preprocessing_v2_contract_digest")})
    if not checks["manifest_common_contract_live_match"]:
        problems.append("manifest consumer_common_contract 与现场重算"
                        "不一致")

    # 代码身份:优先当前树;否则允许**显式迁移 manifest** 携带的
    # candidate_commit(记录哈希逐模块对 git blob 复算——checkpoint
    # 绑定的执行面 = 已归档候选;不把旧 manifest 重签成新运行)
    recorded_identity = manifest.get("code_identity_consumer") or {}
    current_identity = _consumer_code_identity()
    if recorded_identity == current_identity:
        checks["manifest_code_identity_matches"] = True
    elif manifest.get("candidate_commit"):
        checks["manifest_code_identity_matches"] = _verify_identity_at_commit(
            recorded_identity, manifest["candidate_commit"])
        if checks["manifest_code_identity_matches"]:
            checks["manifest_code_identity_via_candidate"] = True
    else:
        checks["manifest_code_identity_matches"] = False
    if not checks["manifest_code_identity_matches"]:
        problems.append("消费代码身份 Ct 漂移(checkpoint 绑定的执行面"
                        "与当前树/已归档候选均不一致)")

    # B3:bank/训练预算绑定(跨文件原件交叉核验;反例 cold_wrong_bank_
    # and_seed——manifest 篡改 bank/seed/steps 后不能仅凭模型 SHA 继续)
    bank_orig_path = Path(model_dir) / "eng_bank_smoke.json"
    smoke_orig_path = Path(model_dir) / "eng_ppo_smoke.json"
    checks["run_originals_exist"] = (
        bank_orig_path.is_file() and smoke_orig_path.is_file())
    if not checks["run_originals_exist"]:
        problems.append(
            f"缺少运行原件(bank/smoke): {bank_orig_path.name}, "
            f"{smoke_orig_path.name}")
    else:
        bank_orig = json.loads(bank_orig_path.read_text(encoding="utf-8"))
        smoke_orig = json.loads(smoke_orig_path.read_text(
            encoding="utf-8"))
        mb = manifest.get("bank", {})
        episodes = bank_orig.get("episodes", [])

        def _as_key_str(e):
            if isinstance(e, dict):
                return (f"{e['namespace']}|{e['family']}|{e['rung']}|"
                        f"{e['pair_index']}|{e['variant']}")
            return str(e)

        episodes_as_keys = [_as_key_str(e) for e in episodes]
        checks["manifest_bank_matches_original"] = (
            mb.get("namespace") == ENG_BANK_NAMESPACE
            and mb.get("n_episodes") == len(episodes)
            and mb.get("keys") == episodes_as_keys
            and mb.get("manifest_sha256") == bank_orig.get(
                "bank_manifest", {}).get("manifest_sha256")
            and mb.get("manifest_sha256") == smoke_orig.get(
                "bank_manifest_sha256"))
        if not checks["manifest_bank_matches_original"]:
            problems.append("manifest bank 绑定与运行原件不一致"
                            "(namespace/keys/数量/manifest hash)")
        mt = manifest.get("training", {})
        checks["manifest_training_matches_original"] = (
            mt.get("total_timesteps") == smoke_orig.get("steps")
            == PPO262E_SMOKE_STEPS
            and mt.get("model_seed") == PPO262E_MODEL_SEED
            and mt.get("optimizer_updates_declared") == len(
                smoke_orig.get("optimizer_update_records", []))
            and manifest.get("model_sha256") == smoke_orig.get(
                "model_sha256"))
        if not checks["manifest_training_matches_original"]:
            problems.append(
                "manifest 训练绑定与运行原件/事前固定 profile 预算不一致"
                f"(steps 必须 = {PPO262E_SMOKE_STEPS},seed 必须 = "
                f"{PPO262E_MODEL_SEED})")

    probe_path = Path(model_dir) / "eng_frozen_probe.json"
    checks["frozen_probe_exists"] = probe_path.is_file()
    if not checks["frozen_probe_exists"]:
        problems.append(f"缺少冻结观察原件: {probe_path}")
    if problems:
        raise QualifiedInputError({
            "format": "ppo262e-cold-read-reject-v1",
            "problems": problems, "checks": checks})

    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    # B3:冻结观察原件与保存时身份绑定(bundle + 事前固定步数/种子;
    # v2 保存路径另写 binding_digest,旧件按既有字段核验并显式声明)
    checks["probe_bundle_bound"] = (
        probe.get("bundle_hash") == bound.get(
            "preprocessor_bundle_hash"))
    checks["probe_steps_fixed"] = (
        probe.get("steps") == PPO262E_FROZEN_OBS_STEPS)
    if not checks["probe_bundle_bound"]:
        problems.append("冻结观察的 bundle hash 与 manifest 绑定不一致")
    if not checks["probe_steps_fixed"]:
        problems.append(
            f"冻结观察步数 {probe.get('steps')!r} != 事前固定 "
            f"{PPO262E_FROZEN_OBS_STEPS}")
    if "binding_digest" in probe:
        expected_probe_binding = "e262pb-" + hashlib.sha256(
            json.dumps([model_sha, probe.get("bundle_hash"),
                        probe.get("steps"), probe.get("reset_seed")],
                       sort_keys=True, separators=(",", ":")).encode(
                "utf-8")).hexdigest()
        checks["probe_binding_digest_valid"] = (
            probe["binding_digest"] == expected_probe_binding)
        if not checks["probe_binding_digest_valid"]:
            problems.append("冻结观察 binding_digest 复算不一致")
    if problems:
        raise QualifiedInputError({
            "format": "ppo262e-cold-read-reject-v1",
            "problems": problems, "checks": checks})
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
_ENTRY_CLASSES = ("smoke", "config_dev", "probe", "core", "dev_eval",
                   "final")


class _ConsumerSentinel(Exception):
    def __init__(self, entry, captured):
        self.entry, self.captured = entry, captured
        super().__init__(f"consumer boundary reached: {entry}")


def _sentinel_generate_bank(entry, captured):
    def _gen(keys, *, locked_plan_rung_params, progress=False, **kw):
        captured.append({
            "boundary": "generate262_bank",
            "keys": [k.canonical() for k in keys],
            "rung_params": json.loads(json.dumps(locked_plan_rung_params)),
        })
        raise _ConsumerSentinel(entry, captured)
    return _gen


def _sentinel_build_policy_set(entry, captured):
    def _build(family, rung_params, thresholds, **kw):
        captured.append({
            "boundary": "build_261_policy_set",
            "family": family,
            "rung_params": json.loads(json.dumps(rung_params)),
            "thresholds": json.loads(json.dumps(thresholds)),
        })
        raise _ConsumerSentinel(entry, captured)
    return _build


def route_profile_inputs(qi: QualifiedInput) -> dict[str, Any]:
    """M02/B1:六类消费入口在新 profile 下的**真实路由**检查。

    ChatGPT 终审 B1 修复标准:检查必须驱动真实消费入口的实现
    (ppo262_entry_specs.prepare_*——官方 cmd_* 实际调用的共享管线),
    在真实 generator/评估消费边界注入哨兵(零生成/零训练),断言:

    1. profile 上下文激活时,六个 prepare_* 返回的参数/阈值/坐标来自
       已验证 pack(namespace = ppo_eng_bank_262e),且真实消费边界
       (spec.build_bank / spec.build_reference)收到的就是这些值;
    2. 上下文未激活时同一 prepare_* 返回官方 R2 参数与官方 namespace
       (旧默认行为不变);
    3. 缓存被污染(pack 字段改写)后,prepare_* 在消费前拒绝
       (verify_integrity)。
    """
    from rl_curriculum.ppo262_entry_specs import (
        ENTRY_PREPARERS, PROFILE_BANK_NAMESPACE, prepare_config_dev_inputs,
        prepare_core_inputs, prepare_dev_eval_inputs, prepare_final_inputs,
        prepare_probe_inputs, prepare_smoke_inputs,
    )
    from rl_curriculum.ppo262_qualified_input import (
        activated_profile_input,
    )

    probes = {
        "smoke": lambda: prepare_smoke_inputs(),
        "config_dev": lambda: prepare_config_dev_inputs(),
        "probe": lambda: prepare_probe_inputs(
            "c1_opportunity", config_name="route_check_probe",
            config={"n_steps": 574}),
        "core": lambda: prepare_core_inputs(1, "staged"),
        "dev_eval": lambda: prepare_dev_eval_inputs(),
        "final": lambda: prepare_final_inputs(),
    }
    routes: dict[str, Any] = {}
    consumer_hits: dict[str, list] = {}

    with activated_profile_input(qi):
        for entry, prep in probes.items():
            spec = prep()
            spec.assert_from_profile(qi)  # 参数/阈值/namespace 同源断言
            captured: list = []
            consumer_hits[entry] = captured
            try:
                spec.build_bank(
                    generate_bank=_sentinel_generate_bank(entry, captured))
            except _ConsumerSentinel:
                pass
            # 评估边界哨兵(thresholds 流向)
            try:
                spec.build_reference(
                    "c1_opportunity", "D1",
                    build=_sentinel_build_policy_set(entry, captured))
            except _ConsumerSentinel:
                pass
            gen_hits = [c for c in captured
                        if c["boundary"] == "generate262_bank"]
            ref_hits = [c for c in captured
                        if c["boundary"] == "build_261_policy_set"]
            if not gen_hits:
                raise QualifiedInputError({
                    "format": "ppo262e-route-reject-v1",
                    "problems": [
                        f"{entry}: 真实 generator 消费边界未被触达"
                        f"(路由检查失效)"],
                })
            if gen_hits[0]["rung_params"] != qi.rung_params():
                raise QualifiedInputError({
                    "format": "ppo262e-route-reject-v1",
                    "problems": [
                        f"{entry}: generator 消费边界收到的 rung_params "
                        f"与已验证 pack 不一致(真实路由断裂)"],
                })
            if ref_hits and ref_hits[0]["thresholds"] != (
                    qi.reference_thresholds()["c1_opportunity"]):
                raise QualifiedInputError({
                    "format": "ppo262e-route-reject-v1",
                    "problems": [
                        f"{entry}: 评估消费边界收到的 thresholds 与 pack "
                        f"不一致(真实路由断裂)"],
                })
            routes[entry] = {
                "rung_params_source": "qualified_input.pack(共享 prepare "
                                      "管线实测)",
                "namespace": spec.namespace,
                "n_bank_keys": len(spec.bank_keys),
                "consumer_boundary_hits": {
                    "generate262_bank": len(gen_hits),
                    "build_261_policy_set": len(ref_hits)},
            }

    # 上下文未激活:官方默认路径(R2 参数 + 官方 namespace)不变
    default_specs = {e: p() for e, p in probes.items()}
    r2_ok = all(
        s.namespace != PROFILE_BANK_NAMESPACE
        for s in default_specs.values())
    from rl_curriculum.ppo262_cli import (
        _locked_reference_thresholds, _locked_rung_params,
    )
    r2_rung = _locked_rung_params()
    default_matches_r2 = all(
        default_specs[e].rung_params == r2_rung for e in default_specs)

    # 缓存污染负对照:污染 pack 字段后 prepare 必须拒绝
    tampered = False
    saved = qi._pack["families"]["c1_opportunity"]["rung_params"]["D1"][
        "opp_drift_bps"]
    try:
        qi._pack["families"]["c1_opportunity"]["rung_params"]["D1"][
            "opp_drift_bps"] = 999.0
        with activated_profile_input(qi):
            try:
                prepare_smoke_inputs()
            except QualifiedInputError:
                tampered = True
    finally:
        qi._pack["families"]["c1_opportunity"]["rung_params"]["D1"][
            "opp_drift_bps"] = saved

    return {
        "format": "ppo262e-route-profile-inputs-v2",
        "iteration": PPO262E_ITERATION_ID,
        "qualified_input": qi.identities(),
        "entry_classes": _ENTRY_CLASSES,
        "routes": routes,
        "consumer_sentinels": "真实 prepare 管线 + generate262_bank/"
                              "build_261_policy_set 边界哨兵(零生成零"
                              "训练)",
        "default_context_official_r2": bool(r2_ok and default_matches_r2),
        "cached_pack_tamper_rejected": tampered,
        "pack_differs_from_r2": any(
            qi.rung_params()[f]["D1"] != r2_rung[f]["D1"]
            for f in qi.rung_params()),
        "pass": bool(r2_ok and default_matches_r2 and tampered
                     and all(r["consumer_boundary_hits"][
                         "generate262_bank"] >= 1
                         for r in routes.values())),
    }
