#!/usr/bin/env python3
import argparse
import base64
import mimetypes
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = PROJECT_ROOT / "frontend" / "assets"
SOURCE_IMAGE = ASSET_DIR / "doctor-li.png"
API_BASE = "https://dashscope.aliyuncs.com/api/v1"

STATE_SPECS = {
    "idle": (
        "固定镜头，保持人物身份、五官、发型、白大褂、牙科诊室背景完全一致。"
        "画面从始至终只能出现李医生一人，前景和背景都不能出现其他人或人体局部。"
        "医生保持原图中的温和微笑和正面视线，自然呼吸，偶尔轻柔眨眼，头肩只有极小幅度的自然微动。"
        "不说话，不做明显口型，不转头，不改变构图和光线。"
    ),
    "listening": (
        "固定镜头，保持人物身份、五官、发型、白大褂、牙科诊室背景完全一致。"
        "这是一段李医生独自拍摄的职业形象短片，画面从始至终只有李医生一人。"
        "镜头内外都没有患者、交谈对象或其他人，前景和背景没有人体、头发、手部或人物轮廓。"
        "医生独自注视固定镜头，保持原图中的温和表情，自然眨眼，并做一次幅度很小的点头。"
        "不说话，不做明显口型，不转头，不改变构图和光线。"
    ),
    "thinking": (
        "固定镜头，保持人物身份、五官、发型、白大褂、牙科诊室背景完全一致。"
        "画面从始至终只能出现李医生一人，前景和背景都不能出现其他人或人体局部。"
        "医生正在认真思考，视线短暂轻微向下移动后自然回到镜头，轻柔眨眼，自然呼吸。"
        "不说话，不做明显口型，不皱眉，不摇头，不改变构图和光线。"
    ),
}

MASTER_SCRIPTS = [
    "你好，我是李医生。请慢慢告诉我哪里不舒服，我会认真听完，再给你清楚、稳妥的建议。",
    "好的，我了解你的情况了。我们可以先从症状出现的时间和具体位置开始，一步一步判断。",
    "不用着急，我会结合你刚才描述的感受认真分析，也会提醒你哪些情况需要尽快到医院检查。",
]

NEGATIVE_PROMPT = (
    "身份变化，五官变化，脸型变化，发型变化，衣服变化，背景变化，镜头移动，明显转头，"
    "大幅摇头，夸张表情，说话口型，嘴部抽动，牙齿变形，画面抖动，闪烁，重影，"
    "患者，患者背影，第二个人，额外人物，其他人的头部，其他人的手，人体局部，人物轮廓"
)

COMPOSITE_ORDERS = [
    (1, 2, 3),
    (2, 3, 1),
    (3, 1, 2),
]


class GenerationError(RuntimeError):
    pass


