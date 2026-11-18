"""WebSocket — stream a case's status snapshots until terminal.

Functional status streaming (polls the DB); true per-agent LangGraph
`astream_events` streaming is the Phase 8 bonus.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_repo
from app.core.constants import WS_MAX_SNAPSHOTS, WS_POLL_INTERVAL_S
from app.core.errors import NotFoundError
from app.schemas.enums import CaseStatus
from app.services.case_repository import CaseRepository

router = APIRouter(tags=["ws"])

_TERMINAL = {
    CaseStatus.APPROVED.value,
    CaseStatus.REJECTED.value,
    CaseStatus.ESCALATED.value,
}


@router.websocket("/ws/cases/{case_id}")
async def stream_case(
    websocket: WebSocket,
    case_id: str,
    repo: CaseRepository = Depends(get_repo),
) -> None:
    await websocket.accept()
    try:
        for _ in range(WS_MAX_SNAPSHOTS):
            detail = await repo.get_detail(case_id)
            await websocket.send_json(
                {
                    "case_id": case_id,
                    "status": detail.status,
                    "decision": detail.decision,
                    "agents": [o.agent for o in detail.agent_outputs],
                }
            )
            if detail.status in _TERMINAL:
                break
            await asyncio.sleep(WS_POLL_INTERVAL_S)
    except NotFoundError:
        await websocket.send_json({"case_id": case_id, "error": "not found"})
    except WebSocketDisconnect:
        return
    await websocket.close()
