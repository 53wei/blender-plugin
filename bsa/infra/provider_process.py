"""把 Provider 网络调用隔离到短生命周期子进程。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..planner.openai_compatible import (
    ProviderConnectionConfig,
    ProviderError,
    ProviderErrorCode,
)
from ..planner.provider import PlannerRequest


MAX_WORKER_OUTPUT_BYTES = 1024 * 1024
MAX_WORKER_INPUT_BYTES = 64 * 1024


@dataclass(frozen=True)
class WorkerOutcome:
    """子进程返回的无秘密结构化结果。"""

    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "result": self.result, "error": self.error}


class ProviderWorkerTask:
    """可轮询、可取消且不会在命令行暴露 Key 的子进程任务。"""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        command: tuple[str, ...],
        deadline: float,
    ) -> None:
        self._process = process
        self.command = command
        self._deadline = deadline
        self._outcome: WorkerOutcome | None = None

    def __repr__(self) -> str:
        return f"ProviderWorkerTask(pid={self._process.pid}, command={self.command!r})"

    @classmethod
    def start(
        cls,
        config: ProviderConnectionConfig,
        api_key: str,
        *,
        python_executable: Path | None = None,
        worker_script: Path | None = None,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> ProviderWorkerTask:
        """启动连接测试；Key 仅写入标准输入。"""

        checked = config.validated()
        return cls._start_worker(
            checked,
            api_key,
            {
                "operation": "connection",
                "api_base": checked.api_base,
                "model": checked.model,
                "timeout_seconds": checked.timeout_seconds,
                "output_format": checked.output_format,
            },
            deadline_seconds=checked.timeout_seconds + 2.0,
            python_executable=python_executable,
            worker_script=worker_script,
            popen_factory=popen_factory,
        )

    @classmethod
    def start_plan(
        cls,
        config: ProviderConnectionConfig,
        api_key: str,
        request: PlannerRequest,
        *,
        python_executable: Path | None = None,
        worker_script: Path | None = None,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> ProviderWorkerTask:
        """启动最多两次 HTTP 调用的结构化规划任务。"""

        checked = config.validated_for_planning()
        return cls._start_worker(
            checked,
            api_key,
            {
                "operation": "plan",
                "api_base": checked.api_base,
                "model": checked.model,
                "timeout_seconds": checked.timeout_seconds,
                "output_format": checked.output_format,
                "request": {
                    "instruction": request.instruction,
                    "scene_context": dict(request.scene_context),
                    "action_schema": dict(request.action_schema),
                },
            },
            deadline_seconds=checked.timeout_seconds * 2.0 + 3.0,
            python_executable=python_executable,
            worker_script=worker_script,
            popen_factory=popen_factory,
        )

    @classmethod
    def _start_worker(
        cls,
        checked: ProviderConnectionConfig,
        api_key: str,
        public_payload: dict[str, Any],
        *,
        deadline_seconds: float,
        python_executable: Path | None,
        worker_script: Path | None,
        popen_factory: Callable[..., subprocess.Popen[bytes]],
    ) -> ProviderWorkerTask:
        """启动统一工作进程；秘密只追加到标准输入负载。"""

        executable = python_executable or find_bundled_python()
        script = worker_script or default_worker_script()
        if not executable.is_file():
            raise ProviderError(ProviderErrorCode.WORKER_FAILED, "找不到 Blender Python")
        if not script.is_file():
            raise ProviderError(ProviderErrorCode.WORKER_FAILED, "找不到 Provider 工作进程")
        command = (str(executable), "-I", "-u", str(script))
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        payload = json.dumps(
            {**public_payload, "api_key": api_key},
            ensure_ascii=False,
        ).encode("utf-8")
        if len(payload) > MAX_WORKER_INPUT_BYTES:
            raise ProviderError(ProviderErrorCode.INVALID_CONFIG, "Provider 配置过大")
        try:
            process = popen_factory(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            if process.stdin is None:
                raise BrokenPipeError("worker stdin unavailable")
            process.stdin.write(payload)
            process.stdin.close()
        except (OSError, BrokenPipeError) as error:
            if "process" in locals() and process.poll() is None:
                process.kill()
            raise ProviderError(ProviderErrorCode.WORKER_FAILED, "无法启动 Provider 工作进程") from error
        return cls(
            process,
            command,
            time.monotonic() + deadline_seconds,
        )

    def poll(self) -> WorkerOutcome | None:
        """非阻塞读取任务状态；完成后始终返回同一个结果。"""

        if self._outcome is not None:
            return self._outcome
        if time.monotonic() > self._deadline:
            self._terminate_process()
            self._close_output_pipes()
            self._outcome = _error_outcome(ProviderErrorCode.TIMEOUT, "连接模型服务超时")
            return self._outcome
        return_code = self._process.poll()
        if return_code is None:
            return None
        if self._process.stdout is None or self._process.stderr is None:
            self._outcome = _error_outcome(ProviderErrorCode.WORKER_FAILED, "工作进程输出不可用")
            return self._outcome
        raw_output = self._process.stdout.read(MAX_WORKER_OUTPUT_BYTES + 1)
        self._process.stderr.read(MAX_WORKER_OUTPUT_BYTES + 1)
        self._close_output_pipes()
        if return_code != 0 or len(raw_output) > MAX_WORKER_OUTPUT_BYTES:
            self._outcome = _error_outcome(ProviderErrorCode.WORKER_FAILED, "工作进程异常退出")
            return self._outcome
        try:
            payload = json.loads(raw_output.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._outcome = _error_outcome(ProviderErrorCode.WORKER_FAILED, "工作进程返回无效结果")
            return self._outcome
        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            self._outcome = _error_outcome(ProviderErrorCode.WORKER_FAILED, "工作进程结果结构无效")
            return self._outcome
        result = payload.get("result", {})
        error = payload.get("error", {})
        if not isinstance(result, dict) or not isinstance(error, dict):
            self._outcome = _error_outcome(ProviderErrorCode.WORKER_FAILED, "工作进程结果结构无效")
        else:
            self._outcome = WorkerOutcome(payload["ok"], result, error)
        return self._outcome

    def cancel(self) -> WorkerOutcome:
        """终止当前工作进程并返回稳定取消结果。"""

        if self._outcome is None:
            self._terminate_process()
            self._close_output_pipes()
            self._outcome = _error_outcome(ProviderErrorCode.CANCELED, "连接测试已取消")
        return self._outcome

    def _terminate_process(self) -> None:
        if self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=0.5)

    def _close_output_pipes(self) -> None:
        for pipe in (self._process.stdout, self._process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()


def default_worker_script() -> Path:
    """返回随扩展分发的 worker 脚本。"""

    return Path(__file__).resolve().parents[1] / "planner" / "llm" / "worker.py"


def find_bundled_python(prefix: Path | None = None) -> Path:
    """定位 Blender 自带 Python；不静默回退到未知系统解释器。"""

    root = Path(sys.prefix) if prefix is None else prefix
    candidates = (
        root / "bin" / "python.exe",
        root / "bin" / "python3",
        root / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ProviderError(ProviderErrorCode.WORKER_FAILED, "找不到 Blender 自带 Python")


def _error_outcome(code: ProviderErrorCode, message: str) -> WorkerOutcome:
    return WorkerOutcome(False, error={"code": code.value, "message": message, "details": {}})
