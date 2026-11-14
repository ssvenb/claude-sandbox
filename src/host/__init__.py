"""The host side of the sandbox: what `run.sh` does on YOUR machine, before and around `docker run`.

    config.py   the worked-on repo's .claude-sandbox.json and .env, and the settings they layer
    agents.py   which agent runs, and the version its image installs
    plugins.py  which plugins run: discovery, enablement, validation
    ports.py    the central port proxy a run joins (src/portd.py)
    stage.py    the plugins' own host.sh / web.sh, sourced by bash (src/lib/host-stage.sh)
    main.py     the command line, and the run itself

Plugins and agents stay shell: their host.sh and web.sh are sourced by one bash process per run,
with the helpers of src/lib/host-*.sh, exactly as before. Standard library only.
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
