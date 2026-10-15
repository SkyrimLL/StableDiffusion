import os
import re
import sys
import json
import time
import argparse
import random
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from colorama import Fore, Style, init
import yaml
import requests
from plyer import notification
import traceback

# Initialize colorama for Windows
init(autoreset=True)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.yaml")

# Schema describing every editable config option exposed by the web UI form.
# Adding a new field here is all that is needed to surface it in the form and
# to coerce it correctly on save (Open/Closed: no handler changes required).
CONFIG_FIELDS = [
    {"key": "invoke_ai_api", "label": "InvokeAI API URL (v1)", "type": "text", "value_type": "str",
     "section": "Benchmark",
     "help": "Base URL for the InvokeAI v1 API (queueing/monitoring)."},
    {"key": "invoke_ai_api_v2", "label": "InvokeAI API URL (v2)", "type": "text", "value_type": "str",
     "help": "Base URL for the InvokeAI v2 API (model listing)."},
    {"key": "default_prompt", "label": "Default Prompt", "type": "textarea", "value_type": "str",
     "help": "Prompt used for every model when none is passed on the command line."},
    {"key": "positive_prompt", "label": "Positive Prompt Additions", "type": "text", "value_type": "str",
     "help": "Appended to the prompt to steer style/quality."},
    {"key": "negative_prompt", "label": "Negative Prompt", "type": "textarea", "value_type": "str",
     "help": "Concepts to avoid in generated images."},
    {"key": "logs_path", "label": "Logs Path", "type": "text", "value_type": "str",
     "help": "Directory where benchmark result JSON files are written."},
    {"key": "base_filter", "label": "Base Model Filter", "type": "text", "value_type": "str",
     "help": "Only benchmark models of this base type (e.g. sdxl, sd-1). Blank = all."},
    {"key": "max_models", "label": "Max Models", "type": "number", "value_type": "int",
     "help": "Maximum number of models to benchmark. Blank or 0 = all."},
    {"key": "randomize_models", "label": "Randomize Models", "type": "checkbox", "value_type": "bool",
     "help": "Randomly select models instead of taking the first N."},
    {"key": "iterations", "label": "Iterations per Model", "type": "number", "value_type": "int",
     "help": "How many times each model is tested."},
    {"key": "width", "label": "Width", "type": "number", "value_type": "int", "help": "Image width in pixels."},
    {"key": "height", "label": "Height", "type": "number", "value_type": "int", "help": "Image height in pixels."},
    {"key": "steps", "label": "Steps", "type": "number", "value_type": "int", "help": "Denoising steps."},
    {"key": "cfg_scale", "label": "CFG Scale", "type": "number", "value_type": "float", "step": "0.1",
     "help": "Classifier-free guidance scale."},
    {"key": "scheduler", "label": "Scheduler", "type": "text", "value_type": "str",
     "help": "Sampler/scheduler name (e.g. dpmpp_sde)."},
    {"key": "vae_override", "label": "VAE Override", "type": "text", "value_type": "str",
     "help": "Replace the model's bundled VAE with this named VAE. Blank = default."},
    {"key": "seed", "label": "Seed", "type": "number", "value_type": "int",
     "help": "Fixed seed for reproducible results. Blank = random each run."},
    {"key": "batch_timeout", "label": "Batch Timeout (s)", "type": "number", "value_type": "int",
     "help": "Max seconds to wait for a single batch before skipping."},
    {"key": "max_retries", "label": "Max Retries", "type": "number", "value_type": "int",
     "help": "Consecutive errors tolerated before skipping a batch."},
    {"key": "server_port", "label": "Server Port", "type": "number", "value_type": "int",
     "section": "Web Server",
     "help": "Port the local web UI listens on (applies on next server start)."},
    {"key": "server_autostart", "label": "Start Server By Default", "type": "checkbox", "value_type": "bool",
     "help": "Launch the web server when running with no CLI arguments."},
    {"key": "server_open_browser", "label": "Open Browser On Start", "type": "checkbox", "value_type": "bool",
     "help": "Automatically open a browser when the server starts."},
]

# --- CONFIGURATION ---

