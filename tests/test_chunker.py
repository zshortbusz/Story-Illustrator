import unittest
from pipeline.chunker import chunk_text, count_words

class TestChunker(unittest.TestCase):
    def test_count_words(self):
        text = "The fog clung to the rusted girders like wet wool."
        self.assertEqual(count_words(text), 10)

    def test_chunk_text_basic(self):
        raw = """Paragraph one text here.

Paragraph two text here, with more details.

Paragraph three."""
        result = chunk_text(raw)
        chunks = result.get("chunks", [])
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["chunk_id"], "chunk_000")
        self.assertEqual(chunks[1]["chunk_id"], "chunk_001")
        self.assertEqual(chunks[2]["chunk_id"], "chunk_002")
        self.assertEqual(chunks[0]["text"], "Paragraph one text here.")

    def test_chunk_text_crlf_and_multiple_blank_lines(self):
        raw = "Chunk A\r\n\r\n\r\n   \r\nChunk B\r\n\r\nChunk C"
        result = chunk_text(raw)
        chunks = result.get("chunks", [])
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["text"], "Chunk A")
        self.assertEqual(chunks[1]["text"], "Chunk B")
        self.assertEqual(chunks[2]["text"], "Chunk C")

    def test_chunk_text_empty(self):
        self.assertEqual(chunk_text("")["chunks"], [])
        self.assertEqual(chunk_text("   \n\n   ")["chunks"], [])

if __name__ == "__main__":
    unittest.main()
