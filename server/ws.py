import asyncio

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, code: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.setdefault(code, set()).add(ws)

    async def disconnect(self, code: str, ws: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(code)
            if sockets is None:
                return
            sockets.discard(ws)
            if not sockets:
                del self._connections[code]

    async def broadcast(self, code: str, payload: dict) -> None:
        async with self._lock:
            sockets = list(self._connections.get(code, ()))
        if not sockets:
            return

        results = await asyncio.gather(
            *(ws.send_json(payload) for ws in sockets),
            return_exceptions=True,
        )
        dead = [ws for ws, r in zip(sockets, results) if isinstance(r, Exception)]
        if dead:
            async with self._lock:
                if code in self._connections:
                    self._connections[code].difference_update(dead)
                    if not self._connections[code]:
                        del self._connections[code]

    def connection_count(self, code: str) -> int:
        return len(self._connections.get(code, ()))
