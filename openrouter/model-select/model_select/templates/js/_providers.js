var PROVIDER_LABELS = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  qwen: "Qwen",
  "z-ai": "Z.ai",
  minimax: "MiniMax",
  "x-ai": "xAI",
  moonshotai: "Moonshot AI",
  deepseek: "DeepSeek",
};

function uniqueProviders(items) {
  var seen = {};
  var result = [];
  items.forEach(function (item) {
    var provider = item.provider;
    if (provider && !seen[provider]) {
      seen[provider] = true;
      result.push(provider);
    }
  });
  result.sort();
  return result;
}

function providerLabel(slug) {
  return PROVIDER_LABELS[slug] || slug;
}

function loadProviderSelection() {
  try {
    var raw = window.localStorage.getItem(PROVIDER_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    var parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.selected) || !Array.isArray(parsed.known)) {
      return null;
    }
    return parsed;
  } catch (e) {
    return null;
  }
}

function saveProviderSelection() {
  try {
    window.localStorage.setItem(
      PROVIDER_STORAGE_KEY,
      JSON.stringify({ selected: selectedProviders(), known: allProviders.slice() })
    );
  } catch (e) {
    // localStorage不可でも絞り込み自体は継続する
  }
}

function initialSelectedProviders() {
  var stored = loadProviderSelection();
  if (!stored) {
    return allProviders.slice();
  }
  var selectedSet = {};
  stored.selected.forEach(function (slug) {
    selectedSet[slug] = true;
  });
  var knownSet = {};
  stored.known.forEach(function (slug) {
    knownSet[slug] = true;
  });
  return allProviders.filter(function (slug) {
    return selectedSet[slug] || !knownSet[slug];
  });
}

function selectedProviders() {
  var checked = [];
  document.querySelectorAll("#provider-filters input[type='checkbox']").forEach(function (box) {
    if (box.checked) {
      checked.push(box.value);
    }
  });
  return checked;
}

function setAllProviderChecks(checked) {
  document.querySelectorAll("#provider-filters input[type='checkbox']").forEach(function (box) {
    box.checked = checked;
  });
}

function initProviderFilters() {
  var container = document.getElementById("provider-filters");
  var initiallySelected = {};
  initialSelectedProviders().forEach(function (slug) {
    initiallySelected[slug] = true;
  });
  allProviders.forEach(function (slug) {
    var label = document.createElement("label");
    var box = document.createElement("input");
    box.type = "checkbox";
    box.value = slug;
    box.checked = !!initiallySelected[slug];
    box.addEventListener("change", function () {
      saveProviderSelection();
      renderAll();
    });
    label.appendChild(box);
    label.appendChild(document.createTextNode(" " + providerLabel(slug)));
    container.appendChild(label);
  });

  document.getElementById("providers-all").addEventListener("click", function () {
    setAllProviderChecks(true);
    saveProviderSelection();
    renderAll();
  });
  document.getElementById("providers-none").addEventListener("click", function () {
    setAllProviderChecks(false);
    saveProviderSelection();
    renderAll();
  });
}
