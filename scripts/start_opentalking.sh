#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENTALKING_ROOT:-${PWD}/vendor/opentalking}"
MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-${PWD}/models/opentalking}"
PROJECT_ROOT="$(cd "$(dirname "${ROOT}")/.." && pwd)"
OPEN_TALKING_BIN="${ROOT}/.venv/bin/opentalking-unified"
if [[ ! -x "${OPEN_TALKING_BIN}" ]] || ! "${ROOT}/.venv/bin/python" -c 'import opentalking' >/dev/null 2>&1; then
  echo "OpenTalking 环境未就绪，开始安装依赖和模型..."
  bash "${PROJECT_ROOT}/scripts/install_opentalking.sh"
fi
cd "${ROOT}"
PROJECT_ROOT="$(cd "${ROOT}/../.." && pwd)"
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.env"
  set +a
fi
export OPENTALKING_MODEL_ROOT="${MODEL_ROOT}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${MODEL_ROOT}/quicktalk"
export OPENTALKING_TORCH_DEVICE="${OPENTALKING_TORCH_DEVICE:-cuda:0}"
export OPENTALKING_STT_DEFAULT_PROVIDER="${OPENTALKING_STT_DEFAULT_PROVIDER:-sensevoice}"
export OPENTALKING_STT_ENABLED_PROVIDERS="${OPENTALKING_STT_ENABLED_PROVIDERS:-sensevoice}"
export OPENTALKING_STT_SENSEVOICE_MODEL_DIR="${MODEL_ROOT}/local-audio/iic__SenseVoiceSmall"
export OPENTALKING_STT_SENSEVOICE_DEVICE="${OPENTALKING_STT_SENSEVOICE_DEVICE:-cpu}"
export OPENTALKING_LLM_PROVIDER="openai_compatible"
export OPENTALKING_LLM_BASE_URL="${LLM_API_URL%/chat/completions}"
export OPENTALKING_LLM_API_KEY="${LLM_API_KEY:-}"
export OPENTALKING_LLM_MODEL="${LLM_MODEL:-moonshot-v1-auto}"
exec bash scripts/start_unified.sh \
  --backend local --model quicktalk --api-port 8210 --web-port 5280
