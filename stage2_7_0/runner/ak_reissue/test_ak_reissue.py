# -*- coding: utf-8 -*-
"""ak_reissue 手写数据-only 控制(零模型/零评价)。"""
import json
import pathlib
import sys

import pytest
import numpy as np
import torch as th

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for d in ("seed_contrast_prep_20261016",
          "teaching_pilot_prep_20261016",
          "diag_panel_prep_20261016",
          "seed_extend_prep_20261017"):
    sys.path.insert(0, "/mnt/f/trading/" + d)

import ak_reissue as AR  # noqa: E402


def test_np_scalars_to_native():
    d = {"tap_kl": np.float32(0.012),
         "n": np.int64(320),
         "flag": np.bool_(True),
         "arr": np.arange(3, dtype=np.float64),
         "nested": {"x": np.float32(-1.5)}}
    out = AR.to_native(d)
    assert type(out["tap_kl"]) is float
    assert out["tap_kl"] == pytest.approx(0.012, abs=1e-6)
    assert type(out["n"]) is int
    assert type(out["flag"]) is bool
    assert all(type(x) is float for x in out["arr"])
    assert type(out["nested"]["x"]) is float
    json.dumps(out, allow_nan=False)


def test_nan_rejected_with_path():
    with pytest.raises(AR.SerializationError) as ei:
        AR.to_native({"rows": [{"kl": float("nan")}]})
    diag = ei.value.args[0]
    assert diag["kind"] == "non-finite"
    assert "kl" in diag["path"]


def test_unknown_type_rejected():
    class Weird:
        pass
    with pytest.raises(AR.SerializationError) as ei:
        AR.to_native({"w": Weird()})
    assert ei.value.args[0]["kind"] == "unknown-type"
    assert ei.value.args[0]["type"] == "Weird"


def test_atomic_no_truncate_on_fail(tmp_path):
    target = tmp_path / "r.json"
    target.write_text('{"existing": 1}', encoding="utf-8")
    with pytest.raises(AR.SerializationError):
        AR.atomic_write_json({"bad": float("nan")}, str(target))
    assert target.read_text(encoding="utf-8") == '{"existing": 1}'
    assert not list(tmp_path.glob("*.tmp.*"))
    AR.atomic_write_json({"ok": 1.5}, str(target))
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": 1.5}
    assert not list(tmp_path.glob("*.tmp.*"))


def test_main_default_explicit(tmp_path, monkeypatch):
    calls = []

    def fake_run(out_dir, spec_path=None, **kw):
        calls.append((out_dir, spec_path))
        return {"status": "stub"}
    monkeypatch.setattr(AR, "run", fake_run)
    AR.main([str(tmp_path / "o1")])
    assert calls[-1][1] == str(
        pathlib.Path(AR._HERE) / "RUNSPEC_AKRE.json")
    AR.main([str(tmp_path / "o2"), "--spec", "/tmp/x.json"])
    assert calls[-1][1] == "/tmp/x.json"
    with pytest.raises(SystemExit):
        AR.main([str(tmp_path / "o3"), "--mode", "debug"])
    assert len(calls) == 2


class _P:
    def state_dict(self):
        return {"k": th.zeros(1)}

    def predict(self, obs, deterministic=False, *a, **k):
        return (np.array([[1.0, 0.0]]), None)


class _M:
    policy = _P()


def _builder(p):
    return _M(), AR.PARAM_HASH_PIN


def _ev(mm, tr, r, tag, lg, bk):
    eps = [{"index": i, "valid": True, "net_log": 0.0}
           for i in range(len(tr))]
    r[tag + "_episodes"] = eps
    steps = sum(len(x["steps"]) for x in tr)
    r["steps"][tag] = steps
    for _ in range(steps):
        lg.add(1, tag)
    for t in tr:
        for _st in t["steps"]:
            mm.policy.predict(th.ones(1, 8))
    return steps


def _pin_digest(monkeypatch):
    monkeypatch.setattr(
        AR, "params_digest",
        lambda policy: AR.PARAM_HASH_PIN)


