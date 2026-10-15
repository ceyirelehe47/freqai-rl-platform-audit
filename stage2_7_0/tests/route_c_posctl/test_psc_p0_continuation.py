# -*- coding: utf-8 -*-
"""统一续训入口 p0continue + 登记 p0registry 纯假对象单测。

范围(批准版 2026-10-15):仅代码+纯假对象/临时目录测试。
不加载真实模型、不调用真实 env/optimizer、不生成 bank、
不写生产 registry 或历史账本;每测试用独立 tmp_path。

覆盖面:
- plan 纯校验(追加/累计不一致、缺字段、大写课程名)
- 前序课程毕业门(c2 无 c1 GRADUATED 拒;有人工批准后仅登记)
- bank 列序错位拒绝
- schedule 漂移在 intent 前拒绝(零训练步零优化器调用)
- resume 语义(append + reset_num_timesteps=False)
- 保存时序(final 唯一且在 learn 之后;异常不伪造 final)
- 预算门(上限前置拒绝;异常计数 attempts/successes/unknown)
- registry 并发重复(flock 互斥,恰一 intent)
- 半写 torn 行(不可充当 settled)
- 双 seed 字段分离登记
- 失败终态(failed 后禁 settle、禁重复 intent、不自动重试)
- 课程状态表(无批准不得 GRADUATED;旧 SHA 证明;历史追加)
- 评估冻结口径(216 格/1024 predict/step;in-sample 标签;
  无 bootstrap)
"""
import json
import multiprocessing
import sys
from pathlib import Path

import pytest

from rl_posctl.skill_p0 import p0continue as pc
from rl_posctl.skill_p0.p0registry import (
    CurriculumStatus, Registry, RegistryError, plan_digest)

HYPER = {"n_steps": 1024, "batch_size": 64, "n_epochs": 10,
         "gamma": 0.99, "gae_lambda": 0.95, "vf_coef": 0.5,
         "ent_coef": 0.0, "max_grad_norm": 0.5}


class FakeOpt:
    def __init__(self):
        self.calls = 0

    def step(self, *a, **k):
        self.calls += 1
        return None


class FakePolicy:
    def __init__(self):
        self.optimizer = FakeOpt()


class FakeModel:
    def __init__(self, base=131072, clip=0.2, lr=3e-4):
        self.num_timesteps = base
        self.n_envs = 1
        self.n_steps = HYPER["n_steps"]
        self.policy = FakePolicy()
        self._clip = clip
        self._lr = lr
        for k, v in HYPER.items():
            setattr(self, k, v)
        self.set_env_calls = []
        self.seed_calls = []
        self.learn_calls = []

    def clip_range(self, pr):
        return self._clip

    def lr_schedule(self, pr):
        return self._lr

    def set_env(self, env):
        self.set_env_calls.append(env)

    def set_random_seed(self, seed):
        self.seed_calls.append(seed)

    def learn(self, **kwargs):
        self.learn_calls.append(kwargs)
        for _ in range(8):
            self.policy.optimizer.step()
        self.num_timesteps += kwargs["total_timesteps"]


