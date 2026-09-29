# Evidence scope

This is ChatGPT's independent review evidence, NOT an Agent RETURN or a PASS certificate.

- `REVIEW.md` / `START_REPAIR.txt`: decision and narrowly scoped repair instructions, independent Flash reviewer required.
- `probes/run_components.py` / `RESULT.json`: actual local execution of unmodified C5 target modules with explicit recorded-valid external dependency capsules. 26 checks, 20 meet expectations, 6 demonstrate two missing checks. No native data, fit, PPO load, or optimizer updates.
- `probes/reproduce_remaining_native.py`: ready for already installed WSL dependencies; syntax-checked here, NOT run on WSL here. Uses a sentinel at PPO.load and writes only isolated copies.
- `validation/ARCHIVE.json`: actual full uploaded archive CRC/path/type/SHA checks.
- `validation/REGRESSION_ARCHIVES.json`: actual v1–v4 archived JUnit/collection checks and detection that v5 directories are missing.
- `received/`: a clearly selected source/input subset of the uploaded RETURN for component reproducibility, NOT the full RETURN.
- `reference_task/`: actual original task requirements and no-time-limit supplement.

Re-run local component script from the extracted evidence root with the local dependencies numpy/pandas/torch available. It creates a fresh timestamped case directory. It does not recreate WSL or pretend its capsules are native numerical validators.
Full `verify_archive.py` additionally needs the unchanged user uploads at the paths given in that script; these are not duplicated into this evidence ZIP.
