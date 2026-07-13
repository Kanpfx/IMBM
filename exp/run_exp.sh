#!/usr/bin/env bash
set -e

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

echo "Waiting for vLLM..."
until curl -fs "http://127.0.0.1:12001/v1/models" >/dev/null; do
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "vLLM failed to start."
    exit 1
  fi
  sleep 2
done

echo "vLLM is ready. Starting experiment..."
python main.py \
  --player_name qwen3_8b_flat48 \
  --map_name Flat48 \
  --difficulty VeryHard \
  --ai_build RandomBuild \
  --own_race Terran \
  --enemy_race Terran \
  --bm
