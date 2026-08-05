# coding: utf-8
import asyncio
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from memgpt import MemGpt
from avatar import AliyunVideoRetalkClient, AvatarServiceError

load_dotenv()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    answer: str
    memory_notice: str | None = None


class AvatarRenderRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class AvatarRenderResponse(BaseModel):
    video_url: str
    audio_url: str | None = None
    duration: float | None = None
    task_id: str | None = None


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

avatar = AliyunVideoRetalkClient()
PROJECT_ROOT = Path(__file__).resolve().parent


def state_video_url(env_name: str) -> str:
    source = os.getenv(env_name, "").strip()
    if not source or source.startswith(("http://", "https://")):
        return source
    return source if (PROJECT_ROOT / "frontend" / source).is_file() else ""


def respond(message: str):
    with doctor_lock:
        return doctor.respond(message)


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
        "provider": "aliyun-videoretalk",
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


@app.post("/api/avatar/render", response_model=AvatarRenderResponse)
async def avatar_render(payload: AvatarRenderRequest):
    if not avatar.configured:
        raise HTTPException(
            status_code=503,
            detail=f"数字人配置不完整：{', '.join(avatar.missing_requirements)}",
        )
    try:
        result = await asyncio.to_thread(avatar.render, payload.text.strip())
        return AvatarRenderResponse(**result)
    except (AvatarServiceError, ValueError, TypeError) as error:
        raise HTTPException(status_code=502, detail=f"数字人渲染失败：{error}") from error
