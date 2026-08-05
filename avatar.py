import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = PROJECT_ROOT / "data" / "avatar"
TERMINAL_STATUSES = {"succeeded", "failed"}


class AvatarServiceError(RuntimeError):
    pass


def split_sentences(text: str, max_chars: int = 70) -> list[str]:
    parts = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text.strip())
    sentences = []
    for part in (item.strip() for item in parts):
        while len(part) > max_chars:
            split_at = max(part.rfind(mark, 0, max_chars + 1) for mark in "，、：,")
            split_at = split_at + 1 if split_at > max_chars // 2 else max_chars
            sentences.append(part[:split_at].strip())
            part = part[split_at:].strip()
        if part:
            sentences.append(part)
    return sentences or [text.strip()]


class LocalAvatarClient:
    def __init__(self):
        self.cosyvoice_root = Path(os.getenv("COSYVOICE_ROOT", "models/CosyVoice"))
        self.cosyvoice_model = Path(os.getenv(
            "COSYVOICE_MODEL", "models/CosyVoice/pretrained_models/CosyVoice2-0.5B"
        ))
        self.cosyvoice_python = Path(os.getenv(
            "COSYVOICE_PYTHON", ".venvs/cosyvoice/bin/python"
        ))
        self.musetalk_root = Path(os.getenv("MUSETALK_ROOT", "models/MuseTalk"))
        self.musetalk_model = Path(os.getenv(
            "MUSETALK_MODEL", "models/MuseTalk/models/musetalkV15"
        ))
        self.musetalk_python = Path(os.getenv(
            "MUSETALK_PYTHON", ".venvs/musetalk/bin/python"
        ))
        self.source_video = Path(os.getenv(
            "AVATAR_SOURCE_VIDEO", "frontend/assets/doctor-speaking-long-01.mp4"
        ))
        self.prompt_wav = os.getenv(
            "AVATAR_TTS_PROMPT_WAV", "models/CosyVoice/asset/zero_shot_prompt.wav"
        ).strip()
        self.prompt_text = os.getenv(
            "AVATAR_TTS_PROMPT_TEXT", "希望你以后能够做的比我还好呦。"
        ).strip()
        self.speaker = os.getenv("AVATAR_TTS_SPEAKER", "中文女").strip()
        self.max_chars = max(20, int(os.getenv("AVATAR_SEGMENT_MAX_CHARS", "70")))
        self.batch_size = max(1, int(os.getenv("MUSETALK_BATCH_SIZE", "2")))
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avatar")
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    def _absolute(self, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def missing_requirements(self) -> list[str]:
        required = {
            "COSYVOICE_ROOT": self.cosyvoice_root,
            "COSYVOICE_MODEL": self.cosyvoice_model,
            "COSYVOICE_PYTHON": self.cosyvoice_python,
            "MUSETALK_ROOT": self.musetalk_root,
            "MUSETALK_MODEL": self.musetalk_model,
            "MUSETALK_PYTHON": self.musetalk_python,
            "AVATAR_SOURCE_VIDEO": self.source_video,
        }
        if self.prompt_wav:
            required["AVATAR_TTS_PROMPT_WAV"] = Path(self.prompt_wav)
        return [name for name, path in required.items() if not self._absolute(path).exists()]

    @property
    def configured(self) -> bool:
        return not self.missing_requirements

    def create_job(self, text: str) -> dict:
        if not self.configured:
            raise AvatarServiceError(f"本地数字人尚未安装：{', '.join(self.missing_requirements)}")
        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "status": "queued",
            "segments": [],
            "segment_count": len(split_sentences(text, self.max_chars)),
            "error": None,
            "created_at": time.time(),
        }
        with self._lock:
            self._jobs[job_id] = job
        self._executor.submit(self._render_job, job_id, text)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return json.loads(json.dumps(job))

    def _update(self, job_id: str, **values):
        with self._lock:
            self._jobs[job_id].update(values)

    def _render_job(self, job_id: str, text: str):
        job_dir = OUTPUT_ROOT / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        self._update(job_id, status="running")
        try:
            sentences = split_sentences(text, self.max_chars)
            self._synthesize_batch(sentences, job_dir)
            for index, sentence in enumerate(sentences):
                audio_path = job_dir / f"{index:03d}.wav"
                video_path = self._animate(audio_path, job_dir, index)
                segment = {
                    "index": index,
                    "text": sentence,
                    "video_url": f"/avatar-files/{job_id}/{video_path.name}",
                }
                with self._lock:
                    self._jobs[job_id]["segments"].append(segment)
            self._update(job_id, status="succeeded")
        except Exception as error:
            self._update(job_id, status="failed", error=str(error))

    def _synthesize_batch(self, sentences: list[str], output_dir: Path):
        manifest = output_dir / "sentences.json"
        manifest.write_text(json.dumps(sentences, ensure_ascii=False), encoding="utf-8")
        command = [
            str(self._absolute(self.cosyvoice_python)),
            str(PROJECT_ROOT / "scripts" / "cosyvoice_tts.py"),
            "--repo", str(self._absolute(self.cosyvoice_root)),
            "--model", str(self._absolute(self.cosyvoice_model)),
            "--manifest", str(manifest),
            "--output-dir", str(output_dir),
            "--speaker", self.speaker,
        ]
        if self.prompt_wav:
            command.extend(["--prompt-wav", str(self._absolute(Path(self.prompt_wav)))])
            command.extend(["--prompt-text", self.prompt_text])
        self._run(command, "CosyVoice")

    def _animate(self, audio_path: Path, job_dir: Path, index: int) -> Path:
        config_path = job_dir / f"musetalk-{index:03d}.yaml"
        result_dir = job_dir / f"result-{index:03d}"
        config_path.write_text(
            "task_0:\n"
            f"  video_path: {json.dumps(str(self._absolute(self.source_video)))}\n"
            f"  audio_path: {json.dumps(str(audio_path))}\n"
            "  bbox_shift: 0\n",
            encoding="utf-8",
        )
        command = [
            str(self._absolute(self.musetalk_python)), "-m", "scripts.inference",
            "--inference_config", str(config_path),
            "--result_dir", str(result_dir),
            "--unet_model_path", str(self._absolute(self.musetalk_model) / "unet.pth"),
            "--unet_config", str(self._absolute(self.musetalk_model) / "musetalk.json"),
            "--version", "v15",
            "--batch_size", str(self.batch_size),
        ]
        self._run(command, "MuseTalk", cwd=self._absolute(self.musetalk_root))
        candidates = sorted(result_dir.rglob("*.mp4"), key=lambda path: path.stat().st_mtime)
        if not candidates:
            raise AvatarServiceError("MuseTalk 未生成 MP4 文件")
        output_path = job_dir / f"{index:03d}.mp4"
        candidates[-1].replace(output_path)
        return output_path

    @staticmethod
    def _run(command: list[str], name: str, cwd: Path | None = None):
        result = subprocess.run(
            command, cwd=cwd or PROJECT_ROOT, capture_output=True, text=True, timeout=600
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-2000:]
            raise AvatarServiceError(f"{name} 执行失败：{detail}")
