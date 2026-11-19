"""仅依赖标准库的渲染输出预算和进程捕获。"""

from __future__ import annotations

from dataclasses import dataclass
import io
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time
from typing import Literal, Mapping, Sequence

DEFAULT_OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024
DEFAULT_TAIL_BYTES = 12000
_READ_BYTES = 64 * 1024
_PIPE_GRACE_SECONDS = 0.25
StreamName = Literal["stdout", "stderr"]
CaptureFailure = Literal["timeout", "output_limit", "incomplete_output"]


def _positive_bytes(value: int, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


class OutputLimitExceeded(RuntimeError):
    def __init__(self, limit_bytes: int):
        super().__init__(f"渲染输出达到字节限额（{limit_bytes} bytes）")
        self.limit_bytes = limit_bytes


class OutputBudget:
    """两路流共享总字节限额，各自仅保留固定长度尾部。"""

    def __init__(
        self,
        limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
        tail_bytes: int = DEFAULT_TAIL_BYTES,
    ) -> None:
        self.limit_bytes = _positive_bytes(limit_bytes, "limit_bytes")
        self.tail_bytes = _positive_bytes(tail_bytes, "tail_bytes")
        self._tails = {"stdout": bytearray(), "stderr": bytearray()}
        self._total_bytes = 0
        self._exceeded = False
        self._lock = threading.Lock()

    def feed(self, stream: StreamName, data: bytes) -> bool:
        with self._lock:
            tail = self._tails[stream]
            tail.extend(data[-self.tail_bytes :])
            if len(tail) > self.tail_bytes:
                del tail[: -self.tail_bytes]
            self._total_bytes += len(data)
            self._exceeded |= self._total_bytes >= self.limit_bytes
            return self._exceeded

    def check(self) -> None:
        with self._lock:
            if self._exceeded:
                raise OutputLimitExceeded(self.limit_bytes)

    def text(self, stream: StreamName) -> str:
        with self._lock:
            return self._tails[stream].decode("utf-8", errors="replace")


class BoundedTextCapture(io.TextIOBase):
    def __init__(self, budget: OutputBudget, stream: StreamName) -> None:
        super().__init__()
        self.budget = budget
        self.stream = stream

    # TextIOBase 在运行时将 encoding 暴露为只读属性。
    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if self.closed:
            raise ValueError("I/O operation on closed file")
        if not isinstance(text, str):
            raise TypeError("write() argument must be str")
        self.budget.check()
        # 分块编码，避免单次巨量 write 再分配同等大小的字节副本。
        for offset in range(0, len(text), 16384):
            self.budget.feed(
                self.stream,
                text[offset : offset + 16384].encode("utf-8", errors="replace"),
            )
            self.budget.check()
        return len(text)

    def getvalue(self) -> str:
        return self.budget.text(self.stream)


@dataclass(frozen=True)
class ProcessCapture:
    returncode: int
    elapsed_seconds: float
    stdout: str
    stderr: str
    failure: CaptureFailure | None


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _read_ready(
    selector: selectors.BaseSelector, budget: OutputBudget, wait: float
) -> bool:
    exceeded = False
    for key, _ in selector.select(wait):
        try:
            data = os.read(key.fd, _READ_BYTES)
        except BlockingIOError:
            continue
        if data:
            exceeded |= budget.feed(key.data, data)
        else:
            selector.unregister(key.fileobj)
    return exceeded


def _capture_until_done(
    process: subprocess.Popen[bytes],
    selector: selectors.BaseSelector,
    budget: OutputBudget,
    deadline: float,
) -> CaptureFailure | None:
    exited_at = None
    while True:
        now = time.monotonic()
        if process.poll() is not None:
            if not selector.get_map():
                return None
            if exited_at is None:
                exited_at = now
            if now - exited_at >= _PIPE_GRACE_SECONDS:
                return "incomplete_output"
        if now >= deadline:
            return "timeout"
        wait = min(0.05, deadline - now)
        if selector.get_map():
            if _read_ready(selector, budget, wait):
                return "output_limit"
        else:
            # 两路流可能先关闭，但进程仍在运行；等待仍受同一截止时间约束。
            try:
                process.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                pass


def _drain_after_stop(selector: selectors.BaseSelector, budget: OutputBudget) -> None:
    deadline = time.monotonic() + _PIPE_GRACE_SECONDS
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        _read_ready(selector, budget, min(0.05, remaining))


def capture_process(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> ProcessCapture:
    if not math.isfinite(timeout):
        raise ValueError("timeout must be finite")
    budget = OutputBudget(output_limit_bytes, tail_bytes)
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    failure = None
    group_stopped = False
    try:
        with selectors.DefaultSelector() as selector:
            assert process.stdout is not None and process.stderr is not None
            for stream, name in (
                (process.stdout, "stdout"),
                (process.stderr, "stderr"),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            failure = _capture_until_done(process, selector, budget, started + timeout)
            if failure is not None:
                _kill_group(process)
                group_stopped = True
                _drain_after_stop(selector, budget)
    finally:
        try:
            if not group_stopped and (failure is not None or process.poll() is None):
                _kill_group(process)
        finally:
            for cleanup_stream in (process.stdout, process.stderr):
                if cleanup_stream is not None:
                    cleanup_stream.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=1)
    return ProcessCapture(
        returncode=process.returncode,
        elapsed_seconds=round(time.monotonic() - started, 3),
        stdout=budget.text("stdout").replace("\r\n", "\n").replace("\r", "\n"),
        stderr=budget.text("stderr").replace("\r\n", "\n").replace("\r", "\n"),
        failure=failure,
    )
