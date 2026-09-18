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
from pipeline.comfy_client import ComfyUIClient, load_workflow_file
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
            return load_workflow_file(path)

    raise FileNotFoundError(f"No valid workflow_api.json found. Checked paths: {candidates}")


def render_block(
    image_client: BaseImageClient,
    project_dir: str,
    block: Dict[str, Any],
    workflow_name: str = "sdxl_base.json",
    workflow_slug: Optional[str] = None
) -> None:
    """Renders a single manifest block into a workflow-specific image directory."""
    cid = block["chunk_id"]
    illus = block["illustration"]
    prompt = illus.get("prompt", "")
    neg_prompt = illus.get("negative_prompt", "")
    width = illus.get("width", 1344)
    height = illus.get("height", 768)
    seed = illus.get("seed", random.randint(1, 1125899906842624))

    # Persist seed
    illus["seed"] = seed

    if not workflow_slug:
        workflow_slug = os.path.splitext(os.path.basename(workflow_name))[0]

    output_dir = os.path.join(project_dir, "images", workflow_slug)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{cid}.png")
    rel_img_path = f"images/{workflow_slug}/{cid}.png"

    print(f"\n[*] Rendering {cid} [{workflow_name}] ({width}x{height}, seed={seed}) ...")
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
    illus["image_file"] = rel_img_path
    illus["workflow"] = workflow_name

    # Preserve in multi-workflow map
    if "illustrations" not in block or not isinstance(block["illustrations"], dict):
        block["illustrations"] = {}
    block["illustrations"][workflow_name] = dict(illus)
    if workflow_slug != workflow_name:
        block["illustrations"][workflow_slug] = dict(illus)

    print(f"[+] Rendered {cid} -> {output_path} ({res.get('bytes_length', 0)} bytes)")


