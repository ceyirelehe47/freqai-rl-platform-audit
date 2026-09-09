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
