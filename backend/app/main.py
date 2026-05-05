"""FastAPI surface for the Agentic Workflow Management facade.

Endpoints:
  GET  /health                     liveness + appointment counts + strategy
  GET  /appointments               full list (dashboard's poll target)
  GET  /appointments/{id}          one detail
  GET  /exceptions                 currently-escalated subset (Exception Queue)
  POST /exceptions/{id}/resolve    concierge resolution (resumes graph)
  POST /admin/seed                 reset and reseed the store
  POST /admin/tick                 manually advance the orchestrator one stage
  POST /admin/strategy             hot-swap priority strategy
                                   body: {"name": "weighted_sum" | "llm_rule"}

Behaviors:
  • On startup, the lifespan seeds the store and starts a background tick
    loop that runs every TICK_INTERVAL_S seconds (default 4).
  • Manual /admin/tick is hybrid with the background loop — both share the
    store's internal lock, so they never overlap on the same appointment.
  • Resolutions accept resolution_type="decisional" | "informational" with
    optional payload; the orchestrator branches accordingly.

CORS is wide-open for dev. Production would lock this down.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.state import AppointmentState, ResolutionMode
from app.store import AppointmentStore
from app.strategies import make_strategy

# Module-level singleton. Lifespan seeds it on startup.
store = AppointmentStore()

TICK_INTERVAL_S = float(os.environ.get("IKS_TICK_INTERVAL_S", "4.0"))
DEFAULT_STRATEGY = os.environ.get("IKS_STRATEGY", "weighted_sum")

_tick_task: Optional[asyncio.Task] = None


async def _tick_loop() -> None:
    """Background task: ticks the orchestrator on a fixed interval. Errors
    are logged to stderr but never crash the loop."""
    while True:
        try:
            await store.tick()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[tick] error: {e!r}", file=sys.stderr)
        await asyncio.sleep(TICK_INTERVAL_S)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _tick_task
    await store.seed()
    store.set_strategy(make_strategy(DEFAULT_STRATEGY))
    _tick_task = asyncio.create_task(_tick_loop())
    try:
        yield
    finally:
        if _tick_task is not None:
            _tick_task.cancel()
            try:
                await _tick_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="IKS Agentic Workflow Facade",
    description=(
        "Demo backend for the medical-appointment agentic workflow case "
        "study. Six-stage pipeline orchestrated via LangGraph; two-mode "
        "concierge resolution (decisional and informational); pluggable "
        "priority scoring (WeightedSumStrategy default; LLMRuleStrategy "
        "available)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────
# Read endpoints
# ──────────────────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "stats": store.stats(),
        "strategy": store.strategy.name if store.strategy else None,
        "tick_interval_s": TICK_INTERVAL_S,
    }


@app.get("/appointments", response_model=list[AppointmentState])
def list_appointments() -> list[AppointmentState]:
    return store.list()


@app.get("/appointments/{appointment_id}", response_model=AppointmentState)
def get_appointment(appointment_id: str) -> AppointmentState:
    apt = store.get(appointment_id)
    if apt is None:
        raise HTTPException(
            status_code=404, detail=f"appointment not found: {appointment_id}"
        )
    return apt


@app.get("/exceptions", response_model=list[AppointmentState])
def list_exceptions() -> list[AppointmentState]:
    return store.exceptions()


# ──────────────────────────────────────────────────────────────────────────
# Concierge resolution
# ──────────────────────────────────────────────────────────────────────────


class ResolutionRequest(BaseModel):
    """Body for POST /exceptions/{id}/resolve.

    Mirrors the orchestrator's exception-node resume payload contract.
    `resolution_type` defaults to "decisional"; informational resolutions
    must include a `payload` (or omit it; the agent's re-run will see None
    and behave as if no extra data was supplied)."""

    note: str = Field(..., min_length=1)
    resolver_id: str = "concierge_demo"
    resolution_type: ResolutionMode = "decisional"
    payload: dict[str, Any] | None = None


@app.post(
    "/exceptions/{appointment_id}/resolve",
    response_model=AppointmentState,
)
async def resolve_exception(
    appointment_id: str, body: ResolutionRequest
) -> AppointmentState:
    try:
        return await store.resolve(appointment_id, body.model_dump())
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────
# Admin (demo control)
# ──────────────────────────────────────────────────────────────────────────


@app.post("/admin/seed")
async def admin_seed() -> dict:
    await store.seed()
    return {"status": "seeded", "stats": store.stats()}


@app.post("/admin/tick")
async def admin_tick() -> dict:
    """Manually advance the orchestrator one stage on the highest-priority
    pickable appointment. Returns the appointment_id ticked, or null if the
    pool was empty (no-op per orchestrator design)."""
    ticked = await store.tick()
    return {"ticked": ticked, "stats": store.stats()}


class StrategyRequest(BaseModel):
    name: str


@app.post("/admin/strategy")
def admin_set_strategy(body: StrategyRequest) -> dict:
    try:
        store.set_strategy(make_strategy(body.name))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"strategy": body.name}
