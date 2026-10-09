# GitHub Copilot Instructions — Automated Story Illustrator

## Project Overview
Automated Story Illustrator (ASI) is an end-to-end local generative pipeline and web dashboard that turns raw text stories into publication-grade digital editions (High-Resolution Print PDF, Fixed-Layout FXL EPUB 3.0, Reflowable EPUB).

## Key Architectural Principles
- **Decoupled 3-Phase Architecture**:
  - Phase 1: LLM text analysis & prompt synthesis (LM Studio / OpenAI-compatible).
  - Phase 2: Headless diffusion rendering (ComfyUI / OpenAI-compatible).
  - Phase 3: Pure Python publication compiling (PDF via ReportLab, EPUBs).
- **Wildcard Tags**: ComfyUI workflows in `workflows/` strictly use:
  - `%PositivePrompt%`
  - `%NegativePrompt%`
  - `"%Width%"`
  - `"%Height%"`
- **Health Verification**: Run `python -m pipeline.health_check` to diagnose dependencies.
- **Testing**: Run `python -m unittest discover -s tests -v`.
- **MCP Server**: Located at `pipeline/mcp_server.py`.
- **Full Guide**: Consult `AGENTS.md` for complete schema definitions and CLI options.
