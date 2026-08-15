const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  defaults: null,
  config: null,
  sections: [],
  presets: {},
  assets: { fonts: [], backgrounds: [] },
  pages: [],
  page: 0,
  zoom: 0.72,
  rendering: false,
  renderStartedAt: 0,
  renderTimer: null,
  toastTimer: null,
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function getPath(object, path) {
  return path.split(".").reduce((current, key) => current?.[key], object);
}

function setPath(object, path, value) {
  const parts = path.split(".");
  const leaf = parts.pop();
  const parent = parts.reduce((current, key) => current[key], object);
  parent[leaf] = value;
}

function mergeDeep(target, source) {
  if (!source || typeof source !== "object" || Array.isArray(source)) return target;
  Object.entries(source).forEach(([key, value]) => {
    if (value && typeof value === "object" && !Array.isArray(value) && target[key]) {
      mergeDeep(target[key], value);
    } else if (key in target) {
      target[key] = value;
    }
  });
  return target;
}

function formatNumber(value, step) {
  if (value === null || value === undefined) return "自动";
  const decimals = String(step).includes(".") ? String(step).split(".")[1].length : 0;
  return Number(value).toFixed(Math.min(decimals, 3)).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

function updateRangePaint(input) {
  const min = Number(input.min);
  const max = Number(input.max);
  const value = Number(input.value);
  const progress = max === min ? 0 : ((value - min) / (max - min)) * 100;
  input.style.setProperty("--range-progress", `${Math.max(0, Math.min(100, progress))}%`);
}

function fieldShell(meta) {
  const field = document.createElement("div");
  field.className = "config-field";
  field.dataset.search = `${meta.label} ${meta.help || ""} ${meta.path}`.toLowerCase();
  field.dataset.path = meta.path;
  return field;
}

function addFieldHelp(field, meta) {
  if (!meta.help) return;
  const help = document.createElement("p");
  help.className = "field-help";
  help.textContent = meta.help;
  field.append(help);
}

function createRangeControl(meta, nullable = false) {
  const field = fieldShell(meta);
  const currentValue = getPath(state.config, meta.path);
  let workingValue = currentValue ?? Math.max(meta.min, Math.min(meta.max, getPath(state.defaults, meta.path) ?? meta.min));
  const preserveInteger = Number.isInteger(getPath(state.defaults, meta.path)) && Number.isInteger(meta.step);

  const head = document.createElement("div");
  head.className = "field-head";
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  const display = document.createElement("span");
  display.className = "field-value";
  display.textContent = currentValue === null ? "自动" : `${formatNumber(currentValue, meta.step)}${meta.unit || ""}`;
  head.append(label, display);

  const row = document.createElement("div");
  row.className = "range-row";
  const range = document.createElement("input");
  range.type = "range";
  range.min = meta.min;
  range.max = meta.max;
  range.step = meta.step;
  range.value = workingValue;
  range.id = `field-${meta.path.replaceAll(".", "-")}`;
  label.htmlFor = range.id;

  const numberWrap = document.createElement("div");
  numberWrap.className = "number-wrap";
  const number = document.createElement("input");
  number.type = "number";
  number.min = meta.min;
  number.max = meta.max;
  number.step = meta.step;
  number.value = workingValue;
  number.setAttribute("aria-label", `${meta.label}精确值`);
  const unit = document.createElement("span");
  unit.textContent = meta.unit || "";
  numberWrap.append(number, unit);
  row.append(range, numberWrap);

  const commit = (rawValue) => {
    let value = Number(rawValue);
    if (!Number.isFinite(value)) return;
    value = Math.max(meta.min, Math.min(meta.max, value));
    if (preserveInteger) value = Math.round(value);
    workingValue = value;
    setPath(state.config, meta.path, value);
    range.value = value;
    number.value = value;
    display.textContent = `${formatNumber(value, meta.step)}${meta.unit || ""}`;
    updateRangePaint(range);
    markChanged();
  };
  range.addEventListener("input", () => commit(range.value));
  number.addEventListener("change", () => commit(number.value));
  updateRangePaint(range);

  field.append(head, row);
  if (nullable) {
    const autoRow = document.createElement("div");
    autoRow.className = "auto-row";
    const autoLabel = document.createElement("label");
    autoLabel.className = "auto-check";
    const auto = document.createElement("input");
    auto.type = "checkbox";
    auto.checked = currentValue === null;
    autoLabel.append(auto, document.createTextNode("自动计算"));
    autoRow.append(autoLabel);
    const syncAuto = () => {
      const isAuto = auto.checked;
      range.disabled = isAuto;
      number.disabled = isAuto;
      setPath(state.config, meta.path, isAuto ? null : Number(workingValue));
      display.textContent = isAuto ? "自动" : `${formatNumber(workingValue, meta.step)}${meta.unit || ""}`;
      markChanged();
    };
    auto.addEventListener("change", syncAuto);
    range.disabled = auto.checked;
    number.disabled = auto.checked;
    field.append(autoRow);
  }
  addFieldHelp(field, meta);
  return field;
}

function createToggleControl(meta) {
  const field = fieldShell(meta);
  const row = document.createElement("div");
  row.className = "toggle-row";
  const copy = document.createElement("div");
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  copy.append(label);
  if (meta.help) {
    const help = document.createElement("p");
    help.className = "field-help";
    help.textContent = meta.help;
    copy.append(help);
  }
  const switchLabel = document.createElement("label");
  switchLabel.className = "switch";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(getPath(state.config, meta.path));
  input.id = `field-${meta.path.replaceAll(".", "-")}`;
  label.htmlFor = input.id;
  const track = document.createElement("span");
  track.className = "switch-track";
  switchLabel.append(input, track);
  input.addEventListener("change", () => {
    setPath(state.config, meta.path, input.checked);
    markChanged();
  });
  row.append(copy, switchLabel);
  field.append(row);
  return field;
}

function createSelectControl(meta) {
  const field = fieldShell(meta);
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  const select = document.createElement("select");
  select.className = "select-control";
  select.id = `field-${meta.path.replaceAll(".", "-")}`;
  label.htmlFor = select.id;
  meta.options.forEach((option) => {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label;
    select.append(element);
  });
  select.value = getPath(state.config, meta.path);
  select.addEventListener("change", () => {
    setPath(state.config, meta.path, select.value);
    if (meta.path === "background.style" && select.value !== "image") {
      setPath(state.config, "background.image", null);
      const imageInput = document.querySelector("#field-background-image");
      if (imageInput) imageInput.value = "";
    }
    markChanged();
  });
  field.append(label, select);
  addFieldHelp(field, meta);
  return field;
}

function createColorControl(meta) {
  const field = fieldShell(meta);
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  const row = document.createElement("div");
  row.className = "color-row";
  const picker = document.createElement("input");
  picker.type = "color";
  picker.value = getPath(state.config, meta.path);
  picker.setAttribute("aria-label", `${meta.label}选择器`);
  const text = document.createElement("input");
  text.type = "text";
  text.value = getPath(state.config, meta.path);
  text.setAttribute("aria-label", `${meta.label}色值`);
  picker.addEventListener("input", () => {
    text.value = picker.value;
    setPath(state.config, meta.path, picker.value);
    markChanged();
  });
  text.addEventListener("change", () => {
    if (/^#[0-9a-f]{6}$/i.test(text.value)) picker.value = text.value;
    setPath(state.config, meta.path, text.value.trim());
    markChanged();
  });
  row.append(picker, text);
  field.append(label, row);
  addFieldHelp(field, meta);
  return field;
}

function createTextControl(meta) {
  const field = fieldShell(meta);
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = meta.label;
  const input = document.createElement("input");
  input.className = "text-control";
  input.type = "text";
  input.value = getPath(state.config, meta.path) ?? "";
  input.id = `field-${meta.path.replaceAll(".", "-")}`;
  label.htmlFor = input.id;
  if (meta.control === "font-path" || meta.control === "background-path") {
    const list = document.createElement("datalist");
    list.id = `${input.id}-options`;
    const assets = meta.control === "font-path" ? state.assets.fonts : state.assets.backgrounds;
    assets.forEach((asset) => {
      const option = document.createElement("option");
      option.value = asset.value;
      option.label = asset.label;
      list.append(option);
    });
    input.setAttribute("list", list.id);
    field.append(label, input, list);
  } else {
    field.append(label, input);
  }
  input.addEventListener("change", () => {
    const value = input.value.trim();
    setPath(state.config, meta.path, value === "" && meta.path !== "handwriting.seed" ? null : value);
    if (meta.path === "background.image" && value) {
      setPath(state.config, "background.style", "image");
      const styleSelect = document.querySelector("#field-background-style");
      if (styleSelect) styleSelect.value = "image";
    }
    markChanged();
  });
  addFieldHelp(field, meta);
  return field;
}

function createField(meta) {
  if (meta.control === "range") return createRangeControl(meta);
  if (meta.control === "nullable-range") return createRangeControl(meta, true);
  if (meta.control === "toggle") return createToggleControl(meta);
  if (meta.control === "select") return createSelectControl(meta);
  if (meta.control === "color") return createColorControl(meta);
  return createTextControl(meta);
}

function renderConfigSections() {
  const container = $("#config-sections");
  container.replaceChildren();
  let fieldCount = 0;
  state.sections.forEach((section, index) => {
    const card = document.createElement("details");
    card.className = "config-card";
    card.dataset.sectionSearch = `${section.title} ${section.description} ${section.eyebrow}`.toLowerCase();
    card.open = ["typography", "second-layer"].includes(section.id);
    const summary = document.createElement("summary");
    const sectionIndex = document.createElement("span");
    sectionIndex.className = "section-index";
    sectionIndex.textContent = String(index + 1).padStart(2, "0");
    const name = document.createElement("span");
    name.className = "section-name";
    const title = document.createElement("strong");
    title.textContent = section.title;
    const description = document.createElement("small");
    description.textContent = section.description;
    name.append(title, description);
    const count = document.createElement("span");
    count.className = "section-count";
    count.textContent = `${section.fields.length} 项`;
    summary.append(sectionIndex, name, count);
    const fields = document.createElement("div");
    fields.className = "config-fields";
    section.fields.forEach((meta) => fields.append(createField(meta)));
    fieldCount += section.fields.length;
    card.append(summary, fields);
    container.append(card);
  });
  $("#field-count").textContent = fieldCount;
  applyConfigSearch();
  updateSummary();
}

function applyConfigSearch() {
  const query = $("#config-search").value.trim().toLowerCase();
  let visibleSections = 0;
  $$(".config-card").forEach((card) => {
    let visibleFields = 0;
    $$(".config-field", card).forEach((field) => {
      const visible = !query || field.dataset.search.includes(query) || card.dataset.sectionSearch.includes(query);
      field.hidden = !visible;
      if (visible) visibleFields += 1;
    });
    card.hidden = visibleFields === 0;
    if (visibleFields > 0) visibleSections += 1;
    if (query && visibleFields > 0) card.open = true;
  });
  const oldEmpty = $(".no-results", $("#config-sections"));
  if (oldEmpty) oldEmpty.remove();
  if (!visibleSections) {
    const empty = document.createElement("div");
    empty.className = "no-results";
    empty.textContent = "没有找到匹配的参数";
    $("#config-sections").append(empty);
  }
}

function markChanged() {
  $("#save-state").textContent = "有未生成的更改";
  $("#save-state").style.color = "var(--accent)";
  $$("[data-preset]").forEach((button) => button.classList.remove("active"));
  updateSummary();
}

function updateSummary() {
  if (!state.config) return;
  const enabled = state.config.handwriting.second_layer_enabled;
  $("#render-summary-title").textContent = enabled ? "双层自然笔迹" : "基础字形笔迹";
  $("#render-summary-meta").textContent = `${state.config.page.dpi} DPI · 第二层${enabled ? "已启用" : "已关闭"}`;
}

function updateDocumentStats() {
  const value = $("#markdown-editor").value;
  $("#char-count").textContent = value.length.toLocaleString("zh-CN");
  $("#line-count").textContent = (value ? value.split(/\r?\n/).length : 0).toLocaleString("zh-CN");
  $("#save-state").textContent = "文稿已更新";
  $("#save-state").style.color = "var(--ink-soft)";
}

async function loadExample(name, notify = true) {
  if (!name) return;
  try {
    const response = await fetch(`/api/examples/${encodeURIComponent(name)}`);
    if (!response.ok) throw new Error("示例读取失败");
    $("#markdown-editor").value = await response.text();
    updateDocumentStats();
    if (notify) showToast("示例已载入", "可以继续编辑，或直接生成预览。");
  } catch (error) {
    showToast("无法载入示例", error.message, true);
  }
}

function applyPreset(name) {
  const values = state.presets[name];
  if (!values) return;
  Object.entries(values).forEach(([path, value]) => setPath(state.config, path, value));
  renderConfigSections();
  $$("[data-preset]").forEach((button) => button.classList.toggle("active", button.dataset.preset === name));
  const names = { formal: "工整", natural: "自然", casual: "随性" };
  $("#render-summary-title").textContent = `${names[name]}笔迹`;
  showToast("风格已切换", `已应用“${names[name]}”扰动参数，可继续微调。`);
}

function setRendering(rendering) {
  state.rendering = rendering;
  $("#render-overlay").hidden = !rendering;
  ["#render-top", "#render-main", "#render-empty"].forEach((selector) => {
    const button = $(selector);
    button.disabled = rendering;
    button.classList.toggle("loading", rendering);
  });
  const dot = $(".status-dot");
  dot.classList.toggle("busy", rendering);
  dot.classList.remove("error");
  $("#service-status").textContent = rendering ? "正在书写与排版" : "本地渲染器已连接";
  if (rendering) {
    state.renderStartedAt = Date.now();
    $("#render-time").textContent = "00:00";
    state.renderTimer = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - state.renderStartedAt) / 1000);
      $("#render-time").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
      const steps = ["解析 Markdown 与公式…", "计算版面与分页…", "逐行书写文字…", "施加第二层墨迹扰动…", "合成纸张并输出 PDF…"];
      $("#render-step").textContent = steps[Math.min(steps.length - 1, Math.floor(seconds / 3))];
    }, 500);
  } else if (state.renderTimer) {
    clearInterval(state.renderTimer);
    state.renderTimer = null;
  }
}

