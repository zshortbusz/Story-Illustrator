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
    btnRegen.innerHTML = `&#8635; Regenerate Selected (${count})`;
    btnRegen.disabled = count === 0;
  }
  const btnToggle = document.getElementById("btnToggleSelectAll");
  if (btnToggle) {
    const totalIllustrated = (currentManifest?.blocks || []).filter(b => b.illustration || (b.illustrations && Object.keys(b.illustrations).length > 0)).length;
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

async function loadResolutionTier() {
  const select = document.getElementById("selectResolutionTier");
  if (!select || !currentSlug) return;
  try {
    const res = await fetch(`/api/project/${encodeURIComponent(currentSlug)}/resolution-tier`);
    if (res.ok) {
      const data = await res.json();
      if (data && data.tier) {
        select.value = data.tier;
      }
    }
  } catch (err) {
    console.warn("Failed to load resolution tier:", err);
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
    loadProjectStyles(),
    loadResolutionTier()
  ]);
  await loadManifest();
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
    const rawPreviews = data.previews || data.preview || [];
    const previews = Array.isArray(rawPreviews) ? rawPreviews : [rawPreviews];
    if (previews.length === 0) return false;

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
// Style Presets & Universal Library Management (Tab 4 & Tab 5)
// ----------------------------------------------------------------------------
let currentProjectStyles = null;
let activeStyleSelection = null;

async function loadProjectStyles() {
  if (!currentSlug) return;
  try {
    const res = await fetch(`/api/project/${currentSlug}/styles`);
    if (!res.ok) return;
    const data = await res.json();
    currentProjectStyles = data;

    activeStyleSelection = data.active_style || null;

    // Update Tab 4 Header Badge & Active display
    const activeBadge = document.getElementById("activeStyleBadge");
    const activeCatLabel = document.getElementById("activeStyleCatLabel");
    const activeDescInput = document.getElementById("activeStyleDescriptionInput");

    if (activeStyleSelection) {
      if (activeBadge) activeBadge.textContent = activeStyleSelection.name || "Custom Style";
      if (activeCatLabel) activeCatLabel.textContent = activeStyleSelection.category === "photography" ? "Photography Era" : "Art Medium";
      if (activeDescInput) activeDescInput.value = activeStyleSelection.description || "";
    }

    const activeId = activeStyleSelection?.id || "";

    // Render Inferred Art Chips
    const artContainer = document.getElementById("artStyleChips");
    if (artContainer) {
      const artList = data.presets?.art || [];
      renderStyleChips(artContainer, artList, activeId, "art");
    }

    // Render Inferred Photo Chips
    const photoContainer = document.getElementById("photoStyleChips");
    if (photoContainer) {
      const photoList = data.presets?.photography || [];
      renderStyleChips(photoContainer, photoList, activeId, "photography");
    }

    // Render Global Library Chips
    const globalLib = data.global_library || { art: [], photography: [] };
    const globalCountEl = document.getElementById("globalLibraryCount");
    const totalGlobal = (globalLib.art || []).length + (globalLib.photography || []).length;
    if (globalCountEl) globalCountEl.textContent = `${totalGlobal} styles`;

    const globalArtContainer = document.getElementById("globalArtChips");
    if (globalArtContainer) {
      renderStyleChips(globalArtContainer, globalLib.art || [], activeId, "art");
    }

    const globalPhotoContainer = document.getElementById("globalPhotoChips");
    if (globalPhotoContainer) {
      renderStyleChips(globalPhotoContainer, globalLib.photography || [], activeId, "photography");
    }

    // Synchronize Tab 5 Style Selector Dropdown if manifest is loaded
    if (currentManifest) {
      syncRenderStyleDropdown();
    }

  } catch (err) {
    console.error("Styles load error:", err);
  }
}

function renderStyleChips(container, styles, activeId, defaultCat = "art") {
  container.innerHTML = "";
  if (!styles || styles.length === 0) {
    container.innerHTML = `<span style="font-size: 0.78rem; color: var(--text-dim); padding: 4px;">No presets yet. Click [+ Infer More] to generate.</span>`;
    return;
  }

  styles.forEach(s => {
    const chip = document.createElement("div");
    const isActive = s.id === activeId || (activeStyleSelection && activeStyleSelection.name === s.name);
    chip.className = `style-chip ${isActive ? "active" : ""}`;
    chip.dataset.styleId = s.id || "";
    chip.title = s.description || "";

    const previewText = (s.description || "").length > 40
      ? (s.description || "").slice(0, 37) + "..."
      : (s.description || "");

    chip.innerHTML = `
      <div class="style-chip-name">${escapeHtml(s.name)}</div>
      <div class="style-chip-preview">${escapeHtml(previewText)}</div>
    `;

    chip.addEventListener("click", () => {
      selectActiveStyle({
        id: s.id || s.name.toLowerCase().replace(/[^a-z0-9]+/g, "_"),
        name: s.name,
        description: s.description || "",
        category: s.category || defaultCat
      });
    });

    container.appendChild(chip);
  });
}

async function selectActiveStyle(styleObj) {
  if (!currentSlug || !styleObj) return;
  activeStyleSelection = styleObj;

  // Update UI indicators
  const activeBadge = document.getElementById("activeStyleBadge");
  const activeCatLabel = document.getElementById("activeStyleCatLabel");
  const activeDescInput = document.getElementById("activeStyleDescriptionInput");

  if (activeBadge) activeBadge.textContent = styleObj.name;
  if (activeCatLabel) activeCatLabel.textContent = styleObj.category === "photography" ? "Photography Era" : "Art Medium";
  if (activeDescInput) activeDescInput.value = styleObj.description || "";

  // Update active class on chips across containers
  document.querySelectorAll(".style-chip").forEach(chip => {
    if (chip.dataset.styleId === styleObj.id || chip.querySelector(".style-chip-name")?.textContent.trim() === styleObj.name) {
      chip.classList.add("active");
    } else {
      chip.classList.remove("active");
    }
  });

  // Sync with Tab 2 Visual Bible field if present
  const bibleArtInput = document.getElementById("bibleArtStyle");
  if (bibleArtInput && styleObj.description) {
    bibleArtInput.value = styleObj.description;
  }

  // Synchronize Tab 5 Style selector dropdown
  const renderStyleSelect = document.getElementById("selectRenderStyle");
  if (renderStyleSelect) {
    const optExists = Array.from(renderStyleSelect.options).some(o => o.value === styleObj.name);
    if (optExists) {
      renderStyleSelect.value = styleObj.name;
    } else {
      syncRenderStyleDropdown();
    }
  }

  // Immediately re-render Tab 4 manifest prompts for this active style
  if (currentManifest) {
    renderManifestBlocks();
    renderGalleryCards();
  }

  // Persist to backend
  try {
    const res = await fetch(`/api/project/${currentSlug}/styles/select`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        style_id: styleObj.id,
        style_name: styleObj.name,
        description: styleObj.description,
        category: styleObj.category
      })
    });
    if (res.ok) {
      showToast(`Active Style set to: ${styleObj.name}`);
    }
  } catch (err) {
    console.error("Select style error:", err);
  }
}

