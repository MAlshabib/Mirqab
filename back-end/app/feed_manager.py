"""
Relays JPEG frame bytes from a field unit sender to all HQ viewers watching that unit.
Each unit has one sender slot and N viewers.
"""
from fastapi import WebSocket


class FeedManager:
    def __init__(self) -> None:
        self._viewers: dict[str, list[WebSocket]] = {}

    def add_viewer(self, unit_id: str, ws: WebSocket) -> None:
        self._viewers.setdefault(unit_id, []).append(ws)

    def remove_viewer(self, unit_id: str, ws: WebSocket) -> None:
        lst = self._viewers.get(unit_id, [])
        if ws in lst:
            lst.remove(ws)

    async def push_frame(self, unit_id: str, frame: bytes) -> None:
        viewers = list(self._viewers.get(unit_id, []))
        dead: list[WebSocket] = []
        for ws in viewers:
            try:
                await ws.send_bytes(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove_viewer(unit_id, ws)

    def viewer_count(self, unit_id: str) -> int:
        return len(self._viewers.get(unit_id, []))


feed_manager = FeedManager()
