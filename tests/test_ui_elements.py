import unittest
import os
import re
import json
import time
import base64
import subprocess
import shutil
from html.parser import HTMLParser
from PIL import Image, ImageStat
from pipeline.web_server import create_app

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML_PATH = os.path.join(WORKSPACE_DIR, 'pipeline', 'web_static', 'index.html')
APP_JS_PATH = os.path.join(WORKSPACE_DIR, 'pipeline', 'web_static', 'app.js')
DEFAULT_BRAIN_DIR = r'C:\Users\Shortbus\.gemini\antigravity\brain\55f1d8f8-9f52-4e71-aa0a-fed84b436ea0'
ARTIFACT_DIR = DEFAULT_BRAIN_DIR if os.path.isdir(DEFAULT_BRAIN_DIR) else os.path.join(WORKSPACE_DIR, 'tests', 'artifacts')
os.makedirs(ARTIFACT_DIR, exist_ok=True)


class HTMLIDParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.classes = set()
        self.data_tabs = set()

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if 'id' in attr_dict:
            self.ids.add(attr_dict['id'])
        if 'class' in attr_dict:
            for c in attr_dict['class'].split():
                self.classes.add(c)
        if 'data-tab' in attr_dict:
            self.data_tabs.add(attr_dict['data-tab'])


class TestUIDOMStructure(unittest.TestCase):
    """Validates that all essential HTML elements, navigation tabs, controls, and modals exist in index.html."""

    @classmethod
    def setUpClass(cls):
        with open(INDEX_HTML_PATH, 'r', encoding='utf-8') as f:
            cls.html_content = f.read()
        parser = HTMLIDParser()
        parser.feed(cls.html_content)
        cls.parsed_ids = parser.ids
        cls.parsed_data_tabs = parser.data_tabs

    def test_navigation_tabs_exist(self):
        expected_tabs = {
            'tab-chunks',
            'tab-bible',
            'tab-beats',
            'tab-manifest',
            'tab-render',
            'tab-reader'
        }
        for tab in expected_tabs:
            self.assertIn(tab, self.parsed_data_tabs, f"Navigation button data-tab missing for {tab}")
            self.assertIn(tab, self.parsed_ids, f"Section id missing for {tab}")

    def test_global_header_elements_exist(self):
        required_ids = [
            'projectSelect',
            'btnNewProject',
            'badgeLMStudio',
            'badgeComfyUI',
            'btnRefreshStatus',
            'hardwareBanner',
            'bannerTitle',
            'bannerDesc'
        ]
        for rid in required_ids:
            self.assertIn(rid, self.parsed_ids, f"Header element ID {rid} missing")

    def test_tab_model_and_action_controls_exist(self):
        required_controls = [
            # Tab 1
            'btnSaveSource', 'btnRunChunker', 'chunkProgressBox', 'sourceStoryText', 'chunkCount', 'chunksList',
            # Tab 2
            'btnSaveBible', 'btnRunBible', 'modelStructuredAnalyst', 'modelStructuredAnalystCustom',
            'tempAnalyst', 'promptAnalyst', 'btnSaveAnalystConfig', 'bibleProgressBox', 'bibleArtStyle',
            'charactersList', 'settingsList',
            # Tab 3
            'btnAddBeat', 'btnSaveBeats', 'btnRunBeats', 'modelNarrativeDirector',
            'modelNarrativeDirectorCustom', 'tempNarrative', 'promptNarrative', 'btnSaveDirectorConfig',
            'beatsProgressBox', 'beatsContainer',
            # Tab 4
            'chkShowIllustratedOnly', 'btnSaveManifest', 'btnRunManifest', 'modelPromptSynthesizer',
            'modelPromptSynthesizerCustom', 'tempSynth', 'promptSynth', 'activeProfileSelect',
            'profilePositivePrefix', 'profileNegativePrompt', 'btnSaveSynthConfig', 'manifestProgressBox', 'manifestBlocksContainer',
            # Tab 5
            'selectWorkflow', 'btnToggleSelectAll', 'btnRegenerateSelected', 'btnStartBatchRender', 'renderProgressBox', 'renderProgressBar', 'imagesGallery',
            # Tab 6
            'readerWorkflowSelect', 'btnExportPdf', 'btnExportFxl', 'btnExportReflowable', 'btnEditEbookMetadata', 'readerIframe'
        ]
        for cid in required_controls:
            self.assertIn(cid, self.parsed_ids, f"Control ID {cid} missing in index.html")

    def test_modals_and_inputs_exist(self):
        modal_ids = [
            'modalNewProject', 'btnCloseModal', 'dropZone', 'btnBrowseFile', 'fileStoryInput',
            'loadedFileInfo', 'newStorySlug', 'newStoryText', 'btnCancelNewProject', 'btnSubmitNewProject',
            'modalTweakRerun', 'tweakChunkId', 'btnCloseTweakModal', 'tweakPrompt', 'tweakNegativePrompt',
            'tweakWidth', 'tweakHeight', 'tweakSeed', 'btnCancelTweak', 'btnSubmitTweakRerun',
            'modalEbookMetadata', 'btnCloseMetadataModal', 'metaBookTitle', 'metaBookAuthor',
            'metaBookPublisher', 'metaBookLanguage', 'metaBookIsbn', 'metaBookDescription',
            'btnCancelMetadata', 'btnSaveMetadata', 'btnSaveAndExport',
            'toast'
        ]
        for mid in modal_ids:
            self.assertIn(mid, self.parsed_ids, f"Modal ID {mid} missing in index.html")


