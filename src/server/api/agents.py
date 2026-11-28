"""An agent's sign-in on this machine: a link to follow, the code it ends on, whether it holds."""
from api import models as m
from api.common import Route
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

import server as core

router = APIRouter(route_class=Route)


@router.get("/api/agents/{agent}/sign-in", response_class=RedirectResponse, status_code=302)
def start_sign_in(agent: str):
    """A link the page follows (a fetch's window.open would be a blocked popup), so a GET that
    starts the sign-in: on to the page it prints."""
    return RedirectResponse(core.sign_in(agent), 302)


@router.post("/api/agents/{agent}/sign-in", response_model=m.Ok)
def finish_sign_in(agent: str, req: m.Code):
    core.sign_in_code(agent, req.code)
    return {}


@router.get("/api/agents/{agent}/sign-in-status", response_model=m.SignInStatus)
def sign_in_status(agent: str):
    return {"signedIn": core.signed_in(agent)}
