"""
pipeline/mcp_server.py: Model Context Protocol (MCP) Server for Automated Story Illustrator.
Exposes tools and resources enabling any MCP-compatible AI agent (Claude, Antigravity,
Cursor, Goose, Copilot, etc.) to inspect, generate, render, and publish illustrated books.
"""

import os
import sys
import json
from typing import Dict, Any, List, Optional

# Root directory of the repository
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pipeline.project_manager import (
    get_base_dir,
    list_projects,
    init_project,
    slugify
)
from pipeline.book_exporter import (
    get_book_metadata,
    export_high_res_pdf,
    export_fxl_epub,
    export_reflowable_epub,
    export_kdp_bundle
)
from pipeline.health_check import run_all_checks


# --- Core Tool Implementations ---

def _load_manifest_dict(project_dir: str) -> Dict[str, Any]:
    """Helper to locate and parse manifest.json."""
    for p in [os.path.join(project_dir, "artifacts", "manifest.json"), os.path.join(project_dir, "manifest.json")]:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
    return {"illustrations": [], "metadata": {}}


def tool_list_projects() -> List[Dict[str, Any]]:
    """List all available story projects and their metadata."""
    base = get_base_dir()
    slugs = list_projects()
    results = []
    for slug in slugs:
        p_dir = os.path.join(base, "projects", slug)
        manifest_data = _load_manifest_dict(p_dir)
        meta = get_book_metadata(manifest_data, project_dir=p_dir)
        items = manifest_data.get("illustrations", [])

        rendered_count = sum(1 for item in items if item.get("status") == "completed")
        results.append({
            "slug": slug,
            "title": meta.get("title", slug),
            "author": meta.get("author", "Unknown"),
            "total_scenes": len(items),
            "rendered_scenes": rendered_count,
            "cover_path": meta.get("cover_image_path", "")
        })
    return results


def tool_get_project_status(project_slug: str) -> Dict[str, Any]:
    """Get detailed lifecycle status and stage progression of a specific story project."""
    p_dir = os.path.join(get_base_dir(), "projects", slugify(project_slug))
    if not os.path.isdir(p_dir):
        raise ValueError(f"Project '{project_slug}' not found at {p_dir}.")
    
    manifest_data = _load_manifest_dict(p_dir)
    meta = get_book_metadata(manifest_data, project_dir=p_dir)
    
    chunks_path = os.path.join(p_dir, "artifacts", "01_chunks.json")
    if not os.path.isfile(chunks_path):
        chunks_path = os.path.join(p_dir, "01_chunks.json")

    bible_path = os.path.join(p_dir, "artifacts", "03_visual_bible.json")
    if not os.path.isfile(bible_path):
        bible_path = os.path.join(p_dir, "03_visual_bible.json")

    beats_path = os.path.join(p_dir, "artifacts", "02_selected_beats.json")
    if not os.path.isfile(beats_path):
        beats_path = os.path.join(p_dir, "02_selected_beats.json")

    manifest_path = os.path.join(p_dir, "artifacts", "manifest.json")
    if not os.path.isfile(manifest_path):
        manifest_path = os.path.join(p_dir, "manifest.json")
    
    chunks_count = 0
    if os.path.isfile(chunks_path):
        try:
            with open(chunks_path, "r", encoding="utf-8") as f:
                chunks_count = len(json.load(f))
        except Exception:
            pass
            
    bible_characters = 0
    bible_settings = 0
    if os.path.isfile(bible_path):
        try:
            with open(bible_path, "r", encoding="utf-8") as f:
                bible_data = json.load(f)
                bible_characters = len(bible_data.get("characters", {}))
                bible_settings = len(bible_data.get("settings", {}))
        except Exception:
            pass

    beats_count = 0
    if os.path.isfile(beats_path):
        try:
            with open(beats_path, "r", encoding="utf-8") as f:
                beats_count = len(json.load(f))
        except Exception:
            pass

    illustrations = []
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
                illustrations = manifest_data.get("illustrations", [])
        except Exception:
            pass

    completed_renders = sum(1 for item in illustrations if item.get("status") == "completed")

    exports_dir = os.path.join(p_dir, "exports")
    exported_files = os.listdir(exports_dir) if os.path.isdir(exports_dir) else []

    raw_story_exists = (
        os.path.isfile(os.path.join(p_dir, "source", "input_story.txt")) or
        os.path.isfile(os.path.join(p_dir, "story.txt"))
    )

    return {
        "slug": project_slug,
        "title": meta.get("title", project_slug),
        "author": meta.get("author", "Unknown"),
        "pipeline_progress": {
            "has_raw_story": raw_story_exists,
            "chunks_count": chunks_count,
            "bible_extracted": os.path.isfile(bible_path),
            "bible_characters_count": bible_characters,
            "bible_settings_count": bible_settings,
            "beats_selected_count": beats_count,
            "manifest_generated": os.path.isfile(manifest_path),
            "total_prompts": len(illustrations),
            "completed_renders": completed_renders,
            "exports": exported_files
        }
    }


def tool_create_project(name: str, story_text: str = "") -> Dict[str, Any]:
    """Create a new story project workspace with scaffolded directories and optional input story text."""
    slug = slugify(name)
    project_dir = init_project(slug, input_text=story_text if story_text.strip() else None)
    return {
        "success": True,
        "slug": slug,
        "project_dir": project_dir,
        "message": f"Project '{name}' (slug: {slug}) initialized successfully."
    }


def tool_chunk_story(project_slug: str, max_words: int = 150) -> Dict[str, Any]:
    """Phase 1, Step 1: Deterministically segment raw story text into scene chunks."""
    p_dir = os.path.join(get_base_dir(), "projects", slugify(project_slug))
    from pipeline.build_manifest import run_stage_chunk
    chunks = run_stage_chunk(p_dir, max_words=max_words)
    return {
        "success": True,
        "slug": project_slug,
        "total_chunks": len(chunks) if chunks else 0
    }


