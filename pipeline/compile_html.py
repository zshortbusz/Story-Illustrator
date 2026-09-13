"""
pipeline/compile_html.py: Phase 3 Static Reader Assembly.
Zero GPU / server dependencies.
Traverses manifest.json blocks, highlights dialogue quotes using character-level
quote splitting (preserved from build_site.cjs), embeds responsive dark-mode styling,
and outputs high-resolution <figure> illustration elements for completed scenes.
"""

import os
import re
import json
import html
import argparse
from typing import Dict, Any, List, Optional


def escape_html(text: str) -> str:
    """Safely escapes HTML metacharacters."""
    return html.escape(text, quote=False)


def split_quotes(text: str) -> List[Dict[str, Any]]:
    """
    Bold quoted text character-by-character toggling bold on each double-quote.
    Ensures both opening and closing quotes are enclosed in the dialogue run.
    """
    out = []
    bold = False
    i = 0
    n = len(text)

    while i < n:
        if text[i] == '"':
            if not bold:
                bold = True
                out.append({"text": '"', "bold": True})
            else:
                out.append({"text": '"', "bold": True})
                bold = False
            i += 1
        else:
            j = i
            while j < n and text[j] != '"':
                j += 1
            out.append({"text": text[i:j], "bold": bold})
            i = j

    return out


def render_dialogue_content(content: str) -> str:
    """
    Renders text with quotes wrapped in <strong class="q"> and internal
    linebreaks preserved via <br>.
    """
    escaped = escape_html(content)
    segments = split_quotes(escaped)

    # Merge consecutive segments with identical bold state
    merged = []
    for seg in segments:
        if merged and merged[-1]["bold"] == seg["bold"]:
            merged[-1]["text"] += seg["text"]
        else:
            merged.append(dict(seg))

    bolded = "".join([
        f'<strong class="q">{seg["text"]}</strong>' if seg["bold"] else seg["text"]
        for seg in merged
    ])

    # Convert line breaks within paragraph to <br>
    lines = bolded.split("\n")
    return "<br>\n".join(lines)


def get_reader_css() -> str:
    """Returns clean, self-contained modern dark-mode responsive typography CSS."""
    return """
:root {
  --bg-primary: #0f1115;
  --bg-surface: #181b21;
  --text-primary: #e6edf3;
  --text-secondary: #9aa5b1;
  --text-quote: #ffdf70;
  --accent: #58a6ff;
  --border: #2e3440;
  --font-serif: "Charter", "Bitstream Charter", "Sitka Text", "Cambria", "Georgia", serif;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  background-color: var(--bg-primary);
  color: var(--text-primary);
  font-family: var(--font-serif);
  font-size: 19px;
  line-height: 1.85;
  letter-spacing: 0.01em;
  padding: 40px 20px 100px;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}

.reader-container {
  max-width: 750px;
  margin: 0 auto;
}

header.story-header {
  border-bottom: 1px solid var(--border);
  padding-bottom: 32px;
  margin-bottom: 48px;
  text-align: center;
}

h1.story-title {
  font-family: var(--font-sans);
  font-size: 2.4rem;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: -0.02em;
  margin-bottom: 12px;
  line-height: 1.25;
}

.story-meta {
  font-family: var(--font-sans);
  font-size: 0.95rem;
  color: var(--text-secondary);
  display: flex;
  justify-content: center;
  gap: 18px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.story-body {
  display: flex;
  flex-direction: column;
  gap: 26px;
}

p.story-paragraph {
  text-align: justify;
  text-justify: inter-word;
  hyphens: auto;
}

/* Dialogue quote styling from build_site.cjs */
strong.q {
  color: var(--text-quote);
  font-weight: 600;
}

figure.scene-illustration {
  margin: 28px 0;
  background-color: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

figure.scene-illustration img {
  display: block;
  width: 100%;
  height: auto;
  object-fit: cover;
}

figcaption {
  font-family: var(--font-sans);
  font-size: 0.85rem;
  color: var(--text-secondary);
  padding: 12px 18px;
  line-height: 1.45;
  border-top: 1px solid var(--border);
  background: rgba(0, 0, 0, 0.2);
}

figcaption strong {
  color: var(--accent);
  margin-right: 6px;
}

footer.story-footer {
  margin-top: 60px;
  border-top: 1px solid var(--border);
  padding-top: 30px;
  text-align: center;
  font-family: var(--font-sans);
  font-size: 0.85rem;
  color: var(--text-secondary);
}

@media (max-width: 600px) {
  body {
    font-size: 17px;
    padding: 20px 14px 60px;
  }
  h1.story-title {
    font-size: 1.8rem;
  }
}
"""


def compile_manifest_to_html(manifest: Dict[str, Any], project_dir: str) -> str:
    """Compiles manifest blocks into offline HTML document."""
    title = manifest.get("story_title", "Illustrated Story")
    blocks = manifest.get("blocks", [])

    total_words = 0
    illustrations_count = 0

    body_html_parts = []

    for block in blocks:
        raw_text = block.get("text", "")
        # Count words
        words = re.findall(r"\b[\w'-]+\b", raw_text)
        total_words += len(words)

        rendered_p = render_dialogue_content(raw_text)
        body_html_parts.append(f'<p class="story-paragraph">{rendered_p}</p>')

        illus = block.get("illustration")
        if illus and illus.get("status") == "completed":
            img_rel_path = illus.get("image_file", f"images/{block['chunk_id']}.png")
            # Verify if image actually exists on disk
            full_img_path = os.path.join(project_dir, img_rel_path)
            if os.path.isfile(full_img_path):
                illustrations_count += 1
                prompt_caption = escape_html(illus.get("prompt", ""))
                cid = block.get("chunk_id", "")
                body_html_parts.append(f"""
<figure class="scene-illustration" id="{cid}">
  <img src="{img_rel_path}" alt="{prompt_caption}" loading="lazy">
  <figcaption><strong>[{cid}]</strong> {prompt_caption}</figcaption>
</figure>""")

    body_content = "\n".join(body_html_parts)
    css = get_reader_css()

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape_html(title)}</title>
  <style>
{css}
  </style>
</head>
<body>
  <div class="reader-container">
    <header class="story-header">
      <h1 class="story-title">{escape_html(title)}</h1>
      <div class="story-meta">
        <span>{total_words:,} words</span>
        <span>&bull;</span>
        <span>{illustrations_count} illustrations</span>
        <span>&bull;</span>
        <span>{len(blocks)} paragraphs</span>
      </div>
    </header>

    <main class="story-body">
{body_content}
    </main>

    <footer class="story-footer">
      <p>Automated Story Illustrator &bull; {escape_html(title)}</p>
    </footer>
  </div>
</body>
</html>
"""
    return html_doc


def compile_html(project_dir: str, output_filepath: Optional[str] = None) -> str:
    """Reads manifest.json from project, verifies rendered images, and compiles index.html."""
    manifest_path = os.path.join(project_dir, "artifacts", "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"Missing {manifest_path}. Please run Phase 1 first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    html_content = compile_manifest_to_html(manifest, project_dir)

    target = output_filepath or os.path.join(project_dir, "index.html")
    with open(target, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[+] Static reader compiled successfully -> {target}")
    return target


def main():
    parser = argparse.ArgumentParser(description="Phase 3: Static Reader Assembly for ASI")
    parser.add_argument("--project", "-p", required=True, help="Path to project directory (e.g. ./projects/my_story)")
    parser.add_argument("--output", "-o", help="Optional custom output HTML path (default: {project}/index.html)")
    args = parser.parse_args()

    compile_html(args.project, args.output)


if __name__ == "__main__":
    main()
