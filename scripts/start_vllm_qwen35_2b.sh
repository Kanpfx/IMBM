#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

SESSION="${TMUX_SESSION:-imbm_exp}"
MODEL_PATH="${VLLM_MODEL_PATH:-${MODEL_PATH:-/root/autodl-tmp/models/Qwen3.5-2B}}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-${IM_MODEL_NAME:-Qwen3.5-2B}}"
HOST="${HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-${PORT:-12001}}"
MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-${MAX_NUM_SEQS:-8}}"
GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-${GPU_MEMORY_UTILIZATION:-0.90}}"
DTYPE="${DTYPE:-auto}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-${MAX_MODEL_LEN:-8192}}"
VLLM_API_KEY="${VLLM_API_KEY:-}"
READY_URL="http://127.0.0.1:${PORT}/v1/models"
DONE_FILE="/tmp/${SESSION}.done"
FAIL_FILE="/tmp/${SESSION}.fail"

rm -f "${DONE_FILE}" "${FAIL_FILE}"
tmux kill-session -t "${SESSION}" 2>/dev/null || true

VLLM_CMD="vllm serve '${MODEL_PATH}' --served-model-name '${SERVED_MODEL_NAME}' --host '${HOST}' --port '${PORT}' --max-num-seqs '${MAX_NUM_SEQS}' --gpu-memory-utilization '${GPU_MEMORY_UTILIZATION}' --dtype '${DTYPE}' --max-model-len '${MAX_MODEL_LEN}'"
if [[ -n "${VLLM_API_KEY}" ]]; then
  VLLM_CMD="${VLLM_CMD} --api-key '${VLLM_API_KEY}'"
fi
if ! command -v vllm >/dev/null 2>&1; then
  VLLM_CMD="python -m vllm.entrypoints.openai.api_server --model '${MODEL_PATH}' --served-model-name '${SERVED_MODEL_NAME}' --host '${HOST}' --port '${PORT}' --max-num-seqs '${MAX_NUM_SEQS}' --gpu-memory-utilization '${GPU_MEMORY_UTILIZATION}' --dtype '${DTYPE}' --max-model-len '${MAX_MODEL_LEN}'"
  if [[ -n "${VLLM_API_KEY}" ]]; then
    VLLM_CMD="${VLLM_CMD} --api-key '${VLLM_API_KEY}'"
  fi
fi

tmux new-session -d -s "${SESSION}" -n vllm "${VLLM_CMD}"

echo "Waiting for vLLM at ${READY_URL}"
until curl -fsS "${READY_URL}" >/dev/null 2>&1; do
  sleep 2
done

RUN_CMD="python main.py --map_name Flat48 --difficulty Harder --ai_build RandomBuild --own_race Terran --enemy_race Terran -bm && touch '${DONE_FILE}' || touch '${FAIL_FILE}'"
tmux new-window -t "${SESSION}" -n main "${RUN_CMD}"

echo "Experiment started in tmux session: ${SESSION}"
echo "Attach with: tmux attach -t ${SESSION}"

while [[ ! -f "${DONE_FILE}" && ! -f "${FAIL_FILE}" ]]; do
  sleep 5
done

if [[ -f "${FAIL_FILE}" ]]; then
  echo "Experiment failed. Keeping machine on for inspection."
  exit 1
fi

echo "Experiment finished. Waiting 30 seconds before shutdown."
sleep 30
shutdown -h now
