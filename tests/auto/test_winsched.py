import xml.etree.ElementTree as ET
from pathlib import Path

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
        assert root.findtext("t:Actions/t:Exec/t:Command", namespaces=NS) == spec.python_exe
        assert root.findtext("t:Actions/t:Exec/t:WorkingDirectory", namespaces=NS) == spec.repo_dir
        assert (
            root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS)
            == f"-m autoclip.auto.cli {spec.action}"
        )


def test_trigger_schedules():
    tick, bot, track, weekly = [
        ET.fromstring(build_task_xml(spec)) for spec in task_specs("python", "repo")
    ]
    assert tick.findtext(".//t:Repetition/t:Interval", namespaces=NS) == "PT30M"
    assert tick.find(".//t:Repetition/t:Duration", NS) is None
    assert tick.findtext(".//t:ExecutionTimeLimit", namespaces=NS) == "PT4H"
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
