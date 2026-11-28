"""What the API's routes share: the server they run in (Conf), their route class, and finding what a
request names (a project, a session)."""
from fastapi import Request
from fastapi.routing import APIRoute

import server as core


class Conf:
    """What one server is: the names it answers to, whether it relays demo subdomains, where its
    projects are, where it listens. Several can run in one process (the tests run a demo beside one)."""

    def __init__(self, hosts, subdomains, projects_file, bind):
        self.hosts, self.subdomains, self.projects_file, self.bind = hosts, subdomains, projects_file, bind


def conf(request: Request) -> Conf:
    return request.scope["sandbox"]


class Route(APIRoute):
    """A route of ours: it answers with the fields of its shape the server set, never a null for
    one it did not (models.py)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **{**kwargs, "response_model_exclude_unset": True})


def known(c, name):
    if name not in core.projects(c.projects_file):
        raise core.NotFound(f"no project {name!r}")
    return name


def session(sid):
    with core.lock:
        s = core.sessions.get(sid)
    if s is None:
        raise core.NotFound("no such session")
    return s


def tell(sid, command):
    """A command for a chat's bridge, which knows what it means."""
    session(sid).tell(command)
    return {}


def dumps(items):
    return None if items is None else [i.model_dump() for i in items]
