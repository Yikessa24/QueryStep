"""Restricted free-SQL practice, separate from the fixed-template executor."""

from collections import Counter
import ctypes
from functools import lru_cache
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
from threading import Event
from time import monotonic

from course_content.sql_tasks import SCENARIOS, _dataset, _get_task, _validate_dataset_args
from sql_lab.query_worker import MAX_RESULT_BYTES, MAX_SQL_BYTES, MEMORY_BYTES, WORKER_SECONDS


WALL_SECONDS = WORKER_SECONDS + 0.5
_WORKER = Path(__file__).with_name("query_worker.py").resolve()


def dataset_view(task_id: str, scenario: str = "sample", seed: int = 0) -> dict:
    return _dataset(task_id, scenario, seed)


def _failure(status: str, error: str) -> dict:
    return {"status": status, "columns": [], "rows": [], "row_count": 0, "error": error}


def _sql_error(sql: str) -> str | None:
    if not isinstance(sql, str):
        return "invalid_sql"
    if len(sql) > MAX_SQL_BYTES:
        return "sql_too_large"
    if not sql.strip() or "\x00" in sql:
        return "invalid_sql"
    try:
        return "sql_too_large" if len(sql.encode()) > MAX_SQL_BYTES else None
    except UnicodeError:
        return "invalid_sql"


@lru_cache(maxsize=1)
def _mac_libproc():
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                     ctypes.c_void_p, ctypes.c_int]
    library.proc_pidinfo.restype = ctypes.c_int
    return library


def _resident_bytes(pid: int) -> int:
    if sys.platform == "darwin":
        # PROC_PIDTASKINFO starts with virtual_size, resident_size (uint64_t).
        buffer = ctypes.create_string_buffer(1024)
        length = _mac_libproc().proc_pidinfo(pid, 4, 0, buffer, len(buffer))
        if length < 16:
            raise OSError("memory_monitor_unavailable")
        return struct.unpack_from("=QQ", buffer.raw)[1]
    if sys.platform == "linux":
        return int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    raise OSError("unsupported_platform")


def _reap(process: subprocess.Popen) -> None:
    try:
        if process.poll() is None:
            # Own session/process group; never target the API's process group.
            os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Darwin can report EPERM when the child exits between poll and killpg.
        # The worker's independent deadline still applies if it is not yet dead.
        process.wait(timeout=WORKER_SECONDS + 0.5)
    finally:
        process.wait()
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()


def _invoke(payload: dict, *, cancel_event: Event | None = None) -> dict:
    if cancel_event is not None and cancel_event.is_set():
        return _failure("timeout", "query_cancelled")
    spec = importlib.util.find_spec("sqlglot")
    if spec is None or spec.origin is None:
        return _failure("error", "sql_parser_unavailable")
    if sys.platform not in ("darwin", "linux"):
        return _failure("error", "sandbox_unavailable")
    # Test the RSS monitor before spawning. Darwin's address-space rlimit is
    # unusable; external RSS checks plus SQLite's hard heap cap are mandatory.
    try:
        _resident_bytes(os.getpid())
    except (OSError, ValueError, IndexError):
        return _failure("error", "sandbox_unavailable")
    parser_directory = str(Path(spec.origin).parent.parent)
    data = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()
    deadline = monotonic() + WALL_SECONDS
    process = None
    try:
        if cancel_event is not None and cancel_event.is_set():
            return _failure("timeout", "query_cancelled")
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", str(_WORKER), parser_directory],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd="/", env={}, close_fds=True, start_new_session=True,
        )
        pending = data
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return _failure("timeout", "query_cancelled")
            remaining = deadline - monotonic()
            if remaining <= 0:
                return _failure("timeout", "query_timeout")
            try:
                output, _ = process.communicate(input=pending, timeout=min(0.025, remaining))
                break
            except subprocess.TimeoutExpired:
                pending = None
                try:
                    if _resident_bytes(process.pid) > MEMORY_BYTES:
                        return _failure("error", "memory_limit_exceeded")
                except (OSError, ValueError, IndexError):
                    # proc_pidinfo can lose the task just before waitpid sees
                    # its exit. Reap that normal exit rather than misclassify it.
                    try:
                        process.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        return _failure("error", "sandbox_unavailable")
        if cancel_event is not None and cancel_event.is_set():
            return _failure("timeout", "query_cancelled")
        if process.returncode in (74, -signal.SIGXCPU, -signal.SIGKILL):
            return _failure("timeout", "query_timeout")
        if process.returncode == 73:
            return _failure("error", "memory_limit_exceeded")
        if process.returncode != 0 or len(output) > MAX_RESULT_BYTES + 8192:
            return _failure("error", "worker_error")
        result = json.loads(output)
        if not isinstance(result, dict):
            return _failure("error", "worker_error")
        return result
    except (OSError, ValueError, subprocess.SubprocessError):
        return _failure("error", "worker_error")
    finally:
        # Also runs on KeyboardInterrupt, cancellation exceptions and failures.
        if process is not None:
            _reap(process)


