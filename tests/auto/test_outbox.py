import json
from datetime import datetime
from pathlib import Path

import pytest
from autoclip.auto import outbox, tick
from autoclip.auto.cli import app
from autoclip.auto.config import AutoConfig
from autoclip.auto.notify import RecordingNotifier
from typer.testing import CliRunner

NOW = datetime(2026, 11, 22, 12)


@pytest.fixture
def case(tmp_path):
    exports = tmp_path / "exports" / "job123"
    exports.mkdir(parents=True)
    source = exports / "clip.mp4"
    source.write_bytes(b"video")
    work = tmp_path / "work"
    work.mkdir()
    (work / "transcript.json").write_text(
        json.dumps(
            {
                "words": [
                    {"start": 0, "end": 1, "text": "naked"},
                    {"start": 10, "end": 11, "text": "hello"},
                    {"start": 45, "end": 46, "text": "porn"},
                ]
            }
        )
    )
    entry = {
        "title": "A clip",
        "status": "exported",
        "path": str(source),
        "start_s": 10,
        "end_s": 40,
        "qa_score": 80,
        "notes": [],
        "caption": "Caption #stale",
        "hashtags": ["ad", "GTA6"],
        "sfx": "Pop",
        "story": {"setup": {"text": "A setup"}, "payoff": {"text": "A payoff"}},
    }
    config = AutoConfig(
        outbox={"dir": str(tmp_path / "outbox")}, upload_post={"manual_platforms": ["tiktok"]}
    )

    def run(**changes):
        entry.update(changes)
        (exports / "report.json").write_text(json.dumps([entry]))
        return outbox.export_job(exports, config, work_dir=work, vod_id="vod456", now=NOW)

    return config, exports, work, run


def test_copy_once_and_caption(case):
    config, _, _, run = case
    first = run()[0]
    assert first["status"] == "copied"
    target = Path(first["path"])
    assert target.parent.name == "2026-11-22"
    assert target.read_bytes() == b"video"
    assert target.with_suffix(".txt").read_text() == "Caption\n\n#ad #GTA6\n"
    assert run()[0]["status"] == "already copied"
    assert outbox.today_count(config, NOW) == 1
    assert len((outbox.outbox_dir(config) / "INDEX.md").read_text().splitlines()) == 1


def test_suffixing_and_sfx_preference(case):
    config, exports, _, run = case
    folder = outbox.outbox_dir(config) / "2026-11-22"
    folder.mkdir(parents=True)
    (folder / "clip_sfx.mp4").write_bytes(b"original")
    (folder / "clip_sfx-2.txt").write_text("existing caption")
    (exports / "clip_sfx.mp4").write_bytes(b"with sfx")
    result = run()[0]
    target = Path(result["path"])
    assert target.name == "clip_sfx-3.mp4"
    assert target.read_bytes() == b"with sfx"
    assert (folder / "clip_sfx.mp4").read_bytes() == b"original"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"qa_score": 69}, "below min_qa"),
        ({"end_s": 21.9}, "duration < 12s"),
        ({"status": "rejected"}, "status rejected"),
        ({"status": "blocked"}, "status blocked"),
        ({"status": "failed"}, "status failed"),
    ],
)
def test_copy_gates(case, changes, reason):
    config, _, _, run = case
    result = run(**changes)[0]
    assert result["status"] == "skipped"
    assert result["reason"] == reason
    assert not outbox.outbox_dir(config).exists()


@pytest.mark.parametrize(
    "text,held",
    [
        ("A NAKED person", True),
        ("strip CLUB", True),
        ("Niggaz", True),
        ("Essex and sexuality", False),
        ("hello", False),
    ],
)
def test_keyword_hold_and_word_boundaries(case, text, held):
    config, _, work, run = case
    (work / "transcript.json").write_text(
        json.dumps(
            {
                "words": [
                    {"start": 12, "end": 13, "text": text},
                ]
            }
        )
    )
    result = run()[0]
    assert result["status"] == ("held" if held else "copied")
    if held:
        assert "blocked keyword:" in result["reason"]
        assert Path(result["path"]).parent.name == "held"
        assert result["reason"] in (outbox.outbox_dir(config) / "INDEX.md").read_text()
        assert outbox.today_count(config, NOW) == 0