def tool_extract_bible(project_slug: str, model: str = "") -> Dict[str, Any]:
    """Phase 1, Step 2: Extract character profiles (Base DNA & timeline modifications) and setting environments."""
    p_dir = os.path.join(get_base_dir(), "projects", slugify(project_slug))
    from pipeline.build_manifest import run_stage_bible
    bible = run_stage_bible(p_dir, model_override=model or None)
    return {
        "success": True,
        "slug": project_slug,
        "characters": list(bible.get("characters", {}).keys()) if bible else [],
        "settings": list(bible.get("settings", {}).keys()) if bible else [],
        "global_art_style": bible.get("global_art_style", "") if bible else ""
    }


def tool_select_beats(project_slug: str, model: str = "") -> Dict[str, Any]:
    """Phase 1, Step 3: Scan story chunks to identify dramatic visual illustration moments."""
    p_dir = os.path.join(get_base_dir(), "projects", slugify(project_slug))
    from pipeline.build_manifest import run_stage_beats
    beats = run_stage_beats(p_dir, model_override=model or None)
    return {
        "success": True,
        "slug": project_slug,
        "total_beats": len(beats) if beats else 0,
        "selected_chunk_ids": [b.get("chunk_id") for b in beats] if beats else []
    }


def tool_synthesize_prompts(project_slug: str, profile_name: str = "sdxl_base", model: str = "") -> Dict[str, Any]:
    """Phase 1, Step 4: Synthesize 5-element diffusion prompts blending Base DNA, attire, setting, and action beats."""
    p_dir = os.path.join(get_base_dir(), "projects", slugify(project_slug))
    from pipeline.build_manifest import run_stage_manifest
    manifest = run_stage_manifest(p_dir, profile_name=profile_name, model_override=model or None)
    illustrations = manifest.get("illustrations", []) if manifest else []
    return {
        "success": True,
        "slug": project_slug,
        "total_prompts": len(illustrations),
        "prompts": [
            {
                "chunk_id": item.get("chunk_id"),
                "prompt": item.get("prompt"),
                "characters": item.get("characters", [])
            }
            for item in illustrations
        ]
    }


def tool_render_illustrations(project_slug: str, workflow_file: str = "animab.json", chunk_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Phase 2: Batch render illustrations headless via ComfyUI using specified workflow."""
    p_dir = os.path.join(get_base_dir(), "projects", slugify(project_slug))
    from pipeline.render_images import run_phase_2
    results = run_phase_2(
        project_dir=p_dir,
        workflow_override=workflow_file,
        rerun_chunks=chunk_ids
    )
    return {
        "success": True,
        "slug": project_slug,
        "workflow": workflow_file,
        "rendered": results
    }


def tool_export_book(project_slug: str, format: str = "all", title: str = "", author: str = "", isbn: str = "") -> Dict[str, Any]:
    """Phase 3: Export publication-ready Print PDF, Fixed-Layout FXL EPUB 3.0, and Reflowable EPUB."""
    p_dir = os.path.join(get_base_dir(), "projects", slugify(project_slug))
    
    metadata_overrides = {}
    if title:
        metadata_overrides["title"] = title
    if author:
        metadata_overrides["author"] = author
    if isbn:
        metadata_overrides["isbn"] = isbn
        
    exported = {}
    if format in ("all", "pdf"):
        exported["pdf"] = export_high_res_pdf(p_dir, metadata_overrides=metadata_overrides)
    if format in ("all", "fxl", "epub_fxl"):
        exported["epub_fxl"] = export_fxl_epub(p_dir, metadata_overrides=metadata_overrides)
    if format in ("all", "reflowable", "epub_reflow"):
        exported["epub_reflow"] = export_reflowable_epub(p_dir, metadata_overrides=metadata_overrides)
    if format == "kdp":
        exported["kdp_bundle"] = export_kdp_bundle(p_dir, metadata_overrides=metadata_overrides)
        
    return {
        "success": True,
        "slug": project_slug,
        "exports": exported
    }


def tool_audit_context(project_slug: str, chunk_id: str) -> Dict[str, Any]:
    """Audit character Base DNA, active timeline modifications, and setting context resolved for a chunk."""
    p_dir = os.path.join(get_base_dir(), "projects", slugify(project_slug))
    from pipeline.build_manifest import compose_prompt_context_for_beat
    return compose_prompt_context_for_beat(p_dir, chunk_id)


# --- Server Construction & Transport ---

def create_mcp_app():
    """Build and configure the MCP server instance."""
    try:
        try:
            from mcp.server.mcpserver import MCPServer
            server = MCPServer("automated-story-illustrator")
        except ImportError:
            from mcp.server.fastmcp import FastMCP
            server = FastMCP("automated-story-illustrator")
            
        # Register Tools
        server.tool()(tool_list_projects)
        server.tool()(tool_get_project_status)
        server.tool()(tool_create_project)
        server.tool()(tool_chunk_story)
        server.tool()(tool_extract_bible)
        server.tool()(tool_select_beats)
        server.tool()(tool_synthesize_prompts)
        server.tool()(tool_render_illustrations)
        server.tool()(tool_export_book)
        server.tool()(tool_audit_context)
        server.tool()(run_all_checks)
        
        return server
    except Exception as e:
        return None


def run_stdio_mcp():
    """Runs the MCP server over standard input/output."""
    server = create_mcp_app()
    if server is None:
        print("MCP SDK not installed or encountered an error. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)
    server.run(transport="stdio")


if __name__ == "__main__":
    run_stdio_mcp()
