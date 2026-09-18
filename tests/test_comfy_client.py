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

    def test_efficiency_loader_workflow(self):
        eff_wf = {
            "1": {
                "inputs": {
                    "base_ckpt_name": "ilustmix_v10.safetensors",
                    "positive": "Positive Prompt",
                    "negative": "Negative Prompt",
                    "empty_latent_width": 1536,
                    "empty_latent_height": 1536,
                    "batch_size": 1
                },
                "class_type": "Eff. Loader SDXL",
                "_meta": {"title": "Eff. Loader SDXL"}
            },
            "4": {
                "inputs": {
                    "noise_seed": 12345,
                    "steps": 20,
                    "sdxl_tuple": ["1", 0],
                    "latent_image": ["1", 1]
                },
                "class_type": "KSampler SDXL (Eff.)",
                "_meta": {"title": "KSampler SDXL (Eff.)"}
            },
            "5": {
                "inputs": {
                    "filename_prefix": "ComfyUI",
                    "images": ["4", 3]
                },
                "class_type": "SaveImage"
            }
        }

        bindings = self.client.detect_node_bindings(eff_wf)
        self.assertEqual(bindings.get("positive_prompt_node"), "1")
        self.assertEqual(bindings.get("negative_prompt_node"), "1")
        self.assertEqual(bindings.get("latent_node"), "1")
        self.assertEqual(bindings.get("sampler_node"), "4")
        self.assertEqual(bindings.get("save_image_node"), "5")

        injected, _ = self.client.inject_parameters(
            workflow=eff_wf,
            prompt="A cyberpunk city in the rain",
            negative_prompt="low quality, deformed",
            width=1280,
            height=720,
            seed=424242,
            filename_prefix="eff_render"
        )

        # Verify positive and negative injected into Eff. Loader node inputs
        self.assertEqual(injected["1"]["inputs"]["positive"], "A cyberpunk city in the rain")
        self.assertEqual(injected["1"]["inputs"]["negative"], "low quality, deformed")
        self.assertEqual(injected["1"]["inputs"]["empty_latent_width"], 1280)
        self.assertEqual(injected["1"]["inputs"]["empty_latent_height"], 720)
        self.assertEqual(injected["4"]["inputs"]["noise_seed"], 424242)
        self.assertEqual(injected["5"]["inputs"]["filename_prefix"], "eff_render")

    def test_actual_draw_workflow_file(self):
        import os, json
        draw_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workflows", "!Draw.json")
        if os.path.exists(draw_path):
            with open(draw_path, "r", encoding="utf-8") as f:
                draw_wf = json.load(f)

            bindings = self.client.detect_node_bindings(draw_wf)
            self.assertEqual(bindings.get("positive_prompt_node"), "1")
            self.assertEqual(bindings.get("negative_prompt_node"), "1")
            self.assertEqual(bindings.get("latent_node"), "1")
            self.assertEqual(bindings.get("sampler_node"), "4")
            self.assertEqual(bindings.get("save_image_node"), "5")

            injected, _ = self.client.inject_parameters(
                workflow=draw_wf,
                prompt="Epic fantasy landscape",
                negative_prompt="bad anatomy",
                width=1344,
                height=768,
                seed=777777,
                filename_prefix="draw_test"
            )

            self.assertEqual(injected["1"]["inputs"]["positive"], "Epic fantasy landscape")
            self.assertEqual(injected["1"]["inputs"]["negative"], "bad anatomy")
            self.assertEqual(injected["1"]["inputs"]["empty_latent_width"], 1344)
            self.assertEqual(injected["1"]["inputs"]["empty_latent_height"], 768)
            self.assertEqual(injected["4"]["inputs"]["noise_seed"], 777777)
            self.assertEqual(injected["5"]["inputs"]["filename_prefix"], "draw_test")

if __name__ == "__main__":
    unittest.main()
