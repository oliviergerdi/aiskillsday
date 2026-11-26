const form = document.querySelector("#comparison-form");
const submit = form.querySelector('[type="submit"]');
const output = document.querySelector(".run-output");
const statusText = document.querySelector("#run-status");
const consoleOutput = document.querySelector("#run-console");
const report = document.querySelector("#run-report");
const presets = document.querySelectorAll("[data-preset]");
const toyDemo = {
  before: location.origin + "/v1",
  after: location.origin + "/v2",
  seeds: "fixtures/seeds.yaml",
};
const toyIntent = document.querySelector('[data-preset="toy"]').dataset.intent.trim();
const sourceTypes = {
  api: ["https://example.com/api", "nParity looks for openapi.json or swagger.json at this URL."],
  spec: ["https://example.com/openapi.json", "Enter a URL or local JSON or YAML path. Set an override if the spec cannot locate its API."],
  manifest: ["samples/api-versions/manifest.json#openfoodfacts_product", "Enter a local JSON manifest path. Add #pair_name to select a pair. For saved responses, use a manifest on both sides."],
};

function updateSource(panel) {
  const { side } = panel.dataset;
  const kind = form.elements[side + "_kind"].value;
  const [placeholder, hint] = sourceTypes[kind];
  form.elements[side + "_source"].placeholder = placeholder;
  panel.querySelector("[data-source-hint]").textContent = hint;
  panel.querySelector("[data-base-field]").hidden = kind === "api";
  form.elements[side + "_base"].disabled = kind === "api";
}

const panels = Array.from(form.querySelectorAll("[data-side]"));
for (const panel of panels) {
  panel.querySelector("select").addEventListener("change", () => updateSource(panel));
  updateSource(panel);
}

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
      intent_text: button.dataset.intent,
      intent: "",
    };
    for (const [name, value] of Object.entries(values)) form.elements[name].value = value;
    for (const panel of panels) updateSource(panel);
    form.querySelector(".run-settings").open = true;
  });
}

function setRunning(running) {
  submit.disabled = running;
  for (const button of presets) button.disabled = running;
}

function resetConsole() {
  output.hidden = false;
  report.hidden = true;
  report.removeAttribute("href");
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
  while (true) {
    const job = await getJSON(url, { cache: "no-store" });
    for (const line of job.lines.slice(seen)) appendLine(line);
    seen = job.lines.length;
    if (job.state === "running") {
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = new FormData(form);
  const source = (side) => ({
    kind: values.get(side + "_kind"),
    source: values.get(side + "_source").trim(),
    base_url: values.get(side + "_base")?.trim() || "",
  });
  const before = source("before");
  const after = source("after");
  const backend = values.get("backend");
  const seeds = values.get("seeds").trim();
  const intent = values.get("intent").trim();
  const intentText = values.get("intent_text");
  clearFieldErrors();
  const missing = [
    ["before_source", before.source, "Enter a source URL or file path."],
    ["after_source", after.source, "Enter a source URL or file path."],
    ["intent_text", intentText.trim(), "Describe what this change was meant to do. Without it every difference is flagged as a regression."],
  ].filter(([, value]) => !value);
  for (const [field, , message] of missing) showFieldError(field, message);
  if (missing.length) {
    form.elements[missing[0][0]].focus();
    return;
  }
  const scoreDemo = before.kind === "api" && before.source === toyDemo.before
    && after.kind === "api" && after.source === toyDemo.after
    && backend === "fake" && seeds === toyDemo.seeds && intentText.trim() === toyIntent;
  resetConsole();
  output.scrollIntoView({ block: "nearest" });
  statusText.textContent = "Starting";
  setRunning(true);
  try {
    const { job_url } = await getJSON("/run-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        before,
        after,
        backend,
        name: values.get("name").trim() || "comparison",
        seeds,
        intent,
        intent_text: intentText,
        score: scoreDemo,
      }),
    });
    const url = new URL(location.href);
    url.searchParams.set("job", job_url.split("/").at(-1));
    history.replaceState(null, "", url);
    await followJob(job_url);
  } catch (error) {
    showError(error);
  } finally {
    setRunning(false);
  }
});

const jobId = new URLSearchParams(location.search).get("job");
if (jobId && /^[a-f0-9]{32}$/.test(jobId)) {
  resetConsole();
  setRunning(true);
  followJob("/run-jobs/" + jobId).catch(showError).finally(() => setRunning(false));
}
