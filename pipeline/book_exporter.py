"""
pipeline/book_exporter.py: Professional Ebook & Print Export Engine.
Produces retailer-ready files for Amazon KDP, Apple Books, Kobo, and Google Play Books:
1. High-Resolution Print-Ready PDF (via ReportLab with vector typography, running headers/footers, metadata)
2. Fixed-Layout EPUB 3.0 (FXL pre-paginated with viewport meta, Kindle tags, and cover image)
3. Reflowable EPUB (EPUB 3.0 / EPUB 2 backward compatible with EPUB3 nav and NCX fallback)
"""

import os
import re
import io
import json
import uuid
import html
import shutil
import zipfile
import datetime
import mimetypes
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image as RLImage,
    PageBreak,
    KeepTogether,
    HRFlowable
)
from reportlab.pdfgen import canvas


def build_default_copyright_text(
    title: str,
    author: str,
    publisher: str,
    c_year: str,
    illustrator: str = "",
    public_domain: bool = False
) -> str:
    """
    Constructs a professional copyright & licensing statement referencing the story metadata.
    """
    lines = []
    if public_domain:
        if author and author != "Author Unknown":
            lines.append(f"Text by {author}, in the public domain in the United States.")
        else:
            lines.append("Text in the public domain in the United States.")

        if illustrator:
            lines.append(f"Original illustrations by {illustrator}.")
            lines.append(f"Art direction and typography layout © {c_year} {publisher}.")
        else:
            lines.append(f"Original illustrations, art direction, and typography layout © {c_year} {publisher}.")
    else:
        if author and author != "Author Unknown":
            lines.append(f"Text copyright © {c_year} {author}.")
        if illustrator:
            lines.append(f"Original illustrations by {illustrator}.")
            lines.append(f"Art direction and typography layout © {c_year} {publisher}.")
        else:
            lines.append(f"Original illustrations, art direction, and typography layout © {c_year} {publisher}.")

    lines.append("All rights reserved.")
    return "\n".join(lines)


def sanitize_art_style_description(raw: str) -> str:
    """
    Strips references to AI model names, checkpoints, and pipeline tools so colophons
    reflect only pure, authentic artistic mediums and traditions.
    """
    if not raw:
        return ""
    forbidden_patterns = [
        r'\bautomated story illustrator\b',
        r'\bstory illustrator\b',
        r'\bmidjourney\b',
        r'\bdall-?e\b',
        r'\bstable diffusion\b',
        r'\bsdxl[-_a-z0-9]*\b',
        r'\bflux[-_a-z0-9]*\b',
        r'\bkrea[-_a-z0-9]*\b',
        r'\bturbo\b',
        r'\bzit\b',
        r'\blora\b',
        r'\bcheckpoint\b',
        r'\bworkflow[-_a-z0-9]*\b',
        r'\bcomfyui\b',
        r'\bcomfy\b',
        r'\bdiffusion\b',
        r'\blatent\b',
        r'\bcommand[-_]r\b',
        r'\bgemini\b',
        r'\bopenai\b',
        r'\bllm\b',
        r'\bapi\b',
    ]
    cleaned = raw
    for pat in forbidden_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\(\)\[\]_\-]+', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -_,;:')
    return cleaned


def build_default_colophon(
    manifest: Dict[str, Any],
    title: str,
    author: str,
    publisher: str,
    c_year: str,
    project_dir: Optional[str] = None
) -> str:
    """
    Constructs a descriptive, publication-grade colophon referencing the illustration plates,
    artistic medium/tradition, and interior typography. Ensures zero references to AI models or tools.
    """
    blocks = manifest.get("blocks", [])
    illus_count = sum(1 for b in blocks if b.get("illustration"))

    # Determine art style description
    style_desc = ""
    # 1. Check visual bible if project_dir is provided
    if project_dir:
        bible_path = os.path.join(project_dir, "artifacts", "03_visual_bible.json")
        if os.path.isfile(bible_path):
            try:
                with open(bible_path, "r", encoding="utf-8") as f:
                    bdata = json.load(f)
                art_style = bdata.get("global_art_style", "").strip()
                if art_style:
                    first_sent = art_style.split(".")[0].strip()
                    if first_sent:
                        style_desc = sanitize_art_style_description(first_sent)
            except Exception:
                pass

    # 2. Check differentiation summary in metadata
    if not style_desc:
        diff_summary = manifest.get("metadata", {}).get("differentiation_summary", "")
        if "illustrations" in diff_summary.lower():
            clean_s = (
                diff_summary
                .replace("Includes", "")
                .replace("includes", "")
                .replace("original full-color", "")
                .replace("illustrations.", "")
                .replace("illustrations", "")
                .strip()
            )
            if clean_s:
                style_desc = sanitize_art_style_description(clean_s)

    # 3. Check active_workflow
    if not style_desc:
        wf = manifest.get("active_workflow") or manifest.get("cover", {}).get("workflow", "")
        if wf:
            if "(" in wf and ")" in wf:
                candidate_style = wf.split("(")[1].split(")")[0].strip()
                style_desc = sanitize_art_style_description(candidate_style)
            else:
                clean_wf = wf.replace("workflow_api__", "").replace("workflow_api", "").replace("ZIT__", "").replace(".json", "")
                clean_wf = clean_wf.replace("_", " ").strip().title()
                style_desc = sanitize_art_style_description(clean_wf)

    if not style_desc or len(style_desc) < 3 or style_desc.lower() in ["style", "art", "fine art"]:
        style_desc = "fine art illustration"

    if style_desc.lower().endswith(" tradition"):
        style_desc = style_desc[:-10].strip()
    if style_desc.lower().endswith(" style"):
        style_desc = style_desc[:-6].strip()

    if illus_count > 0:
        plate_str = f"{illus_count} original plate{'s' if illus_count != 1 else ''}"
        return (
            f"This edition features {plate_str} rendered in the {style_desc} tradition. "
            f"Interior typography set in Charter, Times Roman, and Helvetica. "
            f"Published by {publisher}."
        )
    else:
        return (
            f"This edition is set in Charter, Times Roman, and Helvetica typography, "
            f"featuring original art direction and layout design. "
            f"Published by {publisher}."
        )


