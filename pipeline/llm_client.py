"""
pipeline/llm_client.py: LM Studio OpenAI-compatible client wrapper.
Supports free-form text completions, structured parsing without strict JSON enforcement,
dynamic model listing, health checks, and fallback extraction.
"""

import os
import re
import json
import time
import requests
from typing import Dict, Any, List, Optional, Tuple, Set, Union


class ContextWindowExceededError(RuntimeError):
    """Raised when an LLM prompt exceeds the loaded model's context window (n_ctx)."""
    def __init__(self, message: str, n_prompt_tokens: Optional[int] = None, n_ctx: Optional[int] = None):
        super().__init__(message)
        self.n_prompt_tokens = n_prompt_tokens
        self.n_ctx = n_ctx


def estimate_tokens(text: str) -> int:
    """
    Conservative token count estimator for text prompts across diverse tokenizer families.
    Avoids external C-dependencies while ensuring token budgets aren't exceeded.
    """
    if not text:
        return 0
    char_est = len(text) / 3.2
    word_est = len(text.split()) * 1.35
    return int(max(char_est, word_est)) + 10


class LMStudioClient:
    def __init__(
        self,
        api_base: str = "http://localhost:1234/v1",
        api_key: Optional[str] = None,
        backend: str = "lm_studio",
        context_window: Optional[int] = None,
        timeout: int = 300
    ):
        self.api_base = api_base.rstrip("/")
        # API key resolution: argument > LLM_API_KEY > OPENAI_API_KEY
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        self.backend = backend or ("openai_compatible" if self.api_key or "openai.com" in self.api_base or "openrouter" in self.api_base or "groq.com" in self.api_base else "lm_studio")
        self.timeout = timeout
        self._explicit_context_window = context_window
        self._cached_context_size: Optional[int] = context_window

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_health(self) -> Dict[str, Any]:
        """Checks if LLM server/endpoint is reachable."""
        url = f"{self.api_base}/models"
        headers = self._get_headers()
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id") for m in data.get("data", []) if "id" in m]
                label = "LM Studio" if self.backend == "lm_studio" else "LLM Provider"
                return {
                    "online": True,
                    "url": self.api_base,
                    "backend": self.backend,
                    "models": models,
                    "message": f"{label} is online with {len(models)} model(s) available."
                }
            # For cloud endpoints that don't allow listing models or return 401/403
            return {
                "online": False,
                "url": self.api_base,
                "backend": self.backend,
                "models": [],
                "message": f"Endpoint returned status code {resp.status_code}."
            }
        except Exception as e:
            return {
                "online": False,
                "url": self.api_base,
                "backend": self.backend,
                "models": [],
                "message": f"Connection error at {self.api_base}: {str(e)}"
            }

    def list_available_models(self) -> List[str]:
        """Returns list of model IDs reported by the provider endpoint."""
        health = self.check_health()
        return health.get("models", [])

    def _resolve_model(self, model: str) -> str:
        """Finds matching model or falls back to first loaded model for LM Studio."""
        if not model:
            model = "gpt-4o"
        # If cloud or non-lm_studio, preserve explicit user-chosen model
        if self.backend != "lm_studio":
            return model

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
        """Public resolver returning matching model or fallback from LLM provider."""
        return self._resolve_model(model)

    def get_model_context_size(self, model: Optional[str] = None) -> int:
        """
        Queries LM Studio for the loaded context length of the active model,
        or returns explicitly configured context_window, or default 128k for cloud models.
        """
        if self._cached_context_size:
            return self._cached_context_size

        if self.backend != "lm_studio":
            return self._explicit_context_window or 128000

        host_base = re.sub(r"/v\d+/?$", "", self.api_base)
        url = f"{host_base}/api/v0/models"
        resolved = self._resolve_model(model) if model else None

        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models_data = data.get("data", [])
                loaded_models = [m for m in models_data if m.get("state") == "loaded"]
                target_model = None

                if resolved:
                    matching = [m for m in models_data if m.get("id") == resolved or resolved.lower() in m.get("id", "").lower()]
                    if matching:
                        target_model = next((m for m in matching if m.get("state") == "loaded"), matching[0])

                if not target_model and loaded_models:
                    target_model = loaded_models[0]

                if target_model:
                    ctx = target_model.get("loaded_context_length") or target_model.get("max_context_length")
                    if ctx and isinstance(ctx, int) and ctx > 0:
                        self._cached_context_size = ctx
                        return ctx
        except Exception:
            pass

        return 8192

    def _handle_http_error(self, resp: requests.Response):
        """Processes non-200 responses, parsing context errors without wasteful retries."""
        text = resp.text or ""
        if resp.status_code == 400 and ("exceed_context_size_error" in text or "exceeds the available context size" in text):
            n_tokens = None
            n_ctx = None
            try:
                err_data = resp.json()
                if isinstance(err_data, dict):
                    if "n_prompt_tokens" in err_data:
                        n_tokens = err_data.get("n_prompt_tokens")
                        n_ctx = err_data.get("n_ctx")
                    elif "error" in err_data:
                        err_val = err_data["error"]
                        if isinstance(err_val, dict):
                            n_tokens = err_val.get("n_prompt_tokens")
                            n_ctx = err_val.get("n_ctx")
                        elif isinstance(err_val, str):
                            m = re.search(r"request \((\d+) tokens\) exceeds the available context size \((\d+) tokens\)", err_val)
                            if m:
                                n_tokens = int(m.group(1))
                                n_ctx = int(m.group(2))
            except Exception:
                pass
            if n_ctx:
                self._cached_context_size = n_ctx
            msg = f"Prompt of ~{n_tokens or 'many'} tokens exceeded LM Studio's loaded context window ({n_ctx or 'limit'} tokens)."
            raise ContextWindowExceededError(msg, n_prompt_tokens=n_tokens, n_ctx=n_ctx)

        raise RuntimeError(f"HTTP {resp.status_code}: {text}")

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
        elif self.backend == "lm_studio":
            payload["max_tokens"] = -1

        last_error = None
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=self._get_headers(), timeout=self.timeout)
                if resp.status_code != 200:
                    self._handle_http_error(resp)

                data = resp.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or ""
                # If content is empty because reasoning model generated in reasoning_content or got cut off
                if not content.strip() and msg.get("reasoning_content"):
                    content = msg.get("reasoning_content", "")
                return content.strip()

            except ContextWindowExceededError:
                raise
            except Exception as e:
                last_error = e
                if attempt < retries:
                    time.sleep(backoff ** attempt)

        raise RuntimeError(f"Failed to communicate with LLM provider ({self.backend}) after {retries} attempts: {last_error}")

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
        Calls LLM chat completions and robustly parses JSON.
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
                elif self.backend == "lm_studio":
                    payload["max_tokens"] = -1
                resp = requests.post(url, json=payload, headers=self._get_headers(), timeout=self.timeout)
                if resp.status_code != 200:
                    self._handle_http_error(resp)

                data = resp.json()
                raw_text = data["choices"][0]["message"]["content"]
                break
            except ContextWindowExceededError:
                raise
            except Exception as e:
                if attempt == retries:
                    raise RuntimeError(f"LLM chat error ({self.backend}): {e}")
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
        first_bracket = text.find("[")
        last_bracket = text.rfind("]")
        first_brace = text.find("{")
        last_brace = text.rfind("}")

        # If it looks like a JSON array
        if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            if first_brace == -1 or first_bracket < first_brace:
                return text[first_bracket:last_bracket + 1].strip()

        # If it looks like a JSON object
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
                        "character_attire": b.get("character_attire", {}),
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

        # Extract character attire if present
        char_attire = {}
        attire_m = re.search(r"(?:characters?[_\s-]?attire|attire|clothing|wardrobe)[:\s]+([^\n]+)", block_text, re.IGNORECASE)
        if attire_m:
            attire_raw = attire_m.group(1).strip()
            if attire_raw.lower() not in ["none", "default", "standard"]:
                for part in re.split(r"[;]", attire_raw):
                    part = part.strip()
                    if ":" in part:
                        c_name, c_att = part.split(":", 1)
                        char_attire[c_name.strip()] = c_att.strip()
                    elif " in " in part:
                        c_name, c_att = part.split(" in ", 1)
                        char_attire[c_name.strip()] = c_att.strip()
                    elif part and chars:
                        char_attire[chars[0]] = part

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
                "character_attire": char_attire,
                "setting": setting,
                "action_beat": action,
                "camera_framing": camera
            })

    return beats


