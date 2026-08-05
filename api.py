# coding: utf-8
import asyncio
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from memgpt import MemGpt
from avatar import LocalAvatarClient, AvatarServiceError, OUTPUT_ROOT

load_dotenv()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    answer: str
    memory_notice: str | None = None


class AvatarRenderRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class AvatarJobResponse(BaseModel):
    job_id: str
    status: str
    segments: list[dict]
    segment_count: int
    error: str | None = None
    created_at: float


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
app.mount("/avatar-files", StaticFiles(directory=OUTPUT_ROOT), name="avatar-files")

doctor = MemGpt(
    os.getenv("LLM_API_URL", "https://api.moonshot.cn/v1/chat/completions"),
    os.getenv("LLM_API_KEY", ""),
    os.getenv("LLM_MODEL", "moonshot-v1-auto"),
)
doctor_lock = threading.Lock()

avatar = LocalAvatarClient()
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
        "avatar_configured": avatar.configured,
    }


@app.get("/api/avatar/config")
def avatar_config():
    return {
        "enabled": avatar.configured,
        "provider": "local-cosyvoice-musetalk",
        "missing_requirements": avatar.missing_requirements,
        "state_videos": {
            "idle": state_video_url("AVATAR_IDLE_VIDEO"),
            "listening": state_video_url("AVATAR_LISTENING_VIDEO"),
            "thinking": state_video_url("AVATAR_THINKING_VIDEO"),
        },
    }


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


@app.post("/api/avatar/render", response_model=AvatarJobResponse)
async def avatar_render(payload: AvatarRenderRequest):
    if not avatar.configured:
        raise HTTPException(
            status_code=503,
            detail=f"本地数字人尚未安装：{', '.join(avatar.missing_requirements)}",
        )
    try:
        return AvatarJobResponse(**avatar.create_job(payload.text.strip()))
    except (AvatarServiceError, ValueError, TypeError) as error:
        raise HTTPException(status_code=502, detail=f"数字人渲染失败：{error}") from error


@app.get("/api/avatar/jobs/{job_id}", response_model=AvatarJobResponse)
def avatar_job(job_id: str):
    try:
        return AvatarJobResponse(**avatar.get_job(job_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="数字人任务不存在") from error
