"""不持久化明文的 BYOK 凭据解析。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class CredentialSource(StrEnum):
    """API Key 的来源；只记录来源，不记录值。"""

    SESSION = "SESSION"
    BSA_ENV = "BSA_ENV"
    OPENAI_ENV = "OPENAI_ENV"
    NONE = "NONE"


@dataclass(frozen=True, repr=False)
class ResolvedCredential:
    """内存中的短生命周期凭据。repr 永不展示秘密。"""

    value: str
    source: CredentialSource

    def __repr__(self) -> str:
        return f"ResolvedCredential(value='[REDACTED]', source={self.source.value!r})"


def resolve_api_key(
    session_key: str,
    environ: Mapping[str, str] | None = None,
) -> ResolvedCredential:
    """按会话、BSA 环境变量、OpenAI 环境变量的顺序解析 Key。"""

    values = os.environ if environ is None else environ
    candidates = (
        (session_key.strip(), CredentialSource.SESSION),
        (values.get("BSA_API_KEY", "").strip(), CredentialSource.BSA_ENV),
        (values.get("OPENAI_API_KEY", "").strip(), CredentialSource.OPENAI_ENV),
    )
    for value, source in candidates:
        if value:
            return ResolvedCredential(value=value, source=source)
    return ResolvedCredential(value="", source=CredentialSource.NONE)
