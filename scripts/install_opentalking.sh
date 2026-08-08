#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENTALKING_ROOT="${OPENTALKING_ROOT:-${ROOT_DIR}/vendor/opentalking}"
MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-${ROOT_DIR}/models/opentalking}"
PYPI_INDEX_URL="${PYPI_INDEX_URL:-https://mirrors.huaweicloud.com/repository/pypi/simple/}"
OPENTALKING_PYTHON="${OPENTALKING_PYTHON:-3.11}"
unset VIRTUAL_ENV
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

if [[ ! -f "${OPENTALKING_ROOT}/pyproject.toml" ]]; then
  mkdir -p "$(dirname "${OPENTALKING_ROOT}")"
  git clone --depth 1 https://github.com/datascale-ai/opentalking.git "${OPENTALKING_ROOT}"
fi

if ! command -v uv >/dev/null 2>&1; then
  python -m pip install --index-url "${PYPI_INDEX_URL}" uv
fi

cd "${OPENTALKING_ROOT}"
uv python install "${OPENTALKING_PYTHON}"
uv sync --extra dev --extra models --extra quicktalk-cuda --python "${OPENTALKING_PYTHON}" \
  --index-url "${PYPI_INDEX_URL}"
uv sync --extra dev --extra models --extra local-audio --python "${OPENTALKING_PYTHON}" \
  --index-url "${PYPI_INDEX_URL}"

# insightface requires the native onnxruntime package. A partial install can
# leave only its namespace directory, which makes QuickTalk fail at startup.
if ! .venv/bin/python -c 'import onnxruntime; assert hasattr(onnxruntime, "InferenceSession")' >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python --reinstall "onnxruntime==1.28.0" \
    --index-url "${PYPI_INDEX_URL}"
fi

export OPENTALKING_MODEL_ROOT="${MODEL_ROOT}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${MODEL_ROOT}/quicktalk"
mkdir -p "${OPENTALKING_QUICKTALK_ASSET_ROOT}/checkpoints"

if [[ ! -f "${OPENTALKING_QUICKTALK_ASSET_ROOT}/checkpoints/quicktalk.pth" ]]; then
  QUICKTALK_HF_ENDPOINT="${QUICKTALK_HF_ENDPOINT:-https://huggingface.co}" \
  HF_ENDPOINT="${QUICKTALK_HF_ENDPOINT}" HF_HUB_DISABLE_XET=1 hf download datascale-ai/quicktalk \
    --local-dir "${OPENTALKING_QUICKTALK_ASSET_ROOT}/checkpoints"
fi

for required in \
  "${OPENTALKING_QUICKTALK_ASSET_ROOT}/checkpoints/quicktalk.pth" \
  "${OPENTALKING_QUICKTALK_ASSET_ROOT}/checkpoints/repair.npy" \
  "${OPENTALKING_QUICKTALK_ASSET_ROOT}/checkpoints/chinese-hubert-large/pytorch_model.bin" \
  "${OPENTALKING_QUICKTALK_ASSET_ROOT}/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx"; do
  [[ -e "${required}" ]] || { echo "Missing QuickTalk asset: ${required}" >&2; exit 1; }
done

SENSEVOICE_ROOT="${MODEL_ROOT}/local-audio"
if [[ ! -f "${SENSEVOICE_ROOT}/iic__SenseVoiceSmall/model.pt" ]]; then
  "${OPENTALKING_ROOT}/.venv/bin/python" \
    "${OPENTALKING_ROOT}/scripts/download_local_audio_models.py" \
    --root "${SENSEVOICE_ROOT}" --model sensevoice-small
fi

echo "OpenTalking QuickTalk 安装完成。启动命令："
echo "cd ${OPENTALKING_ROOT}"
echo "OPENTALKING_MODEL_ROOT=${MODEL_ROOT} bash scripts/start_unified.sh --backend local --model quicktalk"
