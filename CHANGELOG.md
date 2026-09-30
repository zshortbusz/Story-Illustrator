# Changelog

All notable changes to the Automated Story Illustrator (ASI) project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.5.0] - 2026-09-30

### Added
- **Cover Studio & Typography Compositor** ([`pipeline/cover_manager.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/cover_manager.py)):
  - Dedicated commercial book cover generation matching standard 1:1.6 KDP aspect ratios (832x1344 standard, 1600x2560 highres).
  - LLM-assisted cover prompt synthesis combining story protagonist DNA, primary setting architecture, and global art style.
  - Professional typography compositor with font selection (serif/modern), drop shadows, gradient scrim overlays, and dynamic subtitle/author positioning.
  - Existing scene converter allowing any illustrated story beat to be converted into an official book cover.
- **Multi-Format Ebook Retailer Exporter** ([`pipeline/book_exporter.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/book_exporter.py)):
  - **Fixed-Layout EPUB (EPUB 3.0 FXL)**: Optimized for graphic novels and picture books with synthetic two-page spreads.
  - **Standard Reflowable EPUB**: Flowable text with embedded illustrations and complete OPF/NCX navigation structures.
  - **Print-Ready PDF**: PDF generation with high-resolution image placement and proper page numbering.
  - **Complete Front/Back Matter**: Automatic generation of Cover, Title Page, Copyright, Dedication, Table of Contents, and Colophon pages with publisher metadata.
- **Real-Time Stage Progress Tracking**:
  - `/api/project/<slug>/stage_progress` polling endpoint on the web server.
  - Live console feedback and front-end status reporting during long-running batch extractions.
- **Comprehensive Test Suite & Static Analysis**:
  - Expanded test suite from 123 to 141 tests across 5 new test modules covering security, network resilience, exporter edge cases, and atomic persistence.
  - Automated Node.js frontend syntax parsing via `node -c pipeline/web_static/app.js`.

### Fixed
- **Web Server Endpoint Crashes** ([`pipeline/web_server.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/web_server.py)):
  - Resolved `NameError` crashes on `/api/project/<slug>/cover/render` by importing `Image` and `load_image_config`.
  - Resolved `AttributeError` by correctly calling `img_client.render()` instead of `generate_image()`.
  - Resolved `NameError` on `/api/project/<slug>/compile` by importing `compile_html` and promoting `get_project_dir` to module scope.
- **Path Traversal & Security Boundary Hardening** ([`pipeline/book_exporter.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/book_exporter.py), [`pipeline/compile_html.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/compile_html.py)):
  - Implemented `os.path.commonpath` verification across image resolvers and static HTML compilation to prevent arbitrary file reading via crafted manifests.
- **LLM Client Null Content & Reasoning Fallback** ([`pipeline/llm_client.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/llm_client.py)):
  - Fixed `chat_json` crashing on `NoneType.strip()` when models return `null` content or empty choices; added automatic fallback to `reasoning_content` for thinking models.
- **Image Resizing & Typography Fallback Resilience** ([`pipeline/book_exporter.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/book_exporter.py), [`pipeline/cover_manager.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/cover_manager.py)):
  - Clamped all image scaling dimensions to a minimum of 1 pixel, preventing Pillow `ValueError` crashes on extreme aspect ratios.
  - Fixed headless font fallback to use scalable TrueType defaults via `ImageFont.load_default(size=size)`.
  - Sanitized XML 1.0 restricted control characters in EPUB metadata and body text.
- **Atomic Persistence & Type Safety** ([`pipeline/project_manager.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/project_manager.py)):
  - Converted `save_global_styles` and profile updates to atomic tempfile writes (`.tmp` + `os.replace`) to prevent file corruption.
  - Added dictionary type validation guards for corrupted config files.
- **Frontend Race Conditions & Polling Stacking** ([`pipeline/web_static/app.js`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/web_static/app.js)):
  - Sequenced manifest loading after styles to resolve style selector dropdown race condition.
  - Added mutex flag to stage progress polling interval to prevent request pile-up during slow server responses.
- **Visual Bible Entity Merging Engine** ([`pipeline/build_manifest.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/build_manifest.py)):
  - Implemented stopword filtering (`"the"`, `"and"`, `"of"`, etc.) and multi-word first-name conflict detection in `match_bible_entity()`.
  - Prevented distinct family members (e.g. Carson Drew vs. Nancy Drew, Ada vs. Isabel Topham) and distinct roles (*The Butler*, *The Banker*, *The Marshal*, *The Robber Leader*) from erroneously collapsing into a single profile.
