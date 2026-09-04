#!/usr/bin/env bash
set -e

export LLM_MODEL="Qwen3-8B"
export LLM_BASE_URL="http://127.0.0.1:12001/v1"
export LLM_API_KEY="local-vllm-model"

vllm serve /home/share/models/Qwen3-8B \
  --served-model-name Qwen3-8B \
  --host 127.0.0.1 \
  --port 12001 \
  --max-model-len 10240 \
  --gpu-memory-utilization 0.80 \
  --enable-prefix-caching \
  --trust-remote-code &

VLLM_PID=$!

cleanup() {
  kill "$VLLM_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Waiting 5s for vLLM startup..."
sleep 5
echo "Checking vLLM readiness..."
until curl -fs http://127.0.0.1:12001/v1/models >/dev/null; do
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "vLLM failed to start."
    exit 1
  fi
  sleep 2
done

echo "vLLM is ready. Starting experiment..."
python run.py \
  --player_name qwen3_8b_PylonAIE_v4 \
  --map_name PylonAIE_v4 \
  --difficulty VeryHard \
  --build_mode RandomBuild \
  --tactic BattleCruiserRush \
  --own_race Terran \
  --enemy_race Terran