# -------------------------------------------------------------------------
# Metadata Helpers
# -------------------------------------------------------------------------
def get_book_metadata(
    manifest: Dict[str, Any],
    overrides: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extracts and normalizes publication metadata suitable for Amazon KDP and ebook retailers.
    Allows overriding fields dynamically from download requests or user forms.
    Enforces Amazon KDP public domain rules (e.g. mandatory '(Illustrated)' tag for differentiated works).
    Ensures copyright & licensing text strictly references the metadata of the file.
    Auto-populates a publication-grade colophon referencing the Visual Bible and typography if omitted.
    """
    existing_meta = manifest.get("metadata", {})
    overrides = overrides or {}

    title = (
        overrides.get("title") or
        existing_meta.get("title") or
        manifest.get("story_title") or
        "Illustrated Story"
    ).strip()

    subtitle = (
        overrides.get("subtitle") or
        existing_meta.get("subtitle") or
        ""
    ).strip()

    author = (
        overrides.get("author") or
        existing_meta.get("author") or
        "Author Unknown"
    ).strip()

    illustrator = (
        overrides.get("illustrator") or
        existing_meta.get("illustrator") or
        ""
    ).strip()

    publisher = (
        overrides.get("publisher") or
        existing_meta.get("publisher") or
        "Self-Published"
    ).strip()

    language = (
        overrides.get("language") or
        existing_meta.get("language") or
        "en"
    ).strip()

    description = (
        overrides.get("description") or
        existing_meta.get("description") or
        f"An illustrated edition of {title}."
    ).strip()

    isbn = (
        overrides.get("isbn") or
        existing_meta.get("isbn") or
        ""
    ).strip()

    dedication = (
        overrides.get("dedication") or
        existing_meta.get("dedication") or
        ""
    ).strip()

    public_domain = (
        overrides.get("public_domain")
        if "public_domain" in overrides
        else existing_meta.get("public_domain", False)
    )

    diff_summary = (
        overrides.get("differentiation_summary") or
        existing_meta.get("differentiation_summary") or
        ""
    ).strip()

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_simple = datetime.date.today().isoformat()
    c_year = date_simple[:4]

    # Resolve copyright_text: strictly reference metadata (publisher, author, year, illustrator)
    raw_copyright = (
        overrides.get("copyright_text")
        if "copyright_text" in overrides
        else existing_meta.get("copyright_text", "")
    )
    raw_copyright = str(raw_copyright).strip() if raw_copyright else ""

    if raw_copyright:
        # Dynamic template placeholder replacement
        raw_copyright = (
            raw_copyright
            .replace("{publisher}", publisher)
            .replace("{year}", c_year)
            .replace("{c_year}", c_year)
            .replace("{author}", author)
            .replace("{title}", title)
            .replace("{illustrator}", illustrator)
            .replace("{isbn}", isbn)
        )
        # Ensure publisher references match metadata:
        # If legacy placeholder "Shortbus Press" exists in raw_copyright and publisher was customized:
        if publisher != "Shortbus Press" and "Shortbus Press" in raw_copyright:
            raw_copyright = raw_copyright.replace("Shortbus Press", publisher)
        # If an override publisher was provided and the existing publisher appears in raw_copyright:
        old_pub = existing_meta.get("publisher", "").strip()
        if old_pub and old_pub != publisher and old_pub in raw_copyright:
            raw_copyright = raw_copyright.replace(old_pub, publisher)
        copyright_text = raw_copyright
    else:
        copyright_text = build_default_copyright_text(
            title=title,
            author=author,
            publisher=publisher,
            c_year=c_year,
            illustrator=illustrator,
            public_domain=public_domain
        )

    # Resolve colophon: strictly reference metadata, visual bible, and typography
    raw_colophon = (
        overrides.get("colophon")
        if "colophon" in overrides
        else existing_meta.get("colophon", "")
    )
    raw_colophon = str(raw_colophon).strip() if raw_colophon else ""

    if raw_colophon:
        raw_colophon = (
            raw_colophon
            .replace("{publisher}", publisher)
            .replace("{year}", c_year)
            .replace("{c_year}", c_year)
            .replace("{author}", author)
            .replace("{title}", title)
            .replace("{illustrator}", illustrator)
            .replace("{isbn}", isbn)
        )
        if publisher != "Shortbus Press" and "Shortbus Press" in raw_colophon:
            raw_colophon = raw_colophon.replace("Shortbus Press", publisher)
        old_pub = existing_meta.get("publisher", "").strip()
        if old_pub and old_pub != publisher and old_pub in raw_colophon:
            raw_colophon = raw_colophon.replace(old_pub, publisher)
        colophon = raw_colophon
    else:
        colophon = build_default_colophon(
            manifest=manifest,
            title=title,
            author=author,
            publisher=publisher,
            c_year=c_year,
            project_dir=project_dir
        )

    # KDP Title compliance:
    # Amazon mandates '(Illustrated)' in Title for differentiated public domain works
    kdp_title = (overrides.get("kdp_title") or existing_meta.get("kdp_title") or title).strip()
    if public_domain and "(Illustrated)" not in kdp_title:
        kdp_title = f"{kdp_title} (Illustrated)"

    identifier = (
        overrides.get("identifier") or
        existing_meta.get("identifier") or
        isbn or
        f"urn:uuid:{uuid.uuid4()}"
    )
    if not identifier.startswith("urn:") and not identifier.startswith("http"):
        identifier = f"urn:isbn:{identifier}" if isbn else f"urn:uuid:{identifier}"

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_simple = datetime.date.today().isoformat()

    meta_res = {
        "title": title,
        "kdp_title": kdp_title,
        "subtitle": subtitle,
        "author": author,
        "illustrator": illustrator,
        "publisher": publisher,
        "language": language,
        "description": description,
        "isbn": isbn,
        "identifier": identifier,
        "dedication": dedication,
        "copyright_text": copyright_text,
        "colophon": colophon,
        "public_domain": public_domain,
        "differentiation_summary": diff_summary,
        "modified": now_iso,
        "date": date_simple
    }
    for k, v in meta_res.items():
        if isinstance(v, str):
            meta_res[k] = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', v)
    return meta_res


def parse_block_heading_and_body(text: str) -> Tuple[Optional[str], str]:
    """
    Detects if block text begins with a Roman numeral Canto (e.g. 'I', 'II', 'VI'),
    a chapter heading ('Chapter 1: ...'), or a Markdown header ('# Heading').
    Returns (heading, cleaned_body).
    """
    text = (text or "").strip()
    lines = text.splitlines()
    if not lines:
        return None, ""
    first_line = lines[0].strip()

    # Match standalone Roman numerals (common in classical poetry cantos I to XII)
    if re.match(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)$", first_line):
        return f"Part {first_line}", "\n".join(lines[1:]).strip()

    # Match Chapter, Part, Act, Book, Canto
    if re.match(r"^(Chapter|Part|Act|Book|Canto)\s+.*", first_line, re.IGNORECASE):
        return first_line, "\n".join(lines[1:]).strip()

    # Match Markdown heading
    if first_line.startswith("# "):
        return first_line.lstrip("# ").strip(), "\n".join(lines[1:]).strip()

    return None, text


def get_scene_nav_label(block: Dict[str, Any], block_idx: int) -> str:
    """
    Derives a human-readable, elegant TOC / bookmark label for a block instead of raw chunk IDs.
    """
    text = block.get("text", "")
    heading, body = parse_block_heading_and_body(text)
    if heading:
        first_phrase = body.splitlines()[0][:35].strip() if body.splitlines() else ""
        if first_phrase:
            return f"{heading} — {first_phrase}..."
        return heading

    first_line = text.strip().splitlines()[0][:40].strip() if text.strip() else ""
    if first_line:
        return f"{first_line}..."

    illus = block.get("illustration") or {}
    cid = block.get("chunk_id", f"scene_{block_idx}")
    return f"Plate {cid.replace('chunk_', '#')}"


def split_quotes_for_pdf(text: str) -> str:
    """Highlights dialogue quotes in warm amber bold text for ReportLab paragraphs."""
    normalized = text.replace("“", '"').replace("”", '"')
    escaped = html.escape(normalized, quote=False)

    parts = []
    in_quote = False
    for char in escaped:
        if char == '"':
            if not in_quote:
                parts.append('<font color="#b45309"><b>"')
                in_quote = True
            else:
                parts.append('"</b></font>')
                in_quote = False
        else:
            parts.append(char)

    if in_quote:
        parts.append('"</b></font>')

    return "".join(parts).replace("\n", "<br/>")


def split_quotes_for_epub(text: str) -> str:
    """Highlights dialogue quotes wrapped in <strong class="q"> for EPUB XHTML."""
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text or "")
    normalized = cleaned.replace("“", '"').replace("”", '"')
    escaped = html.escape(normalized, quote=False)

    parts = []
    in_quote = False
    for char in escaped:
        if char == '"':
            if not in_quote:
                parts.append('<strong class="q">"')
                in_quote = True
            else:
                parts.append('"</strong>')
                in_quote = False
        else:
            parts.append(char)

    if in_quote:
        parts.append('"</strong>')

    return "".join(parts).replace("\n", "<br/>")


def resolve_block_illustration(
    block: Dict[str, Any],
    project_dir: str,
    workflow: Optional[str] = None
) -> Optional[Tuple[str, str, str]]:
    """
    Finds the image file path, prompt, and chunk_id for a block based on specified workflow or active fallback.
    Returns (full_img_path, prompt, chunk_id) if file exists, else None.
    """
    illus = None
    if workflow and "illustrations" in block and isinstance(block["illustrations"], dict):
        illustrations = block["illustrations"]
        if workflow in illustrations:
            illus = illustrations[workflow]
        else:
            candidates = [workflow]
            if workflow.endswith(".json"):
                candidates.append(workflow[:-5])
            else:
                candidates.append(f"{workflow}.json")

            if "__" in workflow:
                wf_part, style_part = workflow.split("__", 1)
                candidates.extend([
                    f"{wf_part} ({style_part})",
                    f"{wf_part}.json ({style_part})",
                    f"{wf_part} ({style_part.replace('_', ' ').title()})",
                    f"{wf_part}.json ({style_part.replace('_', ' ').title()})"
                ])
            elif " (" in workflow and workflow.endswith(")"):
                wf_part, style_part = workflow[:-1].split(" (", 1)
                style_slug = style_part.lower().replace(" ", "_")
                alt_wf = wf_part[:-5] if wf_part.endswith(".json") else f"{wf_part}.json"
                candidates.extend([
                    f"{alt_wf} ({style_part})",
                    f"{wf_part}__{style_slug}",
                    f"{alt_wf}__{style_slug}",
                    wf_part,
                    alt_wf
                ])

            for cand in candidates:
                if cand in illustrations:
                    illus = illustrations[cand]
                    break

            if not illus:
                target_norm = re.sub(r'[^a-z0-9]', '', workflow.lower().replace('.json', ''))
                for k, val in illustrations.items():
                    k_norm = re.sub(r'[^a-z0-9]', '', k.lower().replace('.json', ''))
                    if target_norm == k_norm or target_norm in k_norm or k_norm in target_norm:
                        illus = val
                        break

    if not illus and block.get("illustration"):
        illus = block["illustration"]

    if not illus:
        return None

    img_rel = illus.get("image_file") or illus.get("image_path")
    if not img_rel:
        return None

    full_img = os.path.abspath(os.path.join(project_dir, img_rel))
    proj_abs = os.path.abspath(project_dir)
    try:
        if os.path.commonpath([proj_abs, full_img]) != proj_abs:
            return None
    except ValueError:
        return None

    if not os.path.isfile(full_img):
        fallback = os.path.abspath(os.path.join(project_dir, "images", f"{block['chunk_id']}.png"))
        try:
            if os.path.commonpath([proj_abs, fallback]) == proj_abs and os.path.isfile(fallback):
                full_img = fallback
            else:
                return None
        except ValueError:
            return None

    return full_img, illus.get("prompt", ""), block.get("chunk_id", "")


def resolve_cover_image(manifest: Dict[str, Any], project_dir: str) -> Optional[Tuple[str, str]]:
    """
    Finds the designated cover image path and title for the book.
    Checks manifest['cover'] first (generated or selected from existing scenes),
    then falls back to images/cover/cover.jpg or None.
    Returns (cover_file_path, title) or None.
    """
    proj_abs = os.path.abspath(project_dir)
    cover_meta = manifest.get("cover")
    if isinstance(cover_meta, dict) and cover_meta.get("image_file"):
        cpath = os.path.abspath(os.path.join(project_dir, cover_meta["image_file"]))
        try:
            if os.path.commonpath([proj_abs, cpath]) == proj_abs and os.path.isfile(cpath):
                return cpath, cover_meta.get("title", manifest.get("story_title", "Cover"))
        except ValueError:
            pass

    # Fallback to images/cover/cover.jpg or images/cover/cover_kdp_marketing.jpg
    for candidate in ["images/cover/cover.jpg", "images/cover/cover_kdp_marketing.jpg", "images/cover.jpg"]:
        cpath = os.path.join(project_dir, candidate)
        if os.path.isfile(cpath):
            return cpath, manifest.get("story_title", "Cover")

    return None


def process_image_for_epub(src_path: str, quality: int = 90, max_dim: int = 2400) -> Tuple[bytes, str]:
    """
    Reads an image (PNG, JPEG, WebP) from disk, converts to RGB (sRGB),
    resizes if exceeding max_dim (preserving Kindle 5MP budget),
    and encodes to progressive JPEG at quality 90 to prevent Amazon Whispernet delivery fees.
    Returns (jpeg_bytes, 'image/jpeg').
    """
    with Image.open(src_path) as im:
        # If RGBA, create white background to avoid black boxes on e-ink Kindle
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            converted = im.convert("RGBA")
            bg.paste(converted, mask=converted.split()[3])
            rgb_im = bg
        else:
            rgb_im = im.convert("RGB")

        # Scale down if exceeding max_dim
        w, h = rgb_im.size
        if w > max_dim or h > max_dim:
            scale = min(max_dim / float(w), max_dim / float(h))
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            rgb_im = rgb_im.resize((nw, nh), Image.Resampling.LANCZOS)

        out_buf = io.BytesIO()
        rgb_im.save(out_buf, format="JPEG", quality=quality, progressive=True, optimize=True)
        return out_buf.getvalue(), "image/jpeg"


# -------------------------------------------------------------------------
# 1. High-Resolution Print-Ready PDF
# -------------------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for ReportLab that draws running headers, rules, and 'Page X of Y' footers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append({
            "page_number": self._pageNumber,
            "page_size": self._pagesize,
        })
        canvas.Canvas.showPage(self)

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self._pageNumber = state["page_number"]
            self._pagesize = state["page_size"]
            self.draw_decorations(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_decorations(self, total_pages: int):
        first_body_page = getattr(self, "first_body_page", 2)
        if self._pageNumber >= first_body_page:  # Omit header/footer on front matter pages
            self.saveState()
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#64748b"))

            # Running Header
            header_text = getattr(self, "story_title", "Illustrated Story")
            self.drawRightString(self._pagesize[0] - 54, self._pagesize[1] - 36, header_text)
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(54, self._pagesize[1] - 42, self._pagesize[0] - 54, self._pagesize[1] - 42)

            # Running Footer
            page_str = f"Page {self._pageNumber} of {total_pages}"
            self.drawRightString(self._pagesize[0] - 54, 34, page_str)
            publisher_name = getattr(self, "publisher_name", "")
            footer_label = publisher_name if publisher_name else getattr(self, "story_title", "")
            if footer_label:
                self.drawString(54, 34, footer_label)
            self.line(54, 46, self._pagesize[0] - 54, 46)

            self.restoreState()


def export_high_res_pdf(
    manifest: Dict[str, Any],
    project_dir: str,
    output_path: str,
    workflow: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generates a print-ready, high-resolution PDF document with Title Page,
    formal Copyright/Colophon page, Dedication, styled Canto/Section dividers,
    dialogue quote styling, embedded uncompressed scene illustrations,
    running headers/footers, and complete document metadata.
    """
    meta = get_book_metadata(manifest, overrides, project_dir=project_dir)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Setup DocTemplate (Letter size: 612 x 792 pt, 0.75" margins = 54 pt)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    # Document Metadata for PDF Readers & Retailers
    doc.title = meta["title"]
    doc.author = meta["author"]
    doc.subject = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', meta["description"])).strip()
    doc.creator = meta["publisher"] if meta.get("publisher") else (meta.get("author") or meta.get("title", ""))

    styles = getSampleStyleSheet()

    # Custom typography styles
    title_style = ParagraphStyle(
        "CoverTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=28,
        leading=34,
        textColor=colors.HexColor("#0f172a"),
        alignment=1,
        spaceAfter=10
    )
    subtitle_style = ParagraphStyle(
        "CoverSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#334155"),
        alignment=1,
        spaceAfter=15
    )
    author_style = ParagraphStyle(
        "CoverAuthor",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#475569"),
        alignment=1,
        spaceAfter=8
    )
    illustrator_style = ParagraphStyle(
        "CoverIllustrator",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#64748b"),
        alignment=1,
        spaceAfter=20
    )
    meta_style = ParagraphStyle(
        "CoverMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#94a3b8"),
        alignment=1
    )
    canto_heading_style = ParagraphStyle(
        "CantoHeading",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        alignment=1,
        spaceBefore=18,
        spaceAfter=10
    )
    body_style = ParagraphStyle(
        "StoryBody",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=11,
        leading=17,
        textColor=colors.HexColor("#1e293b"),
        alignment=4,  # Justified
        firstLineIndent=18,
        spaceAfter=10
    )

    printable_width = letter[0] - 108  # 504 pt
    printable_height = letter[1] - 108  # 684 pt

    story = []

    # 1. Title Page (Page 1)
    story.append(Spacer(1, 90))
    story.append(Paragraph(html.escape(meta["title"]), title_style))
    if meta.get("subtitle"):
        story.append(Paragraph(html.escape(meta["subtitle"]), subtitle_style))
    story.append(Paragraph(f"By {html.escape(meta['author'])}", author_style))
    if meta.get("illustrator"):
        story.append(Paragraph(f"Illustrated by {html.escape(meta['illustrator'])}", illustrator_style))
    story.append(HRFlowable(width="40%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceBefore=10, spaceAfter=25, hAlign="CENTER"))

    if meta.get("publisher"):
        story.append(Paragraph(f"Published by {html.escape(meta['publisher'])}", meta_style))
    if meta.get("isbn"):
        story.append(Paragraph(f"ISBN: {html.escape(meta['isbn'])}", meta_style))
    story.append(Paragraph(f"Publication Date: {meta['date']}", meta_style))
    story.append(PageBreak())

    # 2. Copyright & Edition Notice Page (Page 2 / Verso)
    story.append(Spacer(1, 230))
    full_c_title = f"{meta['title']}: {meta['subtitle']}" if meta.get("subtitle") else meta["title"]
    story.append(Paragraph(f"<b>{html.escape(full_c_title)}</b>", meta_style))
    story.append(Spacer(1, 12))

    if meta.get("copyright_text"):
        for cline in meta["copyright_text"].splitlines():
            if cline.strip():
                story.append(Paragraph(html.escape(cline.strip()), ParagraphStyle("CopyLine", parent=meta_style, fontSize=8.5, leading=13, alignment=1)))
    else:
        c_year = meta["date"][:4]
        story.append(Paragraph(f"Copyright &copy; {c_year} {html.escape(meta['publisher'])}", meta_style))
        story.append(Paragraph("All rights reserved.", meta_style))

    if meta.get("isbn"):
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"ISBN: {html.escape(meta['isbn'])}", meta_style))
    if meta.get("publisher") and f"Published by {meta['publisher']}" not in meta.get("copyright_text", ""):
        story.append(Paragraph(f"Published by {html.escape(meta['publisher'])}", meta_style))
    story.append(PageBreak())

    # 3. Dedication Page (Page 3, if present)
    if meta.get("dedication"):
        story.append(Spacer(1, 240))
        ded_style = ParagraphStyle(
            "Dedication",
            parent=styles["Normal"],
            fontName="Times-Italic",
            fontSize=14,
            leading=22,
            textColor=colors.HexColor("#334155"),
            alignment=1
        )
        story.append(Paragraph(f"<i>{html.escape(meta['dedication'])}</i>", ded_style))
        story.append(PageBreak())
        first_body_page = 4
    else:
        first_body_page = 3

    # 4. Body Content & Illustrations
    blocks = manifest.get("blocks", [])
    for block in blocks:
        raw_text = block.get("text", "")
        if raw_text:
            heading, body = parse_block_heading_and_body(raw_text)
            if heading:
                story.append(Spacer(1, 14))
                story.append(Paragraph(html.escape(heading), canto_heading_style))
                story.append(HRFlowable(width="25%", thickness=0.8, color=colors.HexColor("#cbd5e1"), spaceAfter=14, hAlign="CENTER"))
            if body:
                styled_text = split_quotes_for_pdf(body)
                story.append(Paragraph(styled_text, body_style))

        illus_info = resolve_block_illustration(block, project_dir, workflow)
        if illus_info:
            img_path, prompt, cid = illus_info
            try:
                with Image.open(img_path) as im:
                    orig_w, orig_h = im.size

                aspect = orig_w / float(orig_h) if orig_h > 0 else 1.77
                target_w = printable_width
                target_h = target_w / aspect

                # If illustration is taller than 45% of page, scale down
                max_h = printable_height * 0.45
                if target_h > max_h:
                    target_h = max_h
                    target_w = target_h * aspect

                story.append(Spacer(1, 10))
                story.append(RLImage(img_path, width=target_w, height=target_h))
                story.append(Spacer(1, 14))
            except Exception as e:
                print(f"[!] Warning: Could not embed image {img_path} in PDF: {e}")

    # 5. Back Matter: Colophon & List of Plates (if colophon is provided)
    if meta.get("colophon"):
        story.append(PageBreak())
        story.append(Spacer(1, 40))
        col_title_style = ParagraphStyle(
            "ColophonTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#0f172a"),
            alignment=0,
            spaceAfter=10
        )
        col_body_style = ParagraphStyle(
            "ColophonBody",
            parent=styles["Normal"],
            fontName="Times-Roman",
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#475569"),
            spaceAfter=10
        )
        story.append(Paragraph("Colophon", col_title_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=15))
        story.append(Paragraph(html.escape(meta["colophon"]), col_body_style))

        story.append(Spacer(1, 15))
        story.append(Paragraph("<b>List of Illustrations</b>", ParagraphStyle(
            "PlatesHeading",
            parent=col_title_style,
            fontSize=12,
            leading=16,
            spaceAfter=8
        )))
        plate_num = 1
        for b in blocks:
            illus_info = resolve_block_illustration(b, project_dir, workflow)
            if illus_info:
                p_prompt = illus_info[1]
                short_desc = p_prompt.split(".")[0].strip() if p_prompt else f"Plate {plate_num}"
                story.append(Paragraph(f"<b>Plate {plate_num}:</b> {html.escape(short_desc)}", ParagraphStyle(
                    "PlateItem",
                    parent=col_body_style,
                    fontSize=8.5,
                    leading=12,
                    spaceAfter=3
                )))
                plate_num += 1

    # Build PDF with NumberedCanvas
    def make_canvas(*args, **kwargs):
        c = NumberedCanvas(*args, **kwargs)
        c.story_title = meta["title"]
        c.publisher_name = meta.get("publisher", "")
        c.first_body_page = first_body_page
        return c

    doc.build(story, canvasmaker=make_canvas)
    return output_path


