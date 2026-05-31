import os
import json
import glob
import colorama
import requests
import time
import argparse
import random
from colorama import Fore, Style
import yaml
from plyer import notification
import traceback

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.yaml")

# --- CONFIGURATION ---

def load_config(config_path):
    """Loads configuration from a YAML file."""
    print(f">> Loading configuration from {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def extract_transcript(file_path):
    """Parses an LM Studio JSON and returns a text transcript."""
    try:
        print(f">> Reading {file_path}")
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # LM Studio structure usually puts messages in a list
            messages = data.get('messages', [])
            transcript = ""
            for msg in messages:
                message_text = ""
                versions = msg.get('versions', []) 
                version = versions[0] if versions else {}
                steps = version.get('steps', []) if version else []
                if steps and steps[0].get('content', []):
                    steps = version.get('steps', [])
                    content = steps[0].get('content', [])
                    message_text = content[0].get('text', '')  
                else: 
                    content = version.get('content', [])
                    message_text = content[0].get('text', '') 

                
                if message_text != "":
                    transcript += f"{message_text}\n" 

            # print(f"Extracted transcript:\n{transcript}")
            return transcript
    except Exception as e:
        print(f"{Fore.RED}❌ Error reading {file_path}: {e}{Style.RESET_ALL}")
        traceback.print_exc()
        return None

def get_lm_studio_loaded_model(api_url):
    """Returns the key of the first loaded LLM from the LM Studio models list."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(api_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        response = requests.get(f"{base_url}/api/v1/models")
        if response.status_code != 200:
            return None
        for m in response.json().get('models', []):
            if m.get('type') == 'llm' and m.get('loaded_instances'):
                return m['key']
    except Exception as e:
        print(f"{Fore.RED}❌ Could not detect loaded LM Studio model: {e}{Style.RESET_ALL}")
    return None

def get_visual_summary(transcript, api_url, lm_model, system_prompt=None, user_prompt=None):
    """Uses LM Studio to turn a long chat into a single image prompt."""
    print(" -> Analyzing conversation for visual themes...")

    # LM Studio 0.4.0+ native REST API (/api/v1/chat) uses a different format
    # than the legacy OpenAI-compatible endpoint (/v1/chat/completions)
    if '/api/v1/chat' in api_url:
        payload = {
            "model": lm_model,
            "input": f"{user_prompt}:\n\n{transcript[:4000]}",
            "system_prompt": system_prompt,
            "temperature": 0.3
        }
        response = requests.post(api_url, json=payload)
        data = response.json()
        for item in data.get('output', []):
            if item.get('type') == 'message':
                return item['content'].strip()
        print(f"{Fore.RED}❌ Unexpected LM Studio response: {data}{Style.RESET_ALL}")
        return None
    else:
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {"role": "user", "content": f"{user_prompt}:\n\n{transcript[:4000]}"}
            ],
            "temperature": 0.3
        }
        response = requests.post(api_url, json=payload)
        return response.json()['choices'][0]['message']['content'].strip()

def get_model_info(target_name, api_url):
    """Fetches the unique key/hash identifier for a model from Invoke AI."""
    print(f" -> Looking up model info for: {target_name}")
    try:
        response = requests.get(f"{api_url}/models/")
        if response.status_code != 200:
            return None
        
        models = response.json().get('models', [])
        for m in models:
            if m.get('name') == target_name:
                # We extract the 5 keys the error log specifically requested
                # We also ensure 'base' and 'type' are lowercase as per the Enum error
                model_id = {
                    "key": m.get('key'),
                    "hash": m.get('hash'),
                    "name": m.get('name'),
                    "base": (m.get('base') or m.get('base_model', 'unknown')).lower(),
                    "type": (m.get('type') or m.get('model_type', 'main')).lower()
                }
                
                # Validation: Ensure no required fields are None
                if all(model_id.values()):
                    print(f" ✅ Found Model: {target_name} (Base: {model_id['base']})")
                    return model_id
                else:
                    print(f"{Fore.YELLOW} ⚠️ Model found but some fields are missing: {model_id}{Style.RESET_ALL}")

        print(f"{Fore.RED}❌ Model '{target_name}' not found in your Invoke AI library.{Style.RESET_ALL}")
        return None
    
    except Exception as e:
        print(f"Error querying Model Manager: {e}")
        return None

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
    """Submits a modular graph to Invoke AI to avoid union_tag_invalid errors."""
    seed = random.randint(0, 2**32 - 1)
    invoke_ai_api = cfg_params.get('invoke_ai_api')
    invoke_ai_api_v2 = cfg_params.get('invoke_ai_api_v2')
    pos_prompt  = cfg_params.get('positive_prompt')
    neg_prompt  = cfg_params.get('negative_prompt')
    width       = cfg_params.get('width')
    height      = cfg_params.get('height')
    steps       = cfg_params.get('steps')
    cfg         = cfg_params.get('cfg_scale')
    scheduler   = cfg_params.get('scheduler')

    prompt = prompt if pos_prompt is None else f"{prompt}, {pos_prompt}"

    nodes = {
        "loader": {"id": "loader", "type": "sdxl_model_loader", "model": model_info},
        "pos": {"id": "pos", "type": "sdxl_compel_prompt", "prompt": prompt, "style": prompt},
        "neg": {"id": "neg", "type": "sdxl_compel_prompt", "prompt": neg_prompt, "style": neg_prompt},
        "noise": {"id": "noise", "type": "noise", "width": width, "height": height, "seed": seed},
        "denoise": {"id": "denoise", "type": "denoise_latents", "steps": steps, "cfg_scale": cfg, "scheduler": scheduler},

        # --- POPULATE METADATA DIRECTLY ---
        "metadata": {
            "id": "metadata",
            "type": "core_metadata",
            "positive_prompt": prompt,
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

    # When vae_info is supplied, add an explicit vae_loader node to override
    # the model's bundled VAE. This fixes black images caused by fp16 VAE overflow
    # in many SDXL fine-tunes — the model's fp16 VAE produces NaNs/overflow during
    # latent decode, while a separate fp32-safe VAE (e.g. sdxl-vae-fp16-fix) does not.
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

            # Connect UNet and VAE (VAE source depends on whether an override is active)
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
    # Use the /queue/default/enqueue_batch endpoint for v5/v6
    res = requests.post(f"{invoke_ai_api}/queue/default/enqueue_batch", json=payload)
    
    if res.status_code in [200, 201]:
        batch_id = res.json()['batch']['batch_id']
        print(f"{Fore.GREEN} 🚀 Job Enqueued! Batch: {batch_id}{Style.RESET_ALL}")
        return batch_id
    else:
        print(f"{Fore.RED}❌ Failed: {res.text}{Style.RESET_ALL}")
        return None

def monitor_queue(batch_ids, api_url):
    """Polls the Invoke AI Queue API to track batch completion status."""
    pending_batches = list(batch_ids)
    print(f"\n[Monitor] Tracking {len(pending_batches)} batches...")

    while pending_batches:
        for b_id in pending_batches[:]:
            # The correct v6 endpoint for batch status
            url = f"{api_url}/queue/default/b/{b_id}/status"

            try:
                response = requests.get(url)
                if response.status_code == 200:
                    data = response.json()

                    completed = data.get('completed', 0)
                    total     = data.get('total', 0)
                    errors    = data.get('errors', 0)
                    canceled  = data.get('canceled', 0)

                    # Done when every item is accounted for (success, error, or canceled)
                    if completed + errors + canceled >= total:
                        print(f"{Fore.GREEN} ✅ Batch {b_id} finished "
                              f"({completed} success, {errors} errors, {canceled} canceled).{Style.RESET_ALL}")
                        pending_batches.remove(b_id)

                elif response.status_code == 404:
                    # Batch was deleted from the UI — treat it as done
                    print(f"{Fore.YELLOW} ⚠️ Batch {b_id} not found (deleted?). Skipping.{Style.RESET_ALL}")
                    pending_batches.remove(b_id)

                else:
                    print(f"{Fore.YELLOW} ⚠️ Could not get status for {b_id}: {response.status_code}{Style.RESET_ALL}")

            except Exception as e:
                print(f"{Fore.RED} ❌ Connection error during monitoring: {e}{Style.RESET_ALL}")

        if pending_batches:
            # We sleep to avoid spamming the local server
            time.sleep(5) 
    
    # Trigger Desktop Notification
    notification.notify(
        title="Invoke AI: Story Renders Complete",
        message=f"All {len(batch_ids)} stories have been processed.",
        app_name="AI Workflow",
        timeout=10
    )
    print("\n[!] All tasks complete. Check your gallery!")

def main(model_name):
    """Main workflow: process conversations and queue images."""
    config = load_config(CONFIG_FILE)

    # Override globals from config
    lm_studio_api   = config.get('lm_studio_api')
    invoke_ai_api   = config.get('invoke_ai_api')
    invoke_ai_api_v2 = config.get('invoke_ai_api_v2')
    system_prompt   = config.get('system_prompt')
    user_prompt     = config.get('user_prompt')
    convo_path      = os.path.join(config.get('home'), config.get('convo_subpath'))
    number_of_images = config.get('number_of_images', 1)
    number_of_prompt_variants = config.get('number_of_prompt_variants', 1)
    number_of_files  = config.get('number_of_files', 3)

    # Resolve LM Studio model: use config override or auto-detect from loaded models
    lm_studio_model = config.get('lm_studio_model') or get_lm_studio_loaded_model(lm_studio_api)
    if not lm_studio_model:
        print(f"{Fore.RED}❌ No LM Studio model found. Set 'lm_studio_model' in config.yaml or load a model in LM Studio.{Style.RESET_ALL}")
        return
    print(f" -> Using LM Studio model: {lm_studio_model}")

    # Use CLI model override or fall back to config list
    if model_name is not None:
        model_list = [model_name]
    else:
        default_model = config.get('default_model')
        if isinstance(default_model, list):
            model_list = default_model
        else:
            model_list = [default_model]

    cfg_params = {
        'invoke_ai_api': invoke_ai_api,
        'invoke_ai_api_v2': invoke_ai_api_v2,
        'negative_prompt': config.get('negative_prompt'),
        'width':           config.get('width'),
        'height':          config.get('height'),
        'steps':           config.get('steps'),
        'cfg_scale':       config.get('cfg_scale'),
        'scheduler':       config.get('scheduler'),
    }

    # Look up all model infos upfront
    model_infos = {}
    for name in model_list:
        info = get_model_info(name, invoke_ai_api_v2)
        if info:
            model_infos[name] = info
        else:
            print(f"{Fore.YELLOW}⚠️ Skipping model '{name}' (not found).{Style.RESET_ALL}")

    if not model_infos:
        print(f"{Fore.RED}No valid models found. Script aborted.{Style.RESET_ALL}")
        return

    # Look up VAE override (if configured)
    vae_override_name = config.get('vae_override', '').strip()
    vae_info = None
    if vae_override_name:
        vae_info = get_vae_info(vae_override_name, invoke_ai_api_v2)
        if not vae_info:
            print(f"{Fore.YELLOW}⚠️ Falling back to each model's bundled VAE.{Style.RESET_ALL}")

    json_files = glob.glob(convo_path)
    json_files = sorted(json_files, key=os.path.getmtime, reverse=True)[:number_of_files]
    print(f"Found {len(json_files)} conversations in LM Studio folder.")
    print(f"Using models: {list(model_infos.keys())}")

    session_ids = []

    for model_name_item, model_info in model_infos.items():
        print(f"\n{Fore.BLUE}=== Model: {model_name_item} ==={Style.RESET_ALL}")
 
        for file in json_files:
            print(f"\nProcessing: {os.path.basename(file)}")
            chat_text = extract_transcript(file)

            if chat_text and len(chat_text) > 100:
                for _ in range(number_of_prompt_variants):
                    img_prompt = get_visual_summary(chat_text, lm_studio_api, lm_studio_model, system_prompt, user_prompt)
                    if not img_prompt:
                        print(f"{Fore.YELLOW}⚠ Skipping: no prompt generated for this variant.{Style.RESET_ALL}")
                        continue
                    print(f"Generated Prompt: {img_prompt[:100]}...")

                    for _ in range(number_of_images):
                        sid = queue_to_invoke(img_prompt, model_info, cfg_params, vae_info)
                        session_ids.append(sid)
                        time.sleep(2)

        if session_ids:
            print(f"{Fore.GREEN}{len(session_ids)} jobs queued for model '{model_name_item}'.{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}No images were queued for model '{model_name_item}'.{Style.RESET_ALL}")

    if session_ids:
        print(f"\n{Fore.CYAN}Monitoring {len(session_ids)} jobs.{Style.RESET_ALL}")
        monitor_queue(session_ids, invoke_ai_api)
        notification.notify(title="Art Workflow", message=f"All images are ready!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert LM Studio conversations to Invoke AI images")
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name to use for image generation (overrides config.yaml)"
    )
    args = parser.parse_args()

    main(args.model)