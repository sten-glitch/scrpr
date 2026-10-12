"use strict";

(function () {
  const byId = (id) => document.getElementById(id);
  const form = byId("scanForm");
  const imagesInput = byId("imageFiles");
  const preview = byId("previews");
  const analyzeBtn = byId("analyzeButton");
  const error = byId("error");
  let urls = [];
  let lastResult = null;

  const labels = {
    CONFLICT_DETECTED: "Conflict detected",
    HIGH_RISK_REVIEW: "High-risk review",
    REVIEW_REQUIRED: "Evidence still missing",
    VISUALLY_CONSISTENT_NOT_AUTHENTICATED: "Visually consistent — not authenticated",
    NO_CHECKABLE_CLAIMS: "No verifiable claims",
  };

  function showError(message) {
    error.textContent = String(message || "Unknown error");
    error.hidden = false;
  }

  function clearError() {
    error.hidden = true;
    error.textContent = "";
  }

  function appendText(parent, tag, text, className) {
    const el = document.createElement(tag);
    el.textContent = String(text == null ? "" : text);
    if (className) el.className = className;
    parent.appendChild(el);
    return el;
  }

  function displayPreview() {
    urls.forEach((u) => URL.revokeObjectURL(u));
    urls = [];
    preview.replaceChildren();
    const files = Array.from(imagesInput.files || []).slice(0, 4);
    files.forEach((file) => {
      if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) return;
      const url = URL.createObjectURL(file);
      urls.push(url);
      const image = document.createElement("img");
      image.src = url;
      image.alt = file.name;
      image.className = "thumb";
      preview.appendChild(image);
    });
  }

  function readPhoto(file) {
    return new Promise((resolve, reject) => {
      if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
        reject(new Error("Only JPG, PNG and WebP are supported."));
        return;
      }
      if (!file.size || file.size > 5 * 1024 * 1024) {
        reject(new Error("Each photo must be at most 5 MiB."));
        return;
      }
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("Could not read photo locally."));
      reader.onload = () => {
        const result = reader.result;
        if (typeof result !== "string" || !result.includes(";base64,")) {
          reject(new Error("Invalid photo data."));
          return;
        }
        resolve({ mime: file.type, base64: result.split(";base64,", 2)[1] });
      };
      reader.readAsDataURL(file);
    });
  }

  function render(data) {
    lastResult = data;
    clearError();
    byId("empty").hidden = true;
    byId("results").hidden = false;
    byId("download").hidden = false;

    const truth = data.listing_truth || {};
    const counts = truth.counts || {};
    const status = truth.status || "REVIEW_REQUIRED";
    byId("status").textContent = labels[status] || status;
    byId("conflicts").textContent = counts.CONTRADICTION || 0;
    byId("unverified").textContent = (counts.UNVERIFIED || 0) + (counts.QUALIFIED_CLAIM || 0);
    const vision = data.visual_evidence || {};
    const observations = vision.observations || [];
    byId("objects").textContent = observations.length;

    const analyzed = data.image_analysis || {};
    let summary = "Seller claims remain unverified without independent visual and transaction evidence.";
    if (analyzed.mode === "cv_unavailable") {
      summary = "OpenCV/OCR unavailable. Photographs were NOT automatically recognized. Claims need manual inspection.";
    } else if (analyzed.mode === "opencv_offline") {
      summary = "Local OpenCV/OCR produced provisional detections. Exact printing, grade and authenticity remain unverified.";
    } else if (analyzed.mode === "manual_observations") {
      summary = "Evaluation based on manually supplied observation JSON. BIGSTEN has not independently authenticated it.";
    } else if (data.status === "TEXT_ONLY_NO_VISUAL_PROOF") {
      summary = "Text-only analysis: no card photographs were inspected.";
    }
    byId("subtitle").textContent = summary;

    const findings = byId("findings");
    findings.replaceChildren();
    const list = truth.findings || [];
    if (!list.length) {
      appendText(findings, "p",
        "No structured grading/edition/sealed claims were found. Other inaccuracies may still exist.", "block-hint");
    }
    list.forEach((item) => {
      const box = appendText(findings, "div", "", "finding " + String(item.status || ""));
      appendText(box, "strong", item.claim);
      appendText(box, "small",
        String(item.status || "UNVERIFIED") + " · " + String(item.claim_source || "seller"));
      appendText(box, "p", item.explanation);
    });

    const visualMatches = byId("visualMatches");
    visualMatches.replaceChildren();
    const matchRows = data.visual_reference_matches || [];
    if (!matchRows.length) {
      appendText(visualMatches, "p",
        "No private reference index loaded, or no valid photo regions. To enable image matching, build your own rights-cleared image index locally.", "block-hint");
    } else {
      matchRows.slice(0, 20).forEach((match) => {
        const area = appendText(visualMatches, "div", "", "finding");
        appendText(area, "strong",
          "Object #" + (Number(match.observation_index) + 1) + " — " + (match.status || "ABSTAIN"));
        appendText(area, "p", match.reason || "Manual verification required");
        const candidates = Array.isArray(match.candidates) ? match.candidates : [];
        candidates.slice(0, 3).forEach((candidate) => {
          appendText(area, "small",
            String(candidate.identity_key || "?") + " · pHash distance " +
            String(candidate.phash_distance) + " · ORB " +
            String(candidate.orb_good_matches) + " — NOT VERIFIED");
        });
      });
    }
    const suggested = byId("candidates");
    suggested.replaceChildren();
    const suggestions = data.catalog_suggestions || [];
    const populated = suggestions.filter((row) => Array.isArray(row.candidates) && row.candidates.length);
    if (!populated.length) {
      appendText(suggested, "p",
        "No catalog candidate available. Add a local TCGdex metadata index and a readable card name/number. Suggestions do not prove identity.", "block-hint");
    }
    populated.slice(0, 12).forEach((row) => {
      const top = row.candidates.slice(0, 3);
      const area = appendText(suggested, "div", "", "finding");
      appendText(area, "strong", "Observed object #" + (Number(row.observation_index) + 1));
      top.forEach((item) => {
        appendText(area, "p",
          String(item.name || "Unknown") + " — " + String(item.set || "?") +
          " #" + String(item.number || "?") + " · " + String(item.finish || "?") +
          " · " + String(item.language || "?") + " — CANDIDATE ONLY");
      });
    });
    const assessment = data.assessment || {};
    let finance = "No financial evaluation: a text-only listing cannot demonstrate card identity, real comps or cost.";
    if (data.assessment) {
      finance = "Decision: " + String(assessment.decision || "REVIEW") +
        ". Estimated ROI: " +
        (assessment.roi == null ? "UNKNOWN" : (100 * Number(assessment.roi)).toFixed(1) + "%") +
        ". Profit: " + (assessment.net_profit_eur == null ?
          "UNKNOWN" : Number(assessment.net_profit_eur).toFixed(2) + " EUR") +
        ". Financial comparables and full costs require independent verification.";
    }
    byId("financial").textContent = finance;
    const questions = [
      ...(data.open_questions || []),
      ...(assessment.warnings || []),
      ...(analyzed.notes || []),
    ];
    if (!questions.length) questions.push("Confirm photo identity, authenticity, market comps and full costs.");
    const unique = [...new Set(questions.map(String))];
    const questionsNode = byId("questions");
    questionsNode.replaceChildren();
    unique.slice(0, 20).forEach((item) => appendText(questionsNode, "li", item));
  }

  imagesInput.addEventListener("change", displayPreview);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = "Analyzing locally…";
    try {
      const files = Array.from(imagesInput.files || []);
      if (files.length > 4) throw new Error("Please select up to 4 photographs.");
      if (files.reduce((s, f) => s + f.size, 0) > 8 * 1024 * 1024) {
        throw new Error("Please keep total image size under 8 MiB.");
      }
      const price = Number(byId("price").value);
      if (!Number.isFinite(price) || price <= 0) {
        throw new Error("Enter a positive asking price in EUR.");
      }
      const payload = {
        title: byId("title").value,
        description: byId("description").value,
        kind: byId("kind").value,
        asking_eur: price,
        images: await Promise.all(files.map(readPhoto)),
      };
      const observationText = byId("manualObs").value.trim();
      if (observationText) {
        try {
          payload.observation = JSON.parse(observationText);
        } catch (_error) {
          throw new Error("Observation JSON is invalid. Check commas, quotes and bounding boxes.");
        }
      }
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        credentials: "same-origin",
        cache: "no-store",
      });
      const parsed = await res.json();
      if (!res.ok) throw new Error(parsed.error || "Could not analyze the listing.");
      render(parsed);
    } catch (err) {
      showError(err && err.message ? err.message : err);
    } finally {
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = "Analyze evidence →";
    }
  });

  byId("download").addEventListener("click", () => {
    if (!lastResult) return;
    const blob = new Blob([JSON.stringify(lastResult, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "bigsten-local-evidence.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