# -------------------------------------------------------------------------
# 2. Fixed-Layout EPUB 3.0 (FXL Pre-Paginated)
# -------------------------------------------------------------------------
def export_fxl_epub(
    manifest: Dict[str, Any],
    project_dir: str,
    output_path: str,
    workflow: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
    viewport_width: int = 1344,
    viewport_height: int = 768
) -> str:
    """
    Builds an Amazon KDP & Apple Books compliant Fixed-Layout (FXL) EPUB 3.0 archive.
    Each page spread features pre-paginated fixed-viewport layout with high-resolution plates.
    """
    meta = get_book_metadata(manifest, overrides, project_dir=project_dir)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    blocks = manifest.get("blocks", [])

    # Gather illustrations and determine cover image
    illus_list = []
    for b in blocks:
        info = resolve_block_illustration(b, project_dir, workflow)
        if info:
            illus_list.append(info)

    # Determine cover image: check dedicated cover first, then fallback to first illustration
    cover_info = resolve_cover_image(manifest, project_dir)
    cover_img_path = cover_info[0] if cover_info else (illus_list[0][0] if illus_list else None)

    with zipfile.ZipFile(output_path, "w") as zf:
        # 1. mimetype (Uncompressed, must be first)
        zf.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)

        # 2. META-INF/container.xml
        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        zf.writestr("META-INF/container.xml", container_xml)

        # 3. CSS for Fixed Layout
        fxl_css = f"""
@viewport {{
  width: {viewport_width}px;
  height: {viewport_height}px;
}}
html, body {{
  margin: 0;
  padding: 0;
  width: {viewport_width}px;
  height: {viewport_height}px;
  overflow: hidden;
  background-color: #0f1115;
  color: #e6edf3;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Georgia, serif;
}}
.page-container {{
  position: relative;
  width: {viewport_width}px;
  height: {viewport_height}px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 40px;
}}
.cover-title {{
  font-size: 3.2rem;
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 20px;
  text-align: center;
}}
.cover-author {{
  font-size: 1.6rem;
  color: #94a3b8;
  margin-bottom: 30px;
  text-align: center;
}}
.cover-meta {{
  font-size: 1rem;
  color: #64748b;
  text-align: center;
}}
.spread-plate {{
  display: flex;
  width: 100%;
  height: 100%;
  gap: 30px;
  align-items: center;
}}
.plate-image-container {{
  flex: 1 1 55%;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}}
.plate-image {{
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.6);
}}
.plate-text-container {{
  flex: 1 1 45%;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  overflow-y: auto;
  padding: 20px;
}}
.story-text {{
  font-size: 1.25rem;
  line-height: 1.8;
  text-align: justify;
}}
strong.q {{
  color: #f59e0b;
  font-weight: 600;
}}
"""
        zf.writestr("OEBPS/Styles/fxl.css", fxl_css)

        manifest_items = [
            '<item id="fxl_css" href="Styles/fxl.css" media-type="text/css"/>',
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        ]
        spine_items = []
        nav_points = []
        play_order = 1

        # Copy Images into OEBPS/Images/ (transcoding to progressive JPEG)
        copied_images = {}
        has_written_cover = False

        if cover_img_path and os.path.isfile(cover_img_path):
            c_bytes, _ = process_image_for_epub(cover_img_path, quality=92, max_dim=2560)
            zf.writestr("OEBPS/Images/cover_image.jpg", c_bytes)
            manifest_items.append('<item id="cover_img" href="Images/cover_image.jpg" media-type="image/jpeg" properties="cover-image"/>')
            has_written_cover = True

        for idx, (img_path, prompt, cid) in enumerate(illus_list):
            img_bytes, mtype = process_image_for_epub(img_path, quality=90, max_dim=2400)
            dest_name = f"image_{cid}.jpg"
            dest_path = f"OEBPS/Images/{dest_name}"
            zf.writestr(dest_path, img_bytes)

            is_cover = (not has_written_cover and img_path == cover_img_path)
            prop = ' properties="cover-image"' if is_cover else ""
            item_id = "cover_img" if is_cover else f"img_{cid}"
            if is_cover:
                has_written_cover = True
            manifest_items.append(f'<item id="{item_id}" href="Images/{dest_name}" media-type="{mtype}"{prop}/>')
            copied_images[cid] = (f"../Images/{dest_name}", prompt)

        # 1. Build Title / Cover Page (page_000.xhtml)
        sub_html = f'<h2 class="cover-subtitle" style="font-size: 1.5rem; color: #94a3b8; margin-bottom: 25px; text-align: center; font-weight: normal;">{html.escape(meta["subtitle"])}</h2>' if meta.get("subtitle") else ""
        illus_html = f'<p class="cover-illustrator" style="font-size: 1.1rem; color: #94a3b8; margin-bottom: 25px;">Illustrated by {html.escape(meta["illustrator"])}</p>' if meta.get("illustrator") else ""
        cover_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={viewport_width}, height={viewport_height}"/>
  <title>{html.escape(meta['title'])}</title>
  <link rel="stylesheet" type="text/css" href="../Styles/fxl.css"/>
