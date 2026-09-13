"""
pipeline/llm_client.py: LM Studio OpenAI-compatible client wrapper.
Supports free-form text completions, structured parsing without strict JSON enforcement,
dynamic model listing, health checks, and fallback extraction.
"""

import re
import json
import time
import requests
from typing import Dict, Any, List, Optional, Tuple, Set


class LMStudioClient:
    def __init__(self, api_base: str = "http://localhost:1234/v1", timeout: int = 120):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def check_health(self) -> Dict[str, Any]:
        """Checks if LM Studio server is reachable."""
        url = f"{self.api_base}/models"
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id") for m in data.get("data", []) if "id" in m]
                return {
                    "online": True,
                    "url": self.api_base,
                    "models": models,
                    "message": f"LM Studio is online with {len(models)} model(s) available."
                }
            return {
                "online": False,
                "url": self.api_base,
                "models": [],
                "message": f"LM Studio returned status code {resp.status_code}."
            }
        except Exception as e:
            return {
                "online": False,
                "url": self.api_base,
                "models": [],
                "message": f"LM Studio connection error at {self.api_base}: {str(e)}"
            }

    def list_available_models(self) -> List[str]:
        """Returns list of model IDs reported by LM Studio."""
        health = self.check_health()
        return health.get("models", [])

    def _resolve_model(self, model: str) -> str:
        """Finds matching model or falls back to first loaded model."""
        available = self.list_available_models()
        if not available:
            return model
        if model in available:
            return model
        matching = [m for m in available if model.lower() in m.lower()]
        if matching:
            return matching[0]
        return available[0]

    def resolve_model(self, model: str) -> str:
        """Public resolver returning matching model or fallback from LM Studio."""
        return self._resolve_model(model)

    def chat_text(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        retries: int = 3,
        backoff: float = 2.0
    ) -> str:
        """
        Executes free-form text chat completion without enforcing JSON response_format.
        Ideal for literary, creative, and reasoning models that struggle with rigid schema constraints.
        """
        url = f"{self.api_base}/chat/completions"
        chosen_model = self._resolve_model(model)

        payload = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature
        }
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = max_tokens
        else:
            payload["max_tokens"] = -1

        last_error = None
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")

                data = resp.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or ""
                # If content is empty because reasoning model generated in reasoning_content or got cut off
                if not content.strip() and msg.get("reasoning_content"):
                    content = msg.get("reasoning_content", "")
                return content.strip()

            except Exception as e:
                last_error = e
                if attempt < retries:
                    time.sleep(backoff ** attempt)

        raise RuntimeError(f"Failed to communicate with LM Studio after {retries} attempts: {last_error}")

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        retries: int = 3,
        backoff: float = 2.0
    ) -> Dict[str, Any]:
        """
        Calls LM Studio chat completions and robustly parses JSON.
        If strict json_object is rejected by the model/backend, automatically retries in free text mode.
        """
        raw_text = ""
        url = f"{self.api_base}/chat/completions"
        chosen_model = self._resolve_model(model)

        # Attempt 1: Try without forcing response_format first to avoid grammar crashes
        for attempt in range(1, retries + 1):
            try:
                payload = {
                    "model": chosen_model,
                    "messages": messages,
                    "temperature": temperature
                }
                if max_tokens is not None and max_tokens > 0:
                    payload["max_tokens"] = max_tokens
                else:
                    payload["max_tokens"] = -1
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")

                data = resp.json()
                raw_text = data["choices"][0]["message"]["content"]
                break
            except Exception as e:
                if attempt == retries:
                    raise RuntimeError(f"LM Studio chat error: {e}")
                time.sleep(backoff ** attempt)

        # Attempt JSON extraction
        extracted = self._extract_json_block(raw_text)
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            cleaned = self._clean_json_syntax(extracted)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        # Return dict with raw_text if JSON decoding cannot parse it
        return {"_raw_text": raw_text}

    def _extract_json_block(self, text: str) -> str:
        """Extracts JSON substring if enclosed in markdown code fences or surrounded by prose."""
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            return text[first_brace:last_brace + 1].strip()
        return text

    def _clean_json_syntax(self, json_str: str) -> str:
        """Fixes trailing commas and common LLM syntax quirks."""
        cleaned = re.sub(r",\s*([\]}])", r"\1", json_str)
        return cleaned


# -----------------------------------------------------------------------------
# Robust Text Parsers (Eliminates JSON / Tool-Calling Failures)
# -----------------------------------------------------------------------------

