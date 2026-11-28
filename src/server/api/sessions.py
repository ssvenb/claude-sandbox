"""The sessions: started, listed, stopped, deleted (with what of their run to tidy up), and their plugins' commands."""
from typing import Optional

from api import models as m
from api.common import Conf, Route, conf, dumps, session
from fastapi import APIRouter, Depends

import server as core

router = APIRouter(route_class=Route)


@router.get("/api/sessions", response_model=m.Sessions)
def list_sessions():
    with core.lock:
        return {"sessions": [s.json() for s in core.sessions.values()]}


@router.post("/api/sessions", response_model=m.Session, status_code=201)
def create_session(req: m.NewSession, c: Conf = Depends(conf)):
    if req.project not in core.projects(c.projects_file):
        raise ValueError("not a configured project")
    s = core.start(req.project, req.kind, req.run_id, req.task, dumps(req.images))
    with core.lock:
        return s.json()


@router.get("/api/sessions/{sid}", response_model=m.Session)
def get_session(sid: str):
    s = session(sid)
    with core.lock:
        return s.json()


@router.delete("/api/sessions/{sid}", response_model=m.Failed)
def delete_session(sid: str, req: Optional[m.Tidy] = None):
    """Gone from the list, stopped first if it still runs; with `tidy`, the urls of its run's items
    the page's user said yes to tidying up too (cleanup-offers). Says which failed."""
    s = session(sid)
    s.stop()
    with core.lock:
        offered = core.offers(s)
        core.drop(s)
    return {"failed": core.tidy(s, req.tidy if req else [], offered)}


@router.post("/api/sessions/{sid}/stop", response_model=m.Ok)
def stop_session(sid: str):
    """Its container goes, its entry stays: to read, to resume."""
    session(sid).stop()
    return {}


@router.get("/api/sessions/{sid}/cleanup-offers", response_model=m.Offers)
def cleanup_offers(sid: str):
    """What its page asks about before deleting it, one yes/no each. Described afresh first: the
    pull request a run opened a moment ago is offered too, and one closed or merged since is not."""
    s = session(sid)
    core.describe(s.project, keep=True)
    with core.lock:
        found = core.offers(s)
    return {"offers": [{k: i.get(k) for k in ("url", "ref", "title")}
                       | {"ask": str(i["on_delete"].get("ask") or f"Tidy up {i.get('ref') or i.get('title')} too?")}
                       for i in found]}


@router.get("/api/sessions/{sid}/plugins/{plugin}/commands/{name}", response_model=m.PluginResult)
def run_plugin_command(sid: str, plugin: str, name: str):
    s = session(sid)
    return {"result": core.plugin_command(s.project, s.run_id, plugin, name)}
