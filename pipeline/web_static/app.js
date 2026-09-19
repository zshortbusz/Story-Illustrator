// pipeline/web_static/app.js: Frontend controller for Automated Story Illustrator

let currentSlug = "";
let systemStatus = null;
let currentManifest = null;
let availableModels = [];
const selectedImageChunks = new Set();
let currentAuditContext = null;
let currentTweakBlock = null;

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function updateSelectedImagesUI() {
  const count = selectedImageChunks.size;
  const btnRegen = document.getElementById("btnRegenerateSelected");
  if (btnRegen) {
    btnRegen.textContent = `↻ Regenerate Selected (${count})`;
    btnRegen.disabled = count === 0;
  }
  const btnToggle = document.getElementById("btnToggleSelectAll");
  if (btnToggle) {
    const totalIllustrated = (currentManifest?.blocks || []).filter(b => b.illustration).length;
    btnToggle.textContent = (count > 0 && count === totalIllustrated) ? "Deselect All" : "Select All";
  }
  document.querySelectorAll(".image-card").forEach(card => {
    const cid = card.dataset.chunkId;
    if (selectedImageChunks.has(cid)) {
      card.classList.add("selected");
    } else {
      card.classList.remove("selected");
    }
  });
}

// Toast notification helper
function showToast(message, type = "success") {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = `toast show toast-${type}`;
  setTimeout(() => {
    toast.className = "toast";
  }, 3500);
}

// ----------------------------------------------------------------------------
// Initialization & Status Polling
// ----------------------------------------------------------------------------
async function init() {
  setupEventListeners();
  await refreshStatus();
  await loadWorkflows();
  await loadProjects();
}

async function refreshStatus() {
  try {
    const url = currentSlug ? `/api/status?slug=${encodeURIComponent(currentSlug)}` : "/api/status";
    const res = await fetch(url);
    systemStatus = await res.json();

    const lmBadge = document.getElementById("badgeLMStudio");
    const comfyBadge = document.getElementById("badgeComfyUI");
    const lmLabel = document.getElementById("labelLMStudio");
    const comfyLabel = document.getElementById("labelComfyUI");

    const llmInfo = systemStatus.llm || systemStatus.lm_studio || {};
    const imgInfo = systemStatus.image || systemStatus.comfyui || {};

    if (llmInfo.online) {
      lmBadge.className = "badge badge-online";
      lmBadge.title = llmInfo.message || "LLM Provider Online";
      availableModels = llmInfo.models || [];
      populateModelDropdowns(availableModels);
    } else {
      lmBadge.className = "badge badge-offline";
      lmBadge.title = llmInfo.message || "LLM Provider Offline";
    }
    if (lmLabel) {
      lmLabel.textContent = llmInfo.backend === "lm_studio" ? "LM Studio :1234" : "LLM API";
    }

    if (imgInfo.online) {
      comfyBadge.className = "badge badge-online";
      comfyBadge.title = imgInfo.message || "Image Generator Online";
    } else {
      comfyBadge.className = "badge badge-offline";
      comfyBadge.title = imgInfo.message || "Image Generator Offline";
    }
    if (comfyLabel) {
      comfyLabel.textContent = imgInfo.backend === "comfyui" ? "ComfyUI :8188" : "Image API";
    }

    updateHardwareBanner();
  } catch (err) {
    console.error("Status error:", err);
  }
}

function updateHardwareBanner() {
  const activeTab = document.querySelector(".tab-btn.active")?.dataset.tab;
  const banner = document.getElementById("hardwareBanner");
  const title = document.getElementById("bannerTitle");
  const desc = document.getElementById("bannerDesc");

  const llmBackend = systemStatus?.llm?.backend || "lm_studio";
  const imgBackend = systemStatus?.image?.backend || "comfyui";

  if (activeTab === "tab-render") {
    banner.className = "hardware-banner phase-2-active";
    title.textContent = "Phase 2 Active (Illustration Rendering):";
    if (imgBackend === "comfyui") {
      desc.textContent = "ComfyUI server must be running at http://127.0.0.1:8188. LM Studio should be UNLOADED / CLOSED to free GPU VRAM.";
    } else {
      desc.textContent = "Remote Images API active. Rendering proceeds headlessly via your configured image endpoint.";
    }
  } else if (activeTab === "tab-reader") {
    banner.className = "hardware-banner phase-3-active";
    title.textContent = "Phase 3 Active (Reader Assembly):";
    desc.textContent = "Pure Python compilation with embedded base64 images. 100% portable HTML reader with zero runtime dependencies.";
  } else {
    banner.className = "hardware-banner phase-1-active";
    title.textContent = "Phase 1 Active (Analysis & Prompts):";
    if (llmBackend === "lm_studio") {
      desc.textContent = "LM Studio must be running at http://localhost:1234 with your selected model loaded. ComfyUI should be CLOSED to prevent VRAM competition.";
    } else {
      desc.textContent = "Remote LLM API active. Prompts and story analysis synthesize via your configured endpoint.";
    }
  }
}

function getActiveRoleModel(selectId, customId) {
  const sel = document.getElementById(selectId);
  const custom = document.getElementById(customId);
  const selVal = sel?.value?.trim() || "";
  const customVal = custom?.value?.trim() || "";
  return selVal || customVal;
}

function populateModelDropdowns(models) {
  const roleConfigs = [
    { selectId: "modelNarrativeDirector", customId: "modelNarrativeDirectorCustom" },
    { selectId: "modelStructuredAnalyst", customId: "modelStructuredAnalystCustom" },
    { selectId: "modelPromptSynthesizer", customId: "modelPromptSynthesizerCustom" }
  ];

  roleConfigs.forEach(({ selectId, customId }) => {
    const sel = document.getElementById(selectId);
    const custom = document.getElementById(customId);
    if (!sel) return;

    const currentVal = custom?.value.trim() || sel.value;
    sel.innerHTML = `<option value="">-- Select Loaded Model --</option>`;
    models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      sel.appendChild(opt);
    });

    if (currentVal && Array.from(sel.options).some(o => o.value === currentVal)) {
      sel.value = currentVal;
    } else if (models.length > 0 && !currentVal) {
      sel.value = models[0];
      if (custom) custom.value = models[0];
    }

    if (!sel.dataset.synced) {
      sel.dataset.synced = "true";
      sel.addEventListener("change", () => {
        if (sel.value && custom) {
          custom.value = sel.value;
        }
      });
    }
    if (custom && !custom.dataset.synced) {
      custom.dataset.synced = "true";
      custom.addEventListener("input", () => {
        const val = custom.value.trim();
        if (Array.from(sel.options).some(o => o.value === val)) {
          sel.value = val;
        } else {
          sel.value = "";
        }
      });
    }
  });
}

// ----------------------------------------------------------------------------
// Projects Management
// ----------------------------------------------------------------------------
async function loadProjects(preferredSlug = null) {
  try {
    const res = await fetch("/api/projects");
    const projects = await res.json();
    const select = document.getElementById("projectSelect");
    select.innerHTML = "";

    projects.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.slug;
      opt.textContent = p.title + (p.has_manifest ? " (Illustrated)" : "");
      select.appendChild(opt);
    });

    if (projects.length > 0) {
      let targetSlug = preferredSlug || currentSlug;
      if (!targetSlug || !projects.some(p => p.slug === targetSlug)) {
        targetSlug = projects[0].slug;
      }
      currentSlug = targetSlug;
      select.value = currentSlug;
      await loadProjectData(currentSlug);
    } else {
      currentSlug = "";
      select.value = "";
    }
  } catch (err) {
    showToast("Failed to load projects: " + err, "error");
  }
}

async function loadWorkflows() {
  try {
    const res = await fetch("/api/workflows");
    const data = await res.json();
    const wfSelect = document.getElementById("selectWorkflow");
    if (!wfSelect) return;

    wfSelect.innerHTML = "";
    data.workflows.forEach(wf => {
      const o1 = document.createElement("option");
      o1.value = wf;
      o1.textContent = wf;
      wfSelect.appendChild(o1);
    });
  } catch (err) {
    console.error("Workflow list error:", err);
  }
}

async function loadProjectData(slug) {
  if (!slug) return;
  currentSlug = slug;
  await Promise.all([
    loadLLMConfig(),
    loadDiffusionConfig(),
    loadSourceText(),
    loadChunks(),
    loadBible(),
    loadBeats(),
    loadManifest()
  ]);
  loadReaderPreview();
}

// ----------------------------------------------------------------------------
// Configurations (Loaded into In-Tab Controls)
// ----------------------------------------------------------------------------
async function loadLLMConfig() {
  try {
    const res = await fetch(`/api/project/${currentSlug}/config/llm`);
    const cfg = await res.json();
    const roles = cfg.roles || {};

    const syncRole = (roleKey, customId, selectId, tempId, tempValId, promptId, defaultTemp) => {
      const r = roles[roleKey] || {};
      const m = r.model || "";
      const customEl = document.getElementById(customId);
      const selectEl = document.getElementById(selectId);
      if (customEl) customEl.value = m;
      if (selectEl && m) {
        if (Array.from(selectEl.options).some(o => o.value === m)) {
          selectEl.value = m;
        }
      }
      const t = r.temperature != null ? r.temperature : defaultTemp;
      const tempEl = document.getElementById(tempId);
      const tempValEl = document.getElementById(tempValId);
      if (tempEl) tempEl.value = t;
      if (tempValEl) tempValEl.textContent = t;
      const promptEl = document.getElementById(promptId);
      if (promptEl) promptEl.value = r.system_prompt || "";
    };

    // Structured Analyst (Tab 2: Visual Bible)
    syncRole("structured_analyst", "modelStructuredAnalystCustom", "modelStructuredAnalyst", "tempAnalyst", "tempAnalystVal", "promptAnalyst", 0.2);

    // Narrative Director (Tab 3: Visual Beats)
    syncRole("narrative_director", "modelNarrativeDirectorCustom", "modelNarrativeDirector", "tempNarrative", "tempNarrativeVal", "promptNarrative", 0.3);

    // Prompt Synthesizer (Tab 4: Manifest & Prompts)
    syncRole("prompt_synthesizer", "modelPromptSynthesizerCustom", "modelPromptSynthesizer", "tempSynth", "tempSynthVal", "promptSynth", 0.35);
  } catch (err) {
    console.error("LLM config load error:", err);
  }
}


