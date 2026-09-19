# Story Illustrator — Code Review

**Date:** September 18, 2026  
**Scope:** Full codebase review covering performance, security, and code quality  

---

## Summary

| Severity | Security | Performance | Code Quality | Total |
|----------|----------|-------------|--------------|-------|
| 🔴 Critical | 1 | — | — | **1** |
| 🟠 High | 1 | 2 | 1 | **4** |
| 🟡 Medium | — | 2 | 1 | **3** |
| 🟢 Low | 1 | 1 | 3 | **5** |
| **Total** | **3** | **5** | **5** | **13** |

---

## 🔴 Critical

### 1. Debug Mode Enabled on Public Network Interface

| | |
|---|---|
| **File** | [`web_server.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/web_server.py) — Line 636 |
| **Category** | Security |

**Issue:** The Flask app is launched with `app.run(host="0.0.0.0", port=5000, debug=True)`. Binding Werkzeug's development server to all network interfaces with the interactive debugger enabled allows **anyone on the network to execute arbitrary Python code** via the Werkzeug debugger console.

> [!CAUTION]
> This is a remote code execution (RCE) vulnerability. Any machine on the same network can open the debugger and run arbitrary Python.

**Fix:** Change to `debug=False` in the direct-execution path, or bind only to `127.0.0.1`. The `webui.py` launcher already uses `debug=False`, but running `web_server.py` directly exposes this.

```python
# Before
app.run(host="0.0.0.0", port=5000, debug=True)

# After
app.run(host="127.0.0.1", port=5000, debug=False)
```

---

## 🟠 High

### 2. Path Traversal via Unsanitized Project Slug

| | |
|---|---|
| **File** | [`web_server.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/web_server.py) — Lines 46–50 |
| **Category** | Security |

**Issue:** The `slug` parameter from Flask routes is not sanitized against path traversal. On Windows, backslashes (`\`, encoded as `%5C`) can be used to escape the `projects` directory and read/write arbitrary files on the filesystem (e.g., `foo\..\..\Windows`).

**Fix:** Sanitize the slug before constructing paths:

```python
from werkzeug.utils import secure_filename

@app.route("/api/project/<slug>/...")
def some_route(slug):
    safe_slug = secure_filename(slug)
    project_dir = os.path.join(PROJECTS_DIR, safe_slug)
    # ...
```

---

### 3. Synchronous Long-Running AI Operations Block the Web Server

| | |
|---|---|
| **File** | [`web_server.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/web_server.py) — Lines 408–422, 463–468, 504 |
| **Category** | Performance |

**Issue:** Endpoints like `/api/project/<slug>/run_stage` and `/render` perform LLM calls and ComfyUI renders synchronously on Flask's worker threads. This blocks the entire server from handling other requests — including UI polling for progress updates — during operations that can take minutes.

**Fix:** Offload long-running work to a background task queue (e.g., `concurrent.futures.ThreadPoolExecutor`, Celery, or RQ). Return a task ID immediately and let the frontend poll for completion:

```python
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=2)

@app.route("/api/project/<slug>/run_stage", methods=["POST"])
def run_stage(slug):
    future = executor.submit(_run_stage_work, slug, request.json)
    return jsonify({"task_id": id(future), "status": "started"})
```

---

### 4. PDF Export Retains Full Canvas State for Every Page in Memory

| | |
|---|---|
| **File** | [`book_exporter.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/book_exporter.py) — Lines 203–213 |
| **Category** | Performance |

**Issue:** The `NumberedCanvas` class implements two-pass PDF generation by storing `dict(self.__dict__)` for every page in `_saved_page_states`. This retains heavy drawing state objects (including rendered image data), leading to massive memory consumption and potential OOM crashes on large illustrated books.

**Fix:** Only save lightweight metadata (page number, page size) instead of the full canvas `__dict__`. Draw decorations in a deferred pass using only that metadata:

```python
def showPage(self):
    self._saved_page_states.append({
        "page_number": self._pageNumber,
        "page_size": self._pagesize,
    })
    canvas.Canvas.showPage(self)
```

---

### 5. Visual Bible Descriptions Grow Unbounded Across Batches

| | |
|---|---|
| **File** | [`build_manifest.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/build_manifest.py) — Lines 251, 264 |
| **Category** | Code Quality / Performance |

**Issue:** Character and setting descriptions are accumulated by string concatenation with semicolons (e.g., `f"{existing_val}; {cdesc}"`). Since LLMs return semantically similar but textually different descriptions, these strings grow uncontrollably, ballooning the context window and wasting tokens on subsequent prompts.

**Fix:** Deduplicate descriptions more intelligently:
- Use a small LLM summarization call to merge new traits into the existing profile.
- Or keep only the most detailed single description, replacing rather than appending.

---

## 🟡 Medium

### 6. Blocking Directory Walk on Every Project List Request

| | |
|---|---|
| **File** | [`web_server.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/web_server.py) — Line 116 |
| **Category** | Performance |

**Issue:** The `/api/projects` route uses `os.walk(images_dir)` to enumerate all image files for every project on every request. This O(N) traversal blocks the server thread and slows down proportionally to the number of projects and images.

**Fix:** Cache project metadata (including image counts) and invalidate on file changes, or use `os.scandir()` / `pathlib.Path.glob('*.png')` instead of a full recursive walk.

---

### 7. EPUB Export Reads Entire Images Into Memory

| | |
|---|---|
| **File** | [`book_exporter.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/book_exporter.py) — Line 537 |
| **Category** | Performance |

