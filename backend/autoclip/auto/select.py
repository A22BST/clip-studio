"""Step 3b: headless clip selection. ``claude -p "/clip <job>" --model sonnet`` run unattended.

The /clip skill (session 1) reads ``candidates.json`` and writes ``highlights.json``. Here the
result is validated with session 1's own ``load_highlights`` plus a word-index range check, and
retried once with the validation error when it is wrong. The headless prompt tells the skill NOT
to render or post: rendering is a separate, deterministic step.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import paths
from . import claude_cli
from .config import AutoConfig, auto_dir

REPO_ROOT = Path(__file__).resolve().parents[3]

HEADLESS_NOTE = """\
HEADLESS RUN (no human is watching, do not ask questions):
- Do steps 0-5 only: read candidates.json, then write highlights.json at the path below.
- Do NOT run `clip stream`, do NOT render, do NOT post anything, do NOT run any shell command.
- Every `start_word_index`/`end_word_index` must be copied from the transcript's [index] numbers
  and lie inside that candidate's first_word..last_word.
- Include every `limits.required_hashtags` entry in `hashtags` and every
  `limits.required_caption_phrases` phrase in `caption`.
- Output path: {out}
{extra}"""


class SelectionError(RuntimeError):
    pass


def what_works_path() -> Path:
    return auto_dir() / "what_works.md"


def validate_highlights(job_id: str) -> int:
    """Return the number of valid clips; raise SelectionError with a fixable message."""
    from ..stream.pipeline import StreamPipelineError, load_highlights

    work = paths.job_work_dir(job_id)
    path = work / "highlights.json"
    if not path.is_file():
        raise SelectionError("highlights.json was not written")
    try:
        picks = load_highlights(path)
    except StreamPipelineError as exc:
        raise SelectionError(str(exc)) from exc
    cand = json.loads((work / "candidates.json").read_text(encoding="utf-8"))
    ranges = [(c["first_word"], c["last_word"]) for c in cand["candidates"]]
    for position, (clip, _meta) in enumerate(picks, start=1):
        inside = any(
            lo <= clip.start_word_index and clip.end_word_index <= hi for lo, hi in ranges
        )
        if clip.end_word_index <= clip.start_word_index or not inside:
            raise SelectionError(
                f"clips[{position}] word range {clip.start_word_index}-{clip.end_word_index} is "
                f"not inside any candidate's first_word..last_word"
            )
    return len(picks)


def run_selection(
    job_id: str,
    config: AutoConfig,
    *,
    runner=None,
    cwd: Path | None = None,
) -> Path:
    """Write and validate ``highlights.json`` for an autoclip job. Returns its path."""
    work = paths.job_work_dir(job_id)
    out = work / "highlights.json"
    if not (work / "candidates.json").is_file():
        raise SelectionError(f"no candidates.json for job {job_id}")
    try:  # a valid file from an earlier attempt is reused
        validate_highlights(job_id)
        return out
    except SelectionError:
        pass

    kwargs = {"runner": runner} if runner else {}
    error = ""
    for attempt in range(1, config.selection.max_attempts + 1):
        extra = ""
        ww = what_works_path()
        if ww.is_file():
            extra += f"- Also read {ww} ('what works' from past results) and apply it.\n"
        if error:
            extra += f"- Your previous highlights.json was invalid: {error}. Fix exactly that.\n"
            out.unlink(missing_ok=True)
        prompt = f"/clip {job_id}\n\n" + HEADLESS_NOTE.format(out=out, extra=extra)
        result = claude_cli.run_claude(
            prompt,
            model=config.selection.model,
            cwd=cwd or REPO_ROOT,
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            add_dirs=[work, auto_dir()],
            max_turns=config.selection.max_turns,
            timeout_s=config.selection.timeout_min * 60,
            **kwargs,
        )
        try:
            validate_highlights(job_id)
            return out
        except SelectionError as exc:
            error = f"{exc} (claude exit {result.returncode})"
    raise SelectionError(f"selection failed after {config.selection.max_attempts} tries: {error}")
