import os
import json
import time
import argparse
import random
from datetime import datetime
from colorama import Fore, Style, init
import yaml
import requests
from plyer import notification
import traceback

# Initialize colorama for Windows
init(autoreset=True)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.yaml")

# --- CONFIGURATION ---

def load_config(config_path):
    """Loads configuration from a YAML file."""
    print(f">> Loading configuration from {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_all_models(api_url, base_filter=None, model_type="main"):
    """Fetches all available models from InvokeAI, optionally filtered by base model."""
    print(f" -> Fetching models from InvokeAI API...")
    try:
        params = {"model_type": model_type} if model_type else {}
        response = requests.get(f"{api_url}/models/", params=params)
        
        if response.status_code != 200:
            print(f"{Fore.RED}❌ Failed to fetch models: {response.status_code}{Style.RESET_ALL}")
            return []
        
        models = response.json().get('models', [])
        
        # Filter by base model if specified
        if base_filter:
            base_filter_lower = base_filter.lower()
            models = [m for m in models if (m.get('base') or m.get('base_model', '')).lower() == base_filter_lower]
        
        # Format model info
        model_list = []
        for m in models:
            model_info = {
                "key": m.get('key'),
                "hash": m.get('hash'),
                "name": m.get('name'),
                "base": (m.get('base') or m.get('base_model', 'unknown')).lower(),
                "type": (m.get('type') or m.get('model_type', 'main')).lower()
            }
            
            # Only include models with complete info
            if all(model_info.values()):
                model_list.append(model_info)
        
        print(f" ✅ Found {len(model_list)} models")
        if base_filter:
            print(f"    (filtered to base: {base_filter})")
        
        return model_list
    
    except Exception as e:
        print(f"{Fore.RED}❌ Error fetching models: {e}{Style.RESET_ALL}")
        traceback.print_exc()
        return []


def get_vae_info(target_name, api_url):
    """Fetches model info for a VAE by name from Invoke AI."""
    print(f" -> Looking up VAE info for: {target_name}")
    try:
        response = requests.get(f"{api_url}/models/", params={"model_type": "vae"})
        if response.status_code != 200:
            return None
        models = response.json().get('models', [])
        for m in models:
            if m.get('name') == target_name:
                vae_id = {
                    "key": m.get('key'),
                    "hash": m.get('hash'),
                    "name": m.get('name'),
                    "base": (m.get('base') or m.get('base_model', 'unknown')).lower(),
                    "type": "vae"
                }
                if vae_id['key']:
                    print(f" ✅ Found VAE: {target_name}")
                    return vae_id
        print(f"{Fore.YELLOW} ⚠️ VAE '{target_name}' not found — using model's bundled VAE.{Style.RESET_ALL}")
        return None
    except Exception as e:
        print(f"Error querying VAE models: {e}")
        return None


def queue_to_invoke(prompt, model_info, cfg_params, vae_info=None):
    """Submits a modular graph to Invoke AI to generate an image."""
    seed = cfg_params.get('seed')
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    invoke_ai_api = cfg_params.get('invoke_ai_api')
    pos_prompt  = cfg_params.get('positive_prompt')
    neg_prompt  = cfg_params.get('negative_prompt')
    width       = cfg_params.get('width')
    height      = cfg_params.get('height')
    steps       = cfg_params.get('steps')
    cfg         = cfg_params.get('cfg_scale')
    scheduler   = cfg_params.get('scheduler')

    # Combine prompts
    final_prompt = prompt if pos_prompt is None else f"{prompt}, {pos_prompt}"

    nodes = {
        "loader": {"id": "loader", "type": "sdxl_model_loader", "model": model_info},
        "pos": {"id": "pos", "type": "sdxl_compel_prompt", "prompt": final_prompt, "style": final_prompt},
        "neg": {"id": "neg", "type": "sdxl_compel_prompt", "prompt": neg_prompt, "style": neg_prompt},
        "noise": {"id": "noise", "type": "noise", "width": width, "height": height, "seed": seed},
        "denoise": {"id": "denoise", "type": "denoise_latents", "steps": steps, "cfg_scale": cfg, "scheduler": scheduler},
        "metadata": {
            "id": "metadata",
            "type": "core_metadata",
            "positive_prompt": final_prompt,
            "negative_prompt": neg_prompt,
            "seed": seed,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg,
            "scheduler": scheduler,
            "model": model_info
        },
        "render": {"id": "render", "type": "l2i", "is_intermediate": False, "metadata": None}
    }

    # Add VAE loader if override is provided
    if vae_info:
        nodes["vae_loader"] = {"id": "vae_loader", "type": "vae_loader", "vae_model": vae_info}
        vae_source_node = "vae_loader"
    else:
        vae_source_node = "loader"

    graph = {
        "nodes": nodes,
        "edges": [
            # Connect Loader to Prompts (SDXL requires clip AND clip2)
            {"source": {"node_id": "loader", "field": "clip"}, "destination": {"node_id": "pos", "field": "clip"}},
            {"source": {"node_id": "loader", "field": "clip2"}, "destination": {"node_id": "pos", "field": "clip2"}},
            {"source": {"node_id": "loader", "field": "clip"}, "destination": {"node_id": "neg", "field": "clip"}},
            {"source": {"node_id": "loader", "field": "clip2"}, "destination": {"node_id": "neg", "field": "clip2"}},

            # Connect UNet and VAE
            {"source": {"node_id": "loader", "field": "unet"}, "destination": {"node_id": "denoise", "field": "unet"}},
            {"source": {"node_id": vae_source_node, "field": "vae"}, "destination": {"node_id": "render", "field": "vae"}},

            # Connect Conditionings
            {"source": {"node_id": "pos", "field": "conditioning"}, "destination": {"node_id": "denoise", "field": "positive_conditioning"}},
            {"source": {"node_id": "neg", "field": "conditioning"}, "destination": {"node_id": "denoise", "field": "negative_conditioning"}},

            # Connect Noise and Final Output
            {"source": {"node_id": "noise", "field": "noise"}, "destination": {"node_id": "denoise", "field": "noise"}},
            {"source": {"node_id": "denoise", "field": "latents"}, "destination": {"node_id": "render", "field": "latents"}},

            # Link metadata to render
            {"source": {"node_id": "metadata", "field": "metadata"}, "destination": {"node_id": "render", "field": "metadata"}}
        ]
    }

    payload = {"batch": {"graph": graph, "runs": 1}}
    
    try:
        res = requests.post(f"{invoke_ai_api}/queue/default/enqueue_batch", json=payload)
        
        if res.status_code in [200, 201]:
            batch_id = res.json()['batch']['batch_id']
            print(f"{Fore.GREEN} 🚀 Job Enqueued! Batch: {batch_id}{Style.RESET_ALL}")
            return batch_id
        else:
            print(f"{Fore.RED}❌ Failed: {res.status_code} - {res.text}{Style.RESET_ALL}")
            return None
    except Exception as e:
        print(f"{Fore.RED}❌ Error queueing job: {e}{Style.RESET_ALL}")
        return None


def monitor_queue(batch_ids, api_url, batch_timeout=600, max_retries=3):
    """Polls the Invoke AI Queue API to track batch completion status with timing.
    
    Args:
        batch_ids: List of batch IDs to monitor
        api_url: InvokeAI API base URL
        batch_timeout: Maximum seconds to wait for a single batch (default: 600s/10min)
        max_retries: Maximum consecutive errors before skipping a batch (default: 3)
    
    Returns:
        dict: Mapping of batch_id to completion data (status, elapsed, completed, errors, canceled)
    """
    pending_batches = {
        b_id: {
            "start_time": time.time(),
            "error_count": 0,
            "last_successful_check": time.time()
        } for b_id in batch_ids
    }
    completed_batches = {}  # Store results for return
    print(f"\n[Monitor] Tracking {len(pending_batches)} batches...")

    while pending_batches:
        current_time = time.time()
        
        for b_id in list(pending_batches.keys()):
            batch_data = pending_batches[b_id]
            elapsed = current_time - batch_data["start_time"]
            
            # Check for timeout
            if elapsed > batch_timeout:
                print(f"{Fore.YELLOW} ⚠️ Batch {b_id} timed out after {elapsed:.1f}s. Skipping.{Style.RESET_ALL}")
                completion_data = {
                    "end_time": current_time,
                    "elapsed": elapsed,
                    "status": "timeout",
                    "completed": 0,
                    "errors": 0,
                    "canceled": 1
                }
                completed_batches[b_id] = completion_data
                del pending_batches[b_id]
                continue
            
            url = f"{api_url}/queue/default/b/{b_id}/status"

            try:
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    # Reset error count on successful response
                    batch_data["error_count"] = 0
                    batch_data["last_successful_check"] = current_time
                    
                    data = response.json()
                    completed = data.get('completed', 0)
                    total     = data.get('total', 0)
                    errors    = data.get('errors', 0)
                    canceled  = data.get('canceled', 0)
                    in_progress = data.get('in_progress', 0)
                    pending = data.get('pending', 0)
                    failed = data.get('failed', 0)
                    
                    # Check for batch-level status that might indicate failure
                    batch_status = data.get('status', '').lower()
                    
                    # Log unexpected conditions for debugging
                    accounted = completed + errors + canceled + failed
                    if accounted < total and (in_progress + pending == 0):
                        print(f"{Fore.CYAN} 🔍 Debug - Batch {b_id}: {completed}/{total} done, "
                              f"{errors} errors, {failed} failed, {canceled} canceled, "
                              f"{in_progress} in_progress, {pending} pending - "
                              f"Missing: {total - accounted} items{Style.RESET_ALL}")
                    
                    # Track if we've seen this exact state before (for stuck detection)
                    state_key = f"{completed}_{errors}_{canceled}_{in_progress}_{pending}_{failed}"
                    if "last_state" not in batch_data:
                        batch_data["last_state"] = state_key
                        batch_data["last_state_time"] = current_time
                        batch_data["stuck_count"] = 0
                    elif batch_data["last_state"] == state_key:
                        # Same state - check if we've been stuck too long
                        time_in_state = current_time - batch_data["last_state_time"]
                        if time_in_state > 60:  # 60 seconds with no change
                            batch_data["stuck_count"] += 1
                            if batch_data["stuck_count"] >= 3:  # 3 checks = ~6 seconds total stuck time
                                print(f"{Fore.YELLOW} ⚠️ Batch {b_id} appears stuck (no progress for {time_in_state:.0f}s). "
                                      f"Status: {completed}/{total} completed, {errors} errors, {canceled} canceled, "
                                      f"{in_progress} in_progress, {pending} pending, {failed} failed{Style.RESET_ALL}")
                                
                                # Consider any incomplete items as errors if stuck
                                effective_errors = errors + failed + in_progress + pending
                                elapsed = current_time - batch_data["start_time"]
                                
                                completion_data = {
                                    "end_time": current_time,
                                    "elapsed": elapsed,
                                    "completed": completed,
                                    "errors": effective_errors,
                                    "canceled": canceled,
                                    "status": "stuck"
                                }
                                completed_batches[b_id] = completion_data
                                del pending_batches[b_id]
                                continue
                    else:
                        # State changed - reset stuck tracking
                        batch_data["last_state"] = state_key
                        batch_data["last_state_time"] = current_time
                        batch_data["stuck_count"] = 0
                    
                    # Include 'failed' in the completion check
                    # Done when every item is accounted for
                    if completed + errors + canceled + failed >= total:
                        elapsed = current_time - batch_data["start_time"]
                        
                        # Combine errors and failed counts
                        total_errors = errors + failed
                        
                        # Determine actual status based on what happened
                        if canceled > 0 and completed == 0 and total_errors == 0:
                            status = "canceled"
                            status_icon = f"{Fore.YELLOW} ⚠️"
                        elif total_errors > 0 and completed == 0 and canceled == 0:
                            status = "failed"
                            status_icon = f"{Fore.RED} ❌"
                        elif canceled > 0 or total_errors > 0:
                            status = "completed_with_issues"
                            status_icon = f"{Fore.YELLOW} ⚠️"
                        else:
                            status = "completed"
                            status_icon = f"{Fore.GREEN} ✅"
                        
                        # Build detailed status message
                        status_parts = [f"{completed} success"]
                        if total_errors > 0:
                            status_parts.append(f"{total_errors} errors")
                        if canceled > 0:
                            status_parts.append(f"{canceled} canceled")
                        
                        print(f"{status_icon} Batch {b_id} finished in {elapsed:.1f}s "
                              f"({', '.join(status_parts)}).{Style.RESET_ALL}")
                        
                        # Store completion data (use combined error count)
                        completion_data = {
                            "end_time": current_time,
                            "elapsed": elapsed,
                            "completed": completed,
                            "errors": total_errors,
                            "canceled": canceled,
                            "status": status
                        }
                        completed_batches[b_id] = completion_data
                        del pending_batches[b_id]

                elif response.status_code == 404:
                    print(f"{Fore.YELLOW} ⚠️ Batch {b_id} not found (deleted or canceled). Skipping.{Style.RESET_ALL}")
                    completion_data = {
                        "end_time": current_time,
                        "elapsed": current_time - batch_data["start_time"],
                        "status": "not_found",
                        "completed": 0,
                        "errors": 0,
                        "canceled": 1
                    }
                    completed_batches[b_id] = completion_data
                    del pending_batches[b_id]

                else:
                    batch_data["error_count"] += 1
                    print(f"{Fore.YELLOW} ⚠️ Could not get status for {b_id}: {response.status_code} "
                          f"(attempt {batch_data['error_count']}/{max_retries}){Style.RESET_ALL}")
                    
                    if batch_data["error_count"] >= max_retries:
                        print(f"{Fore.RED} ❌ Batch {b_id} exceeded max retries. Skipping.{Style.RESET_ALL}")
                        completion_data = {
                            "end_time": current_time,
                            "elapsed": current_time - batch_data["start_time"],
                            "status": "error",
                            "completed": 0,
                            "errors": 1,
                            "canceled": 0
                        }
                        completed_batches[b_id] = completion_data
                        del pending_batches[b_id]

            except requests.exceptions.Timeout:
                batch_data["error_count"] += 1
                print(f"{Fore.YELLOW} ⚠️ Timeout checking batch {b_id} "
                      f"(attempt {batch_data['error_count']}/{max_retries}){Style.RESET_ALL}")
                
                if batch_data["error_count"] >= max_retries:
                    print(f"{Fore.RED} ❌ Batch {b_id} exceeded max retries. Skipping.{Style.RESET_ALL}")
                    completion_data = {
                        "end_time": current_time,
                        "elapsed": current_time - batch_data["start_time"],
                        "status": "timeout_error",
                        "completed": 0,
                        "errors": 1,
                        "canceled": 0
                    }
                    completed_batches[b_id] = completion_data
                    del pending_batches[b_id]
                    
            except Exception as e:
                batch_data["error_count"] += 1
                print(f"{Fore.RED} ❌ Connection error checking batch {b_id}: {e} "
                      f"(attempt {batch_data['error_count']}/{max_retries}){Style.RESET_ALL}")
                
                if batch_data["error_count"] >= max_retries:
                    print(f"{Fore.RED} ❌ Batch {b_id} exceeded max retries. Skipping.{Style.RESET_ALL}")
                    completion_data = {
                        "end_time": current_time,
                        "elapsed": current_time - batch_data["start_time"],
                        "status": "error",
                        "completed": 0,
                        "errors": 1,
                        "canceled": 0
                    }
                    completed_batches[b_id] = completion_data
                    del pending_batches[b_id]

        if pending_batches:
            time.sleep(2)  # Poll every 2 seconds
    
    return completed_batches


def save_results(results, output_file):
    """Save benchmark results to a JSON file."""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, indent=2, fp=f)
        print(f"\n{Fore.CYAN}📊 Results saved to: {output_file}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}❌ Error saving results: {e}{Style.RESET_ALL}")


