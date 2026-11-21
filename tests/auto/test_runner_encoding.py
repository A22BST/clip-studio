"""Windows output encoding regressions for stream subprocesses."""

import subprocess
import sys

from autoclip.auto.runner import _run


def test_run_overrides_inherited_cp1252_output(monkeypatch):
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setenv("AUTOCLIP_ENCODING_TEST", "inherited")
    code = (
        "import os, sys; "
        "assert os.environ['AUTOCLIP_ENCODING_TEST'] == 'inherited'; "
        "assert os.environ['PYTHONUTF8'] == '1'; "
        "assert sys.stdout.encoding == 'utf-8'; "
        "print('Clip title \\U0001f62d'); "
        "sys.stderr.buffer.write(b'bad byte: \\xff')"
    )

    result = _run([sys.executable, "-c", code], subprocess.run, 30)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Clip title \U0001f62d\n"
    assert result.stderr == "bad byte: \ufffd"


def test_stream_console_prints_title_on_strict_cp1252_stdout():
    code = (
        "import sys; "
        "sys.stdout.reconfigure(encoding='cp1252', errors='strict'); "
        "from autoclip.stream.cli import console; "
        "console.print('Clip title \\U0001f62d')"
    )

    result = _run([sys.executable, "-c", code], subprocess.run, 30)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Clip title ?\n"
