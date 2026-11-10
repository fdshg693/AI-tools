var THEME_STORAGE_KEY = "model-select-theme";

function applyTheme(theme) {
  if (theme === "dark" || theme === "light") {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

function currentEffectiveTheme() {
  var explicit = document.documentElement.getAttribute("data-theme");
  if (explicit === "dark" || explicit === "light") {
    return explicit;
  }
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function updateToggleLabel(button) {
  button.textContent = currentEffectiveTheme() === "dark" ? "☀ ライトモード" : "🌙 ダークモード";
}

function initThemeToggle() {
  var button = document.getElementById("theme-toggle");
  var stored = null;
  try {
    stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  } catch (e) {
    stored = null;
  }
  applyTheme(stored);
  updateToggleLabel(button);

  button.addEventListener("click", function () {
    var next = currentEffectiveTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch (e) {
      // localStorage不可でも表示切り替え自体は継続する
    }
    updateToggleLabel(button);
  });
}

initThemeToggle();
