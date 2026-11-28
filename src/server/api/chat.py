"""A session's conversation: its events as they come, and what the page tells its agent."""
import asyncio
import json

from api import models as m
from api.common import Route, dumps, session, tell
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

import server as core

router = APIRouter(route_class=Route)


KEEPALIVE = 15  # seconds between keepalives on a chat's events: how soon a closed tab is let go


class Listener:
    """A page's event stream: fed by the session's threads, read in the server's event loop."""

    def __init__(self):
        self.loop, self.q = asyncio.get_running_loop(), asyncio.Queue()

    def put(self, event):
        try:
            self.loop.call_soon_threadsafe(self.q.put_nowait, event)
        except RuntimeError:  # the server has gone
            pass


@router.get("/api/sessions/{sid}/events", response_class=StreamingResponse)
async def get_events(sid: str):
    """A chat's events, as server-sent events: the conversation so far in one snapshot, then each
    event as it comes."""
    s = session(sid)
    listener = Listener()
    with core.lock:  # snapshot and subscription in one step, so no event is lost or doubled
        first = json.dumps(s.snapshot())
        if s.exit is None:
            s.listeners.append(listener)
        else:
            listener.q.put_nowait(None)

    async def stream():
        try:
            yield f"data: {first}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(listener.q.get(), KEEPALIVE)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # what keeps a proxy from timing it out
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:  # the stream ended, or its tab was closed
            with core.lock:
                if listener in s.listeners:
                    s.listeners.remove(listener)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/api/sessions/{sid}/messages", response_model=m.Ok)
def post_message(sid: str, req: m.Message):
    session(sid).prompt(req.text, dumps(req.images), dumps(req.files), req.nonce)
    return {}


@router.post("/api/sessions/{sid}/interrupt", response_model=m.Ok)
def interrupt(sid: str):
    return tell(sid, {"type": "interrupt"})


@router.post("/api/sessions/{sid}/questions/{ask}/answer", response_model=m.Ok)
def answer_question(sid: str, ask: str, req: m.Answer):
    """{answers} or {cancel: true}."""
    return tell(sid, {"type": "answer", "id": ask, **req.model_dump(exclude_unset=True)})


@router.put("/api/sessions/{sid}/model", response_model=m.Ok)
def put_model(sid: str, req: m.ModelPick):
    return tell(sid, {"type": "model", "id": req.id})


@router.put("/api/sessions/{sid}/effort", response_model=m.Ok)
def put_effort(sid: str, req: m.EffortPick):
    return tell(sid, {"type": "effort", "level": req.level})


@router.delete("/api/sessions/{sid}/tasks/{task}", response_model=m.Ok)
def stop_task(sid: str, task: str):
    """Stops a task its agent runs in the background."""
    return tell(sid, {"type": "task", "id": task})


@router.post("/api/sessions/{sid}/calls/{call}/background", response_model=m.Ok)
def background_call(sid: str, call: str):
    """Sends the task a tool call waits on to the background: the call returns, the task runs on."""
    return tell(sid, {"type": "background", "id": call})


@router.post("/api/sessions/{sid}/sides", response_model=m.SideId, status_code=201)
def create_side(sid: str, req: m.Text):
    """A side chat, its first question asked; answers with its id."""
    return {"id": session(sid).side(None, req.text)}


@router.post("/api/sessions/{sid}/sides/{side}/messages", response_model=m.SideId)
def post_side_message(sid: str, side: str, req: m.Text):
    return {"id": session(sid).side(side, req.text)}


@router.post("/api/sessions/{sid}/sides/{side}/interrupt", response_model=m.Ok)
def interrupt_side(sid: str, side: str):
    return tell(sid, {"type": "interrupt", "side": side})


@router.delete("/api/sessions/{sid}/sides/{side}", response_model=m.Ok)
def close_side(sid: str, side: str):
    session(sid).side(side, None, close=True)
    return {}
