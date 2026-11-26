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
  intent: "fixtures/intent.md",
};
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
      intent: toy ? toyDemo.intent : "fixtures/petstore/intent.md",
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
    throw new Error(typeof data.detail === "string" ? data.detail : "Check the comparison inputs.");
  }
  return data;
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
    if (job.report_url) {
      report.href = job.report_url;
      report.hidden = false;
    }
    return;
  }
}

function showError(error) {
  statusText.textContent = "Error";
  appendLine(error.message);
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
  const scoreDemo = before.kind === "api" && before.source === toyDemo.before
    && after.kind === "api" && after.source === toyDemo.after
    && backend === "fake" && seeds === toyDemo.seeds && intent === toyDemo.intent;
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
