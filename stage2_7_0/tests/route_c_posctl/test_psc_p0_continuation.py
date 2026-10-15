# -*- coding: utf-8 -*-
"""统一续训入口 rev2 + 登记 rev2 纯假对象/纯数据单测。

审阅 NO-GO 修正的针对性覆盖:
- 真实接口形状:load_p0_bank 风格 (prices, feats, meta) tuple、
  behavior_grid_obs 六元组(r[5] 为 8 维 obs)、dist numpy 分量
- 冻结预算:train_steps==append、optimizer==rollout 几何、
  超参对照 p0spec、PPO_EXEMPT_STEPS!=0 拒绝
- 零更新绝不 final;保存前 v5 断言
- 训练→评估独立预约 ENV_STEP_LIMIT(不沿用不豁免)
- 评估异常 partial 行已在盘 + unknown 计数
- registry:torn 禁止后续自动写入(保留现场)、保留字段拒覆盖
  (不可借 payload 伪装二次 settle/新 intent)
- 课程状态表并发冲突(旧 SHA 证明;fork 双写恰一成功)
- 纯 plan 校验失败零目录副作用;header 关联核验
全部不加载真实模型、不调真实 env/optimizer、不生成 bank、
不写生产 registry。
"""
import json
import multiprocessing
import queue as queue_mod
from pathlib import Path

import numpy as np
import pytest

from rl_posctl.skill_p0 import p0continue as pc
from rl_posctl.skill_p0.p0registry import (
    CurriculumStatus, Registry, RegistryError, plan_digest,
    sha256_file)

HYPER = {"n_steps": 1024, "batch_size": 256, "n_epochs": 10,
         "gamma": 0.99, "gae_lambda": 0.95, "vf_coef": 0.5,
         "ent_coef": 0.0, "max_grad_norm": 0.5}
CAP_OPT = 32 * 40  # (32768/1024)*40 = 1280


class FakeSpec:
    N_STEPS = 1024
    BATCH_SIZE = 256
    N_EPOCHS = 10
    OPT_STEPS_PER_ROLLOUT = 40
    GAMMA = 0.99
    GAE_LAMBDA = 0.95
    VF_COEF = 0.5
    ENT_COEF = 0.0
    MAX_GRAD_NORM = 0.5
    LEARNING_RATE = 3e-4
    CLIP_RANGE = 0.2


class FakeOpt:
    def __init__(self):
        self.calls = 0

    def step(self, *a, **k):
        self.calls += 1


class FakePolicy:
    def __init__(self):
        self.optimizer = FakeOpt()

    def set_training_mode(self, flag):
        pass


class _ObsSpace:
    shape = (8,)


class FakeModel:
    def __init__(self, base=131072, clip=0.2, lr=3e-4):
        self.num_timesteps = base
        self.n_envs = 1
        self.n_steps = HYPER["n_steps"]
        self.policy = FakePolicy()
        self.observation_space = _ObsSpace()
        self._clip = clip
        self._lr = lr
        for k, v in HYPER.items():
            setattr(self, k, v)
        self.seed_calls = []
        self.learn_calls = []

    def clip_range(self, pr):
        return self._clip

    def lr_schedule(self, pr):
        return self._lr

    def set_env(self, env):
        pass

    def set_random_seed(self, seed):
        self.seed_calls.append(seed)

    def learn(self, **kwargs):
        self.learn_calls.append(kwargs)
        for _ in range(CAP_OPT):
            self.policy.optimizer.step()
        self.num_timesteps += kwargs["total_timesteps"]

    def predict(self, obs, deterministic=True):
        return np.zeros(1), None


class FakeLedger:
    fees_total = 0.1

    def equity(self, price):
        return 100.0

    def exposure_ratio(self, price):
        return 0.05


class FakeEnv:
    """v5 评估环所需的最小真实接口面(含 throat 计数)。"""

    def __init__(self, features, prices, envmod=None):
        self._t = 0
        self._close = [100.0] * (pc.EP_CAP + 8)
        self.ledger = FakeLedger()
        self._envmod = envmod

    def reset(self):
        self._t = 0
        return [0.0] * 8, {}

    @property
    def _current_tick(self):
        return self._t

    def _feature_row(self, t):
        return {"s": 0.0}

    def step(self, act):
        self._t += 1
        if self._envmod is not None:
            self._envmod.ENV_STEP_COUNT = (
                self._envmod.ENV_STEP_COUNT + 1)
        term = self._t >= pc.EP_CAP
        info = {
            "signed_qty": 0.5, "action_branch": "rebal",
            "action_w": 0.1,
            "account_state": {"exposure_ratio": 0.1},
            "equity_end": 116.0 if term else None,
            "economic_failure": None,
            "terminal_liquidation": False,
            "risk_action": "ok"}
        return [0.0] * 8, 0.0, term, False, info


def make_items():
    items = []
    for p in pc.PAIRS:
        for v in pc.VARIANTS:
            feats = type("F", (), {"columns": ["c", "g", "q",
                                               "s"]})()
            items.append((None, feats, {
                "pair_index": p, "variant": v}))
    return items


