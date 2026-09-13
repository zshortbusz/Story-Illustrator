// pipeline/web_static/app.js: Frontend controller for Automated Story Illustrator

let currentSlug = "";
let systemStatus = null;
let currentManifest = null;
let availableModels = [];

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
    const res = await fetch("/api/status");
    systemStatus = await res.json();

    const lmBadge = document.getElementById("badgeLMStudio");
    const comfyBadge = document.getElementById("badgeComfyUI");

    if (systemStatus.lm_studio.online) {
      lmBadge.className = "badge badge-online";
      lmBadge.title = `LM Studio Online (${systemStatus.lm_studio.models.length} models)`;
      availableModels = systemStatus.lm_studio.models || [];
      populateModelDropdowns(availableModels);
    } else {
      lmBadge.className = "badge badge-offline";
      lmBadge.title = "LM Studio Offline";
    }

    if (systemStatus.comfyui.online) {
      comfyBadge.className = "badge badge-online";
      comfyBadge.title = "ComfyUI Server Online";
    } else {
      comfyBadge.className = "badge badge-offline";
      comfyBadge.title = "ComfyUI Server Offline";
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

  if (activeTab === "tab-render") {
    banner.className = "hardware-banner phase-2-active";
    title.textContent = "Phase 2 Active (Diffusion):";
    desc.textContent = "ComfyUI server must be running at http://127.0.0.1:8188. LM Studio should be UNLOADED / CLOSED to free GPU VRAM.";
  } else if (activeTab === "tab-reader") {
    banner.className = "hardware-banner phase-3-active";
    title.textContent = "Phase 3 Active (Reader Assembly):";
    desc.textContent = "Pure Python execution with zero GPU footprint. Neither LM Studio nor ComfyUI needs to be running.";
  } else {
    banner.className = "hardware-banner phase-1-active";
    title.textContent = "Phase 1 Active (Analysis & Prompts):";
    desc.textContent = "LM Studio must be running at http://localhost:1234 with your selected model loaded. ComfyUI should be CLOSED to prevent VRAM competition.";
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
async function loadProjects() {
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
      currentSlug = projects[0].slug;
      select.value = currentSlug;
      await loadProjectData(currentSlug);
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
    Object.entries(chars).forEach(([name, desc]) => {
      const item = document.createElement("div");
      item.className = "bible-item-card";
      item.innerHTML = `
        <div class="card-header">
          <input type="text" class="text-input char-name-input" value="${name}" style="font-weight: 600; width: 60%;">
          <button class="btn btn-sm btn-danger btn-del-char">&times;</button>
        </div>
        <textarea class="textarea-input char-desc-input" rows="3">${desc}</textarea>
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
    const desc = el.querySelector(".char-desc-input").value.trim();
    if (name) characters[name] = desc;
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
          <label>Setting:</label>
          <input type="text" class="text-input beat-setting" value="${b.setting || ""}">
        </div>
        <div class="form-group">
          <label>Camera Framing &amp; Lighting:</label>
          <input type="text" class="text-input beat-camera" value="${b.camera_framing || ""}">
        </div>
        <div style="text-align: right;">
          <button class="btn btn-sm btn-danger btn-delete-beat" data-index="${idx}">Delete Beat</button>
        </div>
      `;
      container.appendChild(card);
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
    const setting = c.querySelector(".beat-setting").value.trim();
    const camera = c.querySelector(".beat-camera").value.trim();

    beats.push({
      chunk_id: cid,
      scene_type: stype,
      characters_present: chars,
      setting: setting,
      action_beat: action,
      camera_framing: camera
    });
  });
  return beats;
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
    container.innerHTML = `<div class="card"><p>No visual beats or illustrated blocks in manifest yet. Complete Step 3 (Visual Beats) and click <strong>Synthesize Prompts</strong>, or uncheck <strong>Show Illustrated Blocks Only</strong> above to view all story blocks.</p></div>`;
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
          <span class="chunk-id">${cid}</span>
          <span class="badge">Text Only</span>
        </div>
        <p class="chunk-text" style="color: var(--text-dim);">${block.text}</p>
      `;
    } else {
      const isCompleted = illus.status === "completed";
      card.innerHTML = `
        <div class="card-header">
          <span class="chunk-id">${cid}</span>
          <div>
            <span class="badge ${isCompleted ? 'badge-online' : 'badge-accent'}">${illus.status.toUpperCase()}</span>
            <span class="badge">${illus.width}x${illus.height}</span>
          </div>
        </div>
        <p class="chunk-text" style="margin-bottom: 12px;">${block.text}</p>
        <div class="form-group">
          <label>Positive Prompt:</label>
          <textarea class="textarea-input manifest-prompt" rows="3">${illus.prompt || ""}</textarea>
        </div>
        <div class="form-group">
          <label>Negative Prompt:</label>
          <input type="text" class="text-input manifest-neg-prompt" value="${illus.negative_prompt || ''}">
        </div>
      `;
    }

    container.appendChild(card);
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
      container.innerHTML = `<div class="card"><p>No manifest.json yet. Complete Steps 1-3 and click <strong>Synthesize Prompts</strong>.</p></div>`;
      return;
    }

    currentManifest = await res.json();
    renderManifestBlocks();

    // Render in Image Gallery Tab (Tab 5)
    const blocks = currentManifest.blocks || [];
    blocks.filter(b => b.illustration).forEach(block => {
      const cid = block.chunk_id;
      const illus = block.illustration;
      const isCompleted = illus.status === "completed";

      const imgCard = document.createElement("div");
      imgCard.className = "image-card";
      const imgSrc = `/api/project/${currentSlug}/images/${cid}.png?t=${Date.now()}`;

      imgCard.innerHTML = `
        <div class="image-card-preview">
          ${isCompleted
            ? `<img src="${imgSrc}" alt="${cid}" onerror="this.parentElement.innerHTML='<div class=\\'image-placeholder\\'>Rendered file not found on disk</div>'">`
            : `<div class="image-placeholder">&#9654; Ready to Render (${illus.width}x${illus.height})</div>`}
        </div>
        <div class="image-card-body">
          <div class="card-header" style="margin-bottom: 4px;">
            <span class="chunk-id">${cid}</span>
            <span class="badge ${isCompleted ? 'badge-online' : 'badge-accent'}">${illus.status}</span>
          </div>
          <p style="font-size: 0.82rem; color: var(--text-dim); line-height: 1.35; flex-grow: 1;">${illus.prompt || ""}</p>
          <div style="margin-top: 10px; display: flex; gap: 8px;">
            <button class="btn btn-sm btn-primary btn-tweak-rerun" data-chunk-id="${cid}">
              ${isCompleted ? '&#8635; Tweak &amp; Regenerate' : '&#9654; Render Scene'}
            </button>
          </div>
        </div>
      `;

      imgCard.querySelector(".btn-tweak-rerun").addEventListener("click", () => {
        openTweakModal(block);
      });

      gallery.appendChild(imgCard);
    });

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
  const illus = block.illustration;
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
  showToast(`Rendering ${cid} in ComfyUI...`);

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
      loadReaderPreview();
    } else {
      showToast("Rendering error: " + data.error, "error");
    }
  } catch (err) {
    showToast("Network error: " + err, "error");
  }
}

async function startBatchRender() {
  const wf = document.getElementById("selectWorkflow").value;
  const pbox = document.getElementById("renderProgressBox");
  pbox.style.display = "block";
  document.getElementById("renderStatusText").innerHTML = `<span class="spinner"></span> Dispatching batch to ComfyUI...`;
  document.getElementById("renderProgressBar").style.width = "20%";

  try {
    const res = await fetch(`/api/project/${currentSlug}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow: wf })
    });
    const data = await res.json();
    if (data.success) {
      document.getElementById("renderProgressBar").style.width = "100%";
      document.getElementById("renderStatusText").textContent = "Batch render completed!";
      showToast("All illustrations completed successfully!");
      await loadManifest();
      loadReaderPreview();
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

// ----------------------------------------------------------------------------
// Phase 3: Reader Preview
// ----------------------------------------------------------------------------
function loadReaderPreview() {
  const iframe = document.getElementById("readerIframe");
  const url = `/api/project/${currentSlug}/reader?t=${Date.now()}`;
  iframe.src = url;
  const btnOpen = document.getElementById("btnOpenReaderTab");
  if (btnOpen) btnOpen.href = url;
  const btnDownload = document.getElementById("btnDownloadReader");
  if (btnDownload) {
    btnDownload.href = `/api/project/${currentSlug}/reader?download=1`;
    btnDownload.download = `${currentSlug}_illustrated.html`;
  }
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
  document.getElementById("btnCompileReader").addEventListener("click", compileReader);

  // Save source text
  document.getElementById("btnSaveSource").addEventListener("click", async () => {
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
    item.innerHTML = `
      <div class="card-header">
        <input type="text" class="text-input char-name-input" placeholder="Character Name" style="font-weight: 600; width: 60%;">
        <button class="btn btn-sm btn-danger btn-del-char">&times;</button>
      </div>
      <textarea class="textarea-input char-desc-input" rows="3" placeholder="Visual traits, clothing, age..."></textarea>
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
    const slug = document.getElementById("newStorySlug").value.trim();
    const text = document.getElementById("newStoryText").value;
    if (!slug) return showToast("Slug is required", "error");

    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, story_text: text })
    });
    if (res.ok) {
      document.getElementById("modalNewProject").style.display = "none";
      showToast(`Created story: ${slug}`);
      await loadProjects();
      document.getElementById("projectSelect").value = slug;
      loadProjectData(slug);
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
}

// Start on DOM ready
document.addEventListener("DOMContentLoaded", init);
