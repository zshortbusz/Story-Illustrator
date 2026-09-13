"""
pipeline/render_images.py: Phase 2 Batch Dispatcher for Headless Diffusion Rendering.
Reads manifest.json, injects prompts/dimensions into ComfyUI workflow,
streams rendering over WebSocket, downloads generated images to ./images/{chunk_id}.png,
and performs atomic manifest updates. Supports --rerun {chunk_id}.
"""

import os
import json
import random
import argparse
from typing import Dict, Any, Optional, List
from pipeline.comfy_client import ComfyUIClient
from pipeline.image_client import BaseImageClient, create_image_client


def print_banner():
    print("""
================================================================================
PHASE 2: Headless Diffusion Rendering
  Runtime: Agnostic (Default: ComfyUI @ http://127.0.0.1:8188 | Remote API)
  State: Free local GPU VRAM if running local diffusion models
  Workflow: Reads manifest.json -> renders illustrations -> updates manifest.json
  Output: ./images/*.png + manifest.json updated with "status": "completed"
================================================================================
""")


def load_image_config(project_dir: str) -> Dict[str, Any]:
    """Loads diffusion_profiles.json to retrieve image backend and settings."""
    cfg_path = os.path.join(project_dir, "config", "diffusion_profiles.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def check_runtime_readiness(image_client: BaseImageClient):
    """Verifies image client connectivity and issues reminder about LM Studio if running locally."""
    import requests
    health = image_client.check_health()
    if not health.get("online"):
        raise RuntimeError(
            f"Image Generation Backend ({health.get('backend', 'unknown')}) is NOT reachable!\n"
            f"Details: {health.get('message', 'Server offline')}"
        )

    # If ComfyUI is the active backend, check if LM Studio is still holding memory
    if health.get("backend") == "comfyui":
        try:
            resp = requests.get("http://localhost:1234/v1/models", timeout=1)
            if resp.status_code == 200:
                print("\n[WARNING] LM Studio was detected active at http://localhost:1234.")
                print("[WARNING] To prevent GPU Out-of-Memory (OOM) errors during local diffusion, please UNLOAD your LLM or CLOSE LM Studio.\n")
        except Exception:
            pass


def save_manifest_atomic(manifest_path: str, manifest_data: Dict[str, Any]):
    """Atomically writes manifest to avoid corrupting state on interruption."""
    temp_path = f"{manifest_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)
    # Atomic replace
    os.replace(temp_path, manifest_path)


def resolve_workflow(project_dir: str, explicit_workflow: Optional[str] = None) -> Dict[str, Any]:
    """Loads specified workflow or falls back to project config or global defaults."""
    candidates = []
    if explicit_workflow:
        candidates.append(explicit_workflow)

    candidates.append(os.path.join(project_dir, "config", "workflow_api.json"))
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), "workflows", "sdxl_base.json"))

    for path in candidates:
        if path and os.path.isfile(path):
            print(f"[*] Using ComfyUI workflow: {path}")
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    raise FileNotFoundError(f"No valid workflow_api.json found. Checked paths: {candidates}")


def render_block(
    image_client: BaseImageClient,
    project_dir: str,
    block: Dict[str, Any]
) -> None:
    """Renders a single manifest block."""
    cid = block["chunk_id"]
    illus = block["illustration"]
    prompt = illus.get("prompt", "")
    neg_prompt = illus.get("negative_prompt", "")
    width = illus.get("width", 1344)
    height = illus.get("height", 768)
    seed = illus.get("seed", random.randint(1, 1125899906842624))

    # Persist seed
    illus["seed"] = seed

    output_path = os.path.join(project_dir, "images", f"{cid}.png")

    print(f"\n[*] Rendering {cid} ({width}x{height}, seed={seed}) ...")
    print(f"    Prompt: {prompt[:80]}...")

    res = image_client.render(
        prompt=prompt,
        negative_prompt=neg_prompt,
        width=width,
        height=height,
        seed=seed,
        output_filepath=output_path
    )

    illus["status"] = "completed"
    illus["image_file"] = f"images/{cid}.png"
    print(f"[+] Rendered {cid} -> {output_path} ({res.get('bytes_length', 0)} bytes)")


