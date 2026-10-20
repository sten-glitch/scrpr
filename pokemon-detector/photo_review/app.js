"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const els = {
    select: $("photoSelect"),
    photo: $("photo"),
    frame: $("photoFrame"),
    selection: $("selection"),
    bboxLabel: $("bboxLabel"),
    cases: $("existingLabels"),
    message: $("message"),
    save: $("save")
  };
  const state = { images: [], cases: [], index: 0, box: null, drawing: null };
  let catalogRequest = 0;
  let updatingPhoto = false;

  function text(node, value) {
    node.textContent = String(value == null ? "" : value);
    return node;
  }

  function node(tag, parent, value, className) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value !== undefined) text(el, value);
    parent.appendChild(el);
    return el;
  }

  function notify(message, good) {
    const el = els.message;
    el.hidden = !message;
    el.className = good ? "success" : "alert";
    text(el, message || "");
  }

  function slug(fileName) {
    const raw = fileName.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "_");
    const str = raw.slice(0, 78) || "review";
    return str.length < 4 ? "photo_" + str : str;
  }

  function suggestId(name) {
    const prefix = slug(name);
    const occupied = new Set(state.cases.map((c) => c.case_id));
    for (let i = 1; i <= 500; i++) {
      const candidate = (prefix + "__" + String(i).padStart(2, "0")).slice(0, 100);
      if (!occupied.has(candidate)) return candidate;
    }
    return "case_limit_reached";
  }

  function formatBox(box) {
    return box ? box.map((n) => Number(n).toFixed(3)).join(", ") : "entire image (no crop)";
  }

  function imageRect() {
    return els.photo.getBoundingClientRect();
  }

  function renderBox() {
    const box = state.box;
    text(els.bboxLabel, "Bounding box: " + formatBox(box));
    if (!box || els.photo.hidden) {
      els.selection.style.display = "none";
      return;
    }
    const rect = imageRect();
    const frame = els.frame.getBoundingClientRect();
    const x = rect.left - frame.left + box[0] * rect.width;
    const y = rect.top - frame.top + box[1] * rect.height;
    els.selection.style.left = x + "px";
    els.selection.style.top = y + "px";
    els.selection.style.width = (box[2] - box[0]) * rect.width + "px";
    els.selection.style.height = (box[3] - box[1]) * rect.height + "px";
    els.selection.style.display = "block";
  }

  function pointerCoords(event) {
    const bounds = imageRect();
    if (!bounds.width || !bounds.height) return null;
    const x = (event.clientX - bounds.left) / bounds.width;
    const y = (event.clientY - bounds.top) / bounds.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return null;
    return [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))];
  }

  function drawFrom(start, end) {
    const left = Math.min(start[0], end[0]);
    const top = Math.min(start[1], end[1]);
    const right = Math.max(start[0], end[0]);
    const bottom = Math.max(start[1], end[1]);
    if (right - left < .02 || bottom - top < .02) {
      state.box = null;
    } else {
      state.box = [left, top, right, bottom].map((v) => Number(v.toFixed(5)));
    }
    renderBox();
  }

  els.frame.addEventListener("pointerdown", (event) => {
    if (els.photo.hidden) return;
    const at = pointerCoords(event);
    if (!at) return;
    state.drawing = { start: at, pointerId: event.pointerId };
    els.frame.setPointerCapture(event.pointerId);
    drawFrom(at, at);
  });
  els.frame.addEventListener("pointermove", (event) => {
    if (!state.drawing || state.drawing.pointerId !== event.pointerId) return;
    const bounds = imageRect();
    if (!bounds.width || !bounds.height) return;
    const end = [
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height))
    ];
    drawFrom(state.drawing.start, end);
  });
  function stopDrag(event) {
    if (!state.drawing || state.drawing.pointerId !== event.pointerId) return;
    const old = state.drawing;
    state.drawing = null;
    if (els.frame.hasPointerCapture(event.pointerId)) els.frame.releasePointerCapture(event.pointerId);
    const bounds = imageRect();
    const end = [
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height))
    ];
    if (bounds.width && bounds.height) drawFrom(old.start, end);
  }
  els.frame.addEventListener("pointerup", stopDrag);
  els.frame.addEventListener("pointercancel", () => {
    state.drawing = null;
  });
  els.photo.addEventListener("load", renderBox);
  window.addEventListener("resize", renderBox);

  function currentName() {
    return state.images[state.index] || "";
  }

  function currentCases() {
    return state.cases.filter((row) => row.image_file === currentName());
  }

  function setCase(record) {
    state.box = Array.isArray(record.bbox_xyxy) ? record.bbox_xyxy.slice() : null;
    $("caseId").value = record.case_id;
    $("kind").value = record.kind;
    $("identity").disabled = record.kind === "negative";
    $("photoOrigin").value = record.photo_origin || "unknown";
    $("identity").value = record.expected_identity_key || "";
    $("reviewer").value = record.reviewer || "";
    $("evidence").value = record.annotation_reference || "";
    $("notes").value = record.notes || "";
    $("confirmed").checked = false;
    renderBox();
    notify("Existing label loaded. Confirm the evidence again before saving changes.", true);
  }

  function newCase() {
    state.box = null;
    $("caseId").value = suggestId(currentName());
    $("identity").value = "";
    $("evidence").value = "";
    $("notes").value = "";
    $("confirmed").checked = false;
    $("kind").value = "single";
    $("photoOrigin").value = "real_photo";
    $("identity").disabled = false;
    renderBox();
  }

  function renderCases() {
    const cases = currentCases();
    els.cases.replaceChildren();
    if (!cases.length) node("span", els.cases, "No reviewed labels for this photo yet", "small");
    else {
      for (const item of cases) {
        const b = node("button", els.cases,
          item.case_id + " · " + item.kind, "mini");
        b.type = "button";
        b.addEventListener("click", () => setCase(item));
      }
    }
  }

  function renderProgress() {
    const touched = new Set(state.cases.map((row) => row.image_file));
    const count = state.cases.length;
    const real = new Set(state.cases.filter((row) => row.photo_origin === "real_photo").map((row) => row.image_file));
    text($("progressLabel"),
      count + " reviewed cases · " + real.size + "/50 distinct REAL photographs · " + touched.size + "/" +
      state.images.length + " photos annotated");
    $("progressFill").style.width = Math.min(100, count / 50 * 100) + "%";
    const histogram = {};
    for (const row of state.cases) histogram[row.kind] = (histogram[row.kind] || 0) + 1;
    $("stats").replaceChildren();
    for (const kind of ["single", "binder", "graded", "sealed", "negative"]) {
      const el = node("span", $("stats"));
      node("strong", el, histogram[kind] || 0);
      node("span", el, " " + kind);
    }
  }

  function showPhoto(index) {
    if (!state.images.length) return;
    state.index = (index + state.images.length) % state.images.length;
    const name = currentName();
    els.select.value = name;
    text($("fileName"), (state.index + 1) + " / " + state.images.length + " · " + name);
    els.photo.src = "/api/photo/" + encodeURIComponent(name);
    els.photo.hidden = false;
    $("emptyPhoto").hidden = true;
    $("catalogSearch").value = "";
    ++catalogRequest; // Discard stale asynchronous catalog matches from previous photos.
    $("catalogResults").replaceChildren();
    newCase();
    renderCases();
    notify("", true);
  }

  async function refresh(keepPhoto) {
    const result = await fetch("/api/summary", {cache: "no-store"});
    if (!result.ok) throw new Error("Cannot load private photo library");
    const summary = await result.json();
    const previous = keepPhoto ? currentName() : "";
    state.images = summary.images || [];
    state.cases = summary.cases || [];
    els.select.replaceChildren();
    for (const name of state.images) {
      const option = node("option", els.select, name);
      option.value = name;
    }
    renderProgress();
    if (state.images.length) {
      const desired = state.images.indexOf(previous);
      showPhoto(desired >= 0 ? desired : 0);
    } else {
      $("emptyPhoto").hidden = false;
      text($("emptyPhoto"), "No review photos found in the configured local folder");
    }
  }

  $("photoSelect").addEventListener("change", () => {
    const index = state.images.indexOf(els.select.value);
    if (index >= 0) showPhoto(index);
  });
  $("next").addEventListener("click", () => showPhoto(state.index + 1));
  $("prev").addEventListener("click", () => showPhoto(state.index - 1));
  $("clearBox").addEventListener("click", () => {
    state.box = null;
    renderBox();
  });
  $("addObject").addEventListener("click", () => {
    newCase();
    notify("New card label in the same photo. Draw a separate region to avoid duplicate counts.", true);
  });
  $("kind").addEventListener("change", () => {
    const negative = $("kind").value === "negative";
    if (negative) $("identity").value = "";
    $("identity").disabled = negative;
  });

  $("catalogSearch").addEventListener("input", async () => {
    const query = $("catalogSearch").value.trim();
    const version = ++catalogRequest;
    const results = $("catalogResults");
    results.replaceChildren();
    if (query.length < 2) return;
    try {
      const response = await fetch("/api/catalog?q=" + encodeURIComponent(query), {cache: "no-store"});
      if (!response.ok) return;
      const data = await response.json();
      if (version !== catalogRequest) return;
      for (const item of (data.candidates || [])) {
        const label = [item.name, item.set, item.number, item.finish,
          item.language].filter(Boolean).join(" · ");
        const button = node("button", results, label || item.identity_key);
        button.type = "button";
        button.addEventListener("click", () => {
          $("identity").value = item.identity_key;
          if ($("kind").value === "negative") $("kind").value = "single";
          $("identity").disabled = false;
          results.replaceChildren();
        });
      }
      if (!(data.candidates || []).length) node("p", results, "No matching catalog metadata", "small");
    } catch (_error) {
      if (version === catalogRequest) node("p", results, "Catalog search unavailable", "small");
    }
  });

  $("labelForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    notify("", false);
    if (!currentName()) return notify("No local photo selected", false);
    if (!$("confirmed").checked) return notify("Independent reviewer confirmation is mandatory", false);
    const kind = $("kind").value;
    const row = {
      case_id: $("caseId").value.trim(),
      kind: kind, split: "holdout", photo_origin: $("photoOrigin").value,
      image_file: currentName(),
      expected_identity_key: kind === "negative" ? null : $("identity").value.trim(),
      bbox_xyxy: state.box, annotation_verified: true,
      annotation_reference: $("evidence").value.trim(),
      reviewer: $("reviewer").value.trim(),
      notes: $("notes").value.trim()
    };
    els.save.disabled = true;
    try {
      const response = await fetch("/api/label", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(row), cache: "no-store", credentials: "same-origin"
      });
      const answer = await response.json();
      if (!response.ok) throw new Error(answer.error || "Cannot save reviewed label");
      const prevReviewer = $("reviewer").value;
      await refresh(true);
      $("reviewer").value = prevReviewer;
      notify("Private reviewed label saved. You can add another distinct card region or move to the next photo.", true);
    } catch (err) {
      notify(err && err.message ? err.message : "Could not save label", false);
    } finally {
      els.save.disabled = false;
    }
  });

  refresh(false).catch((err) => {
    notify(err.message || "Photo review app unavailable", false);
  });
})();