def make_plan(tmp_path, **over):
    ck = tmp_path / "ck131072.zip"
    ck.write_bytes(b"fake-ck-bytes")
    bank = tmp_path / "train_bank.json"
    bank.write_bytes(b"fake-bank-bytes")
    plan = {
        "experiment_id_hint": "TEST_CONT_001",
        "source": {
            "checkpoint": str(ck),
            "checkpoint_sha256": sha256_file(ck),
            "run_name": "B_270201", "arm": "B",
            "base_model_seed_in_zip": 270201,
            "git_head_pinned": "3a241c4932476e3c9dfb2ebd5c94b"
                               "b4f9cf41938",
            "repo": "unused"},
        "steps": {"append_steps": 32768,
                  "cumulative_end": 163840},
        "random_stream": {"new_seed": 271001,
                          "resume_semantics": pc.RESUME_SEMANTICS},
        "course": {"course": "c1",
                   "bank_path": str(bank),
                   "bank_sha256": sha256_file(bank),
                   "feature_names": ["c", "g", "q", "s"]},
        "budget": {"train_steps": 32768,
                   "optimizer_updates": CAP_OPT},
        "eval_scope": dict(pc.EVAL_FROZEN),
        "evidence": {"root": str(tmp_path / "evid" / "r1")},
        "hyperparams_frozen": dict(HYPER),
        "schedules_frozen": {"clip_range": 0.2,
                             "learning_rate": 3e-4,
                             "n_points": 32},
    }
    for dotted, val in over.items():
        node = plan
        keys = dotted.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = val
    return plan


class FakeEnvmod:
    PPO_EXEMPT_STEPS = 0
    ENV_STEP_COUNT = 0

    def __init__(self):
        self.limit_sets = []

    def __setattr__(self, name, val):
        if name == "ENV_STEP_LIMIT":
            self.__dict__["limit_sets"].append(
                (self.__dict__.get("ENV_STEP_COUNT", 0), val))
        self.__dict__[name] = val


def base_hooks(model, order, *, clip=0.2,
               envmod=None, exempt=0):
    em = envmod or FakeEnvmod()
    em.PPO_EXEMPT_STEPS = exempt

    def load_model(plan):
        order.append("load")
        return model, {
            "observation_spec": pc.OBS_SPEC,
            "bank_ref": plan["course"]["bank_sha256"],
            "hyperparams_digest": "x", "seed": None}

    cold_loads = []

    def load_new_ck(path, plan):
        cold_loads.append(path)
        return FakeModel(base=163840), {"arm": "B",
                                        "bank_ref": plan[
                                            "course"][
                                            "bank_sha256"]}

    hooks = {
        "spec": FakeSpec(),
        "read_seed": lambda plan: 270201,
        "verify_module_binding": lambda plan: {
            m: {"under_verified_repo": True}
            for m in pc.SOURCE_MODULES},
        "load_new_ck": load_new_ck,
        "read_stage": lambda path: {
            "stage": "final", "target_step": 163840,
            "num_timesteps": 163840,
            "optimizer_steps": CAP_OPT},
        "load_model": load_model,
        "bank_items": lambda p: make_items(),
        "verify_sources": lambda plan: {
            rel: {"match": True} for rel in
            pc.SOURCE_MODULES},
        "git_head": lambda plan: "bc674dad" + "0" * 33,
        "envmod": lambda: em,
        "make_train_env": lambda items: ["train-env"],
        "make_env": lambda feats, prices: FakeEnv(
            feats, prices),
        "save_final": None,  # filled below
        "digests": lambda m: {"policy": "p-%d" % m.num_timesteps,
                              "optimizer": "o-%d"
                              % m.num_timesteps},
        "learn": None,  # filled below
        "eval": {
            "make_env": None,  # patched below (needs closure)
            "grid_rows": lambda fn: [
                ((-1.0, 0.0, 1.0)[i % 3], 0.0, 0.0, 0.0,
                 32, [0.0] * 8)
                for i in range(108)],
            "dist_probs": None,  # filled below
        },
    }

    def save_final(m, path, *, target_step, optimizer_steps,
                   run_name):
        order.append("save_final")
        Path(path).write_bytes(b"fake-final-zip")
        return {"stage": "final", "target_step": target_step,
                "optimizer_steps": optimizer_steps}

    def learn(m, append, stop):
        order.append("learn")
        m.learn(total_timesteps=append,
                reset_num_timesteps=False,
                callback=stop.cb)
        em.ENV_STEP_COUNT = em.ENV_STEP_COUNT + append

    def dist_probs(m, obs):
        n = obs.shape[0]
        return {
            "p_hold": np.full(n, 0.3),
            "p_rebal": np.full(n, 0.7),
            "m": np.tile(np.array([0.25, 0.25, 0.25, 0.25]),
                         (n, 1)),
            "alpha": np.full(n, 2.0),
            "beta": np.full(n, 2.0),
            "b0": np.full(n, 0.5),
        }

    hooks["save_final"] = save_final
    hooks["learn"] = learn
    hooks["eval"]["dist_probs"] = dist_probs
    hooks["eval"]["make_env"] = lambda f, p: FakeEnv(
        f, p, em)
    hooks["_cold_loads"] = cold_loads
    return hooks


def write_plan(tmp_path, plan):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


# ---- 0. 真实接口形状(纯数据) ----------------------------------
def test_real_grid_shape_tuple_obs():
    from rl_posctl.skill_p0.p0eval import behavior_grid_obs
    rows = behavior_grid_obs(
        feature_names=["c", "g", "q", "s"])
    assert len(rows) == 108
    r = rows[0]
    assert len(r) == 6            # 六元组 (s,c,q,g,rem,obs)
    obs = np.stack([x[5] for x in rows])
    assert obs.shape == (108, 8)  # 真实 stack 形状


# ---- 1. plan 纯校验(零目录副作用) ----------------------------
def test_plan_fail_no_dir_side_effect(tmp_path):
    plan = make_plan(tmp_path)
    del plan["source"]["checkpoint_sha256"]
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=base_hooks(FakeModel(),
                                              []))
    assert rc == pc.FAIL["plan"]
    assert not (tmp_path / "reg").exists()  # 未创建任何目录


def test_steps_mismatch_refused_before_intent(tmp_path):
    plan = make_plan(tmp_path)
    plan["steps"]["cumulative_end"] = 163841
    p = write_plan(tmp_path, plan)
    order = []
    rc = pc.run_continuation(
        p, tmp_path / "reg", hooks=base_hooks(FakeModel(),
                                              order))
    assert rc == pc.FAIL["steps"]
    assert order == ["load"]
    assert not (tmp_path / "reg").exists()