def test_over_length_hold(case):
    _, _, _, run = case
    result = run(end_s=71.01)[0]
    assert result["status"] == "held"
    assert "duration > 61s" in result["reason"]


@pytest.mark.parametrize("markdown", [False, True])
def test_explicit_notes_hold(case, markdown):
    _, exports, _, run = case
    if markdown:
        (exports / "report.md").write_text("## EXPORTED A clip\n- note: Adult content\n")
        result = run()[0]
    else:
        result = run(notes=["explicit content"])[0]
    assert result["status"] == "held"
    assert "explicit/adult" in result["reason"]


def test_index_content_and_dry_run(case):
    config, exports, work, run = case
    run(qa_score=69)  # write report without copying
    report = json.loads((exports / "report.json").read_text())
    report[0]["qa_score"] = 80
    (exports / "report.json").write_text(json.dumps(report))
    outbox.export_job(exports, config, work_dir=work, vod_id="vod456", now=NOW, dry_run=True)
    line = (outbox.outbox_dir(config) / "INDEX.md").read_text()
    for value in (
        "[dry-run] 2026-11-22",
        "platforms: tiktok",
        "QA: 80",
        "duration: 30.00s",
        "SFX: Pop",
        "job: job123",
        "VOD: vod456",
        "setup: A setup",
        "payoff: A payoff",
        "status: copied",
    ):
        assert value in line
    config.upload_post.manual_platforms = []
    (exports / "clip.mp4").write_bytes(b"new video size")
    outbox.export_job(exports, config, work_dir=work, now=NOW)
    index = (outbox.outbox_dir(config) / "INDEX.md").read_text()
    assert "platforms: tiktok, youtube, instagram" in index


def test_failing_copy_does_not_raise(case, monkeypatch, caplog):
    _, _, _, run = case

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(outbox.shutil, "copyfileobj", fail)
    assert run()[0]["status"] == "error"
    assert "Outbox failed" in caplog.text


def test_cli_count(case, monkeypatch):
    config, _, _, run = case
    run()
    monkeypatch.setattr("autoclip.auto.cli.load_config", lambda: config)
    monkeypatch.setattr(outbox, "today_count", lambda c: 1)
    result = CliRunner().invoke(app, ["outbox"])
    assert result.exit_code == 0
    assert "Today's copied clips: 1" in result.output
    assert "INDEX.md" in result.output


@pytest.mark.parametrize("dry_run", [False, True])
def test_tick_calls_outbox_and_survives_failure(env, monkeypatch, dry_run):
    env.store.add_job(campaign_key="test-campaign", vod_id="vod")
    called = []

    def fail(store, config, job, **kwargs):
        called.append(kwargs["dry_run"])
        raise OSError("outbox failure")

    monkeypatch.setattr(outbox, "after_render", fail)
    monkeypatch.setattr(tick.diskguard, "disk_ok", lambda _: (True, ""))
    result = tick.tick(
        env.store,
        env.config,
        RecordingNotifier(),
        scan=lambda *a, **k: [],
        process=lambda *a: 0,
        max_jobs=1,
        dry_run=dry_run,
    )
    assert result["jobs_run"] == 1
    assert called == [dry_run]


def test_default_dir_matches_campaign_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPSTUDIO_CAMPAIGNS_DIR", str(tmp_path / "campaigns"))
    assert outbox.outbox_dir(AutoConfig()) == tmp_path / "to-post" / "auto"


def test_custom_regex_is_case_insensitive_and_word_bounded(case):
    config, exports, work, run = case
    config.outbox.block_keywords = ["HELLO|greetings"]
    assert run()[0]["status"] == "held"
    (work / "transcript.json").write_text(
        json.dumps(
            {
                "words": [
                    {"start": 12, "end": 13, "text": "helloworld"},
                ]
            }
        )
    )
    # A different export size permits a new decision for this source.
    source = Path(json.loads((exports / "report.json").read_text())[0]["path"])
    source.write_bytes(b"new video size")
    assert run()[0]["status"] == "copied"
