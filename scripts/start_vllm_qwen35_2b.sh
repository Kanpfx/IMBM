#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${MODEL_PATH:-/root/autodl-tmp/models/Qwen3.5-2B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-Qwen3.5-2B}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-12001}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-8}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
DTYPE="${DTYPE:-auto}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
VLLM_API_KEY="${VLLM_API_KEY:-}"

common_args=(
  --served-model-name "${SERVED_MODEL_NAME}"
  --host "${HOST}"
  --port "${PORT}"
  --max-num-seqs "${MAX_NUM_SEQS}"
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}"
  --dtype "${DTYPE}"
  --max-model-len "${MAX_MODEL_LEN}"
)

if [[ -n "${VLLM_API_KEY}" ]]; then
  common_args+=(--api-key "${VLLM_API_KEY}")
fi

echo "Starting vLLM OpenAI-compatible server"
echo "  model path: ${MODEL_PATH}"
echo "  served model name: ${SERVED_MODEL_NAME}"
echo "  endpoint: http://${HOST}:${PORT}/v1"
echo "  max concurrent sequences: ${MAX_NUM_SEQS}"

if command -v vllm >/dev/null 2>&1; then
  exec vllm serve "${MODEL_PATH}" "${common_args[@]}"
fi

exec python -m vllm.entrypoints.openai.api_server \
  --model "${MODEL_PATH}" \
  "${common_args[@]}"