async function renderDocument() {
  if (state.rendering) return;
  const markdown = $("#markdown-editor").value;
  if (!markdown.trim()) {
    showToast("文稿为空", "请先输入或载入 Markdown 内容。", true);
    return;
  }
  setRendering(true);
  try {
    const response = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown, config: state.config }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "生成失败");
    state.pages = result.pages;
    state.page = 0;
    $("#page-count").textContent = result.pageCount;
    $("#download-pdf").href = result.pdf;
    $("#download-pdf").download = "markdown-to-handwrite.pdf";
    $("#download-pdf").classList.remove("disabled");
    $("#download-pdf").setAttribute("aria-disabled", "false");
    $("#empty-paper").hidden = true;
    $("#preview-image").hidden = false;
    showCurrentPage();
    $("#save-state").textContent = "预览已是最新";
    $("#save-state").style.color = "var(--sage-deep)";
    const seconds = ((Date.now() - state.renderStartedAt) / 1000).toFixed(1);
    showToast("手稿已生成", `${result.pageCount} 页 · 用时 ${seconds} 秒`);
    closePanels();
  } catch (error) {
    $(".status-dot").classList.add("error");
    $("#service-status").textContent = "生成遇到问题";
    showToast("生成失败", error.message, true);
  } finally {
    setRendering(false);
  }
}

