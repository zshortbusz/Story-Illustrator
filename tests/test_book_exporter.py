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
    export_reflowable_epub,
    export_kdp_bundle
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

            self.assertIn("OEBPS/Text/page_000.xhtml", namelist)
            self.assertIn("OEBPS/Text/page_001.xhtml", namelist)
            self.assertIn("OEBPS/Images/image_chunk_000.jpg", namelist)
            self.assertIn("OEBPS/Images/cover_image.jpg", namelist)

            # Verify no captions in FXL pages
            page_text = zf.read("OEBPS/Text/page_000.xhtml").decode("utf-8")
            self.assertNotIn("plate-caption", page_text)
            self.assertNotIn("<figcaption>", page_text)

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
            self.assertNotIn("<figcaption>", story_text)

    def test_kdp_compliance_and_front_matter(self):
        kdp_manifest = {
            "story_title": "Ash Wednesday",
            "metadata": {
                "title": "Ash Wednesday",
                "subtitle": "With 16 Original Pre-Raphaelite Oil Plates",
                "author": "T. S. Eliot",
                "illustrator": "Automated Story Illustrator",
                "publisher": "Shortbus Press",
                "dedication": "To my wife",
                "copyright_text": "Text in the public domain. Original illustrations © 2026 Shortbus Press.",
                "colophon": "Set in Charter and Helvetica. Illustrated in Pre-Raphaelite oil style.",
                "public_domain": True,
                "differentiation_summary": "Includes 16 original full-color Pre-Raphaelite oil illustrations."
            },
            "blocks": [
                {
                    "chunk_id": "chunk_000",
                    "text": "I\nBecause I do not hope to turn again\nBecause I do not hope",
                    "illustration": {
                        "prompt": "The Lady in white standing by dry boughs",
                        "image_file": "images/chunk_000.png"
                    }
                }
            ]
        }
        meta = get_book_metadata(kdp_manifest)
        self.assertEqual(meta["kdp_title"], "Ash Wednesday (Illustrated)")
        self.assertEqual(meta["subtitle"], "With 16 Original Pre-Raphaelite Oil Plates")
        self.assertEqual(meta["dedication"], "To my wife")
        self.assertTrue(meta["public_domain"])

        # Test FXL EPUB generation with front matter
        fxl_out = os.path.join(self.temp_dir, "ash_fxl.epub")
        export_fxl_epub(kdp_manifest, self.temp_dir, fxl_out)
        self.assertTrue(os.path.isfile(fxl_out))
        with zipfile.ZipFile(fxl_out, "r") as zf:
            nl = zf.namelist()
            self.assertIn("OEBPS/Text/page_000.xhtml", nl)  # Title
            self.assertIn("OEBPS/Text/page_001.xhtml", nl)  # Copyright
            self.assertIn("OEBPS/Text/page_002.xhtml", nl)  # Dedication
            self.assertIn("OEBPS/Text/page_003.xhtml", nl)  # Story
            self.assertIn("OEBPS/Text/page_004.xhtml", nl)  # Colophon

            ded_text = zf.read("OEBPS/Text/page_002.xhtml").decode("utf-8")
            self.assertIn("To my wife", ded_text)

            story_text = zf.read("OEBPS/Text/page_003.xhtml").decode("utf-8")
            self.assertIn("Part I", story_text)

            nav_text = zf.read("OEBPS/nav.xhtml").decode("utf-8")
            self.assertIn("Copyright &amp; Licensing", nav_text)
            self.assertIn("Dedication", nav_text)
            self.assertIn("Part I", nav_text)

        # Test KDP Bundle Generation with differentiation bullet
        bundle_out = os.path.join(self.temp_dir, "ash_kdp.zip")
        export_kdp_bundle(kdp_manifest, self.temp_dir, bundle_out)
        self.assertTrue(os.path.isfile(bundle_out))
        with zipfile.ZipFile(bundle_out, "r") as zf:
            nl = zf.namelist()
            self.assertIn("kdp_metadata_sheet.txt", nl)
            sheet = zf.read("kdp_metadata_sheet.txt").decode("utf-8")
            self.assertIn("[AMAZON KDP MANDATORY DIFFERENTIATION (REQUIRED FOR PUBLIC DOMAIN)]", sheet)
            self.assertIn("* Includes 16 original full-color Pre-Raphaelite oil illustrations.", sheet)
            self.assertIn("Book Title: Ash Wednesday (Illustrated)", sheet)
            self.assertIn("Subtitle: With 16 Original Pre-Raphaelite Oil Plates", sheet)

    def test_copyright_metadata_reference_and_publisher_sync(self):
        # 1. Test publisher synchronization when legacy publisher "Shortbus Press" is in copyright_text
        legacy_manifest = {
            "story_title": "Ash Wednesday",
            "metadata": {
                "title": "Ash Wednesday",
                "author": "T. S. Eliot",
                "publisher": "Florissant Press",
                "public_domain": True,
                "copyright_text": "Text by T. S. Eliot (1930), in the public domain in the United States.\nOriginal illustrations, art direction, and typography layout © 2026 Shortbus Press.\nAll rights reserved."
            },
            "blocks": [{"chunk_id": "c1", "text": "I\nBecause I do not hope to turn again"}]
        }
        meta = get_book_metadata(legacy_manifest)
        self.assertIn("Florissant Press", meta["copyright_text"])
        self.assertNotIn("Shortbus Press", meta["copyright_text"])

        # 2. Test auto-generation from metadata when copyright_text is empty
        empty_c_manifest = {
            "story_title": "The Raven",
            "metadata": {
                "title": "The Raven",
                "author": "Edgar Allan Poe",
                "illustrator": "Gothic Master",
                "publisher": "Gothic Classic Editions",
                "public_domain": True
            },
            "blocks": [{"chunk_id": "c1", "text": "Once upon a midnight dreary"}]
        }
        meta_auto = get_book_metadata(empty_c_manifest)
        self.assertIn("Text by Edgar Allan Poe, in the public domain in the United States.", meta_auto["copyright_text"])
        self.assertIn("Original illustrations by Gothic Master.", meta_auto["copyright_text"])
        self.assertIn("Gothic Classic Editions", meta_auto["copyright_text"])

        # 3. Test placeholder substitution
        placeholder_manifest = {
            "story_title": "Custom Work",
            "metadata": {
                "title": "Custom Work",
                "author": "Jane Doe",
                "publisher": "Starlight Publishing",
                "copyright_text": "Copyright © {year} {publisher}. All rights reserved."
            },
            "blocks": [{"chunk_id": "c1", "text": "A new chapter begins."}]
        }
        meta_ph = get_book_metadata(placeholder_manifest)
        self.assertIn("Starlight Publishing", meta_ph["copyright_text"])
        self.assertNotIn("{publisher}", meta_ph["copyright_text"])

        # 4. Test EPUB exports (Reflowable and FXL): verify NO conflicting publisher in copyright page
        epub_reflow = os.path.join(self.temp_dir, "sync_test_reflow.epub")
        export_reflowable_epub(legacy_manifest, self.temp_dir, epub_reflow)
        with zipfile.ZipFile(epub_reflow, "r") as zf:
            copy_html = zf.read("OEBPS/Text/copyright.xhtml").decode("utf-8")
            self.assertIn("Florissant Press", copy_html)
            self.assertNotIn("Shortbus Press", copy_html)
            self.assertIn("Published by Florissant Press", copy_html)

        epub_fxl = os.path.join(self.temp_dir, "sync_test_fxl.epub")
        export_fxl_epub(legacy_manifest, self.temp_dir, epub_fxl)
        with zipfile.ZipFile(epub_fxl, "r") as zf:
            copy_html = zf.read("OEBPS/Text/page_001.xhtml").decode("utf-8")
            self.assertIn("Florissant Press", copy_html)
            self.assertNotIn("Shortbus Press", copy_html)
            self.assertIn("Published by Florissant Press", copy_html)

    def test_colophon_default_generation_and_customization(self):
        # 1. Test auto-generating default colophon when colophon is omitted
        auto_col_manifest = {
            "story_title": "The Raven",
            "active_workflow": "workflow_api__charcoal_noir",
            "metadata": {
                "title": "The Raven",
                "author": "Edgar Allan Poe",
                "publisher": "Midnight Press"
            },
            "blocks": [
                {"chunk_id": "c1", "text": "Once upon a midnight dreary", "illustration": {"image_file": "img1.png", "prompt": "Chamber room"}},
                {"chunk_id": "c2", "text": "While I pondered, weak and weary", "illustration": {"image_file": "img2.png", "prompt": "Raven on bust"}}
            ]
        }
        meta = get_book_metadata(auto_col_manifest)
        self.assertIn("2 original plates", meta["colophon"])
        self.assertIn("Charcoal Noir", meta["colophon"])
        self.assertIn("Charter, Times Roman, and Helvetica", meta["colophon"])
        self.assertIn("Published by Midnight Press", meta["colophon"])

        # 2. Test custom colophon override and placeholder substitution
        custom_manifest = {
            "story_title": "Custom Story",
            "metadata": {
                "title": "Custom Story",
                "author": "Author Name",
                "publisher": "Starlight Books",
                "colophon": "Special limited release printed by {publisher}. Typography in Charter."
            },
            "blocks": []
        }
        meta_custom = get_book_metadata(custom_manifest)
        self.assertEqual(meta_custom["colophon"], "Special limited release printed by Starlight Books. Typography in Charter.")

        # 3. Test that colophon page is generated in exported EPUB
        epub_out = os.path.join(self.temp_dir, "colophon_test.epub")
        export_reflowable_epub(auto_col_manifest, self.temp_dir, epub_out)
        with zipfile.ZipFile(epub_out, "r") as zf:
            self.assertIn("OEBPS/Text/colophon.xhtml", zf.namelist())
            col_text = zf.read("OEBPS/Text/colophon.xhtml").decode("utf-8")
            self.assertIn("2 original plates", col_text)
            self.assertIn("Midnight Press", col_text)

if __name__ == "__main__":
    unittest.main()
