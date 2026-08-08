#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="${ROOT_DIR}/models"
VENV_DIR="${ROOT_DIR}/.venvs"
PYPI_INDEX_URL="${PYPI_INDEX_URL:-https://mirrors.huaweicloud.com/repository/pypi/simple/}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-${PYPI_INDEX_URL}}"

mkdir -p "${MODEL_DIR}" "${VENV_DIR}"
python -m pip install --index-url "${PYPI_INDEX_URL}" \
  --upgrade pip setuptools wheel modelscope huggingface_hub

# Use the HF mirror by default; callers can override it with HF_ENDPOINT.
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

ensure_venv() {
  local name="$1"
  local path="${VENV_DIR}/${name}"
  # A mounted venv can contain an interpreter symlink from a different image.
  if [[ ! -x "${path}/bin/python" ]] || ! "${path}/bin/python" -c 'import sys' >/dev/null 2>&1; then
    python -m venv --clear "${path}"
  fi
}

if [[ ! -d "${MODEL_DIR}/CosyVoice/.git" ]]; then
  git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git "${MODEL_DIR}/CosyVoice"
else
  git -C "${MODEL_DIR}/CosyVoice" submodule update --init --recursive
fi
ensure_venv cosyvoice
"${VENV_DIR}/cosyvoice/bin/python" -m pip install \
  --index-url "${PYPI_INDEX_URL}" --upgrade pip "setuptools<81" wheel
"${VENV_DIR}/cosyvoice/bin/python" -m pip install \
  --index-url "${PYPI_INDEX_URL}" --no-build-isolation openai-whisper==20231117
COSYVOICE_REQUIREMENTS="$(mktemp)"
trap 'rm -f "${COSYVOICE_REQUIREMENTS}"' EXIT
sed '/^[[:space:]]*tensorrt-cu12\(-bindings\|-libs\)\?==/d' \
  "${MODEL_DIR}/CosyVoice/requirements.txt" > "${COSYVOICE_REQUIREMENTS}"
"${VENV_DIR}/cosyvoice/bin/python" -m pip install \
  --index-url "${PYPI_INDEX_URL}" -r "${COSYVOICE_REQUIREMENTS}"
modelscope download --model iic/CosyVoice2-0.5B \
  --local_dir "${MODEL_DIR}/CosyVoice/pretrained_models/CosyVoice2-0.5B"

if [[ ! -d "${MODEL_DIR}/MuseTalk/.git" ]]; then
  git clone https://github.com/TMElyralab/MuseTalk.git "${MODEL_DIR}/MuseTalk"
fi
ensure_venv musetalk
"${VENV_DIR}/musetalk/bin/python" -m pip install \
  --index-url "${PYPI_INDEX_URL}" --upgrade pip "setuptools<81" wheel
"${VENV_DIR}/musetalk/bin/python" -m pip install \
  torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 \
  --index-url "${PYTORCH_INDEX_URL}"
"${VENV_DIR}/musetalk/bin/python" -m pip install \
  --index-url "${PYPI_INDEX_URL}" -r "${MODEL_DIR}/MuseTalk/requirements.txt"
"${VENV_DIR}/musetalk/bin/python" -m pip install \
  --index-url "${PYPI_INDEX_URL}" "mmengine" \
  --find-links https://download.openmmlab.com/mmcv/dist/cu117/torch2.0/index.html \
  "mmcv==2.0.1"
"${VENV_DIR}/musetalk/bin/python" -m pip install \
  --index-url "${PYPI_INDEX_URL}" --no-build-isolation chumpy
"${VENV_DIR}/musetalk/bin/python" -m pip install \
  --index-url "${PYPI_INDEX_URL}" "mmdet==3.1.0" "mmpose==1.1.0"
hf download TMElyralab/MuseTalk \
  --local-dir "${MODEL_DIR}/MuseTalk/models"
hf download yzd-v/DWPose \
  --local-dir "${MODEL_DIR}/MuseTalk/models/dwpose" \
  --include dw-ll_ucoco_384.pth
hf download stabilityai/sd-vae-ft-mse \
  --local-dir "${MODEL_DIR}/MuseTalk/models/sd-vae" \
  --include diffusion_pytorch_model.bin
curl -L https://hf-mirror.com/stabilityai/sd-vae-ft-mse/resolve/main/config.json \
  -o "${MODEL_DIR}/MuseTalk/models/sd-vae/config.json"
hf download openai/whisper-tiny \
  --local-dir "${MODEL_DIR}/MuseTalk/models/whisper" \
  --include pytorch_model.bin preprocessor_config.json
curl -L https://hf-mirror.com/openai/whisper-tiny/resolve/main/config.json \
  -o "${MODEL_DIR}/MuseTalk/models/whisper/config.json"
mkdir -p "${MODEL_DIR}/MuseTalk/models/face-parse-bisent"
"${VENV_DIR}/musetalk/bin/python" -m gdown \
  154JgKpzCPW82qINcVieuPH3fZ2e0P812 \
  -O "${MODEL_DIR}/MuseTalk/models/face-parse-bisent/79999_iter.pth"
curl -L https://download.pytorch.org/models/resnet18-5c106cde.pth \
  -o "${MODEL_DIR}/MuseTalk/models/face-parse-bisent/resnet18-5c106cde.pth"

echo "本地数字人模型已安装。请重启后端。"
