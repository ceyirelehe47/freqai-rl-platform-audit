"""R17 C3 工程切片验收矩阵:G01-G03 / R01-R10 / M01 / E01-E03。

对象:r17_c3_engineering_slice.py(八个预声明坐标的真实生成→评估切片
+ p52 拒绝负例下游哨兵 + v2 完整只读语义读回)。

- G 系:生成/评估/哨兵真实链(独立子进程;numpy 原生线程不进 pytest);
- R 系:读回行为矩阵(以已保存真实产物的副本为基底,只改测试副本;
  真实 reader CLI 出口与回执 problems 同源断言);
- M01:有限离散分布条件化/first_pass 穷举(纯数学,不调生成器);
- E 系:证据包语义层(完整隔离冷读在交付验证 run 中执行)。

注:M01 命名与 test_curriculum261_r17_c3_evidence_unit.py 的
TestM01SchedulingAndDP(调度 DP)相互独立,内容不重叠。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
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


def _orig_slice_dir() -> Path:
    cands = []
    if _HERE.parents[2].name == "stage2_6_1":
        cands.append(_HERE.parents[2] / "artifacts" / "repair17"
                     / "development" / "c3_evidence_generation_slice"
                     / "engineering_slice")
    cands.append(Path(
        "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/"
        "development/c3_evidence_generation_slice/engineering_slice"))
    for c in cands:
        if c.is_dir():
            return c
    pytest.skip("原工程切片产物目录不在本机")


_ORIG_SLICE_SHA = "c975dea878f57c853f62f895fff5d3e9f71287f245fc53b760907cb5c94f1b2f"


def _copy_orig(tmp: Path) -> Path:
    dst = tmp / "engineering_slice"
    shutil.copytree(_orig_slice_dir(), dst)
    # 基线身份:健康原件的 p52 负例字节(任务书 §5.1 固定对象)
    assert hashlib.sha256(
        (dst / "p52_negative.json").read_bytes()).hexdigest() == \
        _ORIG_SLICE_SHA
    return dst


def _tree_digest(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = (
                hashlib.sha256(p.read_bytes()).hexdigest(),
                p.stat().st_size)
    return out


def _run_slice(args: list[str],
               timeout: int = 1200) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_src_dir())
    return subprocess.run(
        [sys.executable, str(_slice_script()), *args],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(_src_dir().parent))


def _run_readback(case: Path, report: Path,
                  envelope: Path | None = None,
                  timeout: int = 300) -> subprocess.CompletedProcess:
    return _run_slice(["--readback", str(case),
                       "--p52-envelope", str(envelope or _orig_envelope()),
                       "--report", str(report)], timeout=timeout)


def _load(report: Path) -> dict:
    return json.loads(report.read_text(encoding="utf-8"))


def _checks(doc: dict) -> set:
    return {p["check"] for p in doc["problems"]}


def _rewrite_json(path: Path, fn) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def _resync_row_digest(case: Path, coord: str) -> None:
    """篡改 detail 后同步行内哈希,使字节校验成立(测语义层,不测 digest)。"""
    rows_path = case / "slice_results.jsonl"
    lines = [json.loads(l) for l in rows_path.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    for row in lines:
        if row["coord"] == coord:
            d = case / "pairs" / row["detail"]
            row["detail_sha256"] = hashlib.sha256(
                d.read_bytes()).hexdigest()
    rows_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n",
        encoding="utf-8")


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
        if os.name == "nt":
            pytest.skip("需要 WSL 执行环境")
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
            self, slice_run, tmp_path):
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
        # 新进程完整语义读回(v2:独立回执;源目录零写入)
        receipt = tmp_path / "g02_receipt.json"
        rb = _run_readback(out, receipt, envelope=_orig_envelope())
        assert rb.returncode == 0, rb.stderr
        rdoc = _load(receipt)
        assert rdoc["readback_verdict"] == "PASS"
        assert rdoc["n_problems"] == 0
        # v2 合同:绝不写源目录(旧版会写 readback_report.json)
        assert not (out / "readback_report.json").exists()


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


# ================================================= R 系:读回行为矩阵
_R_ALL = pytest.mark.skipif(os.name == "nt", reason="需要 WSL 执行环境")


@_R_ALL
class TestR01HealthyReadback:
    """已保存原八坐标+p52 健康对照:真实新 reader PASS;源不变;零业务 import。"""

    def test_r01_pass_source_unchanged_no_business_import(self, tmp_path):
        case = _copy_orig(tmp_path)
        before = _tree_digest(case)
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 0, rb.stderr
        doc = _load(receipt)
        assert doc["readback_verdict"] == "PASS"
        assert doc["n_problems"] == 0
        assert doc["checks"]["accepted_coords"] == [
            "D0/p0", "D0/p1", "D1/p0", "D1/p1",
            "D2/p0", "D2/p1", "D3/p0", "D3/p1"]
        assert doc["checks"]["rejected_coords"] == []
        # 源目录前后不变(字节+大小;reader 内部还比了 mtime)
        assert _tree_digest(case) == before
        assert doc["checks"]["source_snapshot_identical"] is True

    def test_r01_readback_path_pure_stdlib(self, tmp_path):
        """读回进程 sys.modules 无 numpy/pandas/rl_curriculum/
        r17_c3_p52_diagnosis:零生成/评估代码被加载。"""
        case = _copy_orig(tmp_path)
        code = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(_slice_script().parent)!r})\n"
            "import r17_c3_engineering_slice as m\n"
            "rc = m.main(['--readback', " + repr(str(case)) +
            ", '--p52-envelope', " + repr(str(_orig_envelope())) +
            ", '--report', " + repr(str(tmp_path / 'r.json')) + "])\n"
            "loaded = sorted(k for k in sys.modules if k.split('.')[0] in "
            "('numpy','pandas','rl_curriculum','r17_c3_p52_diagnosis'))\n"
            "print('RC', rc)\nprint('LOADED', json.dumps(loaded))\n")
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=300,
                           env={k: v for k, v in os.environ.items()
                                if k != "PYTHONPATH"})
        assert r.returncode == 0, r.stderr
        assert "RC 0" in r.stdout
        assert "LOADED []" in r.stdout, r.stdout


@_R_ALL
class TestR02IndexOrder:
    """反转/打乱结果行顺序:非零,明确顺序不一致;不能先排序再通过。"""

    def test_r02_reordered_rows_rejected(self, tmp_path):
        case = _copy_orig(tmp_path)
        rows_path = case / "slice_results.jsonl"
        lines = [l for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        lines[1], lines[2] = lines[2], lines[1]
        rows_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert doc["readback_verdict"] == "FAIL"
        assert "index_order_exact" in _checks(doc)
        # 顺带确认旧 reader 在同副本上会 PASS(缺陷对照,一次性)
        # → 不重跑旧代码;由 stage1_old_reader_probes.json 归档证据承担


@_R_ALL
class TestR03NegativeRequired:
    """删除 p52 文件或 recipe 负例声明:必需负例缺失,非零;
    不降为 not_expected。"""

    def test_r03a_p52_file_deleted(self, tmp_path):
        case = _copy_orig(tmp_path)
        (case / "p52_negative.json").unlink()
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "file_present" in _checks(doc)
        where = [p["where"] for p in doc["problems"]
                 if p["check"] == "file_present"]
        assert any("p52_negative" in w for w in where)

    def test_r03b_recipe_negative_declaration_removed(self, tmp_path):
        case = _copy_orig(tmp_path)
        _rewrite_json(case / "recipe.json",
                      lambda d: d.pop("negative_control", None))
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "recipe_negative_control_required" in _checks(doc)


@_R_ALL
class TestR04P52Variants:
    """p52 意外接受/少条/重复/缺 B/原因错误/evaluator>0:
    各变体均被最终判定拒绝。"""

    def _expect_fail(self, tmp_path, mutate, expected_check):
        case = _copy_orig(tmp_path)
        _rewrite_json(case / "p52_negative.json", mutate)
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1, rb.stdout
        doc = _load(receipt)
        assert doc["readback_verdict"] == "FAIL"
        assert expected_check in _checks(doc), doc["problems"][:3]

    def test_r04_unexpected_acceptance(self, tmp_path):
        self._expect_fail(
            tmp_path, lambda d: d.update(accepted=True), "p52_rejected")

    def test_r04_too_few_envelopes(self, tmp_path):
        def _cut(d):
            d["attempt_envelopes"] = d["attempt_envelopes"][:4]
            d["n_attempt_envelopes"] = 4
        self._expect_fail(tmp_path, _cut, "p52_envelopes_complete")

    def test_r04_duplicate_attempt_index(self, tmp_path):
        def _dup(d):
            d["attempt_envelopes"][3]["attempt_index"] = 2
        self._expect_fail(tmp_path, _dup, "p52_envelopes_complete")

    def test_r04_missing_B_event_table(self, tmp_path):
        def _nob(d):
            d["attempt_envelopes"][0]["event_table"].pop("B")
        self._expect_fail(tmp_path, _nob, "p52_env_event_table_sides")

    def test_r04_wrong_reasons_vs_original(self, tmp_path):
        def _wrong(d):
            d["attempt_envelopes"][2]["rejection_reasons"] = [
                "A:too_few_signals", "B:too_few_signals",
                "pair:too_few_signals"]
        self._expect_fail(tmp_path, _wrong,
                          "p52_reasons_match_original")

    def test_r04_evaluator_nonzero(self, tmp_path):
        def _ev(d):
            d["downstream_sentinel"]["evaluator_started"] = True
            d["downstream_sentinel"]["evaluator_invocations"] = 2
        self._expect_fail(tmp_path, _ev, "p52_evaluator_zero")


@_R_ALL
class TestR05CrossCoordDetail:
    """D1/p0 指向 D0/p0 的详情及其正确哈希:哈希校验可成立,
    身份关系仍失败;指明两个坐标。"""

    def test_r05_cross_reference_rejected(self, tmp_path):
        case = _copy_orig(tmp_path)
        _resync_row_digest(case, "D1/p0")  # 先确保基线哈希正确
        rows_path = case / "slice_results.jsonl"
        lines = [json.loads(l) for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        for row in lines:
            if row["coord"] == "D1/p0":
                row["detail"] = "D0_p0.json"
                row["detail_sha256"] = hashlib.sha256(
                    (case / "pairs" / "D0_p0.json").read_bytes()
                ).hexdigest()
        rows_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in lines) + "\n", encoding="utf-8")
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        # 字节哈希成立(checks 里 digest=True),身份关系失败
        assert doc["checks"]["detail_digest"]["D1/p0@line3"] is True
        probs = [p for p in doc["problems"]
                 if p["check"] == "detail_identity_cross_coord"]
        assert probs and probs[0]["expected"] == "pairs/D1_p0.json" \
            and probs[0]["actual"] == "pairs/D0_p0.json"


@_R_ALL
class TestR06ContractSubstitution:
    """namespace/family/请求被替换;重复或少坐标;同时改 recipe
    不能授权第九坐标。"""

    def test_r06_rung_substituted(self, tmp_path):
        case = _copy_orig(tmp_path)

        def _sub(d):
            d["requests"][2]["rung"] = "D4"
        _rewrite_json(case / "recipe.json", _sub)
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "recipe_requests_match_authorization" in _checks(doc)

    def test_r06_duplicate_coordinate_in_index(self, tmp_path):
        case = _copy_orig(tmp_path)
        rows_path = case / "slice_results.jsonl"
        lines = [l for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        dup = json.loads(lines[1])
        dup["coord"] = "D0/p0"
        dup["rung"], dup["pair_index"] = "D0", 0
        lines[2] = json.dumps(dup, ensure_ascii=False)
        rows_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "index_no_duplicate" in _checks(doc)

    def test_r06_row_missing(self, tmp_path):
        case = _copy_orig(tmp_path)
        rows_path = case / "slice_results.jsonl"
        lines = [l for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        del lines[7]
        rows_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "index_order_exact" in _checks(doc)

    def test_r06_recipe_and_index_cannot_authorize_ninth(self, tmp_path):
        case = _copy_orig(tmp_path)

        def _add(d):
            d["requests"].append(
                {"namespace": d["namespace"], "family": d["family"],
                 "rung": "D4", "pair_index": 0})
            d["n_requests"] = 9
        _rewrite_json(case / "recipe.json", _add)
        rows_path = case / "slice_results.jsonl"
        with rows_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "coord": "D4/p0", "namespace": "preplan_calibration_main_r17",
                "family": "c3_cost", "rung": "D4", "pair_index": 0,
                "status": "rejected", "selected_attempt": None,
                "n_attempt_envelopes": 5,
                "detail": "D4_p0.json",
                "detail_sha256": "0" * 64}) + "\n")
        _rewrite_json(case / "slice_summary.json",
                      lambda d: d.update(n_requests=9))
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        cs = _checks(doc)
        assert "recipe_requests_match_authorization" in cs
        assert "index_order_exact" in cs


@_R_ALL
class TestR07EvaluationSemantics:
    """详情 A/B 混侧、重复 side、episode 哈希错配、无效 integrity/
    非有限结果:实际语义读回非零;不以任意非空 episodes 视为完整。"""

    def _expect_fail(self, tmp_path, coord, mutate, expected_check):
        case = _copy_orig(tmp_path)
        detail = case / "pairs" / f"{coord.replace('/', '_')}.json"
        _rewrite_json(detail, mutate)
        _resync_row_digest(case, coord)
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1, rb.stdout
        doc = _load(receipt)
        assert doc["readback_verdict"] == "FAIL"
        assert expected_check in _checks(doc), doc["problems"][:3]

    def test_r07_duplicate_side(self, tmp_path):
        def _dup(d):
            d["evaluation"]["episodes"][1]["side"] = "A"
        self._expect_fail(tmp_path, "D0/p1", _dup,
                          "evaluation_sides_exact_AB")

    def test_r07_episode_hash_mismatch(self, tmp_path):
        def _bad_hash(d):
            d["evaluation"]["episodes"][0]["episode_hash"] = \
                "ce-tampered0000"
        self._expect_fail(tmp_path, "D0/p1", _bad_hash,
                          "evaluation_episode_hash_binding")

    def test_r07_integrity_contradiction(self, tmp_path):
        def _bad_int(d):
            d["integrity_ok"] = False
            d["integrity"]["pass"] = False
        self._expect_fail(tmp_path, "D1/p0", _bad_int,
                          "accepted_integrity_ok_consistent")

    def test_r07_nonfinite_policy_result(self, tmp_path):
        def _nan(d):
            d["evaluation"]["episodes"][0]["oracle"] = float("nan")
        self._expect_fail(tmp_path, "D1/p1", _nan,
                          "evaluation_policy_finite")


@_R_ALL
class TestR08AttemptFacts:
    """attempt 数量/顺序/selected/接受状态或 recorder 事实矛盾:
    实际条目而非单一计数字段决定完整性。"""

    def _expect_fail(self, tmp_path, coord, mutate, expected_check):
        case = _copy_orig(tmp_path)
        detail = case / "pairs" / f"{coord.replace('/', '_')}.json"
        _rewrite_json(detail, mutate)
        _resync_row_digest(case, coord)
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1, rb.stdout
        doc = _load(receipt)
        assert doc["readback_verdict"] == "FAIL"
        assert expected_check in _checks(doc), doc["problems"][:3]

    def test_r08_attempt_indices_duplicated(self, tmp_path):
        def _dup(d):
            log = d["pair_record"]["attempt_log"]
            log["attempts"][0]["index"] = 1
        self._expect_fail(tmp_path, "D2/p0", _dup,
                          "accepted_attempts_sequence")

    def test_r08_selected_beyond_attempts(self, tmp_path):
        def _sel(d):
            d["pair_record"]["attempt_log"]["selected_attempt"] = 3
        self._expect_fail(tmp_path, "D2/p1", _sel,
                          "accepted_attempts_sequence")

    def test_r08_selected_attempt_not_accepted(self, tmp_path):
        def _acc(d):
            d["pair_record"]["attempt_log"]["attempts"][0][
                "accepted"] = False
        self._expect_fail(tmp_path, "D3/p0", _acc,
                          "accepted_attempt_gate")

    def test_r08_recorder_error_facts(self, tmp_path):
        def _rec(d):
            d["recorder_errors"] = ["record_failed"]
        self._expect_fail(tmp_path, "D3/p1", _rec,
                          "detail_recorder_errors_empty")

    def test_r08_envelope_accepted_contradiction(self, tmp_path):
        def _env(d):
            d["attempt_envelopes"][0]["accepted"] = False
        self._expect_fail(tmp_path, "D0/p0", _env,
                          "accepted_env_selected_true")


@_R_ALL
class TestR09MalformedInputs:
    """缺件、坏 JSON、未知状态、逃逸 payload 的引用:无 PASS、无补算、
    无覆盖原件;回执或 stderr 保留精确失败位置。"""

    def test_r09_recipe_missing(self, tmp_path):
        case = _copy_orig(tmp_path)
        (case / "recipe.json").unlink()
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "file_present" in _checks(doc)

    def test_r09_detail_bad_json(self, tmp_path):
        case = _copy_orig(tmp_path)
        (case / "pairs" / "D0_p1.json").write_text(
            "{broken", encoding="utf-8")
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "json_parseable" in _checks(doc)
        where = [p["where"] for p in doc["problems"]
                 if p["check"] == "json_parseable"]
        assert any("D0/p1" in w for w in where)

    def test_r09_unknown_status(self, tmp_path):
        case = _copy_orig(tmp_path)
        rows_path = case / "slice_results.jsonl"
        lines = [json.loads(l) for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        lines[4]["status"] = "pending"
        rows_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in lines) + "\n", encoding="utf-8")
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "index_status_known" in _checks(doc)

    def test_r09_escaping_detail_ref(self, tmp_path):
        case = _copy_orig(tmp_path)
        rows_path = case / "slice_results.jsonl"
        lines = [json.loads(l) for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        lines[6]["detail"] = "../p52_negative.json"
        rows_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in lines) + "\n", encoding="utf-8")
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        assert "detail_ref_safe" in _checks(doc)
        # 逃逸引用未被读取(源内 p52 文件未被当作 D2/p2 详情消费)
        assert (case / "p52_negative.json").is_file()

    def test_r09_no_source_mutation_and_receipt_preserved(
            self, tmp_path):
        """读回失败也不补算/不覆盖源(含历史 readback_report.json)。"""
        case = _copy_orig(tmp_path)
        old_report = case / "readback_report.json"
        old_bytes = old_report.read_bytes()
        before = _tree_digest(case)
        (case / "pairs" / "D1_p1.json").unlink()  # 制造缺件
        after_del = _tree_digest(case)
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        # 读回自身零写入:删件后的快照保持不变,历史回执原样
        assert _tree_digest(case) == after_del
        assert old_report.read_bytes() == old_bytes
        assert before != after_del  # (删除是我们做的,非 reader 行为)


# ================================================= R10 负例命令出口
@_R_ALL
class TestR10NegativeExitInjection:
    """主 CLI 的 p52 意外接受/未预期异常出口:注入后真实主流程非零
    并保存真实结果;零 evaluator 由连接的执行路径证明。"""

    def _driver(self, tmp_path, gen_behavior):
        """真实 main 控制流 + 故障注入(生成 API 层),八坐标 stub 掉。"""
        out = tmp_path / "slice"
        code = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(_src_dir())!r})\n"
            f"sys.path.insert(0, {str(_slice_script().parent)!r})\n"
            "import rl_curriculum.curriculum261_api as api\n"
            "import rl_curriculum.curriculum261_qualification as qual\n"
            "calls = {'eval': 0}\n"
            "def fake_eval(*a, **k):\n"
            "    calls['eval'] += 1\n"
            "    raise AssertionError('evaluator must not run')\n"
            "qual.evaluate_pair_corpus = fake_eval\n"
            f"GEN_BEHAVIOR = {gen_behavior!r}\n"
            "if GEN_BEHAVIOR is not None:\n"
            "    def fake_gen(*a, **k):\n"
            "        if GEN_BEHAVIOR == 'accept':\n"
            "            return None\n"
            "        raise RuntimeError('injected unexpected')\n"
            "    api.generate_pair_with_attempts = fake_gen\n"
            "import r17_c3_engineering_slice as m\n"
            "m.run_slice = lambda d: {'n_accepted': 0, 'n_rejected': 8,"
            " 'n_requests': 8}\n"
            "rc = m.main(['--out-dir', " + repr(str(out)) +
            ", '--p52-negative', " + repr(str(_orig_envelope())) + "])\n"
            "print('RC', rc)\n"
            "print('EVAL_CALLS', calls['eval'])\n")
        r = subprocess.run(
            [sys.executable, "-c", code], capture_output=True,
            text=True, timeout=300,
            cwd=str(_src_dir().parent))
        return r, out

    def test_r10_injected_acceptance_nonzero_and_saved(self, tmp_path):
        r, out = self._driver(tmp_path, "accept")
        assert r.returncode == 0, r.stderr  # driver 自身正常结束
        assert "RC 4" in r.stdout, r.stdout + r.stderr
        assert "EVAL_CALLS 0" in r.stdout
        neg = json.loads((out / "p52_negative.json").read_text(
            encoding="utf-8"))
        assert neg["accepted"] is True          # 真实结果被保存
        summ = json.loads((out / "slice_summary.json").read_text(
            encoding="utf-8"))
        assert summ["p52_negative_evidence_ok"] is False
        assert summ["p52_negative_problems"]

    def test_r10_injected_unexpected_exception_nonzero(self, tmp_path):
        r, out = self._driver(tmp_path, "raise")
        assert r.returncode == 0, r.stderr
        assert "RC 4" in r.stdout, r.stdout + r.stderr
        neg = json.loads((out / "p52_negative.json").read_text(
            encoding="utf-8"))
        assert "unexpected_exception" in neg
        assert neg["unexpected_exception"]["error_type"] == "RuntimeError"

    def test_r10_real_rejection_still_zero(self, tmp_path):
        """不注入时(真实 PairGenerationError)同一 main 路径 rc=0。"""
        r, out = self._driver(tmp_path, None)
        assert r.returncode == 0, r.stderr
        assert "RC 0" in r.stdout, r.stdout + r.stderr
        neg = json.loads((out / "p52_negative.json").read_text(
            encoding="utf-8"))
        assert neg["accepted"] is False


# ================================================= M01 有限离散穷举
class TestM01FiniteDistribution:
    """有限离散分布与最多五次 first_pass 穷举:条件分布归一化为 1,
    成功条件输出等于 P(X|S);错误 1/q 示例不成立。纯数学,不调生成器。"""

    #: 8 结果样本空间与概率(手选非退化值)
    P = [0.10, 0.20, 0.05, 0.15, 0.10, 0.20, 0.10, 0.10]
    #: S=全部结构通过;D=至少一个 distractor(以结果下标集合定义)
    S = {1, 2, 3, 4, 5}
    D = {2, 3, 4, 5, 6}
    A = {1, 2, 3}          # 任意目标事件(与 S/D 部分相交)
    M = 5

    def _p(self, ev) -> float:
        return sum(self.P[i] for i in ev)

    def test_m01_conditioning_on_D(self):
        """P(X∈A|D)=P(A∩D)/(1-q),1/(1-q) 归一化;1/q 不成立。"""
        q = self._p(set(range(8)) - self.D)   # P(D 的补集)
        assert q == 1.0 - self._p(self.D)
        want = self._p(self.A & self.D) / (1 - q)
        # 穷举:在 D 上逐结果归一化
        got = sum(self.P[i] for i in self.A & self.D) / sum(
            self.P[i] for i in self.D)
        assert abs(want - got) < 1e-12
        # D 上条件分布归一化为 1
        assert abs(sum(self.P[i] / (1 - q) for i in self.D) - 1.0) < 1e-12
        # 错误示例:P(A∩D)/q ≠ P(A|D)(本例数值上确不相等)
        wrong = self._p(self.A & self.D) / q
        assert abs(wrong - want) > 1e-6

    def test_m01_first_pass_exhaustive(self):
        """穷举 8^5 序列:P(X_J∈A|J≤m)=P(A∩S)/p 等公式逐项吻合。"""
        p = self._p(self.S)
        # 穷举全部候选序列(X_1..X_5 iid),统计 (J≤m, X_J∈A)
        n_total = n_pass = n_pass_and_A = 0
        weight_total = weight_pass = weight_pass_A = 0.0

        def rec(depth, started, weight, j_outcome):
            nonlocal n_total, n_pass, n_pass_and_A
            nonlocal weight_total, weight_pass, weight_pass_A
            if depth == self.M:
                n_total += 1
                weight_total += weight
                if j_outcome is not None:
                    n_pass += 1
                    weight_pass += weight
                    if j_outcome in self.A:
                        n_pass_and_A += 1
                        weight_pass_A += weight
                return
            for i in range(8):
                in_S = i in self.S
                takes = (j_outcome is None) and in_S
                rec(depth + 1, True, weight * self.P[i],
                    i if takes else j_outcome)

        rec(0, False, 1.0, None)
        assert n_total == 8 ** self.M
        assert abs(weight_total - 1.0) < 1e-9
        # P(J≤m) = 1-(1-p)^m
        assert abs(weight_pass - (1 - (1 - p) ** self.M)) < 1e-12
        # P(X_J∈A, J≤m) = Σ_j (1-p)^(j-1) P(A∩S)
        want_joint = sum((1 - p) ** j * self._p(self.A & self.S)
                         for j in range(self.M))
        assert abs(weight_pass_A - want_joint) < 1e-12
        # P(X_J∈A | J≤m) = P(A∩S)/p
        assert abs(weight_pass_A / weight_pass
                   - self._p(self.A & self.S) / p) < 1e-12

    def test_m01_success_output_distribution(self):
        """成功输出分布 P(X|S) 归一化为 1;first_pass 输出与其一致。"""
        p = self._p(self.S)
        cond = {i: self.P[i] / p for i in self.S}
        assert abs(sum(cond.values()) - 1.0) < 1e-12
        # first_pass 成功输出分布 = P(X|S)(上面已证比例),逐值复核
        for i in self.S:
            # P(X_J=i | J≤m) = P(X=i 且 i∈S)/p(穷举恒等式)
            assert cond[i] == self.P[i] / p

    def test_m01_boundaries(self):
        """p=0 无成功条件分布(条件事件零概率);p=1 首次即通过。"""
        # p=0:S 为空 → P(J≤m)=0,条件分布未定义(不能写 0/0)
        empty_S = set()
        assert self._p(empty_S) == 0.0
        # p=1:S 全空间 → J=1 恒成立
        full_S = set(range(8))
        p = self._p(full_S)
        assert abs(p - 1.0) < 1e-12
        assert abs((1 - (1 - p) ** self.M) - 1.0) < 1e-12
        # P(X_J∈A|J≤m) = P(A∩S)/p = P(A)
        assert abs(self._p(self.A & full_S) / p - self._p(self.A)) < 1e-12


# ================================================= E 系:证据包语义层
@_R_ALL
class TestE0xEvidencePackage:
    """E01-E03:现存 C3 包语义层验证(完整隔离冷读在交付验证 run)。"""

    def test_e01_full_package_semantic_readback(self, tmp_path):
        """完整现存包+新 reader:字节与语义均过;验证零生成、
        源与 payload 前后不变。"""
        case = _copy_orig(tmp_path)
        # p52 负例与原 envelope 逐条对照(固定来源)
        before = _tree_digest(case)
        receipt = tmp_path / "pkg_receipt.json"
        rb = _run_readback(case, receipt, envelope=_orig_envelope())
        assert rb.returncode == 0, rb.stderr
        doc = _load(receipt)
        assert doc["readback_verdict"] == "PASS"
        assert doc["checks"]["source_snapshot_identical"] is True
        assert _tree_digest(case) == before  # reader 输入(切片包)不变

    def test_e02_missing_key_files_fail_with_reason(self, tmp_path):
        # 缺件各自由其所在层拒绝:索引引用层用 detail_present,
        # 顶层输入用 file_present;都给出精确位置
        for victim, want in (("p52_negative.json", "file_present"),
                             ("pairs/D1_p1.json", "detail_present"),
                             ("slice_summary.json", "file_present")):
            case = _copy_orig(tmp_path / victim.replace("/", "_"))
            (case / victim).unlink()
            receipt = tmp_path / f"r_{victim.replace('/', '_')}.json"
            rb = _run_readback(case, receipt)
            assert rb.returncode == 1, victim
            doc = _load(receipt)
            assert want in _checks(doc), (victim, doc["problems"][:3])

    def test_e02_tampered_bytes_fail(self, tmp_path):
        case = _copy_orig(tmp_path)
        # 篡改 detail 一个字节且不同步行哈希:字节校验失败
        d = case / "pairs" / "D0_p0.json"
        raw = bytearray(d.read_bytes())
        raw[-10] ^= 0x01
        d.write_bytes(bytes(raw))
        receipt = tmp_path / "receipt.json"
        rb = _run_readback(case, receipt)
        assert rb.returncode == 1
        doc = _load(receipt)
        cs = _checks(doc)
        assert "detail_digest" in cs or "json_parseable" in cs

    def test_e03_mismatch_copy_and_outside_receipt(self, tmp_path):
        """独立语义错配副本:reader 拒绝;健康回执目录在包外,
        旧 readback_report.json 不被覆盖。"""
        case = _copy_orig(tmp_path)
        # 语义错配(R05 同款)+哈希自洽(证明不是外层哈希失败冒充)
        rows_path = case / "slice_results.jsonl"
        lines = [json.loads(l) for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        for row in lines:
            if row["coord"] == "D1/p0":
                row["detail"] = "D0_p0.json"
                row["detail_sha256"] = hashlib.sha256(
                    (case / "pairs" / "D0_p0.json").read_bytes()
                ).hexdigest()
        rows_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in lines) + "\n", encoding="utf-8")
        old_report = case / "readback_report.json"
        old_bytes = old_report.read_bytes()
        outside = tmp_path / "outside_receipts" / "r.json"
        rb = _run_readback(case, outside)
        assert rb.returncode == 1
        doc = _load(outside)
        assert "detail_identity_cross_coord" in _checks(doc)
        assert doc["checks"]["detail_digest"]["D1/p0@line3"] is True
        # 旧回执原样(包外新回执;源零写入)
        assert old_report.read_bytes() == old_bytes


# ============================== v3:身份绑定(I)与回执写入隔离(P)
def _tree_stat(root: Path) -> dict:
    """源树状态(sha256,size,mtime_ns)——P 系断言零源写入用。"""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (
                hashlib.sha256(p.read_bytes()).hexdigest(),
                st.st_size, st.st_mtime_ns)
    return out


def _authority():
    """生产权威 digest 实现(部署树/发布树 src;独立于 reader 薄适配)。"""
    src = _src_dir()
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from rl_curriculum.curriculum261_generation_envelope import (
            canonical_json, stable_digest, _digest_body as auth_body,
            ENVELOPE_DIGEST_PREFIX, CALL_ENVELOPE_DIGEST_PREFIX)
    except ImportError as exc:
        pytest.skip(f"权威模块不可用(需生产环境): {exc}")
    return (canonical_json, stable_digest, auth_body,
            ENVELOPE_DIGEST_PREFIX, CALL_ENVELOPE_DIGEST_PREFIX)


class TestC01CanonicalAdapterVsAuthority:
    """薄适配与生产权威函数逐对象对照(同进程;序列化边界+真实旧件)。"""

    def _objs(self):
        nan = float("nan")
        inf = float("inf")
        return [
            None, True, False, 0, 1, -7, 3.5, 1e300, "ascii", "中文🚀",
            [], {}, [1, "a", None, [2.5]], {"b": 1, "a": {"x": [1, 2]}},
            {"__sorted_set__": ["a", "b"]},
            {"f": nan}, {"g": inf}, {"h": -inf},
            {"deep": [{"nested": [[{"k": "v"}]]}]},
        ]

    def test_canonical_text_matches_authority(self, slice_mod):
        canonical_json, _, _, _, _ = _authority()
        for obj in self._objs():
            auth = canonical_json(obj)
            mine = slice_mod._canonical_json_text(obj)
            assert mine == auth, obj
            assert mine == slice_mod._canonical_json_text(
                json.loads(json.dumps(obj))), obj

    def test_digest_matches_authority_on_real_envelopes(self, tmp_path,
                                                        slice_mod):
        """健康旧件真实 envelope:薄适配复算==权威 stable_digest。"""
        canonical_json, stable_digest, auth_body, env_prefix, _ = _authority()
        case = _copy_orig(tmp_path)
        doc = json.loads((case / "pairs" / "D0_p0.json").read_text(
            encoding="utf-8"))
        for e in doc["attempt_envelopes"]:
            body = slice_mod._digest_body(e)
            assert slice_mod._canonical_json_text(body) == canonical_json(
                auth_body(e))
            assert slice_mod._recompute_envelope_digest(e) == stable_digest(
                auth_body(e), env_prefix)
            assert slice_mod._recompute_envelope_digest(e) == e["digest"]

    def test_non_json_type_rejected(self, slice_mod):
        with pytest.raises(TypeError):
            slice_mod._canonical_json_text({1, 2})

    def test_runtime_excluded_from_digest(self, tmp_path, slice_mod):
        """runtime 是非身份字段:改动不影响复算(不伪装成业务身份)。"""
        case = _copy_orig(tmp_path)
        p = case / "pairs" / "D0_p0.json"
        _rewrite_json(p, lambda d: d["attempt_envelopes"][0][
            "runtime"].update(pythonhashseed="<tampered-env>"))
        doc = json.loads(p.read_text(encoding="utf-8"))
        e = doc["attempt_envelopes"][0]
        assert slice_mod._recompute_envelope_digest(e) == e["digest"]


class TestI01HealthReadbackV3:
    """I01:健康原件在新 reader 下 PASS;新增检查全 True;旧回归仍拒。"""

    def test_health_pass_with_identity_checks(self, tmp_path):
        case = _copy_orig(tmp_path)
        before = _tree_stat(case)
        report = tmp_path / "receipts" / "health.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 0, rb.stderr
        doc = _load(report)
        assert doc["readback_verdict"] == "PASS"
        assert doc["format"] == "r17-c3-engineering-slice-readback-v5"
        # 八坐标每条 envelope digest 复算全 True
        for where, ok in doc["checks"]["envelope_digest"].items():
            assert ok is True, where
        # p52 身份体五条全 True
        for env_i, ok in doc["checks"]["p52_identity_body"].items():
            assert ok is True, env_i
        assert doc["checks"]["p52_orig_call_digest_recomputed"] is True
        assert doc["report_target_admission"]["admitted"] is True
        assert _tree_stat(case) == before

    def test_old_regressions_still_rejected(self, tmp_path):
        """乱序索引/缺 p52 负例/跨坐标引用在 v3 仍拒绝。"""
        # 乱序
        case = _copy_orig(tmp_path / "a")
        p = case / "slice_results.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        lines[0], lines[1] = lines[1], lines[0]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rb = _run_readback(case, tmp_path / "r1.json")
        assert rb.returncode == 1
        assert "index_order_exact" in _checks(_load(tmp_path / "r1.json"))
        # 缺负例
        case = _copy_orig(tmp_path / "b")
        (case / "p52_negative.json").unlink()
        rb = _run_readback(case, tmp_path / "r2.json")
        assert rb.returncode == 1
        assert "file_present" in _checks(_load(tmp_path / "r2.json"))
        # 跨坐标引用(哈希自洽)
        case = _copy_orig(tmp_path / "c")
        rows_path = case / "slice_results.jsonl"
        rows = [json.loads(l) for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        for row in rows:
            if row["coord"] == "D1/p0":
                row["detail"] = "D0_p0.json"
                row["detail_sha256"] = hashlib.sha256(
                    (case / "pairs" / "D0_p0.json").read_bytes()).hexdigest()
        rows_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in rows) + "\n", encoding="utf-8")
        rb = _run_readback(case, tmp_path / "r3.json")
        assert rb.returncode == 1
        assert "detail_identity_cross_coord" in _checks(
            _load(tmp_path / "r3.json"))


class TestI02DownstreamSelfConsistent:
    """I02:三下游(top/log/eval)一起改、selected envelope 不动——
    三个下游互相自洽仍不足以通过(必须在 selected 输出关系处失败)。"""

    def test_all_three_layers_changed_fails(self, tmp_path):
        case = _copy_orig(tmp_path)
        new_h = {s: "ce-" + hashlib.sha256(f"i02-{s}".encode()).hexdigest()
                 for s in ("A", "B")}

        def tweak(doc):
            doc["episode_hashes"] = dict(new_h)
            doc["pair_record"]["attempt_log"][
                "output_episode_hashes"] = dict(new_h)
            for ep in doc["evaluation"]["episodes"]:
                ep["episode_hash"] = new_h[ep["side"]]

        _rewrite_json(case / "pairs" / "D0_p0.json", tweak)
        _resync_row_digest(case, "D0/p0")
        report = tmp_path / "receipts" / "i02.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        cs = _checks(_load(report))
        assert "selected_envelope_output_binding" in cs
        # detail 层外层哈希与三处下游自洽均不构成拒绝依据
        doc = _load(report)
        assert doc["checks"]["detail_digest"]["D0/p0@line1"] is True


class TestI03SelectedEnvelopeDigestValid:
    """I03:selected envelope 输出改动且 digest 权威重算、下游原值——
    内部摘要有效不等于跨层语义正确。"""

    def test_selected_envelope_tampered_digest_valid(self, tmp_path):
        _, stable_digest, auth_body, env_prefix, _ = _authority()
        case = _copy_orig(tmp_path)

        def tweak(doc):
            env = doc["attempt_envelopes"][0]
            env["event_table"]["A"]["episode_content_hash"] = (
                "ce-" + hashlib.sha256(b"i03-tampered").hexdigest())
            env["digest"] = stable_digest(auth_body(env), env_prefix)

        _rewrite_json(case / "pairs" / "D0_p0.json", tweak)
        _resync_row_digest(case, "D0/p0")
        report = tmp_path / "receipts" / "i03.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        cs = _checks(doc)
        assert "selected_envelope_output_binding" in cs
        # digest 本身复算仍通过(证明不是 digest 检查在拦截)
        assert doc["checks"]["envelope_digest"]["D0/p0@line1:env0"] is True


class TestI04EnvelopeDigestRecompute:
    """I04:digest 缺失/乱值/body 改不更新——由真实 canonical 复算拒绝;
    runtime 中性变化不误判。"""

    def _run(self, tmp_path, name, tweak):
        case = _copy_orig(tmp_path / name)
        _rewrite_json(case / "pairs" / "D0_p0.json", tweak)
        _resync_row_digest(case, "D0/p0")
        report = tmp_path / "receipts" / f"{name}.json"
        rb = _run_readback(case, report)
        return rb, _load(report)

    def test_digest_missing(self, tmp_path):
        rb, doc = self._run(tmp_path, "a", lambda d: d[
            "attempt_envelopes"][0].pop("digest"))
        assert rb.returncode == 1
        assert "envelope_digest_recompute" in _checks(doc)

    def test_digest_wrong_value(self, tmp_path):
        rb, doc = self._run(tmp_path, "b", lambda d: d[
            "attempt_envelopes"][0].update(
            digest="r11env-" + "0" * 64))
        assert rb.returncode == 1
        assert "envelope_digest_recompute" in _checks(doc)

    def test_body_changed_without_digest_update(self, tmp_path):
        rb, doc = self._run(tmp_path, "c", lambda d: d[
            "attempt_envelopes"][0].update(internal_derived_seed=999999))
        assert rb.returncode == 1
        assert "envelope_digest_recompute" in _checks(doc)

    def test_runtime_change_neutral(self, tmp_path):
        """仅 runtime 差异:digest 复算 match,整体仍 PASS。"""
        rb, doc = self._run(tmp_path, "d", lambda d: d[
            "attempt_envelopes"][0]["runtime"].update(
            pythonhashseed="<other-env>"))
        assert rb.returncode == 0, rb.stderr
        assert doc["readback_verdict"] == "PASS"
        assert doc["checks"]["envelope_digest"]["D0/p0@line1:env0"] is True


class TestI05P52InnerIdentitySwap:
    """I05:p52 顶层正确、内层换 namespace/seed 且 digest 自洽、
    原因不变——与固定原件身份不符,非零拒绝。"""

    def test_inner_identity_swap_rejected(self, tmp_path):
        _, stable_digest, auth_body, env_prefix, _ = _authority()
        case = _copy_orig(tmp_path)

        def tweak(doc):
            env = doc["attempt_envelopes"][0]
            env["namespace"] = "rt3_calibration_main_r18"
            env["seed_derivation_fields"]["namespace"] = \
                "rt3_calibration_main_r18"
            env["outer_seed"] = int(env["outer_seed"]) + 1
            env["digest"] = stable_digest(auth_body(env), env_prefix)

        _rewrite_json(case / "p52_negative.json", tweak)
        report = tmp_path / "receipts" / "i05.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        cs = _checks(doc)
        assert "p52_identity_body_match_original" in cs
        # 顶层坐标与拒绝词表均未变(不是那些检查在拦截)
        assert "p52_coordinates" not in cs
        assert "p52_reasons_match_original" not in cs
        # 换身份的 digest 自洽:双侧复算通过
        assert doc["checks"]["p52_identity_body"]["env0"] is False
        prob = [p for p in doc["problems"] if p["check"] ==
                "p52_identity_body_match_original"][0]
        assert "namespace" in prob["actual"]["diff_fields"]
        assert "outer_seed" in prob["actual"]["diff_fields"]

    def test_wrong_seeds_same_reasons_rejected(self, tmp_path):
        """五条 envelope 全部换 seed、digest 自洽、原因不变:仍拒绝。"""
        _, stable_digest, auth_body, env_prefix, _ = _authority()
        case = _copy_orig(tmp_path)

        def tweak(doc):
            for i, env in enumerate(doc["attempt_envelopes"]):
                env["internal_derived_seed"] = (
                    int(env["internal_derived_seed"]) + 1000 + i)
                env["digest"] = stable_digest(auth_body(env), env_prefix)

        _rewrite_json(case / "p52_negative.json", tweak)
        report = tmp_path / "receipts" / "i05b.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        assert "p52_identity_body_match_original" in _checks(_load(report))


class TestI06ParamsGeneratorBinding:
    """I06:课程参数/generator 身份与既有来源绑定;健康合法展开不误拒。"""

    def _run(self, tmp_path, name, recipe_tweak=None, detail_tweak=None):
        case = _copy_orig(tmp_path / name)
        if recipe_tweak is not None:
            _rewrite_json(case / "recipe.json", recipe_tweak)
        if detail_tweak is not None:
            _rewrite_json(case / "pairs" / "D0_p0.json", detail_tweak)
            _resync_row_digest(case, "D0/p0")
        report = tmp_path / "receipts" / f"{name}.json"
        rb = _run_readback(case, report)
        return rb, _load(report)

    def test_generator_identity_changed(self, tmp_path):
        rb, doc = self._run(
            tmp_path, "a",
            recipe_tweak=lambda r: r["generator_identity"].update(
                fingerprint="tampered"))
        assert rb.returncode == 1
        assert "envelope_generator_matches_recipe" in _checks(doc)

    def test_rung_params_changed(self, tmp_path):
        rb, doc = self._run(
            tmp_path, "b",
            recipe_tweak=lambda r: r["rung_params"]["D0"].update(
                alpha_bps=71.0))
        assert rb.returncode == 1
        assert "envelope_base_params_matches_rung" in _checks(doc)

    def test_base_params_side_removed(self, tmp_path):
        rb, doc = self._run(
            tmp_path, "c",
            detail_tweak=lambda d: d["attempt_envelopes"][0][
                "base_params"].pop("A"))
        assert rb.returncode == 1
        assert "envelope_base_params_present" in _checks(doc)

    def test_output_hash_removed(self, tmp_path):
        rb, doc = self._run(
            tmp_path, "d",
            detail_tweak=lambda d: d.pop("episode_hashes"))
        assert rb.returncode == 1
        cs = _checks(doc)
        # 顶层缺失:既有缺失检查 + 以 selected envelope 为锚的绑定失败
        # (selected 侧输出仍在,缺的是下游层,报 binding 而非 present)
        assert "episode_hash_present" in cs
        assert "selected_envelope_output_binding" in cs

    def test_legitimate_expansion_not_rejected(self, tmp_path):
        """健康 A/B 合法展开(base_params 含 rung 之外附加键)不误拒。"""
        case = _copy_orig(tmp_path / "e")
        report = tmp_path / "receipts" / "e.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 0, rb.stderr
        doc = _load(report)
        cs = _checks(doc)
        assert not {"envelope_generator_matches_recipe",
                    "envelope_base_params_matches_rung",
                    "envelope_base_params_present"} & cs


class TestP01ReportInsideSource:
    """P01:--report 指向源内文件(历史回执/recipe/新嵌套)——CLI 与
    直接函数都在写入前拒绝;进程退出后源集合/字节/mtime 不变。"""

    def test_report_hits_historical_receipt(self, tmp_path):
        case = _copy_orig(tmp_path)
        target = case / "readback_report.json"
        before = _tree_stat(case)
        rb = _run_readback(case, target)
        assert rb.returncode == 2
        assert _tree_stat(case) == before
        assert not any(p.name.endswith(".tmp")
                       for p in case.rglob("*") if p.is_file())

    def test_report_hits_recipe(self, tmp_path):
        case = _copy_orig(tmp_path)
        target = case / "recipe.json"
        before = _tree_stat(case)
        rb = _run_readback(case, target)
        assert rb.returncode == 2
        assert _tree_stat(case) == before

    def test_report_new_nested_file_in_source(self, tmp_path):
        case = _copy_orig(tmp_path)
        target = case / "nested" / "new" / "report.json"
        before = _tree_stat(case)
        rb = _run_readback(case, target)
        assert rb.returncode == 2
        assert _tree_stat(case) == before

    def test_direct_function_call_rejected(self, tmp_path, slice_mod):
        case = _copy_orig(tmp_path)
        with pytest.raises(slice_mod.ReportTargetRejected):
            slice_mod.readback(case, case / "recipe.json",
                               _orig_envelope())


class TestP02ReportOverlapsInputs:
    """P02:report 与源树外 p52 依据等输入重合;相对路径/链接/别名。"""

    def test_report_equals_p52_envelope_input(self, tmp_path):
        case = _copy_orig(tmp_path)
        target = _orig_envelope()
        before_bytes = target.read_bytes()
        rb = _run_readback(case, target)
        assert rb.returncode == 2
        assert target.read_bytes() == before_bytes

    def test_report_sibling_of_p52_input_allowed(self, tmp_path):
        """p52 依据是文件级保护:同目录新文件不与输入本身重合
        (保护集精确不过宽;用副本验证,不写旧 run 目录)。"""
        case = _copy_orig(tmp_path)
        env_copy = tmp_path / "envs" / "p52.json"
        env_copy.parent.mkdir()
        shutil.copyfile(_orig_envelope(), env_copy)
        report = env_copy.parent / "receipt.json"
        rb = _run_readback(case, report, envelope=env_copy)
        assert rb.returncode == 0, rb.stderr
        assert report.is_file()

    def test_relative_path_into_source(self, tmp_path):
        case = _copy_orig(tmp_path)
        script = _slice_script()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_src_dir())
        rb = subprocess.run(
            [sys.executable, str(script), "--readback", str(case),
             "--p52-envelope", str(_orig_envelope()),
             "--report", os.path.relpath(case / "recipe.json",
                                         case.parent)],
            capture_output=True, text=True, timeout=300, env=env,
            cwd=str(case.parent))
        assert rb.returncode == 2
        assert json.loads((case / "recipe.json").read_text(
            encoding="utf-8"))["format"] == \
            "r17-c3-engineering-slice-recipe-v1"

    def test_symlink_alias_into_source(self, tmp_path):
        if os.name == "nt":
            pytest.skip("symlink 需要 Linux")
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        link = receipts / "alias.json"
        link.symlink_to(case / "recipe.json")
        before = _tree_stat(case)
        rb = _run_readback(case, link)
        assert rb.returncode == 2
        assert _tree_stat(case) == before

    def test_hardlink_alias_to_input(self, tmp_path):
        if os.name == "nt":
            pytest.skip("hardlink 需要同一文件系统(tmp 同盘可行)")
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        alias = receipts / "hard.json"
        os.link(case / "recipe.json", alias)
        rb = _run_readback(case, alias)
        assert rb.returncode == 2
        assert json.loads((case / "recipe.json").read_text(
            encoding="utf-8"))["format"] == \
            "r17-c3-engineering-slice-recipe-v1"


class TestP03TempLinkNotFollowed:
    """P03:安全外部回执目录里预置指向输入的固定名 .tmp 链接——
    独占创建唯一临时名,不跟随不截断。"""

    def test_preset_tmp_link_rejected_not_followed(self, tmp_path):
        """安全外部回执目录预置指向输入的固定名 .tmp 链接:产品选择
        fail-closed 明确拒绝(任务书允许"安全独占创建或明确拒绝"二选一),
        绝不跟随/截断输入;源零改动,链接原样。"""
        if os.name == "nt":
            pytest.skip("symlink 需要 Linux")
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        report = receipts / "r.json"
        evil = receipts / (report.name + ".tmp")
        evil.symlink_to(case / "recipe.json")
        before = _tree_stat(case)
        rb = _run_readback(case, report)
        assert rb.returncode == 2
        assert "r.json.tmp" in rb.stderr
        assert evil.is_symlink()  # 预置链接原样未跟随
        assert _tree_stat(case) == before
        assert not report.exists()


class TestP04DefaultReportCwd:
    """P04:cwd 在源内省略 report 拒绝;cwd 在外或显式外部路径正常;
    同名前缀外部兄弟目录不误拒。"""

    def _run_no_report(self, case: Path, cwd: Path):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_src_dir())
        return subprocess.run(
            [sys.executable, str(_slice_script()), "--readback",
             str(case), "--p52-envelope", str(_orig_envelope())],
            capture_output=True, text=True, timeout=300, env=env,
            cwd=str(cwd))

    def test_cwd_inside_source_rejected(self, tmp_path):
        case = _copy_orig(tmp_path)
        before = _tree_stat(case)
        rb = self._run_no_report(case, case / "pairs")
        assert rb.returncode == 2
        assert _tree_stat(case) == before

    def test_cwd_outside_writes_receipt(self, tmp_path):
        case = _copy_orig(tmp_path)
        cwd = tmp_path / "outside"
        cwd.mkdir()
        rb = self._run_no_report(case, cwd)
        assert rb.returncode == 0, rb.stderr
        got = [p for p in cwd.iterdir() if p.name.startswith(
            "readback_receipt_")]
        assert len(got) == 1

    def test_sibling_prefix_dir_not_rejected(self, tmp_path):
        """外部兄弟目录与源同名前缀(slice-backup)不受误拒。"""
        case = tmp_path / "engineering_slice"
        shutil.copytree(_orig_slice_dir(), case)
        sibling = tmp_path / "engineering_slice-backup" / "receipts"
        sibling.mkdir(parents=True)
        report = sibling / "r.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 0, rb.stderr
        assert report.is_file()


class TestP05WriteFailureSafePath:
    """P05:安全回执目标写入失败不输出完成 PASS;错误输入+安全目标
    正常非零且落盘原因;绝不回退写源目录。"""

    def test_receipt_dir_readonly_write_fails(self, tmp_path):
        if os.name == "nt" or os.geteuid() == 0:
            pytest.skip("chmod 阻断需普通用户 Linux")
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        receipts.chmod(0o555)
        try:
            rb = _run_readback(case, receipts / "r.json")
            assert rb.returncode == 6
            assert "readback_verdict: PASS" not in rb.stdout
            assert not (receipts / "r.json").exists()
        finally:
            receipts.chmod(0o755)

    def test_bad_input_safe_target_receipt_written(self, tmp_path):
        case = _copy_orig(tmp_path)
        rows_path = case / "slice_results.jsonl"
        lines = rows_path.read_text(encoding="utf-8").splitlines()
        lines[0], lines[1] = lines[1], lines[0]
        rows_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = tmp_path / "receipts" / "r.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        assert "index_order_exact" in _checks(doc)
        assert doc["readback_verdict"] == "FAIL"


# ================= 路径检查与使用一致 / 回执不覆盖(v4 新增)
def _dir_set(root: Path) -> list:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                  if p.is_dir())


class TestPD01SymlinkDotdotConsistency:
    """矩阵 P01/P02:目录 symlink 后接 .. 的组合目标(abspath 词法折叠
    会得出另一个目录)——CLI 与直接函数都在写前拒绝,源文件与源目录
    集合均零改动;经链接解析落入源内的"原先不存在的新嵌套目标"同样
    在创建任何源内目录/临时件之前被拒绝。"""

    def _mk(self, tmp_path: Path) -> Path:
        case = tmp_path / "case"
        (case / "outside").mkdir(parents=True)
        shutil.copytree(_orig_slice_dir(), case / "source")
        (case / "source" / "child").mkdir(exist_ok=True)
        os.symlink("../source/child", case / "outside" / "alias")
        return case

    def test_recipe_target_cli_absolute(self, tmp_path):
        case = self._mk(tmp_path)
        before = _tree_stat(case / "source")
        dirs = _dir_set(case)
        rb = _run_readback(
            case / "source",
            case / "outside" / "alias" / ".." / "recipe.json")
        assert rb.returncode == 2
        assert _tree_stat(case / "source") == before
        assert _dir_set(case) == dirs
        assert json.loads((case / "source" / "recipe.json").read_text(
            encoding="utf-8"))["format"] == \
            "r17-c3-engineering-slice-recipe-v1"
        # 拒绝理由指向解析后的真实目标(源内),不是词法折叠的外部位置
        assert str(case / "source" / "recipe.json") in rb.stderr
        assert not any(p.name.endswith(".tmp")
                       for p in case.rglob("*") if p.is_file())

    def test_recipe_target_direct_function(self, tmp_path, slice_mod):
        case = self._mk(tmp_path)
        before = _tree_stat(case / "source")
        with pytest.raises(slice_mod.ReportTargetRejected):
            slice_mod.readback(
                case / "source",
                case / "outside" / "alias" / ".." / "recipe.json",
                _orig_envelope())
        assert _tree_stat(case / "source") == before

    def test_historical_receipt_via_link(self, tmp_path):
        case = self._mk(tmp_path)
        before = _tree_stat(case / "source")
        rb = _run_readback(
            case / "source",
            case / "outside" / "alias" / ".." / "readback_report.json")
        assert rb.returncode == 2
        assert _tree_stat(case / "source") == before

    def test_new_nested_target_rejected_before_create(self, tmp_path):
        case = self._mk(tmp_path)
        before = _tree_stat(case / "source")
        dirs = _dir_set(case)
        rb = _run_readback(
            case / "source",
            case / "outside" / "alias" / ".." / "new" / "deep" / "r.json")
        assert rb.returncode == 2
        assert _tree_stat(case / "source") == before
        assert _dir_set(case) == dirs
        assert not (case / "source" / "new").exists()


class TestPD03RelativeLinkProtectRoot:
    """矩阵 P03:相对组合路径、链接父目录、额外 protect-root 与源外
    p52 依据——同一真实路径判定;实际写入落在准入确认位置。"""

    def _run_rel(self, cwd: Path, args: list):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_src_dir())
        return subprocess.run(
            [sys.executable, str(_slice_script()), *args],
            capture_output=True, text=True, timeout=300, env=env,
            cwd=str(cwd))

    def test_relative_combination_same_verdict(self, tmp_path):
        case = tmp_path / "case"
        (case / "outside").mkdir(parents=True)
        shutil.copytree(_orig_slice_dir(), case / "source")
        (case / "source" / "child").mkdir(exist_ok=True)
        os.symlink("../source/child", case / "outside" / "alias")
        before = _tree_stat(case / "source")
        rb = self._run_rel(
            case, ["--readback", "source", "--p52-envelope",
                   str(_orig_envelope()),
                   "--report", "outside/alias/../recipe.json"])
        assert rb.returncode == 2
        assert _tree_stat(case / "source") == before

    def test_report_dir_symlink_lands_in_real_location(self, tmp_path):
        """回执目录本身是链接:准入按解析后真实位置判定与落地,
        stdout 的 report 路径即确认目标。"""
        case = _copy_orig(tmp_path)
        real = tmp_path / "real_receipts"
        real.mkdir()
        os.symlink("real_receipts", tmp_path / "linked_receipts")
        report = tmp_path / "linked_receipts" / "r.json"
        rb = _run_readback(case, report)
        assert rb.returncode == 0, rb.stderr
        assert (real / "r.json").is_file()
        doc = _load(real / "r.json")
        adm = doc["report_target_admission"]
        assert adm["confirmed_target"] == str((real / "r.json").resolve())
        assert f"report: {adm['confirmed_target']}" in rb.stdout

    def test_extra_protect_root_covers_link_target(self, tmp_path):
        case = tmp_path / "case"
        (case / "outside").mkdir(parents=True)
        shutil.copytree(_orig_slice_dir(), case / "source")
        (case / "source" / "child").mkdir(exist_ok=True)
        os.symlink("../source/child", case / "outside" / "alias")
        before = _tree_stat(case / "source")
        rb = self._run_rel(
            case, ["--readback", "source", "--p52-envelope",
                   str(_orig_envelope()),
                   "--protect-root", ".",
                   "--report", "outside/alias/../source/recipe.json"])
        assert rb.returncode == 2
        assert _tree_stat(case / "source") == before

    def test_p52_evidence_via_link_untouched(self, tmp_path):
        case = _copy_orig(tmp_path)
        envs = tmp_path / "envs"
        envs.mkdir()
        env_copy = envs / "p52.json"
        shutil.copyfile(_orig_envelope(), env_copy)
        os.symlink("..", envs / "up")
        b0 = env_copy.read_bytes()
        rb = self._run_rel(
            envs, ["--readback", str(case), "--p52-envelope", "p52.json",
                   "--report", "up/envs/p52.json"])
        assert rb.returncode == 2
        assert env_copy.read_bytes() == b0


class TestPD04ExistingTargetNoClobber:
    """矩阵 P04:本次调用前已存在的外部显式目标一律拒绝(有效 JSON/
    空文件/普通文件/目录);连续调用不覆盖,旧字节/mtime/身份不变;
    新目标可正常完成。"""

    def test_existing_json_receipt_rejected(self, tmp_path):
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        old = receipts / "r.json"
        old.write_text('{"format": "historical", "keep": true}',
                       encoding="utf-8")
        b0, st0 = old.read_bytes(), old.stat()
        rb = _run_readback(case, old)
        assert rb.returncode == 2
        assert old.read_bytes() == b0
        st1 = old.stat()
        assert (st1.st_ino, st1.st_mtime_ns) == (st0.st_ino, st0.st_mtime_ns)
        assert not any(p.name.endswith(".tmp")
                       for p in receipts.iterdir())

    @pytest.mark.parametrize("content", [b"", b"plain text not json\n"])
    def test_existing_empty_and_plain_rejected(self, tmp_path, content):
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        old = receipts / "r.json"
        old.write_bytes(content)
        rb = _run_readback(case, old)
        assert rb.returncode == 2
        assert old.read_bytes() == content

    def test_existing_directory_target_rejected(self, tmp_path):
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        as_dir = receipts / "as_dir"
        as_dir.mkdir(parents=True)
        rb = _run_readback(case, as_dir)
        assert rb.returncode == 2
        assert as_dir.is_dir()

    def test_first_ok_second_rejected_third_new_ok(self, tmp_path):
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        r1 = receipts / "first.json"
        rb1 = _run_readback(case, r1)
        assert rb1.returncode == 0, rb1.stderr
        b1, st1 = r1.read_bytes(), r1.stat()
        rb2 = _run_readback(case, r1)
        assert rb2.returncode == 2
        st2 = r1.stat()
        assert (r1.read_bytes(), st2.st_ino, st2.st_mtime_ns) == \
            (b1, st1.st_ino, st1.st_mtime_ns)
        r3 = receipts / "third.json"
        rb3 = _run_readback(case, r3)
        assert rb3.returncode == 0, rb3.stderr
        assert not any(p.name.endswith(".tmp")
                       for p in receipts.iterdir())


class TestPD05LinkEntries:
    """矩阵 P05:最终 symlink/悬空链接条目不视为可覆盖、不跟随截断
    (硬链接别名与预置临时件链接分别由 P02/P03 覆盖)。"""

    def test_final_symlink_rejected_no_follow(self, tmp_path):
        if os.name == "nt":
            pytest.skip("symlink 需要 Linux")
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        victim = tmp_path / "elsewhere.json"
        victim.write_text("KEEP", encoding="utf-8")
        link = receipts / "r.json"
        link.symlink_to(victim)
        b0 = victim.read_bytes()
        rb = _run_readback(case, link)
        assert rb.returncode == 2
        assert victim.read_bytes() == b0
        assert link.is_symlink()

    def test_dangling_symlink_rejected(self, tmp_path):
        if os.name == "nt":
            pytest.skip("symlink 需要 Linux")
        case = _copy_orig(tmp_path)
        receipts = tmp_path / "receipts"
        receipts.mkdir()
        link = receipts / "r.json"
        link.symlink_to(receipts / "no_such_file.json")
        rb = _run_readback(case, link)
        assert rb.returncode == 2
        assert link.is_symlink()
        assert not (receipts / "no_such_file.json").exists()


class TestPD07LandingFailureOwnership:
    """矩阵 P07:只创建不替换的落地约束与本次候选所有权(函数级);
    chmod 落地失败路径由 P05 覆盖。"""

    def test_create_only_never_replaces_existing(self, tmp_path, slice_mod):
        target = tmp_path / "r.json"
        target.write_text("OLD", encoding="utf-8")
        with pytest.raises(slice_mod.ReceiptWriteError):
            slice_mod._atomic_write_receipt(target, {"a": 1})
        assert target.read_text(encoding="utf-8") == "OLD"
        assert not any(p.name.endswith(".tmp")
                       for p in tmp_path.iterdir())

    def test_owned_update_replaces_only_owned_candidate(self, tmp_path,
                                                        slice_mod):
        target = tmp_path / "r.json"
        tid = slice_mod._atomic_write_receipt(target, {"v": 1})
        tid2 = slice_mod._atomic_write_receipt(target, {"v": 2},
                                               owned_id=tid)
        assert json.loads(target.read_text(encoding="utf-8"))["v"] == 2
        assert os.stat(target).st_ino == tid2[1]  # 返回值即当前候选身份
        # 外部换掉文件(新 inode 的替换,非同 inode 截断)后,旧所有权
        # 更新必须拒绝且不覆盖
        outsider = tmp_path / "outsider.json"
        outsider.write_text('{"v": 99}', encoding="utf-8")
        os.replace(outsider, target)
        with pytest.raises(slice_mod.ReceiptWriteError):
            slice_mod._atomic_write_receipt(target, {"v": 3},
                                            owned_id=tid2)
        assert json.loads(target.read_text(encoding="utf-8"))["v"] == 99
        assert not any(p.name.endswith(".tmp")
                       for p in tmp_path.iterdir())


# ================= 必要参数完整性(v4 新增)
_RUNGS = ("D0", "D1", "D2", "D3")
_REQ_KEYS = ("alpha_bps", "payoff_bars", "vol_bps",
             "cue_rate", "mixture", "distractor_rate")


def _tamper_env(case: Path, coord: str, fn) -> None:
    """对副本 detail 内全部 envelope 应用 fn,按生产权威 canonical
    合同重算该条 digest,并同步索引行 detail_sha256 —— 摘要自洽,
    使读回只剩参数语义差异(内部/外层哈希校验均成立)。"""
    _, stable_digest, auth_body, env_prefix, _ = _authority()
    det = case / "pairs" / f"{coord.replace('/', '_')}.json"
    doc = json.loads(det.read_text(encoding="utf-8"))
    for e in doc["attempt_envelopes"]:
        fn(e)
        e["digest"] = stable_digest(auth_body(e), env_prefix)
    det.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    _resync_row_digest(case, coord)


def _missing_problems(doc: dict, suffix: str) -> list:
    """取 envelope_base_params_required_keys 且 where 以 suffix 结尾
    的 problem 载荷(missing 键列表)。"""
    return [p["actual"]["missing"] for p in doc["problems"]
            if p["check"] == "envelope_base_params_required_keys"
            and p["where"].endswith(suffix)]


class TestK01RequiredKeysMissing:
    """矩阵 K01:逐项删除 A/B 必要课程键(side 非空,digest 权威重算、
    索引详情哈希同步)——digest/详情校验成立但参数完整性明确失败并
    定位缺键;覆盖四个 rung、两侧、六个键(标量与 mixture)。"""

    def _expect_missing(self, case: Path, report: Path,
                        where_suffix: str) -> dict:
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        # 内部摘要与外层详情哈希均成立:拒绝来自参数层
        assert all(doc["checks"]["envelope_digest"].values())
        assert all(v is True for v in doc["checks"]["detail_digest"].values())
        assert _missing_problems(doc, where_suffix)
        return doc

    def test_scalar_key_side_a_each_rung(self, tmp_path):
        for i, rung in enumerate(_RUNGS):
            case = _copy_orig(tmp_path / f"rung{i}")
            report = tmp_path / f"receipts" / f"k1a_{rung}.json"
            report.parent.mkdir(exist_ok=True)
            _tamper_env(case, f"{rung}/p0",
                        lambda e: e["base_params"]["A"].pop("alpha_bps"))
            line = 2 * i + 1  # 索引行号:D<p>/p0 占奇数行
            doc = self._expect_missing(
                case, report, f"{rung}/p0@line{line}:env0:A")
            assert any(m == ["alpha_bps"]
                       for m in _missing_problems(
                           doc, f"{rung}/p0@line{line}:env0:A"))

    def test_all_six_keys_side_b(self, tmp_path):
        for i, key in enumerate(_REQ_KEYS):
            case = _copy_orig(tmp_path / f"key{i}")
            report = tmp_path / "receipts" / f"k1b_{i}.json"
            report.parent.mkdir(exist_ok=True)
            _tamper_env(case, "D0/p1",
                        lambda e, k=key: e["base_params"]["B"].pop(k))
            doc = self._expect_missing(case, report, "D0/p1@line2:env0:B")
            assert any(m == [key]
                       for m in _missing_problems(
                           doc, "D0/p1@line2:env0:B"))

    def test_mixture_list_key_missing(self, tmp_path):
        case = _copy_orig(tmp_path)
        _tamper_env(case, "D2/p0",
                    lambda e: e["base_params"]["A"].pop("mixture"))
        report = tmp_path / "receipts" / "k1mix.json"
        report.parent.mkdir(exist_ok=True)
        doc = self._expect_missing(case, report, "D2/p0@line5:env0:A")
        assert any(m == ["mixture"]
                   for m in _missing_problems(doc, "D2/p0@line5:env0:A"))


class TestK02MissingNullAdditions:
    """矩阵 K02:两侧同缺、键置 null(是不一致不是缺失)、仅剩合法
    附加键(非空字典不等于完备);缺失与不一致正确区分,不补默认值。"""

    def test_both_sides_missing_same_key(self, tmp_path):
        case = _copy_orig(tmp_path)
        _tamper_env(case, "D0/p0", lambda e: (
            e["base_params"]["A"].pop("cue_rate"),
            e["base_params"]["B"].pop("cue_rate")))
        report = tmp_path / "receipts" / "k2a.json"
        report.parent.mkdir(exist_ok=True)
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        assert _missing_problems(doc, "D0/p0@line1:env0:A") == [["cue_rate"]]
        assert _missing_problems(doc, "D0/p0@line1:env0:B") == [["cue_rate"]]

    def test_null_value_is_mismatch_not_missing(self, tmp_path):
        case = _copy_orig(tmp_path)
        _tamper_env(case, "D0/p0",
                    lambda e: e["base_params"]["A"].update(vol_bps=None))
        report = tmp_path / "receipts" / "k2b.json"
        report.parent.mkdir(exist_ok=True)
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        assert not _missing_problems(doc, "D0/p0@line1:env0:A")
        mism = [p for p in doc["problems"]
                if p["check"] == "envelope_base_params_matches_rung"
                and p["where"].endswith("D0/p0@line1:env0:A")]
        assert mism and mism[0]["actual"]["mismatched"] == ["vol_bps"]

    def test_only_additional_keys_left(self, tmp_path):
        case = _copy_orig(tmp_path)
        # 移除六键后 side 仍非空(仅剩 pair_variant 等合法附加键)
        _tamper_env(case, "D1/p0", lambda e: [
            e["base_params"]["A"].pop(k) for k in _REQ_KEYS])
        report = tmp_path / "receipts" / "k2c.json"
        report.parent.mkdir(exist_ok=True)
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        # missing 按冻结常量声明顺序列出全部六键
        assert any(m == list(_REQ_KEYS)
                   for m in _missing_problems(doc, "D1/p0@line3:env0:A"))


class TestK03RecipeRequiredKeys:
    """矩阵 K03:recipe 缺必要键或与 envelope 同时删键以缩小必要集合
    ——依据固定合同拒绝;健康旧 recipe 不受影响(I01 已覆盖)。"""

    def test_recipe_rung_missing_key(self, tmp_path):
        case = _copy_orig(tmp_path)
        _rewrite_json(case / "recipe.json",
                      lambda d: d["rung_params"]["D0"].pop(
                          "distractor_rate"))
        report = tmp_path / "receipts" / "k3a.json"
        report.parent.mkdir(exist_ok=True)
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        probs = [p for p in doc["problems"]
                 if p["check"] == "recipe_rung_params_required_keys"]
        assert probs and probs[0]["actual"]["missing"] == ["distractor_rate"]
        # envelope 侧健康(六键齐全)不产生缺键误报
        assert not _missing_problems(doc, ":A")
        assert not _missing_problems(doc, ":B")

    def test_recipe_and_envelope_both_drop(self, tmp_path):
        """双方同时删键不能缩小必要集合:envelope 侧按冻结常量照报。"""
        case = _copy_orig(tmp_path)
        _rewrite_json(case / "recipe.json",
                      lambda d: d["rung_params"]["D0"].pop("cue_rate"))
        _tamper_env(case, "D0/p0",
                    lambda e: e["base_params"]["A"].pop("cue_rate"))
        report = tmp_path / "receipts" / "k3b.json"
        report.parent.mkdir(exist_ok=True)
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        assert any(p["check"] == "recipe_rung_params_required_keys"
                   and p["actual"]["missing"] == ["cue_rate"]
                   for p in doc["problems"])
        assert _missing_problems(doc, "D0/p0@line1:env0:A") == [["cue_rate"]]
        assert all(doc["checks"]["envelope_digest"].values())

    def test_recipe_rung_object_absent(self, tmp_path):
        case = _copy_orig(tmp_path)
        _rewrite_json(case / "recipe.json",
                      lambda d: d["rung_params"].pop("D2"))
        report = tmp_path / "receipts" / "k3c.json"
        report.parent.mkdir(exist_ok=True)
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        assert any(p["check"] == "recipe_rung_params_present"
                   and p["where"].endswith("rung_params[D2]")
                   for p in doc["problems"])
        # envelope 侧必要键存在性不受 recipe 缺失影响
        assert not _missing_problems(doc, ":A")


class TestK04ValueChangeMismatch:
    """矩阵 K04:参数值改变(摘要自洽)→ 非零且定位键;健康合法展开
    与原负收益不受影响(I01/I06 已覆盖不重复)。"""

    def test_mixture_value_changed(self, tmp_path):
        case = _copy_orig(tmp_path)
        _tamper_env(case, "D0/p0", lambda e: e["base_params"]["A"].update(
            mixture=[0.61, 0.24, 0.15]))
        report = tmp_path / "receipts" / "k4a.json"
        report.parent.mkdir(exist_ok=True)
        rb = _run_readback(case, report)
        assert rb.returncode == 1
        doc = _load(report)
        assert all(doc["checks"]["envelope_digest"].values())
        mism = [p for p in doc["problems"]
                if p["check"] == "envelope_base_params_matches_rung"
                and p["where"].endswith("D0/p0@line1:env0:A")]
        assert mism and "mixture" in mism[0]["actual"]["mismatched"]
        assert not _missing_problems(doc, "D0/p0@line1:env0:A")


# ============ v5:末端条目/解析错误分类/临时件所有权(PE/TO) ============

class _FixedDatetime:
    """替换 reader 模块全局 datetime 的固定实现(临时名可预测)。"""

    def __init__(self, stamp: str) -> None:
        import datetime as _d
        self._when = _d.datetime.strptime(stamp, "%Y%m%dT%H%M%S%f").replace(
            tzinfo=_d.timezone.utc)

    def now(self, tz):  # noqa: ARG002 —— 与被替换签名一致
        return self._when


def _fixed_tmp_name(target: Path, stamp: str) -> Path:
    """reader 临时名推导(pid 取当前进程,与被测调用同进程)。"""
    return target.with_name(
        f".{target.name}.{os.getpid()}.{stamp}.tmp")


class TestPE01CrossDirDanglingEndLink:
    """矩阵 P01:跨目录末端悬空链接(目标目录存在/目标文件缺失)写前
    拒绝;原末端条目在原位置检查(不从解析后 target.parent 倒推),
    悬空目标文件不被创建,链接条目原样;CLI 与直接函数一致。"""

    def _mk(self, tmp: Path, target: str = "missing.json") -> tuple:
        case = tmp / "case"
        (case / "receipts").mkdir(parents=True)
        (case / "elsewhere").mkdir()
        shutil.copytree(_orig_slice_dir(), case / "source")
        link = case / "receipts" / "result.json"
        os.symlink(f"../elsewhere/{target}", link)
        return case, link

    def test_cli_rejected_no_target_created(self, tmp_path):
        case, link = self._mk(tmp_path)
        missing = case / "elsewhere" / "missing.json"
        before_dirs = _dir_set(case)
        rb = _run_readback(case / "source", link)
        assert rb.returncode == 2
        assert not missing.exists()
        assert link.is_symlink()
        assert os.readlink(link) == "../elsewhere/missing.json"
        assert _dir_set(case) == before_dirs
        # 拒绝理由指向原末端条目(receipts/result.json),不是解析后
        # 的悬空目标位置(elsewhere/missing.json)
        assert str(link) in rb.stderr
        assert not any(p.name.endswith(".tmp")
                       for p in case.rglob("*") if p.is_file())

    def test_direct_function_rejected(self, tmp_path, slice_mod):
        case, link = self._mk(tmp_path)
        missing = case / "elsewhere" / "missing.json"
        with pytest.raises(slice_mod.ReportTargetRejected):
            slice_mod.readback(case / "source", link, _orig_envelope(),
                               protect_roots=[case / "source"])
        assert not missing.exists()
        assert link.is_symlink()


class TestPE02EntryVariants:
    """矩阵 P02:P01 的变体与对照 —— 相对路径、父目录链接、两级末端
    链接;同父目录对照与"链接目标已存在"对照。全部写前拒绝,链接
    条目与目标对象不动。"""

    def _case(self, tmp: Path) -> Path:
        case = tmp / "case"
        (case / "receipts").mkdir(parents=True)
        (case / "elsewhere").mkdir()
        shutil.copytree(_orig_slice_dir(), case / "source")
        return case

    def test_relative_path_variant(self, tmp_path):
        case = self._case(tmp_path)
        os.symlink("../elsewhere/missing.json",
                   case / "receipts" / "result.json")
        missing = case / "elsewhere" / "missing.json"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_src_dir())
        r = subprocess.run(
            [sys.executable, str(_slice_script()), "--readback", "source",
             "--p52-envelope", str(_orig_envelope()),
             "--report", "receipts/result.json"],
            capture_output=True, text=True, timeout=300, env=env,
            cwd=str(case))
        assert r.returncode == 2
        assert not missing.exists()
        assert (case / "receipts" / "result.json").is_symlink()

    def test_parent_dir_link_with_end_link(self, tmp_path):
        """父目录链接 + 末端链接:原末端条目在父链接解析后的真实
        位置检查(real_receipts/result.json 是链接条目 → 拒绝)。"""
        case = self._case(tmp_path)
        real = case / "real_receipts"
        real.mkdir()
        os.symlink("real_receipts", case / "linked")
        os.symlink("../elsewhere/missing.json",
                   real / "result.json")
        missing = case / "elsewhere" / "missing.json"
        rb = _run_readback(case / "source", case / "linked" / "result.json")
        assert rb.returncode == 2
        assert not missing.exists()
        assert (real / "result.json").is_symlink()

    def test_two_hop_end_link_chain(self, tmp_path):
        """末端链接链两级:result.json -> mid.json -> 悬空目标;
        原末端条目(result.json)是链接条目 → 写前拒绝,不逐跳跟随。"""
        case = self._case(tmp_path)
        os.symlink("mid.json", case / "receipts" / "result.json")
        os.symlink("../elsewhere/missing.json", case / "receipts" / "mid.json")
        missing = case / "elsewhere" / "missing.json"
        rb = _run_readback(case / "source",
                           case / "receipts" / "result.json")
        assert rb.returncode == 2
        assert not missing.exists()
        assert (case / "receipts" / "mid.json").is_symlink()

    def test_same_parent_dangling_control(self, tmp_path):
        """对照:同父目录悬空链接(无跨目录)同样拒绝(路径无关)。"""
        case = self._case(tmp_path)
        os.symlink("no_such_local.json",
                   case / "receipts" / "same_parent.json")
        rb = _run_readback(case / "source",
                           case / "receipts" / "same_parent.json")
        assert rb.returncode == 2
        assert not (case / "receipts" / "no_such_local.json").exists()
        assert (case / "receipts" / "same_parent.json").is_symlink()

    def test_crossdir_live_target_control(self, tmp_path):
        """对照:跨目录链接目标已存在(present.json)→ 链接条目存在,
        同样拒绝,目标与条目都不动。"""
        case = self._case(tmp_path)
        (case / "elsewhere" / "present.json").write_text(
            "EXISTING TARGET", encoding="utf-8")
        os.symlink("../elsewhere/present.json",
                   case / "receipts" / "result.json")
        tgt = case / "elsewhere" / "present.json"
        b = tgt.read_bytes()
        rb = _run_readback(case / "source",
                           case / "receipts" / "result.json")
        assert rb.returncode == 2
        assert tgt.read_bytes() == b
        assert (case / "receipts" / "result.json").is_symlink()


class TestPE03NotDirAncestor:
    """矩阵 P03(非目录):普通文件充当祖先的两形态(file/new.json 与
    file/../new.json)在写前准入被拒(分类错误,非写者失败);不折叠成
    兄弟文件;链接指向普通文件的变体同样拒绝;完整 CLI 与直接函数。"""

    def _mk(self, tmp: Path) -> Path:
        case = tmp / "case"
        case.mkdir()
        shutil.copytree(_orig_slice_dir(), case / "source")
        (case / "f").write_text("ordinary file", encoding="utf-8")
        return case

    def test_file_slash_new_cli(self, tmp_path):
        case = self._mk(tmp_path)
        rb = _run_readback(case / "source", case / "f" / "new.json")
        assert rb.returncode == 2
        assert "祖先不是目录" in rb.stderr
        assert str(case / "f") in rb.stderr
        assert not (case / "f" / "new.json").exists()
        assert (case / "f").is_file()

    def test_file_dotdot_new_cli_no_sibling_created(self, tmp_path):
        case = self._mk(tmp_path)
        before = _dir_set(case)
        rb = _run_readback(case / "source", case / "f" / ".." / "new.json")
        assert rb.returncode == 2
        assert "祖先不是目录" in rb.stderr
        # 词法折叠后的兄弟位置不被创建
        assert not (case / "new.json").exists()
        assert not (case / "f" / "new.json").exists()
        assert _dir_set(case) == before

    def test_link_to_file_ancestor(self, tmp_path):
        """链接指向普通文件再穿越:经链接解析为非目录 → 拒绝。"""
        case = self._mk(tmp_path)
        os.symlink("f", case / "lf")
        rb = _run_readback(case / "source", case / "lf" / "new.json")
        assert rb.returncode == 2
        assert not (case / "new.json").exists()

    def test_file_dotdot_direct_function(self, tmp_path, slice_mod):
        case = self._mk(tmp_path)
        with pytest.raises(slice_mod.ReportTargetRejected):
            slice_mod.readback(case / "source",
                               case / "f" / ".." / "new.json",
                               _orig_envelope())
        assert not (case / "new.json").exists()


class TestPE04ResolveErrors:
    """矩阵 P04:循环链接、不可访问祖先(EACCES 物理夹具)、缺失祖先
    后又 ..、悬空祖先链接 —— 有界清晰拒绝,错误类别定位路径;不能
    变成"安全不存在"或写者侧失败。"""

    def _mk(self, tmp: Path) -> Path:
        case = tmp / "case"
        case.mkdir()
        shutil.copytree(_orig_slice_dir(), case / "source")
        return case

    def test_symlink_loop_ancestor(self, tmp_path):
        case = self._mk(tmp_path)
        loop = case / "loop"
        os.symlink("loop", loop)  # 自指
        rb = _run_readback(case / "source", loop / "new.json")
        assert rb.returncode == 2
        assert not (case / "new.json").exists()

    def test_eacces_ancestor_physical(self, tmp_path):
        case = self._mk(tmp_path)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root 下 chmod 000 不构成 EACCES")
        lock = case / "lock"
        lock.mkdir()
        (lock / "inner").mkdir()
        os.chmod(lock, 0o000)
        try:
            rb = _run_readback(case / "source",
                               lock / "inner" / "new.json")
        finally:
            os.chmod(lock, 0o755)  # tmp_path 清理需要恢复访问
        assert rb.returncode == 2
        assert "权限" in rb.stderr
        assert not (lock / "inner" / "new.json").exists()

    def test_missing_then_dotdot_ambiguous(self, tmp_path):
        """缺失祖先后又 ..:歧义形态明确拒绝,不自动修复输入路径。"""
        case = self._mk(tmp_path)
        rb = _run_readback(case / "source",
                           case / "no_such_dir" / ".." / "new.json")
        assert rb.returncode == 2
        assert "缺失祖先后又" in rb.stderr
        assert not (case / "new.json").exists()

    def test_dangling_ancestor_link(self, tmp_path):
        """悬空祖先链接:歧义形态拒绝(不跟随到悬空目标下新建)。"""
        case = self._mk(tmp_path)
        os.symlink("no_such_place", case / "dang")
        rb = _run_readback(case / "source", case / "dang" / "new.json")
        assert rb.returncode == 2
        assert "悬空" in rb.stderr
        assert not (case / "no_such_place").exists()


class TestPE05HealthyMissingPaths:
    """矩阵 P05(健康正例):安全外部缺失末端、普通嵌套新目录、有效
    父目录链接下全新普通名 —— 正常创建并落在 confirmed;不以全面
    禁用正常新路径换取负例通过(绝对/相对两形式)。"""

    def test_plain_external_missing_end_relative(self, tmp_path):
        case = tmp_path / "case"
        case.mkdir()
        shutil.copytree(_orig_slice_dir(), case / "source")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_src_dir())
        r = subprocess.run(
            [sys.executable, str(_slice_script()), "--readback", "source",
             "--p52-envelope", str(_orig_envelope()),
             "--report", "receipts/rel_new.json"],
            capture_output=True, text=True, timeout=300, env=env,
            cwd=str(case))
        assert r.returncode == 0
        doc = _load(case / "receipts" / "rel_new.json")
        assert doc["report_target_admission"]["admitted"] is True

    def test_nested_new_dirs_created(self, tmp_path):
        case = tmp_path / "case"
        case.mkdir()
        shutil.copytree(_orig_slice_dir(), case / "source")
        rb = _run_readback(case / "source",
                           case / "deep" / "a" / "b" / "r.json")
        assert rb.returncode == 0
        assert (case / "deep" / "a" / "b" / "r.json").is_file()

    def test_parent_dir_link_new_name_lands_real(self, tmp_path):
        case = tmp_path / "case"
        case.mkdir()
        shutil.copytree(_orig_slice_dir(), case / "source")
        real = case / "real_receipts"
        real.mkdir()
        os.symlink("real_receipts", case / "linked")
        rb = _run_readback(case / "source", case / "linked" / "n.json")
        assert rb.returncode == 0
        # 实际落在链接解析后的真实位置(confirmed)
        assert (real / "n.json").is_file()
        doc = _load(real / "n.json")
        assert doc["report_target_admission"]["confirmed_target"] == \
            str((real / "n.json").resolve())


class TestTO01TempNameCollision:
    """矩阵 T01:强制临时名碰撞(固定 datetime)。预置外部普通文件/
    链接条目占住临时名 → 真正创建失败后不删除、不替换该对象;
    ReceiptWriteError 非零,冲突项原样保留。"""

    def _collide(self, tmp_path, slice_mod, monkeypatch, occupy) -> Path:
        out = tmp_path / "out"
        out.mkdir()
        target = out / "result.json"
        stamp = "20260909T120000000000"
        monkeypatch.setattr(slice_mod, "datetime", _FixedDatetime(stamp))
        tmp = _fixed_tmp_name(target, stamp)
        occupy(tmp)
        return target

    def test_foreign_plain_file_survives(self, tmp_path, slice_mod,
                                         monkeypatch):
        def occupy(p: Path) -> None:
            p.write_text("PREEXISTING_FOREIGN_TEMP", encoding="utf-8")

        target = self._collide(tmp_path, slice_mod, monkeypatch, occupy)
        tmp = _fixed_tmp_name(target, "20260909T120000000000")
        st0 = tmp.stat()
        b0 = tmp.read_bytes()
        with pytest.raises(slice_mod.ReceiptWriteError):
            slice_mod._atomic_write_receipt(target, {"k": "v"})
        assert tmp.read_bytes() == b0
        st1 = tmp.stat()
        assert (st1.st_ino, st1.st_mtime_ns) == (st0.st_ino, st0.st_mtime_ns)
        assert not target.exists()

    def test_foreign_link_entry_survives(self, tmp_path, slice_mod,
                                         monkeypatch):
        victim = tmp_path / "victim.txt"

        def occupy(p: Path) -> None:
            victim.write_text("VICTIM CONTENT", encoding="utf-8")
            os.symlink(victim, p)

        target = self._collide(tmp_path, slice_mod, monkeypatch, occupy)
        tmp = _fixed_tmp_name(target, "20260909T120000000000")
        with pytest.raises(slice_mod.ReceiptWriteError):
            slice_mod._atomic_write_receipt(target, {"k": "v"})
        assert tmp.is_symlink()
        assert os.readlink(tmp) == str(victim)
        assert victim.read_text(encoding="utf-8") == "VICTIM CONTENT"
        assert not target.exists()

    def test_dangling_foreign_link_survives(self, tmp_path, slice_mod,
                                            monkeypatch):
        def occupy(p: Path) -> None:
            os.symlink("/no/such/target", p)

        target = self._collide(tmp_path, slice_mod, monkeypatch, occupy)
        tmp = _fixed_tmp_name(target, "20260909T120000000000")
        with pytest.raises(slice_mod.ReceiptWriteError):
            slice_mod._atomic_write_receipt(target, {"k": "v"})
        assert tmp.is_symlink()
        assert not target.exists()


class TestTO02CreateFailOwnership:
    """矩阵 T02:创建失败的清理所有权 —— EACCES 创建失败无任何可
    清理对象(目录集合不变);fdopen 包装失败时先关闭本次取得的
    描述符再传播,临时件按本次已创建清理。"""

    def test_eacces_create_fail_no_side_effects(self, tmp_path, slice_mod):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root 下 chmod 000 不构成 EACCES")
        out = tmp_path / "out"
        out.mkdir()
        os.chmod(out, 0o555)
        target = out / "result.json"
        try:
            with pytest.raises(slice_mod.ReceiptWriteError):
                slice_mod._atomic_write_receipt(target, {"k": "v"})
        finally:
            os.chmod(out, 0o755)
        assert sorted(p.name for p in out.iterdir()) == []
        assert not target.exists()

    def test_fdopen_wrap_fail_closes_fd_and_cleans(self, tmp_path,
                                                   slice_mod, monkeypatch):
        out = tmp_path / "out"
        out.mkdir()
        target = out / "result.json"
        stamp = "20260909T120000000000"
        monkeypatch.setattr(slice_mod, "datetime", _FixedDatetime(stamp))
        tmp = _fixed_tmp_name(target, stamp)
        closed: list[int] = []
        real_close = os.close

        def spy_close(fd: int) -> None:
            closed.append(fd)
            real_close(fd)

        def broken_fdopen(fd, *a, **kw):
            raise RuntimeError("fdopen wrap failure")

        monkeypatch.setattr(slice_mod.os, "close", spy_close)
        monkeypatch.setattr(slice_mod.os, "fdopen", broken_fdopen)
        with pytest.raises(RuntimeError):
            slice_mod._atomic_write_receipt(target, {"k": "v"})
        assert len(closed) == 1  # 本次取得的描述符被关闭
        assert not tmp.exists()  # 本次创建的临时件已清理
        assert not target.exists()


class TestTO03WriteFailCleanup:
    """矩阵 T03:创建成功后写入/fsync 失败 —— 非零;本次临时件可
    回收;既有最终文件与输入未变;错误原因保持原始类别。"""

    def test_write_fail_cleans_created_tmp(self, tmp_path, slice_mod,
                                           monkeypatch):
        out = tmp_path / "out"
        out.mkdir()
        target = out / "result.json"
        stamp = "20260909T120000000000"
        monkeypatch.setattr(slice_mod, "datetime", _FixedDatetime(stamp))
        tmp = _fixed_tmp_name(target, stamp)

        def broken_dumps(*a, **kw):
            raise OSError(5, "EIO simulated on write path")

        monkeypatch.setattr(slice_mod.json, "dumps", broken_dumps)
        with pytest.raises(slice_mod.ReceiptWriteError) as ei:
            slice_mod._atomic_write_receipt(target, {"k": "v"})
        assert "回执写失败" in str(ei.value)
        assert not tmp.exists()
        assert not target.exists()
        assert sorted(p.name for p in out.iterdir()) == []

    def test_fsync_fail_cleans_created_tmp(self, tmp_path, slice_mod,
                                           monkeypatch):
        out = tmp_path / "out"
        out.mkdir()
        target = out / "result.json"
        stamp = "20260909T120000000000"
        monkeypatch.setattr(slice_mod, "datetime", _FixedDatetime(stamp))
        tmp = _fixed_tmp_name(target, stamp)

        def broken_fsync(fd):
            raise OSError(5, "EIO simulated on fsync")

        monkeypatch.setattr(slice_mod.os, "fsync", broken_fsync)
        with pytest.raises(slice_mod.ReceiptWriteError) as ei:
            slice_mod._atomic_write_receipt(target, {"k": "v"})
        assert "回执写失败" in str(ei.value)
        assert not tmp.exists()
        assert not target.exists()


class TestTO05CleanupFailHonesty:
    """矩阵 T05:本次拥有的临时件清理自身失败 —— 记录初始/清理
    双失败,不谎称清理完成;发布后清理失败以清理失败非零(目标已
    落地的事实保留在文件系统,不打印完成 PASS);不删除其他对象。"""

    def test_cleanup_fail_after_publish_nonzero(self, tmp_path, slice_mod,
                                                monkeypatch):
        out = tmp_path / "out"
        out.mkdir()
        target = out / "result.json"
        stamp = "20260909T120000000000"
        monkeypatch.setattr(slice_mod, "datetime", _FixedDatetime(stamp))
        tmp = _fixed_tmp_name(target, stamp)

        def broken_unlink(p, *a, **kw):
            raise OSError(13, "EACCES simulated on cleanup")

        monkeypatch.setattr(slice_mod.os, "unlink", broken_unlink)
        with pytest.raises(slice_mod.ReceiptWriteError) as ei:
            slice_mod._atomic_write_receipt(target, {"k": "v"})
        assert "临时件清理失败" in str(ei.value)
        assert str(tmp) in str(ei.value)
        # 发布已完成(首发布只创建不替换成功),未清理对象位置如实在错
        assert target.is_file()
        assert tmp.exists()  # 清理失败:未清理对象保留,不扩大删除

    def test_cleanup_fail_keeps_original_error(self, tmp_path, slice_mod,
                                               monkeypatch):
        out = tmp_path / "out"
        out.mkdir()
        target = out / "result.json"
        stamp = "20260909T120000000000"
        monkeypatch.setattr(slice_mod, "datetime", _FixedDatetime(stamp))
        tmp = _fixed_tmp_name(target, stamp)

        def broken_dumps(*a, **kw):
            raise OSError(5, "EIO simulated on write path")

        def broken_unlink(p, *a, **kw):
            raise OSError(13, "EACCES simulated on cleanup")

        monkeypatch.setattr(slice_mod.json, "dumps", broken_dumps)
        monkeypatch.setattr(slice_mod.os, "unlink", broken_unlink)
        with pytest.raises(slice_mod.ReceiptWriteError) as ei:
            slice_mod._atomic_write_receipt(target, {"k": "v"})
        # 原始错误(写失败)保持为异常主体,清理失败为附注
        assert "回执写失败" in str(ei.value)
        notes = getattr(ei.value, "__notes__", [])
        assert any("临时件清理失败" in n for n in notes)
        assert not target.exists()

