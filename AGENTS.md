# AGENTS.md — AI Agent Integration & Architecture Guide

Welcome, AI Agent! This guide provides machine-actionable instructions for inspecting, installing, developing, testing, and executing the **Automated Story Illustrator (ASI)** pipeline.

---

## 1. Executive Summary & Architecture

Automated Story Illustrator (ASI) is an end-to-end generative AI pipeline and web dashboard that turns raw text stories into publication-grade digital editions (High-Resolution Print PDF, Fixed-Layout FXL EPUB 3.0, Reflowable EPUB, and interactive web readers).

### Strict Three-Phase Decoupled Architecture
To prevent GPU VRAM contention on consumer setups (e.g. 8GB VRAM), ASI enforces strict lifecycle decoupling:
```
┌────────────────────────────────────────────────────────┐
│ Phase 1: Story Analysis & Prompt Synthesis (LLM)      │
│  - Step 1: Chunking (01_chunks.json)                   │
│  - Step 2: Visual Bible Extraction (03_visual_bible)  │
│  - Step 3: Beat Selection (02_selected_beats.json)    │
│  - Step 4: Prompt Synthesis (manifest.json)            │
└──────────────────────────┬─────────────────────────────┘
                           │ (ComfyUI closed / idle)
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 2: Diffusion Rendering (Headless ComfyUI)        │
│  - Reads manifest.json                                 │
│  - Strict wildcard tag injection (%PositivePrompt%,etc)│
│  - Renders to ./images/<workflow>/<chunk_id>.png       │
│  - Atomic status update in manifest.json               │
└──────────────────────────┬─────────────────────────────┘
                           │ (LLM unloaded / idle)
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 3: Publication & Ebook Exports (Pure Python)     │
│  - Print-Ready PDF with vector typography              │
│  - Fixed-Layout FXL EPUB 3.0 (Amazon KDP / Apple Books)│
│  - Reflowable EPUB (e-readers)                         │
└────────────────────────────────────────────────────────┘
```

---

## 2. Environment Setup & Health Verification

### 2.1 One-Step Installation
```bash
# Create and activate virtual environment
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
# Or editable mode:
pip install -e .
```

### 2.2 Health Diagnostic Check
Agents can verify environment, dependencies, and backend services in a single non-interactive command:
```bash
# Human-readable output:
python -m pipeline.health_check

# Machine-readable JSON output (Exit code 0 on success, 1 on missing core deps):
python -m pipeline.health_check --json
```

---

## 3. Running Automated Tests

Always run the test suite to verify changes:
```bash
python -m unittest discover -s tests -v
```

### Key Test Suites:
- `tests/test_chunker.py`: Story segmentation and word boundary preservation.
- `tests/test_timeline_continuity.py`: Character Base DNA, chronological scars/modifications, and wardrobe timelines.
- `tests/test_prompt_context_audit.py`: Context resolution and timeline isolation.
- `tests/test_workflow_tags.py`: Strict wildcard tag validation in ComfyUI workflows.
- `tests/test_book_exporter.py`: PDF, FXL EPUB, and Reflowable EPUB compilation.
- `tests/test_mcp_and_health.py`: MCP tool definitions and health check routines.

---

## 4. Headless CLI Execution for Agents

Agents can trigger individual pipeline stages or complete batches via CLI:

### 4.1 Phase 1: Analysis & Prompt Synthesis
```bash
# Run all Phase 1 stages for a project:
python -m pipeline.build_manifest --project ./projects/the_clockwork_duel --stage all

# Run specific stage:
python -m pipeline.build_manifest --project ./projects/the_clockwork_duel --stage chunker
python -m pipeline.build_manifest --project ./projects/the_clockwork_duel --stage bible
python -m pipeline.build_manifest --project ./projects/the_clockwork_duel --stage beats
python -m pipeline.build_manifest --project ./projects/the_clockwork_duel --stage manifest
```

### 4.2 Phase 2: Headless Diffusion Rendering
```bash
# Batch render all scheduled illustrations:
python -m pipeline.render_images --project ./projects/the_clockwork_duel --workflow ./workflows/animab.json

# Rerun a single scene:
python -m pipeline.render_images --project ./projects/the_clockwork_duel --rerun chunk_002
```

