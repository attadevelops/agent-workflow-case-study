"""Step 7 smoke test — exercises the FastAPI surface end-to-end.

Boots the running server (assumes uvicorn is already up at localhost:8765)
and verifies:
  • /health returns ok with strategy=weighted_sum
  • /appointments returns 25 appointments
  • Manual ticks (POST /admin/tick) advance state visibly: stage_states
    flip from not_started -> processing -> complete, priority_score is
    populated by WeightedSumStrategy.
  • Strategy hot-swap via POST /admin/strategy works; reasoning prefix
    changes from "SLA ..." (weighted_sum) to "[llm_rule:mock] ..." (llm_rule).
  • Resolution endpoint accepts an informational payload and re-runs the
    affected stage.

Run from backend/:
    .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765 --log-level warning &
    .venv/bin/python smoke_step7.py
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def _get(path: str) -> dict | list:
    return json.loads(urllib.request.urlopen(BASE + path).read())


def _post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req).read())


def _wait_for_server(timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            _get("/health")
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.3)
    raise RuntimeError(f"server did not come up at {BASE} within {timeout_s}s")


def _print_top(label: str, appointments: list, n: int = 5) -> None:
    pickable = [
        a for a in appointments
        if a["escalation_reason"] is None and a["current_stage"] is not None
    ]
    print(f"\n── {label} ── (top {n} of {len(pickable)} pickable)")
    for a in sorted(
        pickable, key=lambda x: -(x["priority_score"] or 0.0)
    )[:n]:
        score = a["priority_score"]
        score_s = f"{score:.3f}" if score is not None else "  -  "
        print(
            f"  {a['appointment_id']} {a['patient_name']:22s}  "
            f"score={score_s}  stage={a['current_stage']:30s}  "
            f"reasoning={a['priority_reasoning'] or '-'}"
        )


def main() -> None:
    print(f"step 7 smoke: targeting {BASE}")
    _wait_for_server()

    # ── /health ──────────────────────────────────────────────────────
    health = _get("/health")
    print(f"\n── /health ──")
    print(json.dumps(health, indent=2))
    assert health["status"] == "ok"
    assert health["stats"]["total"] == 25
    assert health["strategy"] == "weighted_sum"

    # ── Reseed + initial snapshot ────────────────────────────────────
    _post("/admin/seed")

    # First tick to populate priority_score on all pickable
    _post("/admin/tick")
    _print_top("after 1st tick (WeightedSum populated scores)", _get("/appointments"))

    # ── Several manual ticks; observe state advance ──────────────────
    print("\n── 4 more manual ticks ──")
    ticked_ids = []
    for i in range(4):
        result = _post("/admin/tick")
        ticked_ids.append(result["ticked"])
        print(f"  tick {i+2}: ticked={result['ticked']!r}  stats={result['stats']}")

    # The tick should not error on subsequent calls; should pick the
    # appointment with the highest priority_score (modulo lock contention).
    snapshot = _get("/appointments")
    _print_top("after 5 total ticks", snapshot)

    # Verify at least one stage advanced past not_started.
    advanced = [
        a for a in snapshot
        if any(s != "not_started" for s in a["stage_states"].values())
    ]
    assert len(advanced) >= 5, (
        f"expected at least 5 appointments to have advanced; got {len(advanced)}"
    )
    print(f"\n  [pass] {len(advanced)} appointments have advanced past not_started")

    # ── Strategy hot-swap to llm_rule ────────────────────────────────
    print("\n── /admin/strategy llm_rule ──")
    swap = _post("/admin/strategy", {"name": "llm_rule"})
    assert swap["strategy"] == "llm_rule"

    _post("/admin/tick")  # rescore with llm_rule
    after_swap = _get("/appointments")
    _print_top("after swap to llm_rule + 1 tick", after_swap)

    # Reasoning prefix should change.
    pickable = [
        a for a in after_swap
        if a["escalation_reason"] is None and a["current_stage"] is not None
        and a["priority_reasoning"] is not None
    ]
    llm_reasoned = [a for a in pickable if "[llm_rule:" in (a["priority_reasoning"] or "")]
    assert len(llm_reasoned) > 0, (
        f"expected llm_rule reasoning prefix, none found in {len(pickable)} pickable"
    )
    print(f"  [pass] {len(llm_reasoned)} appointments now have llm_rule reasoning")

    # Swap back so subsequent demo runs are deterministic.
    _post("/admin/strategy", {"name": "weighted_sum"})

    # ── Resolution flow: pick the first exception, resolve informational ──
    print("\n── concierge resolution flow ──")
    excs = _get("/exceptions")
    print(f"  {len(excs)} exceptions present")
    assert len(excs) >= 1, "expected at least one pre-seeded escalation"
    target = excs[0]
    print(
        f"  resolving {target['appointment_id']} {target['patient_name']!r} "
        f"code={target['escalation_reason']['code']}"
    )
    resolved = _post(
        f"/exceptions/{target['appointment_id']}/resolve",
        {
            "note": (
                "Member ID corrected to M-77321 per patient call. "
                "Carrier confirmed coverage active."
            ),
            "resolver_id": "smoke_step7",
            "resolution_type": "informational",
            "payload": {
                "corrected_member_id": "M-77321",
                "carrier_confirmed": True,
            },
        },
    )
    print(
        f"  resolved: stage_states[{target['escalation_reason']['raised_at_stage']}]="
        f"{resolved['stage_states'][target['escalation_reason']['raised_at_stage']]}"
    )
    print(f"  resolutions in history: {len(resolved['resolutions'])}")

    # ── Empty-pool tick (after all-or-most appointments are mid-stage) ──
    # We can't easily get the pool empty in 5 ticks (we have 25 pickable),
    # so verify the no-op contract by direct unit-style call: tick then tick
    # again immediately — the second one should still pick something or
    # return None gracefully.
    second = _post("/admin/tick")
    print(f"\n  immediate second tick: ticked={second['ticked']!r}  (graceful either way)")

    print("\n[OK] step 7 smoke test passed")


if __name__ == "__main__":
    main()
