"""R17 C3 工程切片验收矩阵:G01 / G02 / G03。

对象:r17_c3_engineering_slice.py(八个预声明坐标的真实生成→评估切片
+ p52 拒绝负例下游哨兵 + 新进程只读读回)。

测试隔离纪律:真实生成/评估一律独立子进程(numpy 原生线程不进
pytest 进程);recipe 冻结等纯函数进程内运行;子进程调用带 watchdog。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()


def _slice_script() -> Path:
    cands = []
    if _HERE.parents[2].name == "stage2_6_1":
        cands.append(_HERE.parents[2] / "runner"
                     / "r17_c3_engineering_slice.py")
    cands.append(Path.home() / "projects" / "crypto_rl"
                 / "stage2_6_1_runner" / "r17_c3_engineering_slice.py")
    for c in cands:
        if c.is_file():
            return c
    pytest.skip("r17_c3_engineering_slice.py 在两树均不可达")


def _src_dir() -> Path:
    return _slice_script().resolve().parent.parent / "src"


def _orig_envelope() -> Path:
    cands = []
    if _HERE.parents[2].name == "stage2_6_1":
        cands.append(_HERE.parents[2] / "artifacts" / "repair17"
                     / "development" / "blocker_diagnosis" / "runs"
                     / "20260906T134324Z_1475"
                     / "generation_failure_envelopes_calibrate_c3_cost"
                     "_D0_p52.json")
    cands.append(Path(
        "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17"
        "/development/blocker_diagnosis/runs/20260906T134324Z_1475/"
        "generation_failure_envelopes_calibrate_c3_cost_D0_p52.json"))
    for c in cands:
        if c.is_file():
            return c
    pytest.skip("原 p52 envelope 不在本机")


def _run_slice(args: list[str],
               timeout: int = 1200) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_src_dir())
    return subprocess.run(
        [sys.executable, str(_slice_script()), *args],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(_src_dir().parent))


@pytest.fixture(scope="module")
def slice_mod():
    p = _slice_script()
    spec = importlib.util.spec_from_file_location(
        "r17_c3_engineering_slice_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def slice_run(tmp_path_factory):
    """一次完整切片运行(八坐标+p52 负例),G01/G02/G03 集成共享。"""
    if os.name == "nt":
        pytest.skip("需要 WSL 执行环境")
    out = tmp_path_factory.mktemp("slice_run") / "slice"
    r = _run_slice(["--out-dir", str(out),
                    "--p52-negative", str(_orig_envelope())])
    assert r.returncode == 0, r.stderr
    rows = [json.loads(line) for line in
            (out / "slice_results.jsonl").read_text(
                encoding="utf-8").splitlines() if line.strip()]
    return out, rows


# ================================================= G01 预声明坐标
class TestG01DeclaredCoordinates:
    """八个预声明坐标:每请求保留;first_pass/五次上限不变;无替换。"""

    def test_g01_recipe_fixed_before_results(self, slice_mod, tmp_path):
        """recipe 先于任何生成结果冻结;清单与任务书 §5.1 完全一致。"""
        recipe = slice_mod.freeze_recipe(tmp_path)
        assert recipe["namespace"] == "preplan_calibration_main_r17"
        assert recipe["family"] == "c3_cost"
        coords = [(q["rung"], q["pair_index"])
                  for q in recipe["requests"]]
        assert coords == [("D0", 0), ("D0", 1), ("D1", 0), ("D1", 1),
                          ("D2", 0), ("D2", 1), ("D3", 0), ("D3", 1)]
        assert recipe["n_requests"] == 8
        assert recipe["max_attempts"] == 5
        assert recipe["engineering_only"] is True
        assert (tmp_path / "recipe.json").is_file()
        # 冻结时无任何生成结果
        assert not (tmp_path / "slice_results.jsonl").exists()

    def test_g01_refuse_nonempty_out_dir(self, slice_mod, tmp_path):
        """非空输出目录:拒绝执行,不覆盖旧结果(不重开旧 run)。"""
        (tmp_path / "occupied.marker").write_text("x", encoding="utf-8")
        r = _run_slice(["--out-dir", str(tmp_path)], timeout=60)
        assert r.returncode == 2

    @pytest.mark.skipif(os.name == "nt", reason="需要 WSL 执行环境")
    def test_g01_full_slice_all_requests_kept(self, slice_run):
        """真实八坐标:每请求恰好一行结果,顺序=声明顺序,无增删替换。"""
        out, rows = slice_run
        assert len(rows) == 8
        assert [(row["rung"], row["pair_index"]) for row in rows] == [
            ("D0", 0), ("D0", 1), ("D1", 0), ("D1", 1),
            ("D2", 0), ("D2", 1), ("D3", 0), ("D3", 1)]
        # 每坐标的 detail 文件存在且 sha256 与执行时记录一致
        for row in rows:
            d = out / "pairs" / row["detail"]
            assert d.is_file()
            import hashlib
            assert hashlib.sha256(d.read_bytes()).hexdigest() == \
                row["detail_sha256"]
        summary = json.loads(
            (out / "slice_summary.json").read_text(encoding="utf-8"))
        assert summary["n_requests"] == 8
        assert summary["n_accepted"] + summary["n_rejected"] == 8
        assert summary["replaced_or_dropped"] is False


# ================================================= G02 真实评估链
class TestG02RealEvaluationChain:
    """合法 pair:生成→特征→环境→评估→保存→新进程读回(非 mocked)。"""

    def test_g02_accepted_pairs_real_evaluation_and_readback(
            self, slice_run):
        out, rows = slice_run
        accepted = [row for row in rows if row["status"] == "accepted"]
        if not accepted:
            pytest.skip("本轮八坐标无接受 pair(全部合法拒绝;"
                        "G02 评估链由负例哨兵 G03 覆盖)")
        for row in accepted:
            doc = json.loads((out / "pairs" / row["detail"]).read_text(
                encoding="utf-8"))
            ev = doc["evaluation"]
            # 真实策略评估:每 episode 有数值结果(非 mocked 占位)
            assert ev["episodes"], row["coord"]
            for ep in ev["episodes"]:
                for pol in ("always_flat", "always_long",
                            "c3_cost_ignorant", "reference", "oracle"):
                    v = ep[pol]
                    assert isinstance(v, float), (row["coord"], pol)
                    assert v == v and abs(v) != float("inf")
            # 生成身份与结构完整性闭合
            assert doc["integrity_ok"] is True, row["coord"]
            assert doc["episode_hashes"]["A"] and \
                doc["episode_hashes"]["B"]
            assert doc["recorder_errors"] == []
            assert doc["engineering_only"] is True
            assert "normalization" in doc["evaluation_note"]
        # 新进程只读读回(独立 subprocess)
        rb = _run_slice(["--readback", str(out)], timeout=300)
        assert rb.returncode == 0, rb.stderr
        rdoc = json.loads((out / "readback_report.json").read_text(
            encoding="utf-8"))
        assert rdoc["readback_verdict"] == "PASS"
        assert rdoc["checks"]["rows_match_requests"] is True
        assert rdoc["checks"]["coordinates_exact_match"] is True
        assert rdoc["checks"]["details_present_digest_status_ok"] is True


# ================================================= G03 拒绝下游哨兵
class TestG03RejectionDownstreamSentinel:
    """p52 被拒绝后:evaluator 零启动;无伪造成功产物;调用保持失败。"""

    def test_g03_p52_negative_sentinel(self, slice_run):
        out, rows = slice_run
        neg_path = out / "p52_negative.json"
        assert neg_path.is_file()
        neg = json.loads(neg_path.read_text(encoding="utf-8"))
        # 原调用实际保持失败(意外接受即证据矛盾)
        assert neg["accepted"] is False
        assert neg["selected_attempt"] is None
        # 五次 envelope 完整且拒绝词表与原记录一致
        assert neg["n_attempt_envelopes"] == 5
        assert neg["rejection_reasons_match_original"] is True
        assert neg["recorder_errors"] == []
        # evaluator 零启动(进程内真实计数)
        ds = neg["downstream_sentinel"]
        assert ds["evaluator_started"] is False
        assert ds["evaluator_invocations"] == 0
        assert ds["fake_empty_episode"] is False
        assert ds["cached_output_used"] is False
        # 无伪造成功产物:负例不在八坐标结果行,无 pairs/ 详情
        assert all(not (row["rung"] == "D0"
                        and row["pair_index"] == 52) for row in rows)
        assert not (out / "pairs" / "D0_p52.json").exists()

    def test_g03_slice_rejected_pairs_zero_eval(self, slice_run):
        """八坐标内若再有拒绝:同样零启动 + 完整失败记录。"""
        out, rows = slice_run
        rejected = [row for row in rows if row["status"] == "rejected"]
        for row in rejected:
            doc = json.loads((out / "pairs" / row["detail"]).read_text(
                encoding="utf-8"))
            assert doc["downstream_sentinel"][
                "evaluator_started"] is False
            assert "evaluation" not in doc
            assert doc["n_attempt_envelopes"] == 5
            assert doc["status"] == "rejected"
