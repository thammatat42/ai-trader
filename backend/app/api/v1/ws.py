"""
WebSocket endpoint for real-time updates.
"""

import asyncio

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.core.dependencies import get_current_user
from app.core.security import decode_token
from app.models.user import User

router = APIRouter()
logger = structlog.get_logger("websocket")


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, client_id: str):
        await ws.accept()
        self._connections[client_id] = ws
        logger.info("ws_connected", client_id=client_id, total=len(self._connections))

    def disconnect(self, client_id: str):
        self._connections.pop(client_id, None)
        logger.info("ws_disconnected", client_id=client_id, total=len(self._connections))

    async def broadcast(self, event: str, data: dict):
        dead = []
        for cid, ws in self._connections.items():
            try:
                await ws.send_json({"event": event, "data": data})
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    @property
    def active_count(self) -> int:
        return len(self._connections)


ws_manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Authenticate via query param: ?token=<jwt>
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await ws.close(code=4001, reason="Invalid token")
        return

    client_id = payload.get("sub", "unknown")
    await ws_manager.connect(ws, client_id)

    try:
        while True:
            # Keep connection alive; client can send pings
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"event": "pong", "data": {}})
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
