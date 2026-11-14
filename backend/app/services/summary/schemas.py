from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TranscriptSource = Literal["subtitle", "asr"]
SummaryTaskState = Literal[
    "queued",
    "fetching",
    "transcribing",
    "summarizing",
    "finished",
    "error",
    "cancelled",
]


class SummaryRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    force: bool = False


class SummaryConfigResponse(BaseModel):
    enabled: bool
    provider: str = "deepseek"
    model: str
    max_duration_seconds: int
    daily_limit_per_ip: int
    rate_limit_per_minute: int
    asr_chunk_seconds: int
    qa_enabled: bool = False
    qa_daily_limit_per_ip: int = 30
    qa_rate_limit_per_minute: int = 10
    qa_max_question_chars: int = 500
    reason: str | None = None


class TranscriptSegment(BaseModel):
    """逐字稿分段；字幕保留原始时间，ASR 使用分片起点。"""

    start_seconds: float = 0
    end_seconds: float | None = None
    text: str = ""


class TranscriptResult(BaseModel):
    source: TranscriptSource
    language: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)
    asr_seconds: float = 0
    chunks: int = 0

    @property
    def chars(self) -> int:
        return sum(len(segment.text) for segment in self.segments)


class MindmapNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    children: list["MindmapNode"] = Field(default_factory=list)


class SummaryChapter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start_seconds: float = 0
    end_seconds: float | None = None
    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)


class SummaryKeyPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    detail: str = ""
    timestamp_seconds: float | None = None


class SummaryConcept(BaseModel):
    model_config = ConfigDict(extra="ignore")

    term: str = ""
    explanation: str = ""


class SummaryPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tldr: str = ""
    overview: str = ""
    keywords: list[str] = Field(default_factory=list)
    chapters: list[SummaryChapter] = Field(default_factory=list)
    key_points: list[SummaryKeyPoint] = Field(default_factory=list)
    concepts: list[SummaryConcept] = Field(default_factory=list)
    mindmap: MindmapNode | None = None
    markdown: str = ""


class SummaryStats(BaseModel):
    chunks: int = 0
    asr_seconds: float = 0
    transcript_chars: int = 0
    segments: int = 0
    model: str = ""
    elapsed_seconds: float = 0
    cached: bool = False
    asr_cost_estimate_cny: float | None = None


class SummaryTaskStatus(BaseModel):
    task_id: str
    status: SummaryTaskState
    stage: str = ""
    progress: float = 0
    message: str | None = None
    title: str = ""
    duration: float | None = None
    platform: str | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    cached: bool = False
    transcript_source: TranscriptSource | None = None
    transcript_language: str | None = None
    stats: SummaryStats = Field(default_factory=SummaryStats)
    summary: SummaryPayload | None = None
    error: str | None = None
    expires_in: int | None = None


class SummaryCreateResponse(BaseModel):
    task_id: str
    status: SummaryTaskState
    cached: bool = False


class SummaryTranscriptResponse(BaseModel):
    task_id: str
    source: TranscriptSource | None = None
    language: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)


class SummaryDeleteResponse(BaseModel):
    status: str = "deleted"


MindmapNode.model_rebuild()
