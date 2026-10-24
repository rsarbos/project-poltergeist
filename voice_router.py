from __future__ import annotations

import asyncio
import io
import os
from dataclasses import dataclass
from typing import Callable

import httpx


DEFAULT_VOICES = {"AURA": "ef_dora", "GASPARIN": "am_adam", "GHOST": "bm_george"}
KOKORO_ENDPOINT = os.getenv("KOKORO_ENDPOINT", "http://localhost:8880/v1/audio/speech")


@dataclass(frozen=True)
class VoiceRequest:
    agent: str
    text: str
    voice: str
    speed: float


class VoiceRouter:
    def __init__(self, on_error: Callable[[str], None] | None = None) -> None:
        self.enabled = False
        self.voices = dict(DEFAULT_VOICES)
        self.speeds = {"AURA": 1.0, "GASPARIN": 1.25, "GHOST": 0.95}
        self._queue: asyncio.Queue[VoiceRequest | None] = asyncio.Queue()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
        self._consumer: asyncio.Task[None] | None = None
        self._on_error = on_error or (lambda _: None)

    async def start(self) -> None:
        if self._consumer is None:
            self._consumer = asyncio.create_task(self._consume(), name="voice-playback-queue")

    async def close(self) -> None:
        if self._consumer is not None:
            await self._queue.put(None)
            await self._consumer
            self._consumer = None
        await self._client.aclose()

    def voice_for(self, agent: str) -> str:
        return self.voices[agent]

    def set_voice(self, agent: str, voice_id: str) -> None:
        if agent not in self.voices:
            raise ValueError(f"Unknown voice agent: {agent}")
        self.voices[agent] = voice_id

    def enqueue(self, agent: str, text: str, *, voice: str | None = None, speed: float | None = None) -> None:
        if self.enabled:
            self._queue.put_nowait(
                VoiceRequest(
                    agent=agent,
                    text=text,
                    voice=voice or self.voices[agent],
                    speed=speed if speed is not None else self.speeds[agent],
                )
            )

    async def initialize_all(self) -> None:
        await self.start()
        self.enabled = True
        self.enqueue("AURA", "Hola Axel. Welcome to the command center. Tranquilos los dos—we have a plan.")
        self.enqueue(
            "GASPARIN",
            "Testing, testing—ugh, no, parezco ardilla.",
            voice="am_michael",
            speed=1.6,
        )
        self.set_voice("GASPARIN", "am_adam")
        self.enqueue(
            "GASPARIN",
            "All right, actual engineer voice. Systems are local, the container is standing by, and I need fewer Chrome tabs.",
            voice="am_adam",
            speed=1.25,
        )
        self.enqueue(
            "GHOST",
            "Voice systems online. Treasury remains zero dollars until proven otherwise.",
            voice="bm_george",
            speed=0.95,
        )

    @staticmethod
    def awakening_lines() -> list[tuple[str, str]]:
        return [
            ("AURA", "Hola Axel. Welcome to the command center. Tranquilos los dos—we have a plan."),
            ("GASPARIN", "Testing, testing—ugh, no, parezco ardilla. Switching to my actual engineer voice."),
            ("GASPARIN", "Systems are local, the container is standing by, and I need fewer Chrome tabs."),
            ("GHOST", "Voice systems online. Treasury remains zero dollars until proven otherwise."),
        ]

    async def _consume(self) -> None:
        while True:
            request = await self._queue.get()
            try:
                if request is None:
                    return
                await self._speak(request)
            except (httpx.HTTPError, OSError, RuntimeError, ImportError, ValueError) as error:
                self._on_error(f"{request.agent}: {error}" if request is not None else str(error))
            finally:
                self._queue.task_done()

    async def _speak(self, request: VoiceRequest) -> None:
        response = await self._client.post(
            KOKORO_ENDPOINT,
            json={
                "model": "kokoro",
                "input": request.text,
                "voice": request.voice,
                "response_format": "wav",
                "speed": request.speed,
            },
        )
        response.raise_for_status()
        await asyncio.to_thread(self._play_audio, response.content)

    @staticmethod
    def _play_audio(audio: bytes) -> None:
        import sounddevice as sd
        import soundfile as sf

        samples, sample_rate = sf.read(io.BytesIO(audio), dtype="float32")
        sd.play(samples, sample_rate)
        sd.wait()
