"""不依赖 Blender 的界面文案、宽度与固定助手几何。"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .assistant_state import AssistantStatus
from ..planner.openai_compatible import (
    ProviderConnectionConfig,
    ProviderError,
    ProviderErrorCode,
)


AVATAR_SIZE_PX = 92.0
AVATAR_HIT_RADIUS = 42.0
POPUP_WIDTH_PX = 420

_PROVIDER_ERROR_MESSAGES = {
    ProviderErrorCode.INVALID_CONFIG.value: "请检查 API 地址、模型和超时设置",
    ProviderErrorCode.AUTHENTICATION_FAILED.value: "API Key 无效或没有访问权限",
    ProviderErrorCode.RATE_LIMITED.value: "请求过于频繁或账户额度受限",
    ProviderErrorCode.CONNECTION_FAILED.value: "无法连接模型服务，请检查地址和网络",
    ProviderErrorCode.TIMEOUT.value: "连接模型服务超时",
    ProviderErrorCode.SERVER_ERROR.value: "模型服务暂时不可用",
    ProviderErrorCode.ONLINE_ACCESS_DISABLED.value: "Blender 当前禁止扩展联网",
    ProviderErrorCode.CANCELED.value: "连接测试已取消",
    ProviderErrorCode.WORKER_FAILED.value: "连接测试进程未能正常完成",
    ProviderErrorCode.OUTPUT_INVALID.value: "模型没有返回可用的结构化计划",
}


@dataclass(frozen=True)
class PhasePresentation:
    """仅描述现有状态，不改变工作流或宣称动作已经执行。"""

    step: int
    title: str
    icon: str


_PHASES = {
    AssistantStatus.IDLE: PhasePresentation(1, "输入要求", "OUTLINER_DATA_FONT"),
    AssistantStatus.AI_REVIEW: PhasePresentation(1, "AI 发送确认", "LOCKED"),
    AssistantStatus.PLANNING: PhasePresentation(1, "正在生成计划", "TIME"),
    AssistantStatus.PLAN_READY: PhasePresentation(2, "检查计划", "PREVIEW_RANGE"),
    AssistantStatus.WORKING: PhasePresentation(3, "正在执行", "TIME"),
    AssistantStatus.SUCCESS: PhasePresentation(3, "已完成", "CHECKMARK"),
    AssistantStatus.ERROR: PhasePresentation(1, "需要处理", "ERROR"),
}


def phase_for(status: AssistantStatus) -> PhasePresentation:
    """返回现有状态对应的阶段标题。"""
    return _PHASES[status]


def display_width(text: str) -> int:
    """按东亚全宽字符估算占用；组合附加符不另占一格。"""
    return sum(
        0 if unicodedata.combining(char) else (
            2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        ) for char in text
    )


def wrap_display_text(text: str, *, columns: int) -> tuple[str, ...]:
    """保留全部文本和显式换行，避免按字符数量把中文画出面板。"""
    if columns < 2:
        raise ValueError("Text needs at least two display columns")
    lines = []
    for source in (text or "").splitlines() or [""]:
        line, used = "", 0
        for char in source:
            width = display_width(char)
            if used + width > columns and line:
                lines.append(line)
                line, used = "", 0
            line += char
            used += width
        lines.append(line)
    return tuple(lines)


def text_columns(width_pixels: float, *, ui_scale: float = 1.0) -> int:
    """为原生边距留空间；小侧栏和较大系统字号使用更短的行。"""
    return max(12, min(72, int((width_pixels / max(ui_scale, 0.5) - 40) / 7)))


def planning_config_issue(
    api_base: str, model: str, timeout_seconds: int, output_format: str,
) -> str | None:
    """只读校验和恢复指引，不联网、不检查或显示任何密钥。"""
    if not model.strip():
        return "还没选择 AI 模型。打开设置，填写模型名称。"
    try:
        ProviderConnectionConfig(
            api_base, model, timeout_seconds, output_format
        ).validated_for_planning()
    except ProviderError as error:
        return error.message + "；请在设置中修改。"
    return None


def provider_error_message(error: ProviderError | str, detail: str = "") -> str:
    """保留安全的具体响应错误；其余稳定错误使用统一用户文案。"""
    if isinstance(error, ProviderError):
        code = error.code.value
        detail = error.message
    else:
        code = str(error)
    if code == ProviderErrorCode.INVALID_RESPONSE.value and detail:
        return detail
    return _PROVIDER_ERROR_MESSAGES.get(code, detail or "模型服务操作失败")