def parse_beats_response(raw_text: str, target_chunk_ids: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """
    Parses beat selection from either JSON or human-readable tagged/bulleted text.
    Handles responses from creative wordsmith models that don't output valid JSON.
    """
    # 1. Check for JSON structure
    client = LMStudioClient()
    extracted_json = client._extract_json_block(raw_text)
    try:
        data = json.loads(extracted_json)
        if isinstance(data, dict) and "selected_beats" in data and isinstance(data["selected_beats"], list):
            beats = []
            for b in data["selected_beats"]:
                cid = b.get("chunk_id")
                if target_chunk_ids is None or cid in target_chunk_ids:
                    beats.append({
                        "chunk_id": cid,
                        "scene_type": b.get("scene_type", "landscape"),
                        "characters_present": b.get("characters_present", []),
                        "setting": b.get("setting", ""),
                        "action_beat": b.get("action_beat", ""),
                        "camera_framing": b.get("camera_framing", "")
                    })
            return beats
    except Exception:
        pass

    # 2. Check for "None" or "No beats" indication
    lower = raw_text.lower().strip()
    if lower in ["none", "no beats", "no illustration", "no beats selected", "selected_beats: []"]:
        return []

    # 3. Parse free-form text / tagged blocks
    beats: List[Dict[str, Any]] = []

    # Split by explicit [BEAT] or chunk header occurrences
    # Patterns like: [BEAT], BEAT 1, chunk_004, **chunk_004**
    chunk_pattern = r"(chunk_\d{3,4})"
    matches = list(re.finditer(chunk_pattern, raw_text, re.IGNORECASE))

    if not matches:
        return []

    for i, match in enumerate(matches):
        cid = match.group(1).lower()
        if target_chunk_ids and cid not in target_chunk_ids:
            continue

        # Extract text block corresponding to this chunk
        start_pos = match.start()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        block_text = raw_text[start_pos:end_pos]

        # Extract scene_type (landscape, portrait, square)
        stype = "landscape"
        stype_m = re.search(r"(?:scene[_\s-]?type|aspect[_\s-]?ratio|format)[:\s]+(landscape|portrait|square)", block_text, re.IGNORECASE)
        if stype_m:
            stype = stype_m.group(1).lower()

        # Extract action
        action = ""
        action_m = re.search(r"(?:action[_\s-]?beat|action|description|visual)[:\s]+([^\n]+(?:\n(?![a-zA-Z\s_-]+:)[^\n]+)*)", block_text, re.IGNORECASE)
        if action_m:
            action = action_m.group(1).strip()
        else:
            # Fallback: take lines that don't match key tags
            lines = [l.strip() for l in block_text.split("\n") if l.strip() and not re.match(r"^[A-Za-z\s_-]+:", l.strip()) and cid not in l]
            if lines:
                action = lines[0]

        # Extract characters
        chars = []
        chars_m = re.search(r"(?:characters?[_\s-]?present|characters?)[:\s]+([^\n]+)", block_text, re.IGNORECASE)
        if chars_m:
            raw_chars = chars_m.group(1)
            raw_chars = re.sub(r"[\[\]\"']", "", raw_chars)
            chars = [c.strip() for c in re.split(r"[,;]", raw_chars) if c.strip() and c.strip().lower() != "none"]

        # Extract setting
        setting = ""
        setting_m = re.search(r"(?:setting|location|environment)[:\s]+([^\n]+)", block_text, re.IGNORECASE)
        if setting_m:
            setting = setting_m.group(1).strip().strip('"\'')

        # Extract camera framing
        camera = ""
        camera_m = re.search(r"(?:camera[_\s-]?framing|camera|framing|shot)[:\s]+([^\n]+)", block_text, re.IGNORECASE)
        if camera_m:
            camera = camera_m.group(1).strip().strip('"\'')
        else:
            camera = "cinematic framing, atmospheric lighting"

        if action:
            beats.append({
                "chunk_id": cid,
                "scene_type": stype,
                "characters_present": chars,
                "setting": setting,
                "action_beat": action,
                "camera_framing": camera
            })

    return beats


def _clean_bible_entry(text: str) -> str:
    """Strips leading/trailing markdown asterisks, underscores, hyphens, colons and excessive whitespace."""
    s = text.strip()
    s = re.sub(r"^[\s\*_\-#:]+", "", s)
    s = re.sub(r"[\s\*_\-#:]+$", "", s)
    s = re.sub(r"^(?:Description|Appearance|Visual Profile)[:\s*]+", "", s, flags=re.IGNORECASE)
    return s.strip()


def parse_bible_response(
    raw_text: str,
    known_characters: Optional[List[str]] = None,
    known_settings: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Parses visual bible response from JSON, tagged text, or markdown sections.
    Dynamically discovers all characters and settings without needing a pre-supplied list.
    Supports **CHARACTER: Name:**, bullet lists, markdown headings, and multi-line descriptions.
    """
    # 1. Attempt JSON parsing
    client = LMStudioClient()
    extracted_json = client._extract_json_block(raw_text)
    try:
        data = json.loads(extracted_json)
        if isinstance(data, dict):
            return {
                "global_art_style": _clean_bible_entry(data.get("global_art_style", "cinematic illustration, dramatic lighting")),
                "characters": {k: _clean_bible_entry(v) for k, v in data.get("characters", {}).items()},
                "settings": {k: _clean_bible_entry(v) for k, v in data.get("settings", {}).items()}
            }
    except Exception:
        pass

    # 2. Extract Global Art Style
    art_style = "cinematic illustration, dramatic atmospheric lighting, detailed textures"
    style_m = re.search(
        r"(?:\*\*|##)?\s*(?:GLOBAL[_\s-]?ART[_\s-]?STYLE|ART[_\s-]?STYLE|AESTHETIC)[:\*\s]+([\s\S]*?)(?=(?:\*\*|##)?\s*(?:CHARACTER|SETTING|Character|Setting|###|##|\Z))",
        raw_text,
        re.IGNORECASE
    )
    if style_m:
        extracted_style = _clean_bible_entry(style_m.group(1))
        if extracted_style:
            art_style = extracted_style

    characters: Dict[str, str] = {}
    settings: Dict[str, str] = {}

    # 3. Dynamic Tagged Parsing (CHARACTER: ... / SETTING: ...)
    char_matches = re.finditer(
        r"(?:\*\*|##)?\s*(?:CHARACTER|Character)[:\*\s]+([^\n:\*]+)(?:[:\*\s\-]+|\n)([\s\S]*?)(?=(?:\*\*|##)?\s*(?:CHARACTER|SETTING|Character|Setting|###|##|\Z))",
        raw_text,
        re.IGNORECASE
    )
    for m in char_matches:
        name = _clean_bible_entry(m.group(1))
        desc = _clean_bible_entry(m.group(2))
        if name and desc and name.lower() not in ["none", "characters", "character"]:
            characters[name] = desc

    setting_matches = re.finditer(
        r"(?:\*\*|##)?\s*(?:SETTING|Setting|LOCATION|Location)[:\*\s]+([^\n:\*]+)(?:[:\*\s\-]+|\n)([\s\S]*?)(?=(?:\*\*|##)?\s*(?:CHARACTER|SETTING|Character|Setting|###|##|\Z))",
        raw_text,
        re.IGNORECASE
    )
    for m in setting_matches:
        name = _clean_bible_entry(m.group(1))
        desc = _clean_bible_entry(m.group(2))
        if name and desc and name.lower() not in ["none", "settings", "setting", "locations"]:
            settings[name] = desc

    # 4. Fallback / Complementary Markdown List Parsing (# Characters / # Settings)
    current_section = None
    for line in raw_text.split("\n"):
        line_s = line.strip()
        if re.search(r"#+\s*(?:characters?|cast|figures)", line_s, re.IGNORECASE):
            current_section = "char"
            continue
        elif re.search(r"#+\s*(?:settings?|locations?|environments?)", line_s, re.IGNORECASE):
            current_section = "setting"
            continue
        elif re.search(r"#+\s*(?:style|art style|aesthetic)", line_s, re.IGNORECASE):
            current_section = "style"
            continue

        bullet_m = re.match(r"^[-*]\s*\*\*([^*]+)\*\*[:\s\-]+(.*)", line_s)
        if bullet_m:
            bname = _clean_bible_entry(bullet_m.group(1))
            bdesc = _clean_bible_entry(bullet_m.group(2))
            if current_section == "char" and bname and bname not in characters:
                characters[bname] = bdesc
            elif current_section == "setting" and bname and bname not in settings:
                settings[bname] = bdesc

    # 5. Check known lists if provided as hints
    if known_characters:
        for c in known_characters:
            if c not in characters:
                m = re.search(rf"\b{re.escape(c)}\b[:\s\-]+([^\n]+)", raw_text, re.IGNORECASE)
                if m:
                    characters[c] = _clean_bible_entry(m.group(1))

    if known_settings:
        for s in known_settings:
            if s not in settings:
                m = re.search(rf"\b{re.escape(s)}\b[:\s\-]+([^\n]+)", raw_text, re.IGNORECASE)
                if m:
                    settings[s] = _clean_bible_entry(m.group(1))

    return {
        "global_art_style": art_style,
        "characters": characters,
        "settings": settings
    }


def _clean_prompt_entry(text: str) -> str:
    """Strips markdown asterisks, backticks, quotes, colons, and excessive whitespace."""
    s = text.strip()
    # Remove markdown bold/italic asterisks or backticks that LLMs wrap around clauses
    s = s.replace("**", "").replace("`", "").replace("##", "")
    s = re.sub(r"^[\s\*_\-#:`\"']+", "", s)
    s = re.sub(r"[\s\*_\-#:`\"']+$", "", s)
    return s.strip()


def parse_prompt_response(raw_text: str, default_negative: str = "") -> Tuple[str, str]:
    """
    Parses diffusion prompts from JSON, tagged text (PROMPT: ... NEGATIVE: ...),
    or direct natural text output. Handles reasoning model thinking preambles and bold markdown tags.
    """
    if not raw_text or not raw_text.strip():
        return "", default_negative

    # 1. Attempt JSON parsing
    client = LMStudioClient()
    extracted_json = client._extract_json_block(raw_text)
    try:
        data = json.loads(extracted_json)
        if isinstance(data, dict):
            pos = data.get("prompt") or data.get("positive_prompt") or data.get("positive") or ""
            neg = data.get("negative_prompt") or data.get("negative") or default_negative
            pos_cleaned = _clean_prompt_entry(str(pos))
            neg_cleaned = _clean_prompt_entry(str(neg))
            if pos_cleaned:
                return pos_cleaned, neg_cleaned or default_negative
    except Exception:
        pass

    # 2. Line-anchored tagged text: (PROMPT: ... NEGATIVE: ...)
    # Anchoring to beginning of line prevents false matches against conversational thought text
    pos_m = re.search(
        r"(?:^|\n)\s*(?:\*\*|##)?\s*(?:PROMPT|POSITIVE\s*PROMPT|POSITIVE)[:\*\s]+([\s\S]*?)(?=(?:^|\n)\s*(?:\*\*|##)?\s*(?:NEGATIVE|NEGATIVE\s*PROMPT)[:\*\s]+|$)",
        raw_text,
        re.IGNORECASE
    )
    neg_m = re.search(
        r"(?:^|\n)\s*(?:\*\*|##)?\s*(?:NEGATIVE|NEGATIVE\s*PROMPT)[:\*\s]+([\s\S]*)$",
        raw_text,
        re.IGNORECASE
    )

    if pos_m and pos_m.group(1).strip():
        pos = _clean_prompt_entry(pos_m.group(1))
        neg = _clean_prompt_entry(neg_m.group(1)) if (neg_m and neg_m.group(1).strip()) else default_negative
        if pos:
            return pos, neg or default_negative

    # 3. Fallback: unanchored tagged search
    pos_m2 = re.search(
        r"\b(?:PROMPT|POSITIVE\s*PROMPT)[:\*\s]+([\s\S]*?)(?=\b(?:NEGATIVE|NEGATIVE\s*PROMPT)[:\*\s]+|$)",
        raw_text,
        re.IGNORECASE
    )
    neg_m2 = re.search(
        r"\b(?:NEGATIVE|NEGATIVE\s*PROMPT)[:\*\s]+([\s\S]*)$",
        raw_text,
        re.IGNORECASE
    )
    if pos_m2 and pos_m2.group(1).strip():
        pos = _clean_prompt_entry(pos_m2.group(1))
        neg = _clean_prompt_entry(neg_m2.group(1)) if (neg_m2 and neg_m2.group(1).strip()) else default_negative
        if pos:
            return pos, neg or default_negative

    # 4. Pure text prompt: clean introductory conversational boilerplate
    cleaned = _clean_prompt_entry(raw_text)
    cleaned = re.sub(r"^(?:Here is the (?:diffusion )?prompt:?|Prompt:?)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = _clean_prompt_entry(cleaned)

    return cleaned, default_negative


def load_llm_config(config_path: str) -> Dict[str, Any]:
    """Loads config/llm_models.json."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)
