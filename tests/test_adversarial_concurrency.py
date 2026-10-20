"""Bounded local-process ownership and failed-initialization experiments."""
from concurrent.futures import Future
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

import pytest

from strata_engine import StrataEngine
from strata_engine.catalog import Catalog


def read_line(process):
    result = Future()

    def read():
        try:
            result.set_result(process.stdout.readline().strip())
        except BaseException as exc:
            result.set_exception(exc)

    thread = Thread(target=read, daemon=True)
    thread.start()
    try:
        return result.result(timeout=8)
    finally:
        thread.join(timeout=0.1)


def test_competing_processes_and_terminated_owner_release_stale_guard(tmp_path):
    directory = tmp_path / "contended"
    with StrataEngine(directory) as engine:
        engine.execute("CREATE TABLE durable (id INTEGER);")
        engine.execute("INSERT INTO durable VALUES (7);")
    # The persistent lock file is intentionally left on disk by normal close.
    assert (directory / ".strata.lock").exists()
    code = """
import sys
from strata_engine import StrataEngine
from strata_engine.concurrency import DatabaseInUseError
print('ready', flush=True)
sys.stdin.readline()
try:
    engine = StrataEngine(sys.argv[1])
    engine.open()
except DatabaseInUseError:
    print('blocked', flush=True)
else:
    print('owned', flush=True)
    sys.stdin.readline()
    engine.close()
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    processes = []
    try:
        for _ in range(2):
            processes.append(subprocess.Popen(
                [sys.executable, "-c", code, str(directory)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ))
        for process in processes:
            assert read_line(process) == "ready"
        for process in processes:
            process.stdin.write("start\n")
            process.stdin.flush()
        states = [read_line(process) for process in processes]
        assert sorted(states) == ["blocked", "owned"]
        owner = processes[states.index("owned")]
        loser = processes[states.index("blocked")]
        assert loser.wait(timeout=8) == 0
        # No writes occur in either child: this tests OS ownership release,
        # not arbitrary-crash durability of partially modified database pages.
        owner.terminate()
        owner.wait(timeout=8)
        assert (directory / ".strata.lock").exists()
        with StrataEngine(directory) as engine:
            assert engine.execute("SELECT id FROM durable;").rows[0][0] == 7
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=8)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def test_failure_after_catalog_initialization_releases_all_resources(tmp_path, monkeypatch):
    directory = tmp_path / "init_failure"
    original = Catalog._initialize_storage

    def fail_after_open(self):
        original(self)
        raise RuntimeError("controlled initialization failure")

    with monkeypatch.context() as patch:
        patch.setattr(Catalog, "_initialize_storage", fail_after_open)
        with pytest.raises(RuntimeError, match="controlled initialization failure"):
            StrataEngine(directory).open()
    with StrataEngine(directory) as engine:
        engine.execute("CREATE TABLE recovered (id INTEGER);")
        engine.execute("INSERT INTO recovered VALUES (9);")
    with StrataEngine(directory) as engine:
        assert engine.execute("SELECT id FROM recovered;").rows[0][0] == 9