async function saveCurrentLLMConfig() {
  const cfg = {
    api_base: "http://localhost:1234/v1",
    roles: {
      structured_analyst: {
        model: getActiveRoleModel("modelStructuredAnalyst", "modelStructuredAnalystCustom"),
        temperature: parseFloat(document.getElementById("tempAnalyst").value),
        max_tokens: -1,
        system_prompt: document.getElementById("promptAnalyst").value
      },
      narrative_director: {
        model: getActiveRoleModel("modelNarrativeDirector", "modelNarrativeDirectorCustom"),
        temperature: parseFloat(document.getElementById("tempNarrative").value),
        max_tokens: -1,
        system_prompt: document.getElementById("promptNarrative").value
      },
      prompt_synthesizer: {
        model: getActiveRoleModel("modelPromptSynthesizer", "modelPromptSynthesizerCustom"),
        temperature: parseFloat(document.getElementById("tempSynth").value),
        max_tokens: -1,
        system_prompt: document.getElementById("promptSynth").value
      }
    }
  };

  try {
    const res = await fetch(`/api/project/${currentSlug}/config/llm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg)
    });
    if (res.ok) {
      showToast("Model settings saved!");
    } else {
      showToast("Failed to save model settings.", "error");
    }
  } catch (err) {
    showToast("Error: " + err, "error");
  }
}

async function loadDiffusionConfig() {
  try {
    const res = await fetch(`/api/project/${currentSlug}/config/diffusion`);
    const cfg = await res.json();
    const sel = document.getElementById("activeProfileSelect");
    sel.innerHTML = "";

    const profiles = cfg.profiles || {};
    Object.keys(profiles).forEach(k => {
      const opt = document.createElement("option");
      opt.value = k;
      opt.textContent = k;
      sel.appendChild(opt);
    });

    sel.value = cfg.active_profile || "sdxl_base";
    const curProfile = profiles[sel.value] || {};
    document.getElementById("profileNegativePrompt").value = curProfile.default_negative || "";
    const prefixEl = document.getElementById("profilePositivePrefix");
    if (prefixEl) prefixEl.value = curProfile.positive_prefix || "";
  } catch (err) {
    console.error("Diffusion config load error:", err);
  }
}

async function saveDiffusionConfig() {
  try {
    const res = await fetch(`/api/project/${currentSlug}/config/diffusion`);
    const cfg = await res.json();
    const activeProf = document.getElementById("activeProfileSelect").value;
    cfg.active_profile = activeProf;
    if (cfg.profiles && cfg.profiles[activeProf]) {
      cfg.profiles[activeProf].default_negative = document.getElementById("profileNegativePrompt").value.trim();
      const prefixEl = document.getElementById("profilePositivePrefix");
      if (prefixEl) {
        cfg.profiles[activeProf].positive_prefix = prefixEl.value.trim();
      }
    }

    await fetch(`/api/project/${currentSlug}/config/diffusion`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg)
    });
    showToast("Diffusion profile updated!");
  } catch (err) {
    showToast("Error updating diffusion profile: " + err, "error");
  }
}

// ----------------------------------------------------------------------------
// Tab 1: Chunks
// ----------------------------------------------------------------------------
async function loadSourceText() {
  try {
    const res = await fetch(`/api/project/${currentSlug}/source`);
    const data = await res.json();
    document.getElementById("sourceStoryText").value = data.text || "";
  } catch (err) {
    console.error("Source text load error:", err);
  }
}

async function loadChunks() {
  try {
    const res = await fetch(`/api/project/${currentSlug}/artifact/chunks`);
    const listEl = document.getElementById("chunksList");
    listEl.innerHTML = "";

    if (!res.ok) {
      listEl.innerHTML = `<div class="chunk-card"><p class="chunk-text">No chunks found. Click <strong>Run Chunker</strong> to generate 01_chunks.json.</p></div>`;
      document.getElementById("chunkCount").textContent = "0";
      document.getElementById("totalWordCount").textContent = "0 words";
      return;
    }

    const data = await res.json();
    const chunks = data.chunks || [];
    let totalWords = 0;

    chunks.forEach(c => {
      totalWords += c.word_count || 0;
      const card = document.createElement("div");
      card.className = "chunk-card";
      card.innerHTML = `
        <div class="chunk-card-header">
          <span class="chunk-id">${c.chunk_id}</span>
          <span>${c.word_count} words</span>
        </div>
        <p class="chunk-text">${c.text}</p>
      `;
      listEl.appendChild(card);
    });

    document.getElementById("chunkCount").textContent = chunks.length;
    document.getElementById("totalWordCount").textContent = `${totalWords.toLocaleString()} words`;
  } catch (err) {
    console.error("Chunks error:", err);
  }
}

// ----------------------------------------------------------------------------
// Tab 2: Visual Bible
// ----------------------------------------------------------------------------
async function loadBible() {
  try {
    const res = await fetch(`/api/project/${currentSlug}/artifact/bible`);
    const charList = document.getElementById("charactersList");
    const settingList = document.getElementById("settingsList");
    charList.innerHTML = "";
    settingList.innerHTML = "";

    if (!res.ok) {
      document.getElementById("bibleArtStyle").value = "";
      charList.innerHTML = `<p class="section-desc">No characters found yet. Click <strong>Run Extraction</strong>.</p>`;
      settingList.innerHTML = `<p class="section-desc">No settings found yet. Click <strong>Run Extraction</strong>.</p>`;
      return;
    }

    const bible = await res.json();
    document.getElementById("bibleArtStyle").value = bible.global_art_style || "";

    const chars = bible.characters || {};
    Object.entries(chars).forEach(([name, charData]) => {
      let baseDna = "";
      let defaultAttire = "";
      let timelineMods = [];
      let wardrobeTimeline = [];
      let altAttires = {};

      if (typeof charData === "string") {
        baseDna = charData;
      } else if (charData && typeof charData === "object") {
        baseDna = charData.base_dna || charData.physical_dna || charData.description || "";
        defaultAttire = charData.default_attire || "";
        timelineMods = charData.timeline_modifications || [];
        wardrobeTimeline = charData.wardrobe_timeline || [];
        altAttires = charData.alternate_attires || {};
      }

      const item = document.createElement("div");
      item.className = "bible-item-card";
      item.dataset.timelineMods = JSON.stringify(timelineMods);
      item.dataset.wardrobeTimeline = JSON.stringify(wardrobeTimeline);
      item.dataset.altAttires = JSON.stringify(altAttires);

      let modsBadgeHtml = "";
      if (timelineMods.length > 0) {
        modsBadgeHtml = `<div style="margin-top: 6px; font-size: 0.75rem; color: #f59e0b;">&#9889; <strong>Modifications:</strong> ${timelineMods.map(m => `[${m.introduced_chunk_id || 'chunk_???'}] ${m.trait || ''}`).join("; ")}</div>`;
      }

      let wardrobeBadgeHtml = "";
      if (wardrobeTimeline.length > 1) {
        wardrobeBadgeHtml = `<div style="margin-top: 4px; font-size: 0.75rem; color: #38bdf8;">&#128084; <strong>Wardrobe Timeline:</strong> ${wardrobeTimeline.map(w => `[${w.from_chunk_id || 'chunk_???'}] ${w.context ? `(${w.context}) ` : ''}${w.attire || ''}`).join("; ")}</div>`;
      }

      item.innerHTML = `
        <div class="card-header">
          <input type="text" class="text-input char-name-input" value="${name}" style="font-weight: 600; width: 60%;">
          <button class="btn btn-sm btn-danger btn-del-char">&times;</button>
        </div>
        <div style="margin-top: 6px;">
          <label style="font-size: 0.75rem; color: var(--text-dim); display: block; margin-bottom: 2px;">Physical Base DNA (Face, hair, build, permanent features):</label>
          <textarea class="textarea-input char-desc-input char-dna-input" rows="2">${baseDna}</textarea>
        </div>
        <div style="margin-top: 6px;">
          <label style="font-size: 0.75rem; color: var(--text-dim); display: block; margin-bottom: 2px;">Default / Everyday Attire:</label>
          <input type="text" class="text-input char-attire-input" value="${defaultAttire}" placeholder="e.g. Weathered leather aviator jacket, utility cargo trousers">
        </div>
        ${modsBadgeHtml}
        ${wardrobeBadgeHtml}
      `;
      item.querySelector(".btn-del-char").addEventListener("click", () => item.remove());
      charList.appendChild(item);
    });

    const settings = bible.settings || {};
    Object.entries(settings).forEach(([name, desc]) => {
      const item = document.createElement("div");
      item.className = "bible-item-card";
      item.innerHTML = `
        <div class="card-header">
          <input type="text" class="text-input setting-name-input" value="${name}" style="font-weight: 600; width: 60%;">
          <button class="btn btn-sm btn-danger btn-del-setting">&times;</button>
        </div>
        <textarea class="textarea-input setting-desc-input" rows="3">${desc}</textarea>
      `;
      item.querySelector(".btn-del-setting").addEventListener("click", () => item.remove());
      settingList.appendChild(item);
    });
  } catch (err) {
    console.error("Bible error:", err);
  }
}

function collectBibleFromUI() {
  const artStyle = document.getElementById("bibleArtStyle").value.trim();
  const characters = {};
  const settings = {};

  document.querySelectorAll("#charactersList .bible-item-card").forEach(el => {
    const name = el.querySelector(".char-name-input").value.trim();
    const dna = el.querySelector(".char-dna-input")?.value.trim() || el.querySelector(".char-desc-input")?.value.trim() || "";
    const attire = el.querySelector(".char-attire-input")?.value.trim() || "";
    let timelineMods = [];
    let wardrobeTimeline = [];
    let altAttires = {};
    try { timelineMods = JSON.parse(el.dataset.timelineMods || "[]"); } catch(e) {}
    try { wardrobeTimeline = JSON.parse(el.dataset.wardrobeTimeline || "[]"); } catch(e) {}
    try { altAttires = JSON.parse(el.dataset.altAttires || "{}"); } catch(e) {}

    if (name) {
      // Ensure wardrobe_timeline has base entry if empty but attire provided
      if (wardrobeTimeline.length === 0 && attire) {
        wardrobeTimeline = [{ from_chunk_id: "chunk_000", context: "Standard", attire: attire }];
      } else if (wardrobeTimeline.length > 0 && attire && wardrobeTimeline[0].from_chunk_id === "chunk_000") {
        wardrobeTimeline[0].attire = attire;
      }
      characters[name] = {
        base_dna: dna,
        timeline_modifications: timelineMods,
        wardrobe_timeline: wardrobeTimeline,
        default_attire: attire,
        alternate_attires: altAttires
      };
    }
  });

  document.querySelectorAll("#settingsList .bible-item-card").forEach(el => {
    const name = el.querySelector(".setting-name-input").value.trim();
    const desc = el.querySelector(".setting-desc-input").value.trim();
    if (name) settings[name] = desc;
  });

  return {
    global_art_style: artStyle,
    characters: characters,
    settings: settings
  };
}

