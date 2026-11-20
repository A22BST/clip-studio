"""Run the Claude Code CLI headlessly (``claude -p``). Uses the logged-in plan, never an API key."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Runner = Callable[..., subprocess.CompletedProcess]


class ClaudeCliError(RuntimeError):
    pass


@dataclass
class ClaudeResult:
    text: str
    returncode: int


def find_claude() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if candidate.exists():
            return str(candidate)
    raise ClaudeCliError("The `claude` CLI was not found (expected ~/.local/bin/claude.exe).")


def build_command(
    prompt: str,
    *,
    model: str,
    allowed_tools: list[str],
    add_dirs: list[Path],
    max_turns: int,
    claude_path: str | None = None,
) -> list[str]:
    cmd = [claude_path or find_claude(), "-p", prompt, "--model", model]
    cmd += ["--permission-mode", "acceptEdits", "--max-turns", str(max_turns)]
    cmd += ["--output-format", "text"]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    for directory in add_dirs:
        cmd += ["--add-dir", str(directory)]
    return cmd


def run_claude(
    prompt: str,
    *,
    model: str = "sonnet",
    cwd: Path,
    allowed_tools: list[str],
    add_dirs: list[Path] | None = None,
    max_turns: int = 40,
    timeout_s: int = 1500,
    runner: Runner = subprocess.run,
    claude_path: str | None = None,
) -> ClaudeResult:
    cmd = build_command(
        prompt, model=model, allowed_tools=allowed_tools, add_dirs=add_dirs or [],
        max_turns=max_turns, claude_path=claude_path,
    )  # fmt: skip
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # use the plan login
    try:
        done = runner(
            cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
            timeout=timeout_s, stdin=subprocess.DEVNULL, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCliError(f"claude -p timed out after {timeout_s}s") from exc
    except OSError as exc:
        raise ClaudeCliError(f"could not start claude: {exc}") from exc
    return ClaudeResult(text=(done.stdout or "").strip(), returncode=done.returncode)