def inspect_sql(task_id: str, sql: str) -> dict:
    """Validate syntax and the permitted subset (not output correctness)."""
    try:
        task = _get_task(task_id)
    except ValueError as exc:
        return {"valid": False, "error": str(exc)}
    error = _sql_error(sql)
    if error:
        return {"valid": False, "error": error}
    result = _invoke({"mode": "inspect", "sql": sql,
                      "allowed_tables": [table.name for table in task.tables]})
    valid = result.get("valid") is True and result.get("error") is None
    return {"valid": valid, "error": None if valid else result.get("error") or "worker_error"}


def _finish(result: dict, task_id: str, scenario: str, seed: int, start: float) -> dict:
    # Error metadata is normalized too: invalid arbitrary objects cannot enter
    # JSON fingerprints. No SQL (including the trusted answer) is serialized.
    scenario = scenario if isinstance(scenario, str) and scenario in SCENARIOS else "sample"
    seed = seed if type(seed) is int and 0 <= seed <= 2**31 - 1 else 0
    task_key = task_id if isinstance(task_id, str) and len(task_id) <= 64 else ""
    body = {**result, "scenario": scenario, "seed": seed}
    digest = sha256(json.dumps({"task_id": task_key, **body}, sort_keys=True,
                               ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    return {**body, "elapsed_ms": round((monotonic() - start) * 1000, 3), "fingerprint": digest}


def run_query(task_id: str, sql: str, scenario: str = "sample", seed: int = 0,
              *, cancel_event: Event | None = None) -> dict:
    start = monotonic()
    if cancel_event is not None and cancel_event.is_set():
        return _finish(_failure("timeout", "query_cancelled"), task_id, scenario, seed, start)
    try:
        task = _get_task(task_id)
        _validate_dataset_args(scenario, seed)
        error = _sql_error(sql)
        if error:
            raise ValueError(error)
    except ValueError as exc:
        return _finish(_failure("rejected", str(exc)), task_id, scenario, seed, start)
    dataset = _dataset(task_id, scenario, seed)
    result = _invoke({"mode": "query", "sql": sql, "tables": dataset["tables"],
                      "ddl": [table.ddl for table in task.tables],
                      "allowed_tables": [table.name for table in task.tables]}, cancel_event=cancel_event)
    return _finish(result, task_id, scenario, seed, start)


def _same_result(actual: dict, expected: dict, ordered: bool) -> bool:
    if len(actual["columns"]) != len(expected["columns"]):
        return False
    # Column aliases are immaterial. Python preserves None vs 0/empty text,
    # while SQLite INTEGER and equal REAL values compare numerically alike.
    # Counter is intentional: set comparison would silently drop duplicates.
    left = [tuple(row) for row in actual["rows"]]
    right = [tuple(row) for row in expected["rows"]]
    return left == right if ordered else Counter(left) == Counter(right)


def evaluate(task_id: str, sql: str, scenarios=None, seed: int = 0,
             *, cancel_event: Event | None = None) -> dict:
    """Return the first concrete counterexample, never a proof of equivalence."""
    try:
        task = _get_task(task_id)
        chosen = list(SCENARIOS) if scenarios is None else scenarios
        if (not isinstance(chosen, (list, tuple)) or not 1 <= len(chosen) <= len(SCENARIOS)
                or any(not isinstance(s, str) or s not in SCENARIOS for s in chosen)
                or len(set(chosen)) != len(chosen)):
            raise ValueError("invalid_scenarios")
        for scenario in chosen:
            _validate_dataset_args(scenario, seed)
    except ValueError as exc:
        return {"status": "rejected", "passed": False, "checked": 0, "total": 0,
                "counterexample": None, "message": str(exc), "query_result": None}
    checked = 0
    first_result = None

    def cancelled() -> dict:
        return {"status": "timeout", "passed": False, "checked": checked, "total": len(chosen),
                "counterexample": None, "message": "query_cancelled", "query_result": first_result}

    for scenario in chosen:
        if cancel_event is not None and cancel_event.is_set():
            return cancelled()
        actual = run_query(task_id, sql, scenario, seed, cancel_event=cancel_event)
        if first_result is None:
            first_result = actual
        if actual["status"] != "ok":
            return {"status": actual["status"], "passed": False, "checked": checked,
                    "total": len(chosen), "counterexample": None,
                    "message": actual["error"], "query_result": first_result}
        if cancel_event is not None and cancel_event.is_set():
            return cancelled()
        expected = run_query(task_id, task.reference_sql, scenario, seed, cancel_event=cancel_event)
        if (expected.get("error") == "query_cancelled"
                or (cancel_event is not None and cancel_event.is_set())):
            return cancelled()
        if expected["status"] != "ok":
            return {"status": "error", "passed": False, "checked": checked, "total": len(chosen),
                    "counterexample": None, "message": "reference_execution_failed",
                    "query_result": first_result}
        checked += 1
        if not _same_result(actual, expected, task.ordered):
            return {"status": "mismatch", "passed": False, "checked": checked, "total": len(chosen),
                    "counterexample": {"scenario": scenario, "seed": seed,
                                       "tables": _dataset(task_id, scenario, seed)["tables"],
                                       "actual": actual, "expected": expected},
                    "message": "发现反例：请对照输入表、重复次数、NULL 与要求的行顺序。",
                    "query_result": first_result}
    return {"status": "passed", "passed": True, "checked": checked, "total": len(chosen),
            "counterexample": None, "message": "通过所选有限场景；这不构成 SQL 等价性的证明。",
            "query_result": first_result}