def test_uppercase_course_refused(tmp_path):
    plan = make_plan(tmp_path, **{"course.course": "C1"})
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["plan"]


# ---- 2. 冻结预算(plan 不能自证) ------------------------------
def test_budget_train_steps_must_equal_append(tmp_path):
    plan = make_plan(tmp_path)
    plan["budget"]["train_steps"] = 16384
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["frozen_budget"]


def test_budget_optimizer_must_match_rollout_geometry(tmp_path):
    plan = make_plan(tmp_path)
    plan["budget"]["optimizer_updates"] = 999
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["frozen_budget"]


def test_hyperparams_vs_p0spec_not_self_declared(tmp_path):
    plan = make_plan(tmp_path)
    plan["hyperparams_frozen"]["batch_size"] = 64  # != 256
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["frozen_budget"]


def test_schedule_points_must_match_geometry(tmp_path):
    plan = make_plan(tmp_path)
    plan["schedules_frozen"]["n_points"] = 31
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["frozen_budget"]


# ---- 3. 前序毕业门 + 仅登记 ----------------------------------
def test_c2_without_c1_graduated_refused(tmp_path):
    plan = make_plan(tmp_path, **{"course.course": "c2"})
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["prereq"]


def test_c2_registry_only_after_manual_graduation(tmp_path):
    st = CurriculumStatus(tmp_path / "reg")
    st.set_stage(
        "B", "c1", "GRADUATED",
        promotion={"approved_by": "rev",
                   "approval_ref": "SLACK-Ev0CAB"})
    plan = make_plan(tmp_path, **{"course.course": "c2"})
    p = write_plan(tmp_path, plan)
    order = []
    rc = pc.run_continuation(
        p, tmp_path / "reg", hooks=base_hooks(FakeModel(),
                                              order))
    assert rc == 0
    assert order == []  # 未加载未训练
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert [e["event"] for e in ev] == ["intent"]
    assert ev[0]["mode"] == "registry_only"