</head>
<body>
  <div class="page-container">
    <h1 class="cover-title">{html.escape(meta['title'])}</h1>
    {sub_html}
    <p class="cover-author" style="font-size: 1.4rem; color: #cbd5e1; margin-bottom: 8px;">By {html.escape(meta['author'])}</p>
    {illus_html}
    <div class="cover-meta" style="margin-top: 15px;">
      <p>Published by {html.escape(meta['publisher'])} &bull; {meta['date']}</p>
      {f"<p>ISBN: {html.escape(meta['isbn'])}</p>" if meta['isbn'] else ""}
    </div>
  </div>
</body>
</html>"""
        zf.writestr("OEBPS/Text/page_000.xhtml", cover_xhtml)
        manifest_items.append('<item id="page_000" href="Text/page_000.xhtml" media-type="application/xhtml+xml"/>')
        spine_items.append('<itemref idref="page_000"/>')
        nav_points.append(f'<navPoint id="np-1" playOrder="{play_order}"><navLabel><text>Title Page</text></navLabel><content src="Text/page_000.xhtml"/></navPoint>')
        nav_toc_entries = [("Title Page", "Text/page_000.xhtml")]
        play_order += 1

        # 2. Build Copyright & Edition Notice Page (page_001.xhtml)
        copyright_lines = []
        if meta.get("copyright_text"):
            for cline in meta["copyright_text"].splitlines():
                if cline.strip():
                    copyright_lines.append(f"<p style='margin: 4px 0;'>{html.escape(cline.strip())}</p>")
        else:
            c_year = meta["date"][:4]
            copyright_lines.append(f"<p>Copyright &copy; {c_year} {html.escape(meta['publisher'])}</p>")
            copyright_lines.append("<p>All rights reserved.</p>")

        if meta.get("isbn"):
            copyright_lines.append(f"<p style='margin-top: 15px;'>ISBN: {html.escape(meta['isbn'])}</p>")
        if meta.get("publisher") and f"Published by {meta['publisher']}" not in meta.get("copyright_text", ""):
            copyright_lines.append(f"<p style='margin-top: 8px;'>Published by {html.escape(meta['publisher'])}</p>")
        copyright_inner = "\n      ".join(copyright_lines)

        full_c_title = f"{meta['title']}: {meta['subtitle']}" if meta.get("subtitle") else meta["title"]
        copyright_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={viewport_width}, height={viewport_height}"/>
  <title>{html.escape(meta['title'])} - Copyright</title>
  <link rel="stylesheet" type="text/css" href="../Styles/fxl.css"/>
</head>
<body>
  <div class="page-container" style="justify-content: center; align-items: center; text-align: center; max-width: 800px; margin: 0 auto;">
    <h3 style="color: #cbd5e1; font-size: 1.4rem; margin-bottom: 20px;">{html.escape(full_c_title)}</h3>
    <div style="font-size: 0.95rem; color: #64748b; line-height: 1.8; max-width: 650px;">
      {copyright_inner}
    </div>
  </div>
</body>
</html>"""
        zf.writestr("OEBPS/Text/page_001.xhtml", copyright_xhtml)
        manifest_items.append('<item id="page_001" href="Text/page_001.xhtml" media-type="application/xhtml+xml"/>')
        spine_items.append('<itemref idref="page_001"/>')
        nav_points.append(f'<navPoint id="np-{play_order}" playOrder="{play_order}"><navLabel><text>Copyright &amp; Licensing</text></navLabel><content src="Text/page_001.xhtml"/></navPoint>')
        nav_toc_entries.append(("Copyright & Licensing", "Text/page_001.xhtml"))
        play_order += 1
        page_idx = 2

        # 3. Optional Dedication Page (page_002.xhtml)
        if meta.get("dedication"):
            ded_page_name = f"page_{page_idx:03d}.xhtml"
            ded_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={viewport_width}, height={viewport_height}"/>
  <title>{html.escape(meta['title'])} - Dedication</title>
  <link rel="stylesheet" type="text/css" href="../Styles/fxl.css"/>
