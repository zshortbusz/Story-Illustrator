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
import threading
import requests
import asyncio
import websockets
from typing import Dict, Any, Optional, Tuple, List


# Persistent background event loop for async WebSocket tracking.
# Avoids creating/destroying event loops per render call and is safe
# to call from any thread (Flask workers, ThreadPoolExecutor, etc.).
_ws_loop: Optional[asyncio.AbstractEventLoop] = None
_ws_loop_lock = threading.Lock()


def _get_ws_event_loop() -> asyncio.AbstractEventLoop:
    """Lazily initializes a persistent background event loop thread."""
    global _ws_loop
    if _ws_loop is not None and _ws_loop.is_running():
        return _ws_loop
    with _ws_loop_lock:
        if _ws_loop is not None and _ws_loop.is_running():
            return _ws_loop
        loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run_loop, daemon=True, name="comfy-ws-loop")
        t.start()
        _ws_loop = loop
        return loop


REQUIRED_WORKFLOW_TAGS = ["%PositivePrompt%", "%NegativePrompt%", "%Width%", "%Height%"]


def load_workflow_file(filepath: str) -> Dict[str, Any]:
    """
    Loads a ComfyUI workflow JSON file, robustly handling multiple encodings
    (UTF-8, UTF-8 with BOM, UTF-16, Latin-1) without decoding errors.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Workflow file not found: {filepath}")
    with open(filepath, "rb") as f:
        raw = f.read()

    for enc in ["utf-8-sig", "utf-8", "utf-16", "latin-1"]:
        try:
            text = raw.decode(enc)
            return json.loads(text)
        except Exception:
            continue

    raise ValueError(f"Could not parse workflow JSON from {filepath}. Ensure it is a valid ComfyUI JSON file.")


def find_missing_workflow_tags(workflow: Dict[str, Any]) -> List[str]:
    """
    Checks whether a ComfyUI workflow contains all required wildcard tags.
    Returns a list of missing tags (empty list if all tags are present).
    """
    dumped = json.dumps(workflow)
    missing = []
    if "%PositivePrompt%" not in dumped:
        missing.append("%PositivePrompt%")
    if "%NegativePrompt%" not in dumped:
        missing.append("%NegativePrompt%")

    has_width = "%Width%" in dumped or "%width%" in dumped or "%WIDTH%" in dumped
    if not has_width:
        missing.append("%Width%")

    has_height = "%Height%" in dumped or "%height%" in dumped or "%HEIGHT%" in dumped
    if not has_height:
        missing.append("%Height%")

    return missing


def replace_wildcard_tags_in_obj(obj: Any, prompt: str, negative_prompt: str, width: int, height: int) -> Any:
    """
    Recursively replaces wildcard tags in a JSON data structure.
    Converts exact '%Width%' and '%Height%' matches to integer values for ComfyUI.
    """
    if isinstance(obj, dict):
        return {k: replace_wildcard_tags_in_obj(v, prompt, negative_prompt, width, height) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_wildcard_tags_in_obj(item, prompt, negative_prompt, width, height) for item in obj]
    elif isinstance(obj, str):
        val = obj
        # Check exact replacements for integers
        if val.strip() in ["%Width%", "%width%", "%WIDTH%"]:
            return int(width)
        if val.strip() in ["%Height%", "%height%", "%HEIGHT%"]:
            return int(height)

        # String replacements
        if "%PositivePrompt%" in val:
            val = val.replace("%PositivePrompt%", prompt)
        if "%NegativePrompt%" in val:
            val = val.replace("%NegativePrompt%", negative_prompt)
        if "%Width%" in val:
            val = val.replace("%Width%", str(width))
        elif "%width%" in val:
            val = val.replace("%width%", str(width))
        elif "%WIDTH%" in val:
            val = val.replace("%WIDTH%", str(width))

        if "%Height%" in val:
            val = val.replace("%Height%", str(height))
        elif "%height%" in val:
            val = val.replace("%height%", str(height))
        elif "%HEIGHT%" in val:
            val = val.replace("%HEIGHT%", str(height))

        return val
    else:
        return obj


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
        """Creates a modified copy of workflow with injected generation parameters via wildcard tags."""
        missing_tags = find_missing_workflow_tags(workflow)
        if missing_tags:
            raise ValueError(
                f"ComfyUI workflow is missing required wildcard tag(s): {', '.join(missing_tags)}.\n"
                f"Please open your ComfyUI workflow JSON and replace:\n"
                f"  - Positive prompt with %PositivePrompt%\n"
                f"  - Negative prompt with %NegativePrompt%\n"
                f"  - Width with \"%Width%\"\n"
                f"  - Height with \"%Height%\""
            )

        wf = copy.deepcopy(workflow)
        if "_bindings" in wf:
            del wf["_bindings"]

        if seed is None:
            seed = random.randint(1, 1125899906842624)

        # 1. Replace wildcard tags
        wf = replace_wildcard_tags_in_obj(wf, prompt, negative_prompt, width, height)

        # 2. Update sampler seeds and SaveImage prefix
        bindings = self.detect_node_bindings(wf)
        samp_id = bindings.get("sampler_node")
        if samp_id and samp_id in wf:
            inputs = wf[samp_id].setdefault("inputs", {})
            if "noise_seed" in inputs:
                inputs["noise_seed"] = seed
            if "seed" in inputs or "noise_seed" not in inputs:
                inputs["seed"] = seed
        else:
            for nid, node in wf.items():
                if isinstance(node, dict) and "inputs" in node:
                    inp = node["inputs"]
                    if "noise_seed" in inp and not isinstance(inp["noise_seed"], list):
                        inp["noise_seed"] = seed
                    elif "seed" in inp and not isinstance(inp["seed"], list):
                        inp["seed"] = seed

        save_id = bindings.get("save_image_node")
        if save_id and save_id in wf:
            inputs = wf[save_id].setdefault("inputs", {})
            inputs["filename_prefix"] = filename_prefix
        else:
            for nid, node in wf.items():
                if isinstance(node, dict) and node.get("class_type") == "SaveImage":
                    node.setdefault("inputs", {})["filename_prefix"] = filename_prefix

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

        # Await completion via WebSocket (uses persistent background event loop)
        try:
            loop = _get_ws_event_loop()
            future = asyncio.run_coroutine_threadsafe(
                self._track_websocket_execution(client_id, prompt_id), loop
            )
            future.result(timeout=self.timeout)
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