async function inferMoreStyles(category) {
  if (!currentSlug) return;
  const btn = category === "photography"
    ? document.getElementById("btnInferMorePhoto")
    : document.getElementById("btnInferMoreArt");

  const originalHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Inferring...`;
  }

  try {
    const res = await fetch(`/api/project/${currentSlug}/styles/infer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: category, count: 3 })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast(`Inferred 3 new ${category} styles!`);
      await loadProjectStyles();
    } else {
      showToast("Inference error: " + (data.error || "Unknown error"), "error");
    }
  } catch (err) {
    showToast("Network error: " + err, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}

// ----------------------------------------------------------------------------
// Style Resolution & Multi-Style Helpers (Tab 4 & Tab 5)
// ----------------------------------------------------------------------------
function resolveBlockIllustrationForStyle(block, styleTarget, workflow = null) {
  if (!block) return null;
  const illustrations = block.illustrations || {};

  // Extract target style identifiers
  let targetName = "";
  let targetId = "";
  if (typeof styleTarget === "string") {
    targetName = styleTarget;
    targetId = styleTarget.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  } else if (styleTarget && typeof styleTarget === "object") {
    targetName = styleTarget.name || "";
    targetId = (styleTarget.id || styleTarget.slug || "").toLowerCase().replace(/[^a-z0-9]+/g, "_");
  }

  const normTargetName = targetName.toLowerCase().trim();
  const normTargetId = targetId.toLowerCase().trim();

  // 1. If a style target is specified, search inside block.illustrations
  if (normTargetName || normTargetId) {
    // If workflow is provided, try exact compound keys first
    if (workflow) {
      const wfClean = workflow.replace(/\.json$/i, "");
      const compoundKeys = [
        `${workflow} (${targetName})`,
        `${wfClean} (${targetName})`,
        `${wfClean}__${normTargetId}`,
        `${wfClean}__${normTargetName.replace(/[^a-z0-9]+/g, "_")}`
      ];
      for (const ck of compoundKeys) {
        if (illustrations[ck]) return illustrations[ck];
      }
    }

    // Try direct keys (style name, style slug)
    if (illustrations[targetName]) return illustrations[targetName];
    if (normTargetId && illustrations[normTargetId]) return illustrations[normTargetId];
    if (illustrations[targetId]) return illustrations[targetId];

    // Search by properties inside illustration objects
    let candidate = null;
    for (const [key, val] of Object.entries(illustrations)) {
      if (!val || typeof val !== "object") continue;
      const vName = (val.style_name || val.style?.name || "").toLowerCase().trim();
      const vId = (val.style_slug || val.style?.id || "").toLowerCase().trim().replace(/[^a-z0-9]+/g, "_");

      const nameMatches = normTargetName && (vName === normTargetName || key.toLowerCase().includes(`(${normTargetName})`));
      const idMatches = normTargetId && (vId === normTargetId || key.toLowerCase().endsWith(`__${normTargetId}`));

      if (nameMatches || idMatches) {
        // If workflow was requested and matches, return immediately
        if (workflow && (val.workflow === workflow || key.startsWith(workflow) || key.startsWith(workflow.replace(/\.json$/i, "")))) {
          return val;
        }
        if (!candidate) candidate = val;
      }
    }
    if (candidate) return candidate;

    // Check root block.illustration if its style matches
    if (block.illustration) {
      const rootName = (block.illustration.style_name || block.illustration.style?.name || "").toLowerCase().trim();
      const rootId = (block.illustration.style_slug || block.illustration.style?.id || "").toLowerCase().trim().replace(/[^a-z0-9]+/g, "_");
      if ((normTargetName && rootName === normTargetName) || (normTargetId && rootId === normTargetId)) {
        return block.illustration;
      }
    }
  }

  // 2. If no styleTarget matched or none specified, fallback to workflow lookup
  if (workflow && illustrations[workflow]) {
    return illustrations[workflow];
  }

  // 3. Fallback to root block.illustration if no specific style was targeted
  if (!normTargetName && !normTargetId && block.illustration) {
    return block.illustration;
  }

  return null;
}

function getManifestStylesList(manifest) {
  const stylesMap = new Map();
  if (!manifest) return [];

  function recordStyle(sName, sId, wf, hasPrompt, isCompleted, desc = "", cat = "art") {
    if (!sName) return;
    const cleanName = sName.trim();
    if (!cleanName) return;
    const cleanId = (sId || cleanName.toLowerCase().replace(/[^a-z0-9]+/g, "_")).trim();

    if (!stylesMap.has(cleanName)) {
      stylesMap.set(cleanName, {
        name: cleanName,
        id: cleanId,
        workflow: wf || null,
        description: desc || "",
        category: cat || "art",
        promptsCount: 0,
        renderedCount: 0
      });
    }
    const entry = stylesMap.get(cleanName);
    if (wf && !entry.workflow) entry.workflow = wf;
    if (desc && !entry.description) entry.description = desc;
    if (cat && entry.category === "art") entry.category = cat;
    if (hasPrompt) entry.promptsCount++;
    if (isCompleted) entry.renderedCount++;
  }

  // Scan blocks
  (manifest.blocks || []).forEach(b => {
    if (b.illustration) {
      const s = b.illustration;
      const sName = s.style_name || s.style?.name || manifest.active_style?.name;
      const sId = s.style_slug || s.style?.id || manifest.active_style?.id;
      const wf = s.workflow || null;
      recordStyle(
        sName,
        sId,
        wf,
        Boolean(s.prompt && s.prompt.trim()),
        s.status === "completed",
        s.style?.description || "",
        s.style?.category || "art"
      );
    }
    if (b.illustrations && typeof b.illustrations === "object") {
      Object.entries(b.illustrations).forEach(([key, v]) => {
        if (!v || typeof v !== "object") return;
        let sName = v.style_name || v.style?.name;
        if (!sName && key.includes("(") && key.endsWith(")")) {
          sName = key.split("(").pop().slice(0, -1).trim();
        }
        let sId = v.style_slug || v.style?.id;
        let wf = v.workflow || (key.includes("(") ? key.split(" (")[0].trim() : null);
        recordStyle(
          sName,
          sId,
          wf,
          Boolean(v.prompt && v.prompt.trim()),
          v.status === "completed",
          v.style?.description || "",
          v.style?.category || "art"
        );
      });
    }
  });

  // Also include project presets if loaded so users can pick any preset style
  if (currentProjectStyles?.presets) {
    const artPresets = currentProjectStyles.presets.art || [];
    const photoPresets = currentProjectStyles.presets.photography || [];
    artPresets.forEach(p => {
      if (p.name && !stylesMap.has(p.name)) {
        stylesMap.set(p.name, {
          name: p.name,
          id: p.id || p.name.toLowerCase().replace(/[^a-z0-9]+/g, "_"),
          workflow: null,
          description: p.description || "",
          category: "art",
          promptsCount: 0,
          renderedCount: 0
        });
      }
    });
    photoPresets.forEach(p => {
      if (p.name && !stylesMap.has(p.name)) {
        stylesMap.set(p.name, {
          name: p.name,
          id: p.id || p.name.toLowerCase().replace(/[^a-z0-9]+/g, "_"),
          workflow: null,
          description: p.description || "",
          category: "photography",
          promptsCount: 0,
          renderedCount: 0
        });
      }
    });
  }

  const list = Array.from(stylesMap.values());
  // Sort: styles with renders or prompts first, then alphabetical
  list.sort((a, b) => {
    const aScore = a.renderedCount * 100 + a.promptsCount;
    const bScore = b.renderedCount * 100 + b.promptsCount;
    if (aScore !== bScore) return bScore - aScore;
    return a.name.localeCompare(b.name);
  });
  return list;
}

function syncRenderStyleDropdown() {
  const selectEl = document.getElementById("selectRenderStyle");
  if (!selectEl) return;

  const styles = getManifestStylesList(currentManifest);
  if (styles.length === 0) {
    selectEl.innerHTML = `<option value="">No styles available</option>`;
    return;
  }

  const targetName = activeStyleSelection?.name || currentManifest?.active_style?.name || styles[0].name;

  selectEl.innerHTML = "";
  styles.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s.name;
    const metaTag = s.renderedCount > 0
      ? `${s.renderedCount} rendered`
      : (s.promptsCount > 0 ? `${s.promptsCount} prompts` : 'no prompts yet');
    opt.textContent = `${s.name} (${metaTag})`;
    if (s.name.toLowerCase() === targetName.toLowerCase()) {
      opt.selected = true;
    }
    selectEl.appendChild(opt);
  });

  // If no option was marked selected, select the first
  if (!selectEl.value && styles.length > 0) {
    selectEl.value = styles[0].name;
  }

  // Ensure activeStyleSelection is in sync
  const matched = styles.find(s => s.name === selectEl.value) || styles[0];
  if (matched && (!activeStyleSelection || activeStyleSelection.name !== matched.name)) {
    activeStyleSelection = {
      id: matched.id,
      name: matched.name,
      description: matched.description || "",
      category: matched.category || "art"
    };
  }

  updateBatchRenderButtonState();
}

