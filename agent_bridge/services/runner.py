from __future__ import annotations

import shlex
import subprocess
import threading
import time
import os
import signal
from dataclasses import dataclass
from typing import Callable, Sequence

StreamCallback = Callable[[str, str], None]

_ACTIVE_PROCESSES: set[subprocess.Popen[str]] = set()
_ACTIVE_PROCESSES_LOCK = threading.Lock()


@dataclass(slots=True)
class CommandResult:
    command: str
    stdout: str
    stderr: str
    returncode: int
    duration_sec: float
    error: str | None = None


def run_shell_command(command: str, cwd: str, timeout: int) -> CommandResult:
    return _run(command=command, cwd=cwd, timeout=timeout, shell=True)


def terminate_active_processes() -> int:
    with _ACTIVE_PROCESSES_LOCK:
        processes = list(_ACTIVE_PROCESSES)
    for process in processes:
        _terminate_process(process)
    return len(processes)


def run_process(
    args: Sequence[str],
    cwd: str,
    timeout: int,
    input_text: str | None = None,
    stream_callback: StreamCallback | None = None,
) -> CommandResult:
    command = " ".join(shlex.quote(part) for part in args)
    if stream_callback is not None:
        return _run_streaming(
            command=command,
            cwd=cwd,
            timeout=timeout,
            args=list(args),
            input_text=input_text,
            stream_callback=stream_callback,
        )
    return _run(command=command, cwd=cwd, timeout=timeout, shell=False, args=list(args), input_text=input_text)


def _run(
    command: str,
    cwd: str,
    timeout: int,
    shell: bool,
    args: Sequence[str] | None = None,
    input_text: str | None = None,
) -> CommandResult:
    start = time.monotonic()
    try:
        process = subprocess.Popen(
            command if shell else list(args or []),
            cwd=cwd,
            shell=shell,
            text=True,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        _register_process(process)
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            return CommandResult(
                command=command,
                stdout=stdout or "",
                stderr=stderr or "",
                returncode=process.returncode,
                duration_sec=time.monotonic() - start,
            )
        finally:
            _unregister_process(process)
    except FileNotFoundError as exc:
        return CommandResult(
            command=command,
            stdout="",
            stderr=str(exc),
            returncode=127,
            duration_sec=time.monotonic() - start,
            error=f"Команда не найдена: {exc.filename or command}",
        )
    except subprocess.TimeoutExpired as exc:
        _terminate_process(process)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        message = f"Превышен timeout {timeout} сек."
        if stderr:
            stderr = f"{stderr}\n{message}"
        else:
            stderr = message
        return CommandResult(
            command=command,
            stdout=stdout,
            stderr=stderr,
            returncode=124,
            duration_sec=time.monotonic() - start,
            error=message,
        )


def _run_streaming(
    command: str,
    cwd: str,
    timeout: int,
    args: Sequence[str],
    input_text: str | None,
    stream_callback: StreamCallback,
) -> CommandResult:
    start = time.monotonic()
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    try:
        process = subprocess.Popen(
            list(args),
            cwd=cwd,
            text=True,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            command=command,
            stdout="",
            stderr=str(exc),
            returncode=127,
            duration_sec=time.monotonic() - start,
            error=f"Команда не найдена: {exc.filename or command}",
        )

    _register_process(process)

    def reader(stream_name: str, chunks: list[str]) -> None:
        stream = process.stdout if stream_name == "stdout" else process.stderr
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            chunks.append(line)
            stream_callback(stream_name, line.rstrip("\n"))
        stream.close()

    stdout_thread = threading.Thread(target=reader, args=("stdout", stdout_chunks), daemon=True)
    stderr_thread = threading.Thread(target=reader, args=("stderr", stderr_chunks), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    if input_text is not None and process.stdin is not None:
        try:
            process.stdin.write(input_text)
            process.stdin.close()
        except BrokenPipeError:
            pass

    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process(process)
        returncode = 124
        stream_callback("stderr", f"Превышен timeout {timeout} сек.")
        stderr_chunks.append(f"\nПревышен timeout {timeout} сек.\n")
    finally:
        _unregister_process(process)

    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)

    return CommandResult(
        command=command,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        returncode=returncode,
        duration_sec=time.monotonic() - start,
        error=f"Превышен timeout {timeout} сек." if returncode == 124 else None,
    )


def _register_process(process: subprocess.Popen[str]) -> None:
    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES.add(process)


def _unregister_process(process: subprocess.Popen[str]) -> None:
    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES.discard(process)


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        except OSError:
            process.kill()