def make_plan(tmp_path, **over):
    ck = tmp_path / "ck131072.zip"
    ck.write_bytes(b"fake-ck-bytes")
    bank = tmp_path / "train_bank.json"
    bank.write_bytes(b"fake-bank-bytes")
    from rl_posctl.skill_p0.p0registry import sha256_file
    plan = {
        "experiment_id_hint": "TEST_CONT_001",
        "source": {
            "checkpoint": str(ck),
            "checkpoint_sha256": sha256_file(ck),
            "run_name": "B_270201", "arm": "B",
            "base_model_seed_in_zip": 270201,
            "git_head_pinned": "3a241c4932476e3c9dfb2ebd5c94b"
                               "b4f9cf41938"},
        "steps": {"append_steps": 32768,
                  "cumulative_end": 163840},
        "random_stream": {"new_seed": 271001,
                          "resume_semantics": pc.RESUME_SEMANTICS},
        "course": {"course": "c1",
                   "bank_path": str(bank),
                   "bank_sha256": sha256_file(bank),
                   "feature_names": ["c", "g", "q", "s"]},
        "budget": {"train_steps": 32768,
                   "optimizer_updates": 8},
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


def base_hooks(model, order, *, clip=0.2):
    def load_model(plan):
        order.append("load")
        return model, {"arm": "B"}

    def bank_feature_names(path):
        return ["c", "g", "q", "s"]

    def save_final(model, path, *, target_step,
                   optimizer_steps, run_name):
        order.append("save_final")
        Path(path).write_bytes(b"fake-final-zip")
        return {"stage": "final", "target_step": target_step,
                "optimizer_steps": optimizer_steps}

    def make_env(items):
        order.append("env")
        return ["fake-env"]

    def envmod():
        return type("M", (), {"ENV_STEP_COUNT": 0,
                              "ENV_STEP_LIMIT": 0})()

    def make_stop():
        return type("S", (), {"failure": None,
                              "cb": None})()

    def learn(m, append, stop):
        order.append("learn")
        m.learn(total_timesteps=append,
                reset_num_timesteps=False,
                callback=stop.cb)

    def run_episodes(m, tier, bank_path, feature_names):
        order.append("episodes:" + tier)
        rows = [{"tier": tier, "step": i,
                 "predict_unknown": False}
                for i in range(512)]
        return rows, {"predicts_done": 512,
                      "steps_done": 512,
                      "predict_unknown": False}

    return {
        "load_model": load_model,
        "bank_feature_names": bank_feature_names,
        "save_final": save_final,
        "load_bank_items": lambda p: ["item"],
        "make_env": make_env,
        "envmod": envmod,
        "make_stop": make_stop,
        "learn": learn,
        "eval_hooks": {
            "grid_obs": lambda fn: [
                {"c": 0.0, "g": 0.0, "q": 0.0, "s": 0.0}
            ] * 108,
            "dist_probs": lambda m, obs: {
                "grid": [[0.25, 0.5, 0.25]] * len(obs)},
            "run_episodes": run_episodes,
        },
    }


# ---- 1. plan 纯校验 ---------------------------------------------
def test_steps_mismatch_refused_before_intent(tmp_path):
    plan = make_plan(tmp_path)
    plan["steps"]["cumulative_end"] = 163841  # 不自洽
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    order = []
    rc = pc.run_continuation(
        p, tmp_path / "reg", hooks=base_hooks(FakeModel(),
                                              order))
    # 163841-131072=32769 != append 32768 → 阶段4拒绝
    assert rc == pc.FAIL["steps"]
    assert order == ["load"]  # 未建 env、未 learn、未登记
    reg = Registry(tmp_path / "reg")
    assert list(reg.iter_events()) == []


def test_missing_sha_refused(tmp_path):
    plan = make_plan(tmp_path)
    del plan["source"]["checkpoint_sha256"]
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["plan"]


def test_uppercase_course_refused(tmp_path):
    plan = make_plan(tmp_path, **{"course.course": "C1"})
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    rc = pc.run_continuation(
        p, tmp_path / "reg",
        hooks=base_hooks(FakeModel(), []))
    assert rc == pc.FAIL["plan"]


# ---- 2. 前序课程毕业门 + 仅登记 -------------------------------
def test_c2_without_c1_graduated_refused(tmp_path):
    plan = make_plan(tmp_path, **{"course.course": "c2"})
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    order = []
    rc = pc.run_continuation(
        p, tmp_path / "reg", hooks=base_hooks(FakeModel(),
                                              order))
    assert rc == pc.FAIL["prereq"]
    assert list(Registry(
        tmp_path / "reg").iter_events()) == []


def test_c2_registry_only_after_manual_graduation(tmp_path):
    status = CurriculumStatus(tmp_path / "reg")
    status.set_stage(
        "B", "c1", "GRADUATED",
        promotion={"approved_by": "U0C90T68D0D",
                   "approval_ref": "SLACK-Ev0CAB0KVBS4",
                   "utc": "2026-10-15T00:00:00Z"})
    plan = make_plan(tmp_path, **{"course.course": "c2"})
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    order = []
    rc = pc.run_continuation(
        p, tmp_path / "reg", hooks=base_hooks(FakeModel(),
                                              order))
    assert rc == 0
    assert order == []  # 仅登记:未加载、未训练
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert [e["event"] for e in ev] == ["intent"]
    assert ev[0]["mode"] == "registry_only"
    assert ev[0]["course"] == "c2"


# ---- 3. bank 列序 ----------------------------------------------
def test_bank_feature_order_mismatch_refused(tmp_path):
    plan = make_plan(tmp_path)
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    hooks = base_hooks(FakeModel(), [])
    hooks["bank_feature_names"] = lambda path: [
        "c", "q", "g", "s"]
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["bank_order"]
    assert list(Registry(
        tmp_path / "reg").iter_events()) == []


# ---- 4. schedule 预验证(intent 前,零训练零更新) -------------
def test_schedule_drift_refused_zero_training(tmp_path):
    plan = make_plan(tmp_path)
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    order = []
    hooks = base_hooks(FakeModel(clip=0.9), order)
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == pc.FAIL["schedule"]
    assert order == ["load"]
    assert list(Registry(
        tmp_path / "reg").iter_events()) == []


# ---- 5. 成功路径:resume 语义/保存时序/评估口径/双 seed -----
def test_success_path_full_contract(tmp_path):
    plan = make_plan(tmp_path)
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    order = []
    model = FakeModel()
    hooks = base_hooks(model, order)
    rc = pc.run_continuation(p, tmp_path / "reg",
                             hooks=hooks)
    assert rc == 0
    # resume 语义
    kw = model.learn_calls[0]
    assert kw["total_timesteps"] == 32768
    assert kw["reset_num_timesteps"] is False
    assert model.seed_calls == [271001]
    # 保存时序:final 唯一且在 learn 之后、评估之前?final 先于
    # 冻结源冷载与评估;无中间档
    assert order.index("learn") < order.index("save_final")
    assert order.count("save_final") == 1
    assert order[order.index("save_final") + 1] == "load"
    # 事件:intent → settled;双 seed 分离
    ev = list(Registry(tmp_path / "reg").iter_events())
    assert [e["event"] for e in ev] == ["intent", "settled"]
    intent, settled = ev
    assert intent["base_model_seed_in_zip"] == 270201
    assert intent["new_random_stream_seed"] == 271001
    assert intent["mode"] == "executable"
    # 实结计数与 v5 门语义一致
    assert settled["optimizer"] == {
        "attempts": 8, "successes": 8, "unknown": False}
    assert settled["train_steps_settled"] == 32768
    assert settled["num_timesteps_end"] == 163840
    # 评估冻结口径
    es = settled["eval"]
    assert es["grid_observations"] == 216
    assert es["predicts_done"] == 1024
    assert es["steps_done"] == 1024
    assert es["raw_rows_flushed"] == 1024
    assert es["predict_attempt_unknown"] is False
    assert "IN-SAMPLE" in es["note"]
    assert "bootstrap" in es["note"]
    evid = Path(plan["evidence"]["root"])
    raw = evid / "eval" / "raw_episodes.jsonl"
    assert sum(1 for _ in open(
        raw, encoding="utf-8")) == 1024
    assert (evid / "eval" / "grid_source_frozen.json"
            ).exists()
    assert (evid / "eval" / "grid_new.json").exists()
    assert (evid / "ck163840.zip").exists()
    # evidence root 独占:重跑同 plan 会在 intent 处拒绝
    rc2 = pc.run_continuation(p, tmp_path / "reg",
                              hooks=base_hooks(FakeModel(),
                                               []))
    assert rc2 == pc.FAIL["intent"]


# ---- 6. 预算门与异常计数(v5 语义) ----------------------------
def test_optimizer_gate_cap_prefixed(tmp_path):
    opt = FakeOpt()
    box = pc.wrap_optimizer_gate(opt, cap=2)
    opt.step()
    opt.step()
    from rl_posctl.budget import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        opt.step()
    assert box["attempts"] == 2
    assert box["successes"] == 2
    assert box["unknown"] is False


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


# ---- 7. learn 异常:无 final、failed 实结、不自动重试 -----
def test_learn_exception_failed_terminal(tmp_path):
    plan = make_plan(tmp_path)
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    order = []

    def bad_learn(m, append, stop):
        order.append("learn")
        m.policy.optimizer.step()
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
    failed = ev[1]
    assert failed["optimizer"]["attempts"] == 2
    assert failed["optimizer"]["successes"] == 2
    # failed 终态:再 settle 拒绝;同 plan 重复 intent 拒绝
    reg = Registry(tmp_path / "reg")
    with pytest.raises(RegistryError):
        reg.record_settled(
            "TEST_CONT_001", plan_digest(plan), {})
    rc2 = pc.run_continuation(p, tmp_path / "reg",
                              hooks=base_hooks(FakeModel(),
                                               []))
    assert rc2 == pc.FAIL["intent"]


# ---- 8. 并发重复(flock 互斥) --------------------------------
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
    intents = [x for x in lines if x["event"] == "intent"]
    assert len(intents) == 1


# ---- 9. 半写 torn 行 -------------------------------------------
def test_torn_line_not_settled(tmp_path):
    reg = Registry(tmp_path / "reg")
    plan = make_plan(tmp_path)
    reg.register_intent(plan, mode="executable")
    # 人为制造半写行(无换行的截断 JSON)
    with open(reg.jsonl, "a", encoding="utf-8") as fh:
        fh.write('{"event": "settled", "experiment_i')
    ev = list(reg.iter_events())
    kinds = [e["event"] for e in ev]
    assert kinds == ["intent", "torn"]
    torn = ev[1]
    assert torn["raw"].startswith('{"event": "settled"')
    # torn 不充当 settled:可正常实结一次,再拒绝
    reg.record_settled("TEST_CONT_001",
                       plan_digest(plan), {"rc": 0})
    with pytest.raises(RegistryError):
        reg.record_settled("TEST_CONT_001",
                           plan_digest(plan), {"rc": 0})


def test_settle_without_intent_rejected(tmp_path):
    reg = Registry(tmp_path / "reg")
    with pytest.raises(RegistryError):
        reg.record_settled(
            "NOPE", "0" * 64, {"rc": 0})


# ---- 10. 课程状态表不变量 -------------------------------------
def test_graduated_requires_manual_approval(tmp_path):
    st = CurriculumStatus(tmp_path / "reg")
    with pytest.raises(RegistryError):
        st.set_stage("B", "c1", "GRADUATED")
    st.set_stage("B", "c1", "IN_PROGRESS")
    assert not st.graduated("B", "c1")
    from rl_posctl.skill_p0.p0registry import sha256_file
    cur = sha256_file(st.path)
    st.set_stage("B", "c1", "GRADUATED",
                 promotion={"approved_by": "rev",
                            "approval_ref": "ref-1"},
                 expected_sha256=cur)
    assert st.graduated("B", "c1")
    with pytest.raises(RegistryError):
        st.set_stage("B", "c1", "IN_PROGRESS",
                     expected_sha256=cur)  # 旧 SHA=过期
    data = json.loads(st.path.read_text(encoding="utf-8"))
    assert data["history"][-1]["from"] == "IN_PROGRESS"
    assert data["history"][-1]["to"] == "GRADUATED"
    assert len(data["history"]) == 2


# ---- 11. 评估引擎口径(直接) ----------------------------------
def test_eval_engine_frozen_contract(tmp_path):
    def run_episodes(m, tier, bank_path, feature_names):
        rows = [{"tier": tier, "predict_unknown": False}
                for _ in range(512)]
        return rows, {"predicts_done": 512,
                      "steps_done": 512,
                      "predict_unknown": False}

    s = pc.run_contrast_eval(
        [("source_frozen", object()), ("new", object())],
        bank_path="unused", feature_names=["c", "g", "q", "s"],
        out_dir=tmp_path / "ev",
        hooks={"grid_obs": lambda fn: [0.0] * 108,
               "dist_probs": lambda m, obs: {
                   "grid": [[0.25, 0.5, 0.25]] * 108},
               "run_episodes": run_episodes})
    assert s["grid_observations"] == 216
    assert s["predicts_done"] == 1024
    assert s["steps_done"] == 1024
    assert s["predict_attempt_unknown"] is False
    assert "NOT unseen-data generalization" in s["note"]


def test_eval_engine_unknown_flag_propagates(tmp_path):
    def run_episodes(m, tier, bank_path, feature_names):
        return [], {"predicts_done": 0, "steps_done": 0,
                    "predict_unknown": (tier == "new")}

    s = pc.run_contrast_eval(
        [("source_frozen", object()), ("new", object())],
        bank_path="unused", feature_names=["c", "g", "q", "s"],
        out_dir=tmp_path / "ev2",
        hooks={"grid_obs": lambda fn: [0.0] * 108,
               "dist_probs": lambda m, obs: {"grid": []},
               "run_episodes": run_episodes})
    assert s["predict_attempt_unknown"] is True
