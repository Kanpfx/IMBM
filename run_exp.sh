#!/usr/bin/env bash
set -euo pipefail

BASE_MODEL="/home/share/models/Qwen3.5-2B"
LORA_PATH="/home/zrshan/projects/data/checkpoints/qwen35-2b-sc2-lora-a100/checkpoint-1119"
LORA_NAME="qwen35-2b-sc2-lora"

HOST="127.0.0.1"
PORT="12001"
LOG_FILE="logs/vllm-${LORA_NAME}.log"

mkdir -p logs

vllm serve "$BASE_MODEL" \
  --served-model-name "Qwen3.5-2B-base" \
  --host "$HOST" \
  --port "$PORT" \
  --dtype bfloat16 \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.85 \
  --enable-prefix-caching \
  --enable-lora \
  --max-loras 1 \
  --max-lora-rank 32 \
  --lora-modules "${LORA_NAME}=${LORA_PATH}" \
  --trust-remote-code \
  >"$LOG_FILE" 2>&1 &

VLLM_PID=$!

cleanup() {
  kill "$VLLM_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

until curl -fsS "http://${HOST}:${PORT}/v1/models" | grep -q "$LORA_NAME"; do
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "vLLM failed to start."
    tail -n 50 "$LOG_FILE"
    exit 1
  fi
  sleep 2
done

echo "vLLM ready."

export IM_MODEL_NAME="qwen35-2b-sc2-lora"
export IM_BASE_URL="http://127.0.0.1:12001/v1"
export IM_API_KEY="EMPTY"

python main.py \
  --player_name qwen35_2b_sc2_lora_PylonAIE_v4 \
  --map_name PylonAIE_v4 \
  --difficulty VeryHard \
  --ai_build RandomBuild \
  --own_race Terran \
  --enemy_race Terran