async function saveBible() {
  const bible = collectBibleFromUI();
  try {
    const res = await fetch(`/api/project/${currentSlug}/artifact/bible`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bible)
    });
    if (res.ok) {
      showToast("Visual Bible saved!");
    } else {
      showToast("Failed to save Visual Bible.", "error");
    }
  } catch (err) {
    showToast("Error saving bible: " + err, "error");
  }
}

// ----------------------------------------------------------------------------
// Tab 3: Visual Beats
// ----------------------------------------------------------------------------
async function loadBeats() {
  const container = document.getElementById("beatsContainer");
  container.innerHTML = "";
  try {
    const res = await fetch(`/api/project/${currentSlug}/artifact/beats`);
    if (!res.ok) {
      container.innerHTML = `<div class="card" style="grid-column: 1 / -1;"><p>No beats generated yet. Click <strong>Run Beat Selection</strong> to identify scenes.</p></div>`;
      return;
    }

    const data = await res.json();
    const beats = data.selected_beats || [];

    if (beats.length === 0) {
      container.innerHTML = `<div class="card" style="grid-column: 1 / -1;"><p>0 beats selected for this story.</p></div>`;
      return;
    }

    beats.forEach((b, idx) => {
      let attireStr = "";
      if (b.character_attire) {
        if (typeof b.character_attire === "string") {
          attireStr = b.character_attire;
        } else if (typeof b.character_attire === "object") {
          attireStr = Object.entries(b.character_attire).map(([c, a]) => `${c}: ${a}`).join("; ");
        }
      }

      const card = document.createElement("div");
      card.className = "beat-card";
      card.dataset.index = idx;
      card.innerHTML = `
        <div class="card-header">
          <span class="chunk-id">${b.chunk_id || "chunk_???"}</span>
          <select class="select-input beat-scene-type" style="width: auto; padding: 2px 8px; font-size: 0.8rem;">
            <option value="landscape" ${b.scene_type === "landscape" ? "selected" : ""}>landscape</option>
            <option value="portrait" ${b.scene_type === "portrait" ? "selected" : ""}>portrait</option>
            <option value="square" ${b.scene_type === "square" ? "selected" : ""}>square</option>
          </select>
        </div>
        <div class="form-group">
          <label>Action Beat:</label>
          <textarea class="textarea-input beat-action" rows="2">${b.action_beat || ""}</textarea>
        </div>
        <div class="form-group">
          <label>Characters Present (comma separated):</label>
          <input type="text" class="text-input beat-chars" value="${(b.characters_present || []).join(", ")}">
        </div>
        <div class="form-group">
          <label>Scene-Specific Attire (e.g. Elena: emerald gown; Vance: formal doublet):</label>
          <input type="text" class="text-input beat-attire" value="${attireStr}" placeholder="Leave blank to use timeline/default wardrobe">
        </div>
        <div class="form-group">
          <label>Setting:</label>
          <input type="text" class="text-input beat-setting" value="${b.setting || ""}">
        </div>
        <div class="form-group">
          <label>Camera Framing &amp; Lighting:</label>
          <input type="text" class="text-input beat-camera" value="${b.camera_framing || ""}">
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">
          <button class="btn btn-sm btn-secondary btn-preview-context" data-index="${idx}" data-chunk="${b.chunk_id || ''}">&#128065; Preview Prompt Context</button>
          <button class="btn btn-sm btn-danger btn-delete-beat" data-index="${idx}">Delete Beat</button>
        </div>
      `;
      container.appendChild(card);
    });

    container.querySelectorAll(".btn-preview-context").forEach(btn => {
      btn.addEventListener("click", e => {
        const card = e.target.closest(".beat-card");
        const chunkId = btn.dataset.chunk;
        const actionBeat = card.querySelector(".beat-action")?.value || "";
        const charsPresent = (card.querySelector(".beat-chars")?.value || "")
          .split(",").map(c => c.trim()).filter(c => c);
        const attireStr = card.querySelector(".beat-attire")?.value || "";
        const setting = card.querySelector(".beat-setting")?.value || "";
        const camera = card.querySelector(".beat-camera")?.value || "";
        const sceneType = card.querySelector(".beat-scene-type")?.value || "landscape";

        let characterAttire = {};
        if (attireStr) {
          attireStr.split(";").forEach(pair => {
            const parts = pair.split(":");
            if (parts.length === 2) {
              characterAttire[parts[0].trim()] = parts[1].trim();
            }
          });
        }

        const currentBeatData = {
          chunk_id: chunkId,
          scene_type: sceneType,
          action_beat: actionBeat,
          characters_present: charsPresent,
          character_attire: characterAttire,
          setting: setting,
          camera_framing: camera
        };

        previewPromptContext(chunkId, currentBeatData);
      });
    });

    container.querySelectorAll(".btn-delete-beat").forEach(btn => {
      btn.addEventListener("click", e => {
        const idx = parseInt(e.target.dataset.index);
        beats.splice(idx, 1);
        saveBeatsArray(beats);
      });
    });
  } catch (err) {
    console.error("Beats error:", err);
  }
}

async function saveBeatsArray(beats) {
  try {
    const res = await fetch(`/api/project/${currentSlug}/artifact/beats`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_beats: beats })
    });
    if (res.ok) {
      showToast("Visual beats saved!");
      await loadBeats();
    }
  } catch (err) {
    showToast("Failed to save beats: " + err, "error");
  }
}

function collectBeatsFromUI() {
  const cards = document.querySelectorAll(".beat-card");
  const beats = [];
  cards.forEach(c => {
    const cid = c.querySelector(".chunk-id").textContent.trim();
    const stype = c.querySelector(".beat-scene-type").value;
    const action = c.querySelector(".beat-action").value;
    const chars = c.querySelector(".beat-chars").value.split(",").map(s => s.trim()).filter(Boolean);
    const attireRaw = c.querySelector(".beat-attire")?.value.trim() || "";
    const setting = c.querySelector(".beat-setting").value.trim();
    const camera = c.querySelector(".beat-camera").value.trim();

    const charAttire = {};
    if (attireRaw) {
      attireRaw.split(";").forEach(part => {
        part = part.trim();
        if (part.includes(":")) {
          const [cname, catt] = part.split(":", 2);
          if (cname && catt) charAttire[cname.trim()] = catt.trim();
        } else if (part.includes(" in ")) {
          const [cname, catt] = part.split(" in ", 2);
          if (cname && catt) charAttire[cname.trim()] = catt.trim();
        } else if (part && chars.length > 0) {
          charAttire[chars[0]] = part;
        }
      });
    }

    beats.push({
      chunk_id: cid,
      scene_type: stype,
      characters_present: chars,
      character_attire: charAttire,
      setting: setting,
      action_beat: action,
      camera_framing: camera
    });
  });
  return beats;
}

// ----------------------------------------------------------------------------
// Prompt Context & Visual Bible Audit
// ----------------------------------------------------------------------------
function renderContinuityBadgesRow(ctx) {
  if (!ctx) return "";
  const badges = [];

  // Setting badge
  if (ctx.setting && ctx.setting.name) {
    badges.push(`<span class="audit-badge badge-setting" title="Resolved Setting / Environment">&#127963; ${escapeHtml(ctx.setting.name)}</span>`);
  }

  // Character badges
  (ctx.characters || []).forEach(ch => {
    badges.push(`<span class="audit-badge badge-char" title="Character Base DNA">&#128100; ${escapeHtml(ch.name)}</span>`);

    // Attire badge
    if (ch.resolved_attire) {
      const isOverride = ch.attire_source === "scene_override";
      const icon = isOverride ? "&#9889; " : "&#128087; ";
      badges.push(`<span class="audit-badge badge-attire" title="${isOverride ? 'Scene Attire Override' : 'Wardrobe'}">${icon}${escapeHtml(ch.resolved_attire)}</span>`);
    }

    // Active timeline modifications
    (ch.active_timeline_mods || []).forEach(mod => {
      const modText = (mod && typeof mod === "object") ? (mod.trait || JSON.stringify(mod)) : String(mod);
      badges.push(`<span class="audit-badge badge-mod" title="Active Timeline Mod (${escapeHtml(ch.name)})">&#10024; ${escapeHtml(modText)}</span>`);
    });

    // Skipped timeline modifications
    if (ch.skipped_timeline_mods && ch.skipped_timeline_mods.length > 0) {
      badges.push(`<span class="audit-badge badge-skipped" title="Future modification (not active in this scene)">&#9203; Future: ${ch.skipped_timeline_mods.length} mod(s)</span>`);
    }
  });

  if (badges.length === 0) return "";
  return `<div class="continuity-badges-row">${badges.join("")}</div>`;
}

