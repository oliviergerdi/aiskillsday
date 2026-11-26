// PRD 0001: Accept / Reject / Undo on findings. Works on bodies loaded later by HTMX (event delegation).
const NAME_KEY = "nparity.reviewer";

function rememberedName() {
  try { return localStorage.getItem(NAME_KEY) || ""; } catch { return ""; }
}

function rememberName(name) {
  try { localStorage.setItem(NAME_KEY, name); } catch { /* storage blocked: fine */ }
}

function decisionUrl(box) {
  return `/runs/${encodeURIComponent(box.dataset.run)}/findings/${encodeURIComponent(box.dataset.finding)}/decision`;
}

async function send(box, method, body) {
  const response = await fetch(decisionUrl(box), {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    alert(typeof data.detail === "string" ? data.detail : "Could not save the decision.");
    return;
  }
  try { sessionStorage.setItem("nparity.scroll", String(window.scrollY)); } catch { /* fine */ }
  location.reload();
}

document.addEventListener("click", (event) => {
  const decide = event.target.closest("[data-decide]");
  const cancel = event.target.closest("[data-cancel]");
  const undo = event.target.closest("[data-undo]");
  const box = event.target.closest(".decision");
  if (!box) return;
  const form = box.querySelector(".decision-form");
  if (decide) {
    form.dataset.decision = decide.dataset.decide;
    form.querySelector("[type=submit]").textContent = decide.dataset.decide === "accept" ? "Save accept" : "Save reject";
    form.elements.by.value ||= rememberedName();
    form.hidden = false;
    (form.elements.by.value ? form.elements.note : form.elements.by).focus();
  } else if (cancel) {
    form.hidden = true;
  } else if (undo) {
    send(box, "DELETE");
  }
});

document.addEventListener("submit", (event) => {
  const form = event.target.closest(".decision-form");
  if (!form) return;
  event.preventDefault();
  const by = form.elements.by.value.trim();
  rememberName(by);
  send(form.closest(".decision"), "POST", { decision: form.dataset.decision, by, note: form.elements.note.value.trim() });
});

const highlightNav = document.querySelector(".highlight-nav");
if (highlightNav) {
  const [previous, next] = highlightNav.querySelectorAll("button");
  let highlights = [];
  let current = null;

  function selectHighlight(line) {
    current?.classList.remove("current-highlight");
    current = line;
    current?.classList.add("current-highlight");
    previous.setAttribute("aria-disabled", current !== null && current === highlights[0]);
    next.setAttribute("aria-disabled", current !== null && current === highlights.at(-1));
  }

  function refreshHighlights() {
    const visible = [...document.querySelectorAll(".f-body .hl-old, .f-body .hl-new")]
      .filter(line => !line.closest("details:not([open])"));
    highlightNav.hidden = visible.length === 0;
    highlights = visible.map(line => ({ line, top: line.getBoundingClientRect().top }))
      .sort((a, b) => a.top - b.top)
      .map(({ line }) => line);
    selectHighlight(highlights.includes(current) ? current : null);
  }

  highlightNav.addEventListener("click", (event) => {
    const button = event.target.closest("[data-highlight-step]");
    if (!button || button.getAttribute("aria-disabled") === "true") return;
    const step = Number(button.dataset.highlightStep);
    const index = current ? highlights.indexOf(current) + step : (step > 0 ? 0 : highlights.length - 1);
    const line = highlights[index];
    if (!line) return;
    selectHighlight(line);
    line.scrollIntoView({ block: "center", inline: "nearest" });
  });

  document.addEventListener("focusin", (event) => {
    if (highlights.includes(event.target)) selectHighlight(event.target);
  });
  document.addEventListener("toggle", refreshHighlights, true);
  document.addEventListener("htmx:afterSwap", refreshHighlights);
  window.addEventListener("resize", refreshHighlights);
  refreshHighlights();
}

try {
  const y = sessionStorage.getItem("nparity.scroll");
  if (y !== null) { sessionStorage.removeItem("nparity.scroll"); window.scrollTo(0, Number(y)); }
} catch { /* fine */ }