function showCurrentPage() {
  if (!state.pages.length) return;
  const image = $("#preview-image");
  image.src = state.pages[state.page];
  image.alt = `手写报告第 ${state.page + 1} 页`;
  $("#current-page").textContent = state.page + 1;
  $("#page-count").textContent = state.pages.length;
  $("#prev-page").disabled = state.page <= 0;
  $("#next-page").disabled = state.page >= state.pages.length - 1;
  $("#preview-meta").textContent = `${state.config.page.width_mm} × ${state.config.page.height_mm} mm · ${state.config.page.dpi} DPI`;
  $("#canvas-viewport").scrollTo({ top: 0, behavior: "smooth" });
}

function setZoom(value) {
  state.zoom = Math.max(0.35, Math.min(1.6, value));
  $("#paper-shell").style.width = `${Math.round(958 * state.zoom)}px`;
  $("#zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
}

function fitPreview() {
  const viewport = $("#canvas-viewport");
  const horizontalPadding = window.innerWidth <= 620 ? 32 : 92;
  setZoom(Math.min(1, Math.max(0.35, (viewport.clientWidth - horizontalPadding) / 958)));
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function showToast(title, message, error = false) {
  const toast = $("#toast");
  if (state.toastTimer) clearTimeout(state.toastTimer);
  $("#toast-title").textContent = title;
  $("#toast-message").textContent = message;
  $(".toast-mark", toast).textContent = error ? "!" : "✓";
  toast.classList.toggle("error", error);
  toast.hidden = false;
  requestAnimationFrame(() => toast.classList.add("show"));
  state.toastTimer = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => { toast.hidden = true; }, 260);
  }, error ? 5200 : 3200);
}

