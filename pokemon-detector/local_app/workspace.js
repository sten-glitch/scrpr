"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const state = {
    tab: "overview", dashboard: null, listings: [], signals: [],
    selectedId: null, selected: null, busy: false
  };

  const statusActions = {
    INBOX: ["REVIEW", "WATCHLIST", "DISMISSED"],
    REVIEW: ["WATCHLIST", "DISMISSED"],
    WATCHLIST: ["REVIEW", "DISMISSED"],
    DISMISSED: ["WATCHLIST", "REVIEW"],
    PURCHASED: [], SOLD: [], ARCHIVED: []
  };

  function text(parent, tag, content, className) {
    const el = document.createElement(tag);
    el.textContent = content == null ? "" : String(content);
    if (className) el.className = className;
    parent.appendChild(el);
    return el;
  }

  function money(value) {
    return value == null || !Number.isFinite(Number(value))
      ? "—"
      : "€" + Number(value).toLocaleString("en-IE",
        { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function percent(value) {
    return value == null || !Number.isFinite(Number(value))
      ? "—" : (100 * Number(value)).toFixed(1) + "%";
  }
  function elTable(columns) {
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    columns.forEach((column) => text(tr, "th", column));
    thead.appendChild(tr);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);
    const scroller = document.createElement("div");
    scroller.className = "scroll-table";
    scroller.appendChild(table);
    return { root: scroller, body: tbody };
  }
  function cell(row, content, style) {
    return text(row, "td", content, style);
  }
  function badge(status) {
    const el = document.createElement("span");
    el.className = "badge " + String(status || "");
    el.textContent = String(status || "UNKNOWN");
    return el;
  }
  function feedback(message, error) {
    const target = $("toast");
    target.textContent = message;
    target.className = "toast" + (error ? " error" : "");
    target.hidden = false;
    if (feedback.timer) clearTimeout(feedback.timer);
    feedback.timer = setTimeout(() => { target.hidden = true; }, 5700);
  }
  async function request(endpoint, body) {
    const options = { credentials: "same-origin", cache: "no-store" };
    if (body !== undefined) {
      options.method = "POST";
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(endpoint, options);
    let result;
    try { result = await response.json(); }
    catch (_err) { throw new Error("BIGSTEN returned an invalid response"); }
    if (!response.ok) throw new Error(result.error || "Request failed (" + response.status + ")");
    return result;
  }
  function show(tab) {
    state.tab = tab;
    document.querySelectorAll(".page").forEach((page) => {
      page.classList.toggle("active", page.id === tab);
    });
    document.querySelectorAll(".side-btn[data-tab]").forEach((btn) => {
      const selected = btn.dataset.tab === tab;
      btn.classList.toggle("selected", selected);
      btn.setAttribute("aria-current", selected ? "page" : "false");
    });
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  function rowButton(row, label, handler, className) {
    const td = document.createElement("td");
    const btn = text(td, "button", label, className || "secondary");
    btn.addEventListener("click", handler);
    row.appendChild(td);
  }
  function basicRows(items, containerId, limit) {
    const host = $(containerId);
    host.replaceChildren();
    if (!items.length) {
      text(host, "div", "No tracked leads yet. Add one to start your opportunity pipeline.", "panel-empty");
      return;
    }
    const t = elTable(["Opportunity", "Source", "Asking price", "Status", "Review"]);
    items.slice(0, limit).forEach((item) => {
      const tr = document.createElement("tr");
      const name = document.createElement("td");
      text(name, "strong", item.title);
      text(name, "small", (item.kind || "single") + " · " + item.created_at.slice(0, 10));
      tr.appendChild(name);
      cell(tr, item.source);
      cell(tr, money(item.asking_eur), "cell-num");
      const tagCell = document.createElement("td");
      tagCell.appendChild(badge(item.status));
      tr.appendChild(tagCell);
      rowButton(tr, "Inspect →", () => openListing(item.id));
      t.body.appendChild(tr);
    });
    host.appendChild(t.root);
  }
  function renderSignals(host, signals, limit) {
    host.replaceChildren();
    if (!signals.length) {
      text(host, "div", "No imported internal radar signals. Refresh only for research usage; source permissions for commercial use are not yet confirmed.", "panel-empty");
      return;
    }
    const t = elTable(["Reference product", "Lowest ask*", "30-day guide*", "Guide spread", "Next step"]);
    signals.slice(0, limit).forEach((signal) => {
      const row = document.createElement("tr");
      const heading = document.createElement("td");
      text(heading, "strong", signal.card_name);
      text(heading, "small",
        signal.card_set + " #" + signal.card_number + " · " + signal.variant);
      row.appendChild(heading);
      cell(row, money(signal.lowest_ask_eur), "cell-num");
      cell(row, money(signal.guide_reference_eur), "cell-num");
      cell(row, Number(signal.guide_discount_pct).toFixed(1) + "%*", "cell-num positive");
      rowButton(row, "Research →", () => {
        const form = $("leadForm");
        form.elements.title.value = [
          signal.card_name, signal.card_set, signal.card_number,
          signal.variant
        ].filter(Boolean).join(" — ").slice(0, 300);
        form.elements.asking_eur.value = signal.lowest_ask_eur;
        form.elements.source.value = "radar_research";
        form.elements.source_url.value = "";
        form.elements.note.value = (
          "Research only: internal guide spread " +
          Number(signal.guide_discount_pct).toFixed(1) + "%, observed " +
          String(signal.observed_at) + ". No actual listing or sold comps validated."
        ).slice(0, 1000);
        show("add");
        feedback("Research lead prepared. Locate and verify the actual listing before saving.");
      });
      t.body.appendChild(row);
    });
    host.appendChild(t.root);
  }
  function renderDashboard() {
    const d = state.dashboard || {};
    $("statLeads").textContent = d.listings_total ?? "0";
    $("statWatch").textContent = (d.counts || {}).WATCHLIST ?? "0";
    $("statPositions").textContent = d.positions_open ?? "0";
    $("statSignals").textContent = d.signals_total ?? "0";
    $("portOpen").textContent = d.positions_open ?? "0";
    $("portCost").textContent = money(d.position_cost_eur);
    $("portSold").textContent = d.self_reported_sales ?? "0";
    $("portProfit").textContent = money(d.self_reported_realized_profit_eur);
    $("engineLabel").textContent = "Local SQLite · " + (d.listings_total ?? 0) + " records";
    basicRows(state.listings, "recentLeads", 7);
    const filter = $("statusFilter").value;
    basicRows(state.listings.filter((r) => !filter || r.status === filter), "pipelineTable", 300);
    renderSignals($("radarTable"), state.signals, 200);
    renderSignals($("radarPreview"), state.signals, 4);
    $("radarCount").textContent = String(state.signals.length) + " research-only signals";
    const src=(d.sources || [])[0];
    $("feedStatus").textContent = src
      ? "Last imported: " + src.imported_at + " · source: " + src.source_tag
      : "No feed imported. The pinned BIGSTEN Pages snapshot is opt-in and might be unavailable.";
    $("sourcesSummary").textContent = src
      ? "Imported source: " + src.source_tag + ". Snapshots recorded: " + src.snapshots + "."
      : "No market feed snapshot imported into this local database.";
    const portfolioItems = state.listings.filter((r) =>
      ["PURCHASED", "SOLD"].includes(r.status));
    basicRows(portfolioItems, "portfolioTable", 300);
  }
  async function reload() {
    const [dashboard, leads, radar] = await Promise.all([
      request("/api/workspace/dashboard"),
      request("/api/workspace/listings?limit=300"),
      request("/api/workspace/radar")
    ]);
    state.dashboard = dashboard;
    state.listings = leads.items || [];
    state.signals = radar.signals || [];
    renderDashboard();
  }
  function formValues(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    Object.keys(data).forEach((key) => {
      if (data[key] === "") delete data[key];
    });
    return data;
  }
  function setDialogPanels(lead) {
    $("purchasePanel").hidden = lead.status !== "WATCHLIST";
    $("salePanel").hidden = lead.status !== "PURCHASED";
    $("purchaseForm").elements.purchased_at.valueAsDate = new Date();
    $("saleForm").elements.sold_at.valueAsDate = new Date();
    const area = $("statusButtons");
    area.replaceChildren();
    area.appendChild(badge(lead.status));
    (statusActions[lead.status] || []).forEach((target) => {
      const btn = text(area, "button", target === "DISMISSED" ? "Dismiss" : "Move to " + target,
                       target === "DISMISSED" ? "secondary" : "primary");
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await request("/api/workspace/status", { id: lead.id, status: target });
          feedback("Pipeline moved to " + target);
          await reload();
          await openListing(lead.id, true);
        } catch (e) { feedback(e.message, true); btn.disabled = false; }
      });
    });
  }
  function renderEvidence(lead) {
    const area = $("leadEvidence");
    area.replaceChildren();
    const truth = (lead.analysis || {}).listing_truth || {};
    text(area,"strong","Listing Truth Engine: " + (truth.status || "Not evaluated"));
    const findings = truth.findings || [];
    findings.slice(0, 15).forEach((item) => {
      text(area,"p",String(item.status || "") + ": " + String(item.claim || "") +
           " — " + String(item.explanation || ""));
    });
    if (!findings.length) text(area,"p","No independently checkable seller claim was extracted.");
    const analysis = lead.analysis || {};
    const photo = analysis.image_analysis;
    if (photo && photo.images > 0) {
      text(area,"strong","Saved photo analysis");
      text(area,"p",String(photo.images) + " photo(s) reviewed · " +
        String(photo.observations || 0) + " provisional object(s). Original photos are not stored.");
      (analysis.visual_reference_matches || []).slice(0,20).forEach((match) => {
        text(area,"p","Reference result: " + String(match.status || "ABSTAIN"));
        (match.candidates || []).slice(0,3).forEach((candidate) => {
          text(area,"p",String(candidate.identity_key || "Unknown") + " — visual candidate, not verified");
        });
      });
    }
      if (lead.analysis && lead.source !== 'ebay' && !/ebay\./i.test(lead.source_url || '') && !/ebay/i.test(JSON.stringify(lead.analysis))) {
      const download = text(area,"button","Export saved analysis JSON ↓","secondary");
      download.type = "button";
      download.addEventListener("click", () => {
        const blob = new Blob([JSON.stringify(lead.analysis,null,2)],{type:"application/json"});
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href=url;
        link.download="bigsten-analysis-" + lead.id + ".json";
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url),1000);
      });
    }
    text(area,"p","Product images/identity, market sales, inventory and full costs are not certified by this analysis.");
    if (lead.source_url) {
      const link = document.createElement("a");
      link.href = lead.source_url;
      link.rel = "noopener noreferrer";
      link.target = "_blank";
      link.textContent = "Open original source ↗";
      area.appendChild(link);
    }
  }
  function showScenario(data) {
    const box = $("scenarioResults");
    box.replaceChildren();
    const entry = data && data.result;
    if (!entry || entry.status !== "HYPOTHETICAL_ONLY") {
      text(box,"strong","No hypothetical ROI model recorded.");
      return;
    }
    text(box,"strong","Hypothetical ROI: " + percent(entry.roi));
    text(box,"p","Projected net profit: " + money(entry.net_profit_eur) +
      " · Break-even sale price: " + money(entry.break_even_resale_eur));
    text(box,"p","Maximum purchase bid for a 25% projected ROI: " +
      money(entry.max_item_bid_for_25pct_roi_eur));
    text(box,"small","USER ASSUMPTIONS ONLY. No market valuation or sale/liquidity verification.");
  }
  function showTrade(trade) {
    const box = $("tradeSummary");
    box.replaceChildren();
    if (!trade) { text(box,"p","No purchase has been recorded."); return; }
    text(box,"strong","Actual purchase: " + money(trade.total_acquisition_eur) +
      " on " + trade.purchased_at);
    if (trade.sold_at) {
      text(box,"p","User-reported exit: " + money(trade.sale_gross_eur) +
        " · Net result " + money(trade.net_profit_eur) +
        " · ROI " + percent(trade.realized_roi) +
        " · Held " + trade.holding_days + " days.");
    } else text(box,"p","Position remains OPEN. No sale is assumed.");
    text(box,"small","All transactions are " + trade.evidence_status +
      ". A user record is not independent sale verification.");
  }
  async function openListing(identifier, keepOpen) {
    try {
      const lead=await request("/api/workspace/listing?id="+encodeURIComponent(identifier));
      state.selectedId=lead.id;
      state.selected=lead;
      $("dialogTitle").textContent=lead.title;
      $("dialogSubtitle").textContent=lead.source.toUpperCase() +
        " · asking " + money(lead.asking_eur) +
        " · " + lead.kind + " · " + lead.id.slice(0,8);
      setDialogPanels(lead);
      renderEvidence(lead);
      const form=$("scenarioForm");
      form.reset();
      const assumptions = (lead.scenario || {}).assumptions || {};
      Object.keys(assumptions).forEach((key) => {
        const target=form.elements.namedItem(key);
        if (target && assumptions[key] != null) target.value=assumptions[key];
      });
      showScenario(lead.scenario);
      showTrade(lead.trade);
      const trail=$("auditTrail");
      trail.replaceChildren();
      (lead.events || []).forEach((event) => {
        const box=text(trail,"div","", "event");
        text(box,"strong",event.action);
        text(box,"small",event.at);
      });
      if (!keepOpen || !$("leadDialog").open) $("leadDialog").showModal();
    } catch (e) { feedback(e.message,true); }
  }

  document.querySelectorAll("[data-tab]").forEach((el) => {
    el.addEventListener("click", () => show(el.dataset.tab));
  });
  $("statusFilter").addEventListener("change", renderDashboard);
  $("closeDialog").addEventListener("click", () => $("leadDialog").close());
  $("leadForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button=$("saveLead");
    button.disabled=true;
    try {
      const payload=formValues($("leadForm"));
      const result=await request("/api/workspace/listings",payload);
      feedback("Lead stored privately. Open it in Pipeline to model costs.");
      $("leadForm").reset();
      await reload();
      show("pipeline");
      await openListing(result.id);
    } catch (e) { feedback(e.message,true); }
    finally { button.disabled=false; }
  });
  $("refreshRadar").addEventListener("click",async () => {
    const button=$("refreshRadar");
    button.disabled=true;
    button.textContent="Refreshing owner feed…";
    try {
      const result=await request("/api/workspace/radar/refresh",{});
      await reload();
      feedback(result.status+" · "+result.accepted+" guide-only research signals"+
               (result.stale?" · WARNING: source snapshot is stale":""));
    } catch (e) { feedback("Feed unavailable: "+e.message+". Your existing data is unchanged.",true); }
    finally { button.disabled=false; button.textContent="Import current feed ↓"; }
  });
  $("chooseLocalFeed").addEventListener("click", () => $("localFeedFile").click());
  $("localFeedFile").addEventListener("change", async () => {
    const input = $("localFeedFile");
    const file = input.files && input.files[0];
    if (!file) return;
    try {
      if (file.size > 8 * 1024 * 1024) {
        throw new Error("Local snapshot too large for browser import (8 MiB limit).");
      }
      const payload = JSON.parse(await file.text());
      const result = await request("/api/workspace/radar/import-local", { snapshot: payload });
      await reload();
      feedback("Imported " + result.accepted + " internal guide-only research signals" +
        (result.stale ? " (STALE snapshot)" : ""));
    } catch (e) {
      feedback("Snapshot import failed: " + e.message, true);
    } finally {
      input.value = "";
    }
  });

  $("scenarioForm").addEventListener("submit",async (event) => {
    event.preventDefault();
    if (!state.selectedId) return;
    try {
      const assumptions=formValues($("scenarioForm"));
      await request("/api/workspace/scenario",{id:state.selectedId,assumptions});
      feedback("Hypothetical scenario stored (not market evidence)");
      await openListing(state.selectedId,true);
    } catch (e) { feedback(e.message,true); }
  });
  $("purchaseForm").addEventListener("submit",async (event) => {
    event.preventDefault();
    if (!state.selectedId) return;
    try {
      await request("/api/workspace/purchase",{
        id:state.selectedId,...formValues($("purchaseForm"))});
      feedback("Actual purchase recorded as USER-REPORTED, not platform verified");
      await reload(); await openListing(state.selectedId,true);
    } catch (e) { feedback(e.message,true); }
  });
  $("saleForm").addEventListener("submit",async (event) => {
    event.preventDefault();
    if (!state.selectedId) return;
    try {
      await request("/api/workspace/sale",{
        id:state.selectedId,...formValues($("saleForm"))});
      feedback("Sale recorded with net P/L; proof remains user-reported");
      await reload(); await openListing(state.selectedId,true);
    } catch (e) { feedback(e.message,true); }
  });
  $("exportWorkspace").addEventListener("click",async () => {
    try {
      const data=await request("/api/workspace/export");
      const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
      const url=URL.createObjectURL(blob);
      const anchor=document.createElement("a");
      anchor.href=url;
      anchor.download="bigsten-private-workspace.json";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1500);
      feedback("Private workspace exported to your browser downloads");
    } catch (e) { feedback(e.message,true); }
  });
  reload().catch((err) => {
    feedback("Local workspace failed to initialize: "+err.message,true);
  });
})();
