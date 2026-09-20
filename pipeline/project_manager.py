"""
pipeline/project_manager.py: Project initialization, config loading, and artifact persistence.
Provides standard directories and default configs for projects/{story_slug}.
"""

import os
import shutil
import json
from typing import Dict, Any, List, Optional


DEFAULT_LLM_CONFIG = {
    "backend": "lm_studio",  # "lm_studio" | "openai_compatible"
    "api_base": "http://localhost:1234/v1",
    "api_key": "",
    "context_window": 8192,
    "roles": {
        "structured_analyst": {
            "model": "thedrummer_orion-26b-a4b-v1",
            "temperature": 0.2,
            "max_tokens": -1,
            "system_prompt": "You are an expert cinematic visual continuity supervisor. Analyze the story text to compile a comprehensive Visual Bible compendium. Infer a cohesive global art style, and extract exhaustive physical visual descriptions for every character (build, face, hair, distinctive features/prosthetic limbs, clothing) and setting (architecture, textures, lighting). Format cleanly using GLOBAL ART STYLE:, CHARACTER: <Name>, and SETTING: <Name> tags."
        },
        "narrative_director": {
            "model": "thedrummer_orion-26b-a4b-v1",
            "temperature": 0.3,
            "max_tokens": -1,
            "system_prompt": "You are an expert narrative director identifying key visual illustration moments from story paragraphs. Select 0 to N beats based purely on dramatic visual impact. Only select beats occurring in the TARGET chunks. Reference established characters and settings from the Visual Bible."
        },
        "prompt_synthesizer": {
            "model": "thedrummer_orion-26b-a4b-v1",
            "temperature": 0.35,
            "max_tokens": -1,
            "system_prompt": "You are an expert diffusion prompt synthesizer. You synthesize rich, cohesive image prompts by seamlessly blending the character's explicit physical appearance and distinctive features from the Visual Bible, the setting's textures and architecture from the Visual Bible, the scene action beat, camera framing, and the global art style."
        }
    }
}

