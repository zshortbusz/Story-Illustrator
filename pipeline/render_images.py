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


def print_banner():
    print("""
================================================================================
PHASE 2: Headless Diffusion Rendering
  Runtime: ComfyUI (API Mode @ http://127.0.0.1:8188)
  State: LM Studio CLOSED / UNLOADED (To free GPU VRAM for diffusion)
  Workflow: WebSocket queue runner reads manifest.json -> renders images
  Output: ./images/*.png + manifest.json updated with "status": "completed"
================================================================================
""")


def check_runtime_readiness(comfy_client: ComfyUIClient):
    """Verifies ComfyUI connectivity and issues reminder about LM Studio."""
    import requests
    health = comfy_client.check_health()
    if not health.get("online"):
        raise RuntimeError(
            f"ComfyUI is NOT reachable at {comfy_client.http_base}!\n"
            "Please launch ComfyUI (API Mode @ http://127.0.0.1:8188) before starting Phase 2."
        )

    # Check if LM Studio is still holding memory
    try:
        resp = requests.get("http://localhost:1234/v1/models", timeout=1)
        if resp.status_code == 200:
            print("\n[WARNING] LM Studio was detected active at http://localhost:1234.")
            print("[WARNING] To prevent GPU Out-of-Memory (OOM) errors during diffusion, please UNLOAD your LLM or CLOSE LM Studio.\n")
    except Exception:
        # LM Studio is closed as desired
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
    client: ComfyUIClient,
    workflow: Dict[str, Any],
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

    res = client.render(
        workflow=workflow,
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
    host: str = "127.0.0.1:8188"
) -> Dict[str, Any]:
    """Executes Phase 2 diffusion batch or single-chunk rerun."""
    print_banner()

    manifest_path = os.path.join(project_dir, "artifacts", "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"Missing {manifest_path}. Please run Phase 1 first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    client = ComfyUIClient(host=host)
    check_runtime_readiness(client)
    workflow = resolve_workflow(project_dir, workflow_path)

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

        render_block(client, workflow, project_dir, target_block)
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
            render_block(client, workflow, project_dir, block)
            # Atomic save after every single render
            save_manifest_atomic(manifest_path, manifest)
        except Exception as err:
            print(f"[ERROR] Rendering failed for {cid}: {err}")
            # Do not re-raise immediately; continue or allow user to rerun
            raise

    print(f"\n[+] Phase 2 diffusion batch completed successfully! All images saved to {os.path.join(project_dir, 'images')}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Phase 2: Headless Diffusion Batch via ComfyUI")
    parser.add_argument("--project", "-p", required=True, help="Path to project directory (e.g. ./projects/my_story)")
    parser.add_argument("--workflow", "-w", help="Optional path to workflow_api.json to use")
    parser.add_argument("--rerun", "-r", help="Chunk ID to rerun (e.g. chunk_004)")
    parser.add_argument("--host", default="127.0.0.1:8188", help="ComfyUI host (default: 127.0.0.1:8188)")
    args = parser.parse_args()

    run_phase_2(
        project_dir=args.project,
        workflow_path=args.workflow,
        rerun_chunk_id=args.rerun,
        host=args.host
    )


if __name__ == "__main__":
    main()
