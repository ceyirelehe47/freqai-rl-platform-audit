import sys
sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_semantic_contract_digest,
)
print(sys.argv[1], cue_semantic_contract_digest())