DEFAULT_DIFFUSION_PROFILES = {
    "backend": "comfyui",  # "comfyui" | "openai_compatible"
    "comfyui": {
        "host": "127.0.0.1:8188",
        "workflow": "sdxl_base.json"
    },
    "openai_compatible": {
        "api_base": "https://api.openai.com/v1",
        "api_key": "",
        "model": "dall-e-3",
        "quality": "standard",
        "style": "vivid"
    },
    "active_profile": "sdxl_base",
    "profiles": {
        "flux_natural": {
            "aspect_ratios": {
                "landscape": {"width": 1344, "height": 768},
                "portrait": {"width": 768, "height": 1344},
                "square": {"width": 1024, "height": 1024}
            },
            "system_prompt": "You are an expert diffusion prompt synthesizer. Convert the provided scene beat, character appearance, setting, and style into a detailed natural-language description (2-3 complete sentences). Avoid booru tags and keyword lists.",
            "positive_prefix": "",
            "default_negative": ""
        },
        "sdxl_base": {
            "aspect_ratios": {
                "landscape": {"width": 1344, "height": 768},
                "portrait": {"width": 832, "height": 1216},
                "square": {"width": 1024, "height": 1024}
            },
            "system_prompt": "You are an expert SDXL prompt synthesizer. Combine the scene elements into a keyword-focused, comma-separated prompt. Place primary subjects first, followed by camera framing, lighting, environment, and art style.",
            "positive_prefix": "",
            "default_negative": "blurry, low quality, deformed, extra limbs, bad anatomy, text, watermark, logo"
        },
        "anime_danbooru": {
            "aspect_ratios": {
                "landscape": {"width": 1216, "height": 832},
                "portrait": {"width": 832, "height": 1216},
                "square": {"width": 1024, "height": 1024}
            },
            "system_prompt": "You are a prompt generator for anime diffusion models. Convert the scene components into Danbooru-style comma-separated tags. Always start with character counts (e.g., 1boy, 1girl), character visual tags, clothing, action pose, background tags, and style tags.",
            "positive_prefix": "",
            "default_negative": "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality"
        },
        "krea2": {
            "aspect_ratios": {
                "landscape": {"width": 1344, "height": 768},
                "portrait": {"width": 768, "height": 1344},
                "square": {"width": 1024, "height": 1024}
            },
            "system_prompt": (
                "You are an expert diffusion prompt synthesizer. Synthesize an evocative, sensory-rich natural language prompt strictly adhering to the following blueprint:\n\n"
                "STRUCTURE & COMPOSITION:\n"
                "1. Subject & Scene Action: Open with the primary characters, their distinctive physical traits from the Visual Bible, and the immediate scene action beat.\n"
                "2. Tangible Materials & Textures: Emphasize tactile physical surfaces (e.g. brushed brass, weathered leather, damp cobblestones, coarse knit wool).\n"
                "3. Lighting Physics & Ambience: Detail the lighting behavior and atmosphere (e.g. warm golden-hour rim lighting, volumetric light shafts, soft diffused shadows).\n"
                "4. Camera Optics & Medium: Conclude with optical camera cues (e.g. 35mm film grain, wide cinematic framing, shallow depth of field) and the art medium.\n\n"
                "CRITICAL CONSTRAINTS:\n"
                "- Format: 2 to 4 flowing, descriptive natural sentences (50–90 words). Do NOT use comma-separated keyword lists or booru tags.\n"
                "- In-Scene Text: If any signs, banners, or titles appear in the scene, enclose the exact wording inside double quotation marks (e.g. a banner reading \"VICTORY\").\n"
                "- Negative Handling: This model does not utilize negative prompts. Output the positive prompt under PROMPT: and leave the NEGATIVE: line completely empty.\n"
                "- Prohibited: Never use filler buzzwords like 'photorealistic', 'masterpiece', or 'trending on artstation'."
            ),
            "positive_prefix": "",
            "default_negative": ""
        },
        "zit": {
            "aspect_ratios": {
                "landscape": {"width": 1344, "height": 768},
                "portrait": {"width": 768, "height": 1344},
                "square": {"width": 1024, "height": 1024}
            },
            "system_prompt": (
                "You are an expert diffusion prompt synthesizer. Synthesize a dense, natural-language prompt paragraph strictly adhering to the following blueprint:\n\n"
                "STRUCTURE & HIERARCHY (BIG-TO-SMALL):\n"
                "1. Setting & Atmosphere: Establish the architectural space, atmospheric depth, time of day, and lighting dynamics first (e.g. volumetric light rays, soft bounce light, high-contrast shadows).\n"
                "2. Subject & Action: Position the characters into the space with their distinctive physical traits from the Visual Bible, facial expression, and active scene beat.\n"
                "3. Attire & Textures: Specify clothing fabrics, gear, and tactile materials in realistic detail (e.g. weathered leather, polished steel, coarse wool).\n"
                "4. Cinematography & Optical Finish: Define camera angle, focal perspective (e.g. 35mm lens, eye-level framing, shallow depth of field), and overall art style.\n\n"
                "CRITICAL CONSTRAINTS:\n"
                "- Format: A single cohesive, descriptive natural-language paragraph (60–100 words). Do NOT use comma-separated keyword lists or booru tags.\n"
                "- Negative Handling: This model runs without classifier-free guidance and CANNOT process negative prompts. Use positive constraints for quality (e.g. 'tack-sharp focus, crisp details') and append any required exclusions to the very end of the positive prompt (e.g. 'clean background, no text, no watermark, no logos').\n"
                "- Output Format: Output the positive prompt under PROMPT: and leave the NEGATIVE: line completely empty.\n"
                "- Prohibited: Never use generic buzzwords like 'masterpiece', '8k', or 'photorealistic'."
            ),
            "positive_prefix": "",
            "default_negative": ""
        }
    }
}


