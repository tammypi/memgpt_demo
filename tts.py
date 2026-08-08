"""主后端语音合成适配器。

TTS 在 OpenTalking 之外执行，输出 16 kHz、单声道、16-bit PCM WAV。
"""
import io
import os
import struct
import wave

import httpx


class TTSError(RuntimeError):
    pass


def _pcm_wav(data: bytes) -> bytes:
    try:
        with wave.open(io.BytesIO(data), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            pcm = source.readframes(source.getnframes())
    except (wave.Error, EOFError):
        channels, width, rate, pcm = 1, 2, 16000, data
    if width not in {1, 2, 3, 4} or channels < 1 or rate < 1:
        raise TTSError("TTS 返回了不支持的 PCM WAV 格式")
    sample_count = len(pcm) // width
    samples = []
    for offset in range(0, sample_count * width, width):
        chunk = pcm[offset:offset + width]
        if width == 1:
            sample = (chunk[0] - 128) << 8
        else:
            sample = int.from_bytes(chunk, "little", signed=True) >> (8 * (width - 2))
        samples.append(sample)
    mono = [
        sum(samples[index:index + channels]) // channels
        for index in range(0, len(samples) - channels + 1, channels)
    ]
    if rate != 16000 and mono:
        output_frames = max(1, round(len(mono) * 16000 / rate))
        resampled = []
        for index in range(output_frames):
            position = index * rate / 16000
            left = min(int(position), len(mono) - 1)
            right = min(left + 1, len(mono) - 1)
            fraction = position - left
            resampled.append(round(mono[left] + (mono[right] - mono[left]) * fraction))
        mono = resampled
    pcm = struct.pack(f"<{len(mono)}h", *mono) if mono else b""
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(pcm)
    return output.getvalue()


class TTSClient:
    def __init__(self, opentalking_url: str) -> None:
        self.url = f"{opentalking_url.rstrip('/')}/tts/preview"
        self.model = ""
        self.voice = "zh-CN-XiaoxiaoNeural"

    async def synthesize(self, text: str) -> bytes:
        if not self.url:
            raise TTSError("OpenTalking TTS 地址无效，无法生成数字人音频")
        payload = {"text": text, "voice": self.voice}
        if self.model:
            payload["tts_model"] = self.model
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(self.url, json=payload)
        if response.is_error:
            raise TTSError(response.text)
        if not response.content:
            raise TTSError("TTS 未返回音频")
        return _pcm_wav(response.content)
