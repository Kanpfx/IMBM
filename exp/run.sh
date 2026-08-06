#!/usr/bin/env bash
#SBATCH -J imbm_qwen3
#SBATCH -o logs/%x-%j.out
#SBATCH -e logs/%x-%j.err
#SBATCH -p compute
#SBATCH -N 1
#SBATCH -t 01:00:00
#SBATCH --gres=gpu:tesla_v100s-pcie-32gb:1

set -e

mkdir -p logs

export SC2PATH="/home/zrshan/apps/StarCraftII"

. /home/zrshan/apps/miniconda3/etc/profile.d/conda.sh
conda activate sc2

cd /home/zrshan/projects/IMBM
bash exp/run_exp.sh