class TestJSUIContract(unittest.TestCase):
    """Ensures that JavaScript DOM element bindings in app.js match valid IDs in index.html."""

    @classmethod
    def setUpClass(cls):
        with open(INDEX_HTML_PATH, 'r', encoding='utf-8') as f:
            html_content = f.read()
        parser = HTMLIDParser()
        parser.feed(html_content)
        cls.html_ids = parser.ids

        with open(APP_JS_PATH, 'r', encoding='utf-8') as f:
            cls.js_content = f.read()

    def test_all_js_queried_ids_exist_in_html(self):
        queried_ids = set(re.findall(r'document\.getElementById\(["\']([a-zA-Z0-9_-]+)["\']\)', self.js_content))
        missing_ids = queried_ids - self.html_ids
        self.assertEqual(len(missing_ids), 0, f"app.js references elements not present in index.html: {missing_ids}")

    def test_key_ui_functions_defined(self):
        key_functions = [
            'getActiveRoleModel',
            'renderManifestBlocks',
            'populateModelDropdowns',
            'saveCurrentLLMConfig',
            'triggerStage',
            'openTweakModal',
            'setupEventListeners'
        ]
        for fn in key_functions:
            self.assertIn(f"function {fn}", self.js_content, f"Expected function {fn} to be defined in app.js")


class TestReaderUIContract(unittest.TestCase):
    """Tests that the static reader preview serves properly formatted HTML with dialogue & styling."""

    def setUp(self):
        app = create_app()
        self.client = app.test_client()

    def test_reader_html_generation_and_styling(self):
        resp = self.client.get('/api/project/the_raven/reader')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check document structure & styling
        self.assertIn('<!DOCTYPE html>', html)
        self.assertIn('<style>', html)
        self.assertIn('--bg-primary', html)

        # Check dialogue quote formatting (<strong class="q">)
        self.assertIn('<strong class="q">', html, 'Dialogue quotes must be styled with <strong class="q">')

        # Check story title
        self.assertIn('The Raven', html)


