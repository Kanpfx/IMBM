#!/usr/bin/env bash
#SBATCH -J imbm_qwen35-2b-sc2-lora
#SBATCH -o logs/%x-%j.out
#SBATCH -e logs/%x-%j.err
#SBATCH -p compute
#SBATCH -N 1
#SBATCH -t 01:00:00
#SBATCH --gres=gpu:nvidia_rtx_a6000:1

set -e

mkdir -p logs

export SC2PATH="/home/zrshan/apps/StarCraftII"

. /home/zrshan/apps/miniconda3/etc/profile.d/conda.sh
conda activate sc2

cd /home/zrshan/projects/IMBM

bash run_exp.sh