class AssetGenerator:
    def __init__(self, api_key: str, master_resolution: str):
        self.api_key = api_key
        self.master_resolution = master_resolution

    def headers(self, **extra):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **extra,
        }

    @staticmethod
    def error_message(data, fallback):
        output = data.get("output", {}) if isinstance(data, dict) else {}
        return (
            output.get("message")
            or output.get("code")
            or data.get("message")
            or data.get("code")
            or fallback
        )

    def json_request(self, method, url, **kwargs):
        try:
            response = requests.request(method, url, timeout=60, **kwargs)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise GenerationError(str(error)) from error
        output = data.get("output") if isinstance(data, dict) else None
        if data.get("code") or (isinstance(output, dict) and output.get("code")):
            raise GenerationError(self.error_message(data, "百炼返回未知错误"))
        return data

    def upload_file(self, file_path: Path, model: str):
        policy = self.json_request(
            "GET",
            f"{API_BASE}/uploads",
            headers=self.headers(),
            params={"action": "getPolicy", "model": model},
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
                    timeout=120,
                )
            response.raise_for_status()
        except requests.RequestException as error:
            raise GenerationError(f"上传 {file_path.name} 失败：{error}") from error
        return f"oss://{object_key}"

    def image_data_url(self):
        mime_type = mimetypes.guess_type(SOURCE_IMAGE.name)[0] or "image/png"
        encoded = base64.b64encode(SOURCE_IMAGE.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def synthesize_speech(self, text):
        data = self.json_request(
            "POST",
            f"{API_BASE}/services/aigc/multimodal-generation/generation",
            headers=self.headers(),
            json={
                "model": "qwen3-tts-flash",
                "input": {"text": text, "voice": "Cherry", "language_type": "Chinese"},
            },
        )
        audio_url = data.get("output", {}).get("audio", {}).get("url")
        if not audio_url:
            raise GenerationError("TTS 未返回音频 URL")
        return audio_url

    def submit_task(self, endpoint, payload, resolve_oss=False):
        extra_headers = {"X-DashScope-Async": "enable"}
        if resolve_oss:
            extra_headers["X-DashScope-OssResourceResolve"] = "enable"
        data = self.json_request(
            "POST",
            f"{API_BASE}{endpoint}",
            headers=self.headers(**extra_headers),
            json=payload,
        )
        task_id = data.get("output", {}).get("task_id")
        if not task_id:
            raise GenerationError("任务提交成功但未返回 task_id")
        return task_id

    def wait_task(self, task_id, interval=15):
        while True:
            data = self.json_request(
                "GET", f"{API_BASE}/tasks/{task_id}", headers=self.headers()
            )
            output = data.get("output", {})
            status = output.get("task_status")
            if status == "SUCCEEDED":
                video_url = output.get("video_url") or output.get("results", {}).get(
                    "video_url"
                )
                if not video_url:
                    raise GenerationError("任务成功但未返回视频 URL")
                return video_url, data.get("usage", {})
            if status in {"FAILED", "UNKNOWN", "CANCELED"}:
                raise GenerationError(self.error_message(data, f"任务状态：{status}"))
            print(f"  task={task_id[:8]} status={status}", flush=True)
            time.sleep(interval)

    @staticmethod
    def download(url, destination):
        try:
            with requests.get(url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with destination.open("wb") as file:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            file.write(chunk)
        except requests.RequestException as error:
            raise GenerationError(f"下载 {destination.name} 失败：{error}") from error

    @staticmethod
    def normalize_master_video(video_path):
        """VideoRetalk requires both video edges to be at least 640 pixels."""
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        width, height = (int(value) for value in probe.stdout.strip().split("x"))
        if min(width, height) >= 640:
            return
        normalized_path = video_path.with_name(f"{video_path.stem}-normalized.mp4")
        if width <= height:
            scale = "640:-2"
        else:
            scale = "-2:640"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(video_path),
                "-vf",
                f"scale={scale},format=yuv420p",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-c:a",
                "aac",
                str(normalized_path),
            ],
            check=True,
        )
        normalized_path.replace(video_path)

    def generate_state(self, name, prompt):
        print(f"生成状态视频：{name}", flush=True)
        task_id = self.submit_task(
            "/services/aigc/video-generation/video-synthesis",
            {
                "model": "wan2.6-i2v-flash",
                "input": {
                    "prompt": prompt,
                    "negative_prompt": NEGATIVE_PROMPT,
                    "img_url": self.image_data_url(),
                },
                "parameters": {
                    "resolution": "720P",
                    "duration": 10,
                    "prompt_extend": False,
                    "audio": False,
                    "watermark": False,
                },
            },
        )
        video_url, usage = self.wait_task(task_id)
        destination = ASSET_DIR / f"doctor-{name}.mp4"
        self.download(video_url, destination)
        print(f"  已保存 {destination.relative_to(PROJECT_ROOT)} usage={usage}", flush=True)

    def generate_masters(self):
        image_url = self.upload_file(SOURCE_IMAGE, "wan2.2-s2v")
        for index, script in enumerate(MASTER_SCRIPTS, start=1):
            print(f"生成说话母版：{index}/3", flush=True)
            audio_url = self.synthesize_speech(script)
            task_id = self.submit_task(
                "/services/aigc/image2video/video-synthesis/",
                {
                    "model": "wan2.2-s2v",
                    "input": {"image_url": image_url, "audio_url": audio_url},
                    "parameters": {"resolution": self.master_resolution},
                },
                resolve_oss=True,
            )
            video_url, usage = self.wait_task(task_id)
            destination = ASSET_DIR / f"doctor-speaking-{index:02d}.mp4"
            self.download(video_url, destination)
            self.normalize_master_video(destination)
            print(f"  已保存 {destination.relative_to(PROJECT_ROOT)} usage={usage}", flush=True)


