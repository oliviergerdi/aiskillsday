const form = document.querySelector("#comparison-form");
const submit = form.querySelector('[type="submit"]');
const output = document.querySelector(".run-output");
const statusText = document.querySelector("#run-status");
const consoleOutput = document.querySelector("#run-console");
const report = document.querySelector("#run-report");
const toyDemo = {
  before: location.origin + "/v1",
  after: location.origin + "/v2",
  seeds: "fixtures/seeds.yaml",
};
const toyIntent = document.querySelector('[data-preset="toy"]').dataset.intent.trim();
const sourceTypes = {
  api: ["https://example.com/api", "nParity looks for a spec at this URL. Without specs for both sides, it compares one GET response per URL."],
  endpoint: ["https://example.com/api/items/1", "Limited comparison. nParity compares one GET response per URL and cannot discover endpoints or check schemas."],
  spec: ["https://example.com/openapi.json", "Enter a spec URL or a local JSON or YAML path. Leave it blank and give an endpoint URL below to compare a single response."],
  manifest: ["samples/api-versions/manifest.json#openfoodfacts_product", "Enter a local JSON manifest path. Add #pair_name to select a pair. For saved responses, use a manifest on both sides."],
};

function updateSource(panel) {
  const { side } = panel.dataset;
  const kind = form.elements[side + "_kind"].value;
  const [placeholder, hint] = sourceTypes[kind];
  form.elements[side + "_source"].placeholder = placeholder;
  panel.querySelector("[data-source-hint]").textContent = hint;
  const showBase = kind === "spec" || kind === "manifest";
  panel.querySelector("[data-base-field]").hidden = !showBase;
  panel.querySelector("[data-base-hint]").textContent = kind === "spec" ? "(required if the spec is blank)" : "(optional)";
  form.elements[side + "_base"].disabled = !showBase;
  form.elements[side + "_source"].required = kind !== "spec";
}

const panels = Array.from(form.querySelectorAll("[data-side]"));
for (const panel of panels) {
  panel.querySelector("select").addEventListener("change", () => updateSource(panel));
  updateSource(panel);
}

function updateFlowSettings() {
  const flowMapping = form.elements.flow_mapping.checked;
  for (const name of ["contract_only", "seeds", "samples", "discover_from"]) {
    form.elements[name].disabled = flowMapping;
  }
  form.elements.intent_text.required = !flowMapping;
}

form.elements.flow_mapping.addEventListener("change", updateFlowSettings);
updateFlowSettings();

const rerunSelect = document.querySelector("#rerun-config");
const rerunBaseline = document.querySelector("#rerun-baseline");
const rerunSummary = document.querySelector("#rerun-summary");
const rerunTitle = document.querySelector("#rerun-title");
const rerunStart = document.querySelector("#rerun-start");
const rerunEdit = document.querySelector("#rerun-edit");
let loadedConfig = null;   // the configuration currently shown in the rerun menu
let hasPreviousRuns = false;

function updateRunLabel() {
  const baseline = rerunBaseline.value;
  const compare = baseline === "auto" ? hasPreviousRuns : baseline !== "";
  const action = compare ? "Rerun" : "Run";
  rerunTitle.textContent = action + " a configuration";
  rerunStart.textContent = action;
}

function option(value, label) {
  const o = document.createElement("option");
  o.value = value;
  o.textContent = label;
  return o;
}

const presets = document.querySelectorAll("[data-preset]");
for (const button of presets) {
  button.addEventListener("click", () => {
    const toy = button.dataset.preset === "toy";
    const before = toy ? toyDemo.before : "https://petstore.swagger.io/v2";
    const after = toy ? toyDemo.after : "https://petstore3.swagger.io/api/v3";
    const values = {
      before_kind: toy ? "api" : "spec",
      after_kind: toy ? "api" : "spec",
      before_source: toy ? before : before + "/swagger.json",
      after_source: toy ? after : after + "/openapi.json",
      before_base: toy ? "" : before,
      after_base: toy ? "" : after,
      name: toy ? "toy" : "petstore",
      backend: toy ? "fake" : "flash",
      seeds: toy ? toyDemo.seeds : "fixtures/petstore/seeds.yaml",
      samples: "",
      discover_from: "",
      intent_text: button.dataset.intent,
      intent: "",
    };
    for (const [name, value] of Object.entries(values)) form.elements[name].value = value;
    form.elements.contract_only.checked = false;
    form.elements.flow_mapping.checked = false;
    updateFlowSettings();
    for (const panel of panels) updateSource(panel);
    form.querySelector(".run-settings").open = true;
  });
}

