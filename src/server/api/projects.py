"""The projects: their files, what their plugins describe, their settings."""
from typing import Any, Dict

from api import models as m
from api.common import Conf, Route, conf, known
from fastapi import APIRouter, Depends

import server as core

router = APIRouter(route_class=Route)


@router.get("/api/projects", response_model=m.Projects)
def list_projects(c: Conf = Depends(conf)):
    return {"projects": core.projects(c.projects_file)}


@router.post("/api/projects", response_model=m.Created, status_code=201)
def create_project(req: m.NewProject):
    core.add_project(req.name, req.repo)
    return {"name": req.name}


@router.get("/api/projects/{name}", response_model=m.ProjectInfo)
def get_project(name: str, c: Conf = Depends(conf)):
    """What its plugins describe: lists, items, its agent."""
    return core.describe(known(c, name))


@router.delete("/api/projects/{name}", response_model=m.Ok)
def remove_project(name: str, c: Conf = Depends(conf)):
    core.delete_project(known(c, name))
    return {}


@router.get("/api/projects/{name}/config", response_model=m.ProjectConfig)
def get_config(name: str, c: Conf = Depends(conf)):
    return core.read_config(known(c, name))


@router.put("/api/projects/{name}/config", response_model=m.ProjectConfig)
def put_config(name: str, config: Dict[str, Any], c: Conf = Depends(conf)):
    core.write_config(known(c, name), config)
    return core.read_config(name)