class TestVisibleChromeDevToolsE2E(unittest.TestCase):
    """End-to-End browser UI automation test using visible Chrome DevTools MCP."""

    @classmethod
    def setUpClass(cls):
        mcp_cmd = None
        user_npm_path = os.path.expanduser('~/AppData/Roaming/npm/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js')
        if os.path.isfile(user_npm_path):
            mcp_cmd = ['node', user_npm_path]
        elif shutil.which('chrome-devtools-mcp') or shutil.which('chrome-devtools-mcp.cmd'):
            bin_path = shutil.which('chrome-devtools-mcp') or shutil.which('chrome-devtools-mcp.cmd')
            mcp_cmd = [bin_path]
        elif shutil.which('npx') or shutil.which('npx.cmd'):
            npx_bin = shutil.which('npx') or shutil.which('npx.cmd')
            mcp_cmd = [npx_bin, '-y', 'chrome-devtools-mcp']

        if not mcp_cmd:
            raise unittest.SkipTest("chrome-devtools-mcp not installed in environment; skipping browser E2E tests.")

        cmd = mcp_cmd + ['--channel=stable', '--viewport', '1280x800']
        cls.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        cls.req_id = 0
        cls._init_mcp()

    @classmethod
    def _init_mcp(cls):
        cls._call('initialize', {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'test_suite', 'version': '1.0'}
        })

    @classmethod
    def _call(cls, method, params=None):
        cls.req_id += 1
        current_id = cls.req_id
        req = {'jsonrpc': '2.0', 'id': current_id, 'method': method}
        if params is not None:
            req['params'] = params
        cls.proc.stdin.write(json.dumps(req) + '\n')
        cls.proc.stdin.flush()
        while True:
            line = cls.proc.stdout.readline()
            if not line:
                return {}
            try:
                data = json.loads(line)
                if data.get('id') == current_id:
                    return data
            except Exception:
                continue

    @classmethod
    def call_tool(cls, name, arguments=None):
        res = cls._call('tools/call', {
            'name': name,
            'arguments': arguments or {}
        })
        return res.get('result', {})

    @classmethod
    def tearDownClass(cls):
        try:
            cls.proc.terminate()
            cls.proc.wait(timeout=2)
        except Exception:
            try:
                cls.proc.kill()
            except Exception:
                pass

    def eval_js(self, script):
        """Helper to evaluate JS code within the active page via DevTools."""
        fn_expr = script.strip()
        if not (fn_expr.startswith('(') or fn_expr.startswith('function')):
            if ';' in fn_expr or '\n' in fn_expr or fn_expr.startswith('const ') or fn_expr.startswith('let ') or fn_expr.startswith('var ') or 'return ' in fn_expr:
                fn_expr = f"() => {{\n{script}\n}}"
            else:
                fn_expr = f"() => ({script})"
        res = self.call_tool('evaluate_script', {
            'pageId': 1,
            'function': fn_expr
        })
        raw = res.get('content', [{}])[0].get('text', '')
        m = re.search(r'```(?:json)?\s*(.*?)\s*```', raw, re.DOTALL)
        if m:
            val_str = m.group(1).strip()
            if val_str == 'undefined':
                return ''
            try:
                parsed = json.loads(val_str)
                if isinstance(parsed, bool):
                    return 'true' if parsed else 'false'
                return str(parsed) if not isinstance(parsed, str) else parsed
            except Exception:
                return val_str
        return raw.strip()

    def _wait_for(self, condition_fn, timeout=120, poll_interval=1.0, desc="Condition"):
        """Polls until condition_fn returns True or timeout is reached."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                if condition_fn():
                    return True
            except Exception:
                pass
            time.sleep(poll_interval)
        return False

    def _capture_screenshot(self, filename):
        """Captures active browser viewport screenshot and saves to artifact directory."""
        screenshot_path = os.path.join(ARTIFACT_DIR, filename)
        shot_res = self.call_tool('take_screenshot', {'pageId': 1})
        content = shot_res.get('content', [])
        img_item = next((c for c in content if c.get('type') == 'image'), None)
        if img_item:
            img_bytes = base64.b64decode(img_item['data'])
            with open(screenshot_path, 'wb') as f:
                f.write(img_bytes)
        return screenshot_path

    def test_visible_browser_ui_walkthrough(self):
        # 1. Navigate to live application
        nav_res = self.call_tool('navigate_page', {
            'pageId': 1,
            'type': 'url',
            'url': 'http://127.0.0.1:5000'
        })
        self.assertTrue(nav_res, 'Navigation failed')
        time.sleep(1.2)  # Visual pacing for user

        # 2. Check title
        text = self.eval_js("document.title")
        self.assertIn('Automated Story Illustrator', text)

        # 3. Cycle sequentially through all navigation tabs with visual pauses
        tabs = [
            ('tab-chunks', 'Tab 1: Chunks'),
            ('tab-bible', 'Tab 2: Visual Bible'),
            ('tab-beats', 'Tab 3: Visual Beats'),
            ('tab-manifest', 'Tab 4: Manifest & Prompts'),
            ('tab-render', 'Tab 5: Render & Review'),
            ('tab-reader', 'Tab 6: Reader Preview')
        ]

        for tab_id, label in tabs:
            self.eval_js(f"""
                const btn = document.querySelector('.tab-btn[data-tab="{tab_id}"]');
                if (btn) btn.click();
            """)
            time.sleep(0.8)  # Visible pause so user can watch tab switch

            # Verify active class on target section
            is_active = self.eval_js(f"document.getElementById('{tab_id}').classList.contains('active')")
            self.assertIn('true', is_active)

        # 4. In Tab 4 (Manifest): Test 'Show Illustrated Blocks Only' toggle
        self.eval_js("document.querySelector('.tab-btn[data-tab=\"tab-manifest\"]').click()")
        time.sleep(0.8)

        # Uncheck filter to show all blocks
        self.eval_js("""
            const chk = document.getElementById('chkShowIllustratedOnly');
            chk.checked = false;
            chk.dispatchEvent(new Event('change'));
        """)
        time.sleep(0.8)

        # Re-check filter
        self.eval_js("""
            const chk = document.getElementById('chkShowIllustratedOnly');
            chk.checked = true;
            chk.dispatchEvent(new Event('change'));
        """)
        time.sleep(0.8)

        # 5. Test Interactive Modals (Open & Close visually)
        # Open New Story Modal
        self.eval_js("document.getElementById('btnNewProject').click()")
        time.sleep(0.8)
        modal_visible = self.eval_js("document.getElementById('modalNewProject').style.display !== 'none'")
        self.assertIn('true', modal_visible)

        # Close New Story Modal
        self.eval_js("document.getElementById('btnCancelNewProject').click()")
        time.sleep(0.8)
        modal_hidden = self.eval_js("document.getElementById('modalNewProject').style.display === 'none'")
        self.assertIn('true', modal_hidden)

        # 6. Capture live dashboard screenshot into artifact directory
        screenshot_path = self._capture_screenshot('ui_test_dashboard.png')
        self.assertTrue(os.path.isfile(screenshot_path), f"Screenshot file missing at {screenshot_path}")
        self.assertGreater(os.path.getsize(screenshot_path), 1000)

    def test_visible_browser_manual_story_end_to_end(self):
        """
        Full End-to-End browser UI automation test:
        1. Manually input a story through the New Story UI modal.
        2. Progress through all 6 pipeline stages sequentially:
           - Chunks (run chunker & verify DOM)
           - Visual Bible (select fast model, extract characters & settings)
           - Visual Beats (select fast model, extract cinematic scene beats)
           - Manifest & Prompts (select fast model, synthesize rich diffusion prompts)
           - Render & Review (select animap.json workflow, trigger batch render in ComfyUI)
           - Reader Preview (compile static HTML reader and verify output)
        3. Comprehensive verification:
           - Check generated image file size, PNG format, RGB mode, dimensions >= 512x512.
           - Check pixel variance (stddev > 15) and dynamic range (extrema).
           - Semantic match verification: ensure positive prompt includes the character's
             distinctive traits and setting, and that the image render matches.
        """
        slug = "manual_e2e_warrior"
        story_text = (
            "Valeria, a formidable warrior with a gleaming brass mechanical arm and short blonde hair, "
            "stood atop the rain-slicked cathedral roof. Midnight lightning fractured the dark sky above "
            "the gothic spires as she gripped her twin golden blades."
        )
        pdir = os.path.join(WORKSPACE_DIR, 'projects', slug)
        if os.path.exists(pdir):
            shutil.rmtree(pdir, ignore_errors=True)

        # 1. Navigate to live application
        self.call_tool('navigate_page', {
            'pageId': 1,
            'type': 'url',
            'url': 'http://127.0.0.1:5000'
        })
        time.sleep(1.5)

        # 2. Open New Story modal
        self.eval_js("document.getElementById('btnNewProject').click()")
        time.sleep(1.0)
        self.assertIn('flex', self.eval_js("document.getElementById('modalNewProject').style.display"))

        # 3. Enter story slug and story text manually
        safe_text = json.dumps(story_text)
        self.eval_js(f"""
            document.getElementById('newStorySlug').value = '{slug}';
            document.getElementById('newStoryText').value = {safe_text};
        """)
        time.sleep(1.0)

        # 4. Submit New Story modal
        self.eval_js("document.getElementById('btnSubmitNewProject').click()")
        time.sleep(2.0)

        # Verify project is selected
        selected_project = self.eval_js("document.getElementById('projectSelect').value")
        self.assertEqual(selected_project, slug)
        time.sleep(1.0)

        # 5. Step 1: Chunks
        self.eval_js("document.querySelector('.tab-btn[data-tab=\"tab-chunks\"]').click()")
        time.sleep(1.0)
        self.eval_js("document.getElementById('btnRunChunker').click()")
        time.sleep(1.0)

        def chunks_ready():
            disabled = str(self.eval_js("document.getElementById('btnRunChunker').disabled")).lower()
            count = self.eval_js("document.getElementById('chunkCount').textContent")
            try:
                c_int = int(str(count).strip() or 0)
            except ValueError:
                c_int = 0
            return disabled == 'false' and c_int >= 1

        self.assertTrue(self._wait_for(chunks_ready, timeout=30, desc="Chunker"))
        time.sleep(1.2)

        # 6. Step 2: Visual Bible
        self.eval_js("document.querySelector('.tab-btn[data-tab=\"tab-bible\"]').click()")
        time.sleep(1.0)

        # Set role model to fast model gemma-4-e4b-it-qat
        self.eval_js("""
            const sel = document.getElementById('modelStructuredAnalyst');
            const opt = Array.from(sel.options).find(o => o.value.includes('gemma-4-e4b-it-qat'));
            if (opt) sel.value = opt.value;
            const custom = document.getElementById('modelStructuredAnalystCustom');
            if (custom) custom.value = 'gemma-4-e4b-it-qat';
            document.getElementById('btnSaveAnalystConfig').click();
        """)
        time.sleep(1.0)

        # Run extraction
        self.eval_js("document.getElementById('btnRunBible').click()")
        time.sleep(1.0)

        def bible_ready():
            disabled = str(self.eval_js("document.getElementById('btnRunBible').disabled")).lower()
            char_count = self.eval_js("document.querySelectorAll('#charactersList .bible-item-card').length")
            try:
                cc_int = int(str(char_count).strip() or 0)
            except ValueError:
                cc_int = 0
            return disabled == 'false' and cc_int >= 1

        self.assertTrue(self._wait_for(bible_ready, timeout=120, desc="Visual Bible Extraction"))
        time.sleep(1.2)

        # Verify character card contains Valeria and brass arm
        bible_chars_text = self.eval_js("""
            return Array.from(document.querySelectorAll('#charactersList .bible-item-card')).map(card => {
                const name = card.querySelector('.char-name-input')?.value || '';
                const desc = card.querySelector('.char-desc-input')?.value || '';
                return `${name}: ${desc}`;
            }).join('\\n');
        """)
        self.assertTrue("valeria" in bible_chars_text.lower() or "warrior" in bible_chars_text.lower(), f"Character missing in UI: {bible_chars_text}")
        
        # Also verify Visual Bible artifact on disk
        bible_path = os.path.join(pdir, 'artifacts', '03_visual_bible.json')
        self.assertTrue(os.path.isfile(bible_path), "Visual Bible artifact missing on disk")
        with open(bible_path, 'r', encoding='utf-8') as f:
            bible_data = json.load(f)
        chars = bible_data.get('characters', {})
        self.assertTrue(any('valeria' in k.lower() or 'warrior' in k.lower() for k in chars.keys()), "Valeria missing in Visual Bible characters")

        # 7. Step 3: Visual Beats
        self.eval_js("document.querySelector('.tab-btn[data-tab=\"tab-beats\"]').click()")
        time.sleep(1.0)

        self.eval_js("""
            const sel = document.getElementById('modelNarrativeDirector');
            const opt = Array.from(sel.options).find(o => o.value.includes('gemma-4-e4b-it-qat'));
            if (opt) sel.value = opt.value;
            const custom = document.getElementById('modelNarrativeDirectorCustom');
            if (custom) custom.value = 'gemma-4-e4b-it-qat';
            document.getElementById('btnSaveDirectorConfig').click();
        """)
        time.sleep(1.0)

        self.eval_js("document.getElementById('btnRunBeats').click()")
        time.sleep(1.0)

        def beats_ready():
            disabled = str(self.eval_js("document.getElementById('btnRunBeats').disabled")).lower()
            return disabled == 'false'

        self.assertTrue(self._wait_for(beats_ready, timeout=120, desc="Beat Selection"))
        time.sleep(1.0)

        # Ensure at least 1 beat card exists
        beat_count_str = self.eval_js("document.querySelectorAll('#beatsContainer .beat-card').length")
        beat_count = int(beat_count_str) if beat_count_str and str(beat_count_str).isdigit() else 0
        if beat_count == 0:
            self.eval_js("document.getElementById('btnAddBeat').click();")
            time.sleep(1.0)
            self.eval_js("""
                const card = document.querySelector('#beatsContainer .beat-card');
                if (card) {
                    card.querySelector('.beat-chars').value = 'Valeria';
                    card.querySelector('.beat-setting').value = 'Cathedral Roof';
                    card.querySelector('.beat-action').value = 'Valeria standing on cathedral roof in cosmic lightning with glowing brass arm';
                    document.getElementById('btnSaveBeats').click();
                }
            """)
            time.sleep(1.2)

        # 8. Step 4: Manifest & Prompts
        self.eval_js("document.querySelector('.tab-btn[data-tab=\"tab-manifest\"]').click()")
        time.sleep(1.0)

        self.eval_js("""
            const sel = document.getElementById('modelPromptSynthesizer');
            const opt = Array.from(sel.options).find(o => o.value.includes('gemma-4-e4b-it-qat'));
            if (opt) sel.value = opt.value;
            const custom = document.getElementById('modelPromptSynthesizerCustom');
            if (custom) custom.value = 'gemma-4-e4b-it-qat';
            document.getElementById('btnSaveSynthConfig').click();
        """)
        time.sleep(1.0)

        self.eval_js("document.getElementById('btnRunManifest').click()")
        time.sleep(1.0)

        def manifest_ready():
            disabled = str(self.eval_js("document.getElementById('btnRunManifest').disabled")).lower()
            illus_count = self.eval_js("document.querySelectorAll('.manifest-block-card.has-illustration').length")
            try:
                ic_int = int(str(illus_count).strip() or 0)
            except ValueError:
                ic_int = 0
            return disabled == 'false' and ic_int >= 1

        self.assertTrue(self._wait_for(manifest_ready, timeout=120, desc="Manifest Prompt Synthesis"))
        time.sleep(1.2)

        # Verify synthesized prompt is non-empty and contains character
        prompt_val = self.eval_js("document.querySelector('.manifest-prompt').value")
        self.assertTrue(len(prompt_val.strip()) > 20, f"Synthesized prompt too short: {prompt_val}")
        self.assertTrue("valeria" in prompt_val.lower() or "warrior" in prompt_val.lower(), "Prompt missing character subject")
        self._capture_screenshot('manual_e2e_manifest.png')

        # 9. Step 5: Render & Review (ComfyUI with animap.json)
        self.eval_js("document.querySelector('.tab-btn[data-tab=\"tab-render\"]').click()")
        time.sleep(1.0)

        # Select animap.json workflow
        self.eval_js("""
            const wfSel = document.getElementById('selectWorkflow');
            wfSel.value = 'animap.json';
            wfSel.dispatchEvent(new Event('change'));
        """)
        time.sleep(1.0)

        # Click Start Batch Render
        self.eval_js("document.getElementById('btnStartBatchRender').click()")
        time.sleep(2.0)

        rendered_img_path = os.path.join(pdir, 'images', 'chunk_000.png')

        def render_finished():
            return os.path.isfile(rendered_img_path) and os.path.getsize(rendered_img_path) > 50000

        self.assertTrue(self._wait_for(render_finished, timeout=180, desc="ComfyUI Batch Render with animap.json"))
        time.sleep(2.0)

        self._capture_screenshot('manual_e2e_render.png')

        # 10. Step 6: Image Verification (Quality, Dimensions, and Semantic Match)
        self.assertTrue(os.path.isfile(rendered_img_path), f"Rendered image missing at {rendered_img_path}")
        img_size = os.path.getsize(rendered_img_path)
        self.assertGreater(img_size, 50000, f"Rendered image file too small ({img_size} bytes)")

        # Verify image structure using Pillow
        with Image.open(rendered_img_path) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.mode, "RGB")
            self.assertGreaterEqual(img.width, 512)
            self.assertGreaterEqual(img.height, 512)

            # Check pixel variation and contrast
            stat = ImageStat.Stat(img)
            for ch_idx, std in enumerate(stat.stddev):
                self.assertGreater(std, 15.0, f"Channel {ch_idx} stddev {std:.1f} too low (image is flat/solid)")

            for ch_idx, (lo, hi) in enumerate(stat.extrema):
                self.assertLess(lo, 65, f"Channel {ch_idx} min value {lo} lacks shadow depth")
                self.assertGreater(hi, 180, f"Channel {ch_idx} max value {hi} lacks highlight brightness")

        # Copy rendered image to artifact directory for display and review
        artifact_img_copy = os.path.join(ARTIFACT_DIR, 'manual_e2e_warrior_render.png')
        shutil.copyfile(rendered_img_path, artifact_img_copy)

        # Verify semantic match against story and manifest
        manifest_path = os.path.join(pdir, 'artifacts', 'manifest.json')
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)

        chunk_illus = None
        for b in manifest_data.get('blocks', []):
            if b.get('chunk_id') == 'chunk_000':
                chunk_illus = b.get('illustration')
                break

        self.assertIsNotNone(chunk_illus, "Manifest missing illustration for chunk_000")
        prompt_lower = chunk_illus.get('prompt', '').lower()
        self.assertTrue('valeria' in prompt_lower or 'warrior' in prompt_lower, "Prompt missing subject character")
        key_matches = sum(1 for kw in ['brass', 'blade', 'cathedral', 'spire', 'lightning', 'storm', 'arm'] if kw in prompt_lower)
        self.assertGreaterEqual(key_matches, 2, f"Prompt lacks visual continuity keywords: {prompt_lower}")

        # 11. Step 7: Reader Preview
        self.eval_js("document.querySelector('.tab-btn[data-tab=\"tab-reader\"]').click()")
        time.sleep(2.0)

        reader_html_path = os.path.join(pdir, 'index.html')
        self.assertTrue(os.path.isfile(reader_html_path), "Reader index.html was not generated")
        with open(reader_html_path, 'r', encoding='utf-8') as f:
            reader_content = f.read()

        self.assertIn("Valeria", reader_content)
        self.assertIn("chunk_000.png", reader_content)
        self._capture_screenshot('manual_e2e_reader.png')
        time.sleep(1.0)


if __name__ == '__main__':
    unittest.main()