### 4.3 Phase 3: Ebook & Print Compilation
```bash
# Export all publication formats (PDF, FXL EPUB, Reflowable EPUB):
python -m pipeline.book_exporter --project ./projects/the_clockwork_duel --format all

# Export specific format with custom metadata:
python -m pipeline.book_exporter --project ./projects/the_clockwork_duel --format pdf --author "Author Name" --isbn "978-0-123456-47-2"
```

---

## 5. Model Context Protocol (MCP) Server

Automated Story Illustrator ships with a built-in MCP server (`pipeline/mcp_server.py`) enabling AI assistants (Claude Desktop, Cursor, Antigravity, VS Code, Goose) to orchestrate book generation natively.

### 5.1 Starting the MCP Server
```bash
# Stdio transport:
python -m pipeline.mcp_server
```

### 5.2 Connecting via `mcpServers` Config (Claude Desktop / Cursor / Antigravity)
```json
{
  "mcpServers": {
    "story-illustrator": {
      "command": "python",
      "args": ["-m", "pipeline.mcp_server"],
      "cwd": "/path/to/Story-Illustrator"
    }
  }
}
```

### 5.3 Exposed MCP Tools
| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `tool_list_projects` | None | List all available story projects and metadata |
| `tool_get_project_status` | `project_slug: str` | Get detailed lifecycle status & progress |
| `tool_create_project` | `name: str, story_text: str` | Scaffold new project with optional story text |
| `tool_chunk_story` | `project_slug: str, max_words: int` | Chunk manuscript into scene paragraphs |
| `tool_extract_bible` | `project_slug: str, model: str` | Extract character DNA & setting environment |
| `tool_select_beats` | `project_slug: str, model: str` | Identify dramatic illustration moments |
| `tool_synthesize_prompts` | `project_slug: str, profile_name: str` | Synthesize 5-element diffusion prompts |
| `tool_render_illustrations` | `project_slug: str, workflow_file: str` | Queue ComfyUI image rendering |
| `tool_export_book` | `project_slug: str, format: str` | Export PDF, FXL EPUB, and Reflowable EPUB |
| `tool_audit_context` | `project_slug: str, chunk_id: str` | Inspect resolved character Base DNA & attire |
| `run_all_checks` | None | Verify environment health and service ports |

---

## 6. Directory Layout & Data Artifacts

```
projects/{story_slug}/
├── source/
│   └── input_story.txt            # Raw manuscript text
├── artifacts/
│   ├── 01_chunks.json             # Sliced text chunks with word counts
│   ├── 03_visual_bible.json       # Extracted characters (Base DNA + timelines) & settings
│   ├── 02_selected_beats.json     # Selected visual illustration moments & scene attire
│   └── manifest.json              # Master execution manifest with synthesized prompts & render status
├── config/
│   ├── llm_models.json            # LLM endpoints and role system prompts
│   ├── diffusion_profiles.json    # ComfyUI/OpenAI resolution tiers and prompt blueprints
│   └── workflow_api.json          # Active ComfyUI workflow template
├── images/                        # Generated illustration PNGs categorized by workflow
│   └── {workflow_name}/
│       └── chunk_002.png
└── exports/                       # Final compiled book editions
    ├── {story_slug}_print.pdf
    ├── {story_slug}_fxl.epub
    └── {story_slug}_reflowable.epub
```

---

## 7. Golden Rules for Agent Contributions

1. **Preserve Decoupled Architecture**: Never introduce dependencies that require ComfyUI and LM Studio to run concurrently in GPU VRAM during Phase 1.
2. **Strict Wildcard Tags in Workflows**: All ComfyUI workflows in `workflows/` MUST contain the 4 mandatory wildcard tags: `%PositivePrompt%`, `%NegativePrompt%`, `"%Width%"`, `"%Height%"`.
3. **Atomic File I/O**: Use `atomic_write_json` / safe temp file replacement when updating manifests and artifacts to protect against Windows file locking issues.
4. **Always Run Tests**: Ensure `python -m unittest discover -s tests` passes before committing code.