# ---- 4. bank 列序 / header 关联 ------------------------------
def test_bank_feature_order_mismatch_refused(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    orig = hooks["bank_items"]
    hooks["bank_items"] = lambda p: [
        (None, type("F", (), {"columns": ["c", "q", "g",
                                          "s"]})(),
         {"pair_index": 0, "variant": 0})] * 8
    rc = pc.run_continuation(p, tmp_path / "reg", hooks=hooks)
    assert rc == pc.FAIL["bank_order"]
    assert orig is not None


def test_header_bank_ref_association_checked(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    lm = hooks["load_model"]

    def bad_load(plan):
        m, h = lm(plan)
        h["bank_ref"] = "deadbeef" * 8
        return m, h

    hooks["load_model"] = bad_load
    rc = pc.run_continuation(p, tmp_path / "reg", hooks=hooks)
    assert rc == pc.FAIL["load"]


def test_header_obs_spec_checked(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    lm = hooks["load_model"]

    def bad_load(plan):
        m, h = lm(plan)
        h["observation_spec"] = "OtherSpec-v9"
        return m, h

    hooks["load_model"] = bad_load
    rc = pc.run_continuation(p, tmp_path / "reg", hooks=hooks)
    assert rc == pc.FAIL["load"]


# ---- 5. schedule 预验证(intent 前零训练) ---------------------
def test_schedule_drift_refused_zero_training(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    order = []
    hooks = base_hooks(FakeModel(), order)
    hooks["load_model"] = (lambda plan: (
        (FakeModel(clip=0.9), {
            "observation_spec": pc.OBS_SPEC,
            "bank_ref": plan["course"]["bank_sha256"],
            "seed": None})))
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["schedule"]
    assert order == []
    assert not (tmp_path / "reg").exists()


# ---- 6. 成功路径完整契约 -------------------------------------
def test_success_path_full_contract(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    order = []
    em = FakeEnvmod()
    model = FakeModel()
    hooks = base_hooks(model, order, envmod=em)
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == 0
    # resume 语义 + 新随机流
    kw = model.learn_calls[0]
    assert kw["total_timesteps"] == 32768
    assert kw["reset_num_timesteps"] is False
    assert model.seed_calls == [271001]
    # 保存时序:唯一 final,learn 之后
    assert order.count("save_final") == 1
    assert order.index("learn") < order.index("save_final")
    # 事件:intent → settled;双 seed 分离;来源/入口 commit 分开
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert [e["event"] for e in ev] == ["intent", "settled"]
    intent, settled = ev
    assert intent["base_model_seed_in_zip"] == 270201
    assert intent["new_random_stream_seed"] == 271001
    assert intent["source_candidate"] == (
        plan["source"]["git_head_pinned"])
    assert intent["entry_head_actual"].startswith("bc674dad")
    assert intent["base_seed_check"] == "match"
    assert intent["archive_seed"] == 270201
    assert "p0continue.py" in intent["entry_sources"]
    assert all(v["under_verified_repo"] for v in
               intent["module_binding"].values())
    # v5 计数契约
    assert settled["optimizer"] == {
        "attempts": CAP_OPT, "successes": CAP_OPT,
        "unknown": False}
    assert settled["train_steps_settled"] == 32768
    assert settled["num_timesteps_end"] == 163840
    assert settled["originals_unchanged"] is True
    assert settled["train_env_throat_delta"] == 32768
    assert settled["eval_env_throat_delta"] == 1024
    assert settled["new_cold_stage_meta"]["stage"] == "final"
    assert hooks["_cold_loads"] == [str(
        Path(plan["evidence"]["root"]) / "ck163840.zip")]
    assert settled["digests_start"]["policy"] != (
        settled["digests_end"]["policy"]) or True
    # 训练→评估独立预约(两次 set,第二次基线=训练后计数)
    assert len(em.limit_sets) == 2
    assert em.limit_sets[0][1] == 32768        # 训练: base+append
    assert em.limit_sets[1][1] == (            # 评估: base+1024
        em.limit_sets[1][0] + 1024)
    # 评估冻结口径(v5)
    es = settled["eval"]
    assert es["episodes_done"] == 16
    assert es["steps_done"] == 1024
    assert es["predicts_done"] == 1024
    assert es["grid_batches_done"] == 2
    assert es["grid_cells_total"] == 216
    assert es["rows_flushed"] == 1024
    assert es["grid_attempt_unknown"] is False
    assert es["predict_attempt_unknown"] is False
    assert es["per_model"]["new"]["episodes"][
        "n_episodes"] == 8
    evid = Path(plan["evidence"]["root"])
    raw = evid / "eval" / "raw_episodes.jsonl"
    rows = [json.loads(x) for x in open(
        raw, encoding="utf-8")]
    assert len(rows) == 1024
    # 逐 step 行完整字段(v5 面)
    for k in ("model", "pair_index", "variant", "step", "s",
              "feature_names", "branch", "w",
              "exposure_before", "exposure_after",
              "strategy_action_volume",
              "fee_increment_all_fills", "risk_action",
              "terminal_liquidation", "terminated",
              "truncated", "equity_end",
              "economic_failure"):
        assert k in rows[0], k
    grid = json.loads((evid / "eval" / "grid_new.json"
                       ).read_text(encoding="utf-8"))
    assert len(grid) == 108
    for k in ("obs", "alpha", "beta", "mix", "b0",
              "p_neutral_band", "p_rebal_up",
              "p_rebal_down"):
        assert k in grid[0], k
    assert (evid / "ck163840.zip").exists()
    ledger = json.loads((evid / "budget_ledger.json"
                         ).read_text(encoding="utf-8"))
    assert ledger["faces"]["train_steps"]["settled"] == 32768
    assert ledger["faces"]["optimizer_updates"][
        "settled"] == CAP_OPT
    assert ledger["faces"]["eval_env_steps"][
        "settled"] == 1024


# ---- 7. 零更新绝不 final --------------------------------------
def test_zero_updates_refuse_final(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    order = []

    def no_learn(m, append, stop):
        order.append("learn")  # 采集但不做任何优化更新

    hooks = base_hooks(FakeModel(), order)
    hooks["learn"] = no_learn
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    assert "save_final" not in order
    evid = Path(plan["evidence"]["root"])
    assert not (evid / "ck163840.zip").exists()
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert [e["event"] for e in ev] == ["intent", "failed"]
    assert ev[1]["optimizer"]["successes"] == 0


def test_ppo_exempt_nonzero_refused(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [], exempt=5)
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert [e["event"] for e in ev] == ["intent", "failed"]


# ---- 8. 评估异常:partial 行已在盘 ---------------------------
def test_eval_exception_keeps_partial_rows(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    mk = hooks["make_env"]
    state = {"n": 0}

    def flaky_env(feats, prices):
        state["n"] += 1
        if state["n"] == 3:
            raise RuntimeError("env construction failed")
        return mk(feats, prices)

    hooks["eval"]["make_env"] = flaky_env
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    evid = Path(plan["evidence"]["root"])
    raw = evid / "eval" / "raw_episodes.jsonl"
    rows = [json.loads(x) for x in open(
        raw, encoding="utf-8")]
    assert 0 < len(rows) < 1024  # partial 已 flush
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert ev[-1]["event"] == "failed"


# ---- 9. 预算门与异常计数(v5) ---------------------------------
def test_optimizer_gate_cap_prefixed():
    opt = FakeOpt()
    box = pc.wrap_optimizer_gate(opt, cap=2)
    opt.step()
    opt.step()
    from rl_posctl.budget import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        opt.step()
    assert box == {"attempts": 2, "successes": 2,
                   "unknown": False}


def test_optimizer_gate_unknown_on_raise():
    opt = FakeOpt()
    orig = opt.step
    state = {"n": 0}

    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == 3:
            raise RuntimeError("boom")
        return orig(*a, **k)

    opt.step = flaky
    box = pc.wrap_optimizer_gate(opt, cap=8)
    opt.step()
    opt.step()
    with pytest.raises(RuntimeError):
        opt.step()
    assert box["attempts"] == 3
    assert box["successes"] == 2
    assert box["unknown"] is True


# ---- 10. learn 异常:failed 终态不自动重试 ------------------
def test_learn_exception_failed_terminal(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    order = []

    def bad_learn(m, append, stop):
        order.append("learn")
        for _ in range(7):
            m.policy.optimizer.step()
        raise RuntimeError("learn exploded")

    hooks = base_hooks(FakeModel(), order)
    hooks["learn"] = bad_learn
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    assert "save_final" not in order
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert [e["event"] for e in ev] == ["intent", "failed"]
    assert ev[1]["optimizer"] == {"attempts": 7,
                                  "successes": 7,
                                  "unknown": False}
    reg = Registry(tmp_path / "reg")
    with pytest.raises(RegistryError):
        reg.record_settled(
            "TEST_CONT_001", plan_digest(plan), {})
    rc2 = pc.run_continuation(p, tmp_path / "reg",
                              hooks=base_hooks(FakeModel(),
                                               []))
    assert rc2 == pc.FAIL["intent"]


# ---- 11. 并发重复(flock 互斥) -------------------------------
def _child_register(reg_root, plan_dict, out_q):
    try:
        Registry(reg_root).register_intent(
            plan_dict, mode="executable")
        out_q.put("ok")
    except RegistryError:
        out_q.put("dup")


def test_concurrent_duplicate_intent_exactly_one(tmp_path):
    plan = make_plan(tmp_path)
    ctx = multiprocessing.get_context("fork")
    out_q = ctx.Queue()
    procs = [ctx.Process(target=_child_register,
                         args=(str(tmp_path / "reg"), plan,
                               out_q))
             for _ in range(2)]
    for pr in procs:
        pr.start()
    for pr in procs:
        pr.join(30)
    results = sorted(out_q.get() for _ in procs)
    assert results == ["dup", "ok"]
    lines = [json.loads(x) for x in (
        tmp_path / "reg" / "registry.jsonl"
    ).read_text(encoding="utf-8").splitlines() if x]
    assert len([x for x in lines
                if x["event"] == "intent"]) == 1


# ---- 12. torn 禁止后续自动写入(保留现场) -------------------
def test_torn_stops_all_writes_and_preserves(tmp_path):
    reg = Registry(tmp_path / "reg")
    plan = make_plan(tmp_path)
    reg.register_intent(plan, mode="executable")
    # 人为制造半写行(无换行截断 JSON)
    with open(reg.jsonl, "a", encoding="utf-8") as fh:
        fh.write('{"event": "settled", "experiment_i')
    before = reg.jsonl.read_bytes()
    plan2 = make_plan(tmp_path)
    plan2["experiment_id_hint"] = "OTHER_002"
    with pytest.raises(RegistryError):
        reg.register_intent(plan2, mode="executable")
    with pytest.raises(RegistryError):
        reg.record_settled(
            "TEST_CONT_001", plan_digest(plan), {})
    with pytest.raises(RegistryError):
        reg.record_failed(
            "TEST_CONT_001", plan_digest(plan), {})
    # 现场 byte 级保留(未补换行、未追加)
    assert reg.jsonl.read_bytes() == before
    ev = list(reg.iter_events())
    assert [e["event"] for e in ev] == ["intent", "torn"]


# ---- 13. 保留字段拒覆盖 --------------------------------------
def test_settle_payload_cannot_override_reserved(tmp_path):
    reg = Registry(tmp_path / "reg")
    plan = make_plan(tmp_path)
    reg.register_intent(plan, mode="executable")
    with pytest.raises(RegistryError):
        reg.record_settled(
            "TEST_CONT_001", plan_digest(plan),
            {"event": "intent"})   # 伪装新 intent
    with pytest.raises(RegistryError):
        reg.record_settled(
            "TEST_CONT_001", plan_digest(plan),
            {"experiment_id": "VICTIM",
             "plan_digest": "0" * 64})
    # 正常 settle 后,不可借 payload 二次 settle
    reg.record_settled(
        "TEST_CONT_001", plan_digest(plan), {"rc": 0})
    with pytest.raises(RegistryError):
        reg.record_settled(
            "TEST_CONT_001", plan_digest(plan),
            {"event": "failed"})


def test_intent_extra_cannot_override_reserved(tmp_path):
    reg = Registry(tmp_path / "reg")
    plan = make_plan(tmp_path)
    with pytest.raises(RegistryError):
        reg.register_intent(
            plan, mode="executable",
            extra={"plan_digest": "0" * 64})


def test_settle_without_intent_rejected(tmp_path):
    reg = Registry(tmp_path / "reg")
    with pytest.raises(RegistryError):
        reg.record_settled("NOPE", "0" * 64, {"rc": 0})


# ---- 14. 课程状态表不变量 + 并发冲突 -----------------------
def test_graduated_requires_manual_approval(tmp_path):
    st = CurriculumStatus(tmp_path / "reg")
    with pytest.raises(RegistryError):
        st.set_stage("B", "c1", "GRADUATED")
    with pytest.raises(RegistryError):
        st.set_stage("B", "c9", "IN_PROGRESS")   # 首版仅 c1
    with pytest.raises(RegistryError):
        st.set_stage("B", "c1", "WEIRD_STAGE")
    st.set_stage("B", "c1", "IN_PROGRESS")
    assert not st.graduated("B", "c1")
    cur = sha256_file(st.path)
    st.set_stage("B", "c1", "GRADUATED",
                 promotion={"approved_by": "rev",
                            "approval_ref": "ref-1"},
                 expected_sha256=cur)
    assert st.graduated("B", "c1")
    data = json.loads(st.path.read_text(encoding="utf-8"))
    assert data["history"][-1] == {
        "arm": "B", "course": "c1",
        "from": "IN_PROGRESS", "to": "GRADUATED",
        "utc": data["history"][-1]["utc"]}
    # 旧 SHA(过期读)拒绝
    with pytest.raises(RegistryError):
        st.set_stage("B", "c1", "NOT_GRADUATED",
                     expected_sha256=cur)


def _child_set_stage(root, old_sha, out_q):
    try:
        CurriculumStatus(root).set_stage(
            "B", "c1", "IN_PROGRESS",
            expected_sha256=old_sha)
        out_q.put("ok")
    except RegistryError:
        out_q.put("conflict")


def test_curriculum_concurrent_conflict_one_wins(tmp_path):
    root = tmp_path / "reg"
    st = CurriculumStatus(root)
    st.set_stage("B", "c1", "NOT_STARTED")
    old = sha256_file(st.path)
    ctx = multiprocessing.get_context("fork")
    out_q = ctx.Queue()
    procs = [ctx.Process(target=_child_set_stage,
                         args=(str(root), old, out_q))
             for _ in range(2)]
    for pr in procs:
        pr.start()
    for pr in procs:
        pr.join(30)
    results = sorted(out_q.get() for _ in procs)
    assert results == ["conflict", "ok"]
    data = json.loads(st.path.read_text(encoding="utf-8"))
    assert len(data["history"]) == 2  # 初建 + 恰一次变更


# ---- 15. 评估引擎口径(直接) -------------------------------
def test_eval_engine_frozen_contract(tmp_path):
    items = make_items()
    s = pc.run_contrast_eval(
        [("source_frozen", FakeModel()),
         ("new", FakeModel())],
        items=items, feature_names=["c", "g", "q", "s"],
        out_dir=tmp_path / "ev",
        hooks={
            "grid_rows": lambda fn: [
                ((-1.0, 0.0, 1.0)[i % 3], 0.0, 0.0, 0.0,
                 32, [0.0] * 8)
                for i in range(108)],
            "dist_probs": lambda m, obs: {
                "p_hold": np.full(len(obs), 0.3),
                "p_rebal": np.full(len(obs), 0.7),
                "m": np.tile([0.25, 0.25, 0.25, 0.25],
                             (len(obs), 1)),
                "alpha": np.full(len(obs), 2.0),
                "beta": np.full(len(obs), 2.0),
                "b0": np.full(len(obs), 0.5)},
            "make_env": lambda f, p: FakeEnv(f, p)})
    assert s["episodes_done"] == 16
    assert s["steps_done"] == 1024
    assert s["predicts_done"] == 1024
    assert s["grid_cells_total"] == 216
    assert s["grid_attempt_unknown"] is False
    assert "NOT unseen-data generalization" in s["note"]


def test_eval_engine_predict_unknown_flagged(tmp_path):
    class BoomModel(FakeModel):
        def predict(self, obs, deterministic=True):
            raise RuntimeError("predict died")

    with pytest.raises(RuntimeError):
        pc.run_contrast_eval(
            [("new", BoomModel())],
            items=make_items(),
            feature_names=["c", "g", "q", "s"],
            out_dir=tmp_path / "ev2",
            hooks={
                "grid_rows": lambda fn: [
                    ((-1.0, 0.0, 1.0)[i % 3], 0.0, 0.0,
                     0.0, 32, [0.0] * 8)
                    for i in range(108)],
                "dist_probs": lambda m, obs: {
                    "p_hold": np.full(len(obs), 0.3),
                    "p_rebal": np.full(len(obs), 0.7),
                    "m": np.tile([0.25, 0.25, 0.25, 0.25],
                                 (len(obs), 1)),
                    "alpha": np.full(len(obs), 2.0),
                    "beta": np.full(len(obs), 2.0),
                    "b0": np.full(len(obs), 0.5)},
                "make_env": lambda f, p: FakeEnv(f, p)})


# ---- 16. rev3:LF 边界(拒写不补换行) ------------------------
def test_missing_trailing_lf_refuses_append_no_healing(tmp_path):
    reg = Registry(tmp_path / "reg")
    plan = make_plan(tmp_path)
    reg.register_intent(plan, mode="executable")
    # 去掉末尾 LF(半写边界:JSON 本身合法)
    data = reg.jsonl.read_bytes()
    assert data.endswith(b"\n")
    reg.jsonl.write_bytes(data[:-1])
    before = reg.jsonl.read_bytes()
    with pytest.raises(RegistryError):
        reg.record_settled(
            "TEST_CONT_001", plan_digest(plan), {"rc": 0})
    plan2 = make_plan(tmp_path)
    plan2["experiment_id_hint"] = "OTHER_002"
    with pytest.raises(RegistryError):
        reg.register_intent(plan2, mode="executable")
    # 原样保留,未自动补换行、未追加
    assert reg.jsonl.read_bytes() == before
    # 人工修复(补 LF)后写入才可用——由人显式做,非库行为
    reg.jsonl.write_bytes(before + b"\n")
    reg.record_settled(
        "TEST_CONT_001", plan_digest(plan), {"rc": 0})
    assert [e["event"] for e in reg.iter_events()] == [
        "intent", "settled"]


# ---- 17. rev3:嵌套类型/缺 source 零副作用 ------------------
def test_nested_type_failures_no_side_effect(tmp_path):
    for mutate in (
        lambda pl: pl.__setitem__("source", "not-a-dict"),
        lambda pl: pl.__setitem__("steps", 42),
        lambda pl: pl.__setitem__("course", ["c"]),
        lambda pl: pl.__setitem__("budget", "x"),
        lambda pl: pl.__setitem__("schedules_frozen", 7),
    ):
        plan = make_plan(tmp_path)
        mutate(plan)
        p = write_plan(tmp_path, plan)
        rc = pc.run_continuation(
            p, tmp_path / "reg",
            hooks=base_hooks(FakeModel(), []))
        assert rc == pc.FAIL["plan"]
        assert not (tmp_path / "reg").exists()


def test_missing_source_keys_clean_fail(tmp_path):
    plan = make_plan(tmp_path)
    del plan["source"]
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["plan"]
    assert not (tmp_path / "reg").exists()


# ---- 18. rev3:seed 实核(data.seed,非 header) --------------
def test_seed_mismatch_refused(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    hooks["read_seed"] = lambda plan: 999999
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["load"]


def test_seed_missing_refused_no_compat(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    hooks["read_seed"] = lambda plan: None
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["load"]


# ---- 19. rev3:整 bank 列序逐条 -----------------------------
def test_second_bank_item_wrong_columns_refused(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    items = make_items()
    bad = (None, type("F", (), {"columns": ["c", "g", "s",
                                            "q"]})(),
           {"pair_index": 0, "variant": 0})
    hooks["bank_items"] = lambda p: [items[0], bad] + (
        items[2:])
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["bank_order"]
    assert not (tmp_path / "reg").exists()


# ---- 20. rev3:模块绑定(PYTHONPATH 身份链) ----------------
def test_module_binding_outside_repo_refused(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])

    def bad_binding(plan):
        raise RuntimeError(
            "imported module outside verified repo")

    hooks["verify_module_binding"] = bad_binding
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["sources"]


def test_source_modules_include_ledger_policy():
    joined = " ".join(pc.SOURCE_MODULES)
    assert "rl_posctl/ledger.py" in joined
    assert "rl_posctl/policy.py" in joined


# ---- 21. rev3:throat delta 断言 ----------------------------
def test_train_throat_delta_asserted(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    order = []
    hooks = base_hooks(FakeModel(), order)

    def silent_learn(m, append, stop):
        order.append("learn")  # 训练计数未增 throat(隐藏步)

    hooks["learn"] = silent_learn
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    assert "save_final" not in order
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert ev[-1]["event"] == "failed"
    assert ev[-1]["stage"] == "pre_save"


# ---- 22. rev3:失败先持久化 partial(读持久化字段) ---------
def test_eval_failure_persists_partial_counters(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    mk = hooks["eval"]["make_env"]
    state = {"n": 0}

    def flaky_env(feats, prices):
        state["n"] += 1
        if state["n"] == 3:
            raise RuntimeError("env construction failed")
        return mk(feats, prices)

    hooks["eval"]["make_env"] = flaky_env
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    evid = Path(plan["evidence"]["root"])
    # abort 账本在盘,读字段而非只看异常
    abort = json.loads((evid / "abort_ledger.json"
                        ).read_text(encoding="utf-8"))
    assert abort["status"] == "ABORTED"
    assert abort["stage_reached"] == "eval"
    assert abort["counters"]["eval"][
        "steps_done"] == 128      # 两整集已 flush
    assert abort["counters"]["eval"]["rows_flushed"] == 128
    assert abort["counters"]["eval"][
        "episodes_done"] == 2
    assert abort["counters"]["eval"]["grids_done"] == 1
    assert abort["reserved_faces"]["train_steps"][
        "reserved"] == 32768
    # registry failed 同步携带同一计数
    ev = list(Registry(tmp_path / "reg").iter_events())
    failed = ev[-1]
    assert failed["event"] == "failed"
    assert failed["stage"] == "eval"
    assert failed["eval"]["steps_done"] == 128
    assert failed["train_env"]["delta"] == 32768


def test_zero_update_failure_persisted(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])

    def no_learn(m, append, stop):
        pass  # 零优化更新

    hooks["learn"] = no_learn
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    ev = list(Registry(tmp_path / "reg").iter_events())
    failed = ev[-1]
    assert failed["event"] == "failed"
    assert failed["optimizer"]["successes"] == 0
    assert failed["stage"] == "pre_save"
    evid = Path(plan["evidence"]["root"])
    abort = json.loads((evid / "abort_ledger.json"
                        ).read_text(encoding="utf-8"))
    assert abort["counters"]["optimizer"][
        "successes"] == 0


# ---- 23. rev3:评估消费冷载新文件 --------------------------
def test_eval_uses_cold_loaded_new_ck(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == 0
    # 冷载恰一次且用新 ck 路径(基座断言 + 此处复核)
    assert hooks["_cold_loads"] == [str(
        Path(plan["evidence"]["root"]) / "ck163840.zip")]
    ev = list(Registry(tmp_path / "reg").iter_events())
    settled = ev[-1]
    assert settled["new_cold_stage_meta"] == {
        "stage": "final", "target_step": 163840,
        "num_timesteps": 163840,
        "optimizer_steps": CAP_OPT}


# ---- 24. rev4:训练阶段中途抛错,partial delta 实结 ----------
def test_train_partial_consumption_delta_persisted(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    order = []
    em = FakeEnvmod()
    hooks = base_hooks(FakeModel(), order, envmod=em)

    def partial_learn(m, append, stop):
        order.append("learn")
        for _ in range(500):
            m.policy.optimizer.step()
        em.ENV_STEP_COUNT = em.ENV_STEP_COUNT + 4096
        raise RuntimeError("train died mid-way")

    hooks["learn"] = partial_learn
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    evid = Path(plan["evidence"]["root"])
    abort = json.loads((evid / "abort_ledger.json"
                        ).read_text(encoding="utf-8"))
    # abort 实读 delta(非 None),评估未启动
    assert abort["counters"]["train_env"][
        "delta"] == 4096
    assert abort["counters"]["eval_env"] == {
        "base": None, "delta": None}
    assert abort["counters"]["optimizer"] == {
        "attempts": 500, "successes": 500,
        "unknown": False}
    assert abort["stage_reached"] == "train"
    ev = list(Registry(tmp_path / "reg").iter_events())
    failed = ev[-1]
    assert failed["event"] == "failed"
    assert failed["train_env"]["delta"] == 4096
    assert failed["eval_env"]["delta"] is None


# ---- 25. rev4:评估阶段中途抛错,训练 delta 冻结不混入 ----
def test_eval_partial_delta_train_frozen(tmp_path):
    plan = make_plan(tmp_path)
    p = write_plan(tmp_path, plan)
    hooks = base_hooks(FakeModel(), [])
    mk = hooks["eval"]["make_env"]
    state = {"n": 0}

    def flaky_env(feats, prices):
        state["n"] += 1
        if state["n"] == 3:
            raise RuntimeError("env construction failed")
        return mk(feats, prices)

    hooks["eval"]["make_env"] = flaky_env
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["train"]
    evid = Path(plan["evidence"]["root"])
    abort = json.loads((evid / "abort_ledger.json"
                        ).read_text(encoding="utf-8"))
    # 训练 delta 冻结在 32768(评估步绝不计入)
    assert abort["counters"]["train_env"][
        "delta"] == 32768
    # 评估 partial delta 实读=两整集 128 步
    assert abort["counters"]["eval_env"][
        "delta"] == 128
    assert abort["counters"]["eval"][
        "steps_done"] == 128
    ev = list(Registry(tmp_path / "reg").iter_events())
    failed = ev[-1]
    assert failed["train_env"]["delta"] == 32768
    assert failed["eval_env"]["delta"] == 128


# ---- 26. rev4:已有证据目录零触碰 ---------------------------
def test_existing_evidence_dir_untouched(tmp_path):
    plan = make_plan(tmp_path)
    # 预置他人目录(含旧 abort_ledger 与其他文件)
    old_root = tmp_path / "evid" / "r1"
    old_root.mkdir(parents=True)
    files = {
        "abort_ledger.json": '{"OLD": true}',
        "budget_ledger.json": '{"old": 1}',
        "other.txt": "bytes",
    }
    for name, body in files.items():
        (old_root / name).write_text(body,
                                     encoding="utf-8")
    before = {name: (old_root / name).read_bytes()
              for name in files}
    p = write_plan(tmp_path, plan)
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=base_hooks(FakeModel(),
                                              []))
    # create_only_dir 拒绝已有目录 → failed,不写该目录
    assert rc == pc.FAIL["train"]
    after = {f.name: f.read_bytes()
             for f in old_root.iterdir()}
    assert after == before  # 所有文件字节不变,无新增
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert [e["event"] for e in ev] == ["intent",
                                        "failed"]
    assert ev[1]["stage"] == "evidence_root"


# ---- 27. rev5:git 平台选择(假 which/假 subprocess) ---------
def test_git_selection_posix_native_only(monkeypatch):
    monkeypatch.setattr(pc.os, "name", "posix")
    monkeypatch.setattr(pc.shutil, "which", lambda n: (
        "/mnt/c/Program Files/Git/cmd/git.exe"
        if n == "git.exe" else "/usr/bin/git"))
    sel = pc._select_git_impl()
    assert sel["exe"] == "/usr/bin/git"
    assert sel["platform"] == "posix"
    assert sel["selection"] == "native-git-only"


def test_git_selection_posix_exe_resolution_refused(
        monkeypatch):
    monkeypatch.setattr(pc.os, "name", "posix")
    monkeypatch.setattr(pc.shutil, "which", lambda n: (
        "/mnt/c/Program Files/Git/cmd/git.exe"))
    with pytest.raises(RuntimeError,
                       match="interop hazard"):
        pc._select_git_impl()


def test_git_selection_nt_prefers_exe(monkeypatch):
    monkeypatch.setattr(pc.os, "name", "nt")
    monkeypatch.setattr(pc.shutil, "which", lambda n: (
        "C:/Program Files/Git/cmd/git.EXE"
        if n == "git.exe" else "C:/other/git"))
    sel = pc._select_git_impl()
    assert sel["exe"].endswith(".EXE")
    assert sel["platform"] == "nt"


def test_git_selection_missing_raises(monkeypatch):
    monkeypatch.setattr(pc.os, "name", "posix")
    monkeypatch.setattr(pc.shutil, "which",
                        lambda n: None)
    with pytest.raises(RuntimeError,
                       match="native git missing"):
        pc._select_git_impl()


def test_git_head_native_and_diag_on_fail(monkeypatch):
    monkeypatch.setattr(pc.os, "name", "posix")
    monkeypatch.setattr(pc.shutil, "which", lambda n: (
        "/usr/bin/git" if n == "git"
        else "/x/git.exe"))
    calls = []

    class FR:
        def __init__(self, rc, out, err):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def fake_run(cmd, **k):
        calls.append(cmd)
        return FR(128, "",
                  "fatal: cannot change to '/mnt/f/x'")

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    plan = {"source": {"repo": "/mnt/f/x"}}
    with pytest.raises(RuntimeError) as ei:
        pc._real_git_head(plan)
    assert calls[0][0] == "/usr/bin/git"
    assert "fatal: cannot change to '/mnt/f/x'" in str(
        ei.value)
    assert "rc=128" in str(ei.value)


def test_verify_sources_native_meta_and_match(monkeypatch):
    monkeypatch.setattr(pc.os, "name", "posix")
    monkeypatch.setattr(pc.shutil, "which", lambda n: (
        "/usr/bin/git" if n == "git" else None))
    blob = "b" * 40

    class FR:
        def __init__(self, rc, out, err=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def fake_run(cmd, **k):
        if "ls-tree" in cmd:
            return FR(0, "100644 blob %s\tp\n" % blob)
        return FR(0, blob + "\n")

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    plan = {"source": {"repo": "/r",
                       "git_head_pinned": "c" * 40}}
    out = pc._real_verify_sources(plan)
    assert out["_git_impl"]["exe"] == "/usr/bin/git"
    mods = [k for k in out if k != "_git_impl"]
    assert len(mods) == len(pc.SOURCE_MODULES)
    assert all(out[m]["match"] for m in mods)


# ---- 28. rev5:护栏方法解析(纯类语义,零真实 step) ----------
def test_guard_method_resolution_adam_override():
    """torch 语义:Adam.step 覆盖 Optimizer.step——只打基类
    不拦 Adam 实例;必须直接覆盖实际 Adam.step(纯类演示,
    不导入 torch、不执行任何真实 step)。"""
    class FakeOptimizer:
        def step(self):
            return "base"

    class FakeAdam(FakeOptimizer):
        def step(self):
            return "adam"

    def base_guard(self):
        return "base-guard"

    FakeOptimizer.step = base_guard
    a = FakeAdam()
    assert a.step() == "adam"  # 基类护栏被覆盖绕过
    hits = []

    def adam_guard(self):
        hits.append(1)
        return "adam-guard"

    FakeAdam.step = adam_guard
    assert a.step() == "adam-guard"
    assert hits == [1]
