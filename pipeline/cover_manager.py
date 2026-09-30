"""
pipeline/cover_manager.py: Complete Cover Studio & Typography Compositor for Automated Story Illustrator.
Supports:
1. Cover Prompt Synthesis via LLM using Visual Bible (Protagonist DNA, Setting, Art Style).
2. Direct Cover Rendering via ComfyUI (832x1344 standard / 1600x2560 highres).
3. Professional Typography Compositor (Title, Subtitle, Author with gradient scrims & drop shadows).
4. Existing Scene Selection (converts any story chunk image into an official KDP cover).
"""

import os
import re
import json
from typing import Dict, Any, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pipeline.project_manager import get_dimensions_for_tier
from pipeline.llm_client import LMStudioClient, load_llm_config, parse_prompt_response


def get_system_font(font_family: str = "serif", bold: bool = True, size: int = 40) -> ImageFont.FreeTypeFont:
    """Safely loads a system TrueType font on Windows/Linux or falls back to default."""
    font_dirs = [
        "C:\\Windows\\Fonts",
        "/usr/share/fonts/truetype",
        "/System/Library/Fonts"
    ]
    candidates = []
    if font_family == "serif":
        if bold:
            candidates = ["georgiab.ttf", "timesbd.ttf", "cambriab.ttf", "georgia.ttf", "times.ttf"]
        else:
            candidates = ["georgia.ttf", "times.ttf", "cambria.ttf"]
    else:  # sans-serif / modern
        if bold:
            candidates = ["seguisb.ttf", "arialbd.ttf", "calibrib.ttf", "segoeui.ttf", "arial.ttf"]
        else:
            candidates = ["segoeui.ttf", "arial.ttf", "calibri.ttf"]

    for fdir in font_dirs:
        if os.path.isdir(fdir):
            for c in candidates:
                p = os.path.join(fdir, c)
                if os.path.isfile(p):
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def synthesize_cover_prompt(
    manifest: Dict[str, Any],
    project_dir: str,
    llm_client: LMStudioClient,
    llm_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Synthesizes a dedicated commercial book cover diffusion prompt by extracting
    Protagonist DNA, Setting Environment, and Art Style from 03_visual_bible.json.
    """
    bible_path = os.path.join(project_dir, "artifacts", "03_visual_bible.json")
    bible = {}
    if os.path.isfile(bible_path):
        try:
            with open(bible_path, "r", encoding="utf-8") as f:
                bible = json.load(f)
        except Exception:
            pass

    story_title = manifest.get("story_title") or os.path.basename(project_dir).replace("_", " ").title()
    meta = manifest.get("metadata", {})
    author = meta.get("author", "Unknown Author")
    description = meta.get("description", "")

    # Extract Protagonist Base DNA
    characters = bible.get("characters", {})
    protagonist_desc = ""
    if characters:
        first_char = list(characters.keys())[0]
        cdata = characters[first_char]
        if isinstance(cdata, dict):
            dna = cdata.get("base_dna", "")
            protagonist_desc = f"{first_char}: {dna}"
        else:
            protagonist_desc = f"{first_char}: {cdata}"

    # Extract Setting Environment
    settings = bible.get("settings", {})
    setting_desc = ""
    if settings:
        first_setting = list(settings.keys())[0]
        sdata = settings[first_setting]
        setting_desc = f"{first_setting}: {sdata}"

    global_style = bible.get("global_art_style", "cinematic, atmospheric digital painting, highly detailed")

    system_prompt = (
        "You are an expert commercial book cover art director. Synthesize a captivating, high-impact "
        "diffusion prompt for the front cover of a novel. Adhere strictly to these rules:\n"
        "1. Hero Composition: Prominently feature the central protagonist or iconic symbolic centerpiece.\n"
        "2. Art & Medium: Use the specified global art style, cinematic rim lighting, and atmospheric depth.\n"
        "3. Negative Space Rule: Leave clear, uncluttered breathing room in the top 20% (for title typography) "
        "and lower 15% (for author name).\n"
        "4. Output format: A single evocative paragraph under 'PROMPT:', followed by 'NEGATIVE:' with unwanted elements."
    )

    user_payload = (
        f"BOOK TITLE: {story_title}\n"
        f"AUTHOR: {author}\n"
        f"SYNOPSIS/BLURB: {description}\n"
        f"PROTAGONIST DNA: {protagonist_desc or 'Central compelling protagonist in a powerful heroic stance'}\n"
        f"SETTING/WORLD: {setting_desc or 'Atmospheric narrative world'}\n"
        f"ART STYLE: {global_style}\n"
        f"TARGET ASPECT RATIO: 1:1.6 Portrait (Book Cover)\n\n"
        "Synthesize the official book cover illustration prompt:"
    )

    role_cfg = llm_config.get("roles", {}).get("prompt_synthesizer", {})
    model = role_cfg.get("model", "thedrummer_orion-26b-a4b-v1")
    temperature = role_cfg.get("temperature", 0.4)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_payload}
    ]

    raw_resp = llm_client.chat_text(messages, model=model, temperature=temperature, max_tokens=300)
    prompt_text, neg_prompt = parse_prompt_response(raw_resp, default_negative="blurry, low quality, deformed, text, watermark, logo")

    return {
        "prompt": prompt_text,
        "negative_prompt": neg_prompt,
        "story_title": story_title,
        "author": author
    }


def composite_cover_typography(
    source_image_path: str,
    title: str,
    author: str,
    output_marketing_path: str,
    output_epub_cover_path: Optional[str] = None,
    subtitle: Optional[str] = None,
    font_family: str = "serif",
    font_color: str = "gold"
) -> Tuple[str, Optional[str]]:
    """
    Overlays Title, Subtitle, and Author typography onto cover artwork:
    - Scales/crops to 1600x2560 (Amazon KDP gold standard 1:1.6).
    - Applies subtle gradient scrims at top and bottom to guarantee high legibility.
    - Emits both standalone marketing cover JPEG and embedded EPUB cover plate.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_marketing_path)), exist_ok=True)
    if output_epub_cover_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_epub_cover_path)), exist_ok=True)

    target_w, target_h = 1600, 2560

    with Image.open(source_image_path) as orig:
        orig = orig.convert("RGBA")
        ow, oh = orig.size
        orig_aspect = ow / float(oh)
        target_aspect = target_w / float(target_h)

        # Aspect fit / crop to 1600x2560
        if orig_aspect > target_aspect:
            # Source is wider: scale height to target_h and crop width
            scale = target_h / float(oh)
            new_w = int(ow * scale)
            scaled = orig.resize((new_w, target_h), Image.Resampling.LANCZOS)
            left = (new_w - target_w) // 2
            cropped = scaled.crop((left, 0, left + target_w, target_h))
        else:
            # Source is taller: scale width to target_w and crop height
            scale = target_w / float(ow)
            new_h = int(oh * scale)
            scaled = orig.resize((target_w, new_h), Image.Resampling.LANCZOS)
            top = (new_h - target_h) // 2
            cropped = scaled.crop((0, top, target_w, top + target_h))

    # Base image
    base = Image.new("RGBA", (target_w, target_h), (15, 17, 21, 255))
    base.paste(cropped, (0, 0))

    # Gradient Scrim Layer for legibility
    scrim = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)

    # Top scrim for Title (0 to 600 px, opacity 180 to 0)
    top_scrim_h = 550
    for y in range(top_scrim_h):
        alpha = int(180 * (1.0 - (y / top_scrim_h) ** 1.5))
        scrim_draw.line([(0, y), (target_w, y)], fill=(10, 12, 16, alpha))

    # Bottom scrim for Author (target_h - 450 to target_h, opacity 0 to 190)
    bottom_scrim_h = 450
    for y in range(bottom_scrim_h):
        alpha = int(190 * ((y / bottom_scrim_h) ** 1.5))
        py = target_h - bottom_scrim_h + y
        scrim_draw.line([(0, py), (target_w, py)], fill=(10, 12, 16, alpha))

    base = Image.alpha_composite(base, scrim)

    # Text Overlay Layer
    draw = ImageDraw.Draw(base)

    # Resolve Colors
    if font_color == "gold":
        primary_color = (250, 204, 21, 255)       # Amber Gold #facc15
        sub_color = (254, 240, 138, 255)          # Soft Gold #fef08a
    elif font_color == "white":
        primary_color = (255, 255, 255, 255)
        sub_color = (226, 232, 240, 255)
    elif font_color == "silver":
        primary_color = (241, 245, 249, 255)
        sub_color = (203, 213, 225, 255)
    else:
        primary_color = (255, 255, 255, 255)
        sub_color = (212, 212, 216, 255)

    shadow_color = (0, 0, 0, 220)

    # Calculate Title font size dynamically based on length
    clean_title = (title or "Illustrated Story").strip().upper()
    title_words = clean_title.split()

    # Wrap title into lines
    title_lines = []
    curr_line = []
    for w in title_words:
        curr_line.append(w)
        if len(" ".join(curr_line)) > 14:
            title_lines.append(" ".join(curr_line))
            curr_line = []
    if curr_line:
        title_lines.append(" ".join(curr_line))
    if not title_lines:
        title_lines = [clean_title]

    # Pick dynamic font size
    max_line_len = max(len(l) for l in title_lines)
    if max_line_len <= 8:
        title_size = 135
    elif max_line_len <= 14:
        title_size = 105
    else:
        title_size = 85

    title_font = get_system_font(font_family, bold=True, size=title_size)

    # Draw Title Lines
    y_start = 180
    line_spacing = int(title_size * 1.25)
    for i, line in enumerate(title_lines):
        # Center line
        bbox = title_font.getbbox(line)
        lw = bbox[2] - bbox[0]
        lx = (target_w - lw) // 2
        ly = y_start + (i * line_spacing)

        # Draw drop shadow (4 offsets for thick shadow)
        for ox, oy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 5), (0, 8)]:
            draw.text((lx + ox, ly + oy), line, font=title_font, fill=shadow_color)

        draw.text((lx, ly), line, font=title_font, fill=primary_color)

    # Draw Subtitle if present
    curr_y = y_start + (len(title_lines) * line_spacing) + 15
    if subtitle:
        sub_font = get_system_font(font_family, bold=False, size=46)
        clean_sub = subtitle.strip().title()
        s_bbox = sub_font.getbbox(clean_sub)
        sw = s_bbox[2] - s_bbox[0]
        sx = (target_w - sw) // 2
        for ox, oy in [(0, 3), (2, 2)]:
            draw.text((sx + ox, curr_y + oy), clean_sub, font=sub_font, fill=shadow_color)
        draw.text((sx, curr_y), clean_sub, font=sub_font, fill=sub_color)

    # Draw Author Name at Bottom
    clean_author = (author or "Author Unknown").strip().upper()
    # Apply wide tracking/letter spacing to author name
    spaced_author = "   ".join(clean_author.split())
    author_font = get_system_font(font_family, bold=True, size=52)
    abox = author_font.getbbox(spaced_author)
    aw = abox[2] - abox[0]
    ax = (target_w - aw) // 2
    ay = target_h - 220

    # Draw small rule above author name
    rule_w = min(400, max(200, aw // 2))
    rx1 = (target_w - rule_w) // 2
    rx2 = rx1 + rule_w
    draw.line([(rx1, ay - 30), (rx2, ay - 30)], fill=sub_color, width=2)

    for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, 4)]:
        draw.text((ax + ox, ay + oy), spaced_author, font=author_font, fill=shadow_color)
    draw.text((ax, ay), spaced_author, font=author_font, fill=primary_color)

    # Final conversion to RGB JPEG (sRGB quality 92)
    final_rgb = base.convert("RGB")
    final_rgb.save(output_marketing_path, format="JPEG", quality=92, progressive=True, optimize=True)

    if output_epub_cover_path:
        final_rgb.save(output_epub_cover_path, format="JPEG", quality=90, progressive=True, optimize=True)

    return output_marketing_path, output_epub_cover_path


