import os
import json
import unittest
from pipeline.comfy_client import (
    ComfyUIClient,
    load_workflow_file,
    find_missing_workflow_tags,
    replace_wildcard_tags_in_obj,
    REQUIRED_WORKFLOW_TAGS
)

class TestWorkflowWildcardTags(unittest.TestCase):
    def setUp(self):
        self.client = ComfyUIClient()
        self.wf_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'workflows')

    def test_required_tags_present_in_all_repo_workflows(self):
        """Validates that every workflow in the workflows directory has all required wildcard tags."""
        workflow_files = [f for f in os.listdir(self.wf_dir) if f.endswith('.json')]
        self.assertGreater(len(workflow_files), 0)

        for fname in workflow_files:
            fpath = os.path.join(self.wf_dir, fname)
            wf = load_workflow_file(fpath)
            missing = find_missing_workflow_tags(wf)
            self.assertEqual(
                missing, [],
                f"Workflow '{fname}' is missing required tags: {missing}"
            )

    def test_animap_loads_without_encoding_error(self):
        """Explicitly tests that animap.json loads without UTF-8 / JSON decode errors."""
        animap_path = os.path.join(self.wf_dir, 'animap.json')
        wf = load_workflow_file(animap_path)
        self.assertIsInstance(wf, dict)
        missing = find_missing_workflow_tags(wf)
        self.assertEqual(missing, [])

    def test_flux_dev_loads_without_encoding_error(self):
        """Explicitly tests that flux_dev.json loads without UTF-8 / JSON decode errors."""
        flux_path = os.path.join(self.wf_dir, 'flux_dev.json')
        wf = load_workflow_file(flux_path)
        self.assertIsInstance(wf, dict)
        missing = find_missing_workflow_tags(wf)
        self.assertEqual(missing, [])

    def test_missing_tags_triggers_validation_error(self):
        """Ensures that omitting any required tag raises a descriptive ValueError."""
        bad_wf = {
            '1': {'inputs': {'text': '%PositivePrompt%'}, 'class_type': 'CLIPTextEncode'},
            '2': {'inputs': {'width': '%Width%', 'height': '%Height%'}, 'class_type': 'EmptyLatentImage'}
        }
        with self.assertRaises(ValueError) as ctx:
            self.client.inject_parameters(bad_wf, prompt='test', negative_prompt='neg', width=1024, height=1024)
        self.assertIn('%NegativePrompt%', str(ctx.exception))

        bad_wf2 = {
            '1': {'inputs': {'text': '%PositivePrompt%'}, 'class_type': 'CLIPTextEncode'},
            '2': {'inputs': {'text': '%NegativePrompt%'}, 'class_type': 'CLIPTextEncode'}
        }
        with self.assertRaises(ValueError) as ctx:
            self.client.inject_parameters(bad_wf2, prompt='test', negative_prompt='neg', width=1024, height=1024)
        self.assertIn('%Width%', str(ctx.exception))
        self.assertIn('%Height%', str(ctx.exception))

    def test_wildcard_replacement_values(self):
        """Tests that wildcard tags are replaced cleanly and width/height are cast to integers."""
        wf = {
            '1': {'inputs': {'positive': '%PositivePrompt%', 'negative': '%NegativePrompt%'}, 'class_type': 'Eff. Loader SDXL'},
            '2': {'inputs': {'width': '%Width%', 'height': '%Height%'}, 'class_type': 'EmptyLatentImage'},
            '3': {'inputs': {'seed': 100}, 'class_type': 'KSampler'}
        }
        injected, _ = self.client.inject_parameters(
            workflow=wf,
            prompt='Magical Forest',
            negative_prompt='dark, murky',
            width=1920,
            height=1080,
            seed=424242
        )
        self.assertEqual(injected['1']['inputs']['positive'], 'Magical Forest')
        self.assertEqual(injected['1']['inputs']['negative'], 'dark, murky')
        self.assertEqual(injected['2']['inputs']['width'], 1920)
        self.assertIsInstance(injected['2']['inputs']['width'], int)
        self.assertEqual(injected['2']['inputs']['height'], 1080)
        self.assertIsInstance(injected['2']['inputs']['height'], int)
        self.assertEqual(injected['3']['inputs']['seed'], 424242)

if __name__ == '__main__':
    unittest.main()
