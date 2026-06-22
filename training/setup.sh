#!/bin/bash
# GPU 机器环境安装。运行: bash setup.sh
set -e

ENV_NAME="machining-llm"
echo "🔧 创建 conda 环境 $ENV_NAME (python 3.10)..."
conda create -n "$ENV_NAME" python=3.10 -y

# 激活（脚本内激活需 source conda）
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

echo "🔧 安装 PyTorch (示例 cu121，按本机 CUDA 版本调整 index-url)..."
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

echo "🔧 安装微调工具栈..."
pip install "transformers>=4.45" datasets accelerate peft bitsandbytes
pip install llamafactory

echo ""
echo "✅ 完成。后续:"
echo "   conda activate $ENV_NAME"
echo "   # 确认 GPU: python -c 'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))'"
echo "   llamafactory-cli train train_config.yaml"
