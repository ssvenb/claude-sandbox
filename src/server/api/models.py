"""The API's shapes: what each route of src/server/server.py takes and answers.

FastAPI checks a request against them and an answer too, and publishes them as OpenAPI
(/api/openapi.json). The page's TypeScript types are generated from that: web/src/api/schema.ts
(`npm run api-types` in web; tests/test_web.py fails while it is stale).

An answer carries only the fields a shape names, and of those only the ones the server set (every
route answers with exclude_unset), so a field that is optional here is absent rather than null.
What a chat's event stream sends is not in here: server-sent events are not OpenAPI's (see
web/src/api/events.ts).
"""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Shape(BaseModel):
    model_config = ConfigDict(extra="ignore")


SessionKind = Literal["run", "resume"]
SessionStatus = Literal["starting", "working", "idle", "question"]
ItemStatus = Literal["ok", "fail", "pending", "done"]


# ---- what the routes take ------------------------------------------------------------------------

class NewProject(Shape):
    name: str
    repo: Optional[str] = None


class Picture(Shape):
    """A picture pasted into a message: its media type and its bytes in base64."""
    type: str
    data: str
    name: Optional[str] = None


class Upload(Shape):
    """A file attached to a message that is not a picture: saved in the sandbox for the agent to read."""
    name: str
    data: str


class NewSession(Shape):
    project: str
    kind: SessionKind
    run_id: Optional[str] = None
    task: Optional[str] = None
    images: Optional[List[Picture]] = None
    ui: Literal["chat"] = Field("chat", description='Every session is a chat')


class Message(Shape):
    text: str
    images: Optional[List[Picture]] = None
    files: Optional[List[Upload]] = None
    nonce: Optional[str] = Field(None, description="The page's name for it: sent again, it is taken once")


class Answer(Shape):
    """{answers}, the pick for each question, or {cancel: true}."""
    answers: Optional[Dict[str, Any]] = None
    cancel: Optional[bool] = None


class Text(Shape):
    text: str


class ModelPick(Shape):
    id: str


class EffortPick(Shape):
    level: str


class Code(Shape):
    code: str


class Tidy(Shape):
    tidy: List[str] = Field([], description="The urls of the run's items to tidy up too (cleanup-offers)")


# ---- what they answer ----------------------------------------------------------------------------

class Ok(Shape):
    """Done: nothing more to say."""


class Created(Shape):
    name: str


class SideId(Shape):
    id: str


class Failed(Shape):
    failed: List[str] = Field(description='The urls whose tidying up failed')


class SignInStatus(Shape):
    signedIn: bool


class Synced(Shape):
    restarting: bool = Field(description='Under systemd: the server restarts itself')


class PluginResult(Shape):
    result: Any = Field(None, description="What the plugin's command printed; null where it has none")


class Start(Shape):
    label: str
    task: str


class Item(Shape):
    """Something a plugin lists for a project or ties to a run: a pull request, an issue, a published port."""
    url: str
    title: str
    ref: Optional[str] = None
    port: Optional[int] = Field(None, description="The port a running session serves it on: a live server (dev-server's demo)")
    up: Optional[bool] = Field(None, description='It answers yet: a demo is published before its server listens')
    note: Optional[str] = None
    status: Optional[ItemStatus] = None
    status_text: Optional[str] = None
    run_id: Optional[str] = None
    section: Optional[str] = None
    start: Optional[Start] = Field(None, description='A button that starts a session on `task`')


class ItemList(Shape):
    title: str
    items: List[Item]


class ProjectInfo(Shape):
    """What a project's plugins say about it (`run.sh --web`), as far as the page is concerned."""
    lists: List[ItemList]
    notes: List[str]
    agent: Optional[str] = None
    plugins: Optional[List[str]] = None
    run_items: Optional[List[Item]] = None
    session_items: Optional[List[Item]] = None


class Context(Shape):
    used: int
    max: int


