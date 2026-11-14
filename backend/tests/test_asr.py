from __future__ import annotations

import asyncio
import shutil
import unittest
import wave
from pathlib import Path

from app.services.summary.asr import (
    AsrChunk,
    AsrError,
    split_audio,
    transcribe_chunks,
)

_RUNTIME = Path(__file__).resolve().parents[2] / "runtime" / "test-asr"


def _make_wav(path: Path, seconds: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * seconds)


class FakeAsrClient:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls = 0

    async def transcribe(self, path: Path, *, content_type: str | None = None):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return {"text": text, "duration_ms": 120000}


class AsrTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        shutil.rmtree(_RUNTIME, ignore_errors=True)
        _RUNTIME.mkdir(parents=True, exist_ok=True)

    async def asyncTearDown(self) -> None:
        shutil.rmtree(_RUNTIME, ignore_errors=True)

    async def test_split_audio(self) -> None:
        source = _RUNTIME / "input.wav"
        _make_wav(source, seconds=3)
        chunks = await split_audio(source, _RUNTIME / "chunks", 3, 120)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].start_seconds, 0.0)
        self.assertEqual(chunks[0].end_seconds, 3.0)
        self.assertTrue(chunks[0].path.exists())
        self.assertIn(chunks[0].content_type, {"audio/ogg", "audio/wav"})

    async def test_transcribe_chunks_merges_in_order(self) -> None:
        source = _RUNTIME / "chunk.ogg"
        source.write_bytes(b"x" * 2048)
        chunks = [
            AsrChunk(0, 0.0, 120.0, source, "audio/ogg"),
            AsrChunk(1, 120.0, 240.0, source, "audio/ogg"),
        ]
        client = FakeAsrClient(["第一段", "第二段"])
        segments, seconds = await transcribe_chunks(
            chunks,
            client,  # type: ignore[arg-type]
            concurrency=2,
        )
        self.assertEqual([segment.text for segment in segments], ["第一段", "第二段"])
        self.assertEqual(segments[1].start_seconds, 120.0)
        self.assertAlmostEqual(seconds, 240.0)

    async def test_empty_text_raises(self) -> None:
        source = _RUNTIME / "chunk.ogg"
        source.write_bytes(b"x" * 2048)
        chunks = [AsrChunk(0, 0.0, 120.0, source, "audio/ogg")]
        client = FakeAsrClient(["   "])
        with self.assertRaises(AsrError):
            await transcribe_chunks(chunks, client, concurrency=1)  # type: ignore[arg-type]

    async def test_cancellation_cleans_up(self) -> None:
        source = _RUNTIME / "chunk.ogg"
        source.write_bytes(b"x" * 2048)
        chunks = [AsrChunk(0, 0.0, 120.0, source, "audio/ogg")]

        class SlowClient:
            async def transcribe(self, path, *, content_type=None):
                await asyncio.sleep(10)
                return {"text": "慢", "duration_ms": 1000}

        task = asyncio.create_task(
            transcribe_chunks(chunks, SlowClient(), concurrency=1)  # type: ignore[arg-type]
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
