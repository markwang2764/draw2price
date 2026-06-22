# 机加工小模型微调脚手架（QLoRA / Qwen2.5-7B）

> 在**带 NVIDIA GPU 的机器**上对本平台做纯文本 LoRA 微调，训好后用 OpenAI 兼容服务挂回平台。
> 规划见 `../docs/本地训练待办.md`；本目录是可直接执行的脚手架。
> 范围：4 个文本任务（工艺路线 / G代码 / 排产 / 报价），**不含图纸识别(视觉)**。

## 目录结构

```
training/
├── README.md              # 本文件，按顺序执行即可
├── setup.sh               # GPU 机器环境安装（conda + torch + LLaMA-Factory）
├── dataset_info.json      # LLaMA-Factory 数据集注册（alpaca + system 字段）
├── train_config.yaml      # QLoRA 训练配置（单卡 24GB 可跑）
├── evaluate.py            # 训后评估：JSON 合法率 / G代码语法 / 工序完整率
└── data/
    └── machining_sft.json # 训练数据（在 Mac 上用蒸馏脚本生成后拷过来）
```

## 步骤

### 0. 在 Mac 上先攒数据（强模型蒸馏，最优先）
```bash
cd ../backend
# .env 临时指向强模型（蒸馏阶段才需要 key）：
#   MISTRAL_BASE_URL=https://api.mistral.ai/v1
#   MISTRAL_MODEL=mistral-large-latest      # 或 OpenAI gpt-4o
#   MISTRAL_API_KEY=<key>
venv/bin/python scripts/generate_sft_corpus.py --output ../training/data/machining_sft.json
# 攒够几百~几千条后，把 training/data/machining_sft.json 拷到 GPU 机器
```
> ⚠️ 别用本地 7B 自产自销当训练数据——质量不够，越训越差。务必用云端 large 模型蒸馏。

### 1. GPU 机器装环境
```bash
cd training
bash setup.sh            # 建 conda 环境 machining-llm + 装 torch/LLaMA-Factory
conda activate machining-llm
```

### 2. 注册数据集
把 `dataset_info.json` 放到 LLaMA-Factory 的 `data/` 目录，或用 `--dataset_dir` 指向本目录：
本仓库已把 `dataset_info.json` 与 `data/machining_sft.json` 放在一起，训练时用
`dataset_dir: training`（见 train_config.yaml）即可。

### 3. 冒烟训练（先用少量数据验证链路）
```bash
# 先确认配置无误：用一小份数据 + num_train_epochs:1 跑通再放量
llamafactory-cli train train_config.yaml
```
产物 LoRA 在 `train_config.yaml` 的 `output_dir`（默认 `./machining-qwen-lora`）。

### 4. 评估（判断有没有用）
```bash
# 先用训好的模型对验证集做推理，得到 predictions.jsonl（每行 {task, output, reference}）
# 再算指标：
python evaluate.py --pred predictions.jsonl
# 目标：JSON 合法率 100% / G代码语法 100% / 工序完整率 ≥90% / 报价 MAPE ≤10%
# 判定：≥ 现有 prompt 工程方案，才值得挂回平台
```

### 5. 合并 LoRA + vLLM 起服务
```bash
# 合并 LoRA 到基座（导出完整权重）
llamafactory-cli export merge_config.yaml   # 见 README 末尾的 merge 模板
# 或直接用 vLLM 加载 base + LoRA：
pip install vllm
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --enable-lora --lora-modules machining=./machining-qwen-lora \
  --port 8001 --served-model-name machining-qwen
```

### 6. 挂回平台（闭环，无需改业务代码）
平台 `_call_api` 走 OpenAI 兼容协议。改 `backend/.env`：
```
MISTRAL_BASE_URL=http://<GPU机IP>:8001/v1
MISTRAL_MODEL=machining-qwen
# 自训服务一般不校验 key；若 vLLM 设了 --api-key 则填上 MISTRAL_API_KEY
```
重启后端即切到自训模型。视觉(图纸识别)仍走原视觉模型(Ollama llava 或云端)。

---

### merge_config.yaml 模板（步骤5用）
```yaml
model_name_or_path: Qwen/Qwen2.5-7B-Instruct
adapter_name_or_path: ./machining-qwen-lora
template: qwen
finetuning_type: lora
export_dir: ./machining-qwen-merged
export_size: 4
export_legacy_format: false
```
