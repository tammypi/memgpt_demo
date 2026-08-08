# coding: utf-8
import asyncio
import json
import os
import threading
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from memgpt import MemGpt
from opentalking_client import OpenTalkingClient, OpenTalkingError

load_dotenv()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    answer: str
    memory_notice: str | None = None


class OpenTalkingSpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


app = FastAPI(title="Dr.Li 有记忆的口腔医生", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

doctor = MemGpt(
    os.getenv("LLM_API_URL", "https://api.moonshot.cn/v1/chat/completions"),
    os.getenv("LLM_API_KEY", ""),
    os.getenv("LLM_MODEL", "moonshot-v1-auto"),
)
doctor_lock = threading.Lock()

opentalking = OpenTalkingClient()
PROJECT_ROOT = Path(__file__).resolve().parent


def state_video_url(env_name: str) -> str:
    source = os.getenv(env_name, "").strip()
    if not source or source.startswith(("http://", "https://")):
        return source
    return source if (PROJECT_ROOT / "frontend" / source).is_file() else ""


def respond(message: str):
    with doctor_lock:
        return doctor.respond(message)


def respond_stream(message: str, on_delta):
    with doctor_lock:
        return doctor.respond_stream(message, on_delta)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": doctor.llm.model_name,
        "configured": bool(doctor.llm.api_key),
        "avatar_provider": "opentalking-quicktalk",
    }


@app.post("/api/opentalking/session")
async def opentalking_session():
    try:
        session_id = await opentalking.create_session()
    except (OpenTalkingError, httpx.HTTPError) as error:
        raise HTTPException(status_code=502, detail=f"OpenTalking 连接失败：{error}") from error
    return {"session_id": session_id, "base_url": opentalking.base_url}


@app.get("/api/opentalking/ice-config")
async def opentalking_ice_config():
    try:
        return await opentalking.ice_config()
    except (OpenTalkingError, httpx.HTTPError) as error:
        raise HTTPException(status_code=502, detail=f"OpenTalking ICE 配置失败：{error}") from error


@app.get("/api/opentalking/sessions/{session_id}/events")
async def opentalking_events(session_id: str):
    async def event_stream():
        async for event_name, payload in opentalking.events(session_id):
            yield f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/opentalking/sessions/{session_id}/speak")
async def opentalking_speak(session_id: str, payload: OpenTalkingSpeakRequest):
    try:
        await opentalking.speak(session_id, payload.text)
    except (OpenTalkingError, httpx.HTTPError) as error:
        raise HTTPException(status_code=502, detail=f"OpenTalking 合成失败：{error}") from error
    return {"status": "queued", "session_id": session_id}


@app.post("/api/opentalking/sessions/{session_id}/webrtc/offer")
async def opentalking_offer(session_id: str, payload: dict):
    try:
        return await opentalking.offer(session_id, payload)
    except (OpenTalkingError, httpx.HTTPError) as error:
        raise HTTPException(status_code=502, detail=f"OpenTalking WebRTC 连接失败：{error}") from error


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):
    if not doctor.llm.api_key:
        raise HTTPException(
            status_code=503,
            detail="尚未配置 LLM_API_KEY，请在 .env 或终端环境变量中设置。",
        )
    answer, memory_notice = await asyncio.to_thread(respond, payload.message.strip())
    if not answer:
        raise HTTPException(status_code=502, detail="模型未返回有效回答，请稍后重试。")
    return ChatResponse(answer=answer, memory_notice=memory_notice)


@app.websocket("/api/chat/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        payload = ChatRequest.model_validate(await websocket.receive_json())
        if not doctor.llm.api_key:
            await websocket.send_json({"type": "error", "message": "尚未配置 LLM_API_KEY"})
            return
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def produce():
            try:
                answer, memory_notice = respond_stream(
                    payload.message.strip(),
                    lambda delta: loop.call_soon_threadsafe(queue.put_nowait, {"type": "delta", "content": delta}),
                )
                loop.call_soon_threadsafe(queue.put_nowait, {
                    "type": "done", "answer": answer, "memory_notice": memory_notice,
                })
            except Exception as error:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(error)})

        worker = asyncio.create_task(asyncio.to_thread(produce))
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event["type"] in {"done", "error"}:
                break
        await worker
    except (WebSocketDisconnect, ValueError):
        return
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass
