from __future__ import annotations

import unittest

import httpx

from app.services.summary.deepseek import DeepSeekClient, DeepSeekError
from app.services.summary.settings import SummarySettings

_SSE = (
    'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"！"},"finish_reason":"stop"}],'
    '"usage":{"total_tokens":5}}\n\n'
    "data: [DONE]\n\n"
)


class StreamChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_tokens(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_SSE.encode("utf-8"),
            )

        client = DeepSeekClient(
            SummarySettings(deepseek_api_key="test-key"),
            transport=httpx.MockTransport(handler),
        )
        try:
            tokens = [token async for token in client.stream_chat([{"role": "user", "content": "hi"}])]
        finally:
            await client.aclose()
        self.assertEqual(tokens, ["你", "好", "！"])

    async def test_stream_auth_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"error": {"message": "bad key"}},
            )

        client = DeepSeekClient(
            SummarySettings(deepseek_api_key="bad-key"),
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaises(DeepSeekError) as ctx:
                async for _ in client.stream_chat([{"role": "user", "content": "hi"}]):
                    pass
        finally:
            await client.aclose()
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_stream_missing_key(self) -> None:
        client = DeepSeekClient(SummarySettings(deepseek_api_key=None))
        try:
            with self.assertRaises(DeepSeekError) as ctx:
                async for _ in client.stream_chat([{"role": "user", "content": "hi"}]):
                    pass
        finally:
            await client.aclose()
        self.assertEqual(ctx.exception.kind, "config")


if __name__ == "__main__":
    unittest.main()