async function onRenderStyleChanged(selectedStyleName) {
  if (!selectedStyleName) return;
  const styles = getManifestStylesList(currentManifest);
  const matched = styles.find(s => s.name === selectedStyleName) || {
    name: selectedStyleName,
    id: selectedStyleName.toLowerCase().replace(/[^a-z0-9]+/g, "_")
  };

  activeStyleSelection = {
    id: matched.id,
    name: matched.name,
    description: matched.description || "",
    category: matched.category || "art"
  };

  // 1. Auto-switch workflow if associated with this style
  if (matched.workflow) {
    const wfSelect = document.getElementById("selectWorkflow");
    if (wfSelect) {
      const optExists = Array.from(wfSelect.options).some(o => o.value === matched.workflow);
      if (optExists) {
        wfSelect.value = matched.workflow;
      }
    }
  }

  // 2. Update Tab 4 indicators
  const activeBadge = document.getElementById("activeStyleBadge");
  const activeCatLabel = document.getElementById("activeStyleCatLabel");
  const activeDescInput = document.getElementById("activeStyleDescriptionInput");
  if (activeBadge) activeBadge.textContent = matched.name;
  if (activeCatLabel) activeCatLabel.textContent = matched.category === "photography" ? "Photography Era" : "Art Medium";
  if (activeDescInput && matched.description) activeDescInput.value = matched.description;

  document.querySelectorAll(".style-chip").forEach(chip => {
    if (chip.dataset.styleId === matched.id || chip.querySelector(".style-chip-name")?.textContent.trim() === matched.name) {
      chip.classList.add("active");
    } else {
      chip.classList.remove("active");
    }
  });

  // 3. Render gallery cards for this style on Tab 5
  renderGalleryCards();

  // 4. Also render manifest blocks on Tab 4 so both tabs are synchronized
  renderManifestBlocks();

  // 5. Update batch render button availability
  updateBatchRenderButtonState();

  // 6. Persist style selection
  if (currentSlug) {
    try {
      await fetch(`/api/project/${currentSlug}/styles/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style_id: matched.id,
          style_name: matched.name,
          description: matched.description,
          category: matched.category
        })
      });
    } catch (e) {
      console.warn("Could not persist style selection:", e);
    }
  }
}

function updateBatchRenderButtonState() {
  const btnBatch = document.getElementById("btnStartBatchRender");
  if (!btnBatch) return;

  const blocks = (currentManifest?.blocks || []).filter(b => b.illustration || (b.illustrations && Object.keys(b.illustrations).length > 0));
  const wf = document.getElementById("selectWorkflow")?.value || "";
  const hasPrompts = blocks.some(b => {
    const illus = resolveBlockIllustrationForStyle(b, activeStyleSelection, wf);
    return Boolean(illus && illus.prompt && illus.prompt.trim());
  });

  if (!hasPrompts) {
    btnBatch.disabled = true;
    btnBatch.title = `Start Batch Render unavailable: No prompts generated for '${activeStyleSelection?.name || 'this style'}' yet. Go to Step 4 (Manifest & Prompts) and click 'Synthesize Prompts' first.`;
    btnBatch.style.opacity = "0.5";
    btnBatch.style.cursor = "not-allowed";
  } else {
    btnBatch.disabled = false;
    btnBatch.title = `Start ComfyUI batch rendering for ${activeStyleSelection?.name || 'active style'}`;
    btnBatch.style.opacity = "";
    btnBatch.style.cursor = "";
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
  const illustratedBlocks = blocks.filter(b => b.illustration || (b.illustrations && Object.keys(b.illustrations).length > 0));

  if (filterIllustratedOnly && illustratedBlocks.length === 0) {
    loadPreGenReviewMatrix(container).then(loaded => {
      if (!loaded) {
        container.innerHTML = `<div class="card"><p>No visual beats or illustrated blocks in manifest yet. Complete Step 3 (Visual Beats) and click <strong>Synthesize Prompts</strong>, or uncheck <strong>Show Illustrated Blocks Only</strong> above to view all story blocks.</p></div>`;
      }
    });
    return;
  }

  const activeStyleName = activeStyleSelection?.name || currentManifest.active_style?.name || "Default Style";

  // Calculate prompt count for this style
  const blocksWithPromptForStyle = illustratedBlocks.filter(b => {
    const illus = resolveBlockIllustrationForStyle(b, activeStyleSelection);
    return Boolean(illus && illus.prompt && illus.prompt.trim());
  });
  const hasPromptsForActiveStyle = blocksWithPromptForStyle.length > 0;

  // Header Banner for Style Prompts Status
  const headerBanner = document.createElement("div");
  headerBanner.className = "card";
  headerBanner.style.marginBottom = "14px";
  headerBanner.style.padding = "10px 16px";
  headerBanner.style.display = "flex";
  headerBanner.style.justifyContent = "space-between";
  headerBanner.style.alignItems = "center";
  headerBanner.style.flexWrap = "wrap";
  headerBanner.style.gap = "8px";
  headerBanner.style.borderLeft = hasPromptsForActiveStyle ? "4px solid var(--online)" : "4px solid #f59e0b";

  headerBanner.innerHTML = `
    <div>
      <span style="font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); display: block;">Active Visual Style</span>
      <strong style="font-size: 1.05rem; color: var(--accent);">${escapeHtml(activeStyleName)}</strong>
    </div>
    <div style="display: flex; gap: 8px; align-items: center;">
      ${hasPromptsForActiveStyle
        ? `<span class="badge badge-online">&#10003; ${blocksWithPromptForStyle.length} / ${illustratedBlocks.length} Prompts Synthesized</span>`
        : `<span class="badge badge-warning">&#9888; 0 / ${illustratedBlocks.length} Prompts Synthesized (Click 'Synthesize Prompts' to generate)</span>`}
    </div>
  `;
  container.appendChild(headerBanner);

  blocks.forEach(block => {
    const cid = block.chunk_id;
    const isIllustrationBeat = Boolean(block.illustration || (block.illustrations && Object.keys(block.illustrations).length > 0));

    if (!isIllustrationBeat && filterIllustratedOnly) {
      return;
    }

    const illus = resolveBlockIllustrationForStyle(block, activeStyleSelection);
    const hasPrompt = Boolean(illus && illus.prompt && illus.prompt.trim());
    const card = document.createElement("div");
    card.className = `manifest-block-card ${isIllustrationBeat ? "has-illustration" : ""}`;
    card.dataset.chunkId = cid;

    if (!isIllustrationBeat) {
      card.innerHTML = `
        <div class="card-header">
          <span class="chunk-id">${escapeHtml(cid)}</span>
          <span class="badge">Text Only</span>
        </div>
        <p class="chunk-text" style="color: var(--text-dim);">${escapeHtml(block.text)}</p>
      `;
    } else if (hasPrompt) {
      const isCompleted = illus.status === "completed";
      const badgesHtml = renderContinuityBadgesRow(illus.llm_context);
      card.innerHTML = `
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="chunk-id">${escapeHtml(cid)}</span>
            <button class="btn btn-sm btn-secondary btn-audit-context" data-chunk-id="${escapeHtml(cid)}" title="Audit Visual Bible context sent to LLM for this prompt">&#128269; Context Audit</button>
          </div>
          <div>
            <span class="badge ${isCompleted ? 'badge-online' : 'badge-accent'}">${escapeHtml((illus.status || 'pending').toUpperCase())}</span>
            <span class="badge">${illus.width || 1344}x${illus.height || 768}</span>
          </div>
        </div>
        <p class="chunk-text" style="margin-bottom: 10px;">${escapeHtml(block.text)}</p>
        ${badgesHtml}
        <div class="form-group" style="margin-top: 10px;">
          <label>Positive Prompt (${escapeHtml(activeStyleName)}):</label>
          <textarea class="textarea-input manifest-prompt" rows="3">${escapeHtml(illus.prompt || "")}</textarea>
        </div>
        <div class="form-group">
          <label>Negative Prompt:</label>
          <input type="text" class="text-input manifest-neg-prompt" value="${escapeHtml(illus.negative_prompt || '')}">
        </div>
      `;
    } else {
      // Illustrated scene, but no prompt generated yet for this style
      card.innerHTML = `
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="chunk-id">${escapeHtml(cid)}</span>
            <button class="btn btn-sm btn-secondary btn-audit-context" data-chunk-id="${escapeHtml(cid)}" title="Audit Visual Bible context sent to LLM for this prompt">&#128269; Context Audit</button>
          </div>
          <div>
            <span class="badge badge-warning">NO PROMPT FOR THIS STYLE</span>
          </div>
        </div>
        <p class="chunk-text" style="margin-bottom: 8px;">${escapeHtml(block.text)}</p>
        <div class="style-no-prompt-notice" style="padding: 8px 12px; margin-bottom: 8px; border-radius: 4px; background: rgba(245, 158, 11, 0.1); border-left: 3px solid #f59e0b; font-size: 0.82rem; color: var(--text-dim);">
          No prompt synthesized for <strong>${escapeHtml(activeStyleName)}</strong> yet. Click <strong>Synthesize Prompts</strong> above to generate, or enter one manually below.
        </div>
        <div class="form-group" style="margin-top: 10px;">
          <label>Positive Prompt (${escapeHtml(activeStyleName)}):</label>
          <textarea class="textarea-input manifest-prompt" rows="3" placeholder="Enter custom positive prompt for ${escapeHtml(activeStyleName)}..."></textarea>
        </div>
        <div class="form-group">
          <label>Negative Prompt:</label>
          <input type="text" class="text-input manifest-neg-prompt" placeholder="Optional negative prompt...">
        </div>
      `;
    }

    container.appendChild(card);
  });

  container.querySelectorAll(".btn-audit-context").forEach(btn => {
    btn.addEventListener("click", () => {
      const cid = btn.dataset.chunkId;
      const blk = (currentManifest?.blocks || []).find(b => b.chunk_id === cid);
      const ill = resolveBlockIllustrationForStyle(blk, activeStyleSelection) || blk?.illustration;
      if (ill && ill.llm_context) {
        openPromptContextModal(ill.llm_context, cid);
      } else {
        previewPromptContext(cid);
      }
    });
  });
}

function renderGalleryCards() {
  const gallery = document.getElementById("imagesGallery");
  if (!gallery || !currentManifest) return;
  gallery.innerHTML = "";

  const blocks = (currentManifest.blocks || []).filter(b => b.illustration || (b.illustrations && Object.keys(b.illustrations).length > 0));
  const activeWf = document.getElementById("selectWorkflow")?.value || currentManifest.active_workflow || "sdxl_base.json";

  if (blocks.length === 0) {
    gallery.innerHTML = `<div class="card" style="grid-column: 1/-1;"><p>No illustrated scenes in manifest. Go to Step 3 &amp; 4 to select beats and synthesize prompts.</p></div>`;
    updateBatchRenderButtonState();
    return;
  }

  blocks.forEach(block => {
    const cid = block.chunk_id;
    const illus = resolveBlockIllustrationForStyle(block, activeStyleSelection, activeWf);
    const hasPrompt = Boolean(illus && illus.prompt && illus.prompt.trim());
    const isCompleted = Boolean(illus && illus.status === "completed" && illus.image_file);
    const isChecked = selectedImageChunks.has(cid);

    const imgCard = document.createElement("div");
    imgCard.className = `image-card ${isChecked ? "selected" : ""}`;
    imgCard.dataset.chunkId = cid;

    let previewHtml = "";
    if (isCompleted) {
      const relImgPath = illus.image_file.replace(/^images\//, "");
      const imgSrc = `/api/project/${currentSlug}/images/${encodeURI(relImgPath)}?t=${Date.now()}`;
      previewHtml = `<img src="${imgSrc}" alt="${cid}" onerror="this.parentElement.innerHTML='<div class=\\'image-placeholder\\'>Rendered file not found on disk</div>'">`;
    } else if (hasPrompt) {
      previewHtml = `<div class="image-placeholder">&#9654; Ready to Render (${illus.width || 1344}x${illus.height || 768})</div>`;
    } else {
      previewHtml = `<div class="image-placeholder" style="color: var(--text-dim); font-size: 0.82rem;">&#9888; No prompt synthesized for this style</div>`;
    }

    const promptText = (illus && illus.prompt) ? illus.prompt : "";
    const statusText = illus ? (illus.status || "pending") : "unrendered";
    const statusBadgeClass = isCompleted ? 'badge-online' : (hasPrompt ? 'badge-accent' : 'badge-warning');

    imgCard.innerHTML = `
      <div class="image-card-preview">
        <input type="checkbox" class="img-card-checkbox" data-chunk-id="${cid}" ${isChecked ? "checked" : ""} ${hasPrompt || isCompleted ? "" : "disabled"} title="Select for regeneration">
        ${previewHtml}
      </div>
      <div class="image-card-body">
        <div class="card-header" style="margin-bottom: 4px;">
          <span class="chunk-id">${cid}</span>
          <span class="badge ${statusBadgeClass}">${statusText.toUpperCase()}</span>
        </div>
        <div class="card-prompt-container" style="font-size: 0.82rem; color: var(--text-dim); line-height: 1.35; flex-grow: 1;">
          <p class="prompt-text prompt-collapsed" style="margin: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-break: break-word;">
            ${escapeHtml(promptText || "No prompt synthesized for this style yet.")}
          </p>
          ${promptText ? `
            <button type="button" class="btn-toggle-prompt" style="background: none; border: none; color: var(--accent); font-size: 0.78rem; cursor: pointer; padding: 2px 0 0 0; text-decoration: underline;">
              View Full Prompt
            </button>
          ` : ''}
        </div>
        <div style="margin-top: 10px; display: flex; gap: 8px;">
          <button class="btn btn-sm btn-primary btn-tweak-rerun" data-chunk-id="${cid}" ${hasPrompt || isCompleted ? "" : "disabled"}>
            ${isCompleted ? '&#8635; Tweak &amp; Regenerate' : '&#9654; Render Scene'}
          </button>
          <button class="btn btn-sm btn-secondary btn-gallery-audit" data-chunk-id="${cid}" title="Inspect Visual Bible Context Audit">
            &#128269; Context
          </button>
        </div>
      </div>
    `;

    const chk = imgCard.querySelector(".img-card-checkbox");
    if (chk) {
      chk.addEventListener("change", (e) => {
        e.stopPropagation();
        if (chk.checked) {
          selectedImageChunks.add(cid);
        } else {
          selectedImageChunks.delete(cid);
        }
        updateSelectedImagesUI();
      });
    }

    const toggleBtn = imgCard.querySelector(".btn-toggle-prompt");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => {
        const pEl = imgCard.querySelector(".prompt-text");
        if (pEl.classList.contains("prompt-collapsed")) {
          pEl.classList.remove("prompt-collapsed");
          pEl.style.display = "block";
          pEl.style.webkitLineClamp = "unset";
          toggleBtn.textContent = "Hide Prompt";
        } else {
          pEl.classList.add("prompt-collapsed");
          pEl.style.display = "-webkit-box";
          pEl.style.webkitLineClamp = "2";
          toggleBtn.textContent = "View Full Prompt";
        }
      });
    }

    imgCard.querySelector(".btn-tweak-rerun")?.addEventListener("click", () => {
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
  updateBatchRenderButtonState();
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
    syncRenderStyleDropdown();
    renderManifestBlocks();
    renderGalleryCards();

  } catch (err) {
    console.error("Manifest load error:", err);
  }
}

async function saveManifest() {
  if (!currentManifest) return;
  const cards = document.querySelectorAll(".manifest-block-card.has-illustration");
  const activeStyleName = activeStyleSelection?.name || currentManifest.active_style?.name || "Default Style";
  const activeStyleSlug = activeStyleSelection?.id || currentManifest.active_style?.id || activeStyleName.toLowerCase().replace(/[^a-z0-9]+/g, "_");

  cards.forEach(c => {
    const cid = c.dataset.chunkId;
    const prompt = c.querySelector(".manifest-prompt")?.value.trim() || "";
    const negPrompt = c.querySelector(".manifest-neg-prompt")?.value.trim() || "";

    const block = currentManifest.blocks.find(b => b.chunk_id === cid);
    if (!block) return;

    if (!block.illustrations) block.illustrations = {};

    // 1. Update any existing entries in block.illustrations for this style
    let updatedInIllustrations = false;
    for (const [k, v] of Object.entries(block.illustrations)) {
      if (!v || typeof v !== "object") continue;
      const vName = v.style_name || v.style?.name || "";
      const vSlug = v.style_slug || v.style?.id || "";
      if (vName === activeStyleName || vSlug === activeStyleSlug || k.includes(`(${activeStyleName})`) || k.endsWith(`__${activeStyleSlug}`)) {
        v.prompt = prompt;
        v.negative_prompt = negPrompt;
        updatedInIllustrations = true;
      }
    }

    // 2. If not found in illustrations, create new entries under style name and slug
    if (!updatedInIllustrations && prompt) {
      const newEntry = {
        status: "pending",
        image_file: `images/${cid}.png`,
        width: block.illustration?.width || 1344,
        height: block.illustration?.height || 768,
        prompt: prompt,
        negative_prompt: negPrompt,
        style_name: activeStyleName,
        style_slug: activeStyleSlug,
        style: activeStyleSelection || { id: activeStyleSlug, name: activeStyleName }
      };
      block.illustrations[activeStyleName] = newEntry;
      block.illustrations[activeStyleSlug] = newEntry;
    }

    // 3. Update root block.illustration if it matches active style or if no root exists
    if (!block.illustration || block.illustration.style_name === activeStyleName || block.illustration.style_slug === activeStyleSlug || block.illustration.style?.name === activeStyleName) {
      if (!block.illustration) {
        block.illustration = {
          status: "pending",
          image_file: `images/${cid}.png`,
          width: 1344,
          height: 768,
          prompt: prompt,
          negative_prompt: negPrompt,
          style: activeStyleSelection || { id: activeStyleSlug, name: activeStyleName },
          style_name: activeStyleName,
          style_slug: activeStyleSlug
        };
      } else {
        block.illustration.prompt = prompt;
        block.illustration.negative_prompt = negPrompt;
      }
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
  const illus = resolveBlockIllustrationForStyle(block, activeStyleSelection, activeWf)
    || (block.illustrations && block.illustrations[activeWf])
    || block.illustration
    || {};

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
        workflow: wf,
        style_name: activeStyleSelection?.name,
        style_slug: activeStyleSelection?.id,
        resolution_tier: document.getElementById("selectResolutionTier")?.value || "standard"
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
  const wf = document.getElementById("selectWorkflow")?.value || "sdxl_base.json";
  const blocks = (currentManifest?.blocks || []).filter(b => b.illustration || (b.illustrations && Object.keys(b.illustrations).length > 0));

  // Check if prompts exist for this active style
  const blocksWithPrompts = blocks.filter(b => {
    const illus = resolveBlockIllustrationForStyle(b, activeStyleSelection, wf);
    return Boolean(illus && illus.prompt && illus.prompt.trim());
  });

  if (blocksWithPrompts.length === 0) {
    showToast(`No prompts synthesized for '${activeStyleSelection?.name || 'this style'}' yet. Go to Step 4 (Manifest & Prompts) and click 'Synthesize Prompts' first.`, "warning");
    return;
  }

  const pendingCount = blocksWithPrompts.filter(b => {
    const illus = resolveBlockIllustrationForStyle(b, activeStyleSelection, wf);
    return !illus || illus.status !== "completed";
  }).length;

  let forceAll = false;
  if (pendingCount === 0 && blocksWithPrompts.length > 0) {
    if (!confirm(`All illustrations for style '${activeStyleSelection?.name || wf}' are already completed. Re-render all scenes with fresh seeds?`)) {
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
      body: JSON.stringify({
        workflow: wf,
        force_all: forceAll,
        style_name: activeStyleSelection?.name,
        style_slug: activeStyleSelection?.id,
        resolution_tier: document.getElementById("selectResolutionTier")?.value || "standard"
      })
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
      body: JSON.stringify({
        workflow: wf,
        chunk_ids: chunkIds,
        style_name: activeStyleSelection?.name,
        style_slug: activeStyleSelection?.id,
        resolution_tier: document.getElementById("selectResolutionTier")?.value || "standard"
      })
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

    const rawWorkflows = Array.from(availableWorkflows);
    const friendlyNames = rawWorkflows.filter(k => k.includes(" (") && k.endsWith(")"));
    const friendlySlugs = new Set(friendlyNames.map(k => {
      const parts = k.slice(0, -1).split(" (");
      const wf = parts[0].replace(/\.json$/i, "").toLowerCase();
      const st = parts[1].toLowerCase().replace(/[^a-z0-9]+/g, "_");
      return `${wf}__${st}`;
    }));
    const displayWorkflows = rawWorkflows.filter(k => !friendlySlugs.has(k.toLowerCase()));

    displayWorkflows.sort().forEach(wf => {
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
  document.getElementById("metaBookSubtitle").value = meta?.subtitle || "";
  document.getElementById("metaBookAuthor").value = meta?.author && meta.author !== "Author Unknown" ? meta.author : "";
  document.getElementById("metaBookIllustrator").value = meta?.illustrator || "";
  document.getElementById("metaBookPublisher").value = meta?.publisher || "Self-Published";
  const copyrightEl = document.getElementById("metaBookCopyright");
  if (copyrightEl) {
    copyrightEl.value = meta?.copyright_text || "";
  }
  const colophonEl = document.getElementById("metaBookColophon");
  if (colophonEl) {
    colophonEl.value = meta?.colophon || "";
  }
  document.getElementById("metaBookDedication").value = meta?.dedication || "";
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
    subtitle: document.getElementById("metaBookSubtitle").value.trim(),
    author: author,
    illustrator: document.getElementById("metaBookIllustrator").value.trim(),
    publisher: document.getElementById("metaBookPublisher").value.trim() || "Self-Published",
    copyright_text: document.getElementById("metaBookCopyright") ? document.getElementById("metaBookCopyright").value.trim() : "",
    colophon: document.getElementById("metaBookColophon") ? document.getElementById("metaBookColophon").value.trim() : "",
    dedication: document.getElementById("metaBookDedication").value.trim(),
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
// Amazon KDP Cover Studio Controller
// ----------------------------------------------------------------------------
let currentCoverData = null;
let currentCoverSelectedChunkId = null;
let currentCoverActiveWorkflow = null;
let currentCoverScenes = [];
let coverStudioEventsBound = false;

async function openCoverStudio(preferredStyle = null) {
  if (!currentSlug) {
    showToast("Please select a story project first.", "error");
    return;
  }
  const modal = document.getElementById("modalCoverStudio");
  if (modal) modal.style.display = "flex";

  // If no style explicitly passed, inherit from Reader tab or Render tab
  if (!preferredStyle) {
    const readerWf = document.getElementById("readerWorkflowSelect")?.value;
    const renderStyle = document.getElementById("selectRenderStyle")?.value;
    preferredStyle = readerWf || renderStyle || null;
  }

  await loadCoverStudio(preferredStyle);
}

function closeCoverStudio() {
  const modal = document.getElementById("modalCoverStudio");
  if (modal) modal.style.display = "none";
}

function switchCoverMode(mode) {
  const btnGen = document.getElementById("tabModeGenerate");
  const btnExist = document.getElementById("tabModeExisting");
  const panelGen = document.getElementById("panelCoverGenerate");
  const panelExist = document.getElementById("panelCoverExisting");

  if (mode === "generate") {
    if (btnGen) { btnGen.className = "btn btn-primary"; }
    if (btnExist) { btnExist.className = "btn btn-secondary"; }
    if (panelGen) panelGen.style.display = "flex";
    if (panelExist) panelExist.style.display = "none";
  } else {
    if (btnGen) { btnGen.className = "btn btn-secondary"; }
    if (btnExist) { btnExist.className = "btn btn-primary"; }
    if (panelGen) panelGen.style.display = "none";
    if (panelExist) panelExist.style.display = "flex";
  }
}

async function loadCoverStudio(preferredStyle = null) {
  if (!currentSlug) return;
  try {
    const query = preferredStyle ? `?workflow=${encodeURIComponent(preferredStyle)}` : "";
    const res = await fetch(`/api/project/${encodeURIComponent(currentSlug)}/cover${query}`);
    if (!res.ok) {
      showToast("Failed to load cover information.", "error");
      return;
    }
    const data = await res.json();
    currentCoverData = data;
    currentCoverActiveWorkflow = data.active_workflow || preferredStyle || "";
    currentCoverScenes = data.available_scenes || [];

    updateCoverPreviewUI(data.cover);

    // Setup style selector
    const selectStyle = document.getElementById("selectCoverStyle");
    if (selectStyle) {
      selectStyle.innerHTML = "";
      const styles = data.available_styles || [];
      if (styles.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No style variants found";
        selectStyle.appendChild(opt);
      } else {
        styles.forEach(s => {
          const opt = document.createElement("option");
          opt.value = s.workflow;
          opt.textContent = `${s.label} (${s.rendered_count} scenes)`;
          if (s.workflow === currentCoverActiveWorkflow) {
            opt.selected = true;
          }
          selectStyle.appendChild(opt);
        });
      }
    }

    // Default selected chunk to current cover chunk if present, else first scene
    if (data.cover && data.cover.chunk_id && currentCoverScenes.some(s => s.chunk_id === data.cover.chunk_id)) {
      currentCoverSelectedChunkId = data.cover.chunk_id;
    } else if (currentCoverScenes.length > 0 && (!currentCoverSelectedChunkId || !currentCoverScenes.some(s => s.chunk_id === currentCoverSelectedChunkId))) {
      currentCoverSelectedChunkId = currentCoverScenes[0].chunk_id;
    }

    // Render Scene Grid
    renderCoverSceneGrid(currentCoverScenes, currentCoverSelectedChunkId);

    // One-time event bindings for style change & search filter
    if (!coverStudioEventsBound) {
      coverStudioEventsBound = true;

      const styleSelectEl = document.getElementById("selectCoverStyle");
      if (styleSelectEl) {
        styleSelectEl.addEventListener("change", async (e) => {
          const newWf = e.target.value;
          if (newWf) {
            await loadCoverStudio(newWf);
          }
        });
      }

      const searchInput = document.getElementById("inputCoverSceneFilter");
      if (searchInput) {
        searchInput.addEventListener("input", (e) => {
          filterCoverScenes(e.target.value);
        });
      }
    }

    const promptInput = document.getElementById("coverPromptInput");
    const negInput = document.getElementById("coverNegativeInput");
    if (promptInput && !promptInput.value.trim()) {
      if (data.cover && data.cover.prompt) {
        promptInput.value = data.cover.prompt;
      } else if (data.default_prompt) {
        promptInput.value = data.default_prompt;
      }
    }
    if (negInput && !negInput.value.trim()) {
      if (data.cover && data.cover.negative_prompt) {
        negInput.value = data.cover.negative_prompt;
      }
    }
  } catch (err) {
    console.error("Error loading cover studio:", err);
    showToast("Error loading cover studio: " + err, "error");
  }
}

function renderCoverSceneGrid(scenes, selectedChunkId) {
  const grid = document.getElementById("coverSceneGrid");
  const countBadge = document.getElementById("coverSceneCountBadge");
  const hiddenSelect = document.getElementById("selectCoverScene");

  if (countBadge) {
    countBadge.textContent = `${scenes.length} scene${scenes.length === 1 ? '' : 's'}`;
  }

  if (hiddenSelect) {
    hiddenSelect.innerHTML = "";
    scenes.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.chunk_id;
      opt.textContent = `${s.chunk_id}: ${s.action_beat || s.title || s.chunk_id}`;
      if (s.chunk_id === selectedChunkId) opt.selected = true;
      hiddenSelect.appendChild(opt);
    });
  }

  if (!grid) return;
  grid.innerHTML = "";

  if (!scenes || scenes.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-dim); padding: 24px 12px; font-size: 0.85rem;">No rendered scenes found for this style. Switch styles above or render scenes in Phase 2.</div>`;
    return;
  }

  scenes.forEach(scene => {
    const isSelected = (scene.chunk_id === selectedChunkId);
    const card = document.createElement("div");
    card.className = `cover-scene-card ${isSelected ? 'selected' : ''}`;
    card.dataset.chunkId = scene.chunk_id;
    card.title = scene.prompt || scene.title || scene.chunk_id;

    const beatText = scene.action_beat || scene.title || "";

    card.innerHTML = `
      <div class="cover-scene-thumb-wrap">
        <img src="${scene.image_url}?t=${Date.now()}" alt="${scene.chunk_id}" onerror="this.src=''; this.alt='Preview unavailable';">
        <span class="cover-scene-badge">${scene.chunk_id}</span>
        <span class="cover-scene-selected-icon">&#10003;</span>
      </div>
      <div class="cover-scene-info">
        <div class="cover-scene-id">${scene.chunk_id}</div>
        <div class="cover-scene-text">${escapeHtml(beatText)}</div>
      </div>
    `;

    card.addEventListener("click", () => {
      selectCoverSceneCard(scene);
    });

    grid.appendChild(card);
  });
}

function selectCoverSceneCard(scene) {
  currentCoverSelectedChunkId = scene.chunk_id;

  // Update visual selection in grid
  const allCards = document.querySelectorAll(".cover-scene-card");
  allCards.forEach(c => {
    if (c.dataset.chunkId === scene.chunk_id) {
      c.classList.add("selected");
    } else {
      c.classList.remove("selected");
    }
  });

  // Update hidden select for backward compatibility
  const hiddenSelect = document.getElementById("selectCoverScene");
  if (hiddenSelect) {
    hiddenSelect.value = scene.chunk_id;
  }

  // Update live preview in right panel staging box
  previewSceneStaging(scene);
}

function previewSceneStaging(scene) {
  if (!scene) return;
  const badge = document.getElementById("coverStatusBadge");
  const img = document.getElementById("coverPreviewImg");
  const placeholder = document.getElementById("coverPlaceholderText");

  if (badge) {
    badge.textContent = `Selected: ${scene.chunk_id}`;
    badge.className = "badge badge-accent";
  }
  if (img) {
    img.src = `${scene.image_url}?t=${Date.now()}`;
    img.style.display = "block";
  }
  if (placeholder) {
    placeholder.style.display = "none";
  }
}

function filterCoverScenes(query) {
  const q = (query || "").trim().toLowerCase();
  const cards = document.querySelectorAll(".cover-scene-card");
  let visibleCount = 0;

  cards.forEach(card => {
    const text = card.textContent.toLowerCase();
    const title = (card.title || "").toLowerCase();
    const matches = !q || text.includes(q) || title.includes(q);
    card.style.display = matches ? "flex" : "none";
    if (matches) visibleCount++;
  });

  const countBadge = document.getElementById("coverSceneCountBadge");
  if (countBadge) {
    countBadge.textContent = `${visibleCount} scene${visibleCount === 1 ? '' : 's'}`;
  }
}

function updateCoverPreviewUI(cover) {
  const badge = document.getElementById("coverStatusBadge");
  const img = document.getElementById("coverPreviewImg");
  const placeholder = document.getElementById("coverPlaceholderText");
  const downloadBox = document.getElementById("coverDownloadActions");
  const downloadLink = document.getElementById("linkDownloadMarketingCover");

  if (cover && (cover.marketing_file || cover.image_file)) {
    let relPath = cover.marketing_file || cover.image_file;
    if (relPath.startsWith("images/")) {
      relPath = relPath.substring(7);
    }
    const imgSrc = `/api/project/${encodeURIComponent(currentSlug)}/images/${encodeURI(relPath)}?t=${Date.now()}`;
    if (badge) {
      badge.textContent = "Cover Ready (1600×2560)";
      badge.className = "badge badge-success";
    }
    if (img) {
      img.src = imgSrc;
      img.style.display = "block";
    }
    if (placeholder) {
      placeholder.style.display = "none";
    }
    if (downloadBox) {
      downloadBox.style.display = "block";
    }
    if (downloadLink) {
      downloadLink.href = imgSrc;
    }
  } else {
    if (badge) {
      badge.textContent = "No Cover Set";
      badge.className = "badge badge-accent";
    }
    if (img) {
      img.style.display = "none";
      img.src = "";
    }
    if (placeholder) {
      placeholder.style.display = "block";
    }
    if (downloadBox) {
      downloadBox.style.display = "none";
    }
  }
}

async function synthesizeCoverPromptAction() {
  if (!currentSlug) return;
  const btn = document.getElementById("btnSynthesizeCoverPrompt");
  const originalText = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Synthesizing...`;
  }
  try {
    const res = await fetch(`/api/project/${encodeURIComponent(currentSlug)}/cover/synthesize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });
    const data = await res.json();
    if (data.success) {
      const promptInput = document.getElementById("coverPromptInput");
      const negInput = document.getElementById("coverNegativeInput");
      if (promptInput) promptInput.value = data.prompt || "";
      if (negInput && data.negative_prompt) negInput.value = data.negative_prompt;
      showToast("Cover prompt synthesized from Visual Bible!");
    } else {
      showToast("Prompt synthesis error: " + (data.error || "Unknown"), "error");
    }
  } catch (err) {
    showToast("Network error synthesizing cover: " + err, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
}

async function renderCoverAction() {
  if (!currentSlug) return;
  const promptInput = document.getElementById("coverPromptInput");
  const prompt = promptInput ? promptInput.value.trim() : "";
  if (!prompt) {
    showToast("Please enter or auto-synthesize a cover prompt first.", "error");
    return;
  }
  const negInput = document.getElementById("coverNegativeInput");
  const negPrompt = negInput ? negInput.value.trim() : "";
  const wf = document.getElementById("selectWorkflow")?.value || "sdxl_base.json";
  const applyTypo = document.getElementById("checkCoverTypography")?.checked ?? true;
  const tier = document.getElementById("selectResolutionTier")?.value || "standard";
  const fontFamily = document.getElementById("selectCoverFontFamily")?.value || "serif";
  const fontColor = document.getElementById("selectCoverFontColor")?.value || "gold";

  const btn = document.getElementById("btnRenderCoverAction");
  const originalText = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Rendering KDP Cover (ComfyUI)...`;
  }

  showToast("Rendering commercial cover in ComfyUI... this may take a moment.");

  try {
    const res = await fetch(`/api/project/${encodeURIComponent(currentSlug)}/cover/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: prompt,
        negative_prompt: negPrompt,
        workflow: wf,
        apply_typography: applyTypo,
        resolution_tier: tier,
        font_family: fontFamily,
        font_color: fontColor
      })
    });
    const data = await res.json();
    if (data.success && data.cover) {
      updateCoverPreviewUI(data.cover);
      showToast("KDP Cover rendered & composited successfully!", "success");
      await loadManifest();
      loadReaderPreview(wf);
    } else {
      showToast("Cover render error: " + (data.error || "Failed"), "error");
    }
  } catch (err) {
    showToast("Network error during cover render: " + err, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
}

async function setExistingSceneCoverAction() {
  if (!currentSlug) return;
  const sceneSelect = document.getElementById("selectCoverScene");
  const chunkId = currentCoverSelectedChunkId || (sceneSelect ? sceneSelect.value : "");
  if (!chunkId) {
    showToast("Please select a scene first.", "error");
    return;
  }
  const applyTypo = document.getElementById("checkCoverTypography")?.checked ?? true;
  const styleSelect = document.getElementById("selectCoverStyle");
  const wf = styleSelect?.value || currentCoverActiveWorkflow || document.getElementById("selectWorkflow")?.value;
  const fontFamily = document.getElementById("selectCoverFontFamily")?.value || "serif";
  const fontColor = document.getElementById("selectCoverFontColor")?.value || "gold";

  const btn = document.getElementById("btnSetExistingCoverAction");
  const originalText = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Building KDP Cover...`;
  }

  try {
    const res = await fetch(`/api/project/${encodeURIComponent(currentSlug)}/cover/set-existing`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chunk_id: chunkId,
        apply_typography: applyTypo,
        workflow: wf,
        font_family: fontFamily,
        font_color: fontColor
      })
    });
    const data = await res.json();
    if (data.success && data.cover) {
      updateCoverPreviewUI(data.cover);
      showToast("Scene successfully set as official KDP Cover!", "success");
      await loadManifest();
      loadReaderPreview(wf);
    } else {
      showToast("Error setting cover: " + (data.error || "Failed"), "error");
    }
  } catch (err) {
    showToast("Network error setting cover: " + err, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
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

  // Progress polling interval with request stacking guard
  let isPolling = false;
  const pollTimer = setInterval(async () => {
    if (isPolling) return;
    isPolling = true;
    try {
      const pRes = await fetch(`/api/project/${currentSlug}/stage_progress`);
      if (pRes.ok) {
        const pData = await pRes.json();
        if (pData.message && msgEl) {
          msgEl.textContent = pData.message;
        }
      }
    } catch (e) {
    } finally {
      isPolling = false;
    }
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
      const totalIllustrated = (currentManifest?.blocks || []).filter(b => b.illustration || (b.illustrations && Object.keys(b.illustrations).length > 0));
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
        renderGalleryCards();
        updateBatchRenderButtonState();
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

  const btnExpKdp = document.getElementById("btnExportKdpPack");
  if (btnExpKdp) btnExpKdp.addEventListener("click", () => triggerBookExport("kdp_pack"));

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

  // Resolution tier switcher in Tab 5 toolbar
  const selTier = document.getElementById("selectResolutionTier");
  if (selTier) {
    selTier.addEventListener("change", async (e) => {
      if (!currentSlug) return;
      try {
        const res = await fetch(`/api/project/${encodeURIComponent(currentSlug)}/resolution-tier`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tier: e.target.value })
        });
        if (res.ok) {
          showToast(`Resolution tier set to ${e.target.value === 'highres' ? 'High-Res Retina (~2048)' : 'Standard Ebook (~1 MP)'}`);
        }
      } catch (err) {
        showToast("Failed to save resolution tier: " + err, "error");
      }
    });
  }

  // Cover Studio Modal bindings
  const btnOpenCover = document.getElementById("btnOpenCoverStudio");
  if (btnOpenCover) btnOpenCover.addEventListener("click", () => openCoverStudio());

  const btnReaderCover = document.getElementById("btnReaderCoverStudio");
  if (btnReaderCover) {
    btnReaderCover.addEventListener("click", () => {
      const selectedWf = document.getElementById("readerWorkflowSelect")?.value;
      openCoverStudio(selectedWf);
    });
  }

  const btnCloseCoverModal = document.getElementById("btnCloseCoverStudioModal");
  if (btnCloseCoverModal) btnCloseCoverModal.addEventListener("click", closeCoverStudio);

  const btnCloseCover = document.getElementById("btnCloseCoverStudio");
  if (btnCloseCover) btnCloseCover.addEventListener("click", closeCoverStudio);

  const modalCover = document.getElementById("modalCoverStudio");
  if (modalCover) {
    modalCover.addEventListener("click", (e) => {
      if (e.target === modalCover) closeCoverStudio();
    });
  }

  const tabGen = document.getElementById("tabModeGenerate");
  if (tabGen) tabGen.addEventListener("click", () => switchCoverMode("generate"));

  const tabExist = document.getElementById("tabModeExisting");
  if (tabExist) tabExist.addEventListener("click", () => switchCoverMode("existing"));

  const btnSynthCover = document.getElementById("btnSynthesizeCoverPrompt");
  if (btnSynthCover) btnSynthCover.addEventListener("click", synthesizeCoverPromptAction);

  const btnRndCover = document.getElementById("btnRenderCoverAction");
  if (btnRndCover) btnRndCover.addEventListener("click", renderCoverAction);

  const btnSetExistCover = document.getElementById("btnSetExistingCoverAction");
  if (btnSetExistCover) btnSetExistCover.addEventListener("click", setExistingSceneCoverAction);

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

  // Style Selection Console (Tab 4 & Tab 5)
  const btnMoreArt = document.getElementById("btnInferMoreArt");
  if (btnMoreArt) {
    btnMoreArt.addEventListener("click", () => inferMoreStyles("art"));
  }
  const btnMorePhoto = document.getElementById("btnInferMorePhoto");
  if (btnMorePhoto) {
    btnMorePhoto.addEventListener("click", () => inferMoreStyles("photography"));
  }
  const styleDescInput = document.getElementById("activeStyleDescriptionInput");
  if (styleDescInput) {
    styleDescInput.addEventListener("change", () => {
      if (activeStyleSelection) {
        activeStyleSelection.description = styleDescInput.value.trim();
        selectActiveStyle(activeStyleSelection);
      }
    });
  }
  const renderStyleSelect = document.getElementById("selectRenderStyle");
  if (renderStyleSelect) {
    renderStyleSelect.addEventListener("change", (e) => {
      onRenderStyleChanged(e.target.value);
    });
  }
  const readerWfSelect = document.getElementById("readerWorkflowSelect");
  if (readerWfSelect) {
    readerWfSelect.addEventListener("change", e => loadReaderPreview(e.target.value));
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
