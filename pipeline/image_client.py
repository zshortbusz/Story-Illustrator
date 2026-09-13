"""
pipeline/image_client.py: Backend-agnostic image generation client.
Supports both local headless ComfyUI and remote OpenAI-compatible Images APIs
(e.g., DALL-E 3, Together AI Flux, Fireworks, custom endpoints) with Bring Your Own Key & Endpoint.
"""

import os
import json
import base64
import requests
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple

from pipeline.comfy_client import ComfyUIClient


class BaseImageClient(ABC):
    """Abstract base interface for all image generation backends."""

    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        """Returns health status dictionary."""
        pass

    @abstractmethod
    def render(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        seed: Optional[int] = None,
        output_filepath: Optional[str] = None
    ) -> Dict[str, Any]:
        """Renders an image from a prompt and writes it to output_filepath."""
        pass


class ComfyUIImageClient(BaseImageClient):
    """Image client implementation for local or remote ComfyUI servers."""

    def __init__(
        self,
        host: str = "127.0.0.1:8188",
        workflow: Optional[Dict[str, Any]] = None,
        workflow_path: Optional[str] = None,
        timeout: int = 300
    ):
        self.host = host
        self.client = ComfyUIClient(host=host, timeout=timeout)
        self.workflow = workflow
        self.workflow_path = workflow_path
        self.timeout = timeout

    def check_health(self) -> Dict[str, Any]:
        health = self.client.check_health()
        health["backend"] = "comfyui"
        return health

    def set_workflow(self, workflow: Dict[str, Any]):
        self.workflow = workflow

    def render(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1344,
        height: int = 768,
        seed: Optional[int] = None,
        output_filepath: Optional[str] = None
    ) -> Dict[str, Any]:
        if not self.workflow:
            raise ValueError("No ComfyUI workflow provided for ComfyUIImageClient.")

        return self.client.render(
            workflow=self.workflow,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=seed,
            output_filepath=output_filepath
        )


class OpenAIImageClient(BaseImageClient):
    """
    Image client for OpenAI and OpenAI-compatible Image Generation APIs
    (e.g., DALL-E 3, Together AI Flux/SDXL, Fireworks, Fal.ai proxies).
    """

    def __init__(
        self,
        api_base: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
        model: str = "dall-e-3",
        quality: str = "standard",
        style: str = "vivid",
        timeout: int = 180
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key or os.environ.get("IMAGE_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        self.model = model or "dall-e-3"
        self.quality = quality
        self.style = style
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_health(self) -> Dict[str, Any]:
        """Checks if the OpenAI-compatible endpoint is reachable."""
        url = f"{self.api_base}/models"
        headers = self._get_headers()
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id") for m in data.get("data", []) if "id" in m]
                return {
                    "online": True,
                    "backend": "openai_compatible",
                    "url": self.api_base,
                    "models": models,
                    "message": f"Image API endpoint is reachable with model '{self.model}'."
                }
            return {
                "online": False,
                "backend": "openai_compatible",
                "url": self.api_base,
                "models": [],
                "message": f"Image API returned HTTP status {resp.status_code}."
            }
        except Exception as e:
            return {
                "online": False,
                "backend": "openai_compatible",
                "url": self.api_base,
                "models": [],
                "message": f"Image API connection error at {self.api_base}: {str(e)}"
            }

    def _resolve_size(self, width: int, height: int) -> str:
        """Translates width/height into API-supported image dimension string."""
        if "dall-e-3" in self.model.lower():
            if width > height:
                return "1792x1024"
            elif height > width:
                return "1024x1792"
            return "1024x1024"
        elif "dall-e-2" in self.model.lower():
            if max(width, height) <= 256:
                return "256x256"
            elif max(width, height) <= 512:
                return "512x512"
            return "1024x1024"
        # Standard custom dimensions for Flux / Together / SDXL endpoints
        return f"{width}x{height}"

    def render(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        seed: Optional[int] = None,
        output_filepath: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes POST /images/generations against the OpenAI-compatible endpoint,
        retrieves the image bytes, and writes to output_filepath.
        """
        url = f"{self.api_base}/images/generations"
        headers = self._get_headers()
        size_str = self._resolve_size(width, height)

        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": size_str,
            "response_format": "b64_json"
        }

        # DALL-E 3 supports quality and style flags
        if "dall-e-3" in self.model.lower():
            if self.quality:
                payload["quality"] = self.quality
            if self.style:
                payload["style"] = self.style

        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)

        # Some third-party OpenAI-compatible endpoints only support response_format="url"
        if resp.status_code == 400 and "response_format" in resp.text:
            payload.pop("response_format", None)
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)

        if resp.status_code != 200:
            raise RuntimeError(f"Image generation failed (HTTP {resp.status_code}): {resp.text}")

        data = resp.json()
        items = data.get("data", [])
        if not items:
            raise RuntimeError(f"Image API returned no image data: {data}")

        img_item = items[0]
        img_bytes = b""
        if "b64_json" in img_item:
            img_bytes = base64.b64decode(img_item["b64_json"])
        elif "url" in img_item:
            img_url = img_item["url"]
            fetch_resp = requests.get(img_url, timeout=self.timeout)
            if fetch_resp.status_code == 200:
                img_bytes = fetch_resp.content
            else:
                raise RuntimeError(f"Failed to fetch generated image from URL: {fetch_resp.status_code}")
        else:
            raise RuntimeError(f"Unrecognized image response format: {img_item}")

        if output_filepath:
            os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
            with open(output_filepath, "wb") as f:
                f.write(img_bytes)

        return {
            "bytes_length": len(img_bytes),
            "filepath": output_filepath,
            "seed": seed,
            "backend": "openai_compatible",
            "model": self.model,
            "size": size_str
        }


def create_image_client(
    config: Optional[Dict[str, Any]] = None,
    workflow: Optional[Dict[str, Any]] = None,
    workflow_path: Optional[str] = None,
    host: Optional[str] = None
) -> BaseImageClient:
    """
    Factory creating the appropriate BaseImageClient based on configuration.
    Defaults to ComfyUIImageClient (host: 127.0.0.1:8188).
    """
    config = config or {}
    backend = config.get("backend", "comfyui").lower()

    if backend in ["openai_compatible", "openai", "dalle", "flux"]:
        openai_cfg = config.get("openai_compatible", {})
        api_base = openai_cfg.get("api_base") or config.get("api_base") or "https://api.openai.com/v1"
        api_key = openai_cfg.get("api_key") or config.get("api_key")
        model = openai_cfg.get("model") or config.get("model") or "dall-e-3"
        quality = openai_cfg.get("quality", "standard")
        style = openai_cfg.get("style", "vivid")
        return OpenAIImageClient(
            api_base=api_base,
            api_key=api_key,
            model=model,
            quality=quality,
            style=style
        )

    # Default to ComfyUI
    comfy_cfg = config.get("comfyui", {})
    resolved_host = host or comfy_cfg.get("host") or config.get("host") or "127.0.0.1:8188"
    return ComfyUIImageClient(
        host=resolved_host,
        workflow=workflow,
        workflow_path=workflow_path
    )