function openPromptContextModal(ctx, chunkId = "") {
  if (!ctx) return;
  currentAuditContext = ctx;

  const modal = document.getElementById("modalPromptContext");
  if (!modal) return;

  // Header badges
  const badgeChunk = document.getElementById("promptContextChunkBadge");
  if (badgeChunk) badgeChunk.textContent = chunkId || ctx.chunk_id || "Scene";

  const badgeProfile = document.getElementById("promptContextProfileBadge");
  if (badgeProfile) badgeProfile.textContent = `Profile: ${ctx.active_profile || "standard"}`;

  // Tab 1: Visual Bible Audit
  // 1. Setting card
  const settingCard = document.getElementById("auditSettingCard");
  if (settingCard) {
    if (ctx.setting && (ctx.setting.name || ctx.setting.visual_keywords || ctx.setting.full_description)) {
      const s = ctx.setting;
      let html = `<div style="font-weight: 600; font-size: 1rem; color: var(--text); margin-bottom: 4px;">&#127963; ${escapeHtml(s.name || "Setting")}</div>`;
      if (s.visual_keywords) html += `<p style="margin: 2px 0; font-size: 0.85rem;"><strong>Visual Keywords:</strong> ${escapeHtml(s.visual_keywords)}</p>`;
      if (s.lighting_ambience) html += `<p style="margin: 2px 0; font-size: 0.85rem;"><strong>Lighting &amp; Ambience:</strong> ${escapeHtml(s.lighting_ambience)}</p>`;
      if (s.era_architecture) html += `<p style="margin: 2px 0; font-size: 0.85rem;"><strong>Era &amp; Architecture:</strong> ${escapeHtml(s.era_architecture)}</p>`;
      if (s.full_description) html += `<p style="margin: 4px 0 0 0; font-size: 0.8rem; color: var(--text-dim); border-top: 1px dashed var(--border); padding-top: 4px;">${escapeHtml(s.full_description)}</p>`;
      settingCard.innerHTML = html;
    } else {
      settingCard.innerHTML = `<p style="color: var(--text-dim); margin: 0;">No specific setting specified for this beat.</p>`;
    }
  }

  // 2. Characters List
  const charsList = document.getElementById("auditCharactersList");
  if (charsList) {
    charsList.innerHTML = "";
    const chars = ctx.characters || [];
    if (chars.length === 0) {
      charsList.innerHTML = `<div class="card" style="padding: 8px 12px; background: rgba(255,255,255,0.02);"><p style="color: var(--text-dim); margin: 0;">No characters present in this beat.</p></div>`;
    } else {
      chars.forEach(ch => {
        const charCard = document.createElement("div");
        charCard.className = "card";
        charCard.style.cssText = "background: rgba(255,255,255,0.02); border-left: 3px solid #6366f1; padding: 10px 14px;";

        let modsHtml = "";
        if (ch.active_timeline_mods && ch.active_timeline_mods.length > 0) {
          modsHtml = ch.active_timeline_mods.map(m => {
            const txt = (m && typeof m === "object") ? (m.trait || JSON.stringify(m)) : String(m);
            return `<span class="audit-badge badge-mod">&#10024; ${escapeHtml(txt)}</span>`;
          }).join(" ");
        } else {
          modsHtml = `<span style="font-size: 0.8rem; color: var(--text-dim);">None (Scene occurs before any timeline changes)</span>`;
        }

        let skippedHtml = "";
        if (ch.skipped_timeline_mods && ch.skipped_timeline_mods.length > 0) {
          skippedHtml = `<div style="margin-top: 6px;"><strong style="font-size: 0.8rem; color: var(--text-dim);">Future Story Modifications (Excluded):</strong><br>` +
            ch.skipped_timeline_mods.map(m => {
              const txt = (m && typeof m === "object") ? (m.trait || JSON.stringify(m)) : String(m);
              const cidTag = (m && m.chunk_id) ? `[${escapeHtml(m.chunk_id)}] ` : "";
              return `<span class="audit-badge badge-skipped" style="margin-top: 3px;">&#9203; Future ${cidTag}${escapeHtml(txt)}</span>`;
            }).join(" ") +
            `</div>`;
        }

        const attireSourceLabel = (ch.attire_source === "scene_override" || ch.attire_source === "beat_override")
          ? `<span class="badge badge-accent" style="font-size: 0.7rem;">Scene Override</span>`
          : `<span class="badge badge-neutral" style="font-size: 0.7rem;">Timeline / Wardrobe</span>`;

        charCard.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-weight: 600; font-size: 0.95rem; color: var(--accent-light);">&#128100; ${escapeHtml(ch.name)}</span>
            ${attireSourceLabel}
          </div>
          <p style="margin: 0 0 6px 0; font-size: 0.85rem;"><strong>Base DNA (Immutable):</strong> ${escapeHtml(ch.base_dna || ch.full_description || "N/A")}</p>
          <p style="margin: 0 0 6px 0; font-size: 0.85rem;"><strong>Resolved Attire:</strong> <span class="audit-badge badge-attire">${escapeHtml(ch.resolved_attire || "Default Wardrobe")}</span></p>
          <div style="margin: 0 0 4px 0; font-size: 0.85rem;">
            <strong>Active Timeline Modifications:</strong><br>
            <div style="margin-top: 4px;">${modsHtml}</div>
          </div>
          ${skippedHtml}
        `;
        charsList.appendChild(charCard);
      });
    }
  }

  // 3. Global Art Style & Action Beat
  const elArtStyle = document.getElementById("auditArtStyle");
  if (elArtStyle) elArtStyle.textContent = ctx.art_style || "Default Art Style";

  const elActionBeat = document.getElementById("auditActionBeat");
  if (elActionBeat) elActionBeat.textContent = ctx.action_beat || "N/A";

  const elCamera = document.getElementById("auditCameraFraming");
  if (elCamera) elCamera.textContent = ctx.camera_framing || "N/A";

  // Tab 2: Raw LLM Messages
  const elSysPrompt = document.getElementById("auditSystemPrompt");
  if (elSysPrompt) elSysPrompt.value = ctx.system_prompt || "";

  const elUserPrompt = document.getElementById("auditUserPrompt");
  if (elUserPrompt) elUserPrompt.value = ctx.raw_user_prompt || ctx.user_prompt || "";

  // Tab 3: Scene & Model Specs
  const elModel = document.getElementById("auditModelName");
  if (elModel) elModel.textContent = ctx.model || "N/A";

  const elTemp = document.getElementById("auditTemperature");
  if (elTemp) elTemp.textContent = ctx.temperature !== undefined ? ctx.temperature : "N/A";

  const elProfile = document.getElementById("auditProfileName");
  if (elProfile) elProfile.textContent = ctx.active_profile || "standard";

  const elSceneType = document.getElementById("auditSceneType");
  if (elSceneType) elSceneType.textContent = ctx.scene_type || "landscape";

  const elDims = document.getElementById("auditDimensions");
  if (elDims) elDims.textContent = `${ctx.dimensions?.width || "?"} x ${ctx.dimensions?.height || "?"}`;

  const elNeg = document.getElementById("auditDefaultNegative");
  if (elNeg) elNeg.textContent = ctx.default_negative || "None";

  // Reset tab to Tab 1 (Visual Bible Audit)
  document.querySelectorAll("#modalPromptContext .modal-tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#modalPromptContext .modal-tab-pane").forEach(p => p.style.display = "none");
  const firstTabBtn = document.querySelector('#modalPromptContext .modal-tab-btn[data-tab="tabAuditVisualBible"]');
  if (firstTabBtn) firstTabBtn.classList.add("active");
  const firstPane = document.getElementById("tabAuditVisualBible");
  if (firstPane) firstPane.style.display = "block";

  modal.style.display = "flex";
}

async function previewPromptContext(chunkId, beatData = null) {
  if (!currentSlug) return;
  try {
    let url = `/api/project/${currentSlug}/prompt_context_preview`;
    let options = {};
    if (beatData) {
      options = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunk_id: chunkId, beat: beatData })
      };
    } else {
      url += `?chunk_id=${encodeURIComponent(chunkId)}`;
    }
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok || (!data.success && data.status !== "ok")) {
      showToast(data.error || "Failed to load context preview", "error");
      return;
    }
    const ctx = data.preview || (Array.isArray(data.previews) ? data.previews[0] : null);
    if (ctx) {
      openPromptContextModal(ctx, chunkId);
    } else {
      showToast("No context available for this beat.", "warning");
    }
  } catch (err) {
    console.error("Preview prompt context error:", err);
    showToast("Error loading context preview: " + err, "error");
  }
}

async function loadPreGenReviewMatrix(container) {
  try {
    const res = await fetch(`/api/project/${currentSlug}/prompt_context_preview`);
    if (!res.ok) return false;
    const data = await res.json();
    const previews = data.previews || data.preview || [];
    if (!Array.isArray(previews) || previews.length === 0) return false;

    let bannerHtml = `
      <div class="pregen-review-banner">
        <div style="font-weight: 600; font-size: 1.05rem; margin-bottom: 4px;">
          &#128203; Pre-Generation Context Review Matrix (${previews.length} visual beats pending synthesis)
        </div>
        <div style="font-size: 0.85rem; opacity: 0.9;">
          Review resolved character Base DNA, active timeline tags, scene attire overrides, and setting environments before generating prompts.
        </div>
      </div>
      <div class="pregen-grid">
    `;

    previews.forEach((ctx, idx) => {
      const cid = ctx.chunk_id;
      const badgesHtml = renderContinuityBadgesRow(ctx);

      bannerHtml += `
        <div class="card pregen-card" style="display: flex; flex-direction: column; justify-content: space-between;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <span class="chunk-id">${escapeHtml(cid)}</span>
              <span class="badge badge-accent">${escapeHtml(ctx.scene_type || "landscape")}</span>
            </div>
            <p style="font-size: 0.88rem; margin: 0 0 8px 0;"><strong>Action Beat:</strong> ${escapeHtml(ctx.action_beat || "N/A")}</p>
            <div style="margin-bottom: 10px;">
              ${badgesHtml}
            </div>
          </div>
          <div style="margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; text-align: right;">
            <button class="btn btn-sm btn-secondary btn-pregen-inspect" data-index="${idx}">&#128065; View Exact Prompt Payload</button>
          </div>
        </div>
      `;
    });

    bannerHtml += `</div>`;
    container.innerHTML = bannerHtml;

    container.querySelectorAll(".btn-pregen-inspect").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.index);
        const ctx = previews[idx];
        if (ctx) {
          openPromptContextModal(ctx, ctx.chunk_id);
        }
      });
    });

    return true;
  } catch (e) {
    console.error("Failed to load pregen review matrix:", e);
    return false;
  }
}

// ----------------------------------------------------------------------------
// Tab 4: Manifest & Prompts
// ----------------------------------------------------------------------------
function renderManifestBlocks() {
  const container = document.getElementById("manifestBlocksContainer");
  if (!container || !currentManifest) return;
  container.innerHTML = "";

  const filterIllustratedOnly = document.getElementById("chkShowIllustratedOnly")?.checked ?? true;
  const blocks = currentManifest.blocks || [];
  const illustratedBlocks = blocks.filter(b => b.illustration);

  if (filterIllustratedOnly && illustratedBlocks.length === 0) {
    loadPreGenReviewMatrix(container).then(loaded => {
      if (!loaded) {
        container.innerHTML = `<div class="card"><p>No visual beats or illustrated blocks in manifest yet. Complete Step 3 (Visual Beats) and click <strong>Synthesize Prompts</strong>, or uncheck <strong>Show Illustrated Blocks Only</strong> above to view all story blocks.</p></div>`;
      }
    });
    return;
  }

  blocks.forEach(block => {
    const cid = block.chunk_id;
    const illus = block.illustration;

    if (!illus && filterIllustratedOnly) {
      return;
    }

    const card = document.createElement("div");
    card.className = `manifest-block-card ${illus ? "has-illustration" : ""}`;
    card.dataset.chunkId = cid;

    if (!illus) {
      card.innerHTML = `
        <div class="card-header">
          <span class="chunk-id">${escapeHtml(cid)}</span>
          <span class="badge">Text Only</span>
        </div>
        <p class="chunk-text" style="color: var(--text-dim);">${escapeHtml(block.text)}</p>
      `;
    } else {
      const isCompleted = illus.status === "completed";
      const badgesHtml = renderContinuityBadgesRow(illus.llm_context);
      card.innerHTML = `
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="chunk-id">${escapeHtml(cid)}</span>
            <button class="btn btn-sm btn-secondary btn-audit-context" data-chunk-id="${escapeHtml(cid)}" title="Audit Visual Bible context sent to LLM for this prompt">&#128269; Context Audit</button>
          </div>
          <div>
            <span class="badge ${isCompleted ? 'badge-online' : 'badge-accent'}">${illus.status.toUpperCase()}</span>
            <span class="badge">${illus.width}x${illus.height}</span>
          </div>
        </div>
        <p class="chunk-text" style="margin-bottom: 10px;">${escapeHtml(block.text)}</p>
        ${badgesHtml}
        <div class="form-group" style="margin-top: 10px;">
          <label>Positive Prompt:</label>
          <textarea class="textarea-input manifest-prompt" rows="3">${escapeHtml(illus.prompt || "")}</textarea>
        </div>
        <div class="form-group">
          <label>Negative Prompt:</label>
          <input type="text" class="text-input manifest-neg-prompt" value="${escapeHtml(illus.negative_prompt || '')}">
        </div>
      `;
    }

    container.appendChild(card);
  });

  container.querySelectorAll(".btn-audit-context").forEach(btn => {
    btn.addEventListener("click", () => {
      const cid = btn.dataset.chunkId;
      const blk = (currentManifest?.blocks || []).find(b => b.chunk_id === cid);
      if (blk && blk.illustration && blk.illustration.llm_context) {
        openPromptContextModal(blk.illustration.llm_context, cid);
      } else {
        previewPromptContext(cid);
      }
    });
  });
}

async function loadManifest() {
  const container = document.getElementById("manifestBlocksContainer");
  const gallery = document.getElementById("imagesGallery");
  container.innerHTML = "";
  gallery.innerHTML = "";

  try {
    const res = await fetch(`/api/project/${currentSlug}/artifact/manifest`);
    if (!res.ok) {
      const hasPregen = await loadPreGenReviewMatrix(container);
      if (!hasPregen) {
        container.innerHTML = `<div class="card"><p>No manifest.json yet. Complete Steps 1-3 and click <strong>Synthesize Prompts</strong>.</p></div>`;
      }
      return;
    }

    currentManifest = await res.json();
    renderManifestBlocks();

    // Render in Image Gallery Tab (Tab 5)
    const blocks = currentManifest.blocks || [];
    const activeWf = document.getElementById("selectWorkflow")?.value || currentManifest.active_workflow || "sdxl_base.json";

    blocks.filter(b => b.illustration).forEach(block => {
      const cid = block.chunk_id;
      const illus = (block.illustrations && block.illustrations[activeWf])
        ? block.illustrations[activeWf]
        : block.illustration;
      const isCompleted = illus.status === "completed";
      const isChecked = selectedImageChunks.has(cid);

      const imgCard = document.createElement("div");
      imgCard.className = `image-card ${isChecked ? "selected" : ""}`;
      imgCard.dataset.chunkId = cid;
      const relImgPath = illus.image_file ? illus.image_file.replace(/^images\//, "") : `${cid}.png`;
      const imgSrc = `/api/project/${currentSlug}/images/${encodeURI(relImgPath)}?t=${Date.now()}`;

      imgCard.innerHTML = `
        <div class="image-card-preview">
          <input type="checkbox" class="img-card-checkbox" data-chunk-id="${cid}" ${isChecked ? "checked" : ""} title="Select for regeneration">
          ${isCompleted
            ? `<img src="${imgSrc}" alt="${cid}" onerror="this.parentElement.innerHTML='<div class=\\'image-placeholder\\'>Rendered file not found on disk</div>'">`
            : `<div class="image-placeholder">&#9654; Ready to Render (${illus.width || 1344}x${illus.height || 768})</div>`}
        </div>
        <div class="image-card-body">
          <div class="card-header" style="margin-bottom: 4px;">
            <span class="chunk-id">${cid}</span>
            <span class="badge ${isCompleted ? 'badge-online' : 'badge-accent'}">${illus.status}</span>
          </div>
          <p style="font-size: 0.82rem; color: var(--text-dim); line-height: 1.35; flex-grow: 1;">${escapeHtml(illus.prompt || "")}</p>
          <div style="margin-top: 10px; display: flex; gap: 8px;">
            <button class="btn btn-sm btn-primary btn-tweak-rerun" data-chunk-id="${cid}">
              ${isCompleted ? '&#8635; Tweak &amp; Regenerate' : '&#9654; Render Scene'}
            </button>
            <button class="btn btn-sm btn-secondary btn-gallery-audit" data-chunk-id="${cid}" title="Inspect Visual Bible Context Audit">
              &#128269; Context
            </button>
          </div>
        </div>
      `;

      const chk = imgCard.querySelector(".img-card-checkbox");
      chk.addEventListener("change", (e) => {
        e.stopPropagation();
        if (chk.checked) {
          selectedImageChunks.add(cid);
        } else {
          selectedImageChunks.delete(cid);
        }
        updateSelectedImagesUI();
      });

      imgCard.querySelector(".btn-tweak-rerun").addEventListener("click", () => {
        openTweakModal(block);
      });

      imgCard.querySelector(".btn-gallery-audit")?.addEventListener("click", () => {
        if (illus && illus.llm_context) {
          openPromptContextModal(illus.llm_context, cid);
        } else {
          previewPromptContext(cid);
        }
      });

      gallery.appendChild(imgCard);
    });
    updateSelectedImagesUI();

  } catch (err) {
    console.error("Manifest load error:", err);
  }
}

async function saveManifest() {
  if (!currentManifest) return;
  const cards = document.querySelectorAll(".manifest-block-card.has-illustration");
  cards.forEach(c => {
    const cid = c.dataset.chunkId;
    const prompt = c.querySelector(".manifest-prompt").value.trim();
    const negPrompt = c.querySelector(".manifest-neg-prompt").value.trim();

    const block = currentManifest.blocks.find(b => b.chunk_id === cid);
    if (block && block.illustration) {
      block.illustration.prompt = prompt;
      block.illustration.negative_prompt = negPrompt;
    }
  });

  try {
    const res = await fetch(`/api/project/${currentSlug}/artifact/manifest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentManifest)
    });
    if (res.ok) {
      showToast("Master Manifest updated!");
      await loadManifest();
    }
  } catch (err) {
    showToast("Failed to save manifest: " + err, "error");
  }
}

