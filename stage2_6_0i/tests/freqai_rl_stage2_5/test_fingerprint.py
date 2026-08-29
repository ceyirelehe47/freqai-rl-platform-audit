"""实验指纹与缓存隔离测试(任务书十五节,函数级)。

集成级验证(修改一个关键参数 -> 新 identifier -> 新模型/缓存目录)
在 PPO 烟雾测试中执行:seed 42 与 43 两次 run_experiment 产生不同
identifier,各自命中独立目录,日志出现 "Could not find backtesting
prediction file"。
"""

import json
from pathlib import Path

from rl_platform.fingerprint import (
    build_identifier,
    collect_code_hashes,
    compute_fingerprint,
    sha256_file,
)

BASE_PARTS = {
    "freqtrade_commit": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
    "code_sha256": {"src/rl_platform/env.py": "a" * 64, "src/rl_platform/ledger.py": "b" * 64},
    "reward": {"type": "log_equity_return", "scale": 1.0},
    "fee": 0.001,
    "slippage_bps": 0.0,
    "features": ["%-ret-1", "%-ret-4"],
    "timerange": "20260601-20260701",
    "data_slice": {"sha256": "d" * 64, "bars": 720},
    "seed": 42,
    "model_type": "PPO",
    "train_params": {"net_arch": [32, 32], "train_cycles": 1},
}


def test_same_inputs_same_identifier():
    fp1 = compute_fingerprint(BASE_PARTS)
    fp2 = compute_fingerprint(json.loads(json.dumps(BASE_PARTS)))
    assert fp1 == fp2
    assert build_identifier("stage25-rc", fp1) == build_identifier("stage25-rc", fp2)


def test_single_change_breaks_identifier():
    base = compute_fingerprint(BASE_PARTS)
    changes = [
        {"seed": 43},                                # 随机种子
        {"slippage_bps": 5.0},                       # 滑点
        {"fee": 0.002},                               # 手续费
        {"features": ["%-ret-1", "%-ret-4", "%-x"]},  # 特征
        {"data_slice": {"sha256": "e" * 64, "bars": 720}},  # 数据
        {"train_params": {"net_arch": [64, 64], "train_cycles": 1}},  # 训练参数
        {"code_sha256": {"src/rl_platform/env.py": "f" * 64, "src/rl_platform/ledger.py": "b" * 64}},  # 环境代码
        {"timerange": "20260601-20260615"},           # 时间范围
    ]
    ids = set()
    for ch in changes:
        parts = json.loads(json.dumps(BASE_PARTS))
        parts.update(ch)
        fp = compute_fingerprint(parts)
        assert fp != base, f"修改 {list(ch.keys())} 未改变指纹"
        ids.add(build_identifier("stage25-rc", fp))
    assert len(ids) == len(changes)


def test_code_file_hash_tracks_content(tmp_path: Path):
    f = tmp_path / "env.py"
    f.write_text("x = 1\n")
    h1 = sha256_file(f)
    f.write_text("x = 2\n")
    h2 = sha256_file(f)
    assert h1 != h2

    (tmp_path / "ledger.py").write_text("y = 1\n")
    hashes = collect_code_hashes(
        tmp_path, files=["env.py", "ledger.py"]
    )
    assert set(hashes) == {"env.py", "ledger.py"}
    assert all(len(v) == 64 for v in hashes.values())
