"""
pipeline/build_manifest.py: Phase 1 Orchestrator for Automated Story Illustrator (ASI).
Executes Phase 1 stages in logical order:
  Step 1: Chunking (01_chunks.json)
  Step 2: Visual Bible Extraction (03_visual_bible.json) - Art style, characters & settings
  Step 3: Sliding window Beat Selection (02_selected_beats.json) - Visual moments
  Step 4: Config-Driven Prompt Synthesis (manifest.json) - Final diffusion prompts
Includes runtime pre-flight hardware checks and supports per-stage execution with progress callbacks.
"""

import os
import re
import json
import argparse
from typing import Dict, Any, List, Optional, Callable, Tuple, Union
from pipeline.chunker import chunk_file
from pipeline.llm_client import (
    LMStudioClient,
    load_llm_config,
    parse_beats_response,
    parse_bible_response,
    parse_prompt_response,
    estimate_tokens,
    ContextWindowExceededError,
    CharacterProfile,
    normalize_character_entry,
    infer_styles
)
from pipeline.project_manager import merge_into_global_styles


def print_banner(stage_name: str = "ALL"):
    print("""
================================================================================
PHASE 1: Story Analysis & Prompt Synthesis
  Runtime: LM Studio (Local Server @ http://localhost:1234/v1)
  State: ComfyUI CLOSED (To prevent GPU VRAM competition)
  Workflow: Chunker -> Visual Bible -> Beat Selector -> Prompt Synthesizer
  Output: manifest.json (Self-contained execution checkpoint)
================================================================================
""")


def check_runtime_readiness(llm_client: LMStudioClient):
    """Verifies LLM server is accessible and warns if ComfyUI is also running (for local models)."""
    import requests
    health = llm_client.check_health()
    if not health.get("online"):
        label = "LM Studio" if getattr(llm_client, "backend", "lm_studio") == "lm_studio" else "LLM Provider"
        raise RuntimeError(
            f"{label} is NOT reachable at {llm_client.api_base}!\n"
            f"Details: {health.get('message', 'Server offline')}"
        )

    # Only warn about ComfyUI if running local LM Studio backend
    if getattr(llm_client, "backend", "lm_studio") == "lm_studio":
        try:
            resp = requests.get("http://127.0.0.1:8188/system_stats", timeout=1)
            if resp.status_code == 200:
                print("\n[WARNING] ComfyUI server is currently running at http://127.0.0.1:8188.")
                print("[WARNING] It is strongly recommended to CLOSE ComfyUI during local Phase 1 to prevent GPU VRAM Out-of-Memory failures.\n")
        except Exception:
            pass