</head>
<body>
  <div class="page-container" style="justify-content: center; align-items: center; text-align: center;">
    <p style="font-style: italic; font-size: 1.8rem; color: #cbd5e1; line-height: 1.6; max-width: 650px;">{html.escape(meta['dedication'])}</p>
  </div>
</body>
</html>"""
            zf.writestr(f"OEBPS/Text/{ded_page_name}", ded_xhtml)
            pid = f"page_{page_idx:03d}"
            manifest_items.append(f'<item id="{pid}" href="Text/{ded_page_name}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="{pid}"/>')
            nav_points.append(f'<navPoint id="np-{play_order}" playOrder="{play_order}"><navLabel><text>Dedication</text></navLabel><content src="Text/{ded_page_name}"/></navPoint>')
            nav_toc_entries.append(("Dedication", f"Text/{ded_page_name}"))
            play_order += 1
            page_idx += 1

        # 4. Build Page Spreads from Blocks
        for b_idx, block in enumerate(blocks):
            cid = block.get("chunk_id", "")
            raw_text = block.get("text", "")
            heading, body = parse_block_heading_and_body(raw_text)
            heading_html = f'<h2 style="color: #f59e0b; font-size: 1.6rem; margin-bottom: 15px; text-align: center;">{html.escape(heading)}</h2>' if heading else ""
            styled_text = split_quotes_for_epub(body if heading else raw_text)

            img_info = copied_images.get(cid)
            if img_info:
                img_href, prompt = img_info
                page_content = f"""
    <div class="spread-plate">
      <div class="plate-image-container">
        <img class="plate-image" src="{img_href}" alt="{html.escape(prompt)}"/>
      </div>
      <div class="plate-text-container">
        {heading_html}
        <p class="story-text">{styled_text}</p>
      </div>
    </div>"""
            else:
                page_content = f"""
    <div class="page-container" style="justify-content: center; align-items: center; max-width: 900px; margin: 0 auto;">
      {heading_html}
      <p class="story-text">{styled_text}</p>
    </div>"""

            page_name = f"page_{page_idx:03d}.xhtml"
            xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={viewport_width}, height={viewport_height}"/>
  <title>{html.escape(meta['title'])} - Scene {b_idx + 1}</title>
  <link rel="stylesheet" type="text/css" href="../Styles/fxl.css"/>
</head>
<body>
{page_content}
</body>
</html>"""
            zf.writestr(f"OEBPS/Text/{page_name}", xhtml)
            pid = f"page_{page_idx:03d}"
            manifest_items.append(f'<item id="{pid}" href="Text/{page_name}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="{pid}"/>')

            nav_label = get_scene_nav_label(block, b_idx + 1)
            nav_points.append(f'<navPoint id="np-{play_order}" playOrder="{play_order}"><navLabel><text>{html.escape(nav_label)}</text></navLabel><content src="Text/{page_name}"/></navPoint>')
            nav_toc_entries.append((nav_label, f"Text/{page_name}"))
            play_order += 1
            page_idx += 1

        # 5. Optional Colophon Page
        if meta.get("colophon"):
            col_page_name = f"page_{page_idx:03d}.xhtml"
            col_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={viewport_width}, height={viewport_height}"/>
  <title>{html.escape(meta['title'])} - Colophon</title>
  <link rel="stylesheet" type="text/css" href="../Styles/fxl.css"/>
</head>
<body>
  <div class="page-container" style="justify-content: center; align-items: center; max-width: 900px; margin: 0 auto; text-align: left;">
    <h2 style="color: #ffffff; font-size: 2.2rem; margin-bottom: 15px;">Colophon</h2>
    <div style="border-top: 1px solid #334155; padding-top: 20px; font-size: 1.1rem; line-height: 1.8; color: #94a3b8;">
      <p>{html.escape(meta['colophon'])}</p>
    </div>
  </div>
</body>
</html>"""
            zf.writestr(f"OEBPS/Text/{col_page_name}", col_xhtml)
            pid = f"page_{page_idx:03d}"
            manifest_items.append(f'<item id="{pid}" href="Text/{col_page_name}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="{pid}"/>')
            nav_points.append(f'<navPoint id="np-{play_order}" playOrder="{play_order}"><navLabel><text>Colophon &amp; List of Plates</text></navLabel><content src="Text/{col_page_name}"/></navPoint>')
            nav_toc_entries.append(("Colophon & List of Plates", f"Text/{col_page_name}"))
            play_order += 1
            page_idx += 1

        # Build nav.xhtml (EPUB 3 Navigation Document)
        nav_items_list = []
        for label, href in nav_toc_entries:
            nav_items_list.append(f'      <li><a href="{href}">{html.escape(label)}</a></li>')
        nav_ol_items = "\n".join(nav_items_list)
        nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <title>Table of Contents</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
{nav_ol_items}
    </ol>
  </nav>
  <nav epub:type="landmarks" hidden="">
    <h2>Landmarks</h2>
    <ol>
      <li><a epub:type="cover" href="Text/page_000.xhtml">Cover</a></li>
      <li><a epub:type="bodymatter" href="Text/page_001.xhtml">Story</a></li>
    </ol>
  </nav>
</body>
</html>"""
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)

        # Build toc.ncx (EPUB 2 NCX Fallback)
        toc_ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{meta['identifier']}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{html.escape(meta['title'])}</text></docTitle>
  <docAuthor><text>{html.escape(meta['author'])}</text></docAuthor>
  <navMap>
{chr(10).join(nav_points)}
  </navMap>