function when(iso) {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function loadConfig(name) {
  loadedConfig = null;
  rerunBaseline.replaceChildren();
  updateRunLabel();
  const data = await getJSON("/comparisons/" + encodeURIComponent(name), { cache: "no-store" });
  if (rerunSelect.value !== name) return;
  loadedConfig = data.config;
  hasPreviousRuns = data.runs.length > 0;
  const c = data.config;
  rerunSummary.textContent = `${c.before.source || c.before.base_url} → ${c.after.source || c.after.base_url} · ${c.backend}${c.flow_mapping ? " · flow mapping" : c.score ? " · scored" : ""}`;
  const choices = [option("auto", hasPreviousRuns ? `Latest: ${when(data.runs[0].started_at)} (${data.runs[0].open} open)` : "Latest (no runs yet)")];
  for (const r of data.runs) choices.push(option(r.id, `${when(r.started_at)} · ${r.open} open · ${r.id}`));
  choices.push(option("", "None"));
  rerunBaseline.replaceChildren(...choices);
  updateRunLabel();
}

async function loadConfigs() {
  try {
    const configs = await getJSON("/comparisons", { cache: "no-store" });
    rerunSelect.replaceChildren(...configs.map((c) => option(c.name, `${c.name} (${c.backend})`)));
    if (configs.length) await loadConfig(configs[0].name);
    else rerunSummary.textContent = "No saved configurations yet. Tick “Save as configuration” below.";
  } catch (error) {
    rerunSummary.textContent = error.message;
  }
}

rerunSelect.addEventListener("change", () => loadConfig(rerunSelect.value).catch(showError));
rerunBaseline.addEventListener("change", updateRunLabel);

rerunEdit.addEventListener("click", () => {
  if (!loadedConfig) return;
  const c = loadedConfig;
  const values = {
    before_kind: c.before.kind, before_source: c.before.source, before_base: c.before.base_url || "",
    after_kind: c.after.kind, after_source: c.after.source, after_base: c.after.base_url || "",
    before_headers: (c.before.headers || []).join("; "), after_headers: (c.after.headers || []).join("; "),
    name: c.name, backend: c.backend, seeds: c.seeds, intent: c.intent,
    samples: c.samples || "", discover_from: (c.discover_from || []).join("; "),
  };
  for (const [name, value] of Object.entries(values)) form.elements[name].value = value;
  form.elements.contract_only.checked = Boolean(c.contract_only);
  form.elements.flow_mapping.checked = Boolean(c.flow_mapping);
  updateFlowSettings();
  for (const panel of panels) updateSource(panel);
  form.querySelector(".run-settings").open = true;
  form.scrollIntoView({ block: "start" });
});

rerunStart.addEventListener("click", () => {
  if (loadedConfig) startJob({ ...loadedConfig, baseline: rerunBaseline.value });
});

function setRunning(running) {
  submit.disabled = running;
  rerunStart.disabled = running;
}

const stepItems = Array.from(document.querySelectorAll("#run-steps li"));
const opening = document.querySelector("#run-opening");

function renderSteps(job) {
  const current = stepItems.findIndex((li) => li.dataset.step === job.stage);
  const last = job.lines.at(-1) || "";
  const failedMessage = last.startsWith("Error: ") ? last.slice(7) : job.error?.message || "";
  stepItems.forEach((li, index) => {
    let state = "waiting";
    if (job.state === "complete" || index < current) state = "done";
    else if (index === current) state = job.state === "failed" ? "failed" : "running";
    li.dataset.state = state;
    li.querySelector(".run-step-marker").textContent = state;
    const slot = li.querySelector(".run-step-error");
    slot.textContent = state === "failed" ? failedMessage : "";
    slot.hidden = state !== "failed";
  });
}

let openTimer = null;

function resetConsole() {
  clearTimeout(openTimer);
  output.hidden = false;
  report.hidden = true;
  report.removeAttribute("href");
  opening.hidden = true;
  renderSteps({ state: "running", stage: null, lines: [] });
  consoleOutput.replaceChildren();
}

function appendLine(line) {
  const follow = consoleOutput.scrollHeight - consoleOutput.scrollTop - consoleOutput.clientHeight < 16;
  consoleOutput.append(document.createTextNode(line + "\n"));
  if (follow) consoleOutput.scrollTop = consoleOutput.scrollHeight;
}

async function getJSON(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "Check the comparison inputs.");
    error.status = response.status;
    error.detail = data.detail;
    throw error;
  }
  return data;
}

function clearFieldErrors() {
  for (const slot of form.querySelectorAll("[data-error-for]")) {
    slot.hidden = true;
    slot.textContent = "";
  }
  for (const element of form.elements) element.removeAttribute("aria-invalid");
}

