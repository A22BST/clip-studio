"""Reviewable Windows Task Scheduler XML; all operations default to dry run."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


@dataclass(frozen=True)
class TaskSpec:
    name: str
    python_exe: str
    repo_dir: str
    action: str
    schedule: str


def task_specs(python_exe: str | Path, repo_dir: str | Path) -> list[TaskSpec]:
    return [
        TaskSpec(f"ClipStudio-{name}", str(python_exe), str(repo_dir), action, schedule)
        for name, action, schedule in (
            ("Tick", "tick", "interval"),
            ("Bot", "bot", "logon"),
            ("Track", "track", "daily"),
            ("Weekly", "weekly", "weekly"),
        )
    ]


def build_task_xml(spec: TaskSpec) -> str:
    """Build Task Scheduler 1.2 XML without inspecting the host or running commands."""
    task = ET.Element("Task", {"version": "1.2", "xmlns": _NS})

    def child(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
        element = ET.SubElement(parent, tag)
        element.text = text
        return element

    triggers = child(task, "Triggers")
    if spec.schedule == "logon":
        trigger = child(triggers, "LogonTrigger")
        child(trigger, "Enabled", "true")
    elif spec.schedule == "interval":
        trigger = child(triggers, "TimeTrigger")
        repetition = child(trigger, "Repetition")
        child(repetition, "Interval", "PT30M")
        child(repetition, "StopAtDurationEnd", "false")
        child(trigger, "StartBoundary", "2020-01-01T00:00:00")
        child(trigger, "Enabled", "true")
    elif spec.schedule in ("daily", "weekly"):
        trigger = child(triggers, "CalendarTrigger")
        boundary = "2020-01-01T09:00:00" if spec.schedule == "daily" else "2020-01-06T08:00:00"
        child(trigger, "StartBoundary", boundary)
        child(trigger, "Enabled", "true")
        if spec.schedule == "daily":
            child(child(trigger, "ScheduleByDay"), "DaysInterval", "1")
        else:
            weekly = child(trigger, "ScheduleByWeek")
            child(weekly, "WeeksInterval", "1")
            child(child(weekly, "DaysOfWeek"), "Monday")
    else:
        raise ValueError("Unknown task schedule")
    principal = ET.SubElement(child(task, "Principals"), "Principal", {"id": "Author"})
    child(principal, "LogonType", "InteractiveToken")
    child(principal, "RunLevel", "LeastPrivilege")
    settings = child(task, "Settings")
    child(settings, "MultipleInstancesPolicy", "IgnoreNew")
    child(settings, "DisallowStartIfOnBatteries", "false")
    child(settings, "StopIfGoingOnBatteries", "false")
    child(settings, "StartWhenAvailable", "true")
    child(settings, "ExecutionTimeLimit", "PT0S" if spec.action == "bot" else "PT4H")
    if spec.action == "bot":
        restart = child(settings, "RestartOnFailure")
        child(restart, "Interval", "PT1M")
        child(restart, "Count", "3")
    actions = ET.SubElement(task, "Actions", {"Context": "Author"})
    execute = child(actions, "Exec")
    child(execute, "Command", spec.python_exe)
    child(execute, "Arguments", f"-m autoclip.auto.cli {spec.action}")
    child(execute, "WorkingDirectory", spec.repo_dir)
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + ET.tostring(task, encoding="unicode")


def install_tasks(
    dry_run: bool = True,
    runner: Callable[..., Any] = subprocess.run,
    *,
    python_exe: str | Path | None = None,
    repo_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return XML/argument lists; only explicit dry_run=False invokes schtasks."""
    specs = task_specs(
        python_exe or sys.executable, repo_dir or Path(__file__).resolve().parents[3]
    )
    plans = []
    for spec in specs:
        xml = build_task_xml(spec)
        command = ["schtasks", "/Create", "/XML", f"{spec.name}.xml", "/TN", spec.name, "/F"]
        plans.append({"name": spec.name, "xml": xml, "command": command})
        if not dry_run:
            with tempfile.TemporaryDirectory(prefix="clipstudio-scheduler-") as directory:
                path = Path(directory) / f"{spec.name}.xml"
                path.write_text(xml, encoding="utf-16")
                runner(command[:3] + [str(path)] + command[4:], check=True)
    return plans


def uninstall_tasks(
    dry_run: bool = True,
    runner: Callable[..., Any] = subprocess.run,
) -> list[list[str]]:
    commands = [["schtasks", "/Delete", "/TN", spec.name, "/F"] for spec in task_specs("", "")]
    if not dry_run:
        for command in commands:
            runner(command, check=True)
    return commands