- **Reasoning Model Parser Hardening** ([`pipeline/llm_client.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/llm_client.py)):
  - Added automatic stripping of `<thought>...</thought>` and `<think>...</think>` tokens in JSON and text parsers so internal model reasoning never pollutes character or style presets.
  - Increased `infer_styles()` completion token budget to 3072 tokens to allow deep reasoning models (e.g. Gemma 4) to deliberate without getting truncated before JSON output.
  - Enforced strict keyword matching for markdown style fallback parsing.
- **Socket Timeout Resilience**:
  - Increased default LLM read timeout from 300s to 600s across `llm_client.py`, `project_manager.py`, and `web_server.py` to support deep ingestion of 30k+ token batches.

---

## [1.4.0] - 2026-09-20

### Added
- **Universal Style Presets Engine**:
  - Automated inference of story-tailored **Art Mediums** (e.g. *Charcoal Noir*, *Impasto Oil*, *Storybook Watercolor*, *Intaglio Etching*) and **Photography Eras** (e.g. *1970s Kodachrome*, *1890s Wet Plate*, *1950s Silver Gelatin Noir*).
  - Global styles compendium ([`config/global_styles.json`](file:///c:/Users/Shortbus/Story%20illustrator/config/global_styles.json)) allowing cross-project style inheritance and discovery.
- **Multi-Style Isolated Directory Rendering**:
  - Headless diffusion rendering isolates outputs into subdirectories formatted as `images/<workflow>__<style_id>/chunk_xxx.png`.
  - Style-isolated manifest tracking preventing image overwrites across different visual aesthetics.
- **Optimized Diffusion Profiles**:
  - Custom profiles for `krea2_turbo` and `zit_turbo_base` incorporating explicit structural blueprints and negative prompt engineering.

---

## [1.3.0] - 2026-09-18

### Added
- **Prompt Context Audit System**:
  - Real-time audit modal in WebUI showing exact attribution breakdown for every generated prompt.
  - Inspect active character traits, base DNA, setting architecture, and art style keywords incorporated into each scene.
- **Chronological Timeline & Wardrobe Continuity**:
  - Support for `Physical Change [chunk_xxx]: <trait>` tags to represent injuries, scars, or aging that only activate after specific story events.
  - Contextual wardrobe tracking supporting default attire, timeline changes (`Costume Change [chunk_xxx]: <attire>`), setting-specific alternates, and per-beat scene overrides.
- **Interactive Reader Comparison**:
  - Side-by-side workflow and style comparison in the Reader tab with instant switching.

---

## [1.2.0] - 2026-09-17

### Added
- **ComfyUI Wildcard Tag Injection**:
  - Universal tag replacement system supporting `%PositivePrompt%`, `%NegativePrompt%`, `%Width%`, `%Height%`, and `%Seed%` inside any ComfyUI JSON graph.
  - Drop-in compatibility allowing users to bring any custom workflow JSON directly into the `workflows/` directory.
- **ComfyUI Efficiency Loader Support**:
  - Automated parameter discovery and injection for advanced ComfyUI custom node suites (e.g., Efficiency Nodes, `!Draw`).
- **Batch Regeneration Controls**:
  - Selective re-render by chunk, single-workflow regeneration, and global force re-render options.

---

## [1.1.0] - 2026-09-13

### Added
- **Dynamic Context Window Auto-Detection**:
  - Automatic probing of active LLM context size via `/v1/models` and endpoint metadata.
- **Incremental Visual Bible Batching**:
  - Chunk batching scaled dynamically to model context budgets (e.g. 32k, 64k, 128k tokens) with overlapping continuity buffers.
- **Backend-Agnostic LLM Architecture**:
  - Support for Bring-Your-Own-API endpoints, custom keys, and local/remote providers (LM Studio, vLLM, Ollama, OpenAI).
- **Portable HTML Reader**:
  - Export self-contained standalone HTML storybooks with images embedded directly as base64 data URIs.

---

## [1.0.0] - 2026-09-12

### Added
- **Initial Beta Release of Automated Story Illustrator (ASI)**:
  - 6-stage autonomous storybook publishing pipeline:
    1. Narrative Chunking (`01_chunks.json`)
    2. Visual Bible Extraction (`03_visual_bible.json`)
    3. Narrative Beat Selection (`02_selected_beats.json`)
    4. Config-Driven Prompt Synthesis (`manifest.json`)
    5. Headless ComfyUI Diffusion Rendering (`images/*.png`)
    6. Browser-Based Reader & Review UI (`index.html`)
  - Multi-character DNA tracking and setting environment extraction.
  - Native ComfyUI WebSocket API integration with seed tracking and live progress reporting.