// ----------------------------------------------------------------------------
// Phase 2: Render & Regenerate Modal
// ----------------------------------------------------------------------------
function openTweakModal(block) {
  currentTweakBlock = block;
  const activeWf = document.getElementById("selectWorkflow")?.value || currentManifest?.active_workflow || "sdxl_base.json";
  const illus = (block.illustrations && block.illustrations[activeWf]) ? block.illustrations[activeWf] : block.illustration;
  document.getElementById("tweakChunkId").textContent = block.chunk_id;
  document.getElementById("tweakPrompt").value = illus.prompt || "";
  document.getElementById("tweakNegativePrompt").value = illus.negative_prompt || "";
  document.getElementById("tweakWidth").value = illus.width || 1344;
  document.getElementById("tweakHeight").value = illus.height || 768;
  document.getElementById("tweakSeed").value = illus.seed || "";
  document.getElementById("modalTweakRerun").style.display = "flex";
}

async function submitTweakRerun() {
  const cid = document.getElementById("tweakChunkId").textContent;
  const prompt = document.getElementById("tweakPrompt").value.trim();
  const negPrompt = document.getElementById("tweakNegativePrompt").value.trim();
  const width = parseInt(document.getElementById("tweakWidth").value);
  const height = parseInt(document.getElementById("tweakHeight").value);
  const seed = document.getElementById("tweakSeed").value ? parseInt(document.getElementById("tweakSeed").value) : null;
  const wf = document.getElementById("selectWorkflow").value;

  document.getElementById("modalTweakRerun").style.display = "none";
  showToast(`Rendering ${cid} [${wf}] in ComfyUI...`);

  try {
    const res = await fetch(`/api/project/${currentSlug}/rerun`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chunk_id: cid,
        prompt: prompt,
        negative_prompt: negPrompt,
        width: width,
        height: height,
        seed: seed,
        workflow: wf
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Successfully rendered ${cid}!`, "success");
      await loadManifest();
      loadReaderPreview(wf);
    } else {
      showToast("Rendering error: " + data.error, "error");
    }
  } catch (err) {
    showToast("Network error: " + err, "error");
  }
}

async function startBatchRender() {
  const wf = document.getElementById("selectWorkflow").value;
  const blocks = (currentManifest?.blocks || []).filter(b => b.illustration);
  const pendingCount = blocks.filter(b => {
    const illus = (b.illustrations && b.illustrations[wf]) ? b.illustrations[wf] : b.illustration;
    return !illus || illus.status !== "completed";
  }).length;

  let forceAll = false;
  if (pendingCount === 0 && blocks.length > 0) {
    if (!confirm(`All illustrations for workflow '${wf}' are already completed. Re-render all scenes with fresh seeds?`)) {
      return;
    }
    forceAll = true;
  }

  const pbox = document.getElementById("renderProgressBox");
  pbox.style.display = "block";
  document.getElementById("renderStatusText").innerHTML = `<span class="spinner"></span> Dispatching batch to ComfyUI [${wf}]...`;
  document.getElementById("renderProgressBar").style.width = "20%";

  try {
    const res = await fetch(`/api/project/${currentSlug}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow: wf, force_all: forceAll })
    });
    const data = await res.json();
    if (data.success) {
      document.getElementById("renderProgressBar").style.width = "100%";
      document.getElementById("renderStatusText").textContent = "Batch render completed!";
      showToast("All illustrations completed successfully!");
      selectedImageChunks.clear();
      await loadManifest();
      loadReaderPreview(wf);
    } else {
      document.getElementById("renderStatusText").textContent = "Render stopped with error.";
      showToast("Render error: " + data.error, "error");
    }
  } catch (err) {
    showToast("Render network error: " + err, "error");
  } finally {
    setTimeout(() => { pbox.style.display = "none"; }, 5000);
  }
}

