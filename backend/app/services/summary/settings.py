from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BACKEND_DIR


class SummarySettings(BaseSettings):
    """AI 总结专用配置。

    独立于 ``app.config.Settings``，避免修改已有配置结构；同样读取
    ``VDS_*`` 环境变量和 ``backend/.env``。
    """

    model_config = SettingsConfigDict(
        env_prefix="VDS_",
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    summary_enabled: bool = True
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    summary_max_duration_seconds: int = 2 * 3600
    summary_daily_limit_per_ip: int = 3
    summary_rate_limit_per_minute: int = 5
    summary_max_concurrent: int = 2
    summary_max_concurrent_per_ip: int = 1
    summary_task_ttl_seconds: int = 1800
    summary_cache_ttl_seconds: int = 6 * 3600
    summary_cache_max_entries: int = 50

    # 60 秒分片：在官方 120 秒上限内，同时给章节/要点提供 1 分钟级时间戳
    summary_asr_chunk_seconds: int = 60
    summary_asr_concurrency: int = 4
    summary_max_audio_bytes: int = 500 * 1024**2
    summary_max_transcript_chars: int = 200_000
    summary_request_timeout_seconds: int = 180
    summary_prompt_version: str = "v2"
    summary_thinking_enabled: bool = False
    summary_asr_price_per_hour_cny: float = 0.78

    # ---- 进度/内容流（SSE） ----
    # 前端不展示进度条：未完成时只推送状态文案，完成后把 Markdown 逐块下发
    summary_stream_poll_seconds: float = 0.8
    summary_stream_chunk_chars: int = 48
    summary_stream_interval_ms: int = 35

    @field_validator("summary_stream_interval_ms")
    @classmethod
    def _clamp_stream_interval(cls, value: int) -> int:
        return max(0, min(200, int(value)))

    @field_validator("summary_stream_chunk_chars")
    @classmethod
    def _clamp_stream_chunk(cls, value: int) -> int:
        return max(16, min(400, int(value)))

    # ---- 视频内 AI 问答 ----
    qa_enabled: bool = True
    qa_rate_limit_per_minute: int = 10
    qa_daily_limit_per_ip: int = 30
    qa_max_question_chars: int = 500
    qa_max_history_messages: int = 6
    qa_max_answer_tokens: int = 1200
    qa_gate_max_tokens: int = 120
    qa_material_max_chars: int = 12000
    qa_answer_temperature: float = 0.3

    @field_validator("summary_asr_chunk_seconds")
    @classmethod
    def _clamp_chunk_seconds(cls, value: int) -> int:
        # DeepSeek ASR 单次最长 120 秒，超出会被服务端拒绝
        return max(10, min(120, int(value)))

    @field_validator("summary_asr_concurrency")
    @classmethod
    def _clamp_asr_concurrency(cls, value: int) -> int:
        return max(1, min(8, int(value)))

    @field_validator("summary_max_concurrent")
    @classmethod
    def _clamp_max_concurrent(cls, value: int) -> int:
        return max(1, min(8, int(value)))

    @field_validator("qa_max_question_chars")
    @classmethod
    def _clamp_question_chars(cls, value: int) -> int:
        return max(20, min(2000, int(value)))

    @field_validator("qa_max_history_messages")
    @classmethod
    def _clamp_history_messages(cls, value: int) -> int:
        return max(2, min(20, int(value)))

    @field_validator("qa_max_answer_tokens")
    @classmethod
    def _clamp_answer_tokens(cls, value: int) -> int:
        return max(200, min(4000, int(value)))

    @field_validator("qa_gate_max_tokens")
    @classmethod
    def _clamp_gate_tokens(cls, value: int) -> int:
        return max(50, min(500, int(value)))

    @field_validator("qa_rate_limit_per_minute")
    @classmethod
    def _clamp_qa_rate(cls, value: int) -> int:
        return max(1, min(60, int(value)))

    @field_validator("qa_daily_limit_per_ip")
    @classmethod
    def _clamp_qa_daily(cls, value: int) -> int:
        return max(0, min(500, int(value)))

    @field_validator("qa_material_max_chars")
    @classmethod
    def _clamp_material_chars(cls, value: int) -> int:
        return max(2000, min(50000, int(value)))

    @property
    def api_key(self) -> str | None:
        if self.deepseek_api_key is None:
            return None
        value = self.deepseek_api_key.get_secret_value().strip()
        return value or None

    @property
    def enabled(self) -> bool:
        return bool(self.summary_enabled and self.api_key)

    @property
    def qa_available(self) -> bool:
        return bool(self.qa_enabled and self.summary_enabled and self.api_key)

    @property
    def chat_url(self) -> str:
        return f"{self.deepseek_base_url.rstrip('/')}/chat/completions"

    @property
    def asr_url(self) -> str:
        base = self.deepseek_base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/tools/asr"
        return f"{base}/v1/tools/asr"


@lru_cache(maxsize=1)
def get_summary_settings() -> SummarySettings:
    return SummarySettings()