function showFieldError(field, message) {
  const slot = form.querySelector(`[data-error-for="${field}"]`) || form.querySelector('[data-error-for="form"]');
  slot.textContent = message;
  slot.hidden = false;
  const details = slot.closest("details");
  if (details) details.open = true;
  form.elements[field]?.setAttribute("aria-invalid", "true");
}

function fieldFromLoc(loc) {
  const path = loc.slice(1);
  if (path[0] === "before" || path[0] === "after") {
    const part = { source: "source", base_url: "base" }[path[1]];
    return part && path[0] + "_" + part;
  }
  return path[0];
}

async function followJob(url) {
  let seen = 0;
  let sawRunning = false;
  while (true) {
    const job = await getJSON(url, { cache: "no-store" });
    for (const line of job.lines.slice(seen)) appendLine(line);
    seen = job.lines.length;
    renderSteps(job);
    if (job.state === "running") {
      sawRunning = true;
      statusText.textContent = "Running";
      await new Promise((resolve) => setTimeout(resolve, 400));
      continue;
    }
    statusText.textContent = job.state === "complete" ? "Complete" : "Failed";
    if (job.error) showFieldError(job.error.field, job.error.message);
    if (job.report_url) {
      report.href = job.report_url;
      report.hidden = false;
    }
    if (job.state === "complete" && sawRunning) {
      opening.hidden = false;
      openTimer = setTimeout(() => location.replace(job.report_url), 1500);
    }
    return;
  }
}

function showError(error) {
  statusText.textContent = "Error";
  if (error.status === 422 && Array.isArray(error.detail)) {
    let unmapped = false;
    for (const entry of error.detail) {
      const field = fieldFromLoc(entry.loc);
      if (field && form.querySelector(`[data-error-for="${field}"]`)) showFieldError(field, entry.msg);
      else unmapped = true;
    }
    if (!unmapped) return;
  }
  showFieldError("form", error.message);
}

async function startJob(body) {
  resetConsole();
  output.scrollIntoView({ block: "start" });
  statusText.textContent = "Starting";
  setRunning(true);
  try {
    const { job_url } = await getJSON("/run-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const url = new URL(location.href);
    url.searchParams.set("job", job_url.split("/").at(-1));
    history.replaceState(null, "", url);
    await followJob(job_url);
    loadConfigs();
  } catch (error) {
    showError(error);
  } finally {
    setRunning(false);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const values = new FormData(form);
  const source = (side) => ({
    kind: values.get(side + "_kind"),
    source: values.get(side + "_source").trim(),
    base_url: values.get(side + "_base")?.trim() || "",
    headers: (values.get(side + "_headers") || "").split(/[;\n]/).map((h) => h.trim()).filter(Boolean),
  });
  const before = source("before");
  const after = source("after");
  const backend = values.get("backend");
  const seeds = (values.get("seeds") || "").trim();
  const intent = values.get("intent").trim();
  const intentText = values.get("intent_text") ?? "";
  const contractOnly = values.has("contract_only");
  const flowMapping = values.has("flow_mapping");
  const name = values.get("name").trim() || "comparison";
  clearFieldErrors();
  const missing = [
    ["before_source", before.source || (before.kind === "spec" && before.base_url), "Enter a source URL or file path."],
    ["after_source", after.source || (after.kind === "spec" && after.base_url), "Enter a source URL or file path."],
    ["intent_text", contractOnly || flowMapping || intentText.trim(), "Describe what this change was meant to do. Without it every difference is flagged as a regression."],
  ].filter(([, value]) => !value);
  for (const [field, , message] of missing) showFieldError(field, message);
  if (missing.length) {
    form.elements[missing[0][0]].focus();
    return;
  }
  const scoreDemo = before.kind === "api" && before.source === toyDemo.before
    && after.kind === "api" && after.source === toyDemo.after
    && backend === "fake" && seeds === toyDemo.seeds && intentText.trim() === toyIntent;
  const fromConfig = loadedConfig && loadedConfig.name === name ? loadedConfig.score : false;
  startJob({
    before, after, backend, name, seeds, intent, intent_text: intentText,
    samples: (values.get("samples") || "").trim(),
    discover_from: (values.get("discover_from") || "").split(";").map(value => value.trim()).filter(Boolean),
    contract_only: contractOnly,
    flow_mapping: flowMapping,
    score: scoreDemo || fromConfig,
    save_config: values.get("save_config") === "on",
    baseline: "auto",
  });
});

loadConfigs();

const jobId = new URLSearchParams(location.search).get("job");
if (jobId && /^[a-f0-9]{32}$/.test(jobId)) {
  resetConsole();
  setRunning(true);
  followJob("/run-jobs/" + jobId).catch(showError).finally(() => setRunning(false));
}
