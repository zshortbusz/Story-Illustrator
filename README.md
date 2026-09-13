# Automated Story Illustrator (ASI)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![ComfyUI Compatible](https://img.shields.io/badge/ComfyUI-Compatible-brightgreen.svg)](https://github.com/comfyanonymous/ComfyUI)
[![LM Studio Compatible](https://img.shields.io/badge/LM%20Studio-Compatible-purple.svg)](https://lmstudio.ai/)

**Automated Story Illustrator (ASI)** is an end-to-end local generative pipeline and interactive web dashboard that transforms raw text stories and novels into fully illustrated, beautifully formatted static web readers.

Designed specifically for consumer-grade GPU setups (such as an NVIDIA GeForce RTX 3070 with 8GB VRAM), ASI implements a strict **three-phase decoupled architecture** that separates literary analysis from diffusion rendering, guaranteeing zero GPU memory contention or VRAM Out-of-Memory (OOM) crashes.

---

## Key Features

- **Strict Three-Phase Lifecycle**:
  - **Phase 1 (Analysis & Prompts)**: Powered by local LLMs via LM Studio (`http://localhost:1234/v1`).
  - **Phase 2 (Diffusion Rendering)**: Batch rendered headless via ComfyUI WebSocket & REST API (`http://127.0.0.1:8188`).
  - **Phase 3 (Reader Assembly)**: Pure Python compilation into standalone, offline, responsive HTML readers.
- **Visual Bible Compendium & Continuity**:
  - Automatically extracts exhaustive character profiles (build, face, hair, clothing, and distinctive features such as prosthetic limbs/implants) and setting environments.
  - Multi-strategy entity resolution (exact, case-insensitive, substring, and token overlap) connects characters and locations across beats for prompt consistency.
- **5-Element Diffusion Prompt Synthesis**:
  - Synthesizes rich diffusion prompts combining: (1) Character visual appearance, (2) Action beat, (3) Setting architecture & texture, (4) Camera angle & lighting, and (5) Global art style.
  - Ready-to-use profiles for **SDXL Base**, **Flux Natural Language**, and **Anime Danbooru**.
- **Failure Visibility & Uncapped Thinking**:
  - Zero synthetic fallbacks: errors and empty model responses fail loudly with clear diagnostics.
  - Uncapped thinking token budget (`max_tokens: -1`) to empower modern reasoning models (e.g., DeepSeek-R1, Orion, Gemma 4, Qwen).
- **Interactive WebUI Dashboard**:
  - Single-page application with real-time service health monitoring for LM Studio and ComfyUI.
  - Hardware warning banners instructing the user when to load or unload models between phases.
  - In-tab model overrides, parameter tuning, drag-and-drop story creation, manifest filtering, and single-chunk tweak & regeneration.
- **Automated Verification Suite**:
  - 35 automated tests covering DOM structure, JavaScript contracts, reader styling, API endpoints, ComfyUI node injection, and visible Chrome DevTools E2E automation with image quality verification.

---

## System Architecture

```
                               RAW STORY (.txt / .md)
                                         │
┌────────────────────────────────────────▼────────────────────────────────────────┐
│                        PHASE 1: STORY ANALYSIS (LM Studio)                      │
│                                                                                 │
│   ┌───────────────────┐    ┌───────────────────┐    ┌───────────────────────┐   │
│   │ 1. Story Chunker  │───►│  2. Visual Bible  │───►│   3. Visual Beats     │   │
│   │ (Deterministic    │    │ (Character &      │    │  (Cinematic Scene     │   │
│   │  Regex Slicing)   │    │  Setting Profiles)│    │   Beat Selection)     │   │
│   └───────────────────┘    └───────────────────┘    └───────────┬───────────┘   │
│                                                                 │               │
│                                                                 ▼               │
│                                                     ┌───────────────────────┐   │
│                                                     │ 4. Prompt Synthesis   │   │
│                                                     │ (Master manifest.json)│   │
│                                                     └───────────────────────┘   │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     PHASE 2: DIFFUSION BATCH (ComfyUI)                          │
│                                                                                 │
│   - Headless WebSocket execution tracking & REST job dispatch                   │
│   - Automatic node parameter injection (prompt, negative, width, height, seed)  │
│   - Compatible with SDXL, Flux.1 Dev, and Anima 1.5 / Qwen workflows           │
│   - Atomic manifest checkpointing and single-chunk tweak & rerun                │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    PHASE 3: STATIC READER ASSEMBLY (Python)                     │
│                                                                                 │
│   - Pure Python zero-footprint compilation (no GPU / no server required)        │
│   - Dialogue quote highlighting (<strong class="q">) and embedded figures       │
│   - Generates standalone, dark-mode, mobile-responsive index.html               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
.
├── webui.py                         # Top-level WebUI launcher
├── requirements.txt                 # Project Python dependencies
├── LICENSE                          # MIT License
├── README.md                        # Documentation
├── workflows/                       # ComfyUI API workflow templates
│   ├── animap.json                  # Anima 1.5 + Qwen fast diffusion workflow
│   ├── sdxl_base.json               # SDXL base diffusion workflow
│   └── flux_dev.json                # Flux.1 Dev diffusion workflow
├── pipeline/                        # Core Python pipeline modules
│   ├── chunker.py                   # Deterministic regex story chunker
│   ├── llm_client.py                # LM Studio client & robust text parsers
│   ├── build_manifest.py            # Phase 1 orchestrator (Chunks -> Bible -> Beats -> Manifest)
│   ├── comfy_client.py              # ComfyUI WebSocket & REST client
│   ├── render_images.py             # Phase 2 batch orchestrator & rerun handler
│   ├── compile_html.py              # Phase 3 reader compiler & dialogue quote parser
│   ├── project_manager.py           # Project scaffolding & default configuration
│   ├── web_server.py                # Flask backend REST API
│   └── web_static/                  # WebUI SPA frontend
│       ├── index.html               # Responsive multi-tab dashboard
│       ├── style.css                # Dark mode styling & responsive layout
│       └── app.js                   # Frontend controller
├── projects/                        # Story project workspaces
│   ├── the_rust_forest/             # Sample dark sci-fi story project
│   └── winnie/                      # Sample children's classic story project
└── tests/                           # Complete automated test suite (35 tests)
    ├── test_chunker.py              # Paragraph chunking & word counting tests
    ├── test_llm_client.py           # Free-text & markdown parser tests
    ├── test_manifest_continuity.py  # Fuzzy entity resolution & continuity tests
    ├── test_comfy_client.py         # Workflow parameter injection tests
    ├── test_compile_html.py         # Dialogue quote & HTML compilation tests
    ├── test_web_api.py              # REST API endpoint tests
    └── test_ui_elements.py          # UI DOM, JS contracts, & visible Chrome E2E tests
```

---

## Prerequisites

1. **Python 3.10 or higher**: [python.org](https://www.python.org/)
2. **LM Studio**: [lmstudio.ai](https://lmstudio.ai/)
   - Start the local server at `http://localhost:1234/v1`.
   - Load any capable instruction-following model (e.g., `gemma-4-e4b-it-qat`, `thedrummer_orion-26b-a4b-v1`, `qwen2.5-7b-instruct`).
3. **ComfyUI**: [github.com/comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI)
   - Running at `http://127.0.0.1:8188`.
   - Ensure the required checkpoints for your chosen workflow are installed in `ComfyUI/models/`.

---

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/zshortbusz/Story-Illustrator.git
   cd Story-Illustrator
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   # Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## Quickstart: Interactive WebUI

Launch the web dashboard:
```bash
python webui.py
```
Open your browser to:
```
http://127.0.0.1:5000
```

### WebUI Workflow:
1. Click **+ New Story** to paste story text or drag and drop a `.txt` / `.md` file.
2. **Tab 1 (Chunks)**: Click **Run Chunker** to divide your story into scene-length paragraphs.
3. **Tab 2 (Visual Bible)**: Select your loaded LM Studio model and click **Run Extraction** to extract character and setting profiles.
4. **Tab 3 (Visual Beats)**: Click **Run Beat Selection** to select dramatic visual moments.
5. **Tab 4 (Manifest & Prompts)**: Click **Synthesize Prompts** to generate diffusion prompts. Review or fine-tune prompts directly.
6. **Tab 5 (Render & Regenerate)**: Select your ComfyUI workflow (`animap.json`, `sdxl_base.json`, etc.) and click **Start Batch Render**. Inspect generated illustrations or click **Tweak & Rerun** to adjust individual scenes.
7. **Tab 6 (Reader Preview)**: Click **Compile index.html** to generate the final illustrated offline reader.

---

## Headless CLI Execution

For automated batch scripting, the pipeline can be run completely headless:

```bash
# Phase 1: Full Story Analysis & Prompt Synthesis
python -m pipeline.build_manifest --project ./projects/the_rust_forest --stage all

# Phase 2: Batch Diffusion Rendering via ComfyUI
python -m pipeline.render_images --project ./projects/the_rust_forest --workflow ./workflows/sdxl_base.json

# Rerun a single image with adjustments:
python -m pipeline.render_images --project ./projects/the_rust_forest --rerun chunk_003

# Phase 3: Compile Static Offline Reader
python -m pipeline.compile_html --project ./projects/the_rust_forest
```

---

## Running Tests

Run the full automated test suite (all 35 unit, contract, API, and visible browser E2E tests):

```bash
python -m unittest discover -s tests -v
```

### Visible Chrome DevTools E2E Tests:
The UI test suite in `tests/test_ui_elements.py` includes a live browser test that drives Google Chrome in a visible window using the Chrome DevTools protocol, verifying modal forms, tab navigation, end-to-end story generation, ComfyUI rendering, and image pixel quality:

```bash
python -m unittest tests/test_ui_elements.py -v
```

*(Note: Chrome DevTools tests automatically skip gracefully if `chrome-devtools-mcp` is not installed).*

---

## License

This project is licensed under the [MIT License](LICENSE).