class PlanItem(Shape):
    text: str
    status: Literal["pending", "active", "done"]


class Session(Shape):
    id: str
    project: str
    kind: SessionKind
    run_id: Optional[str]
    started: float
    exit: Optional[int] = Field(description='Its exit code once it has ended')
    status: Optional[SessionStatus] = Field(description='Null once it has ended')
    workspace: Optional[str] = Field(description='Where its checkout is mirrored on this machine, if anywhere')
    plugins: List[str] = Field(description="Its project's enabled plugins")
    items: List[Item]
    title: str
    activity: str
    said: str
    agent: Optional[str]
    model: Optional[str]
    cost: Optional[float]
    context: Optional[Context]
    waiting: int = Field(description='Messages kept until its agent is ready')
    todos: Optional[List[PlanItem]]


class AppState(Shape):
    projects: List[str]
    projects_file: str
    sessions: List[Session]


class Projects(Shape):
    projects: List[str]


class Sessions(Shape):
    sessions: List[Session]


class Offer(Shape):
    """What deleting a session offers to tidy up with it, a yes/no each."""
    url: str
    ask: str
    ref: Optional[str] = None
    title: Optional[str] = None


class Offers(Shape):
    offers: List[Offer]


SettingType = Literal["string", "path", "boolean", "enum", "integer", "text", "json", "list", "map", "object", "file"]


class SettingSpec(BaseModel):
    """One setting, as a manifest declares it: its type picks its control. A manifest may say more
    than the page reads: that goes along too."""
    # A field a manifest leaves out is absent, never null: `X = None` here, not Optional[X].
    model_config = ConfigDict(extra="allow")
    type: SettingType = None
    key: str = None
    env: str = None
    label: str = None
    description: str = None
    default: Any = Field(None, json_schema_extra={"tsType": "Json"})
    placeholder: str = None
    required: bool = None
    monospace: bool = None
    pattern: str = None
    min: float = None
    max: float = None
    choices: List[Union[str, float]] = None
    items: "SettingSpec" = None
    fields: List["SettingSpec"] = None
    title: str = None
    groupBy: str = Field(None, description="A list of objects shown in groups by this field's value")
    when: Dict[str, List[Any]] = Field(None, json_schema_extra={"tsType": "Record<string, Json[]>"}, description='Shown only while these settings hold one of these values')


class SettingsPart(Shape):
    name: str
    description: str = None
    settings: List[SettingSpec]


class PluginManifest(SettingsPart):
    defaultEnabled: bool
    requiredAgent: Optional[str] = None  # sent as null when a plugin names none
    requiredEnv: List[str] = None
    example: Any = Field(None, description='Its section of .claude-sandbox.example.json')


class Kernel(Shape):
    description: str = None
    settings: List[SettingSpec]


class ProjectConfig(Shape):
    file: str
    exists: bool
    config: Dict[str, Any] = Field(json_schema_extra={"tsType": "JsonObject"}, description="What the project's file holds")
    kernel: Kernel
    agents: List[SettingsPart]
    plugins: List[PluginManifest]


class AuthFileInfo(Shape):
    """What a file of an authentication is, told without a byte of it."""
    kind: str = Field(description='"RSA private key", "OpenSSH private key", "3 hosts", "Not a PEM key"…')
    size: int
    modified: int = Field(description='When it was put there, in seconds')


class AuthFileState(Shape):
    exists: bool
    file: Optional[AuthFileInfo]


class AuthType(Shape):
    required: List[str]
    optional: List[str]


class AuthConfig(Shape):
    """Your authentications' file, every secret masked, and what each type of entry holds."""
    file: str
    exists: bool
    config: Dict[str, Any] = Field(json_schema_extra={"tsType": "JsonObject"}, description="The entries, every secret masked")
    files: Dict[str, Dict[str, AuthFileInfo]] = Field(description='Entry name → field → what is there')
    types: Dict[str, AuthType]
