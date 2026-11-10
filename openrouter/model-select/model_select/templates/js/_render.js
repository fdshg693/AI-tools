function formatMetric(value) {
  // Python の :g 相当（末尾の不要な小数を落とす）の簡易実装
  var rounded = Math.round(value * 1000) / 1000;
  return String(rounded);
}

function clearChildren(el) {
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
}

function renderBucket(bucket) {
  var frag = document.createDocumentFragment();

  var heading = document.createElement("h3");
  heading.textContent =
    "coding_index [" + formatMetric(bucket.low) + ", " + formatMetric(bucket.high) + ")";
  frag.appendChild(heading);

  var table = document.createElement("table");
  var thead = document.createElement("thead");
  var headRow = document.createElement("tr");
  ["モデル", "ID", "coding_index", "価格（$/M tokens）"].forEach(function (text) {
    var th = document.createElement("th");
    th.textContent = text;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  var tbody = document.createElement("tbody");
  bucket.rows.forEach(function (row) {
    var tr = document.createElement("tr");

    var tdName = document.createElement("td");
    tdName.textContent = row.name;
    tr.appendChild(tdName);

    var tdId = document.createElement("td");
    tdId.textContent = row.id;
    tr.appendChild(tdId);

    var tdCoding = document.createElement("td");
    tdCoding.textContent = formatMetric(row.coding_index);
    tr.appendChild(tdCoding);

    var tdPrice = document.createElement("td");
    tdPrice.textContent = row.price_per_million.toFixed(2);
    tr.appendChild(tdPrice);

    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  frag.appendChild(table);

  return frag;
}

function filterByProviders(items) {
  var allowed = {};
  selectedProviders().forEach(function (slug) {
    allowed[slug] = true;
  });
  return items.filter(function (item) {
    return !!allowed[item.provider];
  });
}

function loadDisplayMode() {
  try {
    var stored = window.localStorage.getItem(DISPLAY_STORAGE_KEY);
    if (stored === "full" || stored === "pareto") {
      return stored;
    }
  } catch (e) {
    // localStorage不可でも表示切り替え自体は継続する
  }
  return "pareto";
}

function saveDisplayMode(mode) {
  try {
    window.localStorage.setItem(DISPLAY_STORAGE_KEY, mode);
  } catch (e) {
    // localStorage不可でも表示切り替え自体は継続する
  }
}

function currentDisplayMode() {
  var checked = document.querySelector('input[name="display-mode"]:checked');
  return checked && checked.value === "full" ? "full" : "pareto";
}

function initDisplayMode() {
  var radio = document.querySelector(
    'input[name="display-mode"][value="' + loadDisplayMode() + '"]'
  );
  if (radio) {
    radio.checked = true;
  }
  document.querySelectorAll('input[name="display-mode"]').forEach(function (input) {
    input.addEventListener("change", function () {
      saveDisplayMode(currentDisplayMode());
      renderAll();
    });
  });
}

function renderAxis(containerId, summaryId, priceField, minimum, step, scoped, paretoOnly) {
  var container = document.getElementById(containerId);
  var summary = document.getElementById(summaryId);
  clearChildren(container);

  var buckets = groupByBucket(scoped, codingIndexOf, minimum, step);
  var view = buildAxisView(buckets, priceField, paretoOnly);

  summary.textContent =
    "スコープ内対象モデル総数（ランク分け前）: " +
    scoped.length +
    "件（全" +
    records.length +
    "件中、選択プロバイダのみ、表示: " +
    (paretoOnly ? "Pareto" : "フル") +
    "）";

  view.forEach(function (bucket) {
    container.appendChild(renderBucket(bucket));
  });
}

function renderAll() {
  var thresholdInput = document.getElementById("threshold-input");
  var stepInput = document.getElementById("step-input");

  var minimum = Math.max(FLOOR, Number(thresholdInput.value) || FLOOR);
  if (minimum !== Number(thresholdInput.value)) {
    thresholdInput.value = String(minimum);
  }
  var step = Number(stepInput.value);
  if (!(step > 0)) {
    step = 1;
    stepInput.value = String(step);
  }

  var scoped = filterByProviders(records);
  var paretoOnly = currentDisplayMode() === "pareto";
  renderAxis(
    "buckets-prompt",
    "summary-prompt",
    "price_prompt_per_million",
    minimum,
    step,
    scoped,
    paretoOnly
  );
  renderAxis(
    "buckets-completion",
    "summary-completion",
    "price_completion_per_million",
    minimum,
    step,
    scoped,
    paretoOnly
  );
}

document.getElementById("threshold-input").addEventListener("input", renderAll);
document.getElementById("step-input").addEventListener("input", renderAll);

initDisplayMode();
initProviderFilters();
renderAll();