def build_composite_masters():
    for output_index, order in enumerate(COMPOSITE_ORDERS, start=1):
        inputs = [ASSET_DIR / f"doctor-speaking-{index:02d}.mp4" for index in order]
        missing = [path for path in inputs if not path.is_file()]
        if missing:
            raise GenerationError(f"缺少说话母版：{', '.join(str(path) for path in missing)}")
        output = ASSET_DIR / f"doctor-speaking-long-{output_index:02d}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(inputs[0]),
                "-i",
                str(inputs[1]),
                "-i",
                str(inputs[2]),
                "-filter_complex",
                (
                    "[0:v][1:v][2:v]concat=n=3:v=1:a=0,"
                    "format=yuv420p[out]"
                ),
                "-map",
                "[out]",
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                str(output),
            ],
            check=True,
        )
        print(f"已合成长母版：{output.relative_to(PROJECT_ROOT)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="生成李医生数字人状态视频和 VideoRetalk 母版")
    parser.add_argument("--states", action="store_true", help="生成待机、聆听、思考视频")
    parser.add_argument(
        "--state",
        action="append",
        choices=sorted(STATE_SPECS),
        help="只生成指定状态，可重复传入",
    )
    parser.add_argument("--masters", action="store_true", help="生成三段说话母版")
    parser.add_argument(
        "--compose-masters", action="store_true", help="将现有三段母版合成为长母版"
    )
    parser.add_argument(
        "--master-resolution", choices=["480P", "720P"], default="480P"
    )
    parser.add_argument(
        "--confirm-paid-generation",
        action="store_true",
        help="确认调用会产生百炼视频生成费用",
    )
    args = parser.parse_args()
    if args.state:
        args.states = True
    if not args.states and not args.masters and not args.compose_masters:
        args.states = args.masters = True

    selected_states = args.state or list(STATE_SPECS)
    print("计划：")
    if args.states:
        print(
            f"- {len(selected_states)} 段 10 秒 720P 无声状态视频"
            f"（wan2.6-i2v-flash）：{', '.join(selected_states)}"
        )
    if args.masters:
        print("- 3 段由 TTS 时长决定的说话母版（wan2.2-s2v）")
        print(f"- 说话母版分辨率：{args.master_resolution}")
    if args.compose_masters or args.masters:
        print("- 将三段说话素材无重叠拼接为 3 段约 23 秒长母版")
    if (args.states or args.masters) and not args.confirm_paid_generation:
        print("未提交任务。确认费用后追加 --confirm-paid-generation。")
        return 0

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if (args.states or args.masters) and not api_key:
        print("缺少 DASHSCOPE_API_KEY", file=sys.stderr)
        return 2
    if not SOURCE_IMAGE.is_file():
        print(f"缺少参考图：{SOURCE_IMAGE}", file=sys.stderr)
        return 2

    generator = AssetGenerator(api_key, args.master_resolution)
    if args.states:
        for name in selected_states:
            generator.generate_state(name, STATE_SPECS[name])
    if args.masters:
        generator.generate_masters()
    if args.masters or args.compose_masters:
        build_composite_masters()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
