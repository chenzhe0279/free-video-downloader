from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QaHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class QaAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[QaHistoryMessage] = Field(default_factory=list, max_length=20)


class QaGateResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    relevant: bool
    reason: str = ""
