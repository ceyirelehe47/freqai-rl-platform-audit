"""工作包 0 修复 2:freqtrade 成功但预测目录缺失必须致命(fail closed)。

monkeypatch subprocess 模拟 freqtrade 退出码 0 且不产生
backtesting_predictions:整轮实验必须 invalid + 退出码 4 + manifest
记录原始异常;不得写成 SKIPPED 后继续成功;模型目录保留。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))
sys.path.insert(0, str(PROJ_ROOT / "experiments" / "freqai_rl_stage2_5_2a"))


class _FakeCompleted:
    def __init__(self, code=0):
        self.returncode = code
        self.stdout = ""
        self.stderr = ""


def _run_main(monkeypatch, tmp_path, freqtrade_rc=0):
    import run_experiment as rx

    # 隔离 runtime 输出目录,避免污染真实 runtime
    monkeypatch.setattr(rx, "RUNTIME_DIR", tmp_path, raising=False)
    monkeypatch.setattr(
        rx, "freqtrade_commit", lambda: "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
    )

    calls = {"backtest": 0}

    def fake_run(cmd, **kwargs):
        if "backtesting" in cmd:
            calls["backtest"] += 1
            return _FakeCompleted(freqtrade_rc)
        return _FakeCompleted(0)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        sys, "argv",
        ["run_experiment.py", "--timerange", "20260601-20260610",
         "--suffix", "fatality"])
    rc = rx.main()
    manifests = sorted(tmp_path.glob("manifest_*.json"))
    assert manifests, "manifest 未写出"
    manifest = json.loads(manifests[-1].read_text())
    return rc, manifest, calls


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_missing_predictions_dir_is_fatal(monkeypatch, tmp_path):
    rc, manifest, calls = _run_main(monkeypatch, tmp_path, freqtrade_rc=0)
    assert calls["backtest"] == 1
    assert rc == 4  # CACHE_PIPELINE_EXIT_CODE
    cm = manifest["cache_content_manifest"]
    assert cm.get("invalid") is True
    assert cm.get("self_check") == "INCONSISTENT"
    assert "FileNotFoundError" in cm.get("error", "")
    assert "不存在" in cm.get("error", "")
    assert cm.get("state") != "SKIPPED"  # 不得 SKIPPED
    assert cm.get("models_dir_kept") is True


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_freqtrade_nonzero_still_reports_own_code(monkeypatch, tmp_path):
    rc, manifest, _ = _run_main(monkeypatch, tmp_path, freqtrade_rc=2)
    assert rc == 2
    cm = manifest["cache_content_manifest"]
    assert cm.get("state") == "SKIPPED"
    assert "2" in cm.get("reason", "")


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_manifest_records_exit_code_and_missing_dir(monkeypatch, tmp_path):
    rc, manifest, _ = _run_main(monkeypatch, tmp_path, freqtrade_rc=0)
    cm = manifest["cache_content_manifest"]
    assert cm["freqtrade_exit_code"] == 0
    assert "backtesting_predictions" in cm["missing_predictions_dir"]
    assert manifest["post_run"]["exit_code"] == 0  # freqtrade 本身成功
