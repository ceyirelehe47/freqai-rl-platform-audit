import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"
ART.mkdir(parents=True, exist_ok=True)