class CharacterProfile(dict):
    """
    Structured character profile tracking invariant physical traits and timeline wardrobe/modifications.
    Inherits from dict for seamless JSON serialization and dictionary access, with enhanced __contains__
    and string formatting for backward compatibility with string-based assertions and legacy consumers.
    """
    def __init__(self, data: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__()
        initial = dict(data or {})
        initial.update(kwargs)
        self["base_dna"] = str(initial.get("base_dna") or initial.get("physical_dna") or initial.get("description") or "").strip()
        self["timeline_modifications"] = list(initial.get("timeline_modifications") or [])
        self["wardrobe_timeline"] = list(initial.get("wardrobe_timeline") or [])
        self["default_attire"] = str(initial.get("default_attire") or "").strip()
        self["alternate_attires"] = dict(initial.get("alternate_attires") or {})

        # Ensure timeline entry if default attire exists and timeline is empty
        if self["default_attire"] and not self["wardrobe_timeline"]:
            self["wardrobe_timeline"].append({
                "from_chunk_id": "chunk_000",
                "context": "Standard",
                "attire": self["default_attire"]
            })
        elif not self["default_attire"] and self["wardrobe_timeline"]:
            self["default_attire"] = self["wardrobe_timeline"][0].get("attire", "")

    def __contains__(self, item: Any) -> bool:
        if super().__contains__(item):
            return True
        if isinstance(item, str):
            text_corpus = f"{self.get('base_dna', '')} {self.get('default_attire', '')} {self.get('timeline_modifications', '')} {self.get('alternate_attires', '')}"
            return item.lower() in text_corpus.lower()
        return False

    def __str__(self) -> str:
        parts = []
        if self.get("base_dna"):
            parts.append(self["base_dna"])
        if self.get("default_attire"):
            parts.append(f"Attire: {self['default_attire']}")
        return "; ".join(parts) if parts else ""


def _clean_bible_entry(text: Any) -> str:
    """Strips leading/trailing markdown asterisks, underscores, hyphens, colons and excessive whitespace."""
    if not isinstance(text, str):
        return str(text or "")
    s = text.strip()
    s = re.sub(r"^[\s\*_\-#:]+", "", s)
    s = re.sub(r"[\s\*_\-#:]+$", "", s)
    s = re.sub(r"^(?:Description|Appearance|Visual Profile)[:\s*]+", "", s, flags=re.IGNORECASE)
    return s.strip()


def normalize_character_entry(char_val: Any, current_chunk_id: str = "chunk_000") -> CharacterProfile:
    """Standardizes a character entry into the unified timeline schema."""
    if isinstance(char_val, CharacterProfile):
        return char_val
    if isinstance(char_val, dict):
        return CharacterProfile(char_val)

    text = _clean_bible_entry(str(char_val or ""))
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    base_dna_parts = []
    default_attire = ""
    timeline_mods = []
    wardrobe_tl = []
    alt_attires = {}

    has_subtags = False
    for line in lines:
        # Check modifications (scars, injuries, prosthetics) first
        m_mod = re.match(r"^[-*]?\s*(?:Physical\s*Change|Scar|Injury|Modification)(?:\s*\[?(chunk_\d+)\]?)?\s*[:=\-]\s*(.*)$", line, re.IGNORECASE)
        if m_mod:
            has_subtags = True
            cid = m_mod.group(1) or current_chunk_id
            trait_text = m_mod.group(2).strip()
            if trait_text:
                timeline_mods.append({"introduced_chunk_id": cid, "trait": trait_text})
            continue

        # Check costume changes second
        m_cost = re.match(r"^[-*]?\s*(?:Costume\s*Change|Alternate\s*Attire|New\s*Attire)(?:\s*\[?(chunk_\d+)\]?)?(?:\s*\(([^)]+)\))?\s*[:=\-]\s*(.*)$", line, re.IGNORECASE)
        if m_cost:
            has_subtags = True
            cid = m_cost.group(1) or current_chunk_id
            ctx = m_cost.group(2) or "Scene"
            outfit = m_cost.group(3).strip()
            if outfit:
                wardrobe_tl.append({"from_chunk_id": cid, "context": ctx, "attire": outfit})
                alt_attires[ctx] = outfit
            continue

        # Check base physical DNA
        m_phys = re.match(r"^[-*]?\s*(?:Physical(?:\s*DNA)?|Appearance|Traits?)\s*[:=\-]\s*(.*)$", line, re.IGNORECASE)
        if m_phys:
            has_subtags = True
            base_dna_parts.append(m_phys.group(1).strip())
            continue

        # Check default attire
        m_att = re.match(r"^[-*]?\s*(?:Default\s*Attire|Attire|Clothing|Wardrobe|Outfit)\s*[:=\-]\s*(.*)$", line, re.IGNORECASE)
        if m_att:
            has_subtags = True
            default_attire = m_att.group(1).strip()
            continue

        if not has_subtags:
            base_dna_parts.append(line)

    if has_subtags:
        base_dna = " ".join(base_dna_parts).strip()
    else:
        # Heuristic split on wearing / dressed in
        m_wear = re.search(r"\b(?:wearing|dressed in|attired in|clad in)\s+([^;]+)", text, re.IGNORECASE)
        if m_wear:
            default_attire = m_wear.group(0).strip()
        base_dna = text

    if default_attire and not wardrobe_tl:
        wardrobe_tl.append({"from_chunk_id": current_chunk_id, "context": "Standard", "attire": default_attire})

    return CharacterProfile({
        "base_dna": base_dna,
        "timeline_modifications": timeline_mods,
        "wardrobe_timeline": wardrobe_tl,
        "default_attire": default_attire,
        "alternate_attires": alt_attires
    })


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
            raw_chars = data.get("characters", {})
            chars = {}
            if isinstance(raw_chars, dict):
                for k, v in raw_chars.items():
                    chars[k] = normalize_character_entry(v)
            raw_settings = data.get("settings", {})
            settings = {}
            if isinstance(raw_settings, dict):
                for k, v in raw_settings.items():
                    settings[k] = _clean_bible_entry(str(v))
            return {
                "global_art_style": _clean_bible_entry(str(data.get("global_art_style", "cinematic illustration, dramatic lighting"))),
                "characters": chars,
                "settings": settings
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

    characters: Dict[str, CharacterProfile] = {}
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
            characters[name] = normalize_character_entry(desc)

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
                characters[bname] = normalize_character_entry(bdesc)
            elif current_section == "setting" and bname and bname not in settings:
                settings[bname] = bdesc

    # 5. Check known lists if provided as hints
    if known_characters:
        for c in known_characters:
            if c not in characters:
                m = re.search(rf"\b{re.escape(c)}\b[:\s\-]+([^\n]+)", raw_text, re.IGNORECASE)
                if m:
                    characters[c] = normalize_character_entry(m.group(1))

    if known_settings:
        for s in known_settings:
            if s not in settings:
                m = re.search(rf"\b{re.escape(s)}\b[:\s\-]+([^\n]+)", raw_text, re.IGNORECASE)
                if m:
                    settings[s] = _clean_bible_entry(m.group(1))

    return {
        "global_art_style": art_style,
        "characters": {k: normalize_character_entry(v) for k, v in characters.items()},
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
    """Loads config/llm_models.json and populates defaults/environment keys."""
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not data.get("api_key"):
        data["api_key"] = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if not data.get("backend"):
        data["backend"] = "lm_studio"
    return data


# Generalized alias for backend-agnostic usage
LLMClient = LMStudioClient


def _slugify_style_local(name: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9]+', '_', name.strip().lower()).strip('_')
    return cleaned or "style"


def parse_styles_response(raw_text: str, category: str = "art", requested_count: int = 3) -> List[Dict[str, str]]:
    """
    Robustly parses LLM response into a list of style dictionaries containing id, name, description, category.
    Handles JSON arrays, JSON wrapped in objects, and markdown bulleted lists.
    """
    cat_key = "photography" if category.lower() in ("photography", "photo") else "art"
    styles: List[Dict[str, str]] = []

    # 1. Attempt JSON block extraction
    client = LMStudioClient()
    extracted_json = client._extract_json_block(raw_text)
    if extracted_json:
        try:
            parsed = json.loads(extracted_json)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(client._clean_json_syntax(extracted_json))
            except Exception:
                parsed = None
        except Exception:
            parsed = None

        if parsed is not None:
            raw_list = []
            if isinstance(parsed, list):
                raw_list = parsed
            elif isinstance(parsed, dict):
                for k in ("styles", "presets", "mediums", "results", "items", cat_key):
                    if k in parsed and isinstance(parsed[k], list):
                        raw_list = parsed[k]
                        break

            for item in raw_list:
                if isinstance(item, dict):
                    name = _clean_prompt_entry(str(item.get("name", "")))
                    desc = _clean_prompt_entry(str(item.get("description", "")))
                    sid = _clean_prompt_entry(str(item.get("id", ""))) or _slugify_style_local(name)
                    if name and desc:
                        styles.append({
                            "id": sid,
                            "name": name,
                            "description": desc,
                            "category": cat_key
                        })

    # 2. If JSON failed or yielded nothing, parse bulleted/tagged markdown
    if not styles:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        cur_name = ""
        cur_desc = ""

        for line in lines:
            # Match "Name: Foo" or "**Name**: Foo" or "1. **Foo**"
            name_m = re.match(r"^(?:\d+\.|\*|-)?\s*(?:\*\*)?(?:Name|Style|Medium|Photographic Style)?(?:\*\*)?[:\s\-]+(?:\*\*)?([^*\n]+?)(?:\*\*)?$", line, re.IGNORECASE)
            desc_m = re.match(r"^(?:\d+\.|\*|-)?\s*(?:\*\*)?(?:Description|Prompt|Keywords)?(?:\*\*)?[:\s\-]+(.*)$", line, re.IGNORECASE)

            # Check for inline format: "1. **Style Name**: Description here..."
            inline_m = re.match(r"^(?:\d+\.|\*|-)?\s*\*\*([^*]+)\*\*[:\s\-]+(.*)$", line)

            if inline_m:
                cand_name = _clean_prompt_entry(inline_m.group(1))
                cand_desc = _clean_prompt_entry(inline_m.group(2))
                if cand_name.lower() not in ("name", "description", "note", "style"):
                    styles.append({
                        "id": _slugify_style_local(cand_name),
                        "name": cand_name,
                        "description": cand_desc,
                        "category": cat_key
                    })
                    continue

            if name_m and not inline_m:
                cand_name = _clean_prompt_entry(name_m.group(1))
                if cand_name.lower() not in ("name", "description", "note"):
                    if cur_name and cur_desc:
                        styles.append({
                            "id": _slugify_style_local(cur_name),
                            "name": cur_name,
                            "description": cur_desc,
                            "category": cat_key
                        })
                    cur_name = cand_name
                    cur_desc = ""
            elif desc_m and cur_name:
                cur_desc = _clean_prompt_entry(desc_m.group(1))

        if cur_name and cur_desc:
            styles.append({
                "id": _slugify_style_local(cur_name),
                "name": cur_name,
                "description": cur_desc,
                "category": cat_key
            })

    # Return parsed items capped at requested count if we got enough
    if len(styles) >= requested_count:
        return styles[:requested_count]

    # Fallback curated starter styles if LLM returned incomplete list or failed
    curated_fallbacks = {
        "art": [
            {"id": "charcoal_noir", "name": "Charcoal & Carbon Noir", "description": "expressive charcoal drawing, velvety carbon black shadows, dramatic chiaroscuro contrast, textured cold-press paper tooth, powdery smudge gradients", "category": "art"},
            {"id": "impasto_oil", "name": "Impasto Oil & Palette Knife", "description": "heavy textured oil painting, visible palette knife strokes, thick raised impasto ridges, rich layered pigments, tactile linen canvas weave", "category": "art"},
            {"id": "storybook_watercolor", "name": "Storybook Watercolor & Ink", "description": "storybook illustration, delicate translucent watercolor washes, wet-on-wet pigment blooming, precise fountain pen and ink linework, warm archival paper grain", "category": "art"},
            {"id": "etching_engraving", "name": "Copperplate Etching & Crosshatch", "description": "fine antique copperplate etching, intaglio engraving, dense rhythmic crosshatching, crisp dark line art on cream paper, atmospheric cross-hatch shading", "category": "art"},
            {"id": "matte_gouache", "name": "Matte Gouache & Graphic Cel", "description": "matte opaque gouache painting, bold graphic shapes, flat velvety pigment blocks, subtle paper texture, stylized editorial illustration", "category": "art"},
            {"id": "colored_pencil_pastel", "name": "Colored Pencil & Soft Pastel", "description": "layered colored pencil shading, soft dry pastel blending, visible tooth and paper grain, warm luminous highlights, velvety blended shadows", "category": "art"},
            {"id": "linocut_blockprint", "name": "Linocut Relief Print", "description": "hand-carved linocut print, bold carved relief lines, stark black and white contrast, subtle ink press grain, organic printmaker textures", "category": "art"}
        ],
        "photography": [
            {"id": "kodachrome_1970s", "name": "1970s 35mm Kodachrome", "description": "vintage 1970s color photography, 35mm analog film capture, authentic Kodachrome color science, warm saturated reds and yellows, fine film grain, natural optical lens flare", "category": "photography"},
            {"id": "wet_plate_collodion", "name": "1890s Wet Plate Collodion Tintype", "description": "19th century tintype photograph, wet plate collodion process, silver gelatin emulsion swirls, sepia and graphite tones, chemical plate imperfections, heavy edge vignetting", "category": "photography"},
            {"id": "medium_format_editorial", "name": "Modern Medium Format Editorial", "description": "tack-sharp medium format studio photograph, Hasselblad optical clarity, cinematic studio softbox lighting, ultra-clean shadow detail, shallow depth of field", "category": "photography"},
            {"id": "noir_tri_x_1950s", "name": "1950s Noir 35mm Tri-X", "description": "1950s documentary black-and-white film, Kodak Tri-X 400 grain, high-contrast monochrome, dramatic street lamp shadows, moody atmospheric silver-halide grain", "category": "photography"}
        ]
    }

    existing_ids = {s["id"] for s in styles}
    for fb in curated_fallbacks.get(cat_key, []):
        if len(styles) >= requested_count:
            break
        if fb["id"] not in existing_ids:
            styles.append(dict(fb))
            existing_ids.add(fb["id"])

    return styles[:requested_count]


def infer_styles(
    llm_client: LMStudioClient,
    model: str,
    theme_text: str,
    category: str = "art",
    count: int = 3,
    existing_styles: Optional[List[str]] = None,
    temperature: float = 0.5
) -> List[Dict[str, str]]:
    """
    Infers thematic style presets (Art Mediums or Photography Eras) based on the story's visual tone.
    Uses category-specific fine art or photographic domain instructions.
    """
    cat_key = "photography" if category.lower() in ("photography", "photo") else "art"

    avoid_clause = ""
    if existing_styles and len(existing_styles) > 0:
        names_str = ", ".join([f"'{s}'" for s in existing_styles if s])
        if names_str:
            avoid_clause = f"\nIMPORTANT: The user already has the following styles: {names_str}. Propose DIFFERENT, distinctly unique options that do not duplicate these.\n"

    if cat_key == "art":
        system_prompt = (
            "You are an expert art director and fine art print historian. "
            "Your task is to recommend physical, tangible artistic mediums and illustration styles "
            "(e.g. charcoal, oil, watercolor, gouache, intaglio etching, pastel, fresco, woodblock) "
            "that would elevate and suit the story's visual atmosphere. "
            "Avoid generic buzzwords like 'digital art' or 'hyperrealistic'; focus on genuine artist tools, "
            "pigments, binders, mark-making techniques, and paper/canvas textures."
        )
        user_prompt = f"""STORY VISUAL THEME & TONE:
{theme_text or 'Dramatic narrative story with rich atmosphere'}

{avoid_clause}
TASK:
Propose exactly {count} distinctly different ARTISTIC ILLUSTRATION MEDIUMS tailored to this story.
For each medium, provide:
1. "name": An evocative, concise medium name (e.g. "Charcoal & Carbon Noir", "Impasto Oil & Palette Knife", "Storybook Watercolor & Ink").
2. "description": A rich diffusion prompt descriptor (20-40 words) specifying the physical pigments, mark-making tools, surface tooth, and lighting interplay.

Format your output strictly as a JSON array of objects:
[
  {{
    "name": "Medium Name",
    "description": "expressive physical medium keywords..."
  }}
]
"""
    else:
        system_prompt = (
            "You are an expert cinematic still photographer, camera technician, and film historian. "
            "Your task is to recommend photographic eras, vintage film stocks, period camera systems, "
            "and optical photographic aesthetics (e.g. 1970s Kodachrome, 1890s tintype, 1950s Tri-X noir, "
            "medium format studio editorial, Polaroid transfer) that capture the story's dramatic mood. "
            "Focus on authentic film chemistry, optical lens properties, grain structure, and lighting physics."
        )
        user_prompt = f"""STORY VISUAL THEME & TONE:
{theme_text or 'Dramatic narrative story with rich atmosphere'}

{avoid_clause}
TASK:
Propose exactly {count} distinctly different PHOTOGRAPHIC ERAS OR CAMERA/FILM AESTHETICS tailored to this story.
For each style, provide:
1. "name": An evocative, concise photographic style name (e.g. "1970s 35mm Kodachrome", "1890s Wet Plate Collodion Tintype", "1950s Noir Silver Gelatin").
2. "description": A rich diffusion prompt descriptor (20-40 words) specifying camera optics, film stock/chemistry, grain, color palette, and lighting physics.

Format your output strictly as a JSON array of objects:
[
  {{
    "name": "Photographic Style Name",
    "description": "optical film keywords..."
  }}
]
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try:
        raw_output = llm_client.chat_text(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=1024
        )
        parsed = parse_styles_response(raw_output, category=cat_key, requested_count=count)
        return parsed
    except Exception as e:
        # Graceful fallback: return curated starter presets if endpoint is offline or times out
        return parse_styles_response("", category=cat_key, requested_count=count)
