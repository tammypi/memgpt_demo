import argparse
import json
import os
import sys
from pathlib import Path

_model = None


def synthesize(repo, model_path, text, output, speaker="中文女", prompt_wav="", prompt_text=""):
    global _model
    sys.path.insert(0, repo)
    sys.path.insert(0, str(Path(repo) / "third_party" / "Matcha-TTS"))
    cuda_devices = os.environ.pop("CUDA_VISIBLE_DEVICES", None)
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import CosyVoice2

    if _model is None:
        _model = CosyVoice2(
            model_path, load_jit=False, load_trt=False, load_vllm=False, fp16=False
        )
        if cuda_devices is None:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = cuda_devices
    if prompt_wav:
        chunks = _model.inference_zero_shot(text, prompt_text, prompt_wav, stream=False)
    else:
        speakers = _model.list_available_spks()
        selected = speaker if speaker in speakers else speakers[0]
        chunks = _model.inference_sft(text, selected, stream=False)
    audio = torch.cat([chunk["tts_speech"].cpu() for chunk in chunks], dim=1)
    torchaudio.save(output, audio, _model.sample_rate)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--text")
    parser.add_argument("--output")
    parser.add_argument("--manifest")
    parser.add_argument("--output-dir")
    parser.add_argument("--speaker", default="中文女")
    parser.add_argument("--prompt-wav", default="")
    parser.add_argument("--prompt-text", default="")
    args = parser.parse_args()

    if args.manifest:
        texts = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        output_dir = Path(args.output_dir)
        for index, text in enumerate(texts):
            synthesize(
                args.repo, args.model, text, str(output_dir / f"{index:03d}.wav"),
                args.speaker, args.prompt_wav, args.prompt_text,
            )
    else:
        if not args.text or not args.output:
            parser.error("--text and --output are required without --manifest")
        synthesize(
            args.repo, args.model, args.text, args.output, args.speaker,
            args.prompt_wav, args.prompt_text,
        )


if __name__ == "__main__":
    main()