</ncx>"""
        zf.writestr("OEBPS/toc.ncx", toc_ncx)

        # Build content.opf
        manifest_str = "\n    ".join(manifest_items)
        spine_str = "\n    ".join(spine_items)
        cover_meta_tag = '<meta name="cover" content="cover_img"/>' if cover_img_path else ""

        content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" prefix="rendition: http://www.idpf.org/vocab/rendition/# ibooks: http://vocabulary.itunes.apple.com/rdf/ibooks/vocabulary-extensions-1.0/">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{html.escape(meta['title'])}</dc:title>
    <dc:creator id="creator">{html.escape(meta['author'])}</dc:creator>
    <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>
    <dc:identifier id="pub-id">{meta['identifier']}</dc:identifier>
    <dc:language>{meta['language']}</dc:language>
    <dc:publisher>{html.escape(meta['publisher'])}</dc:publisher>
    <dc:description>{html.escape(meta['description'])}</dc:description>
    <dc:date>{meta['date']}</dc:date>
    <meta property="dcterms:modified">{meta['modified']}</meta>

    <!-- EPUB 3 Fixed-Layout Metadata -->
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="rendition:spread">auto</meta>

    <!-- Amazon KDP Specific Fixed-Layout Tags -->
    <meta name="fixed-layout" content="true"/>
    <meta name="original-resolution" content="{viewport_width}x{viewport_height}"/>
    <meta name="book-type" content="comic"/>
    <meta property="ibooks:specified-fonts">true</meta>
    {cover_meta_tag}
  </metadata>
  <manifest>
    {manifest_str}
  </manifest>
  <spine toc="ncx">
    {spine_str}
  </spine>
</package>"""
        zf.writestr("OEBPS/content.opf", content_opf)

    return output_path


# -------------------------------------------------------------------------
# 3. Reflowable EPUB (EPUB 3.0 / EPUB 2 Compatible)
# -------------------------------------------------------------------------
def export_reflowable_epub(
    manifest: Dict[str, Any],
    project_dir: str,
    output_path: str,
    workflow: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None
) -> str:
    """
    Builds a standard Reflowable EPUB 3.0 book with dynamic typography scaling,
    flexible margin reflow, dialogue quote classes, responsive images, and full retailer metadata.
    """
    meta = get_book_metadata(manifest, overrides, project_dir=project_dir)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    blocks = manifest.get("blocks", [])

    # Gather illustrations and determine cover image
    illus_list = []
    for b in blocks:
        info = resolve_block_illustration(b, project_dir, workflow)
        if info:
            illus_list.append(info)

    # Determine cover image: check dedicated cover first, then fallback to first illustration
    cover_info = resolve_cover_image(manifest, project_dir)
    cover_img_path = cover_info[0] if cover_info else (illus_list[0][0] if illus_list else None)

    with zipfile.ZipFile(output_path, "w") as zf:
        # 1. mimetype (Uncompressed, must be first)
        zf.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)

        # 2. META-INF/container.xml
        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        zf.writestr("META-INF/container.xml", container_xml)

        # 3. Clean Reflowable CSS with max-height and break-inside protection
        reflow_css = """
body {
  margin: 5% 8%;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1.1em;
  line-height: 1.7;
  color: #1a1a1a;
}
.book-header {
  text-align: center;
  margin-top: 15%;
  margin-bottom: 25%;
  page-break-after: always;
}
h1.book-title {
  font-size: 2.2em;
  line-height: 1.25;
  margin-bottom: 0.2em;
  font-weight: bold;
}
h2.book-subtitle {
  font-size: 1.2em;
  line-height: 1.35;
  color: #475569;
  font-weight: normal;
  font-style: italic;
  margin-bottom: 1.2em;
}
p.book-author {
  font-size: 1.2em;
  color: #334155;
  margin-bottom: 0.4em;
}
p.book-illustrator {
  font-size: 1.0em;
  color: #64748b;
  margin-bottom: 2em;
}
.book-meta {
  font-size: 0.85em;
  color: #777777;
}
.dedication-page {
  text-align: center;
  margin-top: 25%;
  margin-bottom: 25%;
  page-break-after: always;
}
.dedication-text {
  font-style: italic;
  font-size: 1.3em;
  color: #334155;
}
.copyright-page {
  text-align: center;
  font-size: 0.85em;
  line-height: 1.6;
  color: #64748b;
  margin-top: 20%;
  page-break-after: always;
}
.canto-header {
  text-align: center;
  color: #b45309;
  margin: 2.4em 0 1em;
  font-weight: bold;
  font-size: 1.5em;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.3em;
}
p.story-p {
  text-indent: 1.5em;
  margin: 0;
  text-align: justify;
}
p.first-p {
  text-indent: 0;
}
strong.q {
  color: #b45309;
  font-weight: 600;
}
figure.illustration {
  margin: 1.8em 0;
  text-align: center;
  break-inside: avoid;
  page-break-inside: avoid;
}
figure.illustration img {
  max-width: 100%;
  max-height: 70vh;
  height: auto;
  object-fit: contain;
  border-radius: 4px;
}
"""
        zf.writestr("OEBPS/Styles/reflow.css", reflow_css)

        manifest_items = [
            '<item id="reflow_css" href="Styles/reflow.css" media-type="text/css"/>',
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        ]
        spine_items = []
        nav_points = []
        nav_toc_entries = []
        play_order = 1

        # Copy Images into OEBPS/Images/ (transcoding to progressive JPEG)
        copied_images = {}
        has_written_cover = False

        if cover_img_path and os.path.isfile(cover_img_path):
            c_bytes, _ = process_image_for_epub(cover_img_path, quality=92, max_dim=2560)
            zf.writestr("OEBPS/Images/cover_image.jpg", c_bytes)
            manifest_items.append('<item id="cover_img" href="Images/cover_image.jpg" media-type="image/jpeg" properties="cover-image"/>')
            has_written_cover = True

        for idx, (img_path, prompt, cid) in enumerate(illus_list):
            img_bytes, mtype = process_image_for_epub(img_path, quality=90, max_dim=2400)
            dest_name = f"image_{cid}.jpg"
            dest_path = f"OEBPS/Images/{dest_name}"
            zf.writestr(dest_path, img_bytes)

            is_cover = (not has_written_cover and img_path == cover_img_path)
            prop = ' properties="cover-image"' if is_cover else ""
            item_id = "cover_img" if is_cover else f"img_{cid}"
            if is_cover:
                has_written_cover = True
            manifest_items.append(f'<item id="{item_id}" href="Images/{dest_name}" media-type="{mtype}"{prop}/>')
            copied_images[cid] = (f"../Images/{dest_name}", prompt)

        # Optional Cover Page in EPUB spine
        if has_written_cover:
            cover_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <title>Cover</title>
  <link rel="stylesheet" type="text/css" href="../Styles/reflow.css"/>
</head>
<body style="margin: 0; padding: 0; text-align: center;">
  <div style="text-align: center; margin: 0 auto; padding: 0;">
    <img src="../Images/cover_image.jpg" alt="Cover" style="max-width: 100%; max-height: 96vh; height: auto; object-fit: contain;"/>
  </div>
