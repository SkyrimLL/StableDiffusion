# LMStudioToInvokeAI

Automatically converts your **LM Studio conversations** into AI-generated images via **Invoke AI**. The script reads your recent chat transcripts, uses an LLM to extract a visual summary/prompt, and queues image generation jobs directly in Invoke AI.

---

## How It Works

1. **Scan** – Finds the most recent LM Studio conversation JSON files in your configured folder.
2. **Summarize** – Sends each conversation transcript to an LM Studio API endpoint to generate a descriptive image prompt.
3. **Queue** – Submits the generated prompt to Invoke AI's queue using an SDXL graph pipeline.
4. **Monitor** – Polls the Invoke AI queue until all jobs complete, then sends a desktop notification.

---

## Requirements

- Python 3.10+
- [LM Studio](https://lmstudio.ai/) running locally with its API server enabled (Tested on 0.4.7)
- [Invoke AI](https://github.com/invoke-ai/InvokeAI) running locally (v5/v6 = Tested on 6.12)

### Python Dependencies

```bash
pip install requests pyyaml plyer
```

---

## Configuration

Copy or edit `config.yaml` in the same directory as the script. All settings are required unless marked optional.

```yaml
# LM Studio local API endpoint (for prompt generation)
lm_studio_api: "http://localhost:1234/v1/chat/completions"

# Invoke AI API endpoints
invoke_ai_api:    "http://localhost:9090/api/v1"
invoke_ai_api_v2: "http://localhost:9090/api/v2"

# Path to LM Studio conversation files
home: "C:/Users/YourName/AppData/Roaming/LM Studio"
convo_subpath: "conversations/*.json"

# Default SDXL model name (must match exactly in your Invoke AI model library)
default_model: "your-sdxl-model-name"

# LLM prompts used to extract a visual description from the conversation
system_prompt: "You are an expert at writing Stable Diffusion image prompts."
user_prompt: "Summarize the following conversation as a single vivid image generation prompt"

# Image generation parameters
negative_prompt: "blurry, watermark, text"
width:    1024
height:   1024
steps:    30
cfg_scale: 7.0
scheduler: "dpmpp_2m"

# How many recent conversation files to process
number_of_files: 3

# How many prompt variants to generate per conversation
number_of_prompt_variants: 1

# How many images to render per prompt
number_of_images: 1
```

---

## Usage

### Basic (uses `default_model` from config)

```bash
python LMStudioToInvokeAI.py
```

### Override the model via CLI

```bash
python LMStudioToInvokeAI.py --model "my-other-sdxl-model"
```

---

## CLI Arguments

| Argument  | Type   | Default | Description                                              |
|-----------|--------|---------|----------------------------------------------------------|
| `--model` | string | `None`  | Model name to use for image generation (overrides config) |

---

## Output

- Generated image prompts are printed to the console (first 100 characters shown).
- Jobs are queued in the Invoke AI default queue.
- A **desktop notification** is sent when all renders are complete.
- Check your Invoke AI gallery for the finished images.

---

## File Structure

```
LMStudioToInvokeAI/
├── LMStudioToInvokeAI.py   # Main script
├── config.yaml             # Your local configuration
└── README.md               # This file
```

---

## Notes

- Only conversations with more than **100 characters** of extracted text are processed.
- The script uses the **most recently modified** conversation files, up to `number_of_files`.
- The model must be loaded in your Invoke AI model library and the name must match exactly.
- Transcripts are truncated to **4000 characters** when sent to the LLM for summarization.