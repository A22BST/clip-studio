import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from autoclip.auto.winsched import (
    build_task_xml,
    install_tasks,
    task_specs,
    uninstall_tasks,
)

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def test_task_xml_settings_and_actions():
    specs = task_specs(r"C:\Some Folder\python.exe", r"C:\Ahmad & Co\Studio")
    assert [spec.name for spec in specs] == [
        "ClipStudio-Tick",
        "ClipStudio-Bot",
        "ClipStudio-Track",
        "ClipStudio-Weekly",
    ]
    for spec in specs:
        root = ET.fromstring(build_task_xml(spec).encode("utf-16"))
        assert root.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=NS) == "IgnoreNew"
        for setting in ("DisallowStartIfOnBatteries", "StopIfGoingOnBatteries"):
            assert root.findtext(f"t:Settings/t:{setting}", namespaces=NS) == "false"
        assert root.findtext("t:Settings/t:StartWhenAvailable", namespaces=NS) == "true"
        assert (
            root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=NS)
            == "InteractiveToken"
        )
        command = root.findtext("t:Actions/t:Exec/t:Command", namespaces=NS)
        if spec.action == "tick":
            assert command == str(Path(spec.python_exe).with_name("pythonw.exe"))
        else:
            assert command == spec.python_exe
        assert root.findtext("t:Actions/t:Exec/t:WorkingDirectory", namespaces=NS) == spec.repo_dir
        arguments = root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS)
        if spec.action == "tick":
            assert arguments.startswith('-X utf8 -c "')
            assert "PYTHONUTF8='1'" in arguments
            assert "AUTOCLIP_HOME=r'D:\\autoclip'" in arguments
            # Execute the bootstrap with a fake module runner to check env and argv.
            import os
            import runpy
            import sys
            from unittest.mock import patch

            with (
                patch.dict(os.environ),
                patch.object(sys, "argv", []),
                patch.object(runpy, "run_module") as run,
            ):
                exec(arguments[len('-X utf8 -c "'):-1])
                assert os.environ["AUTOCLIP_HOME"] == r"D:\autoclip"
                assert os.environ["PYTHONUTF8"] == "1"
                run.assert_called_once_with("autoclip.auto.cli", run_name="__main__")
        else:
            assert arguments == f"-m autoclip.auto.cli {spec.action}"


def test_trigger_schedules():
    tick, bot, track, weekly = [
        ET.fromstring(build_task_xml(spec)) for spec in task_specs("python", "repo")
    ]
    assert tick.findtext(".//t:Repetition/t:Interval", namespaces=NS) == "PT30M"
    assert tick.find(".//t:Repetition/t:Duration", NS) is None
    assert tick.findtext(".//t:ExecutionTimeLimit", namespaces=NS) == "PT3H"
    assert bot.find(".//t:LogonTrigger", NS) is not None
    assert bot.findtext(".//t:ExecutionTimeLimit", namespaces=NS) == "PT0S"
    assert bot.findtext(".//t:RestartOnFailure/t:Interval", namespaces=NS) == "PT1M"
    assert bot.findtext(".//t:RestartOnFailure/t:Count", namespaces=NS) == "3"
    assert track.findtext(".//t:StartBoundary", namespaces=NS).endswith("T09:00:00")
    assert track.findtext(".//t:DaysInterval", namespaces=NS) == "1"
    assert weekly.findtext(".//t:StartBoundary", namespaces=NS).endswith("T08:00:00")
    assert weekly.find(".//t:DaysOfWeek/t:Monday", NS) is not None


def test_default_dry_run_never_calls_runner():
    def runner(*args, **kwargs):
        raise AssertionError("dry run invoked schtasks")

    plans = install_tasks(runner=runner)
    assert len(plans) == 4
    for plan in plans:
        ET.fromstring(plan["xml"])
        assert plan["command"] == [
            "schtasks",
            "/Create",
            "/XML",
            f"{plan['name']}.xml",
            "/TN",
            plan["name"],
            "/F",
        ]
    assert len(uninstall_tasks(runner=runner)) == 4


def test_import_writes_utf16_and_uses_argument_list():
    calls = []

    def runner(command, *, check):
        assert check is True
        assert command[:3] == ["schtasks", "/Create", "/XML"]
        data = Path(command[3]).read_bytes()
        assert data.startswith((b"\xff\xfe", b"\xfe\xff"))
        root = ET.fromstring(data)
        assert root.findtext(".//t:WorkingDirectory", namespaces=NS) == "C:\\Studie \u00e6 & co"
        calls.append(command)

    install_tasks(False, runner, python_exe="python", repo_dir="C:\\Studie \u00e6 & co")
    assert len(calls) == 4


def test_uninstall_commands():
    calls = []

    def runner(command, *, check):
        assert check
        calls.append(command)

    assert uninstall_tasks(False, runner) == calls
    assert len(calls) == 4
    assert calls[0] == ["schtasks", "/Delete", "/TN", "ClipStudio-Tick", "/F"]


def test_only_cli_parsing(monkeypatch):
    from typer.testing import CliRunner
    from autoclip.auto import cli, winsched

    calls = []
    original = winsched.install_tasks

    def install(**kwargs):
        calls.append(kwargs)
        return original(**kwargs, runner=lambda *a, **k: pytest.fail("ran schtasks"))

    monkeypatch.setattr(winsched, "install_tasks", install)
    result = CliRunner().invoke(cli.app, ["install-tasks", "--only", " tick,weekly "])
    assert result.exit_code == 0, result.output
    assert calls[0]["only"] == ["tick", "weekly"]
    assert calls[0]["dry_run"] is True
    assert "ClipStudio-Tick:" in result.output
    assert "ClipStudio-Weekly:" in result.output
    assert "ClipStudio-Bot" not in result.output
    assert "ClipStudio-Track" not in result.output
    assert "Dry run only" in result.output


@pytest.mark.parametrize("value", ["", "tick,", "tick,unknown"])
def test_only_rejects_invalid_names(value):
    from typer.testing import CliRunner
    from autoclip.auto.cli import app

    result = CliRunner().invoke(app, ["install-tasks", "--only", value])
    assert result.exit_code == 2
    assert "--only" in result.output


def test_only_filters_specs():
    plans = install_tasks(only=["tick", "weekly"])
    assert [p["name"] for p in plans] == ["ClipStudio-Tick", "ClipStudio-Weekly"]