</body>
</html>"""
            zf.writestr("OEBPS/Text/cover.xhtml", cover_xhtml)
            manifest_items.append('<item id="cover_page" href="Text/cover.xhtml" media-type="application/xhtml+xml"/>')
            spine_items.append('<itemref idref="cover_page"/>')
            nav_points.append(f'<navPoint id="np-cover" playOrder="{play_order}"><navLabel><text>Cover</text></navLabel><content src="Text/cover.xhtml"/></navPoint>')
            play_order += 1

        # 1. Title Page (title.xhtml)
        sub_html = f'<h2 class="book-subtitle">{html.escape(meta["subtitle"])}</h2>' if meta.get("subtitle") else ""
        illus_html = f'<p class="book-illustrator">Illustrated by {html.escape(meta["illustrator"])}</p>' if meta.get("illustrator") else ""
        title_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(meta['title'])}</title>
  <link rel="stylesheet" type="text/css" href="../Styles/reflow.css"/>
</head>
<body>
  <div class="book-header">
    <h1 class="book-title">{html.escape(meta['title'])}</h1>
    {sub_html}
    <p class="book-author">By {html.escape(meta['author'])}</p>
    {illus_html}
    <div class="book-meta">
      <p>Published by {html.escape(meta['publisher'])}</p>
      {f"<p>ISBN: {html.escape(meta['isbn'])}</p>" if meta['isbn'] else ""}
      <p>{meta['date']}</p>
    </div>
  </div>
</body>
</html>"""
        zf.writestr("OEBPS/Text/title.xhtml", title_xhtml)
        manifest_items.append('<item id="title_page" href="Text/title.xhtml" media-type="application/xhtml+xml"/>')
        spine_items.append('<itemref idref="title_page"/>')
        nav_points.append(f'<navPoint id="np-1" playOrder="{play_order}"><navLabel><text>Title Page</text></navLabel><content src="Text/title.xhtml"/></navPoint>')
        nav_toc_entries.append(("Title Page", "Text/title.xhtml"))
        play_order += 1

        # 2. Copyright & Public Domain Notice Page (copyright.xhtml)
        copyright_lines = []
        if meta.get("copyright_text"):
            for cline in meta["copyright_text"].splitlines():
                if cline.strip():
                    copyright_lines.append(f"<p>{html.escape(cline.strip())}</p>")
        else:
            c_year = meta["date"][:4]
            copyright_lines.append(f"<p>Copyright &copy; {c_year} {html.escape(meta['publisher'])}</p>")
            copyright_lines.append("<p>All rights reserved.</p>")

        if meta.get("isbn"):
            copyright_lines.append(f"<p style='margin-top: 15px;'>ISBN: {html.escape(meta['isbn'])}</p>")
        if meta.get("publisher") and f"Published by {meta['publisher']}" not in meta.get("copyright_text", ""):
            copyright_lines.append(f"<p style='margin-top: 8px;'>Published by {html.escape(meta['publisher'])}</p>")
        copyright_inner = "\n    ".join(copyright_lines)

        full_c_title = f"{meta['title']}: {meta['subtitle']}" if meta.get("subtitle") else meta["title"]
        copyright_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(meta['title'])} - Copyright</title>
  <link rel="stylesheet" type="text/css" href="../Styles/reflow.css"/>
</head>
<body>
  <div class="copyright-page">
    <h3 style="color: #334155; font-size: 1.2em; margin-bottom: 15px;">{html.escape(full_c_title)}</h3>
    {copyright_inner}
  </div>
</body>
</html>"""
        zf.writestr("OEBPS/Text/copyright.xhtml", copyright_xhtml)
        manifest_items.append('<item id="copyright_page" href="Text/copyright.xhtml" media-type="application/xhtml+xml"/>')
        spine_items.append('<itemref idref="copyright_page"/>')
        nav_points.append(f'<navPoint id="np-{play_order}" playOrder="{play_order}"><navLabel><text>Copyright &amp; Licensing</text></navLabel><content src="Text/copyright.xhtml"/></navPoint>')
        nav_toc_entries.append(("Copyright & Licensing", "Text/copyright.xhtml"))
        play_order += 1

        # 3. Optional Dedication Page (dedication.xhtml)
        if meta.get("dedication"):
            ded_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(meta['title'])} - Dedication</title>
  <link rel="stylesheet" type="text/css" href="../Styles/reflow.css"/>
</head>
<body>
  <div class="dedication-page">
    <p class="dedication-text">{html.escape(meta['dedication'])}</p>
  </div>
</body>
</html>"""
            zf.writestr("OEBPS/Text/dedication.xhtml", ded_xhtml)
            manifest_items.append('<item id="dedication_page" href="Text/dedication.xhtml" media-type="application/xhtml+xml"/>')
            spine_items.append('<itemref idref="dedication_page"/>')
            nav_points.append(f'<navPoint id="np-{play_order}" playOrder="{play_order}"><navLabel><text>Dedication</text></navLabel><content src="Text/dedication.xhtml"/></navPoint>')
            nav_toc_entries.append(("Dedication", "Text/dedication.xhtml"))
            play_order += 1

        # 4. Story Flow Page
        story_body_parts = []
        for i, block in enumerate(blocks):
            cid = block.get("chunk_id", "")
            raw_text = block.get("text", "")
            heading, body = parse_block_heading_and_body(raw_text)

            if heading:
                story_body_parts.append(f'<h2 class="canto-header" id="heading_{i}">{html.escape(heading)}</h2>')

            content_text = body if heading else raw_text
            p_class = "story-p first-p" if (i == 0 or heading) else "story-p"
            styled_text = split_quotes_for_epub(content_text)
            story_body_parts.append(f'<p class="{p_class}">{styled_text}</p>')

            img_info = copied_images.get(cid)
            if img_info:
                img_href, prompt = img_info
                story_body_parts.append(f"""
<figure class="illustration" id="{cid}">
  <img src="{img_href}" alt="{html.escape(prompt)}"/>
</figure>""")

        story_content = "\n".join(story_body_parts)
        story_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(meta['title'])}</title>
  <link rel="stylesheet" type="text/css" href="../Styles/reflow.css"/>
</head>
<body>
  {story_content}
</body>
</html>"""
        zf.writestr("OEBPS/Text/story.xhtml", story_xhtml)
        manifest_items.append('<item id="story_text" href="Text/story.xhtml" media-type="application/xhtml+xml"/>')
        spine_items.append('<itemref idref="story_text"/>')
        nav_points.append(f'<navPoint id="np-story" playOrder="{play_order}"><navLabel><text>Start Reading</text></navLabel><content src="Text/story.xhtml"/></navPoint>')
        nav_toc_entries.append(("Start Reading", "Text/story.xhtml"))
        play_order += 1

        # 5. Optional Colophon Page
        if meta.get("colophon"):
            col_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(meta['title'])} - Colophon</title>
  <link rel="stylesheet" type="text/css" href="../Styles/reflow.css"/>
</head>
<body>
  <div style="margin: 10% 5%;">
    <h2 style="color: #1a1a1a; font-size: 1.8em; margin-bottom: 0.5em;">Colophon</h2>
    <div style="border-top: 1px solid #cbd5e1; padding-top: 1em; line-height: 1.7; color: #475569;">
      <p>{html.escape(meta['colophon'])}</p>
    </div>
  </div>
</body>
</html>"""
            zf.writestr("OEBPS/Text/colophon.xhtml", col_xhtml)
            manifest_items.append('<item id="colophon_page" href="Text/colophon.xhtml" media-type="application/xhtml+xml"/>')
            spine_items.append('<itemref idref="colophon_page"/>')
            nav_points.append(f'<navPoint id="np-colophon" playOrder="{play_order}"><navLabel><text>Colophon &amp; List of Plates</text></navLabel><content src="Text/colophon.xhtml"/></navPoint>')
            nav_toc_entries.append(("Colophon & List of Plates", "Text/colophon.xhtml"))
            play_order += 1

        # Build nav.xhtml
        nav_items_list = []
        for label, href in nav_toc_entries:
            nav_items_list.append(f'      <li><a href="{href}">{html.escape(label)}</a></li>')
        nav_ol_items = "\n".join(nav_items_list)
        nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <title>Table of Contents</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
{nav_ol_items}
    </ol>
  </nav>
  <nav epub:type="landmarks" hidden="">
    <h2>Landmarks</h2>
    <ol>
      <li><a epub:type="cover" href="Text/title.xhtml">Cover</a></li>
      <li><a epub:type="bodymatter" href="Text/story.xhtml">Story</a></li>
    </ol>
  </nav>
</body>
</html>"""
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)

        # Build toc.ncx
        toc_ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{meta['identifier']}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{html.escape(meta['title'])}</text></docTitle>
  <docAuthor><text>{html.escape(meta['author'])}</text></docAuthor>
  <navMap>
{chr(10).join(nav_points)}
  </navMap>
</ncx>"""
        zf.writestr("OEBPS/toc.ncx", toc_ncx)

        # Build content.opf
        manifest_str = "\n    ".join(manifest_items)
        spine_str = "\n    ".join(spine_items)
        cover_meta_tag = '<meta name="cover" content="cover_img"/>' if cover_img_path else ""

        content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{html.escape(meta['title'])}</dc:title>
    <dc:creator id="creator">{html.escape(meta['author'])}</dc:creator>
    <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>
    <dc:identifier id="pub-id">{meta['identifier']}</dc:identifier>
    <dc:language>{meta['language']}</dc:language>
    <dc:publisher>{html.escape(meta['publisher'])}</dc:publisher>
    <dc:description>{html.escape(meta['description'])}</dc:description>
    <dc:date>{meta['date']}</dc:date>
    <meta property="dcterms:modified">{meta['modified']}</meta>

    <!-- Reflowable Layout -->
    <meta property="rendition:layout">reflowable</meta>
    {cover_meta_tag}
  </metadata>
  <manifest>
    {manifest_str}
  </manifest>
  <spine toc="ncx">
    {spine_str}
  </spine>
