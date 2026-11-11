"""src/merge-settings.py: plugin policy fragments → one managed-settings file."""
import json
import subprocess
import sys

from conftest import REPO

MERGE = REPO / "src/merge-settings.py"


def merge(tmp_path, *docs):
    paths = []
    for i, doc in enumerate(docs):
        path = tmp_path / f"{i}.json"
        path.write_text(json.dumps(doc))
        paths.append(str(path))
    out = subprocess.run([sys.executable, MERGE, *paths], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_objects_merge_lists_concatenate_later_scalars_win(tmp_path):
    a = {"hooks": {"PreToolUse": [{"matcher": "Bash"}]}, "x": 1, "keep": {"a": 1}}
    b = {"hooks": {"PreToolUse": [{"matcher": "Edit"}], "Stop": []}, "x": 2, "keep": {"b": 2}}
    assert merge(tmp_path, a, b) == {
        "hooks": {"PreToolUse": [{"matcher": "Bash"}, {"matcher": "Edit"}], "Stop": []},
        "x": 2,
        "keep": {"a": 1, "b": 2},
    }


def test_type_mismatch_takes_the_later_value(tmp_path):
    assert merge(tmp_path, {"k": [1]}, {"k": {"a": 1}}) == {"k": {"a": 1}}


def test_no_fragments_is_an_empty_policy(tmp_path):
    assert merge(tmp_path) == {}


def test_base_plus_branch_guard_installs_the_hook():
    out = subprocess.run([sys.executable, MERGE, REPO / "settings-base.json", REPO / "plugins/branch-guard/settings.json"],
                         capture_output=True, text=True, check=True).stdout
    [entry] = json.loads(out)["hooks"]["PreToolUse"]
    assert entry["matcher"] == "Bash"
    command = entry["hooks"][0]["command"]
    # The image installs plugins/ at /opt/plugins, so the hook must exist at the mapped path.
    assert command.startswith("/opt/plugins/")
    assert (REPO / "plugins" / command.removeprefix("/opt/plugins/")).is_file()
