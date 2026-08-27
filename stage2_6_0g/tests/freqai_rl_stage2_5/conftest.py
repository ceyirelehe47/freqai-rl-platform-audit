"""阶段 2.5 测试公共配置:注入项目 src 到 sys.path。"""

import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJ_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
TESTS_DIR = PROJ_ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
