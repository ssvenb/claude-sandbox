"""The orchestrator: what `run.sh` does on YOUR machine, before and around `docker run`.

    config.py   the worked-on repo's .claude-sandbox.json and .env, and the settings they layer
    agents.py   which agent runs, and the version its image installs
    plugins.py  which plugins run: discovery, enablement, validation
    stage.py    the plugins' own host.sh / web.sh, sourced by bash (src/contract/host/stage.sh)
    main.py     the command line, and the run itself
    kernel.json the sandbox's own settings, declared as plugins declare theirs

The rest of the core, beside it under src/:

    contract/   what a plugin's or an agent's scripts are sourced with: host/ on this machine,
                container/ in the image
    boot/       the container's root stage and agent stage
    services/   core features, host and container side together: ports/, credentials/, settings/, chat/
    shared/     helpers of more than one of those

Plugins and agents stay shell: their host.sh and web.sh are sourced by one bash process per run.
Standard library only.
"""
import sys
from pathlib import Path

SANDBOX = Path(__file__).resolve().parent.parent.parent  # the sandbox checkout: run.sh, plugins/, agents/


class Die(Exception):
    """A refusal, said as `❌ <message>` and exit status 1."""


def say(*lines, file=None):
    """A line for whoever watches the run. Flushed at once: what bash and docker print comes in
    between, and a chat session's stdout is a pipe."""
    print(*lines, file=file or sys.stdout, flush=True)
