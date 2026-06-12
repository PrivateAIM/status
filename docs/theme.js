import { CONFIG } from "./constants.js";

export function initTheme() {
  const toggleBtn = document.getElementById("theme-toggle");
  if (!toggleBtn) return;

  const logoImg = document.getElementById("logo-img");
  const icon = document.getElementById("theme-toggle-icon");
  const darkLogo = CONFIG.theme.darkLogo;
  const lightLogo = CONFIG.theme.lightLogo;
  const sunIcon = CONFIG.theme.sunIcon;
  const moonIcon = CONFIG.theme.moonIcon;

  const applyTheme = (isDark) => {
    document.body.classList.toggle("dark-theme", isDark);
    if (logoImg) {
      logoImg.src = isDark ? darkLogo : lightLogo;
    }
    if (icon) {
      icon.innerHTML = isDark ? sunIcon : moonIcon;
    }
  };

  let initialIsDark = false;
  const savedTheme = localStorage.getItem("theme");
  if (savedTheme) {
    initialIsDark = savedTheme === "dark";
  } else if (window.matchMedia) {
    initialIsDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  applyTheme(initialIsDark);

  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
      if (!localStorage.getItem("theme")) applyTheme(e.matches);
    });
  }

  toggleBtn.onclick = () => {
    const isDark = !document.body.classList.contains("dark-theme");
    localStorage.setItem("theme", isDark ? "dark" : "light");
    applyTheme(isDark);
  };
}
