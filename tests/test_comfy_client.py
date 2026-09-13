import unittest
from pipeline.comfy_client import ComfyUIClient

class TestComfyClient(unittest.TestCase):
    def setUp(self):
        self.client = ComfyUIClient()
        self.sample_wf = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 100,
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0]
                }
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": 1024,
                    "height": 1024
                }
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "old prompt"
                },
                "_meta": {"title": "CLIP Text Encode (Prompt)"}
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "old neg"
                },
                "_meta": {"title": "CLIP Text Encode (Negative Prompt)"}
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "old_prefix"
                }
            }
        }

    def test_detect_node_bindings(self):
        bindings = self.client.detect_node_bindings(self.sample_wf)
        self.assertEqual(bindings.get("sampler_node"), "3")
        self.assertEqual(bindings.get("positive_prompt_node"), "6")
        self.assertEqual(bindings.get("negative_prompt_node"), "7")
        self.assertEqual(bindings.get("latent_node"), "5")
        self.assertEqual(bindings.get("save_image_node"), "9")

    def test_inject_parameters(self):
        injected, bindings = self.client.inject_parameters(
            workflow=self.sample_wf,
            prompt="A majestic brass robot in a misty forest",
            negative_prompt="blurry, distorted",
            width=1344,
            height=768,
            seed=999999,
            filename_prefix="test_render"
        )

        self.assertEqual(injected["6"]["inputs"]["text"], "A majestic brass robot in a misty forest")
        self.assertEqual(injected["7"]["inputs"]["text"], "blurry, distorted")
        self.assertEqual(injected["5"]["inputs"]["width"], 1344)
        self.assertEqual(injected["5"]["inputs"]["height"], 768)
        self.assertEqual(injected["3"]["inputs"]["seed"], 999999)
        self.assertEqual(injected["9"]["inputs"]["filename_prefix"], "test_render")

if __name__ == "__main__":
    unittest.main()