</package>"""
        zf.writestr("OEBPS/content.opf", content_opf)

    return output_path


def export_kdp_bundle(
    manifest: Dict[str, Any],
    project_dir: str,
    output_zip_path: str,
    workflow: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None
) -> str:
    """
    Builds a complete, 1-click Amazon KDP Publishing Kit (.zip archive) containing:
    1. [StoryTitle]_kdp.epub (Reflowable EPUB 3 with embedded cover, metadata & optimized JPEGs)
    2. cover_kdp_marketing.jpg (1600x2560 standalone cover file for the KDP Bookshelf)
    3. kdp_metadata_sheet.txt (Amazon KDP compliant Title, Subtitle, Author, Blurb, and Differentiation)
    """
    meta = get_book_metadata(manifest, overrides, project_dir=project_dir)
    slug = os.path.basename(project_dir)
    os.makedirs(os.path.dirname(os.path.abspath(output_zip_path)), exist_ok=True)

    temp_dir = os.path.join(project_dir, "exports", ".tmp_kdp_bundle")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # 1. Generate Reflowable EPUB
        epub_name = f"{slug}_kdp.epub"
        epub_path = os.path.join(temp_dir, epub_name)
        export_reflowable_epub(manifest, project_dir, epub_path, workflow=workflow, overrides=overrides)

        # 2. Get or Generate Standalone Marketing Cover (1600x2560)
        cover_info = resolve_cover_image(manifest, project_dir)
        marketing_cover_name = "cover_kdp_marketing.jpg"
        marketing_cover_path = os.path.join(temp_dir, marketing_cover_name)

        if cover_info and os.path.isfile(cover_info[0]):
            with Image.open(cover_info[0]) as im:
                im_rgb = im.convert("RGB")
                w, h = im_rgb.size
                if w != 1600 or h != 2560:
                    scale = max(1600 / float(w), 2560 / float(h))
                    nw, nh = int(w * scale), int(h * scale)
                    scaled = im_rgb.resize((nw, nh), Image.Resampling.LANCZOS)
                    left = (nw - 1600) // 2
                    top = (nh - 2560) // 2
                    im_rgb = scaled.crop((left, top, left + 1600, top + 2560))
                im_rgb.save(marketing_cover_path, format="JPEG", quality=92, progressive=True, optimize=True)
        else:
            # Fallback: check if any illustration exists to composite
            from pipeline.cover_manager import composite_cover_typography
            blocks = manifest.get("blocks", [])
            first_img = None
            for b in blocks:
                info = resolve_block_illustration(b, project_dir, workflow)
                if info:
                    first_img = info[0]
                    break
            if first_img:
                composite_cover_typography(
                    first_img,
                    title=meta["title"],
                    subtitle=meta.get("subtitle", ""),
                    author=meta["author"],
                    output_marketing_path=marketing_cover_path
                )
            else:
                # Generate clean dark placeholder
                blank = Image.new("RGB", (1600, 2560), (20, 24, 33))
                blank.save(marketing_cover_path, format="JPEG", quality=90)

        # 3. Generate Metadata Upload Sheet (Amazon KDP Compliant)
        sheet_name = "kdp_metadata_sheet.txt"
        sheet_path = os.path.join(temp_dir, sheet_name)

        diff_section = ""
        if meta.get("public_domain"):
            diff_bullet = meta.get("differentiation_summary") or "* Includes original full-color illustrations."
            if not diff_bullet.startswith("*"):
                diff_bullet = f"* {diff_bullet}"
            diff_section = f"""[AMAZON KDP MANDATORY DIFFERENTIATION (REQUIRED FOR PUBLIC DOMAIN)]
Differentiation Category: {meta.get('differentiation_type', 'Illustrated')}
Mandatory First Line of Description (Max 80 chars):
{diff_bullet}
"""

        metadata_text = f"""================================================================================
AMAZON KDP PUBLISHING METADATA SHEET
Title: {meta['kdp_title']}
Publisher: {meta['publisher']}
Date: {meta['date']}
================================================================================
{diff_section}
[BOOK DETAILS (AMAZON KDP COMPLIANT)]
Book Title: {meta['kdp_title']}
Subtitle: {meta['subtitle']}
Author: {meta['author']}
Illustrator: {meta['illustrator']}
Publisher: {meta['publisher']}
Language: {meta['language']}
ISBN (Optional for digital Kindle): {meta['isbn']}

[BOOK DESCRIPTION / AMAZON BLURB (HTML COMPLIANT)]
{meta['description']}

[RECOMMENDED SEARCH KEYWORDS (7 KDP SLOTS)]
1. illustrated poetry
2. {meta['author'].lower()}
3. {meta['title'].lower()}
4. fine art illustrated edition
5. gift book poetry
6. spiritual literature
7. classic literature

[UPLOAD INSTRUCTIONS FOR KDP.AMAZON.COM]
1. Go to https://kdp.amazon.com and click "+ Create" -> "Kindle eBook" (or "Paperback").
2. Under "Kindle eBook Details":
   - Enter Book Title: "{meta['kdp_title']}"
   - Enter Subtitle: "{meta['subtitle']}"
   - Enter Primary Author: "{meta['author']}"
   - Enter Illustrator: "{meta['illustrator']}"
   - Enter Book Description: Copy and paste the blurb above (ensuring the bullet point is at the top for public domain).
3. Under "Kindle eBook Content":
   - Upload "{marketing_cover_name}" into the "Kindle eBook Cover" field.
   - Upload "{epub_name}" into the "Kindle eBook Manuscript" field.
4. Preview the book using Amazon's online previewer and click Save and Continue to set your pricing!
"""
        with open(sheet_path, "w", encoding="utf-8") as f:
            f.write(metadata_text)

        # 4. Pack into final ZIP
        with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(epub_path, epub_name)
            zf.write(marketing_cover_path, marketing_cover_name)
            zf.write(sheet_path, sheet_name)

        return output_zip_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export illustrated story to retailer-ready High-Res PDF, FXL EPUB3, Reflowable EPUB, or KDP Kit.")
    parser.add_argument("--project", "-p", required=True, help="Path to project directory (e.g. ./projects/the_raven)")
    parser.add_argument("--format", "-f", choices=["pdf", "fxl", "reflowable", "kdp", "all"], default="all", help="Export format (default: all)")
    parser.add_argument("--workflow", "-w", default=None, help="Workflow name or slug to use for illustration plates")
    parser.add_argument("--title", default=None, help="Override book title")
    parser.add_argument("--author", default=None, help="Override author name")
    parser.add_argument("--publisher", default=None, help="Override publisher name")
    parser.add_argument("--language", default=None, help="Override language code (e.g. en)")
    parser.add_argument("--isbn", default=None, help="Override ISBN / catalog identifier")
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project)
    if not os.path.isdir(project_dir):
        print(f"Error: Project directory not found: {project_dir}")
        return 1

    manifest_path = os.path.join(project_dir, "artifacts", "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"Error: manifest.json not found in {os.path.join(project_dir, 'artifacts')}")
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    slug = os.path.basename(project_dir)
    workflow = args.workflow or manifest.get("active_workflow")

    overrides = {}
    if args.title:
        overrides["title"] = args.title
    if args.author:
        overrides["author"] = args.author
    if args.publisher:
        overrides["publisher"] = args.publisher
    if args.language:
        overrides["language"] = args.language
    if args.isbn:
        overrides["identifier"] = args.isbn

    export_dir = os.path.join(project_dir, "exports")
    os.makedirs(export_dir, exist_ok=True)

    formats = ["pdf", "fxl", "reflowable", "kdp"] if args.format == "all" else [args.format]
    for fmt in formats:
        print(f"[*] Exporting {fmt.upper()} for {slug}...")
        if fmt == "pdf":
            out_path = os.path.join(export_dir, f"{slug}_print.pdf")
            out = export_high_res_pdf(manifest, project_dir, out_path, workflow=workflow, overrides=overrides)
        elif fmt == "fxl":
            out_path = os.path.join(export_dir, f"{slug}_fxl.epub")
            out = export_fxl_epub(manifest, project_dir, out_path, workflow=workflow, overrides=overrides)
        elif fmt == "reflowable":
            out_path = os.path.join(export_dir, f"{slug}_reflowable.epub")
            out = export_reflowable_epub(manifest, project_dir, out_path, workflow=workflow, overrides=overrides)
        elif fmt == "kdp":
            out_path = os.path.join(export_dir, f"{slug}_kdp_pack.zip")
            out = export_kdp_bundle(manifest, project_dir, out_path, workflow=workflow, overrides=overrides)
        print(f"[+] Successfully exported {fmt.upper()} -> {out} ({os.path.getsize(out):,} bytes)")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


