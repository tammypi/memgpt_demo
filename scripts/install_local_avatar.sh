#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="${ROOT_DIR}/models"

mkdir -p "${MODEL_DIR}"
python -m pip install --upgrade pip setuptools wheel modelscope huggingface_hub

if [[ ! -d "${MODEL_DIR}/CosyVoice/.git" ]]; then
  git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git "${MODEL_DIR}/CosyVoice"
else
  git -C "${MODEL_DIR}/CosyVoice" submodule update --init --recursive
fi
python -m venv "${ROOT_DIR}/.venvs/cosyvoice"
"${ROOT_DIR}/.venvs/cosyvoice/bin/python" -m pip install --upgrade pip setuptools wheel
"${ROOT_DIR}/.venvs/cosyvoice/bin/python" -m pip install \
  -r "${MODEL_DIR}/CosyVoice/requirements.txt"
modelscope download --model iic/CosyVoice2-0.5B \
  --local_dir "${MODEL_DIR}/CosyVoice/pretrained_models/CosyVoice2-0.5B"

if [[ ! -d "${MODEL_DIR}/MuseTalk/.git" ]]; then
  git clone https://github.com/TMElyralab/MuseTalk.git "${MODEL_DIR}/MuseTalk"
fi
python -m venv "${ROOT_DIR}/.venvs/musetalk"
"${ROOT_DIR}/.venvs/musetalk/bin/python" -m pip install --upgrade pip setuptools wheel
"${ROOT_DIR}/.venvs/musetalk/bin/python" -m pip install \
  -r "${MODEL_DIR}/MuseTalk/requirements.txt"
huggingface-cli download TMElyralab/MuseTalk \
  --local-dir "${MODEL_DIR}/MuseTalk/models"

echo "本地数字人模型已安装。请重启后端。"