def run_phase_2(
    project_dir: str,
    workflow_path: Optional[str] = None,
    rerun_chunk_id: Optional[str] = None,
    host: Optional[str] = None,
    backend: Optional[str] = None,
    image_api_base: Optional[str] = None,
    image_api_key: Optional[str] = None,
    image_model: Optional[str] = None
) -> Dict[str, Any]:
    """Executes Phase 2 diffusion batch or single-chunk rerun with backend-agnostic support."""
    print_banner()

    manifest_path = os.path.join(project_dir, "artifacts", "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"Missing {manifest_path}. Please run Phase 1 first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    img_config = load_image_config(project_dir)
    if backend:
        img_config["backend"] = backend
    if host:
        img_config.setdefault("comfyui", {})["host"] = host
    if image_api_base:
        img_config.setdefault("openai_compatible", {})["api_base"] = image_api_base
    if image_api_key:
        img_config.setdefault("openai_compatible", {})["api_key"] = image_api_key
    if image_model:
        img_config.setdefault("openai_compatible", {})["model"] = image_model

    active_backend = img_config.get("backend", "comfyui").lower()
    workflow = None
    if active_backend == "comfyui":
        workflow = resolve_workflow(project_dir, workflow_path)

    image_client = create_image_client(
        config=img_config,
        workflow=workflow,
        workflow_path=workflow_path,
        host=host
    )
    check_runtime_readiness(image_client)

    blocks = manifest.get("blocks", [])

    # Handle single image rerun
    if rerun_chunk_id:
        target_block = None
        for b in blocks:
            if b.get("chunk_id") == rerun_chunk_id:
                target_block = b
                break

        if not target_block:
            raise ValueError(f"Chunk ID '{rerun_chunk_id}' not found in manifest.")
        if target_block.get("illustration") is None:
            raise ValueError(f"Chunk '{rerun_chunk_id}' has no illustration defined.")

        print(f"[*] Rerunning single illustration for {rerun_chunk_id} ...")
        # Remove old image file
        old_image = os.path.join(project_dir, "images", f"{rerun_chunk_id}.png")
        if os.path.isfile(old_image):
            try:
                os.remove(old_image)
                print(f"[*] Deleted prior image {old_image}")
            except Exception as e:
                print(f"[!] Warning: could not delete {old_image}: {e}")

        # Set status pending & generate fresh seed
        target_block["illustration"]["status"] = "pending"
        target_block["illustration"]["seed"] = random.randint(1, 1125899906842624)

        render_block(image_client, project_dir, target_block)
        save_manifest_atomic(manifest_path, manifest)
        print(f"[+] Successfully rerendered {rerun_chunk_id} and updated manifest.")
        return manifest

    # Normal batch execution
    pending_blocks = [
        b for b in blocks
        if b.get("illustration") is not None and b["illustration"].get("status") == "pending"
    ]

    total_illus = sum(1 for b in blocks if b.get("illustration") is not None)
    completed_before = total_illus - len(pending_blocks)

    print(f"[*] Manifest status: {total_illus} total illustration(s). {completed_before} completed, {len(pending_blocks)} pending.")

    if not pending_blocks:
        print("[+] All illustrations are already completed! Nothing to render.")
        return manifest

    for idx, block in enumerate(pending_blocks, 1):
        cid = block["chunk_id"]
        print(f"\n--- Processing {idx}/{len(pending_blocks)}: {cid} ---")
        try:
            render_block(image_client, project_dir, block)
            # Atomic save after every single render
            save_manifest_atomic(manifest_path, manifest)
        except Exception as err:
            print(f"[ERROR] Rendering failed for {cid}: {err}")
            # Do not re-raise immediately; continue or allow user to rerun
            raise

    print(f"\n[+] Phase 2 diffusion batch completed successfully! All images saved to {os.path.join(project_dir, 'images')}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Phase 2: Backend-Agnostic Headless Illustration Rendering")
    parser.add_argument("--project", "-p", required=True, help="Path to project directory (e.g. ./projects/my_story)")
    parser.add_argument("--workflow", "-w", help="Optional path to workflow_api.json (for ComfyUI)")
    parser.add_argument("--rerun", "-r", help="Chunk ID to rerun (e.g. chunk_004)")
    parser.add_argument("--host", default=None, help="ComfyUI host (default: 127.0.0.1:8188)")
    parser.add_argument("--backend", choices=["comfyui", "openai_compatible"], help="Image backend (default: from config or comfyui)")
    parser.add_argument("--image-api-base", help="OpenAI-compatible image API base URL")
    parser.add_argument("--image-api-key", help="API key for image generation endpoint")
    parser.add_argument("--image-model", help="Image model name (e.g. dall-e-3, FLUX.1-schnell)")
    args = parser.parse_args()

    run_phase_2(
        project_dir=args.project,
        workflow_path=args.workflow,
        rerun_chunk_id=args.rerun,
        host=args.host,
        backend=args.backend,
        image_api_base=args.image_api_base,
        image_api_key=args.image_api_key,
        image_model=args.image_model
    )


if __name__ == "__main__":
    main()
