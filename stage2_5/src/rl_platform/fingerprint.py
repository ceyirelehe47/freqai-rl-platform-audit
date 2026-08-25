"""实验指纹与缓存隔离(阶段 2.5 路线 C)。

上一阶段审计发现 FreqAI 预测缓存只按"文件名 + 行数"判定有效性,
策略/奖励/环境/随机种子变化后旧缓存仍会被静默复用。
本模块为每次实验生成稳定指纹:任一关键项改变 -> identifier 改变 ->
FreqAI 使用新的模型目录与预测缓存目录(不改 FreqAI 核心缓存校验代码)。

identifier 在 IFreqaiModel.__init__(freqai_interface.py:69,72)读取
config["freqai"]["identifier"] 并展开为 user_data/models/<identifier>,
因此指纹必须在渲染 config 阶段注入(experiments/.../run_experiment.py 负责)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# 参与指纹的自有代码(相对项目根)
DEFAULT_CODE_FILES = [
    "src/rl_platform/env.py",
    "src/rl_platform/ledger.py",
    "src/rl_platform/inference.py",
    "src/rl_platform/signal_convert.py",
    "user_data/freqaimodels/RouteCModel.py",
    "user_data/strategies/RouteCStrategy.py",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    return sha256_bytes(path.read_bytes())


def collect_code_hashes(project_root: str | Path, files: list[str] | None = None) -> dict[str, str]:
    """收集参与指纹的代码文件 SHA-256(相对路径 -> 哈希)。"""
    root = Path(project_root)
    files = files or DEFAULT_CODE_FILES
    return {rel: sha256_file(root / rel) for rel in files}


def compute_fingerprint(parts: dict[str, Any]) -> str:
    """对规范化 JSON(canonical,排序键)计算 SHA-256 指纹。"""
    canonical = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_bytes(canonical.encode("utf-8"))


def build_identifier(prefix: str, fingerprint: str) -> str:
    """可读前缀 + 哈希短值,例如 stage25-rc-3fa92b1c7d。"""
    return f"{prefix}-{fingerprint[:10]}"
