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


# -------------------------------------------------------------------------
# Metadata Helpers
# -------------------------------------------------------------------------
def get_book_metadata(manifest: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Extracts and normalizes publication metadata suitable for Amazon KDP and ebook retailers.
    Allows overriding fields dynamically from download requests or user forms.
    """
    existing_meta = manifest.get("metadata", {})
    overrides = overrides or {}

    title = (
        overrides.get("title") or
        existing_meta.get("title") or
        manifest.get("story_title") or
        "Illustrated Story"
    ).strip()

    author = (
        overrides.get("author") or
        existing_meta.get("author") or
        "Author Unknown"
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

    return {
        "title": title,
        "author": author,
        "publisher": publisher,
        "language": language,
        "description": description,
        "isbn": isbn,
        "identifier": identifier,
        "modified": now_iso,
        "date": date_simple
    }


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
    normalized = text.replace("“", '"').replace("”", '"')
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

    if not illus or not illus.get("image_file"):
        return None

    img_rel = illus["image_file"]
    full_img = os.path.join(project_dir, img_rel)
    if not os.path.isfile(full_img):
        fallback = os.path.join(project_dir, "images", f"{block['chunk_id']}.png")
        if os.path.isfile(fallback):
            full_img = fallback
        else:
            return None

    return full_img, illus.get("prompt", ""), block.get("chunk_id", "")


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
        if self._pageNumber > 1:  # Omit header/footer on title page
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
            self.drawString(54, 34, "Automated Story Illustrator")
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
    Generates a print-ready, high-resolution PDF document with dialogue quote styling,
    embedded uncompressed scene illustrations, running headers/footers, and complete document metadata.
    """
    meta = get_book_metadata(manifest, overrides)
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
    doc.subject = meta["description"]
    doc.creator = f"Automated Story Illustrator ({meta['publisher']})"

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
        spaceAfter=30
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
    caption_style = ParagraphStyle(
        "IllustrationCaption",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#64748b"),
        alignment=1,
        spaceAfter=16
    )

    printable_width = letter[0] - 108  # 504 pt
    printable_height = letter[1] - 108  # 684 pt

    story = []

    # Title Page
    story.append(Spacer(1, 100))
    story.append(Paragraph(html.escape(meta["title"]), title_style))
    story.append(Paragraph(f"By {html.escape(meta['author'])}", author_style))
    story.append(HRFlowable(width="40%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceAfter=25, hAlign="CENTER"))

    if meta.get("publisher"):
        story.append(Paragraph(f"Published by {html.escape(meta['publisher'])}", meta_style))
    if meta.get("isbn"):
        story.append(Paragraph(f"ISBN: {html.escape(meta['isbn'])}", meta_style))
    story.append(Paragraph(f"Publication Date: {meta['date']}", meta_style))

    story.append(PageBreak())

    # Body Content & Illustrations
    blocks = manifest.get("blocks", [])
    for block in blocks:
        raw_text = block.get("text", "")
        if raw_text:
            styled_text = split_quotes_for_pdf(raw_text)
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
                caption_text = f"<b>[{cid}]</b> {html.escape(prompt)}"
                story.append(Paragraph(caption_text, caption_style))
                story.append(Spacer(1, 8))
            except Exception as e:
                print(f"[!] Warning: Could not embed image {img_path} in PDF: {e}")

    # Build PDF with NumberedCanvas
    def make_canvas(*args, **kwargs):
        c = NumberedCanvas(*args, **kwargs)
        c.story_title = meta["title"]
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
    meta = get_book_metadata(manifest, overrides)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    blocks = manifest.get("blocks", [])

    # Gather illustrations and determine cover image
    illus_list = []
    for b in blocks:
        info = resolve_block_illustration(b, project_dir, workflow)
        if info:
            illus_list.append(info)

    cover_img_path = illus_list[0][0] if illus_list else None

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
  max-height: 88%;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.6);
}}
.plate-caption {{
  font-size: 0.85rem;
  color: #94a3b8;
  margin-top: 8px;
  text-align: center;
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

        # Copy Images into OEBPS/Images/
        copied_images = {}
        for idx, (img_path, prompt, cid) in enumerate(illus_list):
            img_ext = os.path.splitext(img_path)[1].lower()
            mtype = "image/jpeg" if img_ext in [".jpg", ".jpeg"] else "image/png"
            dest_name = f"image_{cid}{img_ext}"
            dest_path = f"OEBPS/Images/{dest_name}"

            zf.write(img_path, dest_path)

            is_cover = (img_path == cover_img_path)
            prop = ' properties="cover-image"' if is_cover else ""
            item_id = "cover_img" if is_cover else f"img_{cid}"
            manifest_items.append(f'<item id="{item_id}" href="Images/{dest_name}" media-type="{mtype}"{prop}/>')
            copied_images[cid] = (f"../Images/{dest_name}", prompt)

        # Build Title / Cover Page
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
    <h2 class="cover-author">By {html.escape(meta['author'])}</h2>
    <div class="cover-meta">
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
        play_order += 1

        # Build Page Spreads from Blocks
        page_idx = 1
        for block in blocks:
            cid = block.get("chunk_id", "")
            raw_text = block.get("text", "")
            styled_text = split_quotes_for_epub(raw_text)

            img_info = copied_images.get(cid)
            if img_info:
                img_href, prompt = img_info
                page_content = f"""
    <div class="spread-plate">
      <div class="plate-image-container">
        <img class="plate-image" src="{img_href}" alt="{html.escape(prompt)}"/>
        <div class="plate-caption"><strong>[{cid}]</strong> {html.escape(prompt)}</div>
      </div>
      <div class="plate-text-container">
        <p class="story-text">{styled_text}</p>
      </div>
    </div>"""
            else:
                page_content = f"""
    <div class="page-container" style="justify-content: center; align-items: center; max-width: 900px; margin: 0 auto;">
      <p class="story-text">{styled_text}</p>
    </div>"""

            page_name = f"page_{page_idx:03d}.xhtml"
            xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{meta['language']}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width={viewport_width}, height={viewport_height}"/>
  <title>{html.escape(meta['title'])} - Scene {page_idx}</title>
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
            nav_points.append(f'<navPoint id="np-{play_order}" playOrder="{play_order}"><navLabel><text>Scene {cid}</text></navLabel><content src="Text/{page_name}"/></navPoint>')
            play_order += 1
            page_idx += 1

        # Build nav.xhtml (EPUB 3 Navigation Document)
        nav_items_list = []
        for i in range(page_idx):
            label = "Title Page" if i == 0 else f"Scene {blocks[i-1].get('chunk_id', i)}"
            nav_items_list.append(f'      <li><a href="Text/page_{i:03d}.xhtml">{label}</a></li>')
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
    meta = get_book_metadata(manifest, overrides)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    blocks = manifest.get("blocks", [])

    # Gather illustrations and determine cover image
    illus_list = []
    for b in blocks:
        info = resolve_block_illustration(b, project_dir, workflow)
        if info:
            illus_list.append(info)

    cover_img_path = illus_list[0][0] if illus_list else None

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

        # 3. Clean Reflowable CSS
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
  margin-bottom: 0.3em;
  font-weight: bold;
}
p.book-author {
  font-size: 1.2em;
  color: #555555;
  margin-bottom: 2em;
}
.book-meta {
  font-size: 0.85em;
  color: #777777;
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
  page-break-inside: avoid;
}
figure.illustration img {
  max-width: 100%;
  height: auto;
  border-radius: 4px;
}
figcaption {
  font-size: 0.8em;
  color: #666666;
  margin-top: 0.5em;
  font-family: sans-serif;
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
        play_order = 1

        # Copy Images into OEBPS/Images/
        copied_images = {}
        for idx, (img_path, prompt, cid) in enumerate(illus_list):
            img_ext = os.path.splitext(img_path)[1].lower()
            mtype = "image/jpeg" if img_ext in [".jpg", ".jpeg"] else "image/png"
            dest_name = f"image_{cid}{img_ext}"
            dest_path = f"OEBPS/Images/{dest_name}"

            zf.write(img_path, dest_path)

            is_cover = (img_path == cover_img_path)
            prop = ' properties="cover-image"' if is_cover else ""
            item_id = "cover_img" if is_cover else f"img_{cid}"
            manifest_items.append(f'<item id="{item_id}" href="Images/{dest_name}" media-type="{mtype}"{prop}/>')
            copied_images[cid] = (f"../Images/{dest_name}", prompt)

        # Title Page
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
    <p class="book-author">By {html.escape(meta['author'])}</p>
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
        play_order += 1

        # Story Flow Page (or Chapters)
        story_body_parts = []
        for i, block in enumerate(blocks):
            cid = block.get("chunk_id", "")
            raw_text = block.get("text", "")
            p_class = "story-p first-p" if i == 0 else "story-p"
            styled_text = split_quotes_for_epub(raw_text)
            story_body_parts.append(f'<p class="{p_class}">{styled_text}</p>')

            img_info = copied_images.get(cid)
            if img_info:
                img_href, prompt = img_info
                story_body_parts.append(f"""
<figure class="illustration" id="{cid}">
  <img src="{img_href}" alt="{html.escape(prompt)}"/>
  <figcaption><strong>[{cid}]</strong> {html.escape(prompt)}</figcaption>
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
        nav_points.append(f'<navPoint id="np-2" playOrder="{play_order}"><navLabel><text>Read Story</text></navLabel><content src="Text/story.xhtml"/></navPoint>')

        # Build nav.xhtml
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
      <li><a href="Text/title.xhtml">Title Page</a></li>
      <li><a href="Text/story.xhtml">Start Reading</a></li>
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export illustrated story to retailer-ready High-Res PDF, FXL EPUB3, or Reflowable EPUB.")
    parser.add_argument("--project", "-p", required=True, help="Path to project directory (e.g. ./projects/the_raven)")
    parser.add_argument("--format", "-f", choices=["pdf", "fxl", "reflowable", "all"], default="all", help="Export format (default: all)")
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
    wf_suffix = f"_{workflow.replace('.json', '')}" if workflow else ""

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

    formats = ["pdf", "fxl", "reflowable"] if args.format == "all" else [args.format]
    for fmt in formats:
        print(f"[*] Exporting {fmt.upper()} for {slug}...")
        if fmt == "pdf":
            out_path = os.path.join(export_dir, f"{slug}{wf_suffix}_print.pdf")
            out = export_high_res_pdf(manifest, project_dir, out_path, workflow=workflow, overrides=overrides)
        elif fmt == "fxl":
            out_path = os.path.join(export_dir, f"{slug}{wf_suffix}_fxl.epub")
            out = export_fxl_epub(manifest, project_dir, out_path, workflow=workflow, overrides=overrides)
        elif fmt == "reflowable":
            out_path = os.path.join(export_dir, f"{slug}{wf_suffix}_reflowable.epub")
            out = export_reflowable_epub(manifest, project_dir, out_path, workflow=workflow, overrides=overrides)
        print(f"[+] Successfully exported {fmt.upper()} -> {out} ({os.path.getsize(out):,} bytes)")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


