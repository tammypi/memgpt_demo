# coding: utf-8
import asyncio
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from memgpt import MemGpt

load_dotenv()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    answer: str
    memory_notice: str | None = None


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


def respond(message: str):
    with doctor_lock:
        return doctor.respond(message)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": doctor.llm.model_name,
        "configured": bool(doctor.llm.api_key),
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