TR = []
_per = 2112 // 128
_rem = 2112 - _per * 128
for _i in range(128):
    _n = _per + (1 if _i < _rem else 0)
    TR.append({"remaining": 32 if _i % 2 == 0 else 1,
               "s0": 1 if _i % 2 == 0 else -1,
               "steps": [{"s": 1}] * _n})

def _mk_spec(tmp, tr):
    import hashlib, json as J
    spec = J.loads(
        pathlib.Path(AR._HERE, "RUNSPEC_AKRE.json")
        .read_text(encoding="utf-8"))
    canon = hashlib.sha256(
        J.dumps(tr, sort_keys=True,
                separators=(",", ":"))
        .encode()).hexdigest()
    spec["inputs"]["traces_canon_sha256"] = canon
    p = tmp / "spec.json"
    p.write_text(J.dumps(spec, ensure_ascii=False,
                         indent=1) + "\n", encoding="utf-8")
    return str(p), hashlib.sha256(
        p.read_bytes()).hexdigest()



def test_fake_chain_completed(tmp_path, monkeypatch):
    _pin_digest(monkeypatch)
    sp, sh = _mk_spec(tmp_path, TR)
    orig_pin = AR.RUNSPEC_SHA256
    AR.RUNSPEC_SHA256 = sh
    try:
        rep = AR.run(
            str(tmp_path / "c"), traces=TR,
            spec_path=sp,
            builder=_builder, inner_eval=_ev,
            clock=(lambda: 0.0, lambda: 0.0))
    finally:
        AR.RUNSPEC_SHA256 = orig_pin
    assert rep["status"] == "completed"
    assert len(rep["eval_actions"]) == 2112
    assert (tmp_path / "c" / "DONE.marker").exists()
    receipt = json.loads(
        (tmp_path / "c" / "ak_reissue.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "completed"
    assert receipt["kind"] == "reissue_eval_only"


def test_fake_chain_serialization_refused(tmp_path, monkeypatch):
    _pin_digest(monkeypatch)
    class _Weird:
        pass

    def ev_w(mm, tr, r, tag, lg, bk):
        n = _ev(mm, tr, r, tag, lg, bk)
        r["weird"] = _Weird()
        return n
    sp, sh = _mk_spec(tmp_path, TR)
    orig_pin = AR.RUNSPEC_SHA256
    AR.RUNSPEC_SHA256 = sh
    try:
        with pytest.raises(RuntimeError,
                           match="serialization refused"):
            AR.run(str(tmp_path / "s"), traces=TR,
                   spec_path=sp,
                   builder=_builder, inner_eval=ev_w,
                   clock=(lambda: 0.0, lambda: 0.0))
    finally:
        AR.RUNSPEC_SHA256 = orig_pin
    receipt = json.loads(
        (tmp_path / "s" / "ak_reissue.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "serialization_refused"
    assert receipt["diag"]["kind"] == "unknown-type"
    assert (tmp_path / "s" / "FAILED.marker").exists()


def test_budget_final_boom(tmp_path, monkeypatch):
    _pin_digest(monkeypatch)
    import seed_contrast as SCi

    class _Boom:
        def __init__(self):
            self.seen = []

        def checkpoint(self, ph):
            self.seen.append(ph)
            if ph == "final":
                return ("wall", {"wall_s": 1e3}, {})
            return (None, {}, {})
    real = SCi.Book
    boom = _Boom()

    class _PB:
        def __init__(self, *a, **k):
            self._r = real(*a, **k)

        def checkpoint(self, ph):
            w, c, p2 = boom.checkpoint(ph)
            rw, rc, rp = self._r.checkpoint(ph)
            return (w or rw, c if w else rc, p2 if w else rp)

        def snapshot(self):
            return self._r.snapshot()
    orig = AR.SC.Book
    AR.SC.Book = _PB
    try:
        sp, sh = _mk_spec(tmp_path, TR)
        orig_pin = AR.RUNSPEC_SHA256
        AR.RUNSPEC_SHA256 = sh
        try:
            with pytest.raises(RuntimeError, match="budget"):
                AR.run(
                    str(tmp_path / "b"), traces=TR,
                    spec_path=sp,
                    builder=_builder,
                    inner_eval=_ev,
                    clock=(lambda: 0.0, lambda: 0.0))
        finally:
            AR.RUNSPEC_SHA256 = orig_pin
    finally:
        AR.SC.Book = orig
    rep = json.loads(
        (tmp_path / "b" / "ak_reissue.json").read_text(encoding="utf-8"))
    assert rep["status"] == "failed"


def test_status():
    assert AR.STATUS == "PREPARED_NOT_RUN"


class _StubPolicy:
    def __init__(self):
        self.training = True

    def set_training_mode(self, m):
        self.training = m

    def predict(self, obs, deterministic=False, *a, **k):
        return (np.array([[1.0, 0.0]]), None)

    def state_dict(self):
        return {"k": th.zeros(1)}


class _StubModel:
    def __init__(self):
        self.policy = _StubPolicy()


def test_cold_load_stub_cpu_custom(tmp_path, monkeypatch):
    """open/load 桩走实际 cold_load:SHA 先拒/
    cpu+custom_objects/param hash 拒。"""
    import stable_baselines3 as sb3
    calls = {"load": [], "custom": []}

    def fake_load(path, device=None, custom_objects=None, **kw):
        calls["load"].append({"path": path, "device": device})
        calls["custom"].append(custom_objects)
        return _StubModel()
    monkeypatch.setattr(AR, "PPO", sb3.PPO)
    monkeypatch.setattr(sb3.PPO, "load", staticmethod(fake_load))
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"junk")
    with pytest.raises(RuntimeError, match="AK_final SHA"):
        AR.cold_load(str(bad))
    assert calls["load"] == []
    ck = "/mnt/f/trading/auxkeep_a1_20261017_output/AK_final.zip"
    monkeypatch.setattr(
        AR, "sha256_file",
        lambda p: AR.AK_FINAL_PIN if p.endswith("AK_final.zip")
        else AR.sha256_file(p))
    with pytest.raises(RuntimeError, match="param hash"):
        AR.cold_load(ck)
    assert calls["load"][0]["device"] == "cpu"
    co = calls["custom"][0]
    assert co["pilot_env"] is None
    assert co["_auxkeep_logger"] == []
    assert co["_auxkeep_obs"] is None


def test_run_identity_fail_zero_eval(tmp_path, monkeypatch):
    """pilot spec SHA 拒(默认路径)→零 eval。"""
    ev_called = {"n": 0}

    def ev(mm, tr, r, tag, lg, bk):
        ev_called["n"] += 1
        return 0
    _orig_sha = AR.sha256_file

    def sha(p):
        if p.endswith("run_spec.json"):
            return AR.PILOT_SPEC_PIN + "0"
        return _orig_sha(p)
    monkeypatch.setattr(AR, "sha256_file", sha)
    with pytest.raises(RuntimeError, match="pilot spec"):
        AR.run(str(tmp_path / "i"),
               clock=(lambda: 0.0, lambda: 0.0))
    assert ev_called["n"] == 0


def test_oserror_failed_keeps_data(tmp_path, monkeypatch):
    """一次 OSError→failed+partial 数据保留。"""
    _pin_digest(monkeypatch)

    def ev_os(mm, tr, r, tag, lg, bk):
        _ev(mm, tr, r, tag, lg, bk)
        raise OSError("disk boom")
    sp, sh = _mk_spec(tmp_path, TR)
    orig_pin = AR.RUNSPEC_SHA256
    AR.RUNSPEC_SHA256 = sh
    try:
        with pytest.raises(OSError):
            AR.run(str(tmp_path / "oe"), traces=TR,
                   spec_path=sp, builder=_builder,
                   inner_eval=ev_os,
                   clock=(lambda: 0.0, lambda: 0.0))
    finally:
        AR.RUNSPEC_SHA256 = orig_pin
    rep = json.loads(
        (tmp_path / "oe" / "ak_reissue.json").read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert "disk boom" in rep["fail_reason"]
    dd = json.loads(
        (tmp_path / "oe" / "eval_data.json").read_text(encoding="utf-8"))
    assert dd["complete"] is False
    assert dd["n_actions_captured"] == 2112
    assert len(json.loads(
        (tmp_path / "oe" / "eval_actions.json").read_text(encoding="utf-8"))) == 2112


def test_post_save_overlimit_failed(tmp_path, monkeypatch):
    """post_save 超限:rp 已在仍 failed/FAILED。"""
    _pin_digest(monkeypatch)
    import seed_contrast as SCi

    class _Boom:
        def checkpoint(self, ph):
            if ph == "post_save":
                return ("wall", {"wall_s": 1e3}, {})
            return (None, {}, {})
    real = SCi.Book
    boom = _Boom()

    class _PB:
        def __init__(self, *a, **k):
            self._r = real(*a, **k)

        def checkpoint(self, ph):
            w, c, p2 = boom.checkpoint(ph)
            rw, rc, rp = self._r.checkpoint(ph)
            return (w or rw, c if w else rc, p2 if w else rp)

        def snapshot(self):
            return self._r.snapshot()
    orig = AR.SC.Book
    AR.SC.Book = _PB
    try:
        sp, sh = _mk_spec(tmp_path, TR)
        orig_pin = AR.RUNSPEC_SHA256
        AR.RUNSPEC_SHA256 = sh
        try:
            with pytest.raises(RuntimeError,
                               match=r"budget\(post_save\)"):
                AR.run(str(tmp_path / "ps"), traces=TR,
                       spec_path=sp, builder=_builder,
                       inner_eval=_ev,
                       clock=(lambda: 0.0, lambda: 0.0))
        finally:
            AR.RUNSPEC_SHA256 = orig_pin
    finally:
        AR.SC.Book = orig
    rep = json.loads(
        (tmp_path / "ps" / "ak_reissue.json").read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert (tmp_path / "ps" / "FAILED.marker").exists()
    assert not (tmp_path / "ps" / "DONE.marker").exists()
    assert (tmp_path / "ps" / "eval_data.json").exists()


def test_params_changed_after_eval(tmp_path, monkeypatch):
    """eval 后参数变更→拒,failed。"""
    monkeypatch.setattr(
        AR, "params_digest",
        lambda policy: "0" * 64)
    sp, sh = _mk_spec(tmp_path, TR)
    orig_pin = AR.RUNSPEC_SHA256
    AR.RUNSPEC_SHA256 = sh
    try:
        with pytest.raises(RuntimeError, match="params changed"):
            AR.run(str(tmp_path / "pm"), traces=TR,
                   spec_path=sp, builder=_builder,
                   inner_eval=_ev,
                   clock=(lambda: 0.0, lambda: 0.0))
    finally:
        AR.RUNSPEC_SHA256 = orig_pin
    rep = json.loads(
        (tmp_path / "pm" / "ak_reissue.json").read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert (tmp_path / "pm" / "FAILED.marker").exists()


def test_early_identity_fail_receipt(tmp_path, monkeypatch):
    """反例1:identity 早失败也产失败 receipt
    (actions 前移修复)。"""
    _orig_sha = AR.sha256_file

    def sha(p):
        if p.endswith("run_spec.json"):
            return "0" * 64
        return _orig_sha(p)
    monkeypatch.setattr(AR, "sha256_file", sha)
    with pytest.raises(RuntimeError, match="pilot spec"):
        AR.run(str(tmp_path / "e1"),
               clock=(lambda: 0.0, lambda: 0.0))
    rep = json.loads(
        (tmp_path / "e1" / "ak_reissue.json")
        .read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert "pilot spec" in rep["fail_reason"]
    assert (tmp_path / "e1" / "FAILED.marker").exists()


def test_actions_write_fail_independent(tmp_path, monkeypatch):
    """反例2:data 落而 actions 首写失败→
    data 保留+io_errors 记录+receipt 仍写。"""
    _pin_digest(monkeypatch)
    real_aw = AR.atomic_write_json
    aw_state = {"boom": True}

    def aw(obj, path):
        if path.endswith("eval_actions.json") \
                and aw_state["boom"]:
            aw_state["boom"] = False
            raise OSError("actions io boom")
        return real_aw(obj, path)
    monkeypatch.setattr(AR, "atomic_write_json", aw)

    def ev_os(mm, tr, r, tag, lg, bk):
        _ev(mm, tr, r, tag, lg, bk)
        raise OSError("disk boom")
    sp, sh = _mk_spec(tmp_path, TR)
    orig_pin = AR.RUNSPEC_SHA256
    AR.RUNSPEC_SHA256 = sh
    try:
        with pytest.raises(OSError):
            AR.run(str(tmp_path / "e2"), traces=TR,
                   spec_path=sp, builder=_builder,
                   inner_eval=ev_os,
                   clock=(lambda: 0.0, lambda: 0.0))
    finally:
        AR.RUNSPEC_SHA256 = orig_pin
    dd = json.loads(
        (tmp_path / "e2" / "eval_data.json")
        .read_text(encoding="utf-8"))
    assert dd["complete"] is False
    rep = json.loads(
        (tmp_path / "e2" / "ak_reissue.json")
        .read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert any("eval_actions" in e
               for e in rep.get("io_errors", []))
    assert (tmp_path / "e2" / "FAILED.marker").exists()


def test_post_save_overlimit_no_done_even_if_rewrite_fails(
        tmp_path, monkeypatch):
    """反例3:post_save 超限且 receipt 覆写失败
    →无 DONE+FAILED 在+保持失败。"""
    import seed_contrast as SCi
    _pin_digest(monkeypatch)

    class _Boom:
        def checkpoint(self, ph):
            if ph == "post_save":
                return ("wall", {"wall_s": 1e3}, {})
            return (None, {}, {})
    real = SCi.Book
    boom = _Boom()

    class _PB:
        def __init__(self, *a, **k):
            self._r = real(*a, **k)

        def checkpoint(self, ph):
            w, c, p2 = boom.checkpoint(ph)
            rw, rc, rp = self._r.checkpoint(ph)
            return (w or rw, c if w else rc,
                    p2 if w else rp)

        def snapshot(self):
            return self._r.snapshot()
    orig_book = AR.SC.Book
    AR.SC.Book = _PB
    real_aw = AR.atomic_write_json
    aw_state = {"receipt_writes": 0}

    def aw(obj, path):
        if path.endswith("ak_reissue.json"):
            aw_state["receipt_writes"] += 1
            # 首 receipt(completed)
            # 成功;覆写全失败
            if aw_state["receipt_writes"] > 1:
                raise OSError("disk gone")
        return real_aw(obj, path)
    monkeypatch.setattr(AR, "atomic_write_json", aw)
    try:
        sp, sh = _mk_spec(tmp_path, TR)
        orig_pin = AR.RUNSPEC_SHA256
        AR.RUNSPEC_SHA256 = sh
        try:
            with pytest.raises(RuntimeError,
                               match=r"budget\(post_save\)"):
                AR.run(str(tmp_path / "e3"), traces=TR,
                       spec_path=sp, builder=_builder,
                       inner_eval=_ev,
                       clock=(lambda: 0.0, lambda: 0.0))
        finally:
            AR.RUNSPEC_SHA256 = orig_pin
    finally:
        AR.SC.Book = orig_book
    assert not (tmp_path / "e3" / "DONE.marker").exists()
    assert (tmp_path / "e3" / "FAILED.marker").exists()
    assert (tmp_path / "e3" / "ak_reissue.json").exists()