def set_existing_scene_as_cover(
    manifest: Dict[str, Any],
    project_dir: str,
    chunk_id: str,
    apply_typography: bool = True,
    workflow: Optional[str] = None,
    font_family: str = "serif",
    font_color: str = "gold"
) -> Dict[str, Any]:
    """
    Selects an existing generated scene illustration as the official book cover.
    Optionally overlays Title and Author typography onto a 1600x2560 KDP canvas.
    """
    blocks = manifest.get("blocks", [])
    target_block = None
    for b in blocks:
        if b.get("chunk_id") == chunk_id:
            target_block = b
            break

    if not target_block:
        raise ValueError(f"Chunk ID '{chunk_id}' not found in manifest blocks.")

    # Find the image file path
    from pipeline.book_exporter import resolve_block_illustration
    illus_info = resolve_block_illustration(target_block, project_dir, workflow)
    if not illus_info:
        raise FileNotFoundError(f"No rendered illustration found for chunk '{chunk_id}'. Render this scene first.")

    source_img_path, prompt, _ = illus_info

    # Paths for cover outputs
    cover_dir = os.path.join(project_dir, "images", "cover")
    os.makedirs(cover_dir, exist_ok=True)
    marketing_path = os.path.join(cover_dir, "cover_kdp_marketing.jpg")
    epub_cover_path = os.path.join(cover_dir, "cover.jpg")

    meta = manifest.get("metadata", {})
    title = meta.get("title") or manifest.get("story_title") or "Illustrated Story"
    subtitle = meta.get("subtitle", "")
    author = meta.get("author", "Author Unknown")

    if apply_typography:
        composite_cover_typography(
            source_image_path=source_img_path,
            title=title,
            author=author,
            output_marketing_path=marketing_path,
            output_epub_cover_path=epub_cover_path,
            subtitle=subtitle,
            font_family=font_family,
            font_color=font_color
        )
    else:
        # Convert and save directly without text overlay
        with Image.open(source_img_path) as im:
            rgb = im.convert("RGB")
            # Scale to 1600x2560 maintaining aspect ratio with crop
            target_w, target_h = 1600, 2560
            ow, oh = rgb.size
            scale = max(target_w / float(ow), target_h / float(oh))
            nw, nh = int(ow * scale), int(oh * scale)
            scaled = rgb.resize((nw, nh), Image.Resampling.LANCZOS)
            left = (nw - target_w) // 2
            top = (nh - target_h) // 2
            cropped = scaled.crop((left, top, left + target_w, top + target_h))
            cropped.save(marketing_path, format="JPEG", quality=92, progressive=True, optimize=True)
            cropped.save(epub_cover_path, format="JPEG", quality=90, progressive=True, optimize=True)

    rel_marketing = "images/cover/cover_kdp_marketing.jpg"
    rel_cover = "images/cover/cover.jpg"

    cover_record = {
        "mode": "existing",
        "chunk_id": chunk_id,
        "image_file": rel_cover,
        "marketing_file": rel_marketing,
        "applied_typography": apply_typography,
        "prompt": prompt,
        "title": title,
        "author": author,
        "workflow": workflow
    }

    manifest["cover"] = cover_record
    manifest_path = os.path.join(project_dir, "artifacts", "manifest.json")
    from pipeline.render_images import save_manifest_atomic
    save_manifest_atomic(manifest_path, manifest)

    return cover_record
