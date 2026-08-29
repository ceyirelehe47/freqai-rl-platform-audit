"""工作包 C1:正式 CLI 无进程内候选绕过(--no-subprocess 已删除)。"""

from __future__ import annotations

import inspect
from pathlib import Path
import subprocess
import sys


def test_cli_has_no_no_subprocess_flag():
    from rl_curriculum import hidden_exam_cli

    src = inspect.getsource(hidden_exam_cli)
    assert 'ap.add_argument("--no-subprocess"' not in src


def test_run_sealed_exam_has_no_use_subprocess_parameter():
    from rl_curriculum.formal_exam import run_sealed_exam

    params = inspect.signature(run_sealed_exam).parameters
    assert "use_subprocess" not in params
    assert "in_process" not in params


def test_formal_exam_never_constructs_inprocess_candidate():
    from rl_curriculum import formal_exam

    src = inspect.getsource(formal_exam)
    assert "SB3CheckpointPolicy(" not in src, (
        "正式执行器不得在评估主进程内构造候选(进程内执行只允许 "
        "public dev test 或单元测试专用入口)")
    assert "SandboxedCandidate" in src


def _cli_env():
    """CLI 子进程需要 src 在 PYTHONPATH(与 pytest 运行环境一致)。"""
    import os

    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_dev_mode_marks_formal_conclusion_false(tmp_path):
    """--dev(公开 pack,进程内)输出 formal_conclusion=false。"""
    from rl_curriculum.exam_pack import ExamPack
    from rl_curriculum.generator_api import EpisodeSpec
    from rl_platform.versions import spec_versions

    specs = [EpisodeSpec("probe_segmented_drift",
                         {"episode_bars": 32,
                          "regimes": [[1, 20.0, 16], [0, 0.0, 16]]},
                         1, "train", "15m")]
    pack = ExamPack(name="public_dev_pack", version="v1",
                    visibility="public", charter_hash="c",
                    spec_versions=spec_versions(), episodes=specs,
                    timeframe="15m")
    pack_path = tmp_path / "pack.json"
    pack.save(pack_path)
    out = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
         "--dev", "--pack", str(pack_path), "--policy", "always_flat",
         "--out", str(out)],
        capture_output=True, text=True, timeout=600, env=_cli_env())
    assert proc.returncode == 0, proc.stderr[-2000:]
    import json

    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["mode"] == "dev"
    assert result["formal_conclusion"] is False
    assert result["status"] == "DEV_ONLY"


def test_sealed_mode_without_manifest_exits_2(tmp_path):
    from rl_curriculum.exam_pack import ExamPack
    from rl_curriculum.generator_api import EpisodeSpec
    from rl_platform.versions import spec_versions

    specs = [EpisodeSpec("probe_null_sign", {"episode_bars": 32},
                         1, "null_control", "15m")]
    pack = ExamPack(name="p", version="v", visibility="mock_hidden",
                    charter_hash="c", spec_versions=spec_versions(),
                    episodes=specs, timeframe="15m")
    pack_path = tmp_path / "pack.json"
    pack.save(pack_path)
    proc = subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
         "--pack", str(pack_path), "--checkpoint", "x.zip",
         "--out", str(tmp_path / "o.json")],
        capture_output=True, text=True, timeout=120, env=_cli_env())
    assert proc.returncode == 2


def test_no_subprocess_flag_is_rejected_by_argparse(tmp_path):
    """显式传 --no-subprocess 直接被 argparse 拒绝(参数不存在)。"""
    proc = subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
         "--no-subprocess", "--pack", "x", "--out", "y"],
        capture_output=True, text=True, timeout=120, env=_cli_env())
    assert proc.returncode == 2
    assert "unrecognized arguments" in proc.stderr
