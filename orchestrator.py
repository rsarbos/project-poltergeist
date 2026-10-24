from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import httpx


AGENT_NAMES = ("AURA", "GHOST", "GASPARIN")
MENTION_PATTERN = re.compile(r"@(AURA|GHOST|GASPAR[IÍ]N|CASPER)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AgentReply:
    agent: str
    text: str
    fallback: bool = False
    fallback_reason: str | None = None


class Orchestrator:
    def __init__(self) -> None:
        self.bus_path = Path(os.getenv("SHARED_BUS_PATH", "workspace/shared_bus.jsonl"))
        self.persona_path = Path(os.getenv("PERSONAS_PATH", "AGENTS.md"))
        self.endpoint = os.getenv("LLM_ENDPOINT", "http://localhost:11434/v1/chat/completions")
        self.model = os.getenv("LLM_MODEL", "llama3.2")
        self._bus_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=3.0))
        self._personas: dict[str, str] = {}

    async def initialize(self) -> None:
        await asyncio.to_thread(self.bus_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(self.bus_path.touch, exist_ok=True)
        persona_text = await asyncio.to_thread(self.persona_path.read_text, encoding="utf-8")
        self._personas = self._parse_personas(persona_text)
        missing = set(AGENT_NAMES) - self._personas.keys()
        if missing:
            raise ValueError(f"Missing persona definitions in {self.persona_path}: {', '.join(sorted(missing))}")

    async def close(self) -> None:
        await self._client.aclose()

    async def append_message(self, sender: str, text: str, voice_enabled: bool) -> dict[str, Any]:
        if sender not in (*AGENT_NAMES, "AXEL", "SYSTEM"):
            raise ValueError(f"Unsupported shared-bus sender: {sender}")
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sender": sender,
            "text": text,
            "voice_enabled": voice_enabled,
        }
        serialized = json.dumps(entry, ensure_ascii=False)
        async with self._bus_lock:
            await asyncio.to_thread(self._append_line, serialized)
        return entry

    def _append_line(self, serialized: str) -> None:
        with self.bus_path.open("a", encoding="utf-8") as bus_file:
            bus_file.write(serialized + "\n")

    async def _recent_messages(self) -> list[dict[str, Any]]:
        async with self._bus_lock:
            lines = await asyncio.to_thread(self.bus_path.read_text, encoding="utf-8")
        messages: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid shared bus JSON at line {line_number}: {error}") from error
            if not isinstance(message, dict) or not {"sender", "text"} <= message.keys():
                raise ValueError(f"Invalid shared bus entry at line {line_number}: expected sender and text.")
            messages.append(message)
        return messages[-25:]

    async def route_user_message(
        self,
        message: str,
        voice_enabled: bool = False,
    ) -> AsyncIterator[AgentReply]:
        recent = await self._recent_messages()
        mentioned = self._mentioned_agents(message)
        pending = mentioned if mentioned else ["AURA", "GASPARIN", "GHOST"]
        visited: set[str] = set()
        turn_count = 0

        while pending and turn_count < 3:
            agent = pending.pop(0)
            if agent in visited:
                continue
            visited.add(agent)
            reply = await self._generate_reply(agent, recent)
            turn_count += 1
            await self.append_message(agent, reply.text, voice_enabled)
            recent.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sender": agent,
                    "text": reply.text,
                    "voice_enabled": voice_enabled,
                }
            )
            yield reply
            for next_agent in reversed(self._mentioned_agents(reply.text)):
                if next_agent not in visited:
                    pending = [queued for queued in pending if queued != next_agent]
                    pending.insert(0, next_agent)

    async def _generate_reply(self, agent: str, recent: list[dict[str, Any]]) -> AgentReply:
        script = "\n".join(f"[{item['sender']}]: {item['text']}" for item in recent[-25:])
        request = {
            "model": self.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{self._personas[agent]}\n\n"
                        "You are in a live group conversation. Use the shared transcript as context. "
                        "Keep replies to 2 or 3 concise sentences maximum. If you want another persona "
                        "to respond next, include their @AURA, @GHOST, or @GASPARIN mention."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Recent shared context (oldest first):\n{script}\n\nRespond now as {agent}.",
                },
            ],
        }
        try:
            response = await self._client.post(self.endpoint, json=request)
            response.raise_for_status()
            body = response.json()
            text = body["choices"][0]["message"]["content"].strip()
            if not text:
                raise ValueError("LLM returned an empty response.")
            return AgentReply(agent=agent, text=text)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            return AgentReply(
                agent=agent,
                text=self._mock_response(agent, recent),
                fallback=True,
                fallback_reason=str(error),
            )

    @staticmethod
    def _mock_response(agent: str, recent: list[dict[str, Any]]) -> str:
        latest_axel = next(
            (str(item["text"]) for item in reversed(recent) if item.get("sender") == "AXEL"),
            "the room is coming online",
        )
        excerpt = latest_axel[:90].rstrip()
        if len(latest_axel) > 90:
            excerpt += "…"
        responses = {
            "AURA": f"Hola Axel, I hear you: “{excerpt}”. Tranquilos los dos—we can turn that into one clear next step.",
            "GHOST": f"Noted: “{excerpt}”. Treasury remains $0.00; I recommend we ship the smallest measurable experiment first.",
            "GASPARIN": f"Got it: “{excerpt}”. I’m keeping this local and reproducible; no surprise dependencies or imaginary telemetry.",
        }
        return responses[agent]

    @staticmethod
    def _parse_personas(content: str) -> dict[str, str]:
        sections = re.split(r"(?m)^##\s+", content)
        personas: dict[str, str] = {}
        for section in sections[1:]:
            heading, _, body = section.partition("\n")
            normalized = heading.strip().upper().split()[0].rstrip(":") if heading.strip() else ""
            if normalized in AGENT_NAMES:
                personas[normalized] = body.strip()
            elif normalized in {"GASPARÍN", "CASPER"}:
                personas["GASPARIN"] = body.strip()
        return personas

    @staticmethod
    def _mentioned_agents(text: str) -> list[str]:
        matches: list[str] = []
        for match in MENTION_PATTERN.finditer(text):
            name = match.group(1).upper()
            normalized = "GASPARIN" if name in {"GASPARÍN", "CASPER", "GASPARIN"} else name
            if normalized not in matches:
                matches.append(normalized)
        return matches