def load_config(config_path):
    """Loads configuration from a YAML file."""
    print(f">> Loading configuration from {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _coerce_field_value(field, value):
    """Coerces a raw form value to the type declared in the field schema."""
    value_type = field.get("value_type", "str")
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return "" if value_type == "str" else None
    try:
        if value_type == "int":
            return int(value)
        if value_type == "float":
            return float(value)
        if value_type == "bool":
            return bool(value)
    except (ValueError, TypeError):
        return value
    return str(value)


def save_config(config_path, form_values):
    """Persists edited form values back to the YAML config file.

    Uses ruamel.yaml when available to preserve the file's comments and
    formatting, falling back to PyYAML (which drops comments) otherwise.
    """
    updates = {}
    for field in CONFIG_FIELDS:
        key = field["key"]
        if key in form_values:
            updates[key] = _coerce_field_value(field, form_values[key])

    try:
        from ruamel.yaml import YAML
        yaml_rt = YAML()
        yaml_rt.preserve_quotes = True
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml_rt.load(f)
        for key, value in updates.items():
            data[key] = value
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml_rt.dump(data, f)
    except ImportError:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        data.update(updates)
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

    return updates


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


def execute_benchmark(config, output_file=None):
    """Runs the full benchmark workflow for an already-resolved config dict.

    Shared entry point used by both the CLI and the web server so the two
    surfaces always exercise identical behaviour.
    """
    # Use prompt from config (CLI/web overrides are applied before this call)
    prompt = config.get('default_prompt')
    if not prompt:
        print(f"{Fore.RED}❌ No prompt provided. Set default_prompt in config.yaml or pass --prompt.{Style.RESET_ALL}")
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

    # Resolve selection parameters from config (overrides already merged in)
    base_filter = config.get('base_filter')
    max_models = config.get('max_models')
    iterations = config.get('iterations', 1)

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
    if output_file:
        pass
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

    return results


# --- WEB SERVER MODE ---

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(text):
    """Removes ANSI colour escape codes so log text is readable in the browser."""
    return _ANSI_RE.sub('', text)


class RunStatus:
    """Thread-safe holder for the live state and log output of a benchmark run."""

    def __init__(self):
        self._lock = threading.Lock()
        self.state = "idle"  # idle | running | completed | error
        self.lines = []
        self._partial = ""
        self.started_at = None
        self.finished_at = None
        self.error = None

    def start(self):
        with self._lock:
            self.state = "running"
            self.lines = []
            self._partial = ""
            self.started_at = time.time()
            self.finished_at = None
            self.error = None

    def append_output(self, text):
        """Buffers raw stdout text and splits it into clean log lines."""
        with self._lock:
            self._partial += text
            while "\n" in self._partial:
                line, self._partial = self._partial.split("\n", 1)
                self.lines.append(_strip_ansi(line))

    def finish(self, error=None):
        with self._lock:
            if self._partial:
                self.lines.append(_strip_ansi(self._partial))
                self._partial = ""
            self.state = "error" if error else "completed"
            self.error = error
            self.finished_at = time.time()

    def snapshot(self, since=0):
        with self._lock:
            return {
                "state": self.state,
                "lines": self.lines[since:],
                "total_lines": len(self.lines),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed": (self.finished_at or time.time()) - self.started_at if self.started_at else 0,
                "error": self.error,
            }


class _TeeStream:
    """Writes stdout to both the real console and a RunStatus log buffer."""

    def __init__(self, original, status):
        self._original = original
        self._status = status

    def write(self, text):
        self._original.write(text)
        self._status.append_output(text)

    def flush(self):
        self._original.flush()


class BrainstormServer:
    """Coordinates the web UI: config persistence and single benchmark runs."""

    def __init__(self, config_file, host, port):
        self.config_file = config_file
        self.host = host
        self.port = port
        self.status = RunStatus()
        self._run_lock = threading.Lock()
        self._thread = None

    def is_running(self):
        return self.status.state == "running"

    def start_run(self):
        """Starts a benchmark in a background thread. Returns False if one is active."""
        with self._run_lock:
            if self.is_running():
                return False
            self.status.start()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def _run(self):
        old_stdout = sys.stdout
        sys.stdout = _TeeStream(old_stdout, self.status)
        error = None
        try:
            config = load_config(self.config_file)
            execute_benchmark(config)
        except Exception as exc:
            traceback.print_exc()
            error = str(exc)
        finally:
            sys.stdout = old_stdout
            self.status.finish(error=error)


# HTML/CSS/JS for the config form and live status panel. Kept self-contained so
# the tool has no extra static-file dependencies.
_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brainstorm InvokeAI</title>
<style>
  :root {
    --bg: #0f1115; --panel: #181b22; --panel2: #1f2430; --border: #2a3140;
    --text: #e6e9ef; --muted: #9aa4b2; --accent: #6d8bff; --accent2: #4f6ef7;
    --ok: #3fb950; --err: #f85149; --run: #d29922;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); }
  header { padding: 18px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  header .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px var(--accent); }
  .layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; padding: 20px 24px; align-items: start; }
  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .card h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); margin: 0; padding: 14px 18px; border-bottom: 1px solid var(--border); }
  .card-body { padding: 18px; }
  .field { margin-bottom: 16px; }
  .field label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 5px; }
  .field .help { font-size: 11px; color: var(--muted); margin-top: 4px; }
  .section-head { font-size: 12px; text-transform: uppercase; letter-spacing: .6px; color: var(--accent);
    font-weight: 700; margin: 22px 0 14px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
  .section-head:first-child { margin-top: 0; }
  input[type=text], input[type=number], textarea, select {
    width: 100%; background: var(--panel2); border: 1px solid var(--border); color: var(--text);
    border-radius: 8px; padding: 9px 11px; font-size: 13px; font-family: inherit; outline: none;
  }
  input:focus, textarea:focus { border-color: var(--accent); }
  textarea { resize: vertical; min-height: 64px; }
  .switch { display: flex; align-items: center; gap: 10px; }
  .switch input { width: 18px; height: 18px; accent-color: var(--accent2); }
  .actions { display: flex; gap: 10px; padding: 16px 18px; border-bottom: 1px solid var(--border); background: var(--panel); }
  button { border: none; border-radius: 8px; padding: 10px 18px; font-size: 13px; font-weight: 600; cursor: pointer; transition: .15s; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  .btn-run { background: var(--accent2); color: #fff; }
  .btn-run:hover:not(:disabled) { background: var(--accent); }
  .btn-save { background: var(--panel2); color: var(--text); border: 1px solid var(--border); }
  .btn-save:hover:not(:disabled) { border-color: var(--accent); }
  .status-bar { display: flex; align-items: center; gap: 10px; padding: 12px 18px; border-bottom: 1px solid var(--border); font-size: 13px; }
  .badge { padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .badge.idle { background: #2a3140; color: var(--muted); }
  .badge.running { background: rgba(210,153,34,.15); color: var(--run); }
  .badge.completed { background: rgba(63,185,80,.15); color: var(--ok); }
  .badge.error { background: rgba(248,81,73,.15); color: var(--err); }
  #log { font-family: "Cascadia Code", Consolas, monospace; font-size: 12px; line-height: 1.5; padding: 14px 18px;
    height: 60vh; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }
  #log .line { color: var(--text); }
  .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: var(--panel2);
    border: 1px solid var(--border); color: var(--text); padding: 10px 18px; border-radius: 8px; opacity: 0;
    transition: opacity .25s; pointer-events: none; }
  .toast.show { opacity: 1; }
</style>
</head>
<body>
<header>
  <span class="dot"></span>
  <h1>Brainstorm InvokeAI &mdash; Control Panel</h1>
</header>
<div class="layout">
  <div class="card">
    <h2>Configuration</h2>
    <div class="card-body" id="form"></div>
  </div>
  <div class="card">
    <h2>Run Status</h2>
    <div class="actions">
      <button class="btn-save" id="saveBtn">Save</button>
      <button class="btn-run" id="runBtn">Save &amp; Run Brainstorm</button>
    </div>
    <div class="status-bar">
      <span id="badge" class="badge idle">idle</span>
      <span id="elapsed" class="muted"></span>
    </div>
    <div id="log"></div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
let schema = [];
let polling = null;
let logCount = 0;

async function init() {
  schema = await (await fetch('/api/schema')).json();
  const cfg = await (await fetch('/api/config')).json();
  buildForm(schema, cfg);
  document.getElementById('saveBtn').onclick = () => save(false);
  document.getElementById('runBtn').onclick = () => save(true);
  pollStatus();
}

function buildForm(fields, cfg) {
  const form = document.getElementById('form');
  form.innerHTML = '';
  for (const f of fields) {
    if (f.section) {
      const head = document.createElement('div');
      head.className = 'section-head';
      head.textContent = f.section;
      form.appendChild(head);
    }
    const wrap = document.createElement('div');
    wrap.className = 'field';
    const val = cfg[f.key];
    if (f.type === 'checkbox') {
      wrap.innerHTML = `<div class="switch"><input type="checkbox" id="f_${f.key}" ${val ? 'checked' : ''}>
        <label for="f_${f.key}" style="margin:0">${f.label}</label></div>`;
    } else {
      const safe = (val === null || val === undefined) ? '' : String(val);
      let input;
      if (f.type === 'textarea') {
        input = `<textarea id="f_${f.key}">${escapeHtml(safe)}</textarea>`;
      } else if (f.type === 'number') {
        input = `<input type="number" id="f_${f.key}" value="${escapeHtml(safe)}" ${f.step ? `step="${f.step}"` : ''}>`;
      } else {
        input = `<input type="text" id="f_${f.key}" value="${escapeHtml(safe)}">`;
      }
      wrap.innerHTML = `<label for="f_${f.key}">${f.label}</label>${input}`;
    }
    if (f.help) {
      const h = document.createElement('div');
      h.className = 'help';
      h.textContent = f.help;
      wrap.appendChild(h);
    }
    form.appendChild(wrap);
  }
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function collect() {
  const data = {};
  for (const f of schema) {
    const el = document.getElementById('f_' + f.key);
    data[f.key] = f.type === 'checkbox' ? el.checked : el.value;
  }
  return data;
}

async function save(thenRun) {
  const endpoint = thenRun ? '/api/run' : '/api/config';
  const res = await fetch(endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(collect())
  });
  const out = await res.json();
  if (!res.ok || out.error) { toast(out.error || 'Request failed'); return; }
  toast(thenRun ? 'Saved — benchmark started' : 'Configuration saved');
  if (thenRun) { logCount = 0; document.getElementById('log').innerHTML = ''; pollStatus(); }
}

async function pollStatus() {
  if (polling) clearInterval(polling);
  const tick = async () => {
    const res = await fetch('/api/status?since=' + logCount);
    const s = await res.json();
    const log = document.getElementById('log');
    for (const line of s.lines) {
      const div = document.createElement('div');
      div.className = 'line';
      div.textContent = line;
      log.appendChild(div);
    }
    if (s.lines.length) log.scrollTop = log.scrollHeight;
    logCount = s.total_lines;
    const badge = document.getElementById('badge');
    badge.className = 'badge ' + s.state;
    badge.textContent = s.state;
    document.getElementById('elapsed').textContent = s.started_at ? Math.round(s.elapsed) + 's' : '';
    document.getElementById('runBtn').disabled = (s.state === 'running');
    if (s.state !== 'running') { clearInterval(polling); polling = null; }
  };
  await tick();
  if (!polling) polling = setInterval(tick, 1000);
}

let toastTimer = null;
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
}

init();
</script>
</body>
</html>"""


def _make_handler(server):
    """Builds an HTTP request handler bound to a BrainstormServer instance."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Silence default per-request console logging

        def _send_json(self, payload, status=200):
            body = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get('Content-Length', 0))
            if not length:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode('utf-8'))

        def do_GET(self):
            route = urlparse(self.path)
            if route.path == '/':
                body = _PAGE_HTML.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif route.path == '/api/schema':
                self._send_json(CONFIG_FIELDS)
            elif route.path == '/api/config':
                self._send_json(load_config(server.config_file))
            elif route.path == '/api/status':
                since = int(parse_qs(route.query).get('since', [0])[0])
                self._send_json(server.status.snapshot(since=since))
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self):
            route = urlparse(self.path)
            try:
                data = self._read_json()
            except (ValueError, json.JSONDecodeError):
                self._send_json({"error": "invalid JSON body"}, status=400)
                return

            if route.path == '/api/config':
                save_config(server.config_file, data)
                self._send_json({"ok": True})
            elif route.path == '/api/run':
                save_config(server.config_file, data)
                if server.start_run():
                    self._send_json({"ok": True, "started": True})
                else:
                    self._send_json({"error": "A benchmark is already running"}, status=409)
            else:
                self._send_json({"error": "not found"}, status=404)

    return Handler


