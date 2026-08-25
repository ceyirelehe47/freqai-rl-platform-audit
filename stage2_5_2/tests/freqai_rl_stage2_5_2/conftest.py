"""阶段 2.5.2 测试包:路径注入(与阶段 2.5/2.5.1 conftest 同一约定)。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "src", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