def run_stage_chunk(project_dir: str, callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Step 1: Chunking."""
    input_file = os.path.join(project_dir, "source", "input_story.txt")
    output_file = os.path.join(project_dir, "artifacts", "01_chunks.json")
    msg = f"Step 1: Chunking {input_file}..."
    print(f"[*] {msg}")
    if callback: callback(msg)

    data = chunk_file(input_file, output_file)
    done_msg = f"Chunking completed: {len(data['chunks'])} chunks saved to 01_chunks.json"
    print(f"[+] {done_msg}")
    if callback: callback(done_msg)
    return data


def chunk_num(cid: Any) -> int:
    """Extract integer index from chunk ID (e.g. 'chunk_025' -> 25)."""
    m = re.search(r"\d+", str(cid))
    return int(m.group(0)) if m else 0


def merge_character_profile(
    existing: Union[str, Dict[str, Any]],
    incoming: Union[str, Dict[str, Any]],
    current_chunk_id: str = "chunk_000",
    max_dna_chars: int = 400
) -> CharacterProfile:
    """
    Merges an incoming character update into the existing profile:
    1. Compares incoming base_dna with existing base_dna using word token overlap.
       If overlap >= 60%, treats as redundant re-description and preserves existing base_dna.
       If overlap < 60% and introduces new permanent traits, appends unique clauses (capped at max_dna_chars).
    2. Ingests new timeline modifications (scars, injuries, prosthetics).
    3. Ingests wardrobe timeline updates or alternate attires without polluting base_dna.
    """
    ex = normalize_character_entry(existing, current_chunk_id=current_chunk_id)
    inc = normalize_character_entry(incoming, current_chunk_id=current_chunk_id)

    # 1. Merge Base DNA
    ex_dna = ex.get("base_dna", "").strip()
    inc_dna = inc.get("base_dna", "").strip()

    merged_dna = ex_dna
    if not ex_dna:
        merged_dna = inc_dna
    elif inc_dna:
        # If existing base_dna was very sparse, upgrade to richer incoming description
        if len(ex_dna) < 40 and len(inc_dna) > len(ex_dna):
            merged_dna = inc_dna
        # Otherwise retain canonical base_dna; chronological changes are tracked in timeline_modifications

    # 2. Merge Timeline Modifications (Scars, Amputations, Prosthetics)
    merged_mods = list(ex.get("timeline_modifications", []))
    for mod in inc.get("timeline_modifications", []):
        trait = mod.get("trait", "").strip()
        cid = mod.get("introduced_chunk_id", current_chunk_id)
        if trait and not any(m.get("trait", "").lower() == trait.lower() for m in merged_mods):
            merged_mods.append({"introduced_chunk_id": cid, "trait": trait})

    # 3. Merge Wardrobe Timeline & Alternate Attires
    merged_wardrobe = list(ex.get("wardrobe_timeline", []))
    for w in inc.get("wardrobe_timeline", []):
        attire = w.get("attire", "").strip()
        cid = w.get("from_chunk_id", current_chunk_id)
        ctx = w.get("context", "Scene")
        if attire and not any(m.get("attire", "").lower() == attire.lower() and m.get("from_chunk_id") == cid for m in merged_wardrobe):
            merged_wardrobe.append({"from_chunk_id": cid, "context": ctx, "attire": attire})

    merged_alt = dict(ex.get("alternate_attires", {}))
    merged_alt.update(inc.get("alternate_attires", {}))

    default_attire = ex.get("default_attire") or inc.get("default_attire") or ""

    return CharacterProfile({
        "base_dna": merged_dna,
        "timeline_modifications": merged_mods,
        "wardrobe_timeline": merged_wardrobe,
        "default_attire": default_attire,
        "alternate_attires": merged_alt
    })


def merge_setting_profile(existing: str, incoming: str, max_chars: int = 400) -> str:
    """
    Dedupes and merges setting descriptions across batches without runaway string bloat.
    """
    if not existing:
        return incoming
    if not incoming:
        return existing
    if incoming.lower() in existing.lower():
        return existing

    ex_words = set(re.findall(r"\w+", existing.lower()))
    in_words = set(re.findall(r"\w+", incoming.lower()))
    if not in_words:
        return existing

    overlap = len(ex_words & in_words) / len(in_words)
    if overlap >= 0.65:
        if len(incoming) > len(existing) and len(incoming) <= max_chars:
            return incoming
        return existing

    combined = f"{existing}; {incoming}"
    if len(combined) <= max_chars:
        return combined
    return existing


def resolve_character_audit_for_scene(
    char_entry: Union[str, Dict[str, Any]],
    chunk_id: str,
    setting_name: str = "",
    beat_attire_override: str = ""
) -> Dict[str, Any]:
    """
    Chronologically and contextually resolves a character's appearance for a specific scene,
    returning structured audit metadata alongside the resolved prompt description.
    """
    norm = normalize_character_entry(char_entry)
    target_idx = chunk_num(chunk_id)

    # 1. Base DNA
    base_dna = norm.get("base_dna", "").strip()
    traits = []
    if base_dna:
        traits.append(base_dna)

    # 2. Timeline Modifications (active vs skipped)
    active_mods = []
    skipped_mods = []
    for mod in norm.get("timeline_modifications", []):
        mod_cid = mod.get("introduced_chunk_id", "chunk_000")
        trait = mod.get("trait", "").strip()
        if not trait:
            continue
        if target_idx >= chunk_num(mod_cid):
            if trait.lower() not in base_dna.lower():
                traits.append(trait)
            active_mods.append({"chunk_id": mod_cid, "trait": trait})
        else:
            skipped_mods.append({"chunk_id": mod_cid, "trait": trait})

    physical_summary = ", ".join(traits) if traits else "Figure"

    # 3. Wardrobe Resolution
    attire = beat_attire_override.strip() if beat_attire_override else ""
    attire_source = "beat_override" if attire else "none"

    if not attire and norm.get("wardrobe_timeline"):
        active_entry = None
        for entry in sorted(norm["wardrobe_timeline"], key=lambda x: chunk_num(x.get("from_chunk_id", "chunk_000"))):
            if target_idx >= chunk_num(entry.get("from_chunk_id", "chunk_000")):
                active_entry = entry
        if active_entry and active_entry.get("attire"):
            attire = active_entry["attire"]
            attire_source = "wardrobe_timeline"

    if not attire and setting_name and norm.get("alternate_attires"):
        for alt_setting, alt_attire in norm["alternate_attires"].items():
            if alt_setting.lower() in setting_name.lower() or setting_name.lower() in alt_setting.lower():
                attire = alt_attire
                attire_source = "setting_alternate"
                break

    if not attire and norm.get("default_attire"):
        attire = norm["default_attire"]
        attire_source = "default_attire"

    full_desc = physical_summary
    if attire:
        if attire.lower() not in physical_summary.lower():
            full_desc = f"{physical_summary}; Attire: {attire}"

    return {
        "base_dna": base_dna,
        "active_timeline_mods": active_mods,
        "skipped_timeline_mods": skipped_mods,
        "resolved_attire": attire,
        "attire_source": attire_source,
        "full_description": full_desc
    }


def resolve_character_for_scene(
    char_entry: Union[str, Dict[str, Any]],
    chunk_id: str,
    setting_name: str = "",
    beat_attire_override: str = ""
) -> str:
    """
    Chronologically and contextually resolves a character's appearance for a specific scene:
    1. Base physical DNA (face, hair, build, age).
    2. Active timeline modifications (where introduced_chunk_id <= target_chunk_id).
    3. Active wardrobe (beat override -> wardrobe timeline -> alternate attire -> default attire).
    """
    audit = resolve_character_audit_for_scene(
        char_entry=char_entry,
        chunk_id=chunk_id,
        setting_name=setting_name,
        beat_attire_override=beat_attire_override
    )
    return audit["full_description"]


def match_bible_entity(name: str, bible_dict: Dict[str, Any]) -> Optional[Tuple[str, Any]]:
    """
    Fuzzy and case-insensitive resolution of a character or setting name against the Visual Bible.
    Handles partial matches (e.g. 'Lyra' matching 'Lyra (Mechanic)' or 'Catwalks' matching 'The Rust Catwalks').
    """
    if not name or not bible_dict:
        return None
    name_clean = name.strip().lower()

    # 1. Exact match (case-insensitive)
    for k, v in bible_dict.items():
        if k.strip().lower() == name_clean:
            return k, v

    # 2. Key contains query or query contains key
    for k, v in bible_dict.items():
        k_clean = k.strip().lower()
        if name_clean in k_clean or k_clean in name_clean:
            return k, v

    # 3. Word token overlap
    name_words = set(re.findall(r"\w+", name_clean))
    best_match = None
    best_score = 0
    for k, v in bible_dict.items():
        k_words = set(re.findall(r"\w+", k.strip().lower()))
        overlap = len(name_words.intersection(k_words))
        if overlap > best_score:
            best_score = overlap
            best_match = (k, v)

    if best_match and best_score > 0:
        return best_match

    return None


def run_stage_bible(
    project_dir: str,
    llm_client: LMStudioClient,
    llm_config: Dict[str, Any],
    callback: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Step 2: Visual Bible Extraction.
    Analyzes story text directly to extract:
    1. Global art style inferred from story tone and genre
    2. Character visual profiles (physical traits, distinguishing marks, clothing)
    3. Setting profiles (architecture, atmosphere, lighting)
    Dynamically partitions large stories across batches to stay safely within the loaded model's context window.
    """
    chunks_file = os.path.join(project_dir, "artifacts", "01_chunks.json")
    beats_file = os.path.join(project_dir, "artifacts", "02_selected_beats.json")
    output_file = os.path.join(project_dir, "artifacts", "03_visual_bible.json")

    if not os.path.isfile(chunks_file):
        raise FileNotFoundError(f"Missing {chunks_file}. Run chunking stage first.")

    with open(chunks_file, "r", encoding="utf-8") as f:
        chunks_data = json.load(f)

    chunks = chunks_data.get("chunks", [])
    if not chunks:
        return {"global_art_style": "", "characters": {}, "settings": {}}

    # Check if beats already exist for seeding known names
    known_chars = set()
    known_settings = set()
    if os.path.isfile(beats_file):
        try:
            with open(beats_file, "r", encoding="utf-8") as f:
                bdata = json.load(f)
            for b in bdata.get("selected_beats", []):
                for c in b.get("characters_present", []):
                    if c and c.strip(): known_chars.add(c.strip())
                if b.get("setting"): known_settings.add(b.get("setting").strip())
        except Exception:
            pass

    char_list = sorted(list(known_chars))
    setting_list = sorted(list(known_settings))

    role_cfg = llm_config.get("roles", {}).get("structured_analyst", {})
    model = role_cfg.get("model", "thedrummer_orion-26b-a4b-v1")
    temperature = role_cfg.get("temperature", 0.2)
    max_tokens = role_cfg.get("max_tokens", -1)
    system_prompt = role_cfg.get(
        "system_prompt",
        "You are an expert cinematic visual continuity supervisor. "
        "Analyze the story text to compile a comprehensive Visual Bible compendium. "
        "Infer a cohesive global art style, and extract exhaustive physical visual descriptions "
        "for every character (build, face, hair, distinctive features/prosthetic limbs, clothing) "
        "and setting (architecture, textures, lighting). Format cleanly using GLOBAL ART STYLE:, "
        "CHARACTER: <Name>, and SETTING: <Name> tags."
    )

    resolved_model = llm_client.resolve_model(model)
    n_ctx = llm_client.get_model_context_size(resolved_model)

    # Reserve token budget for system prompt, instructions, known hints, and output tokens
    reserved_tokens = 2200
    chunk_token_budget = max(2048, n_ctx - reserved_tokens)

    # Calculate total tokens for all chunks
    total_tokens = sum(estimate_tokens(c["text"]) + 8 for c in chunks)

    # Check whether all chunks fit comfortably in a single pass or need batching
    if total_tokens <= chunk_token_budget:
        chunk_batches = [chunks]
    else:
        chunk_batches = []
        curr_batch = []
        curr_tokens = 0
        for c in chunks:
            c_tok = estimate_tokens(c["text"]) + 8
            if curr_batch and (curr_tokens + c_tok > chunk_token_budget):
                chunk_batches.append(curr_batch)
                curr_batch = [c]
                curr_tokens = c_tok
            else:
                curr_batch.append(c)
                curr_tokens += c_tok
        if curr_batch:
            chunk_batches.append(curr_batch)

    total_batches = len(chunk_batches)
    msg = f"Extracting Visual Bible using model '{resolved_model}' (context size: {n_ctx} tokens, {total_batches} batch(es))..."
    print(f"[*] {msg}", flush=True)
    if callback: callback(msg)

    known_hint = ""
    if char_list or setting_list:
        known_hint = f"\nFocus on these known entities if present in the text:\nCharacters: {', '.join(char_list)}\nSettings: {', '.join(setting_list)}\n"

    accumulated_bible: Dict[str, Any] = {
        "global_art_style": "",
        "characters": {},
        "settings": {}
    }

    for b_idx, b_chunks in enumerate(chunk_batches, 1):
        b_sample = "\n\n".join([f"[{c['chunk_id']}]: {c['text']}" for c in b_chunks])
        first_cid = b_chunks[0]["chunk_id"]
        last_cid = b_chunks[-1]["chunk_id"]
        status_msg = f"Visual Bible: processing batch {b_idx}/{total_batches} ({first_cid} to {last_cid})..."
        print(f"  -> {status_msg}", flush=True)
        if callback: callback(status_msg)

        if b_idx == 1:
            user_prompt = f"""STORY TEXT (PART {b_idx}/{total_batches}):
{b_sample}
{known_hint}
Extract the visual continuity bible for this story:
1. GLOBAL ART STYLE: A concise artistic aesthetic, color palette, and rendering medium for illustrating this story consistently (e.g. "1980s dark anime aesthetic, muted earth tones, cinematic cel shading").
2. CHARACTERS: Identify all characters with exhaustive physical appearance, face, hair, distinctive features (e.g. mechanical/prosthetic limbs, scars), and clothing.
3. SETTINGS: Identify all locations/settings with architecture, materials, lighting, atmosphere, and visual textures.

Format cleanly as:
GLOBAL ART STYLE: <style description>
CHARACTER: <Name>: <exhaustive physical appearance, distinctive features, clothing>
SETTING: <Name>: <visual environment description, materials, textures, lighting>
"""
        else:
            # Multi-batch continuation pass
            existing_chars = "\n".join([f"- {k}: {v}" for k, v in accumulated_bible["characters"].items()])
            existing_settings = "\n".join([f"- {k}: {v}" for k, v in accumulated_bible["settings"].items()])
            existing_section = f"""[ESTABLISHED VISUAL CONTINUITY BIBLE FROM PRECEDING CHUNKS]
Global Art Style: {accumulated_bible['global_art_style']}

Established Characters:
{existing_chars if existing_chars else 'None'}

Established Settings:
{existing_settings if existing_settings else 'None'}
"""
            user_prompt = f"""{existing_section}
STORY TEXT (PART {b_idx}/{total_batches}, chunks {first_cid} to {last_cid}):
{b_sample}

Analyze this new story section to expand and update the Visual Continuity Bible:
1. NEW CHARACTERS: Identify any new characters introduced with exhaustive physical appearance, face, hair, clothing, and distinctive features.
2. EXISTING CHARACTER UPDATES: ONLY mention an established character if they undergo a new permanent physical transformation (scar, injury, amputation, haircut) or wear a new distinct costume/attire in this scene. If their physical appearance is unchanged, DO NOT output them.
   - For costume changes: CHARACTER: <Name>: Costume Change [{first_cid}] (<Setting/Context>): <attire details>
   - For permanent physical changes: CHARACTER: <Name>: Physical Change [{first_cid}]: <new scar or permanent modification>
3. NEW SETTINGS: Identify any newly visited locations with architecture, materials, lighting, atmosphere, and textures.
4. GLOBAL ART STYLE: Maintain the established cohesive global art style.

Format cleanly as:
GLOBAL ART STYLE: <style description>
CHARACTER: <Name>: <exhaustive physical appearance, distinctive features, clothing>
SETTING: <Name>: <visual environment description, materials, textures, lighting>
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        raw_resp = llm_client.chat_text(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        batch_bible = parse_bible_response(raw_resp, char_list, setting_list)

        # Merge batch_bible into accumulated_bible
        if batch_bible.get("global_art_style"):
            if not accumulated_bible["global_art_style"] or len(batch_bible["global_art_style"]) > len(accumulated_bible["global_art_style"]):
                accumulated_bible["global_art_style"] = batch_bible["global_art_style"]

        for cname, cdesc in batch_bible.get("characters", {}).items():
            if not cdesc:
                continue
            matched = match_bible_entity(cname, accumulated_bible["characters"])
            if matched:
                existing_key, existing_val = matched
                accumulated_bible["characters"][existing_key] = merge_character_profile(existing_val, cdesc, first_cid)
            else:
                accumulated_bible["characters"][cname] = normalize_character_entry(cdesc, first_cid)

        for sname, sdesc in batch_bible.get("settings", {}).items():
            if not sdesc:
                continue
            matched = match_bible_entity(sname, accumulated_bible["settings"])
            if matched:
                existing_key, existing_val = matched
                accumulated_bible["settings"][existing_key] = merge_setting_profile(existing_val, sdesc)
            else:
                accumulated_bible["settings"][sname] = sdesc

    # Infer story-tailored style presets (6 Art Mediums + 3 Photography Eras)
    infer_notice = "Inferring story-tailored style presets (6 Art Mediums, 3 Photography Eras)..."
    print(f"[*] {infer_notice}", flush=True)
    if callback: callback(infer_notice)

    theme_text = accumulated_bible.get("global_art_style", "")
    art_styles = infer_styles(llm_client, model=model, theme_text=theme_text, category="art", count=6)
    photo_styles = infer_styles(llm_client, model=model, theme_text=theme_text, category="photography", count=3)

    accumulated_bible["style_presets"] = {
        "art": art_styles,
        "photography": photo_styles
    }

    if not accumulated_bible.get("active_style") and art_styles:
        accumulated_bible["active_style"] = art_styles[0]
        if not accumulated_bible.get("global_art_style"):
            accumulated_bible["global_art_style"] = art_styles[0].get("description", "")

    # Merge into universal global library
    try:
        proj_slug = os.path.basename(os.path.normpath(project_dir))
        merge_into_global_styles(art_styles, category="art", source_project=proj_slug)
        merge_into_global_styles(photo_styles, category="photography", source_project=proj_slug)
    except Exception as ge:
        print(f"[!] Note: Could not merge into global styles: {ge}")

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(accumulated_bible, f, indent=2, ensure_ascii=False)

    done_msg = f"Visual Bible completed across {total_batches} batch(es): {len(accumulated_bible.get('characters', {}))} characters, {len(accumulated_bible.get('settings', {}))} settings, {len(art_styles)} art presets, {len(photo_styles)} photo presets -> 03_visual_bible.json"
    print(f"[+] {done_msg}", flush=True)
    if callback: callback(done_msg)
    return accumulated_bible


def run_stage_beats(
    project_dir: str,
    llm_client: LMStudioClient,
    llm_config: Dict[str, Any],
    callback: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Step 3: Sliding Window Beat Selection.
    Target: 5 chunks (dynamically scaled for context size), Context: 2 chunks.
    Selects 0 to N visual moments based on established Visual Bible context.
    """
    chunks_file = os.path.join(project_dir, "artifacts", "01_chunks.json")
    bible_file = os.path.join(project_dir, "artifacts", "03_visual_bible.json")
    output_file = os.path.join(project_dir, "artifacts", "02_selected_beats.json")

    if not os.path.isfile(chunks_file):
        raise FileNotFoundError(f"Missing {chunks_file}. Run chunking stage first.")

    with open(chunks_file, "r", encoding="utf-8") as f:
        chunks_data = json.load(f)

    chunks = chunks_data.get("chunks", [])
    if not chunks:
        return {"selected_beats": []}

    # Load visual bible context if available
    bible_context = ""
    if os.path.isfile(bible_file):
        try:
            with open(bible_file, "r", encoding="utf-8") as f:
                bdata = json.load(f)
            chars = list(bdata.get("characters", {}).keys())
            settings = list(bdata.get("settings", {}).keys())
            style = bdata.get("global_art_style", "")
            bible_context = f"[ESTABLISHED VISUAL CONTINUITY BIBLE]\nArt Style: {style}\nEstablished Characters: {', '.join(chars) if chars else 'None'}\nEstablished Settings: {', '.join(settings) if settings else 'None'}\n"
        except Exception:
            pass

    role_cfg = llm_config.get("roles", {}).get("narrative_director", {})
    model = role_cfg.get("model", "command-r-08-2024")
    temperature = role_cfg.get("temperature", 0.3)
    max_tokens = role_cfg.get("max_tokens", -1)
    system_prompt = role_cfg.get(
        "system_prompt",
        "You are an expert narrative director identifying key visual illustration moments from story paragraphs. "
        "Select 0 to N beats based purely on dramatic visual impact. "
        "Only select beats occurring in the TARGET chunks."
    )

    resolved_model = llm_client.resolve_model(model)
    n_ctx = llm_client.get_model_context_size(resolved_model)
    max_prompt_budget = max(2048, n_ctx - 1500)

    target_size = 5
    context_size = 2

    all_beats: List[Dict[str, Any]] = []
    seen_chunk_ids = set()

    msg = f"Step 3: Beat Selection across {len(chunks)} chunks using model '{resolved_model}' (context window: {n_ctx} tokens)..."
    print(f"[*] {msg}", flush=True)
    if callback: callback(msg)

    start_idx = 0
    window_idx = 0

    while start_idx < len(chunks):
        window_idx += 1
        # Dynamically scale target_size down if chunks in this window are dense
        curr_target_size = min(target_size, len(chunks) - start_idx)
        while curr_target_size > 1:
            test_target = chunks[start_idx:start_idx + curr_target_size]
            test_context = chunks[max(0, start_idx - context_size):start_idx]
            est_tokens = (
                estimate_tokens(bible_context) +
                estimate_tokens(system_prompt) +
                sum(estimate_tokens(c["text"]) + 10 for c in test_context) +
                sum(estimate_tokens(c["text"]) + 10 for c in test_target) +
                400
            )
            if est_tokens <= max_prompt_budget:
                break
            curr_target_size -= 1

        target_chunks = chunks[start_idx:start_idx + curr_target_size]
        target_ids = {c["chunk_id"] for c in target_chunks}

        context_start = max(0, start_idx - context_size)
        context_chunks = chunks[context_start:start_idx]

        context_text = "\n\n".join([f"[{c['chunk_id']}]: {c['text']}" for c in context_chunks])
        target_text = "\n\n".join([f"[{c['chunk_id']}]: {c['text']}" for c in target_chunks])

        status_msg = f"Analyzing Window {window_idx} ({', '.join(sorted(target_ids))}) with model '{resolved_model}'..."
        print(f"  -> {status_msg}", flush=True)
        if callback: callback(status_msg)

        user_prompt = f"""{bible_context}
[PREVIOUS CONTEXT - DO NOT SELECT BEATS HERE]
{context_text if context_text else "None (Beginning of story)"}

[TARGET SCENE CHUNKS - SELECT 0 TO N ILLUSTRATION BEATS FROM THESE CHUNKS ONLY]
{target_text}

Identify if any key visual moments in the TARGET chunks warrant an illustration.
Target chunks available: {", ".join(sorted(target_ids))}

For each illustration beat, provide:
[BEAT]
Chunk: chunk_xxx (must match one of the target chunks)
Scene Type: landscape, portrait, or square
Characters: character names present (or None)
Attire: character clothing in this specific scene (e.g. Elena: emerald gown; Vance: formal doublet), or Default
Setting: location name
Action: description of the visual moment
Camera: shot angle, framing, and lighting

If no illustration is warranted for these chunks, simply reply:
NONE
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        raw_resp = llm_client.chat_text(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        beats = parse_beats_response(raw_resp, target_ids)

        for b in beats:
            cid = b.get("chunk_id")
            if cid in target_ids and cid not in seen_chunk_ids:
                seen_chunk_ids.add(cid)
                all_beats.append(b)

        start_idx += curr_target_size

    all_beats.sort(key=lambda x: x.get("chunk_id", ""))
    result = {"selected_beats": all_beats}

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    done_msg = f"Beat selection completed: {len(all_beats)} beats selected -> 02_selected_beats.json"
    print(f"[+] {done_msg}", flush=True)
    if callback: callback(done_msg)
    return result


def run_stage_manifest(
    project_dir: str,
    llm_client: LMStudioClient,
    llm_config: Dict[str, Any],
    callback: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Step 4: Config-Driven Prompt Synthesis.
    Combines 01_chunks, 02_selected_beats, 03_visual_bible, and diffusion_profiles.json
    into the master execution checkpoint: manifest.json.
    Seamlessly injects character physical traits and setting environment from the Visual Bible
    with the scene action beat and camera framing.
    """
    chunks_file = os.path.join(project_dir, "artifacts", "01_chunks.json")
    beats_file = os.path.join(project_dir, "artifacts", "02_selected_beats.json")
    bible_file = os.path.join(project_dir, "artifacts", "03_visual_bible.json")
    profiles_file = os.path.join(project_dir, "config", "diffusion_profiles.json")
    output_file = os.path.join(project_dir, "artifacts", "manifest.json")

    for req_file in [chunks_file, beats_file, bible_file, profiles_file]:
        if not os.path.isfile(req_file):
            raise FileNotFoundError(f"Missing required file {req_file} for prompt synthesis.")

    with open(chunks_file, "r", encoding="utf-8") as f:
        chunks_data = json.load(f)
    with open(beats_file, "r", encoding="utf-8") as f:
        beats_data = json.load(f)
    with open(bible_file, "r", encoding="utf-8") as f:
        bible = json.load(f)
    with open(profiles_file, "r", encoding="utf-8") as f:
        profiles_config = json.load(f)

    chunks = chunks_data.get("chunks", [])
    beats = beats_data.get("selected_beats", [])
def compose_prompt_context_for_beat(
    beat: Dict[str, Any],
    bible: Dict[str, Any],
    chunks: List[Dict[str, Any]],
    profile: Dict[str, Any],
    active_profile_name: str,
    llm_config: Dict[str, Any],
    model_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Composes the full prompt synthesis context for a single beat, returning both
    the structured audit breakdown and the exact system & user prompts sent to the LLM.
    """
    cid = beat.get("chunk_id", "chunk_000")
    scene_type = beat.get("scene_type", "landscape")
    aspect_ratios = profile.get("aspect_ratios", {
        "landscape": {"width": 1344, "height": 768},
        "portrait": {"width": 832, "height": 1216},
        "square": {"width": 1024, "height": 1024}
    })
    dims = aspect_ratios.get(scene_type, aspect_ratios.get("landscape", {"width": 1344, "height": 768}))

    profile_system_prompt = profile.get(
        "system_prompt",
        "You are an expert diffusion prompt synthesizer. You synthesize rich, cohesive image prompts "
        "by seamlessly blending the character's explicit physical appearance and distinctive features from "
        "the Visual Bible, the setting's textures and architecture from the Visual Bible, the scene action beat, "
        "camera framing, and the global art style."
    )
    default_negative = profile.get("default_negative", "")
    positive_prefix = profile.get("positive_prefix", "").strip()

    role_cfg = llm_config.get("roles", {}).get("prompt_synthesizer", {})
    resolved_model = model_name or role_cfg.get("model", "thedrummer_orion-26b-a4b-v1")
    temperature = role_cfg.get("temperature", 0.35)

    # 1. Setting Resolution
    setting_name = beat.get("setting", "")
    matched_setting = match_bible_entity(setting_name, bible.get("settings", {}))
    if matched_setting:
        sname, sdesc = matched_setting
        setting_desc = f"{sname} (Environment details: {sdesc})"
        setting_audit = {
            "name": setting_name,
            "matched_key": sname,
            "description": sdesc,
            "formatted": setting_desc
        }
    else:
        setting_desc = setting_name or "Atmospheric cinematic environment"
        setting_audit = {
            "name": setting_name,
            "matched_key": None,
            "description": None,
            "formatted": setting_desc
        }

    # 2. Characters Resolution
    chars_present = beat.get("characters_present", [])
    char_attire_map = beat.get("character_attire", {})
    resolved_chars_strings = []
    resolved_chars_audit = []

    for name in chars_present:
        matched = match_bible_entity(name, bible.get("characters", {}))
        if matched:
            cname, cdesc = matched
            override_attire = char_attire_map.get(name) or char_attire_map.get(cname, "")
            audit = resolve_character_audit_for_scene(cdesc, cid, setting_name=setting_name, beat_attire_override=override_attire)
            resolved_chars_strings.append(f"{cname} (Visual Traits: {audit['full_description']})")
            audit["name"] = name
            audit["matched_key"] = cname
            resolved_chars_audit.append(audit)
        else:
            resolved_chars_strings.append(name)
            resolved_chars_audit.append({
                "name": name,
                "matched_key": None,
                "base_dna": "",
                "active_timeline_mods": [],
                "skipped_timeline_mods": [],
                "resolved_attire": char_attire_map.get(name, ""),
                "attire_source": "beat_override" if char_attire_map.get(name) else "unmatched",
                "full_description": name
            })

    # Fallback: scan chunk text if no characters were explicitly listed
    if not resolved_chars_strings:
        chunk_text = ""
        for c in chunks:
            if c.get("chunk_id") == cid:
                chunk_text = c.get("text", "")
                break
        for b_name, b_desc in bible.get("characters", {}).items():
            if b_name.lower() in chunk_text.lower():
                override_attire = char_attire_map.get(b_name, "")
                audit = resolve_character_audit_for_scene(b_desc, cid, setting_name=setting_name, beat_attire_override=override_attire)
                resolved_chars_strings.append(f"{b_name} (Visual Traits: {audit['full_description']})")
                audit["name"] = b_name
                audit["matched_key"] = b_name
                resolved_chars_audit.append(audit)

    char_info = "; ".join(resolved_chars_strings) if resolved_chars_strings else "No prominent characters specified."

    prefix_instruction = f"- Positive Prompt Prefix (Must be included at the beginning): {positive_prefix}\n" if positive_prefix else ""
    user_prompt = f"""SCENE COMPOSITION REQUIREMENTS:
- Action Beat: {beat.get('action_beat', '')}
- Camera Framing & Lighting: {beat.get('camera_framing', '')}
- Characters Present (Explicit physical appearance from Visual Bible):
  {char_info}
- Setting / Environment (Architectural details & textures from Visual Bible):
  {setting_desc}
- Global Art Style & Medium: {bible.get('global_art_style', '')}
- Target Aspect Ratio: {scene_type} ({dims['width']}x{dims['height']})
{prefix_instruction}- Default Negative Prompt: {default_negative}

SYNTHESIZE THE DIFFUSION PROMPT:
Construct a high-quality positive diffusion prompt that seamlessly combines:
1. The character's specific physical traits (face, hair, build, distinctive prosthetic limbs/features, clothing).
2. The exact scene action beat.
3. The setting architecture, textures, and atmosphere.
4. The camera framing, angle, and lighting.
5. The global art style.

Format your output simply as:
PROMPT: <positive prompt string>
NEGATIVE: <negative prompt string>
"""

    return {
        "chunk_id": cid,
        "scene_type": scene_type,
        "dimensions": dims,
        "active_profile": active_profile_name,
        "setting": setting_audit,
        "characters": resolved_chars_audit,
        "action_beat": beat.get("action_beat", ""),
        "camera_framing": beat.get("camera_framing", ""),
        "global_art_style": bible.get("global_art_style", ""),
        "positive_prefix": positive_prefix,
        "default_negative": default_negative,
        "system_prompt": profile_system_prompt,
        "raw_user_prompt": user_prompt,
        "model": resolved_model,
        "temperature": temperature
    }


def run_stage_manifest(
    project_dir: str,
    llm_client: LMStudioClient,
    llm_config: Dict[str, Any],
    callback: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Stage 4: Master Manifest & Prompt Synthesis.
    Reads:
      - 01_chunks.json
      - 02_selected_beats.json
      - 03_visual_bible.json
      - diffusion_profiles.json
    Synthesizes positive/negative prompts for each selected beat using the active profile.
    Produces: manifest.json with full prompt context audit trail stored per illustration block.
    """
    chunks_file = os.path.join(project_dir, "artifacts", "01_chunks.json")
    beats_file = os.path.join(project_dir, "artifacts", "02_selected_beats.json")
    bible_file = os.path.join(project_dir, "artifacts", "03_visual_bible.json")
    profiles_file = os.path.join(project_dir, "config", "diffusion_profiles.json")
    output_file = os.path.join(project_dir, "artifacts", "manifest.json")

    for fpath in [chunks_file, beats_file, bible_file, profiles_file]:
        if not os.path.isfile(fpath):
            raise FileNotFoundError(f"Missing prerequisite artifact: {fpath}")

    with open(chunks_file, "r", encoding="utf-8") as f:
        chunks_data = json.load(f)
    with open(beats_file, "r", encoding="utf-8") as f:
        beats_data = json.load(f)
    with open(bible_file, "r", encoding="utf-8") as f:
        bible = json.load(f)
    with open(profiles_file, "r", encoding="utf-8") as f:
        profiles_config = json.load(f)

    chunks = chunks_data.get("chunks", [])
    beats = beats_data.get("selected_beats", [])
    active_profile_name = profiles_config.get("active_profile", "sdxl_base")
    profile = profiles_config.get("profiles", {}).get(active_profile_name, {})

    default_negative = profile.get("default_negative", "")
    positive_prefix = profile.get("positive_prefix", "").strip()

    role_cfg = llm_config.get("roles", {}).get("prompt_synthesizer", {})
    model = role_cfg.get("model", "thedrummer_orion-26b-a4b-v1")
    temperature = role_cfg.get("temperature", 0.35)
    max_tokens = role_cfg.get("max_tokens", -1)

    resolved_model = llm_client.resolve_model(model)
    msg = f"Step 4: Synthesizing prompts for {len(beats)} beats using profile '{active_profile_name}' and model '{resolved_model}'..."
    print(f"[*] {msg}")
    if callback: callback(msg)

    illustrations_by_chunk: Dict[str, Dict[str, Any]] = {}

    for idx, beat in enumerate(beats, 1):
        cid = beat["chunk_id"]

        # Compose context with full Visual Bible and timeline resolution
        ctx = compose_prompt_context_for_beat(
            beat=beat,
            bible=bible,
            chunks=chunks,
            profile=profile,
            active_profile_name=active_profile_name,
            llm_config=llm_config,
            model_name=resolved_model
        )

        status_msg = f"Synthesizing prompt {idx}/{len(beats)} for {cid} with model '{resolved_model}'..."
        print(f"  -> {status_msg}")
        if callback: callback(status_msg)

        messages = [
            {"role": "system", "content": ctx["system_prompt"]},
            {"role": "user", "content": ctx["raw_user_prompt"]}
        ]

        raw_resp = llm_client.chat_text(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        prompt_text, neg_prompt = parse_prompt_response(raw_resp, default_negative)

        # Prompt generation failure visibility: do not mask failures with synthetic fallbacks
        if not prompt_text or not prompt_text.strip():
            raise RuntimeError(
                f"Prompt synthesis failed for {cid}: model '{resolved_model}' produced an empty or unparseable prompt. "
                f"Raw model response: {raw_resp[:200]!r}"
            )

        # Apply positive_prefix if specified and not already prepended
        if positive_prefix:
            clean_prefix = positive_prefix.rstrip(" ,")
            if not prompt_text.lower().startswith(clean_prefix.lower()):
                prompt_text = f"{clean_prefix}, {prompt_text.lstrip(' ,')}"

        if not neg_prompt or not neg_prompt.strip():
            neg_prompt = default_negative

        active_style = bible.get("active_style") or {
            "id": "custom",
            "name": "Default Style",
            "description": bible.get("global_art_style", ""),
            "category": "art"
        }

        illustrations_by_chunk[cid] = {
            "status": "pending",
            "image_file": f"images/{cid}.png",
            "width": ctx["dimensions"]["width"],
            "height": ctx["dimensions"]["height"],
            "prompt": prompt_text,
            "negative_prompt": neg_prompt,
            "style": active_style,
            "llm_context": ctx
        }

    story_title = os.path.basename(os.path.abspath(project_dir)).replace("_", " ").title()

    # Load existing manifest to preserve past multi-workflow/multi-style illustrations
    existing_blocks_by_cid = {}
    if os.path.isfile(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                old_m = json.load(f)
                for b in old_m.get("blocks", []):
                    existing_blocks_by_cid[b.get("chunk_id")] = b
        except Exception:
            pass

    blocks = []
    for chunk in chunks:
        cid = chunk["chunk_id"]
        illus = illustrations_by_chunk.get(cid, None)
        old_b = existing_blocks_by_cid.get(cid, {})
        old_illustrations = old_b.get("illustrations", {})

        block_data = {
            "chunk_id": cid,
            "text": chunk["text"],
            "illustration": illus
        }
        if old_illustrations:
            block_data["illustrations"] = old_illustrations

        blocks.append(block_data)

    active_style = bible.get("active_style") or {
        "id": "custom",
        "name": "Default Style",
        "description": bible.get("global_art_style", ""),
        "category": "art"
    }

    manifest = {
        "story_title": story_title,
        "active_profile": active_profile_name,
        "active_style": active_style,
        "blocks": blocks
    }

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    total_illus = sum(1 for b in blocks if b.get("illustration") is not None)
    done_msg = f"Master manifest generated: {total_illus} illustrations scheduled -> manifest.json"
    print(f"[+] {done_msg}")
    if callback: callback(done_msg)
    return manifest


def run_phase_1(
    project_dir: str,
    stage: str = "all",
    callback: Optional[Callable[[str], None]] = None,
    backend: Optional[str] = None,
    llm_api_base: Optional[str] = None,
    llm_api_key: Optional[str] = None,
    context_window: Optional[int] = None
) -> Dict[str, Any]:
    """Runs Phase 1 stages in logical sequence: chunk -> bible -> beats -> manifest."""
    print_banner(stage)
    config_file = os.path.join(project_dir, "config", "llm_models.json")
    if not os.path.isfile(config_file):
        raise FileNotFoundError(f"Missing config: {config_file}")

    llm_config = load_llm_config(config_file)
    api_base = llm_api_base or llm_config.get("api_base", "http://localhost:1234/v1")
    api_key = llm_api_key or llm_config.get("api_key")
    resolved_backend = backend or llm_config.get("backend", "lm_studio")
    ctx_win = context_window or llm_config.get("context_window")

    client = LMStudioClient(
        api_base=api_base,
        api_key=api_key,
        backend=resolved_backend,
        context_window=ctx_win
    )

    if stage in ["bible", "beats", "manifest", "all"]:
        check_runtime_readiness(client)

    result = {}
    if stage in ["chunk", "all"]:
        result["chunks"] = run_stage_chunk(project_dir, callback)
    if stage in ["bible", "all"]:
        result["bible"] = run_stage_bible(project_dir, client, llm_config, callback)
    if stage in ["beats", "all"]:
        result["beats"] = run_stage_beats(project_dir, client, llm_config, callback)
    if stage in ["manifest", "all"]:
        result["manifest"] = run_stage_manifest(project_dir, client, llm_config, callback)

    return result


def main():
    parser = argparse.ArgumentParser(description="Phase 1: Story Analysis & Prompt Synthesis for ASI")
    parser.add_argument("--project", "-p", required=True, help="Path to project directory (e.g. ./projects/my_story)")
    parser.add_argument("--stage", "-s", choices=["chunk", "bible", "beats", "manifest", "all"], default="all",
                        help="Pipeline stage to execute (default: all)")
    parser.add_argument("--backend", choices=["lm_studio", "openai_compatible"], help="LLM backend (default: from config or lm_studio)")
    parser.add_argument("--llm-api-base", help="Custom OpenAI-compatible LLM endpoint URL")
    parser.add_argument("--llm-api-key", help="API key for custom LLM endpoint")
    parser.add_argument("--context-window", type=int, help="Override context window size in tokens")
    args = parser.parse_args()

    run_phase_1(
        args.project,
        stage=args.stage,
        backend=args.backend,
        llm_api_base=args.llm_api_base,
        llm_api_key=args.llm_api_key,
        context_window=args.context_window
    )


if __name__ == "__main__":
    main()