def run_server(config_file, host="127.0.0.1", port=7865, open_browser=True):
    """Starts the local web UI server for editing config and running benchmarks."""
    server = BrainstormServer(config_file, host, port)
    httpd = ThreadingHTTPServer((host, port), _make_handler(server))
    url = f"http://{host}:{port}"
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Brainstorm InvokeAI web server running{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"  URL:    {Fore.GREEN}{url}{Style.RESET_ALL}")
    print(f"  Config: {config_file}")
    print(f"  Press Ctrl+C to stop.\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Server stopped.{Style.RESET_ALL}")
    finally:
        httpd.server_close()


def main():
    """Parses CLI arguments and dispatches to CLI benchmark or web server mode."""
    parser = argparse.ArgumentParser(description="Benchmark InvokeAI models with a test prompt")
    parser.add_argument(
        "--server",
        action="store_true",
        help="Launch the web UI to edit config and run benchmarks from the browser"
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host for --server mode")
    parser.add_argument("--port", type=int, default=None, help="Port for --server mode (overrides server_port in config)")
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

    # Load configuration and merge CLI overrides before running the benchmark
    config = load_config(CONFIG_FILE)

    # Autostart applies only when no benchmark-specific CLI arguments were given
    no_benchmark_args = not any([
        args.prompt, args.max_models is not None, args.base_filter,
        args.iterations is not None, args.output
    ])
    start_server = args.server or (config.get('server_autostart', False) and no_benchmark_args)

    if start_server:
        port = args.port if args.port is not None else config.get('server_port', 7865)
        open_browser = config.get('server_open_browser', True)
        run_server(CONFIG_FILE, host=args.host, port=port, open_browser=open_browser)
        return

    if args.prompt:
        config['default_prompt'] = args.prompt
    if args.max_models is not None:
        config['max_models'] = args.max_models
    if args.base_filter:
        config['base_filter'] = args.base_filter
    if args.iterations is not None:
        config['iterations'] = args.iterations

    execute_benchmark(config, output_file=args.output)


if __name__ == "__main__":
    main()
