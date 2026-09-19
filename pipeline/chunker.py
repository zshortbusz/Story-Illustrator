r"""
pipeline/chunker.py: Deterministic text chunking and indexing.
Splits story text on paragraph boundaries (regex \n\s*\n), counts words,
and assigns deterministic zero-padded identifiers (chunk_000, chunk_001, ...).
"""

import os
import re
import json
import argparse
from typing import Dict, Any, List


def count_words(text: str) -> int:
    """Counts words using word boundary matching compatible with literary text."""
    matches = re.findall(r"\b[\w'-]+\b", text)
    return len(matches)


def chunk_text(raw_text: str, max_chunk_words: int = 400) -> Dict[str, Any]:
    r"""
    Splits raw story text into deterministic chunks.
    Normalizes CRLF to LF, splits on paragraph breaks (\n\s*\n),
    and filters out empty strings.
    If a paragraph exceeds max_chunk_words, it splits on sentence boundaries to keep chunks manageable.
    """
    # Normalize line breaks
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return {"chunks": []}

    # Split on paragraph breaks
    raw_paragraphs = re.split(r"\n\s*\n+", normalized)

    chunks: List[Dict[str, Any]] = []
    chunk_idx = 0

    for para in raw_paragraphs:
        cleaned = para.strip()
        if not cleaned:
            continue

        w_count = count_words(cleaned)
        if max_chunk_words and w_count > max_chunk_words:
            # Split giant paragraph on sentence boundaries
            sentences = re.split(r"(?:(?<=[.!?])|(?<=[.!?][\"'\u2019\u201d]))\s+", cleaned)
            sub_chunks: List[str] = []
            curr_text: List[str] = []
            curr_words = 0
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                swords = count_words(sent)
                if curr_text and (curr_words + swords > max_chunk_words):
                    sub_chunks.append(" ".join(curr_text))
                    curr_text = [sent]
                    curr_words = swords
                else:
                    curr_text.append(sent)
                    curr_words += swords
            if curr_text:
                sub_chunks.append(" ".join(curr_text))

            for sc in sub_chunks:
                chunk_id = f"chunk_{chunk_idx:03d}"
                chunks.append({
                    "chunk_id": chunk_id,
                    "text": sc,
                    "word_count": count_words(sc)
                })
                chunk_idx += 1
        else:
            chunk_id = f"chunk_{chunk_idx:03d}"
            chunks.append({
                "chunk_id": chunk_id,
                "text": cleaned,
                "word_count": w_count
            })
            chunk_idx += 1

    return {"chunks": chunks}


def chunk_file(input_path: str, output_path: str = None, max_chunk_words: int = 400) -> Dict[str, Any]:
    """Reads input story file, executes chunking, and optionally saves to output_path."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input story file not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    result = chunk_text(content, max_chunk_words=max_chunk_words)

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    return result


def main():
    parser = argparse.ArgumentParser(description="Deterministic Text Chunker for ASI")
    parser.add_argument("--input", "-i", help="Path to input text file")
    parser.add_argument("--output", "-o", help="Path to save 01_chunks.json")
    parser.add_argument("--project", "-p", help="Path to project directory (e.g. ./projects/my_story)")
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output

    if args.project:
        input_path = input_path or os.path.join(args.project, "source", "input_story.txt")
        output_path = output_path or os.path.join(args.project, "artifacts", "01_chunks.json")

    if not input_path:
        parser.error("Either --input or --project must be specified.")

    data = chunk_file(input_path, output_path)
    print(f"Successfully chunked {len(data['chunks'])} paragraphs.")
    if output_path:
        print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
