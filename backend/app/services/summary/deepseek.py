from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from app.services.summary.settings import SummarySettings, get_summary_settings

logger = logging.getLogger("vds.summary.deepseek")

_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class DeepSeekError(Exception):
    """统一的 AI 服务错误；``kind`` 供上层映射为中文提示。"""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "upstream",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


class DeepSeekClient:
    """DeepSeek Chat Completions + ASR 客户端。

    只用 httpx，不引入 openai SDK；测试可注入 ``httpx.MockTransport``。
    """

    def __init__(
        self,
        settings: SummarySettings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_summary_settings()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=self.settings.summary_request_timeout_seconds),
                transport=self._transport,
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _auth_headers(self) -> dict[str, str]:
        key = self.settings.api_key
        if not key:
            raise DeepSeekError(
                "AI 总结未启用：缺少 VDS_DEEPSEEK_API_KEY",
                kind="config",
                status_code=503,
            )
        return {"Authorization": f"Bearer {key}"}

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._get_client()
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise DeepSeekError(
                    "AI 服务响应超时，请稍后重试", kind="timeout"
                ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise DeepSeekError(f"无法连接 AI 服务：{exc}", kind="network") from exc

            if response.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS - 1:
                delay = 1.5 * (attempt + 1)
                retry_after = response.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass
                await response.aclose()
                await asyncio.sleep(min(delay, 15))
                continue
            return response
        raise DeepSeekError("AI 服务暂时不可用", kind="network") from last_error

    @staticmethod
    def _error_from_response(response: httpx.Response) -> DeepSeekError:
        status = response.status_code
        detail = ""
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
        except Exception:  # pragma: no cover - defensive
            detail = (response.text or "")[:300]
        detail = detail.strip()[:300]
        suffix = f"：{detail}" if detail else ""

        if status == 401:
            return DeepSeekError(
                "DeepSeek API Key 无效，请检查 backend/.env 中的 VDS_DEEPSEEK_API_KEY",
                kind="auth",
                status_code=401,
            )
        if status == 402:
            return DeepSeekError("DeepSeek 账户余额不足，请先充值", kind="balance", status_code=402)
        if status == 429:
            return DeepSeekError("AI 服务请求过于频繁，请稍后重试", kind="rate_limit", status_code=429)
        if status == 413:
            return DeepSeekError("音频分片超过 AI 服务限制", kind="too_large", status_code=413)
        if status == 400:
            return DeepSeekError(f"AI 服务拒绝了请求{suffix}", kind="bad_request", status_code=400)
        if status >= 500:
            return DeepSeekError(f"AI 服务暂时不可用{suffix}", kind="upstream", status_code=status)
        return DeepSeekError(f"AI 服务返回错误（{status}）{suffix}", kind="upstream", status_code=status)

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 6000,
        temperature: float = 0.2,
    ) -> tuple[str, dict[str, Any]]:
        """调用 Chat Completions 的 JSON 模式，返回 ``(content, meta)``。"""
        payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {
                "type": "enabled" if self.settings.summary_thinking_enabled else "disabled"
            },
        }
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        response = await self._request("POST", self.settings.chat_url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise self._error_from_response(response)

        try:
            data = response.json()
            choice = data["choices"][0]
            content = str(choice["message"].get("content") or "").strip()
            usage = data.get("usage") or {}
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DeepSeekError("AI 返回内容格式异常", kind="bad_response", status_code=502) from exc
        if not content:
            raise DeepSeekError("AI 没有返回总结内容", kind="bad_response", status_code=502)
        return content, {
            "usage": usage,
            "finish_reason": str(choice.get("finish_reason") or ""),
        }

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Chat Completions 流式输出，逐段产出 ``delta.content``。"""
        payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "thinking": {"type": "disabled"},
        }
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        client = self._get_client()
        try:
            async with client.stream(
                "POST",
                self.settings.chat_url,
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise self._error_from_response(response)

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        choice = (chunk.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                    except (ValueError, TypeError, IndexError, AttributeError):
                        logger.warning("无法解析 DeepSeek 流式分片，已跳过")
                        continue
                    if content:
                        yield str(content)
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"AI 流式响应中断：{exc}", kind="network") from exc

    async def transcribe(
        self,
        audio_path: Path,
        *,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """调用独立 ASR 接口，返回 ``{text, duration_ms}``。"""
        auth_headers = self._auth_headers()
        try:
            data = audio_path.read_bytes()
        except OSError as exc:
            raise DeepSeekError(f"读取音频分片失败：{exc}", kind="io") from exc
        if not data:
            raise DeepSeekError("音频分片为空", kind="io")

        suffix = audio_path.suffix.lower()
        mime = content_type or ("audio/ogg" if suffix in {".ogg", ".opus"} else "audio/wav")
        files = {"file": (audio_path.name, data, mime)}
        response = await self._request(
            "POST",
            self.settings.asr_url,
            headers=auth_headers,
            files=files,
        )
        if response.status_code >= 400:
            raise self._error_from_response(response)

        try:
            payload = response.json()
            text = str(payload.get("text") or "").strip()
            duration_ms = int(payload.get("duration_ms") or 0)
        except (TypeError, ValueError) as exc:
            raise DeepSeekError("语音识别返回格式异常", kind="bad_response", status_code=502) from exc
        return {"text": text, "duration_ms": duration_ms}


def parse_json_object(content: str) -> dict[str, Any]:
    """从模型输出中提取第一个完整 JSON 对象。

    兼容 ```json 代码块、前后说明文字；失败时抛出 ``ValueError``。
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("AI 返回为空")

    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI 返回内容不是合法 JSON")
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("AI 返回的 JSON 不是对象")
    return parsed