async function regenerateSelectedImages() {
  if (selectedImageChunks.size === 0) return;
  const wf = document.getElementById("selectWorkflow").value;
  const chunkIds = Array.from(selectedImageChunks);

  const pbox = document.getElementById("renderProgressBox");
  pbox.style.display = "block";
  document.getElementById("renderStatusText").innerHTML = `<span class="spinner"></span> Regenerating ${chunkIds.length} scene(s) [${wf}]...`;
  document.getElementById("renderProgressBar").style.width = "25%";

  try {
    const res = await fetch(`/api/project/${currentSlug}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow: wf, chunk_ids: chunkIds })
    });
    const data = await res.json();
    if (data.success) {
      document.getElementById("renderProgressBar").style.width = "100%";
      document.getElementById("renderStatusText").textContent = `Regenerated ${chunkIds.length} scene(s)!`;
      showToast(`Successfully regenerated ${chunkIds.length} scene(s)!`);
      selectedImageChunks.clear();
      await loadManifest();
      loadReaderPreview(wf);
    } else {
      document.getElementById("renderStatusText").textContent = "Regeneration stopped with error.";
      showToast("Regeneration error: " + data.error, "error");
    }
  } catch (err) {
    showToast("Network error: " + err, "error");
  } finally {
    setTimeout(() => { pbox.style.display = "none"; }, 5000);
  }
}

// ----------------------------------------------------------------------------
// Phase 3: Reader Preview
// ----------------------------------------------------------------------------
function loadReaderPreview(targetWf = null) {
  if (!currentSlug) return;
  const iframe = document.getElementById("readerIframe");
  const wfSelect = document.getElementById("readerWorkflowSelect");

  const availableWorkflows = new Set();
  if (currentManifest) {
    if (currentManifest.active_workflow) availableWorkflows.add(currentManifest.active_workflow);
    (currentManifest.blocks || []).forEach(b => {
      if (b.illustrations && typeof b.illustrations === "object") {
        Object.keys(b.illustrations).forEach(k => availableWorkflows.add(k));
      }
      if (b.illustration && b.illustration.workflow) {
        availableWorkflows.add(b.illustration.workflow);
      }
    });
  }
  if (availableWorkflows.size === 0) {
    availableWorkflows.add("sdxl_base.json");
  }

  if (wfSelect) {
    const currentVal = targetWf || wfSelect.value || currentManifest?.active_workflow || "sdxl_base.json";
    wfSelect.innerHTML = "";
    Array.from(availableWorkflows).sort().forEach(wf => {
      const opt = document.createElement("option");
      opt.value = wf;
      const count = (currentManifest?.blocks || []).filter(b => {
        const ill = b.illustrations?.[wf] || (b.illustration?.workflow === wf ? b.illustration : null);
        return ill && ill.status === "completed";
      }).length;
      opt.textContent = `${wf} (${count} images)`;
      wfSelect.appendChild(opt);
    });

    if (Array.from(wfSelect.options).some(o => o.value === currentVal)) {
      wfSelect.value = currentVal;
    } else if (wfSelect.options.length > 0) {
      wfSelect.value = wfSelect.options[0].value;
    }
  }

  const selectedWf = wfSelect?.value || targetWf || "";
  const wfParam = selectedWf ? `&workflow=${encodeURIComponent(selectedWf)}` : "";
  const url = `/api/project/${currentSlug}/reader?t=${Date.now()}${wfParam}`;
  if (iframe) iframe.src = url;

  // Portable HTML download removed in favor of professional PDF / FXL EPUB / Reflowable EPUB exports
}

// ----------------------------------------------------------------------------
// Ebook Retailer Metadata & Multi-Format Book Exporters
// ----------------------------------------------------------------------------
let pendingExportFormat = null;
let currentProjectMetadata = null;

async function fetchProjectMetadata() {
  if (!currentSlug) return null;
  try {
    const res = await fetch(`/api/project/${currentSlug}/metadata`);
    const data = await res.json();
    if (data.success) {
      currentProjectMetadata = data.metadata;
      return currentProjectMetadata;
    }
  } catch (err) {
    console.error("Failed to fetch project metadata", err);
  }
  return null;
}

async function openMetadataModal(formatToDownloadAfter = null) {
  pendingExportFormat = formatToDownloadAfter;
  const meta = await fetchProjectMetadata();

  document.getElementById("metaBookTitle").value = meta?.title || currentManifest?.story_title || currentSlug || "";
  document.getElementById("metaBookAuthor").value = meta?.author && meta.author !== "Author Unknown" ? meta.author : "";
  document.getElementById("metaBookPublisher").value = meta?.publisher || "Self-Published";
  document.getElementById("metaBookLanguage").value = meta?.language || "en";
  document.getElementById("metaBookIsbn").value = meta?.isbn || "";
  document.getElementById("metaBookDescription").value = meta?.description || "";

  const btnSaveExport = document.getElementById("btnSaveAndExport");
  const btnSaveOnly = document.getElementById("btnSaveMetadata");
  if (formatToDownloadAfter) {
    btnSaveExport.style.display = "inline-flex";
    btnSaveExport.textContent = `Save & Download ${formatToDownloadAfter.replace('_', ' ').toUpperCase()}`;
    btnSaveOnly.style.display = "none";
  } else {
    btnSaveExport.style.display = "none";
    btnSaveOnly.style.display = "inline-flex";
  }

  document.getElementById("modalEbookMetadata").style.display = "flex";
}

function closeMetadataModal() {
  document.getElementById("modalEbookMetadata").style.display = "none";
  pendingExportFormat = null;
}

async function saveMetadata(andDownload = false) {
  const title = document.getElementById("metaBookTitle").value.trim();
  const author = document.getElementById("metaBookAuthor").value.trim();
  if (!title || !author) {
    showToast("Book Title and Author are required for publication metadata.", "error");
    return false;
  }

  const payload = {
    title: title,
    author: author,
    publisher: document.getElementById("metaBookPublisher").value.trim() || "Self-Published",
    language: document.getElementById("metaBookLanguage").value.trim() || "en",
    isbn: document.getElementById("metaBookIsbn").value.trim(),
    description: document.getElementById("metaBookDescription").value.trim()
  };

  try {
    const res = await fetch(`/api/project/${currentSlug}/metadata`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      currentProjectMetadata = data.metadata;
      showToast("Publication metadata saved!");
      const formatToExport = pendingExportFormat;
      closeMetadataModal();
      if (andDownload && formatToExport) {
        executeDownload(formatToExport);
      }
      return true;
    } else {
      showToast("Failed to save metadata: " + data.error, "error");
      return false;
    }
  } catch (err) {
    showToast("Error saving metadata: " + err, "error");
    return false;
  }
}

async function triggerBookExport(format) {
  if (!currentSlug) {
    showToast("Please select a story project first.", "error");
    return;
  }
  const meta = await fetchProjectMetadata();
  if (!meta || !meta.author || meta.author === "Author Unknown") {
    openMetadataModal(format);
  } else {
    executeDownload(format);
  }
}

function executeDownload(format) {
  const wfSelect = document.getElementById("readerWorkflowSelect");
  const selectedWf = wfSelect?.value || "";
  const wfParam = selectedWf ? `?workflow=${encodeURIComponent(selectedWf)}` : "";
  const downloadUrl = `/api/project/${currentSlug}/export/${format}${wfParam}`;

  showToast(`Preparing ${format.replace('_', ' ').toUpperCase()} export...`);
  const a = document.createElement("a");
  a.href = downloadUrl;
  a.setAttribute("download", "");
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function compileReader() {
  try {
    const res = await fetch(`/api/project/${currentSlug}/compile`, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("index.html compiled successfully!");
      loadReaderPreview();
    } else {
      showToast("Compilation failed: " + data.error, "error");
    }
  } catch (err) {
    showToast("Error: " + err, "error");
  }
}

// ----------------------------------------------------------------------------
// Stage Execution with Continuous Progress & Button Disabling
// ----------------------------------------------------------------------------
const stageElements = {
  chunk: { btn: "btnRunChunker", box: "chunkProgressBox", msg: "chunkProgressMsg" },
  bible: { btn: "btnRunBible", box: "bibleProgressBox", msg: "bibleProgressMsg" },
  beats: { btn: "btnRunBeats", box: "beatsProgressBox", msg: "beatsProgressMsg" },
  manifest: { btn: "btnRunManifest", box: "manifestProgressBox", msg: "manifestProgressMsg" }
};

async function triggerStage(stageName, label) {
  if (!currentSlug) {
    const sel = document.getElementById("projectSelect");
    if (sel && sel.value) currentSlug = sel.value;
  }
  if (!currentSlug) {
    showToast("No story selected in the dropdown. Please select or create a story first.", "error");
    return;
  }

  const el = stageElements[stageName] || {};
  const btn = el.btn ? document.getElementById(el.btn) : null;
  const box = el.box ? document.getElementById(el.box) : null;
  const msgEl = el.msg ? document.getElementById(el.msg) : null;

  // Extract active model, temperature, and system prompt for this stage
  let activeModel = "";
  let activeTemp = null;
  let activePrompt = "";

  if (stageName === "bible") {
    activeModel = getActiveRoleModel("modelStructuredAnalyst", "modelStructuredAnalystCustom");
    activeTemp = parseFloat(document.getElementById("tempAnalyst")?.value || 0.2);
    activePrompt = document.getElementById("promptAnalyst")?.value || "";
  } else if (stageName === "beats") {
    activeModel = getActiveRoleModel("modelNarrativeDirector", "modelNarrativeDirectorCustom");
    activeTemp = parseFloat(document.getElementById("tempNarrative")?.value || 0.3);
    activePrompt = document.getElementById("promptNarrative")?.value || "";
  } else if (stageName === "manifest") {
    activeModel = getActiveRoleModel("modelPromptSynthesizer", "modelPromptSynthesizerCustom");
    activeTemp = parseFloat(document.getElementById("tempSynth")?.value || 0.35);
    activePrompt = document.getElementById("promptSynth")?.value || "";
  }

  if (btn) {
    btn.disabled = true;
    btn.dataset.origText = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span> Running...`;
  }
  if (box && msgEl) {
    box.style.display = "flex";
    const modelDisplay = activeModel ? ` using model '${activeModel}'` : "";
    msgEl.textContent = `Connecting to LM Studio and executing ${label}${modelDisplay}... Please wait.`;
  }

  showToast(`Running ${label}...`);

  // Progress polling interval
  const pollTimer = setInterval(async () => {
    try {
      const pRes = await fetch(`/api/project/${currentSlug}/stage_progress`);
      if (pRes.ok) {
        const pData = await pRes.json();
        if (pData.message && msgEl) {
          msgEl.textContent = pData.message;
        }
      }
    } catch (e) {}
  }, 800);

  try {
    const res = await fetch(`/api/project/${currentSlug}/run_stage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stage: stageName,
        model: activeModel,
        temperature: activeTemp,
        system_prompt: activePrompt
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`${label} completed successfully!`);
      if (msgEl) msgEl.textContent = `✓ ${label} completed successfully!`;
      await loadProjectData(currentSlug);
    } else {
      showToast(`${label} error: ${data.error}`, "error");
      if (msgEl) msgEl.textContent = `⚠ ${label} error: ${data.error}`;
    }
  } catch (err) {
    showToast(`Network error: ${err}`, "error");
    if (msgEl) msgEl.textContent = `⚠ Network error: ${err}`;
  } finally {
    clearInterval(pollTimer);
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = btn.dataset.origText || btn.innerHTML;
    }
    setTimeout(() => {
      if (box) box.style.display = "none";
    }, 4000);
  }
}

// ----------------------------------------------------------------------------
// Event Listeners Setup
// ----------------------------------------------------------------------------
function setupEventListeners() {
  // Tab switching
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.add("active");
      updateHardwareBanner();
    });
  });

  // Project select change
  document.getElementById("projectSelect").addEventListener("change", e => {
    loadProjectData(e.target.value);
  });

  // Refresh status
  document.getElementById("btnRefreshStatus").addEventListener("click", refreshStatus);

  // Temperature sliders
  document.getElementById("tempNarrative").addEventListener("input", e => {
    document.getElementById("tempNarrativeVal").textContent = e.target.value;
  });
  document.getElementById("tempAnalyst").addEventListener("input", e => {
    document.getElementById("tempAnalystVal").textContent = e.target.value;
  });
  document.getElementById("tempSynth").addEventListener("input", e => {
    document.getElementById("tempSynthVal").textContent = e.target.value;
  });

  // Dropdown sync to custom text & auto-save
  ["NarrativeDirector", "StructuredAnalyst", "PromptSynthesizer"].forEach(role => {
    const sel = document.getElementById(`model${role}`);
    const custom = document.getElementById(`model${role}Custom`);
    if (sel && custom) {
      sel.addEventListener("change", e => {
        if (e.target.value) {
          custom.value = e.target.value;
          saveCurrentLLMConfig();
        }
      });
      custom.addEventListener("change", () => {
        saveCurrentLLMConfig();
      });
    }
  });

  // In-tab model save buttons
  document.getElementById("btnSaveAnalystConfig").addEventListener("click", saveCurrentLLMConfig);
  document.getElementById("btnSaveDirectorConfig").addEventListener("click", saveCurrentLLMConfig);
  document.getElementById("btnSaveSynthConfig").addEventListener("click", async () => {
    await saveCurrentLLMConfig();
    await saveDiffusionConfig();
  });

  // Artifact save buttons
  document.getElementById("btnSaveBeats").addEventListener("click", () => saveBeatsArray(collectBeatsFromUI()));
  document.getElementById("btnSaveBible").addEventListener("click", saveBible);
  document.getElementById("btnSaveManifest").addEventListener("click", saveManifest);

  // Filter toggle for Manifest Prompts tab
  const chkShowOnly = document.getElementById("chkShowIllustratedOnly");
  if (chkShowOnly) {
    chkShowOnly.addEventListener("change", renderManifestBlocks);
  }

  // Stage execution buttons
  document.getElementById("btnRunChunker").addEventListener("click", () => triggerStage("chunk", "Chunker"));
  document.getElementById("btnRunBible").addEventListener("click", () => triggerStage("bible", "Visual Bible Extraction"));
  document.getElementById("btnRunBeats").addEventListener("click", () => triggerStage("beats", "Beat Selection"));
  document.getElementById("btnRunManifest").addEventListener("click", () => triggerStage("manifest", "Prompt Synthesis"));

  // Batch render & compile
  document.getElementById("btnStartBatchRender").addEventListener("click", startBatchRender);

  // Mass selection controls
  const btnToggleAll = document.getElementById("btnToggleSelectAll");
  if (btnToggleAll) {
    btnToggleAll.addEventListener("click", () => {
      const totalIllustrated = (currentManifest?.blocks || []).filter(b => b.illustration);
      if (selectedImageChunks.size === totalIllustrated.length && totalIllustrated.length > 0) {
        selectedImageChunks.clear();
      } else {
        totalIllustrated.forEach(b => selectedImageChunks.add(b.chunk_id));
      }
      updateSelectedImagesUI();
      document.querySelectorAll(".img-card-checkbox").forEach(chk => {
        chk.checked = selectedImageChunks.has(chk.dataset.chunkId);
      });
    });
  }

  const btnRegenSel = document.getElementById("btnRegenerateSelected");
  if (btnRegenSel) {
    btnRegenSel.addEventListener("click", regenerateSelectedImages);
  }

  // Workflow switcher in Tab 5 to refresh gallery
  const selWf = document.getElementById("selectWorkflow");
  if (selWf) {
    selWf.addEventListener("change", () => {
      if (currentManifest) {
        loadManifest();
      }
    });
  }

  // Workflow switcher in Tab 6 reader preview
  const readerWfSel = document.getElementById("readerWorkflowSelect");
  if (readerWfSel) {
    readerWfSel.addEventListener("change", (e) => {
      loadReaderPreview(e.target.value);
    });
  }

  // Export buttons & Metadata Modal Event Listeners
  const btnExpPdf = document.getElementById("btnExportPdf");
  if (btnExpPdf) btnExpPdf.addEventListener("click", () => triggerBookExport("pdf"));

  const btnExpFxl = document.getElementById("btnExportFxl");
  if (btnExpFxl) btnExpFxl.addEventListener("click", () => triggerBookExport("fxl_epub"));

  const btnExpReflow = document.getElementById("btnExportReflowable");
  if (btnExpReflow) btnExpReflow.addEventListener("click", () => triggerBookExport("reflowable_epub"));

  const btnEditMeta = document.getElementById("btnEditEbookMetadata");
  if (btnEditMeta) btnEditMeta.addEventListener("click", () => openMetadataModal(null));

  const btnCloseMeta = document.getElementById("btnCloseMetadataModal");
  if (btnCloseMeta) btnCloseMeta.addEventListener("click", closeMetadataModal);

  const btnCancelMeta = document.getElementById("btnCancelMetadata");
  if (btnCancelMeta) btnCancelMeta.addEventListener("click", closeMetadataModal);

  const btnSaveMeta = document.getElementById("btnSaveMetadata");
  if (btnSaveMeta) btnSaveMeta.addEventListener("click", () => saveMetadata(false));

  const btnSaveExp = document.getElementById("btnSaveAndExport");
  if (btnSaveExp) btnSaveExp.addEventListener("click", () => saveMetadata(true));

  // Active diffusion profile switcher in Tab 4
  const activeProfSel = document.getElementById("activeProfileSelect");
  if (activeProfSel) {
    activeProfSel.addEventListener("change", async () => {
      try {
        const res = await fetch(`/api/project/${currentSlug}/config/diffusion`);
        const cfg = await res.json();
        const profiles = cfg.profiles || {};
        const curProfile = profiles[activeProfSel.value] || {};
        document.getElementById("profileNegativePrompt").value = curProfile.default_negative || "";
        const prefixEl = document.getElementById("profilePositivePrefix");
        if (prefixEl) prefixEl.value = curProfile.positive_prefix || "";
      } catch (err) {}
    });
  }

  // Save source text
  document.getElementById("btnSaveSource").addEventListener("click", async () => {
    if (!currentSlug) {
      const sel = document.getElementById("projectSelect");
      if (sel && sel.value) currentSlug = sel.value;
    }
    if (!currentSlug) {
      showToast("No story selected. Please create or select a story first.", "error");
      return;
    }
    const text = document.getElementById("sourceStoryText").value;
    const res = await fetch(`/api/project/${currentSlug}/source`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    if (res.ok) showToast("Raw story text saved!");
  });

  // Add items
  document.getElementById("btnAddBeat").addEventListener("click", () => {
    const beats = collectBeatsFromUI();
    beats.push({
      chunk_id: `chunk_${String(beats.length).padStart(3, "0")}`,
      scene_type: "landscape",
      characters_present: [],
      character_attire: {},
      setting: "",
      action_beat: "New scene action",
      camera_framing: "Cinematic medium shot"
    });
    saveBeatsArray(beats);
  });

  document.getElementById("btnAddCharacter").addEventListener("click", () => {
    const list = document.getElementById("charactersList");
    const item = document.createElement("div");
    item.className = "bible-item-card";
    item.dataset.timelineMods = "[]";
    item.dataset.wardrobeTimeline = "[]";
    item.dataset.altAttires = "{}";
    item.innerHTML = `
      <div class="card-header">
        <input type="text" class="text-input char-name-input" placeholder="Character Name" style="font-weight: 600; width: 60%;">
        <button class="btn btn-sm btn-danger btn-del-char">&times;</button>
      </div>
      <div style="margin-top: 6px;">
        <label style="font-size: 0.75rem; color: var(--text-dim); display: block; margin-bottom: 2px;">Physical Base DNA (Face, hair, build, permanent features):</label>
        <textarea class="textarea-input char-desc-input char-dna-input" rows="2" placeholder="e.g. Woman in early 30s, sharp angular jawline, dark braided raven hair, grey eyes..."></textarea>
      </div>
      <div style="margin-top: 6px;">
        <label style="font-size: 0.75rem; color: var(--text-dim); display: block; margin-bottom: 2px;">Default / Everyday Attire:</label>
        <input type="text" class="text-input char-attire-input" placeholder="e.g. Weathered brown leather aviator jacket, utility cargo trousers">
      </div>
    `;
    item.querySelector(".btn-del-char").addEventListener("click", () => item.remove());
    list.prepend(item);
  });

  document.getElementById("btnAddSetting").addEventListener("click", () => {
    const list = document.getElementById("settingsList");
    const item = document.createElement("div");
    item.className = "bible-item-card";
    item.innerHTML = `
      <div class="card-header">
        <input type="text" class="text-input setting-name-input" placeholder="Setting Name" style="font-weight: 600; width: 60%;">
        <button class="btn btn-sm btn-danger btn-del-setting">&times;</button>
      </div>
      <textarea class="textarea-input setting-desc-input" rows="3" placeholder="Architecture, atmosphere, lighting..."></textarea>
    `;
    item.querySelector(".btn-del-setting").addEventListener("click", () => item.remove());
    list.prepend(item);
  });

  // File handling for New Story (Drag & Drop + Native File Browser)
  function handleStoryFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
      const text = e.target.result;
      document.getElementById("newStoryText").value = text;

      // Derive story slug from filename
      let baseName = file.name.replace(/\.[^/.]+$/, "");
      let slug = baseName.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      if (!slug) slug = "my_story";
      document.getElementById("newStorySlug").value = slug;

      // Word count calculation
      const words = text.match(/\b[\w'-]+\b/g) || [];
      const wordCount = words.length;

      // Show loaded file info box
      const infoBox = document.getElementById("loadedFileInfo");
      const nameEl = document.getElementById("loadedFileName");
      const statsEl = document.getElementById("loadedFileStats");
      infoBox.style.display = "block";
      nameEl.textContent = `📄 ${file.name}`;
      statsEl.textContent = `${wordCount.toLocaleString()} words (${(file.size / 1024).toFixed(1)} KB)`;

      showToast(`Loaded "${file.name}" (${wordCount.toLocaleString()} words)`);
    };
    reader.readAsText(file, "UTF-8");
  }

  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileStoryInput");
  const btnBrowse = document.getElementById("btnBrowseFile");

  if (btnBrowse && fileInput) {
    btnBrowse.addEventListener("click", e => {
      e.stopPropagation();
      fileInput.click();
    });
  }

  if (dropZone && fileInput) {
    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", e => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", e => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", e => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
      if (e.dataTransfer && e.dataTransfer.files.length > 0) {
        handleStoryFile(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener("change", e => {
      if (e.target.files && e.target.files.length > 0) {
        handleStoryFile(e.target.files[0]);
      }
    });
  }

  // Global window drop support: dragging a file onto the window opens New Story modal
  window.addEventListener("dragover", e => {
    e.preventDefault();
  });

  window.addEventListener("drop", e => {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (file.name.endsWith(".txt") || file.name.endsWith(".md") || file.name.endsWith(".text")) {
        document.getElementById("modalNewProject").style.display = "flex";
        handleStoryFile(file);
      }
    }
  });

  // New Story modal
  document.getElementById("btnNewProject").addEventListener("click", () => {
    document.getElementById("modalNewProject").style.display = "flex";
  });
  document.getElementById("btnCloseModal").addEventListener("click", () => {
    document.getElementById("modalNewProject").style.display = "none";
  });
  document.getElementById("btnCancelNewProject").addEventListener("click", () => {
    document.getElementById("modalNewProject").style.display = "none";
  });
  document.getElementById("btnSubmitNewProject").addEventListener("click", async () => {
    let rawSlug = document.getElementById("newStorySlug").value.trim();
    let slug = rawSlug.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    if (!slug) slug = `story_${Date.now()}`;
    const text = document.getElementById("newStoryText").value;

    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, story_text: text })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      document.getElementById("modalNewProject").style.display = "none";
      showToast(`Created story: ${data.slug}`);
      await loadProjects(data.slug);
    } else {
      showToast("Error creating story: " + (data.error || "Unknown error"), "error");
    }
  });

  // Tweak & Regenerate modal
  document.getElementById("btnCloseTweakModal").addEventListener("click", () => {
    document.getElementById("modalTweakRerun").style.display = "none";
  });
  document.getElementById("btnCancelTweak").addEventListener("click", () => {
    document.getElementById("modalTweakRerun").style.display = "none";
  });
  document.getElementById("btnSubmitTweakRerun").addEventListener("click", submitTweakRerun);

  // Tweak modal Context Audit button
  const btnTweakAudit = document.getElementById("btnTweakContextAudit");
  if (btnTweakAudit) {
    btnTweakAudit.addEventListener("click", () => {
      if (!currentTweakBlock) return;
      const cid = currentTweakBlock.chunk_id;
      const activeWf = document.getElementById("selectWorkflow")?.value || currentManifest?.active_workflow || "sdxl_base.json";
      const illus = (currentTweakBlock.illustrations && currentTweakBlock.illustrations[activeWf])
        ? currentTweakBlock.illustrations[activeWf]
        : currentTweakBlock.illustration;
      if (illus && illus.llm_context) {
        openPromptContextModal(illus.llm_context, cid);
      } else {
        previewPromptContext(cid);
      }
    });
  }

  // Prompt Context & Visual Bible Audit modal
  document.querySelectorAll("#modalPromptContext .modal-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#modalPromptContext .modal-tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll("#modalPromptContext .modal-tab-pane").forEach(p => p.style.display = "none");
      btn.classList.add("active");
      const pane = document.getElementById(btn.dataset.tab);
      if (pane) pane.style.display = "block";
    });
  });

  const btnCloseContext = document.getElementById("btnClosePromptContextModal");
  if (btnCloseContext) {
    btnCloseContext.addEventListener("click", () => {
      document.getElementById("modalPromptContext").style.display = "none";
    });
  }
  const btnCloseContextBottom = document.getElementById("btnClosePromptContextBottom");
  if (btnCloseContextBottom) {
    btnCloseContextBottom.addEventListener("click", () => {
      document.getElementById("modalPromptContext").style.display = "none";
    });
  }

  const modalPromptContext = document.getElementById("modalPromptContext");
  if (modalPromptContext) {
    modalPromptContext.addEventListener("click", (e) => {
      if (e.target === modalPromptContext) {
        modalPromptContext.style.display = "none";
      }
    });
  }

  // Copy buttons
  function setupCopyBtn(btnId, getText) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener("click", async () => {
      const text = getText();
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        const originalText = btn.innerHTML;
        btn.innerHTML = "&#10004; Copied!";
        setTimeout(() => { btn.innerHTML = originalText; }, 1500);
      } catch (e) {
        showToast("Failed to copy to clipboard", "error");
      }
    });
  }

  setupCopyBtn("btnCopySystemPrompt", () => document.getElementById("auditSystemPrompt")?.value || "");
  setupCopyBtn("btnCopyUserPrompt", () => document.getElementById("auditUserPrompt")?.value || "");
  setupCopyBtn("btnCopyEntirePayload", () => currentAuditContext ? JSON.stringify(currentAuditContext, null, 2) : "");

  // Providers & API Settings modal
  const btnOpenProviders = document.getElementById("btnOpenProvidersModal");
  if (btnOpenProviders) {
    btnOpenProviders.addEventListener("click", openProvidersModal);
  }
  const btnCloseProviders = document.getElementById("btnCloseProvidersModal");
  if (btnCloseProviders) {
    btnCloseProviders.addEventListener("click", () => {
      document.getElementById("modalProviders").style.display = "none";
    });
  }
  const btnCancelProviders = document.getElementById("btnCancelProviders");
  if (btnCancelProviders) {
    btnCancelProviders.addEventListener("click", () => {
      document.getElementById("modalProviders").style.display = "none";
    });
  }
  const btnSaveProviders = document.getElementById("btnSaveProviders");
  if (btnSaveProviders) {
    btnSaveProviders.addEventListener("click", saveProvidersConfig);
  }
  const selImageBackend = document.getElementById("providerImageBackend");
  if (selImageBackend) {
    selImageBackend.addEventListener("change", e => toggleImageBackendSettings(e.target.value));
  }
}

async function openProvidersModal() {
  if (!currentSlug) return;
  try {
    const res = await fetch(`/api/project/${currentSlug}/config/providers`);
    const data = await res.json();

    const llm = data.llm || {};
    const img = data.image || {};

    const selLLMBackend = document.getElementById("providerLLMBackend");
    const inpLLMBase = document.getElementById("providerLLMBase");
    const inpLLMKey = document.getElementById("providerLLMKey");
    const inpLLMContext = document.getElementById("providerLLMContext");

    if (selLLMBackend) selLLMBackend.value = llm.backend || "lm_studio";
    if (inpLLMBase) inpLLMBase.value = llm.api_base || "http://localhost:1234/v1";
    if (inpLLMKey) inpLLMKey.value = llm.api_key || "";
    if (inpLLMContext) inpLLMContext.value = llm.context_window || 8192;

    const selImgBackend = document.getElementById("providerImageBackend");
    const inpComfyHost = document.getElementById("providerComfyHost");
    const inpImgBase = document.getElementById("providerImageBase");
    const inpImgKey = document.getElementById("providerImageKey");
    const inpImgModel = document.getElementById("providerImageModel");

    if (selImgBackend) {
      selImgBackend.value = img.backend || "comfyui";
      toggleImageBackendSettings(selImgBackend.value);
    }
    if (inpComfyHost) inpComfyHost.value = img.comfyui_host || "127.0.0.1:8188";
    if (inpImgBase) inpImgBase.value = img.openai_api_base || "https://api.openai.com/v1";
    if (inpImgKey) inpImgKey.value = img.api_key || "";
    if (inpImgModel) inpImgModel.value = img.model || "dall-e-3";

    document.getElementById("modalProviders").style.display = "flex";
  } catch (err) {
    showToast("Error loading provider settings: " + err, "error");
  }
}

function toggleImageBackendSettings(backend) {
  const comfyGroup = document.getElementById("comfySettingsGroup");
  const openaiGroup = document.getElementById("openaiImageSettingsGroup");
  if (backend === "openai_compatible") {
    if (comfyGroup) comfyGroup.style.display = "none";
    if (openaiGroup) openaiGroup.style.display = "block";
  } else {
    if (comfyGroup) comfyGroup.style.display = "block";
    if (openaiGroup) openaiGroup.style.display = "none";
  }
}

async function saveProvidersConfig() {
  if (!currentSlug) return;
  const llmBackend = document.getElementById("providerLLMBackend")?.value;
  const llmBase = document.getElementById("providerLLMBase")?.value?.trim();
  const llmKey = document.getElementById("providerLLMKey")?.value?.trim();
  const llmContext = parseInt(document.getElementById("providerLLMContext")?.value) || 8192;

  const imgBackend = document.getElementById("providerImageBackend")?.value;
  const comfyHost = document.getElementById("providerComfyHost")?.value?.trim();
  const imgBase = document.getElementById("providerImageBase")?.value?.trim();
  const imgKey = document.getElementById("providerImageKey")?.value?.trim();
  const imgModel = document.getElementById("providerImageModel")?.value?.trim();

  const payload = {
    llm: {
      backend: llmBackend,
      api_base: llmBase,
      api_key: llmKey,
      context_window: llmContext
    },
    image: {
      backend: imgBackend,
      comfyui_host: comfyHost,
      openai_api_base: imgBase,
      api_key: imgKey,
      model: imgModel
    }
  };

  try {
    const res = await fetch(`/api/project/${currentSlug}/config/providers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      document.getElementById("modalProviders").style.display = "none";
      showToast("Provider settings saved successfully!");
      await refreshStatus();
    } else {
      const err = await res.json();
      showToast("Failed to save providers: " + (err.error || "Unknown"), "error");
    }
  } catch (e) {
    showToast("Error saving provider settings: " + e, "error");
  }
}

// Start on DOM ready
document.addEventListener("DOMContentLoaded", init);
