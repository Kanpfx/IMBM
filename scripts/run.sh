#!/usr/bin/env bash
#SBATCH -J im_qwen3
#SBATCH -o logs/%x-%j.out
#SBATCH -e logs/%x-%j.err
#SBATCH -p compute
#SBATCH -N 1
#SBATCH -t 01:00:00
#SBATCH --gres=gpu:a100-pcie-40gb:1

set -e

mkdir -p logs

export SC2PATH="/home/zrshan/apps/StarCraftII"

. /home/zrshan/apps/miniconda3/etc/profile.d/conda.sh
conda activate why

cd /home/zrshan/projects/why_ares
bash scripts/run_exp.sh
