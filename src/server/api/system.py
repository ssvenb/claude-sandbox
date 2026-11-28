"""The dashboard's one-call view, and the server's own update."""
from api import models as m
from api.common import Conf, Route, conf
from fastapi import APIRouter, Depends

import server as core

router = APIRouter(route_class=Route)


@router.get("/api/state", response_model=m.AppState)
def get_state(c: Conf = Depends(conf)):
    """Everything the dashboard draws, in one call."""
    with core.lock:
        live = [s.json() for s in core.sessions.values()]
    return {"projects": core.projects(c.projects_file), "projects_file": str(c.projects_file), "sessions": live}


@router.post("/api/server/sync", response_model=m.Synced)
def post_sync(c: Conf = Depends(conf)):
    return core.sync(c.bind)
