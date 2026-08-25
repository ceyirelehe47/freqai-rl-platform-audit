"""实验指纹与缓存隔离(阶段 2.5.1 工作包 D 全面加固)。

阶段 2.5 的指纹只覆盖 6 个手选文件哈希 + 少量字段。阶段 2.5.1 起指纹覆盖:

1. 第一方代码 tree hash:src/rl_platform/**/*.py、RouteCModel.py、
   RouteCStrategy.py、experiments/freqai_rl_stage2_5{,_1}/**/*.py|json
   (排除 runtime/ logs/ artifacts/ __pycache__/ 模型目录/预测缓存);
2. 完整最终解析配置(规范化排序 JSON;移除 freqai.identifier 避免自指循环);
3. 完整数据范围哈希:数据文件中所有 date < 评估结束时间的行
   (覆盖评估 + 全部训练 + startup 预热,不受评估后新增 K 线影响);
4. 关键依赖版本(import 后实测,不从文档手填);
5. Freqtrade commit。

任一项改变 -> fingerprint 改变 -> identifier 改变 -> FreqAI 使用新的模型
目录与预测缓存目录(不改 FreqAI 核心缓存校验代码)。

identifier 在 IFreqaiModel.__init__(freqai_interface.py)读取
config["freqai"]["identifier"],因此指纹在渲染 config 阶段计算,
之后才把 identifier 写入最终配置。
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# 参与代码树哈希的根(相对项目根):目录递归 *.py/*.json,或单个文件
CODE_TREE_INCLUDE_DIRS = [
    "src/rl_platform",
    "experiments/freqai_rl_stage2_5",
    "experiments/freqai_rl_stage2_5_1",
    "experiments/freqai_rl_stage2_5_2",
]
CODE_TREE_INCLUDE_FILES = [
    "user_data/freqaimodels/RouteCModel.py",
    "user_data/strategies/RouteCStrategy.py",
]
# 递归遍历时跳过的目录名(运行时输出/缓存/模型二进制)
CODE_TREE_EXCLUDE_DIR_NAMES = {
    "__pycache__", "runtime", "logs", "artifacts",
    "backtesting_predictions", "tensorboard", "models",
}
CODE_TREE_SUFFIXES = {".py", ".json"}

# 规范化配置时移除的键(纯运行时输出/自指字段)
CONFIG_STRIP_PATHS = [
    ("freqai", "identifier"),  # identifier 由指纹生成,避免循环
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    return sha256_bytes(path.read_bytes())


def compute_fingerprint(parts: dict[str, Any]) -> str:
    """对规范化 JSON(canonical,排序键)计算 SHA-256 指纹。"""
    canonical = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_bytes(canonical.encode("utf-8"))


def build_identifier(prefix: str, fingerprint: str) -> str:
    """可读前缀 + 哈希短值,例如 stage251-rc-3fa92b1c7d。"""
    return f"{prefix}-{fingerprint[:10]}"


# ---------------------------------------------------------------- 代码树哈希
def _iter_code_files(root: Path, include_dirs: list[str], include_files: list[str]):
    files: list[Path] = []
    for rel_dir in include_dirs:
        d = root / rel_dir
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix not in CODE_TREE_SUFFIXES:
                continue
            if any(part in CODE_TREE_EXCLUDE_DIR_NAMES for part in p.relative_to(root).parts):
                continue
            files.append(p)
    for rel_file in include_files:
        p = root / rel_file
        if p.is_file():
            files.append(p)
    return sorted(set(files), key=lambda p: str(p))


def code_tree_hash(
    project_root: str | Path,
    include_dirs: list[str] | None = None,
    include_files: list[str] | None = None,
) -> dict[str, Any]:
    """对第一方代码生成稳定 tree hash(内容哈希,不用修改时间)。"""
    root = Path(project_root)
    files = _iter_code_files(
        root,
        include_dirs or CODE_TREE_INCLUDE_DIRS,
        include_files or CODE_TREE_INCLUDE_FILES,
    )
    file_hashes = {str(p.relative_to(root)).replace("\\", "/"): sha256_file(p) for p in files}
    return {
        "tree_hash": sha256_bytes(
            json.dumps(file_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "files": file_hashes,
        "n_files": len(file_hashes),
    }


# ------------------------------------------------------------ 配置规范化
def strip_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    """深拷贝并移除运行时输出字段(identifier 等),返回可哈希的规范化输入。"""
    import copy

    c = copy.deepcopy(config)
    for path in CONFIG_STRIP_PATHS:
        node = c
        for key in path[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return c


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """排序键的规范化 dict(json.dumps(sort_keys=True) 的字典形态)。"""
    return json.loads(json.dumps(strip_runtime_config(config), sort_keys=True))


def config_hash(config: dict[str, Any]) -> str:
    return compute_fingerprint(normalize_config(config))


# ------------------------------------------------------------ 数据范围哈希
def data_scope_hash(
    data_file: str | Path,
    eval_end: pd.Timestamp,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """哈希数据文件中所有 date < eval_end 的行。

    覆盖评估区间 + 全部训练数据 + startup/预热数据;
    不受评估结束之后新增 K 线影响。单交易对单周期(BTC/USDT 1h)阶段够用,
    后续加入其他周期/币种时每个实际数据文件都必须进入哈希。
    """
    data_file = Path(data_file)
    df = pd.read_feather(data_file)
    cols = columns or ["date", "open", "high", "low", "close", "volume"]
    sl = df[df["date"] < eval_end]
    if sl.empty:
        raise RuntimeError(f"date < {eval_end} 的数据为空:{data_file}")
    payload = sl[cols].to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    return {
        "source_file": data_file.name,
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "rows_hashed": int(len(sl)),
        "first_date": str(sl["date"].min()),
        "last_hashed_date": str(sl["date"].max()),
        "columns": cols,
    }


def eval_slice_info(
    data_file: str | Path, eval_start: pd.Timestamp, eval_end: pd.Timestamp
) -> dict[str, Any]:
    """评估区间行数(诊断信息,与 data_scope_hash 配套记录)。"""
    df = pd.read_feather(data_file)
    sl = df[(df["date"] >= eval_start) & (df["date"] < eval_end)]
    return {
        "eval_rows": int(len(sl)),
        "eval_start": str(eval_start),
        "eval_end": str(eval_end),
    }


# ------------------------------------------------------------ 依赖版本
def dependency_versions() -> dict[str, str]:
    """import 后实测的关键依赖版本(不从文档手填)。"""
    import sklearn  # noqa: F401  (scikit-learn)
    import stable_baselines3
    import torch
    import gymnasium
    import numpy
    import ccxt
    import freqtrade

    return {
        "python": sys.version.split()[0],
        "os": platform.platform(),
        "freqtrade": freqtrade.__version__,
        "stable_baselines3": stable_baselines3.__version__,
        "gymnasium": gymnasium.__version__,
        "torch": torch.__version__,
        "numpy": numpy.__version__,
        "pandas": pd.__version__,
        "scikit-learn": sklearn.__version__,
        "ccxt": ccxt.__version__,
    }


# ------------------------------------------------------------ 兼容入口
def collect_code_hashes(project_root: str | Path, files: list[str] | None = None) -> dict[str, str]:
    """阶段 2.5 兼容入口:按给定相对路径列表读单文件哈希。

    files 为 None 时等价于 code_tree_hash 的完整文件清单(新代码请用 code_tree_hash)。
    """
    root = Path(project_root)
    if files is None:
        return dict(code_tree_hash(project_root)["files"])
    return {rel: sha256_file(root / rel) for rel in files}
