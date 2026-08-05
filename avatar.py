import os
import random
import threading
import time
from pathlib import Path

import requests


DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
PROJECT_ROOT = Path(__file__).resolve().parent
TERMINAL_TASK_STATUSES = {"SUCCEEDED", "FAILED", "UNKNOWN", "CANCELED"}


class AvatarServiceError(RuntimeError):
    pass


def _split_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class AliyunVideoRetalkClient:
    def __init__(self):
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        self.tts_model = os.getenv("AVATAR_TTS_MODEL", "qwen3-tts-flash").strip()
        self.tts_voice = os.getenv("AVATAR_TTS_VOICE", "Cherry").strip()
        self.tts_instructions = os.getenv(
            "AVATAR_TTS_INSTRUCTIONS",
            "语气温柔、专业、可信，语速自然，像口腔医生面对面回答患者。",
        ).strip()
        self.master_video_sources = _split_values(os.getenv(
            "AVATAR_MASTER_VIDEOS",
            "frontend/assets/doctor-speaking-long-01.mp4,frontend/assets/doctor-speaking-long-02.mp4,frontend/assets/doctor-speaking-long-03.mp4",
        ))
        self.reference_image_source = os.getenv(
            "AVATAR_REFERENCE_IMAGE", "frontend/assets/doctor-li.png"
        ).strip()
        self.timeout = float(os.getenv("AVATAR_TIMEOUT", "300"))
        self.poll_interval = max(1.0, float(os.getenv("AVATAR_POLL_INTERVAL", "3")))
        self._upload_cache = {}
        self._cache_lock = threading.Lock()
        self._render_lock = threading.Lock()

    @property
    def available_master_videos(self) -> list[str]:
        return [source for source in self.master_video_sources if self._source_exists(source)]

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.available_master_videos)

    @property
    def missing_requirements(self) -> list[str]:
        missing = []
        if not self.api_key:
            missing.append("DASHSCOPE_API_KEY")
        if not self.available_master_videos:
            missing.append("AVATAR_MASTER_VIDEOS")
        return missing

    @staticmethod
    def _is_remote(source: str) -> bool:
        return source.startswith(("http://", "https://", "oss://"))

    def _source_exists(self, source: str) -> bool:
        return self._is_remote(source) or (PROJECT_ROOT / source).is_file()

    def _headers(self, **extra) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **extra,
        }

    @staticmethod
    def _response_error(data, fallback: str) -> str:
        output = data.get("output") if isinstance(data, dict) else None
        if isinstance(output, dict):
            return output.get("message") or output.get("code") or fallback
        if isinstance(data, dict):
            return data.get("message") or data.get("code") or fallback
        return fallback

    def _json_request(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = requests.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise AvatarServiceError(f"百炼请求失败：{error}") from error
        output = data.get("output") if isinstance(data, dict) else None
        if data.get("code") or (isinstance(output, dict) and output.get("code")):
            raise AvatarServiceError(self._response_error(data, "百炼返回未知错误"))
        return data

    def _upload_local_file(self, source: str) -> str:
        file_path = (PROJECT_ROOT / source).resolve()
        if not file_path.is_file() or PROJECT_ROOT not in file_path.parents:
            raise AvatarServiceError(f"数字人素材不存在或不在项目目录内：{source}")
        cache_key = (str(file_path), file_path.stat().st_mtime_ns)
        now = time.time()
        with self._cache_lock:
            cached = self._upload_cache.get(cache_key)
            if cached and cached[1] > now:
                return cached[0]

        policy = self._json_request(
            "GET",
            f"{DASHSCOPE_BASE_URL}/uploads",
            headers=self._headers(),
            params={"action": "getPolicy", "model": "videoretalk"},
        )["data"]
        object_key = f"{policy['upload_dir']}/{file_path.name}"
        fields = [
            ("OSSAccessKeyId", (None, policy["oss_access_key_id"])),
            ("Signature", (None, policy["signature"])),
            ("policy", (None, policy["policy"])),
            ("x-oss-object-acl", (None, policy["x_oss_object_acl"])),
            ("x-oss-forbid-overwrite", (None, policy["x_oss_forbid_overwrite"])),
            ("key", (None, object_key)),
            ("success_action_status", (None, "200")),
        ]
        try:
            with file_path.open("rb") as file:
                response = requests.post(
                    policy["upload_host"],
                    files=[*fields, ("file", (file_path.name, file))],
                    timeout=60,
                )
            response.raise_for_status()
        except requests.RequestException as error:
            raise AvatarServiceError(f"上传数字人素材失败：{error}") from error

        oss_url = f"oss://{object_key}"
        with self._cache_lock:
            self._upload_cache[cache_key] = (oss_url, now + 47 * 60 * 60)
        return oss_url

    def _resolve_source(self, source: str) -> str:
        if self._is_remote(source):
            return source
        return self._upload_local_file(source)

    def synthesize_speech(self, text: str) -> str:
        input_data = {
            "text": text,
            "voice": self.tts_voice,
            "language_type": "Chinese",
        }
        if self.tts_model == "qwen3-tts-instruct-flash" and self.tts_instructions:
            input_data.update(
                {
                    "instructions": self.tts_instructions,
                    "optimize_instructions": True,
                }
            )
        data = self._json_request(
            "POST",
            f"{DASHSCOPE_BASE_URL}/services/aigc/multimodal-generation/generation",
            headers=self._headers(),
            json={"model": self.tts_model, "input": input_data},
        )
        audio_url = data.get("output", {}).get("audio", {}).get("url")
        if not audio_url:
            raise AvatarServiceError("语音合成成功但未返回音频 URL")
        return audio_url

    def submit_video_task(self, video_url: str, audio_url: str) -> str:
        input_data = {"video_url": video_url, "audio_url": audio_url}
        if self.reference_image_source and self._source_exists(self.reference_image_source):
            input_data["ref_image_url"] = self._resolve_source(self.reference_image_source)
        data = self._json_request(
            "POST",
            f"{DASHSCOPE_BASE_URL}/services/aigc/image2video/video-synthesis",
            headers=self._headers(
                **{
                    "X-DashScope-Async": "enable",
                    "X-DashScope-OssResourceResolve": "enable",
                }
            ),
            json={
                "model": "videoretalk",
                "input": input_data,
                "parameters": {"video_extension": True},
            },
        )
        task_id = data.get("output", {}).get("task_id")
        if not task_id:
            raise AvatarServiceError("VideoRetalk 未返回任务 ID")
        return task_id

    def wait_for_video(self, task_id: str) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            data = self._json_request(
                "GET",
                f"{DASHSCOPE_BASE_URL}/tasks/{task_id}",
                headers=self._headers(),
            )
            output = data.get("output", {})
            status = output.get("task_status")
            if status == "SUCCEEDED" and output.get("video_url"):
                return {
                    "video_url": output["video_url"],
                    "duration": data.get("usage", {}).get("video_duration"),
                }
            if status in TERMINAL_TASK_STATUSES:
                raise AvatarServiceError(
                    self._response_error(data, f"VideoRetalk 任务状态：{status}")
                )
            time.sleep(self.poll_interval)
        raise AvatarServiceError(f"VideoRetalk 生成超过 {self.timeout:g} 秒")

    def render(self, text: str) -> dict:
        if not self.configured:
            raise AvatarServiceError(
                f"数字人配置不完整：{', '.join(self.missing_requirements)}"
            )
        with self._render_lock:
            audio_url = self.synthesize_speech(text)
            master_url = self._resolve_source(random.choice(self.available_master_videos))
            task_id = self.submit_video_task(master_url, audio_url)
            result = self.wait_for_video(task_id)
            return {**result, "audio_url": audio_url, "task_id": task_id}
