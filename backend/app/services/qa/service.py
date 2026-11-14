from __future__ import annotations

import logging
from datetime import date
from typing import Any, AsyncIterator

from pydantic import ValidationError

from app.services.qa.errors import (
    QaGateError,
    QaQuotaError,
    QaValidationError,
)
from app.services.qa.prompts import (
    build_answer_messages,
    build_gate_messages,
    build_material,
    suggest_questions,
    trim_history,
)
from app.services.qa.schemas import QaGateResult
from app.services.summary.deepseek import DeepSeekClient, parse_json_object
from app.services.summary.settings import SummarySettings, get_summary_settings
from app.services.summary.tasks import SummaryTask

logger = logging.getLogger("vds.qa.service")


class QaService:
    """无状态问答服务（额度/日期状态除外）；对话历史由前端提供。"""

    def __init__(self, settings: SummarySettings | None = None) -> None:
        self._settings = settings or get_summary_settings()
        self._daily: dict[str, int] = {}
        self._daily_date: date | None = None

    def _daily_reset_if_needed(self) -> None:
        today = date.today()
        if self._daily_date != today:
            self._daily_date = today
            self._daily.clear()

    def check_daily(self, client_ip: str) -> None:
        self._daily_reset_if_needed()
        limit = self._settings.qa_daily_limit_per_ip
        if limit > 0 and self._daily.get(client_ip, 0) >= limit:
            raise QaQuotaError(
                f"今日 AI 问答次数已达上限（{limit} 次），请明天再试或调高 "
                "VDS_QA_DAILY_LIMIT_PER_IP"
            )

    def increment_daily(self, client_ip: str) -> None:
        self._daily_reset_if_needed()
        self._daily[client_ip] = self._daily.get(client_ip, 0) + 1

    def validate_question(self, question: str) -> str:
        text = (question or "").strip()
        if not text:
            raise QaValidationError("请输入问题")
        limit = self._settings.qa_max_question_chars
        if len(text) > limit:
            raise QaValidationError(f"问题过长（最多 {limit} 字）")
        return text

    def prepare_history(self, history: list[Any]) -> list[dict[str, str]]:
        return trim_history(history, max_messages=self._settings.qa_max_history_messages)

    def material(self, task: SummaryTask) -> str:
        return build_material(task, self._settings.qa_material_max_chars)

    def suggestions(self, task: SummaryTask) -> list[str]:
        return suggest_questions(task.summary)

    async def check_relevance(
        self,
        client: DeepSeekClient,
        task: SummaryTask,
        question: str,
        history: list[dict[str, str]],
    ) -> tuple[bool, dict[str, Any]]:
        material = self.material(task)
        if not material:
            raise QaGateError("当前总结材料为空，无法判断问题相关性")
        messages = build_gate_messages(
            material,
            question,
            history,
            max_history=2,
        )
        last_error: Exception | None = None
        for attempt in range(2):
            content, meta = await client.chat_json(
                messages,
                max_tokens=self._settings.qa_gate_max_tokens,
                temperature=0.0,
            )
            try:
                raw = parse_json_object(content)
                result = QaGateResult.model_validate(raw)
                logger.info(
                    "qa gate task=%s relevant=%s reason=%s",
                    task.id,
                    result.relevant,
                    (result.reason or "")[:160],
                )
                return result.relevant, meta
            except (ValueError, ValidationError) as exc:
                last_error = exc
                if attempt == 0:
                    messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "上一次输出无法解析。请只输出 JSON，例如 "
                                '{"relevant": true, "reason": "问题在询问视频内容"}。'
                                "不要输出 Markdown 代码块或解释。"
                            ),
                        },
                    ]
                    continue
                break

        logger.warning("qa gate failed task=%s error=%s", task.id, last_error)
        raise QaGateError("无法判断问题是否与视频相关，请稍后重试") from last_error

    async def stream_answer(
        self,
        client: DeepSeekClient,
        task: SummaryTask,
        question: str,
        history: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        material = self.material(task)
        messages = build_answer_messages(
            material,
            question,
            history,
            max_history=self._settings.qa_max_history_messages,
        )
        async for token in client.stream_chat(
            messages,
            max_tokens=self._settings.qa_max_answer_tokens,
            temperature=self._settings.qa_answer_temperature,
        ):
            yield token


qa_service = QaService()
