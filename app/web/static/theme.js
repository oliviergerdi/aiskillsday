(() => {
  const key = "nparity-theme";
  const root = document.documentElement;
  const system = matchMedia("(prefers-color-scheme: dark)");
  let preference;
  try {
    const saved = localStorage.getItem(key);
    if (saved === "light" || saved === "dark") {
      preference = saved;
      root.dataset.theme = saved;
    }
  } catch {
    // The toggle still works for this page when browser storage is unavailable.
  }

  const isDark = () => preference ? preference === "dark" : system.matches;

  document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.querySelector(".theme-toggle");
    const updateLabel = () => { toggle.textContent = isDark() ? "Light mode" : "Dark mode"; };
    updateLabel();
    toggle.hidden = false;

    system.addEventListener("change", updateLabel);
    toggle.addEventListener("click", () => {
      preference = isDark() ? "light" : "dark";
      root.dataset.theme = preference;
      updateLabel();
      try {
        localStorage.setItem(key, preference);
      } catch {
        // The selected theme remains active for this page.
      }
    });
  });
})();
