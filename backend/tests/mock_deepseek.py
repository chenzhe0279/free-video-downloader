from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="Mock DeepSeek", version="0.1.0")

_SUMMARY: dict[str, Any] = {
    "tldr": "这是一条模拟总结：视频用几个例子说明 AI 视频总结的完整流程。",
    "overview": "模拟的 DeepSeek 返回内容，用于在没有真实 API Key 的情况下验证整条链路。"
    "视频从链接解析、逐字稿获取、语音识别到结构化总结逐步展开，并给出可回看的时间戳。",
    "keywords": ["AI 总结", "DeepSeek", "逐字稿", "时间戳"],
    "chapters": [
        {
            "start_seconds": 0,
            "end_seconds": 30,
            "title": "问题与目标",
            "summary": "说明为什么需要把长视频压缩成可复习的笔记。",
            "key_points": ["长视频信息密度低", "先看结论再回看"],
        },
        {
            "start_seconds": 30,
            "end_seconds": 60,
            "title": "技术流程",
            "summary": "介绍平台字幕、ASR 兜底和 JSON 结构化总结的流程。",
            "key_points": ["字幕优先", "无字幕走 ASR"],
        },
        {
            "start_seconds": 60,
            "end_seconds": 120,
            "title": "使用建议",
            "summary": "建议结合时间戳回看，并对 AI 生成内容进行核对。",
            "key_points": ["点击时间戳跳转", "AI 内容需要核对"],
        },
    ],
    "key_points": [
        {"title": "先看 TL;DR", "detail": "用一句话判断视频是否值得继续看。", "timestamp_seconds": 0},
        {"title": "按章节学习", "detail": "章节大纲给出内容结构。", "timestamp_seconds": 30},
        {"title": "回看原文", "detail": "点击时间戳回到视频对应位置。", "timestamp_seconds": 60},
        {"title": "导出笔记", "detail": "支持复制和下载 Markdown。", "timestamp_seconds": 60},
        {"title": "注意准确性", "detail": "AI 生成内容可能有偏差。", "timestamp_seconds": 60},
    ],
    "concepts": [
        {"term": "ASR", "explanation": "自动语音识别，把音频转成文字。"},
        {"term": "逐字稿", "explanation": "视频完整口播文本，是总结的输入。"},
    ],
    "mindmap": {
        "title": "AI 视频总结",
        "children": [
            {
                "title": "输入",
                "children": [{"title": "平台字幕"}, {"title": "ASR 兜底"}],
            },
            {
                "title": "处理",
                "children": [{"title": "分片识别"}, {"title": "结构化总结"}],
            },
            {
                "title": "输出",
                "children": [{"title": "章节"}, {"title": "要点"}, {"title": "思维导图"}],
            },
        ],
    },
}


@app.post("/chat/completions")
async def chat_completions(request: Request) -> dict[str, Any]:
    await request.json()
    content = json.dumps(_SUMMARY, ensure_ascii=False)
    return {
        "id": "mock-chat",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 600, "total_tokens": 1800},
    }


async def _asr_response() -> dict[str, Any]:
    return {
        "request_id": "mock-asr",
        "text": "这是模拟的语音识别逐字稿。视频介绍了 AI 视频总结的完整流程："
        "先解析链接，再优先获取平台字幕，没有字幕时把音频切成两分钟的分片，"
        "调用语音识别接口，最后用大模型生成带时间戳的章节、要点和思维导图。"
        "使用时应结合时间戳回看原视频，并注意 AI 生成内容可能有偏差。",
        "duration_ms": 120000,
    }


@app.post("/v1/tools/asr")
async def asr(request: Request) -> dict[str, Any]:
    # 不解析 multipart，避免测试环境额外依赖 python-multipart
    await request.body()
    return await _asr_response()


@app.post("/tools/asr")
async def asr_short(request: Request) -> dict[str, Any]:
    await request.body()
    return await _asr_response()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tests.mock_deepseek:app", host="127.0.0.1", port=8100, reload=False)
