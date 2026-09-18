import os
import io
import json
import shutil
import zipfile
import tempfile
import unittest
from pipeline.book_exporter import (
    get_book_metadata,
    export_high_res_pdf,
    export_fxl_epub,
    export_reflowable_epub
)

class TestBookExporter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mock_manifest = {
            "story_title": "The Cyber Quest",
            "metadata": {
                "author": "Ada Lovelace",
                "publisher": "Algorithmic Press",
                "isbn": "978-0-123456-78-9",
                "language": "en",
                "description": "An epic cyber journey."
            },
            "blocks": [
                {
                    "chunk_id": "chunk_000",
                    "text": 'The terminal glowed. "Access granted," the machine hummed.',
                    "illustration": {
                        "prompt": "Glowing cyberpunk terminal with green text",
                        "image_file": "images/chunk_000.png"
                    }
                },
                {
                    "chunk_id": "chunk_001",
                    "text": '"We are inside," whispered Marcus.',
                    "illustration": {
                        "prompt": "Hacker looking at holographic screens",
                        "image_file": "images/chunk_001.png"
                    }
                }
            ]
        }
        # Create dummy images
        img_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(img_dir, exist_ok=True)
        from PIL import Image
        for cid in ["chunk_000", "chunk_001"]:
            im = Image.new("RGB", (640, 360), color=(20, 30, 40))
            im.save(os.path.join(img_dir, f"{cid}.png"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_book_metadata(self):
        meta = get_book_metadata(self.mock_manifest)
        self.assertEqual(meta["title"], "The Cyber Quest")
        self.assertEqual(meta["author"], "Ada Lovelace")
        self.assertEqual(meta["publisher"], "Algorithmic Press")
        self.assertEqual(meta["isbn"], "978-0-123456-78-9")
        self.assertEqual(meta["language"], "en")

        # Test overrides
        overrides = {"author": "Charles Babbage", "title": "The Analytical Engine"}
        meta_overridden = get_book_metadata(self.mock_manifest, overrides=overrides)
        self.assertEqual(meta_overridden["author"], "Charles Babbage")
        self.assertEqual(meta_overridden["title"], "The Analytical Engine")

    def test_export_high_res_pdf(self):
        pdf_out = os.path.join(self.temp_dir, "output.pdf")
        export_high_res_pdf(self.mock_manifest, self.temp_dir, pdf_out)
        self.assertTrue(os.path.isfile(pdf_out))
        self.assertGreater(os.path.getsize(pdf_out), 1000)

        # Validate PDF magic header
        with open(pdf_out, "rb") as f:
            header = f.read(5)
            self.assertEqual(header, b"%PDF-")

    def test_export_fxl_epub(self):
        epub_out = os.path.join(self.temp_dir, "output_fxl.epub")
        export_fxl_epub(self.mock_manifest, self.temp_dir, epub_out)
        self.assertTrue(os.path.isfile(epub_out))
        self.assertGreater(os.path.getsize(epub_out), 1000)

        # Validate EPUB structure
        with zipfile.ZipFile(epub_out, "r") as zf:
            namelist = zf.namelist()
            # 1. mimetype must be the first file and uncompressed
            self.assertEqual(namelist[0], "mimetype")
            info = zf.getinfo("mimetype")
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(zf.read("mimetype").decode("utf-8"), "application/epub+zip")

            # 2. Container XML
            self.assertIn("META-INF/container.xml", namelist)

            # 3. Content OPF
            self.assertIn("OEBPS/content.opf", namelist)
            opf_text = zf.read("OEBPS/content.opf").decode("utf-8")
            self.assertIn("<dc:title>The Cyber Quest</dc:title>", opf_text)
            self.assertIn("<dc:creator id=\"creator\">Ada Lovelace</dc:creator>", opf_text)
            self.assertIn("rendition:layout\">pre-paginated", opf_text)
            self.assertIn("name=\"fixed-layout\" content=\"true\"", opf_text)

            # 4. Nav and NCX
            self.assertIn("OEBPS/nav.xhtml", namelist)
            self.assertIn("OEBPS/toc.ncx", namelist)

            # 5. Pages & Images
            self.assertIn("OEBPS/Text/page_000.xhtml", namelist)
            self.assertIn("OEBPS/Text/page_001.xhtml", namelist)
            self.assertIn("OEBPS/Images/image_chunk_000.png", namelist)

    def test_export_reflowable_epub(self):
        epub_out = os.path.join(self.temp_dir, "output_reflow.epub")
        export_reflowable_epub(self.mock_manifest, self.temp_dir, epub_out)
        self.assertTrue(os.path.isfile(epub_out))
        self.assertGreater(os.path.getsize(epub_out), 1000)

        with zipfile.ZipFile(epub_out, "r") as zf:
            namelist = zf.namelist()
            self.assertEqual(namelist[0], "mimetype")
            info = zf.getinfo("mimetype")
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

            opf_text = zf.read("OEBPS/content.opf").decode("utf-8")
            self.assertIn("rendition:layout\">reflowable", opf_text)
            self.assertIn("Ada Lovelace", opf_text)

            self.assertIn("OEBPS/Text/story.xhtml", namelist)
            story_text = zf.read("OEBPS/Text/story.xhtml").decode("utf-8")
            self.assertIn('<strong class="q">"Access granted,"</strong>', story_text)
            self.assertIn('<strong class="q">"We are inside,"</strong>', story_text)

if __name__ == "__main__":
    unittest.main()