def run_phase_2(
    project_dir: str,
    workflow_path: Optional[str] = None,
    rerun_chunk_id: Optional[str] = None,
    rerun_chunk_ids: Optional[List[str]] = None,
    force_all: bool = False,
    host: Optional[str] = None,
    backend: Optional[str] = None,
    image_api_base: Optional[str] = None,
    image_api_key: Optional[str] = None,
    image_model: Optional[str] = None,
    workflow: Optional[str] = None
) -> Dict[str, Any]:
    """Executes Phase 2 diffusion batch or targeted rerun with non-destructive multi-workflow image sets."""
    print_banner()

    effective_workflow_path = workflow_path or workflow
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

    # Determine workflow identity
    if effective_workflow_path:
        workflow_name = os.path.basename(effective_workflow_path)
    else:
        workflow_name = img_config.get("comfyui", {}).get("workflow", "sdxl_base.json")
    workflow_slug = os.path.splitext(workflow_name)[0]

    active_backend = img_config.get("backend", "comfyui").lower()
    workflow_graph = None
    if active_backend == "comfyui":
        workflow_graph = resolve_workflow(project_dir, effective_workflow_path)

    image_client = create_image_client(
        config=img_config,
        workflow=workflow_graph,
        workflow_path=effective_workflow_path,
        host=host
    )
    check_runtime_readiness(image_client)

    blocks = manifest.get("blocks", [])
    manifest["active_workflow"] = workflow_name

    # Synchronize multi-workflow illustrations map in each block
    for b in blocks:
        if b.get("illustration") is not None:
            if "illustrations" not in b or not isinstance(b["illustrations"], dict):
                b["illustrations"] = {}
                legacy_wf = b["illustration"].get("workflow") or "sdxl_base.json"
                b["illustrations"][legacy_wf] = dict(b["illustration"])
            if workflow_name not in b["illustrations"] and workflow_slug not in b["illustrations"]:
                new_illus = dict(b["illustration"])
                new_illus["status"] = "pending"
                new_illus["seed"] = random.randint(1, 1125899906842624)
                new_illus["image_file"] = f"images/{workflow_slug}/{b['chunk_id']}.png"
                new_illus["workflow"] = workflow_name
                b["illustrations"][workflow_name] = new_illus
                if workflow_slug != workflow_name:
                    b["illustrations"][workflow_slug] = new_illus
            elif workflow_name not in b["illustrations"] and workflow_slug in b["illustrations"]:
                b["illustrations"][workflow_name] = b["illustrations"][workflow_slug]
            elif workflow_slug not in b["illustrations"] and workflow_name in b["illustrations"]:
                b["illustrations"][workflow_slug] = b["illustrations"][workflow_name]
            b["illustration"] = b["illustrations"][workflow_name]

    # Process rerun targets / mass selection
    target_cids = set()
    if rerun_chunk_id:
        target_cids.add(rerun_chunk_id)
    if rerun_chunk_ids:
        target_cids.update(rerun_chunk_ids)

    if force_all:
        print(f"[*] Force re-render requested for all illustrations with workflow '{workflow_name}'.")
        for b in blocks:
            if b.get("illustration"):
                b["illustrations"][workflow_name]["status"] = "pending"
                b["illustrations"][workflow_name]["seed"] = random.randint(1, 1125899906842624)
                b["illustration"] = b["illustrations"][workflow_name]
    elif target_cids:
        print(f"[*] Targeted rerun requested for chunks: {sorted(target_cids)} with workflow '{workflow_name}'.")
        for b in blocks:
            cid = b.get("chunk_id")
            if cid in target_cids and b.get("illustration"):
                b["illustrations"][workflow_name]["status"] = "pending"
                b["illustrations"][workflow_name]["seed"] = random.randint(1, 1125899906842624)
                b["illustration"] = b["illustrations"][workflow_name]
                # Only delete the file for this workflow, preserving other workflow outputs
                wf_img = os.path.join(project_dir, "images", workflow_slug, f"{cid}.png")
                if os.path.isfile(wf_img):
                    try:
                        os.remove(wf_img)
                        print(f"[*] Removed existing image for {cid} [{workflow_name}]")
                    except Exception as e:
                        print(f"[!] Warning: could not delete {wf_img}: {e}")

    # Identify pending blocks for this specific workflow
    pending_blocks = [
        b for b in blocks
        if b.get("illustrations", {}).get(workflow_name, {}).get("status") == "pending"
    ]

    total_illus = sum(1 for b in blocks if b.get("illustration") is not None)
    completed_before = total_illus - len(pending_blocks)

    print(f"[*] Manifest status for '{workflow_name}': {total_illus} total illustration(s). {completed_before} completed, {len(pending_blocks)} pending.")

    if not pending_blocks:
        print(f"[+] All illustrations for workflow '{workflow_name}' are already completed! Nothing to render.")
        save_manifest_atomic(manifest_path, manifest)
        return manifest

    for idx, block in enumerate(pending_blocks, 1):
        cid = block["chunk_id"]
        print(f"\n--- Processing {idx}/{len(pending_blocks)}: {cid} [{workflow_name}] ---")
        try:
            # Ensure block['illustration'] is pointing to this workflow
            block["illustration"] = block["illustrations"][workflow_name]
            render_block(image_client, project_dir, block, workflow_name=workflow_name, workflow_slug=workflow_slug)
            save_manifest_atomic(manifest_path, manifest)
        except Exception as err:
            print(f"[ERROR] Rendering failed for {cid}: {err}")
            raise

    print(f"\n[+] Phase 2 diffusion batch for '{workflow_name}' completed successfully! All images saved to {os.path.join(project_dir, 'images', workflow_slug)}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Phase 2: Backend-Agnostic Headless Illustration Rendering")
    parser.add_argument("--project", "-p", required=True, help="Path to project directory (e.g. ./projects/my_story)")
    parser.add_argument("--workflow", "-w", help="Optional path to workflow_api.json (for ComfyUI)")
    parser.add_argument("--rerun", "-r", help="Single chunk ID to rerun (e.g. chunk_004)")
    parser.add_argument("--rerun-chunks", nargs="+", help="List of chunk IDs to mass rerun (e.g. chunk_001 chunk_003)")
    parser.add_argument("--force-all", action="store_true", help="Force re-render all illustrations for this workflow")
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
        rerun_chunk_ids=args.rerun_chunks,
        force_all=args.force_all,
        host=args.host,
        backend=args.backend,
        image_api_base=args.image_api_base,
        image_api_key=args.image_api_key,
        image_model=args.image_model
    )


if __name__ == "__main__":
    main()