def get_base_dir() -> str:
    """Returns absolute path of the repository root."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def list_projects() -> List[str]:
    """Lists existing story slugs under projects/ directory."""
    projects_dir = os.path.join(get_base_dir(), "projects")
    if not os.path.isdir(projects_dir):
        return []
    return [
        d for d in os.listdir(projects_dir)
        if os.path.isdir(os.path.join(projects_dir, d))
    ]


def slugify(text: str) -> str:
    """Sanitizes text into a safe directory and URL slug."""
    import re
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


def init_project(story_slug: str, input_text: Optional[str] = None, workflow_name: str = "sdxl_base.json", base_dir: Optional[str] = None) -> str:
    """
    Scaffolds /projects/{story_slug}/ with source, config, artifacts, images directories,
    default configs, and optionally initial input_story.txt.
    """
    story_slug = slugify(story_slug)
    repo_base = get_base_dir()
    if base_dir is None:
        project_dir = os.path.join(repo_base, "projects", story_slug)
    else:
        project_dir = os.path.join(base_dir, story_slug)

    for subdir in ["source", "config", "artifacts", "images"]:
        os.makedirs(os.path.join(project_dir, subdir), exist_ok=True)

    # Write configs if not present
    llm_path = os.path.join(project_dir, "config", "llm_models.json")
    if not os.path.exists(llm_path):
        with open(llm_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_LLM_CONFIG, f, indent=2)

    diff_path = os.path.join(project_dir, "config", "diffusion_profiles.json")
    if not os.path.exists(diff_path):
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DIFFUSION_PROFILES, f, indent=2)

    # Copy workflow
    target_wf = os.path.join(project_dir, "config", "workflow_api.json")
    if not os.path.exists(target_wf):
        src_wf = os.path.join(repo_base, "workflows", workflow_name)
        if os.path.isfile(src_wf):
            shutil.copyfile(src_wf, target_wf)

    # Write source text if supplied
    if input_text is not None:
        source_file = os.path.join(project_dir, "source", "input_story.txt")
        with open(source_file, "w", encoding="utf-8") as f:
            f.write(input_text)

    return project_dir


def get_project_diffusion_profiles(project_dir: str) -> Dict[str, Any]:
    """Loads diffusion profiles for a project, falling back to defaults."""
    diff_path = os.path.join(project_dir, "config", "diffusion_profiles.json")
    if os.path.isfile(diff_path):
        try:
            with open(diff_path, "r", encoding="utf-8") as f:
                return json.load(f).get("profiles", {})
        except Exception:
            pass
    return DEFAULT_DIFFUSION_PROFILES.get("profiles", {})


def update_project_diffusion_profile(project_dir: str, profile_name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Updates fields for a specific profile in diffusion_profiles.json."""
    diff_path = os.path.join(project_dir, "config", "diffusion_profiles.json")
    cfg = dict(DEFAULT_DIFFUSION_PROFILES)
    if os.path.isfile(diff_path):
        try:
            with open(diff_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    if "profiles" not in cfg:
        cfg["profiles"] = dict(DEFAULT_DIFFUSION_PROFILES.get("profiles", {}))
    if profile_name not in cfg["profiles"]:
        cfg["profiles"][profile_name] = {}
    cfg["profiles"][profile_name].update(updates)
    os.makedirs(os.path.dirname(diff_path), exist_ok=True)
    with open(diff_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg["profiles"]


def get_global_styles_path() -> str:
    """Returns absolute path to root config/global_styles.json or environment override."""
    if "GLOBAL_STYLES_PATH" in os.environ and os.environ["GLOBAL_STYLES_PATH"]:
        return os.environ["GLOBAL_STYLES_PATH"]
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "config", "global_styles.json")


def load_global_styles() -> Dict[str, List[Dict[str, Any]]]:
    """Loads the universal style presets library, creating it if missing."""
    path = get_global_styles_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("art", [])
                    data.setdefault("photography", [])
                    return data
        except Exception:
            pass
    return {"art": [], "photography": []}


def save_global_styles(data: Dict[str, List[Dict[str, Any]]]) -> None:
    """Persists the universal style presets library."""
    path = get_global_styles_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def slugify_style(name: str) -> str:
    """Converts a style name into a clean alphanumeric slug."""
    import re
    cleaned = re.sub(r'[^a-zA-Z0-9]+', '_', name.strip().lower()).strip('_')
    return cleaned or "style"


def merge_into_global_styles(
    styles: List[Dict[str, Any]],
    category: str = "art",
    source_project: str = "project"
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Merges newly inferred or saved styles into the universal library.
    Prevents duplicate entries based on normalized name and id.
    """
    cat_key = "photography" if category.lower() in ("photography", "photo") else "art"
    global_data = load_global_styles()
    existing_items = global_data.get(cat_key, [])

    existing_slugs = {item.get("id"): idx for idx, item in enumerate(existing_items) if item.get("id")}
    existing_names = {item.get("name", "").strip().lower(): idx for idx, item in enumerate(existing_items) if item.get("name")}

    for s in styles:
        name = s.get("name", "").strip()
        if not name:
            continue
        sid = s.get("id") or slugify_style(name)
        desc = s.get("description", "").strip()
        entry = {
            "id": sid,
            "name": name,
            "description": desc,
            "category": cat_key,
            "source_project": s.get("source_project") or source_project
        }

        norm_name = name.lower()
        if norm_name in existing_names:
            # Update if incoming description is more detailed
            idx = existing_names[norm_name]
            if len(desc) > len(existing_items[idx].get("description", "")):
                existing_items[idx]["description"] = desc
        elif sid in existing_slugs:
            idx = existing_slugs[sid]
            if len(desc) > len(existing_items[idx].get("description", "")):
                existing_items[idx]["description"] = desc
        else:
            existing_items.append(entry)
            existing_names[norm_name] = len(existing_items) - 1
            existing_slugs[sid] = len(existing_items) - 1

    global_data[cat_key] = existing_items
    save_global_styles(global_data)
    return global_data


def get_project_styles(project_dir: str) -> Dict[str, Any]:
    """
    Loads project-level inferred styles and active style selection from 03_visual_bible.json.
    Falls back to global style library if project styles are not yet generated.
    """
    bible_path = os.path.join(project_dir, "artifacts", "03_visual_bible.json")
    project_presets = {"art": [], "photography": []}
    active_style = None

    if os.path.isfile(bible_path):
        try:
            with open(bible_path, "r", encoding="utf-8") as f:
                bible = json.load(f)
                if "style_presets" in bible and isinstance(bible["style_presets"], dict):
                    project_presets["art"] = bible["style_presets"].get("art", [])
                    project_presets["photography"] = bible["style_presets"].get("photography", [])
                active_style = bible.get("active_style")
                if not active_style and bible.get("global_art_style"):
                    active_style = {
                        "id": "custom",
                        "name": "Custom / Inferred Style",
                        "description": bible.get("global_art_style"),
                        "category": "art"
                    }
        except Exception:
            pass

    global_styles = load_global_styles()

    # If project has no presets yet, populate from global styles as starters
    effective_art = project_presets["art"] if project_presets["art"] else global_styles.get("art", [])
    effective_photo = project_presets["photography"] if project_presets["photography"] else global_styles.get("photography", [])

    if not active_style and effective_art:
        active_style = effective_art[0]

    return {
        "presets": {
            "art": effective_art,
            "photography": effective_photo
        },
        "active_style": active_style,
        "global_library": global_styles
    }


def update_project_active_style(
    project_dir: str,
    style_id: str,
    style_name: Optional[str] = None,
    description: Optional[str] = None,
    category: str = "art"
) -> Dict[str, Any]:
    """
    Sets the active style in 03_visual_bible.json and synchronizes global_art_style.
    """
    bible_path = os.path.join(project_dir, "artifacts", "03_visual_bible.json")
    if not os.path.isfile(bible_path):
        bible = {"global_art_style": "", "characters": {}, "settings": {}, "style_presets": {"art": [], "photography": []}}
    else:
        with open(bible_path, "r", encoding="utf-8") as f:
            bible = json.load(f)

    # Find style details if not fully provided
    if not style_name or not description:
        all_styles = []
        if "style_presets" in bible:
            all_styles.extend(bible["style_presets"].get("art", []))
            all_styles.extend(bible["style_presets"].get("photography", []))
        global_lib = load_global_styles()
        all_styles.extend(global_lib.get("art", []))
        all_styles.extend(global_lib.get("photography", []))

        for s in all_styles:
            if s.get("id") == style_id:
                style_name = style_name or s.get("name")
                description = description or s.get("description")
                category = s.get("category", category)
                break

    style_obj = {
        "id": style_id,
        "name": style_name or style_id,
        "description": description or "",
        "category": category
    }

    bible["active_style"] = style_obj
    if description:
        bible["global_art_style"] = description

    os.makedirs(os.path.dirname(bible_path), exist_ok=True)
    with open(bible_path, "w", encoding="utf-8") as f:
        json.dump(bible, f, indent=2, ensure_ascii=False)

    return bible