function openPanel(name) {
  closePanels();
  $(`#${name}-panel`).classList.add("open");
  $("#panel-scrim").hidden = false;
}

function closePanels() {
  $$(".side-panel.open").forEach((panel) => panel.classList.remove("open"));
  $("#panel-scrim").hidden = true;
}

function bindEvents() {
  $("#markdown-editor").addEventListener("input", updateDocumentStats);
  $("#example-select").addEventListener("change", (event) => loadExample(event.target.value));
  $("#markdown-import").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    $("#markdown-editor").value = await file.text();
    updateDocumentStats();
    showToast("文稿已导入", file.name);
    event.target.value = "";
  });
  $("#config-import").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const imported = JSON.parse(await file.text());
      state.config = mergeDeep(clone(state.defaults), imported);
      renderConfigSections();
      markChanged();
      showToast("配置已导入", file.name);
    } catch (error) {
      showToast("配置无法导入", "请确认文件是有效的 JSON 配置。", true);
    }
    event.target.value = "";
  });
  $("#config-export").addEventListener("click", () => downloadJson("markdown-to-handwrite-config.json", state.config));
  $("#reset-config").addEventListener("click", () => {
    state.config = clone(state.defaults);
    renderConfigSections();
    $$("[data-preset]").forEach((button) => button.classList.toggle("active", button.dataset.preset === "natural"));
    showToast("已恢复默认参数", "所有分组均已重置。" );
  });
  $("#config-search").addEventListener("input", applyConfigSearch);
  $$("[data-preset]").forEach((button) => button.addEventListener("click", () => applyPreset(button.dataset.preset)));
  ["#render-top", "#render-main", "#render-empty"].forEach((selector) => $(selector).addEventListener("click", renderDocument));
  $("#prev-page").addEventListener("click", () => { if (state.page > 0) { state.page -= 1; showCurrentPage(); } });
  $("#next-page").addEventListener("click", () => { if (state.page < state.pages.length - 1) { state.page += 1; showCurrentPage(); } });
  $("#zoom-in").addEventListener("click", () => setZoom(state.zoom + 0.1));
  $("#zoom-out").addEventListener("click", () => setZoom(state.zoom - 0.1));
  $("#zoom-fit").addEventListener("click", fitPreview);
  $("#theme-toggle").addEventListener("click", () => {
    const theme = document.body.dataset.theme === "dark" ? "light" : "dark";
    document.body.dataset.theme = theme;
    localStorage.setItem("markdown-to-handwrite-theme", theme);
  });
  $("#toggle-editor").addEventListener("click", () => openPanel("editor"));
  $("#toggle-settings").addEventListener("click", () => openPanel("settings"));
  $$("[data-close-panel]").forEach((button) => button.addEventListener("click", closePanels));
  $("#panel-scrim").addEventListener("click", closePanels);
  window.addEventListener("resize", () => { if (window.innerWidth <= 620) fitPreview(); });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      renderDocument();
    }
    if (event.key === "Escape") closePanels();
  });
}

async function initialize() {
  document.body.dataset.theme = localStorage.getItem("markdown-to-handwrite-theme") || "light";
  try {
    const response = await fetch("/api/bootstrap");
    if (!response.ok) throw new Error("无法读取配置模型");
    const bootstrap = await response.json();
    state.defaults = bootstrap.config;
    state.config = clone(bootstrap.config);
    state.sections = bootstrap.sections;
    state.presets = bootstrap.presets;
    state.assets = bootstrap.assets;
    bootstrap.examples.forEach((example) => {
      const option = document.createElement("option");
      option.value = example.value;
      option.textContent = example.label;
      $("#example-select").append(option);
    });
    renderConfigSections();
    bindEvents();
    const preferred = bootstrap.examples.find((example) => example.value === "report0.md") || bootstrap.examples[0];
    if (preferred) {
      $("#example-select").value = preferred.value;
      await loadExample(preferred.value, false);
    }
    requestAnimationFrame(fitPreview);
    $("#service-status").textContent = "本地渲染器已连接";
  } catch (error) {
    $(".status-dot").classList.add("error");
    $("#service-status").textContent = "无法连接渲染器";
    showToast("WebUI 初始化失败", error.message, true);
  }
}

initialize();
