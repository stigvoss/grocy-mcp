"""Guards the container image's contract with the rest of the project.

The image itself is built and smoke-tested by the Container image workflow; these tests catch the
cheap mistakes earlier: a default command the server no longer accepts, or a build context that
leaves out a file the wheel build needs.
"""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from grocy_mcp.mcp.server import main

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()


def _instruction(name: str) -> str:
    matches = re.findall(rf"^{name}\s+(.*)$", DOCKERFILE, flags=re.MULTILINE)
    assert matches, f"Dockerfile has no {name}"
    return matches[-1]  # the last stage is the runtime image


def test_default_command_is_accepted_by_the_server(monkeypatch):
    server = MagicMock()
    monkeypatch.setattr("grocy_mcp.mcp.server.create_mcp_server", lambda: server)
    entrypoint = json.loads(_instruction("ENTRYPOINT"))
    command = json.loads(_instruction("CMD"))
    assert entrypoint == ["grocy-mcp"]
    monkeypatch.setattr("sys.argv", [*entrypoint, *command])

    main()

    server.run.assert_called_once_with(
        transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp", stateless_http=True
    )


def test_exposed_port_matches_the_default_command():
    command = json.loads(_instruction("CMD"))
    assert _instruction("EXPOSE") == command[command.index("--port") + 1]


def test_image_runs_as_a_non_root_user():
    assert _instruction("USER") not in {"root", "0"}


def test_entry_points_the_image_relies_on_exist():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'grocy-mcp = "grocy_mcp.mcp.server:main"' in pyproject
    assert 'grocy = "grocy_mcp.cli.app:main"' in pyproject


def test_dockerignore_keeps_everything_the_wheel_build_copies():
    ignored = {
        line.strip().rstrip("/")
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    copied = re.findall(r"^COPY (?!--from)(.+?)\s+\S+$", DOCKERFILE, flags=re.MULTILINE)
    needed = {path.strip("./") or "." for line in copied for path in line.split()}
    assert needed >= {"pyproject.toml", "README.md", "src"}
    assert not (needed & ignored), f"in both COPY and .dockerignore: {needed & ignored}"


def test_workflow_publishes_both_architectures_only_outside_pull_requests():
    workflow = (ROOT / ".github" / "workflows" / "docker.yml").read_text()
    assert "linux/amd64,linux/arm64" in workflow
    assert "push: ${{ github.event_name != 'pull_request' }}" in workflow
    assert "if: github.event_name != 'pull_request'" in workflow  # the registry login
