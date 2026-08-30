"""阶段 2.6.1 测试夹具:C1/C2/C3 课程生成器与资格闭环。"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