def main():
    """Main workflow: benchmark InvokeAI models."""
    parser = argparse.ArgumentParser(description="Benchmark InvokeAI models with a test prompt")
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Text prompt to use for benchmarking (uses default_prompt from config if not specified)"
    )
    parser.add_argument(
        "--max-models",
        type=int,
        default=None,
        help="Maximum number of models to benchmark (default: all models)"
    )
    parser.add_argument(
        "--base-filter",
        type=str,
        default=None,
        help="Filter models by base type (e.g., 'sdxl', 'sd-1', 'sd-2')"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Number of iterations per model (default: from config or 1)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for benchmark results (default: benchmark_TIMESTAMP.json)"
    )
    
    args = parser.parse_args()

    # Load configuration
    config = load_config(CONFIG_FILE)

    # Use provided prompt or fall back to config default
    prompt = args.prompt or config.get('default_prompt')
    if not prompt:
        print(f"{Fore.RED}❌ No prompt provided. Use --prompt or set default_prompt in config.yaml{Style.RESET_ALL}")
        return

    invoke_ai_api   = config.get('invoke_ai_api')
    invoke_ai_api_v2 = config.get('invoke_ai_api_v2')
    
    cfg_params = {
        'invoke_ai_api': invoke_ai_api,
        'negative_prompt': config.get('negative_prompt'),
        'positive_prompt': config.get('positive_prompt'),
        'width':           config.get('width'),
        'height':          config.get('height'),
        'steps':           config.get('steps'),
        'cfg_scale':       config.get('cfg_scale'),
        'scheduler':       config.get('scheduler'),
        'seed':            config.get('seed'),  # Use fixed seed for consistent benchmarking
    }

    # Get base filter from config if not specified in CLI
    base_filter = args.base_filter or config.get('base_filter')
    max_models = args.max_models or config.get('max_models')
    iterations = args.iterations if args.iterations is not None else config.get('iterations', 1)

    # Fetch all available models
    all_models = get_all_models(invoke_ai_api_v2, base_filter=base_filter, model_type="main")
    
    if not all_models:
        print(f"{Fore.RED}❌ No models found. Check your InvokeAI connection.{Style.RESET_ALL}")
        return

    # Randomize models if configured
    randomize_models = config.get('randomize_models', False)
    if randomize_models:
        random.shuffle(all_models)
        print(f" -> Models randomized for selection")

    # Limit number of models if specified
    if max_models and max_models > 0:
        all_models = all_models[:max_models]
        print(f" -> Limited to {len(all_models)} models")

    # Look up VAE override (if configured)
    vae_override_name = config.get('vae_override', '').strip()
    vae_info = None
    if vae_override_name:
        vae_info = get_vae_info(vae_override_name, invoke_ai_api_v2)

    # Display benchmark configuration
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}BENCHMARK CONFIGURATION{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"Prompt: {prompt}")
    print(f"Models: {len(all_models)}")
    print(f"Iterations per model: {iterations}")
    print(f"Image size: {cfg_params['width']}x{cfg_params['height']}")
    print(f"Steps: {cfg_params['steps']}")
    print(f"CFG Scale: {cfg_params['cfg_scale']}")
    print(f"Scheduler: {cfg_params['scheduler']}")
    if cfg_params.get('seed'):
        print(f"Seed: {cfg_params['seed']} (fixed)")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")

    # Queue jobs for each model
    benchmark_start = time.time()
    batch_info = []
    
    for idx, model_info in enumerate(all_models, 1):
        model_name = model_info['name']
        print(f"\n{Fore.BLUE}[{idx}/{len(all_models)}] Queuing: {model_name}{Style.RESET_ALL}")
        
        for iteration in range(iterations):
            batch_id = queue_to_invoke(prompt, model_info, cfg_params, vae_info)
            if batch_id:
                batch_info.append({
                    "batch_id": batch_id,
                    "model_name": model_name,
                    "model_key": model_info['key'],
                    "model_base": model_info['base'],
                    "iteration": iteration + 1,
                    "queue_time": time.time()
                })
            time.sleep(0.5)  # Small delay between queue operations

    if not batch_info:
        print(f"{Fore.RED}❌ No jobs were queued successfully.{Style.RESET_ALL}")
        return

    # Monitor all batches
    print(f"\n{Fore.CYAN}Monitoring {len(batch_info)} jobs across {len(all_models)} models...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Press Ctrl+C to stop monitoring (jobs will continue in InvokeAI){Style.RESET_ALL}")
    batch_ids = [b["batch_id"] for b in batch_info]
    
    # Get timeout configuration from config (default 600s = 10 minutes)
    batch_timeout = config.get('batch_timeout', 600)
    max_retries = config.get('max_retries', 3)
    
    try:
        batch_results = monitor_queue(batch_ids, invoke_ai_api, batch_timeout=batch_timeout, max_retries=max_retries)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠️ Monitoring interrupted by user. Jobs will continue in InvokeAI.{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}You can check their status in the InvokeAI queue panel.{Style.RESET_ALL}")
        batch_results = {}
    
    # Merge batch results back into batch_info
    for batch in batch_info:
        batch_id = batch["batch_id"]
        if batch_id in batch_results:
            batch.update(batch_results[batch_id])
    
    benchmark_end = time.time()
    total_time = benchmark_end - benchmark_start

    # Calculate summary statistics
    status_counts = {}
    total_completed = 0
    total_errors = 0
    total_canceled = 0
    
    for batch in batch_info:
        status = batch.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
        total_completed += batch.get('completed', 0)
        total_errors += batch.get('errors', 0)
        total_canceled += batch.get('canceled', 0)

    # Compile results
    results = {
        "benchmark_date": datetime.now().isoformat(),
        "prompt": prompt,
        "config": {
            "width": cfg_params['width'],
            "height": cfg_params['height'],
            "steps": cfg_params['steps'],
            "cfg_scale": cfg_params['cfg_scale'],
            "scheduler": cfg_params['scheduler'],
            "seed": cfg_params.get('seed'),
            "base_filter": base_filter,
            "max_models": max_models,
            "iterations": iterations
        },
        "total_models": len(all_models),
        "total_iterations": len(batch_info),
        "total_time_seconds": total_time,
        "summary": {
            "total_completed": total_completed,
            "total_errors": total_errors,
            "total_canceled": total_canceled,
            "status_counts": status_counts
        },
        "batches": batch_info
    }

    # Generate output filename
    if args.output:
        output_file = args.output
    else:
        # Use logs_path from config
        logs_path = config.get('logs_path', './logs')
        # Make path absolute if it's relative
        if not os.path.isabs(logs_path):
            logs_path = os.path.join(os.path.dirname(__file__), logs_path)
        # Create logs directory if it doesn't exist
        os.makedirs(logs_path, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(logs_path, f"benchmark_{timestamp}.json")

    save_results(results, output_file)

    # Summary
    print(f"\n{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}BENCHMARK COMPLETE{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
    print(f"Total Models: {len(all_models)}")
    print(f"Total Jobs: {len(batch_info)}")
    print(f"Total Time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
    print(f"Average per model: {total_time/len(all_models):.1f}s")
    print(f"\nJob Status:")
    print(f"  Completed: {status_counts.get('completed', 0)}")
    if status_counts.get('completed_with_issues', 0) > 0:
        print(f"  Completed with issues: {status_counts.get('completed_with_issues', 0)}")
    if total_canceled > 0:
        print(f"  Canceled: {status_counts.get('canceled', 0)} ({total_canceled} items)")
    if total_errors > 0:
        print(f"  Failed: {status_counts.get('failed', 0)} ({total_errors} items)")
    if status_counts.get('timeout', 0) > 0:
        print(f"  Timed out: {status_counts.get('timeout', 0)}")
    if status_counts.get('error', 0) > 0 or status_counts.get('timeout_error', 0) > 0:
        print(f"  Errors: {status_counts.get('error', 0) + status_counts.get('timeout_error', 0)}")
    if status_counts.get('not_found', 0) > 0:
        print(f"  Not found: {status_counts.get('not_found', 0)}")
    print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}")

    # Desktop notification
    notification.notify(
        title="InvokeAI Benchmark Complete",
        message=f"Tested {len(all_models)} models in {total_time/60:.1f} minutes",
        app_name="InvokeAI Benchmark",
        timeout=10
    )


if __name__ == "__main__":
    main()
