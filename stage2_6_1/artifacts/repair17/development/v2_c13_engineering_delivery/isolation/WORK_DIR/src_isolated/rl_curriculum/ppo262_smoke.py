"""阶段 2.6.2:PPO smoke(ppo_smoke_262;不参与任何指标/选择)。

只验证(§26):
- multi-episode env 的 reset/step/episode 切换;
- observation shape(9 维 float32)/ reward 有限 / action space;
- SB3 PPO 集成 + model save/load 后 deterministic eval 一致;
- manifest 消耗顺序确定、耗尽行为(exhausted)受控;
- 无状态泄漏(episode 边界 equity/position 完整清空);
- 固定 model seed + 固定 manifest 的短 run 可复现(actions 一致)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_TIMEFRAME,
)
from rl_curriculum.ppo262_banks import (
    EpisodeKey, generate262_bank,
)
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_train import build_ppo


def _locked_rung_params() -> dict[str, Any]:
    from rl_curriculum.curriculum261_plan import load_locked_plan
    from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    return {fam: fp["rung_params"] for fam, fp in plan["families"].items()}


def run_ppo262_smoke(out_dir: Path | None = None) -> dict[str, Any]:
    """执行 PPO smoke,返回结构化结果(并可选写盘)。"""
    from stable_baselines3 import PPO

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    rung_params = _locked_rung_params()

    # --- smoke bank(ppo_smoke_262:3 family 各 D1 1 pair 双端 = 6 eps)
    keys: list[EpisodeKey] = []
    for fam in ("c1_opportunity", "c2_context", "c3_cost"):
        for variant in ("A", "B"):
            keys.append(EpisodeKey(
                "ppo_smoke_262", fam, "D1", 0, variant))
    bank = generate262_bank(keys, locked_plan_rung_params=rung_params)
    details["bank"] = [e.key.canonical() for e in bank]

    env = CurriculumMultiEpisodeEnv(bank)
    obs, info = env.reset(seed=7)
    obs_arr = np.asarray(obs)
    checks["observation_shape_9"] = obs_arr.shape == (9,)
    checks["observation_finite"] = bool(np.all(np.isfinite(obs_arr)))
    checks["observation_dtype_float32"] = str(obs_arr.dtype) == "float32"
    checks["action_space_discrete2"] = (
        env.action_space.__class__.__name__ == "Discrete"
        and env.action_space.n == 2)

    # episode 推进 + 边界清空验证
    rewards_finite = True
    equities_reset_ok = True
    steps_per_episode = []
    cur_steps = 0
    done_count = 0
    for _ in range(6):
        done = False
        while not done:
            obs, r, term, trunc, info = env.step(1)
            rewards_finite = rewards_finite and np.isfinite(r)
            cur_steps += 1
            done = term or trunc
        # 终端清算后 equity 必须 = 全现金(position 清零)
        eq = info.get("equity_end")
        btc = info.get("btc", info.get("actual_position", 0))
        equities_reset_ok = equities_reset_ok and (btc == 0)
        steps_per_episode.append(cur_steps)
        cur_steps = 0
        done_count += 1
        obs, info = env.reset()
    checks["rewards_finite"] = rewards_finite
    checks["position_cleared_between_episodes"] = equities_reset_ok
    checks["episodes_completed_6"] = done_count == 6
    checks["steps_287_per_episode"] = all(
        s == 287 for s in steps_per_episode)
    audit = env.audit()
    checks["no_skip_no_repeat"] = (
        audit["duplicate_episode_completions"] == 0
        and audit["first_pass_order_ok"])
    # 耗尽行为:第 7 次 reset 触发 exhausted_cycles(受控,非静默)
    env.reset()
    checks["exhaustion_detected"] = env.exhausted_cycles == 1
    details["env_audit"] = audit
    details["steps_per_episode"] = steps_per_episode

    # --- SB3 短训练(n_steps 对齐:6 eps x 287 = 1722 = 287 x 6;
    #     smoke config:n_steps=574 -> 3 块;预算 1722)
    env2 = CurriculumMultiEpisodeEnv(bank)
    cfg = dict(PPO262_CANDIDATES["cand_a_center"])
    model = build_ppo(cfg, seed=26299, env=env2)
    model.learn(total_timesteps=6 * 287, progress_bar=False)
    a2 = env2.audit()
    checks["sb3_learn_completed"] = a2["steps_taken"] == 6 * 287
    checks["sb3_no_bank_overrun"] = a2["exhausted_cycles"] <= 1

    # --- save/load + deterministic eval 一致
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "smoke_model"
        model.save(str(mp))
        loaded = PPO.load(str(mp), device="cpu")
        acts_a, acts_b = [], []
        envA = CurriculumMultiEpisodeEnv(bank)
        envB = CurriculumMultiEpisodeEnv(bank)
        oa, _ = envA.reset(seed=5)
        ob, _ = envB.reset(seed=5)
        for _ in range(287):
            pa = loaded.predict(oa.reshape(1, -1), deterministic=True)
            pb = loaded.predict(ob.reshape(1, -1), deterministic=True)
            acts_a.append(int(np.asarray(pa[0]).reshape(-1)[0]))
            acts_b.append(int(np.asarray(pb[0]).reshape(-1)[0]))
            oa, _, ta, _, _ = envA.step(acts_a[-1])
            ob, _, tb, _, _ = envB.step(acts_b[-1])
        checks["deterministic_eval_reproducible"] = acts_a == acts_b
        details["deterministic_actions_sha256"] = hashlib.sha256(
            np.asarray(acts_a, dtype=np.int8).tobytes()).hexdigest()

    # --- 固定 seed + 固定 manifest 短 run 可复现
    env3 = CurriculumMultiEpisodeEnv(bank)
    m3 = build_ppo(cfg, seed=26299, env=env3)
    m3.learn(total_timesteps=2 * 287, progress_bar=False)
    env4 = CurriculumMultiEpisodeEnv(bank)
    m4 = build_ppo(cfg, seed=26299, env=env4)
    m4.learn(total_timesteps=2 * 287, progress_bar=False)
    w3 = m3.policy.state_dict()
    w4 = m4.policy.state_dict()
    same = all(
        np.array_equal(w3[k].detach().numpy(), w4[k].detach().numpy())
        for k in w3)
    checks["fixed_seed_run_reproducible"] = same

    result = {
        "format": "ppo262-ppo-smoke-v1",
        "stage": "stage2_6_2",
        "namespace": "ppo_smoke_262",
        "timeframe": CURRICULUM261_TIMEFRAME,
        "checks": checks,
        "details": details,
        "pass": all(checks.values()),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "ppo_smoke.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False,
                       default=_np_default),
            encoding="utf-8")
    return result


def _np_default(o):
    import numpy as np
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"不可序列化: {type(o)}")
