"""
pipeline/web_server.py: Local REST API and WebUI server for Automated Story Illustrator (ASI).
Provides interactive inspection, editing, and execution endpoints for all three phases.
"""

import os
import json
import random
import threading
from typing import Dict, Any, List, Optional
from flask import Flask, request, jsonify, send_file, send_from_directory, render_template_string

from pipeline.project_manager import (
    get_base_dir,
    list_projects,
    init_project,
    DEFAULT_LLM_CONFIG,
    DEFAULT_DIFFUSION_PROFILES
)
from pipeline.llm_client import LMStudioClient, load_llm_config
from pipeline.comfy_client import ComfyUIClient
from pipeline.chunker import chunk_file
from pipeline.build_manifest import (
    run_stage_chunk,
    run_stage_beats,
    run_stage_bible,
    run_stage_manifest
)
from pipeline.render_images import run_phase_2, save_manifest_atomic, resolve_workflow
from pipeline.compile_html import compile_html, compile_manifest_to_html


def create_app() -> Flask:
    base_dir = get_base_dir()
    static_dir = os.path.join(base_dir, "pipeline", "web_static")

    app = Flask(__name__, static_folder=static_dir, static_url_path="/static")
    app.config["JSON_AS_ASCII"] = False

    # Job tracking for background stage runs
    jobs: Dict[str, Dict[str, Any]] = {}

    def get_project_dir(slug: str) -> str:
        pdir = os.path.join(base_dir, "projects", slug)
        if not os.path.isdir(pdir):
            raise FileNotFoundError(f"Project '{slug}' not found.")
        return pdir

    @app.route("/")
    def index():
        index_file = os.path.join(static_dir, "index.html")
        if os.path.isfile(index_file):
            return send_file(index_file)
        return "<h1>WebUI Static Files Missing</h1>", 404

    # -------------------------------------------------------------------------
    # System Status & Health Checks
    # -------------------------------------------------------------------------
    @app.route("/api/status", methods=["GET"])
    def get_status():
        llm_client = LMStudioClient()
        llm_health = llm_client.check_health()

        comfy_client = ComfyUIClient()
        comfy_health = comfy_client.check_health()

        return jsonify({
            "lm_studio": llm_health,
            "comfyui": comfy_health,
            "instructions": {
                "phase_1": "Phase 1 requires LM Studio running at :1234 with a model loaded. ComfyUI should be CLOSED to prevent VRAM competition.",
                "phase_2": "Phase 2 requires ComfyUI running at :8188. LM Studio should be UNLOADED / CLOSED to free VRAM for diffusion.",
                "phase_3": "Phase 3 is pure Python compilation. No GPU, LM Studio, or ComfyUI required."
            }
        })

    # -------------------------------------------------------------------------
    # Projects & Workflows
    # -------------------------------------------------------------------------
    @app.route("/api/projects", methods=["GET"])
    def list_all_projects():
        slugs = list_projects()
        results = []
        for s in slugs:
            pdir = os.path.join(base_dir, "projects", s)
            manifest_exists = os.path.isfile(os.path.join(pdir, "artifacts", "manifest.json"))
            chunks_exists = os.path.isfile(os.path.join(pdir, "artifacts", "01_chunks.json"))
            source_exists = os.path.isfile(os.path.join(pdir, "source", "input_story.txt"))
            images_dir = os.path.join(pdir, "images")
            img_count = len([f for f in os.listdir(images_dir) if f.endswith(".png")]) if os.path.isdir(images_dir) else 0

            results.append({
                "slug": s,
                "title": s.replace("_", " ").title(),
                "has_source": source_exists,
                "has_chunks": chunks_exists,
                "has_manifest": manifest_exists,
                "image_count": img_count
            })
        return jsonify(results)

    @app.route("/api/projects", methods=["POST"])
    def create_project():
        data = request.json or {}
        slug = data.get("slug", "").strip().lower().replace(" ", "_")
        if not slug:
            return jsonify({"error": "Story slug is required."}), 400
        story_text = data.get("story_text", "")
        wf_name = data.get("workflow", "sdxl_base.json")

        pdir = init_project(slug, input_text=story_text, workflow_name=wf_name)
        return jsonify({"success": True, "slug": slug, "path": pdir})

    @app.route("/api/workflows", methods=["GET"])
    def list_workflows():
        wf_dir = os.path.join(base_dir, "workflows")
        templates = []
        if os.path.isdir(wf_dir):
            for f in os.listdir(wf_dir):
                if f.endswith(".json"):
                    templates.append(f)
        return jsonify({"workflows": sorted(templates)})

    # -------------------------------------------------------------------------
    # Configuration endpoints
    # -------------------------------------------------------------------------
    @app.route("/api/project/<slug>/config/llm", methods=["GET"])
    def get_llm_config(slug):
        pdir = get_project_dir(slug)
        cfg_path = os.path.join(pdir, "config", "llm_models.json")
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        return jsonify(DEFAULT_LLM_CONFIG)

    @app.route("/api/project/<slug>/config/llm", methods=["POST"])
    def update_llm_config(slug):
        pdir = get_project_dir(slug)
        cfg_path = os.path.join(pdir, "config", "llm_models.json")
        data = request.json or {}
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"success": True})

    @app.route("/api/project/<slug>/config/diffusion", methods=["GET"])
    def get_diffusion_config(slug):
        pdir = get_project_dir(slug)
        cfg_path = os.path.join(pdir, "config", "diffusion_profiles.json")
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        return jsonify(DEFAULT_DIFFUSION_PROFILES)

    @app.route("/api/project/<slug>/config/diffusion", methods=["POST"])
    def update_diffusion_config(slug):
        pdir = get_project_dir(slug)
        cfg_path = os.path.join(pdir, "config", "diffusion_profiles.json")
        data = request.json or {}
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"success": True})

    # -------------------------------------------------------------------------
    # Artifacts & Source text
    # -------------------------------------------------------------------------
    @app.route("/api/project/<slug>/source", methods=["GET"])
    def get_source(slug):
        pdir = get_project_dir(slug)
        src_path = os.path.join(pdir, "source", "input_story.txt")
        if os.path.isfile(src_path):
            with open(src_path, "r", encoding="utf-8") as f:
                return jsonify({"text": f.read()})
        return jsonify({"text": ""})

    @app.route("/api/project/<slug>/source", methods=["POST"])
    def update_source(slug):
        pdir = get_project_dir(slug)
        src_path = os.path.join(pdir, "source", "input_story.txt")
        data = request.json or {}
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(data.get("text", ""))
        return jsonify({"success": True})

    @app.route("/api/project/<slug>/artifact/<name>", methods=["GET"])
    def get_artifact(slug, name):
        pdir = get_project_dir(slug)
        fname_map = {
            "chunks": "01_chunks.json",
            "beats": "02_selected_beats.json",
            "bible": "03_visual_bible.json",
            "manifest": "manifest.json"
        }
        filename = fname_map.get(name, f"{name}.json")
        path = os.path.join(pdir, "artifacts", filename)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        return jsonify({"error": f"Artifact {name} does not exist yet."}), 404

    @app.route("/api/project/<slug>/artifact/<name>", methods=["POST"])
    def update_artifact(slug, name):
        pdir = get_project_dir(slug)
        fname_map = {
            "chunks": "01_chunks.json",
            "beats": "02_selected_beats.json",
            "bible": "03_visual_bible.json",
            "manifest": "manifest.json"
        }
        filename = fname_map.get(name, f"{name}.json")
        path = os.path.join(pdir, "artifacts", filename)
        data = request.json
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"success": True})

    # Active stage tracking for live UI feedback
    stage_progress_map: Dict[str, Dict[str, Any]] = {}

    @app.route("/api/project/<slug>/stage_progress", methods=["GET"])
    def get_stage_progress(slug):
        return jsonify(stage_progress_map.get(slug, {"running": False, "message": "Idle"}))

    # -------------------------------------------------------------------------
    # Stage Runner & Image Generation
    # -------------------------------------------------------------------------
    @app.route("/api/project/<slug>/run_stage", methods=["POST"])
    def run_stage_endpoint(slug):
        pdir = get_project_dir(slug)
        data = request.json or {}
        stage = data.get("stage", "chunk")

        llm_cfg_path = os.path.join(pdir, "config", "llm_models.json")
        llm_cfg = load_llm_config(llm_cfg_path)
        client = LMStudioClient(api_base=llm_cfg.get("api_base", "http://localhost:1234/v1"))

        # Role mapping for stage model overrides
        role_map = {
            "bible": "structured_analyst",
            "beats": "narrative_director",
            "manifest": "prompt_synthesizer"
        }
        role = role_map.get(stage)
        if role and "roles" in llm_cfg and role in llm_cfg["roles"]:
            updated = False
            if data.get("model") and data["model"].strip():
                llm_cfg["roles"][role]["model"] = data["model"].strip()
                updated = True
            if data.get("temperature") is not None:
                try:
                    llm_cfg["roles"][role]["temperature"] = float(data["temperature"])
                    updated = True
                except (ValueError, TypeError):
                    pass
            if data.get("max_tokens"):
                try:
                    llm_cfg["roles"][role]["max_tokens"] = int(data["max_tokens"])
                    updated = True
                except (ValueError, TypeError):
                    pass
            if data.get("system_prompt"):
                llm_cfg["roles"][role]["system_prompt"] = data["system_prompt"].strip()
                updated = True
            if updated:
                try:
                    with open(llm_cfg_path, "w", encoding="utf-8") as f:
                        json.dump(llm_cfg, f, indent=2, ensure_ascii=False)
                except Exception as ex:
                    print(f"[!] Warning: failed to persist updated llm config: {ex}")

        def cb(msg: str):
            stage_progress_map[slug] = {
                "running": True,
                "stage": stage,
                "message": msg
            }

        try:
            chosen_model = client.resolve_model(llm_cfg.get("roles", {}).get(role, {}).get("model", "")) if role else ""
            cb(f"Starting {stage}" + (f" with model '{chosen_model}'" if chosen_model else "") + "...")
            if stage == "chunk":
                result = run_stage_chunk(pdir, callback=cb)
            elif stage == "bible":
                result = run_stage_bible(pdir, client, llm_cfg, callback=cb)
            elif stage == "beats":
                result = run_stage_beats(pdir, client, llm_cfg, callback=cb)
            elif stage == "manifest":
                result = run_stage_manifest(pdir, client, llm_cfg, callback=cb)
            elif stage == "all_phase_1":
                r_chunk = run_stage_chunk(pdir, callback=cb)
                r_bible = run_stage_bible(pdir, client, llm_cfg, callback=cb)
                r_beats = run_stage_beats(pdir, client, llm_cfg, callback=cb)
                r_manifest = run_stage_manifest(pdir, client, llm_cfg, callback=cb)
                result = {"chunks": r_chunk, "bible": r_bible, "beats": r_beats, "manifest": r_manifest}
            else:
                stage_progress_map[slug] = {"running": False, "message": f"Unknown stage: {stage}"}
                return jsonify({"error": f"Unknown stage: {stage}"}), 400

            stage_progress_map[slug] = {"running": False, "stage": stage, "message": "Completed successfully."}
            return jsonify({"success": True, "stage": stage, "result": result})
        except Exception as e:
            stage_progress_map[slug] = {"running": False, "stage": stage, "error": str(e), "message": f"Error: {str(e)}"}
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/project/<slug>/render", methods=["POST"])
    def run_render_endpoint(slug):
        pdir = get_project_dir(slug)
        data = request.json or {}
        workflow_name = data.get("workflow")
        wf_path = None
        if workflow_name:
            wf_path = os.path.join(base_dir, "workflows", workflow_name)

        try:
            manifest = run_phase_2(project_dir=pdir, workflow_path=wf_path)
            return jsonify({"success": True, "manifest": manifest})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/project/<slug>/rerun", methods=["POST"])
    def rerun_image_endpoint(slug):
        pdir = get_project_dir(slug)
        data = request.json or {}
        chunk_id = data.get("chunk_id")
        if not chunk_id:
            return jsonify({"error": "chunk_id is required."}), 400

        # If user tweaked prompt or negative prompt in UI, update manifest first!
        manifest_path = os.path.join(pdir, "artifacts", "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        for block in manifest.get("blocks", []):
            if block.get("chunk_id") == chunk_id and block.get("illustration"):
                if "prompt" in data and data["prompt"]:
                    block["illustration"]["prompt"] = data["prompt"]
                if "negative_prompt" in data and data["negative_prompt"] is not None:
                    block["illustration"]["negative_prompt"] = data["negative_prompt"]
                if "width" in data and data["width"]:
                    block["illustration"]["width"] = int(data["width"])
                if "height" in data and data["height"]:
                    block["illustration"]["height"] = int(data["height"])
                break

        save_manifest_atomic(manifest_path, manifest)

        workflow_name = data.get("workflow")
        wf_path = os.path.join(base_dir, "workflows", workflow_name) if workflow_name else None

        try:
            updated_manifest = run_phase_2(project_dir=pdir, workflow_path=wf_path, rerun_chunk_id=chunk_id)
            return jsonify({"success": True, "chunk_id": chunk_id, "manifest": updated_manifest})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/project/<slug>/compile", methods=["POST"])
    def compile_reader_endpoint(slug):
        pdir = get_project_dir(slug)
        try:
            data = request.json or {}
            embed = data.get("embed_images", True)
            target = compile_html(pdir, embed_images=embed)
            return jsonify({"success": True, "path": target, "embedded": embed})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # -------------------------------------------------------------------------
    # Image Serving & Reader Preview
    # -------------------------------------------------------------------------
    @app.route("/api/project/<slug>/images/<filename>")
    def serve_project_image(slug, filename):
        pdir = get_project_dir(slug)
        images_dir = os.path.join(pdir, "images")
        return send_from_directory(images_dir, filename)

    @app.route("/api/project/<slug>/reader")
    def serve_project_reader(slug):
        pdir = get_project_dir(slug)
        index_file = os.path.join(pdir, "index.html")
        as_download = request.args.get("download") == "1"
        download_name = f"{slug}_illustrated.html"

        if os.path.isfile(index_file):
            # Auto-heal: if index.html contains legacy relative image links ('src="images/'),
            # recompile it on the fly with embedded base64 images so it is always 100% portable
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    content = f.read()
                if '<img src="images/' in content:
                    compile_html(pdir, embed_images=True)
            except Exception:
                pass
            return send_file(index_file, as_attachment=as_download, download_name=download_name)

        # Fallback compile on the fly if manifest exists
        manifest_path = os.path.join(pdir, "artifacts", "manifest.json")
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            html_content = compile_manifest_to_html(manifest, pdir, embed_images=True)
            if as_download:
                import io
                return send_file(
                    io.BytesIO(html_content.encode("utf-8")),
                    mimetype="text/html",
                    as_attachment=True,
                    download_name=download_name
                )
            return html_content

        return "<h1>Manifest not yet generated for this story.</h1>", 404

    return app


if __name__ == "__main__":
    app = create_app()
    print("Starting Automated Story Illustrator WebUI on http://localhost:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=True)
