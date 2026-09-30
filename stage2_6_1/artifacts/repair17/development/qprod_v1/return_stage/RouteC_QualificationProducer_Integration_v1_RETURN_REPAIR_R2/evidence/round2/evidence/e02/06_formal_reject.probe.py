import sys
sys.path.insert(0, "src")
from rl_curriculum.ppo262_qualified_input import (
    QualifiedInputError, load_qualified_input,
)
base = sys.argv[1]
auth = sys.argv[2]
try:
    load_qualified_input(base, authorization_path=auth,
                         expected_scope="formal")
    print("UNEXPECTED: formal scope loaded")
    raise SystemExit(1)
except QualifiedInputError as exc:
    print("formal-scope rejection OK:", str(exc)[:120])
    raise SystemExit(0)
