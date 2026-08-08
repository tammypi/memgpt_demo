import asyncio
import json
import os
from collections.abc import AsyncIterator

import httpx


class OpenTalkingError(RuntimeError):
    pass


class OpenTalkingClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("OPENTALKING_URL", "http://127.0.0.1:8210").rstrip("/")
        self.avatar_id = os.getenv("OPENTALKING_AVATAR_ID", "demo-avatar")
        self.model = os.getenv("OPENTALKING_MODEL", "quicktalk")

    async def create_session(self) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/sessions",
                json={"avatar_id": self.avatar_id, "model": self.model},
            )
        if response.is_error:
            raise OpenTalkingError(response.text)
        session_id = response.json().get("session_id")
        if not session_id:
            raise OpenTalkingError("OpenTalking 未返回 session_id")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self.base_url}/sessions/{session_id}/start")
        if response.is_error:
            raise OpenTalkingError(response.text)
        return session_id

    async def speak_flashtalk_audio(self, session_id: str, audio: bytes) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/sessions/{session_id}/speak_flashtalk_audio",
                files={"file": ("speech.wav", audio, "audio/wav")},
            )
        if response.is_error:
            raise OpenTalkingError(response.text)

    async def offer(self, session_id: str, body: dict) -> dict:
        last_error = ""
        for attempt in range(30):
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.base_url}/sessions/{session_id}/webrtc/offer", json=body
                )
            if not response.is_error:
                return response.json()
            last_error = response.text
            if "not loaded" not in last_error and "not ready" not in last_error:
                break
            await asyncio.sleep(1)
        raise OpenTalkingError(last_error)

    async def ice_config(self) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/sessions/webrtc/ice-config")
        if response.is_error:
            raise OpenTalkingError(response.text)
        return response.json()

    async def events(self, session_id: str) -> AsyncIterator[tuple[str, dict]]:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", f"{self.base_url}/sessions/{session_id}/events") as response:
                if response.is_error:
                    raise OpenTalkingError(await response.aread())
                event_name = "message"
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        yield event_name, json.loads(line[5:].strip())
