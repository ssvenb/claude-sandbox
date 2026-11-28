"""Your authentications, every secret masked, and their files."""
from typing import Any, Dict

from api import models as m
from api.common import Route
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

import server as core

router = APIRouter(route_class=Route)


@router.get("/api/auth", response_model=m.AuthConfig)
def get_auth():
    return core.read_auth()


@router.put("/api/auth", response_model=m.AuthConfig)
def put_auth(entries: Dict[str, Any]):
    core.write_auth(entries)
    return core.read_auth()


@router.put("/api/auth/{name}/files/{field}", response_model=m.AuthFileState)
async def upload_auth_file(name: str, field: str, request: Request):
    """The body: the file itself."""
    return await run_in_threadpool(core.put_auth_file, name, field, await request.body())


@router.delete("/api/auth/{name}/files/{field}", response_model=m.AuthFileState)
def delete_auth_file(name: str, field: str):
    return core.put_auth_file(name, field, None)
