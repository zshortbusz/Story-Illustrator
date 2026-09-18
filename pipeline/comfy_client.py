"""
pipeline/comfy_client.py: ComfyUI REST & WebSocket API client.
Handles workflow parameter injection, job submission, WebSocket execution tracking,
and image retrieval from ComfyUI servers.
"""

import os
import json
import uuid
import time
import copy
import random
import requests
import asyncio
import websockets
from typing import Dict, Any, Optional, Tuple


class ComfyUIClient:
    def __init__(self, host: str = "127.0.0.1:8188", timeout: int = 300):
        self.host = host.rstrip("/")
        if "://" in self.host:
            self.host = self.host.split("://")[1]
        self.http_base = f"http://{self.host}"
        self.ws_base = f"ws://{self.host}/ws"
        self.timeout = timeout

    def check_health(self) -> Dict[str, Any]:
        """Checks if ComfyUI server is reachable and reports GPU status if available."""
        url = f"{self.http_base}/system_stats"
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                stats = resp.json()
                return {
                    "online": True,
                    "url": self.http_base,
                    "stats": stats,
                    "message": "ComfyUI server is online."
                }
            return {
                "online": False,
                "url": self.http_base,
                "stats": {},
                "message": f"ComfyUI returned HTTP status {resp.status_code}."
            }
        except Exception as e:
            return {
                "online": False,
                "url": self.http_base,
                "stats": {},
                "message": f"ComfyUI is offline at {self.http_base}: {str(e)}"
            }

    def detect_node_bindings(self, workflow: Dict[str, Any]) -> Dict[str, str]:
        """
        Discovers or parses node bindings for parameter injection.
        Checks for explicit '_bindings' metadata, or auto-detects by class_type and title.
        """
        bindings = workflow.get("_bindings", {})
        if bindings and all(k in bindings for k in ["positive_prompt_node", "latent_node", "sampler_node"]):
            return dict(bindings)

        detected: Dict[str, str] = {}
        # Find KSampler first
        sampler_id = None
        for nid, node in workflow.items():
            if nid.startswith("_"):
                continue
            ctype = node.get("class_type", "")
            if "KSampler" in ctype:
                sampler_id = nid
                detected["sampler_node"] = nid
                break

        # Discover connected positive, negative, and latent nodes from KSampler
        if sampler_id:
            s_inputs = workflow[sampler_id].get("inputs", {})
            if "positive" in s_inputs and isinstance(s_inputs["positive"], list):
                detected["positive_prompt_node"] = str(s_inputs["positive"][0])
            if "negative" in s_inputs and isinstance(s_inputs["negative"], list):
                detected["negative_prompt_node"] = str(s_inputs["negative"][0])
            if "latent_image" in s_inputs and isinstance(s_inputs["latent_image"], list):
                detected["latent_node"] = str(s_inputs["latent_image"][0])

        # Fallbacks by class_type
        for nid, node in workflow.items():
            if nid.startswith("_"):
                continue
            ctype = node.get("class_type", "")
            title = node.get("_meta", {}).get("title", "").lower()
            inputs = node.get("inputs", {})

            # Support Efficiency Nodes (Eff. Loader SDXL / Efficient Loader)
            is_eff_loader = (
                "Eff. Loader" in ctype or
                "Efficient Loader" in ctype or
                ("positive" in inputs and isinstance(inputs.get("positive"), str) and
                 "negative" in inputs and isinstance(inputs.get("negative"), str))
            )
            if is_eff_loader:
                if "positive_prompt_node" not in detected:
                    detected["positive_prompt_node"] = nid
                if "negative_prompt_node" not in detected:
                    detected["negative_prompt_node"] = nid
                if "latent_node" not in detected:
                    detected["latent_node"] = nid

            if "positive_prompt_node" not in detected and ctype == "CLIPTextEncode" and "negative" not in title:
                detected["positive_prompt_node"] = nid
            elif "negative_prompt_node" not in detected and ctype == "CLIPTextEncode" and "negative" in title:
                detected["negative_prompt_node"] = nid
            elif "latent_node" not in detected and ctype == "EmptyLatentImage":
                detected["latent_node"] = nid
            elif "save_image_node" not in detected and ctype == "SaveImage":
                detected["save_image_node"] = nid

        return detected

    def inject_parameters(
        self,
        workflow: Dict[str, Any],
        prompt: str,
        negative_prompt: str = "",
        width: int = 1344,
        height: int = 768,
        seed: Optional[int] = None,
        filename_prefix: str = "asi_render"
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """Creates a modified copy of workflow with injected generation parameters."""
        wf = copy.deepcopy(workflow)
        # Remove metadata wrapper if present
        bindings = self.detect_node_bindings(wf)
        if "_bindings" in wf:
            del wf["_bindings"]

        if seed is None:
            seed = random.randint(1, 1125899906842624)

        # Inject Positive Prompt
        pos_id = bindings.get("positive_prompt_node")
        if pos_id and pos_id in wf:
            pos_inputs = wf[pos_id].setdefault("inputs", {})
            ctype = wf[pos_id].get("class_type", "")
            if "positive" in pos_inputs or "Eff. Loader" in ctype or "Efficient Loader" in ctype:
                pos_inputs["positive"] = prompt
            else:
                pos_inputs["text"] = prompt

        # Inject Negative Prompt
        neg_id = bindings.get("negative_prompt_node")
        if neg_id and neg_id in wf:
            neg_inputs = wf[neg_id].setdefault("inputs", {})
            ctype = wf[neg_id].get("class_type", "")
            if "negative" in neg_inputs or "Eff. Loader" in ctype or "Efficient Loader" in ctype:
                neg_inputs["negative"] = negative_prompt
            else:
                neg_inputs["text"] = negative_prompt

        # Inject Latent Dimensions
        lat_id = bindings.get("latent_node")
        if lat_id and lat_id in wf:
            lat_inputs = wf[lat_id].setdefault("inputs", {})
            ctype = wf[lat_id].get("class_type", "")
            if "empty_latent_width" in lat_inputs or "Eff. Loader" in ctype or "Efficient Loader" in ctype:
                lat_inputs["empty_latent_width"] = width
                lat_inputs["empty_latent_height"] = height
            else:
                lat_inputs["width"] = width
                lat_inputs["height"] = height

        # Inject Seed
        samp_id = bindings.get("sampler_node")
        if samp_id and samp_id in wf:
            inputs = wf[samp_id].setdefault("inputs", {})
            if "noise_seed" in inputs:
                inputs["noise_seed"] = seed
            if "seed" in inputs or "noise_seed" not in inputs:
                inputs["seed"] = seed

        # Inject SaveImage filename prefix
        save_id = bindings.get("save_image_node")
        if save_id and save_id in wf:
            inputs = wf[save_id].setdefault("inputs", {})
            inputs["filename_prefix"] = filename_prefix

        return wf, bindings

    async def _track_websocket_execution(self, client_id: str, prompt_id: str) -> None:
        """Listens on WebSocket for ComfyUI execution completion or errors."""
        ws_url = f"{self.ws_base}?clientId={client_id}"
        async with websockets.connect(ws_url) as ws:
            start_time = time.time()
            while True:
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"ComfyUI render timed out after {self.timeout}s.")

                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    continue

                if isinstance(msg, str):
                    data = json.loads(msg)
                    mtype = data.get("type")
                    mdata = data.get("data", {})

                    if mtype == "execution_error":
                        if mdata.get("prompt_id") == prompt_id:
                            raise RuntimeError(f"ComfyUI Execution Error: {mdata.get('exception_message')}")

                    elif mtype == "executing":
                        # Node null means graph execution completed
                        if mdata.get("prompt_id") == prompt_id and mdata.get("node") is None:
                            return

    def _poll_history_fallback(self, prompt_id: str) -> Dict[str, Any]:
        """Polls /history/{prompt_id} until completed (used as fallback or validation)."""
        start_time = time.time()
        url = f"{self.http_base}/history/{prompt_id}"
        while time.time() - start_time < self.timeout:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                history = resp.json()
                if prompt_id in history:
                    return history[prompt_id]
            time.sleep(1.0)
        raise TimeoutError(f"ComfyUI history polling timed out for prompt {prompt_id}.")

    def render(
        self,
        workflow: Dict[str, Any],
        prompt: str,
        negative_prompt: str = "",
        width: int = 1344,
        height: int = 768,
        seed: Optional[int] = None,
        output_filepath: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a prompt through ComfyUI:
        1. Injects parameters into workflow.
        2. Submits prompt via POST /prompt with client_id.
        3. Awaits completion via WebSocket.
        4. Queries history and downloads output image to output_filepath.
        """
        client_id = str(uuid.uuid4())
        prefix = f"asi_{int(time.time())}"
        injected_wf, bindings = self.inject_parameters(
            workflow=workflow,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=seed,
            filename_prefix=prefix
        )

        # Submit prompt
        post_url = f"{self.http_base}/prompt"
        payload = {"prompt": injected_wf, "client_id": client_id}
        resp = requests.post(post_url, json=payload, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to queue prompt in ComfyUI (HTTP {resp.status_code}): {resp.text}")

        resp_data = resp.json()
        prompt_id = resp_data.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"Invalid response from ComfyUI: {resp_data}")

        # Await completion via WebSocket
        try:
            asyncio.run(self._track_websocket_execution(client_id, prompt_id))
        except Exception as ws_err:
            # Fallback to polling history
            print(f"[*] WebSocket tracking notice: {ws_err}. Falling back to history polling...")

        # Retrieve history to get output filename
        history_data = self._poll_history_fallback(prompt_id)
        outputs = history_data.get("outputs", {})

        # Find output image details
        image_info = None
        for nid, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                image_info = images[0]
                break

        if not image_info:
            raise RuntimeError(f"ComfyUI completed but no output images were produced. History: {history_data}")

        filename = image_info["filename"]
        subfolder = image_info.get("subfolder", "")
        img_type = image_info.get("type", "output")

        # Download image bytes
        view_url = f"{self.http_base}/view?filename={filename}&subfolder={subfolder}&type={img_type}"
        img_resp = requests.get(view_url, timeout=30)
        if img_resp.status_code != 200:
            raise RuntimeError(f"Failed to download image from {view_url} (HTTP {img_resp.status_code})")

        if output_filepath:
            os.makedirs(os.path.dirname(os.path.abspath(output_filepath)), exist_ok=True)
            with open(output_filepath, "wb") as f:
                f.write(img_resp.content)

        return {
            "prompt_id": prompt_id,
            "filename": filename,
            "subfolder": subfolder,
            "saved_to": output_filepath,
            "bytes_length": len(img_resp.content)
        }
