"""C3 finite-reserve generation for R17 calibration corpora (GOAL §4 contract).

Main coordinates are the standard grid; reserve coordinates are derived
deterministically from (rung, idx, slot) and declared in the journal BEFORE
any generation. Only a fully evidenced C3 structural exhaustion — exactly
max_attempts attempt envelopes, every attempt rejected with reasons from the
frozen C3_REJECT_VOCAB, no unexpected exception on any attempt — permits the
next predeclared reserve coordinate for that slot. Unknown exceptions, C1
generation and exhausted budgets are never reclassified or silently retried:
the original error propagates and the chain aborts per §11.

R6 frozen implementations are not modified; this wraps generation at the R17
layer only. The supervised corpus keeps strict no-reserve semantics on
purpose: its train/test split is defined by pair index (§8.3), so index
substitution would silently move a train slot into the test set; a structural
failure there remains fatal and is reported as such.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

RESERVE_CONTRACT = "cur261-r17-c3-finite-reserve-v1"
RESERVE_INDEX_BASE = 1000
RESERVE_SLOTS_PER_COORDINATE = 2


def reserve_index(idx: int, slot: int) -> int:
    """Deterministic predeclared reserve coordinate for (main idx, slot)."""
    if not (0 <= idx < RESERVE_INDEX_BASE) or not (0 <= slot
            < RESERVE_SLOTS_PER_COORDINATE):
        raise ValueError("reserve coordinate out of declared range")
    return RESERVE_INDEX_BASE + idx * RESERVE_SLOTS_PER_COORDINATE + slot


def reserve_declaration(namespace: str, pairs_per_rung: int) -> dict[str, Any]:
    """The coordinate/budget declaration written before any generation."""
    from rl_curriculum.curriculum261_c3 import C3_REJECT_VOCAB
    return {
        "contract": RESERVE_CONTRACT,
        "namespace": namespace,
        "family": "c3_cost",
        "pairs_per_rung": int(pairs_per_rung),
        "main_indices": list(range(int(pairs_per_rung))),
        "reserve_index_base": RESERVE_INDEX_BASE,
        "reserve_slots_per_coordinate": RESERVE_SLOTS_PER_COORDINATE,
        "reserve_indices": {
            f"{rung}/{idx}": [reserve_index(idx, slot)
                              for slot in range(RESERVE_SLOTS_PER_COORDINATE)]
            for rung in ("D0", "D1", "D2", "D3")
            for idx in range(int(pairs_per_rung))},
        "allowed_rejection_vocabulary": list(C3_REJECT_VOCAB),
        "unknown_exception_policy": "never reclassified; chain aborts (§11)",
        "supervised_corpus_policy": "strict, no reserve (pair-index split §8.3)",
    }


def _reasons_from_vocabulary(reasons: Any) -> bool:
    from rl_curriculum.curriculum261_c3 import C3_REJECT_VOCAB
    vocab = set(C3_REJECT_VOCAB)
    if not isinstance(reasons, list) or not reasons:
        return False
    for reason in reasons:
        if not isinstance(reason, str):
            return False
        code = reason.split(":", 1)[1] if ":" in reason else reason
        if code not in vocab:
            return False
    return True


def structural_exhaustion_evidence(exc: BaseException) -> dict | None:
    """Fully evidenced C3 structural exhaustion, or None.

    Mirrors the R17 p52 diagnosis v2 completeness rules: never conclude
    "structural" from an empty or partial evidence set.
    """
    envelopes = getattr(exc, "attempt_envelopes", None)
    if not isinstance(envelopes, list) or not envelopes:
        return None
    call = getattr(exc, "call_envelope", None)
    max_attempts = None
    if isinstance(call, dict):
        max_attempts = call.get("max_attempts")
    if not isinstance(max_attempts, int) or max_attempts <= 0:
        return None
    if len(envelopes) != max_attempts:
        return None
    attempts_seen = []
    reasons_by_attempt = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            return None
        index = envelope.get("attempt_index")
        if type(index) is not int:
            return None
        if envelope.get("accepted") is not False:
            return None
        if envelope.get("exception") not in (None, ""):
            return None
        reasons = envelope.get("rejection_reasons")
        if not _reasons_from_vocabulary(reasons):
            return None
        attempts_seen.append(index)
        reasons_by_attempt.append(list(reasons))
    if sorted(attempts_seen) != list(range(max_attempts)):
        return None
    identity = {
        "family": envelopes[0].get("family"),
        "rung": envelopes[0].get("rung"),
        "pair_index": envelopes[0].get("pair_index"),
        "namespace": envelopes[0].get("namespace"),
    }
    return {
        "contract": RESERVE_CONTRACT,
        "n_attempts": max_attempts,
        "reasons_by_attempt": reasons_by_attempt,
        "coordinate": identity,
        "evidence_digest": hashlib.sha256(
            json.dumps({"attempts": attempts_seen,
                        "reasons": reasons_by_attempt,
                        "identity": identity},
                       sort_keys=True).encode("utf-8")).hexdigest(),
    }


def generate_c3_pair_with_finite_reserve(
        rung: str, idx: int, *, namespace: str, override: Any,
        reserve_log: list | None = None) -> Any:
    """generate_pair for c3_cost under the finite-reserve contract."""
    from rl_curriculum.curriculum261_api import PairGenerationError
    from rl_curriculum.curriculum261_pairs import generate_pair

    try:
        return generate_pair("c3_cost", rung, idx, namespace=namespace,
                             rung_params_override=override)
    except PairGenerationError as exc:
        evidence = structural_exhaustion_evidence(exc)
        if evidence is None:
            raise
        last = exc
        if reserve_log is not None:
            reserve_log.append({
                "event": "main_structural_exhaustion",
                "namespace": namespace, "rung": rung, "main_index": idx,
                "evidence": evidence})
        for slot in range(RESERVE_SLOTS_PER_COORDINATE):
            ridx = reserve_index(idx, slot)
            try:
                record = generate_pair(
                    "c3_cost", rung, ridx, namespace=namespace,
                    rung_params_override=override)
            except PairGenerationError as exc2:
                evidence2 = structural_exhaustion_evidence(exc2)
                if evidence2 is None:
                    raise
                last = exc2
                if reserve_log is not None:
                    reserve_log.append({
                        "event": "reserve_structural_exhaustion",
                        "namespace": namespace, "rung": rung,
                        "main_index": idx, "reserve_index": ridx,
                        "slot": slot, "evidence": evidence2})
                continue
            if reserve_log is not None:
                reserve_log.append({
                    "event": "reserve_substituted",
                    "namespace": namespace, "rung": rung,
                    "main_index": idx, "reserve_index": ridx,
                    "slot": slot,
                    "effective_pair_index": ridx})
            return record
        raise last