**Issue:** When building the EPUB archive, images are fully loaded into memory via `f.read()` before being written with `zf.writestr()`. For books with many high-resolution images, this causes unnecessary memory spikes.

**Fix:** Use `zf.write()` to stream directly from disk:

```python
# Before
with open(img_path, "rb") as f:
    zf.writestr(dest_path, f.read())

# After
zf.write(img_path, dest_path)
```

---

### 8. Mixing `asyncio.run()` Inside Synchronous Methods

| | |
|---|---|
| **File** | [`comfy_client.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/comfy_client.py) — Line 352 |
| **Category** | Code Quality |

**Issue:** `asyncio.run()` is called inside the synchronous `render` method to track WebSocket execution. This creates a new event loop on each call, blocks the calling thread entirely, and conflicts with any existing event loop (e.g., if Flask is running with an async adapter).

**Fix:** Either refactor `render` to be fully `async`, or manage a dedicated background thread with a persistent event loop for WebSocket communication.

---

## 🟢 Low

### 9. Incomplete HTML Escaping in Build Script

| | |
|---|---|
| **File** | [`build_site.cjs`](file:///c:/Users/Shortbus/Story%20illustrator/build_site.cjs) — Lines 23–28 |
| **Category** | Security |

**Issue:** The `escapeHtml` function escapes `<`, `>`, and `&`, but does not escape quotes (`"` or `'`). If this function is reused for attribute contexts, it opens the door to Cross-Site Scripting (XSS).

**Fix:**
```javascript
function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
```

---

### 10. Thread-Blocking `time.sleep()` in LLM Retry Logic

| | |
|---|---|
| **File** | [`llm_client.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/llm_client.py) — Lines 237, 282 |
| **Category** | Performance |

**Issue:** `time.sleep(backoff ** attempt)` blocks the entire thread during retry backoffs. Combined with synchronous Flask routes, the web thread is completely paralyzed during the wait.

**Fix:** If moving to async, use `asyncio.sleep()`. Otherwise, this is acceptable in a task-queue worker but should not run on a Flask request thread.

---

### 11. Sentence-Splitting Regex Breaks on Quoted Dialogue

| | |
|---|---|
| **File** | [`chunker.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/chunker.py) — Line 46 |
| **Category** | Code Quality |

**Issue:** The regex `r"(?<=[.!?])\s+"` splits on any whitespace following sentence-ending punctuation, but ignores closing quotation marks. This incorrectly splits dialogue like `"Stop!" he yelled.` into two chunks.

**Fix:**
```python
# Before
r"(?<=[.!?])\s+"

# After — account for optional closing quotes
r"(?<=[.!?][\"'"']?)\s+"
```

---

### 12. Silenced Exceptions Hide Bugs

| | |
|---|---|
| **File** | [`web_server.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/web_server.py) — Lines 77, 201, 261, 460 |
| **Category** | Code Quality |

**Issue:** Broad `except Exception: pass` blocks are used when loading configurations or updating files. This silently swallows genuine errors like JSON parse failures or filesystem permission issues, making debugging very difficult.

**Fix:** Catch specific exceptions and log them:

```python
# Before
try:
    data = json.load(f)
except Exception:
    pass

# After
import logging
logger = logging.getLogger(__name__)

try:
    data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning("Failed to load config: %s", e)
```

---

### 13. Local Imports Violate PEP-8 Conventions

| | |
|---|---|
| **Files** | [`build_manifest.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/build_manifest.py) L42, [`render_images.py`](file:///c:/Users/Shortbus/Story%20illustrator/pipeline/render_images.py) L43 |
| **Category** | Code Quality |

**Issue:** `import requests` is placed inside `check_runtime_readiness()` functions instead of at the top of the file, violating PEP-8 import conventions.

**Fix:** Move `import requests` to the top-level import block.

---

## Recommended Priority Order

The following order balances risk and effort:

1. **Fix #1** (Debug mode) — trivial one-line fix, eliminates RCE
2. **Fix #2** (Path traversal) — small fix, eliminates filesystem access vulnerability
3. **Fix #9** (HTML escaping) — small fix, hardens against future XSS
4. **Fix #12** (Silenced exceptions) — incremental, immediately improves debuggability
5. **Fix #7** (EPUB memory) — one-line change, big memory improvement
6. **Fix #4** (PDF memory) — moderate refactor, prevents OOM on large books
7. **Fix #3** (Async operations) — larger architectural change, biggest UX/performance win
8. **Fix #5** (Visual Bible growth) — moderate refactor, reduces token waste
9. **Fix #6** (Directory caching) — moderate, scales with project count
10. **Fix #11** (Chunker regex) — small fix, improves text processing accuracy
11. **Fix #8** (asyncio mixing) — refactor, best done alongside #3
12. **Fix #10** (Sleep blocking) — best addressed as part of #3
13. **Fix #13** (Import style) — cosmetic, low priority
