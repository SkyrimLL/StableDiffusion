# BrainstormInvokeAI

A Python tool to benchmark InvokeAI models by running the same prompt across multiple models and measuring performance.

## Features

- 🚀 **Automated Benchmarking**: Run the same prompt against multiple InvokeAI models automatically
- 📊 **Performance Tracking**: Measure and record generation times for each model
- 🎯 **Configurable Selection**: Limit the number of models or filter by base type (SD1.5, SDXL, etc.)
- 🔄 **Multiple Iterations**: Run multiple iterations per model for more accurate results
- 💾 **JSON Output**: Save detailed benchmark results with timestamps and configuration
- 🎨 **Flexible Settings**: Configure image size, steps, CFG scale, scheduler, and more

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy `config_sample.yaml` to `config.yaml` and update with your settings:
   ```bash
   cp config_sample.yaml config.yaml
   ```

## Configuration

Edit `config.yaml` to customize your benchmark settings:

### API Settings
- `invoke_ai_api`: InvokeAI API v1 endpoint (default: `http://localhost:9090/api/v1`)
- `invoke_ai_api_v2`: InvokeAI API v2 endpoint (default: `http://localhost:9090/api/v2`)

### Prompt Settings
- `default_prompt`: Default prompt to use if none provided via `--prompt` argument
- `logs_path`: Output directory for benchmark JSON files (default: `./logs`)

### Model Selection
- `base_filter`: Filter models by base type (e.g., `"sdxl"`, `"sd-1"`, `"sd-2"`)
- `max_models`: Maximum number of models to benchmark (0 or blank = all models)

### Generation Parameters
- `width` / `height`: Output image dimensions (default: 1024x1024)
- `steps`: Number of denoising steps (default: 30)
- `cfg_scale`: Classifier-free guidance scale (default: 7.5)
- `scheduler`: Sampler/scheduler to use (default: `"dpmpp_sde"`)
- `seed`: Fixed seed for reproducible results (blank = random)

### Prompt Modifiers
- `positive_prompt`: Additional positive prompt text appended to your input
- `negative_prompt`: Negative prompt for all generations

### Advanced
- `vae_override`: Use a specific VAE for all models (fixes black images on some models)
- `batch_timeout`: Maximum seconds to wait for a batch before timing out (default: 600)
- `max_retries`: Maximum consecutive errors before skipping a batch (default: 3)

## Usage

### Basic Benchmark

Run with the default prompt from config.yaml:

```bash
python BrainstormInvokeAI.py
```

Or provide a custom prompt:

```bash
python BrainstormInvokeAI.py --prompt "a beautiful sunset over mountains"
```

### Limit Number of Models

Benchmark only the first N models:

```bash
python BrainstormInvokeAI.py --prompt "a beautiful sunset" --max-models 3
```

### Filter by Base Model

Benchmark only SDXL models:

```bash
python BrainstormInvokeAI.py --prompt "a beautiful sunset" --base-filter sdxl
```

### Multiple Iterations

Run multiple iterations per model for better timing data:

```bash
python BrainstormInvokeAI.py --prompt "a beautiful sunset" --iterations 3
```

### Custom Output File

Specify where to save results:

```bash
python BrainstormInvokeAI.py --prompt "a beautiful sunset" --output my_benchmark.json
```

### Combined Example

```bash
python BrainstormInvokeAI.py \
  --prompt "a majestic dragon flying over a castle" \
  --max-models 5 \
  --base-filter sdxl \
  --iterations 2 \
  --output dragon_benchmark.json
```

## Command Line Arguments

| Argument | Description | Required |
|----------|-------------|----------|
| `--prompt` | Text prompt to benchmark with | ✅ Yes |
| `--max-models` | Maximum number of models to test | ❌ No |
| `--base-filter` | Filter by base model type (e.g., 'sdxl') | ❌ No |
| `--iterations` | Number of iterations per model (default: 1) | ❌ No |
| `--output` | Output JSON file path (default: auto-generated in logs_path) | ❌ No |

## Output

The tool generates a JSON file with benchmark results. By default, results are saved to the directory specified by `logs_path` in config.yaml (default: `./logs`). The logs directory is created automatically if it doesn't exist.

Output files are named with timestamps: `benchmark_YYYYMMDD_HHMMSS.json`

Each JSON file contains:

```json
{
  "benchmark_date": "2026-08-20T10:30:00",
  "prompt": "a beautiful sunset over mountains",
  "config": {
    "width": 1024,
    "height": 1024,
    "steps": 30,
    "cfg_scale": 7.5,
    "scheduler": "dpmpp_sde",
    "seed": 42
  },
  "total_models": 5,
  "total_iterations": 5,
  "total_time_seconds": 245.3,
  "batches": [
    {
      "batch_id": "abc123...",
      "model_name": "Juggernaut XL v9",
      "model_key": "model-key-123",
      "model_base": "sdxl",
      "iteration": 1,
      "queue_time": 1234567890.123
    }
  ]
}
```

## How It Works

1. **Model Discovery**: Fetches all available models from InvokeAI API
2. **Filtering**: Applies base model filter and max models limit
3. **Queue Jobs**: Submits the same prompt to each model with identical settings
4. **Monitor Progress**: Tracks batch completion and timing
5. **Save Results**: Exports detailed benchmark data to JSON

## Robustness & Error Handling

The tool includes several features to prevent queue stalls and handle interruptions gracefully:

- **Timeout Protection**: Automatically skips batches that exceed the configured timeout (default: 10 minutes)
- **Retry Logic**: Retries failed API requests up to 3 times before skipping a batch
- **Manual Interruption**: Press `Ctrl+C` to stop monitoring while jobs continue in InvokeAI
- **Deleted Batches**: Detects and handles batches that are canceled or deleted externally
- **Network Resilience**: Continues monitoring other batches even if some requests fail
- **Status Tracking**: Records completion status (completed, timeout, error, canceled) for each batch

These safeguards ensure the benchmark completes even if individual jobs fail or are interrupted.

## Tips

- Use a **fixed seed** in config.yaml for reproducible results across runs
- Start with **fewer models** (`--max-models 3`) to test your setup
- Use **base-filter** to compare models within the same family (e.g., all SDXL models)
- Run **multiple iterations** for more reliable timing data
- Check the **generated images** in InvokeAI to verify quality differences

## Troubleshooting

### No models found
- Check that InvokeAI is running and accessible at the configured API endpoint
- Verify your `base_filter` matches your model base types (use `sdxl`, not `SDXL`)

### Black images
- Set `vae_override` in config.yaml to a fp16-fix VAE model
- Example: `vae_override: "sdxl-vae-fp16-fix"`

### Connection errors
- Ensure InvokeAI is running on the correct port
- Check firewall settings if InvokeAI is on a different machine

### Benchmark stalls or hangs
- The tool now automatically handles stalled jobs with timeout and retry logic
- Adjust `batch_timeout` in config.yaml if your jobs typically take longer than 10 minutes
- Increase `max_retries` if you have intermittent connection issues
- Press `Ctrl+C` to stop monitoring; queued jobs will continue in InvokeAI

### Jobs interrupted before completion
- The tool will automatically skip batches that time out or encounter persistent errors
- Check the InvokeAI queue panel to see the status of individual jobs
- Review the benchmark JSON output for status information on each batch

## License

This tool is provided as-is for benchmarking InvokeAI installations.

## Related Tools

- **LMStudioToInvokeAI**: Convert LM Studio conversations to images
- **InvokeDBToFiles**: Export images from InvokeAI database
- **MidjourneyImport**: Import Midjourney images to InvokeAI
