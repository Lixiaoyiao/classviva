const state = {
  groups: [],
  results: [],
  busy: false,
};

const $ = (id) => document.getElementById(id);

const els = {
  url: $("urlInput"),
  textApiKey: $("textApiKeyInput"),
  textBaseUrl: $("textBaseUrlInput"),
  textModelInput: $("textModelInput"),
  visionApiKey: $("visionApiKeyInput"),
  visionBaseUrl: $("visionBaseUrlInput"),
  visionModelInput: $("visionModelInput"),
  headless: $("headlessInput"),
  visionFallback: $("visionFallbackInput"),
  pageStatus: $("pageStatus"),
  depsStatus: $("depsStatus"),
  textModel: $("textModel"),
  visionStatus: $("visionStatus"),
  configStatus: $("configStatus"),
  depsHelp: $("depsHelp"),
  groupCount: $("groupCount"),
  resultCount: $("resultCount"),
  groups: $("groups"),
  results: $("results"),
  log: $("log"),
};

bind("saveConfigBtn", () => run("保存设置", "/api/config", {
  textApiKey: els.textApiKey.value.trim(),
  textBaseUrl: els.textBaseUrl.value.trim(),
  textModel: els.textModelInput.value.trim(),
  visionApiKey: els.visionApiKey.value.trim(),
  visionBaseUrl: els.visionBaseUrl.value.trim(),
  visionModel: els.visionModelInput.value.trim(),
  classvivaUrl: els.url.value.trim(),
}, (data) => {
  els.textApiKey.value = "";
  els.visionApiKey.value = "";
  applyConfig(data.config);
  log(data.message || "配置已保存");
  refreshStatus();
}));

bind("startBtn", () => run("启动浏览器", "/api/start", {
  url: els.url.value.trim(),
  headless: els.headless.checked,
}, (data) => {
  log(data.message || "浏览器已启动");
  refreshStatus();
}));

bind("extractBtn", () => run("提取题目", "/api/extract", {
  visionFallback: els.visionFallback.checked,
}, (data) => {
  state.groups = data.groups || [];
  state.results = [];
  renderGroups();
  renderResults();
  log(`提取到 ${state.groups.length} 道题`);
  (data.warnings || []).forEach((warning) => log(`提醒：${warning}`));
  refreshStatus();
}));

bind("solveBtn", () => run("文本求解", "/api/solve", {
  groups: state.groups,
}, (data) => {
  state.results = data.results || [];
  renderResults();
  log(`生成 ${state.results.length} 组答案`);
  refreshStatus();
}));

bind("visionBtn", () => run("视觉求解", "/api/vision-solve", {
  visionFallback: els.visionFallback.checked,
}, (data) => {
  state.groups = data.groups || state.groups;
  state.results = data.results || [];
  renderGroups();
  renderResults();
  (data.warnings || []).forEach((warning) => log(`提醒：${warning}`));
  log(`视觉模型返回 ${state.results.length} 组答案`);
  refreshStatus();
}));

bind("fillBtn", () => run("填入网页", "/api/fill", {
  results: collectResults(),
}, (data) => {
  log(`已填入 ${data.filled || 0} 个答案`);
  refreshStatus();
}));

bind("closeBtn", () => run("关闭浏览器", "/api/close", {}, (data) => {
  state.groups = [];
  state.results = [];
  renderGroups();
  renderResults();
  log(data.message || "浏览器已关闭");
  refreshStatus();
}));

bind("clearLogBtn", () => {
  els.log.textContent = "";
});

loadConfig();
refreshStatus();

function bind(id, handler) {
  $(id).addEventListener("click", handler);
}

async function run(label, url, payload, onSuccess) {
  if (state.busy) return;
  setBusy(true);
  log(`${label}...`);
  try {
    const data = await postJSON(url, payload);
    if (!data.ok) {
      if (data.groups) {
        state.groups = data.groups;
        state.results = [];
        renderGroups();
        renderResults();
      }
      (data.warnings || []).forEach((warning) => log(`提醒：${warning}`));
      throw new Error(data.error || "操作失败");
    }
    onSuccess(data);
  } catch (err) {
    log(`${label}失败：${err.message}`);
  } finally {
    setBusy(false);
  }
}

async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload || {}),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || res.statusText);
  }
  return data;
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (!data.ok) return;
    const page = data.page || {};
    els.pageStatus.textContent = page.started
      ? `${page.title || "已启动"} · ${page.url || ""}`
      : "未启动";
    els.textModel.textContent = data.textModel ? `文本：${data.textModel}` : "文本：未配置";
    els.visionStatus.textContent = data.visionConfigured
      ? `视觉：${data.visionModel || "已配置"}`
      : "视觉：未配置";
    const deps = data.dependencies || {};
    els.depsStatus.textContent = deps.ready ? "依赖：OK" : "依赖：未完成";
    els.depsHelp.textContent = deps.ready
      ? ""
      : "还缺 Python 依赖。先在终端运行：python -m pip install -r requirements.txt，然后运行：playwright install chromium";
    els.groupCount.textContent = String(data.groupCount || state.groups.length || 0);
    els.resultCount.textContent = String(data.resultCount || state.results.length || 0);
  } catch {
    els.pageStatus.textContent = "服务未连接";
  }
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    if (data.ok) {
      applyConfig(data);
    }
  } catch {
    els.configStatus.textContent = "读取失败";
  }
}

function applyConfig(data) {
  els.textBaseUrl.value = data.textBaseUrl || "";
  els.textModelInput.value = data.textModel || "";
  els.visionBaseUrl.value = data.visionBaseUrl || "";
  els.visionModelInput.value = data.visionModel || "";
  els.url.value = data.classvivaUrl || els.url.value || "";
  const text = data.textKeySet ? "文本 key 已保存" : "文本 key 未保存";
  const vision = data.visionKeySet ? "视觉 key 已保存" : "视觉 key 未保存";
  els.configStatus.textContent = `${text} · ${vision}`;
}

function renderGroups() {
  els.groupCount.textContent = String(state.groups.length);
  if (!state.groups.length) {
    els.groups.className = "list empty";
    els.groups.textContent = "暂无题目";
    return;
  }
  els.groups.className = "list";
  els.groups.innerHTML = "";
  state.groups.forEach((group) => {
    const item = document.createElement("article");
    item.className = "item";
    item.innerHTML = `
      <div class="item-head">
        <div class="item-title">第 ${escapeHTML(group.qnum)} 题</div>
        <span class="badge">${(group.slots || []).length} 空</span>
      </div>
      <div class="question-text">${escapeHTML(group.text || "")}</div>
    `;
    els.groups.appendChild(item);
  });
}

function renderResults() {
  els.resultCount.textContent = String(state.results.length);
  if (!state.results.length) {
    els.results.className = "list empty";
    els.results.textContent = "暂无答案";
    return;
  }
  els.results.className = "list";
  els.results.innerHTML = "";
  state.results.forEach((result, resultIndex) => {
    const group = result.group || {};
    const answers = result.answers || [];
    const item = document.createElement("article");
    item.className = "item";
    item.innerHTML = `
      <div class="item-head">
        <div class="item-title">第 ${escapeHTML(group.qnum ?? "?")} 题</div>
        <span class="badge ${result.success ? "good" : "bad"}">${result.success ? "OK" : "FAIL"}</span>
      </div>
      <div class="answer-grid">
        ${answers.map((answer, answerIndex) => `
          <label class="answer-row">
            <span>#${answerIndex + 1}</span>
            <input class="answer-input" data-result="${resultIndex}" data-answer="${answerIndex}" value="${escapeAttr(answer)}">
          </label>
        `).join("")}
      </div>
      <div class="meta-line">
        ${result.vision ? `<span class="badge warn">视觉</span>` : ""}
        ${result.confidence ? `<span class="badge">置信：${escapeHTML(result.confidence)}</span>` : ""}
        ${result.note ? `<span class="badge warn">${escapeHTML(result.note)}</span>` : ""}
      </div>
    `;
    els.results.appendChild(item);
  });
}

function collectResults() {
  const cloned = JSON.parse(JSON.stringify(state.results));
  document.querySelectorAll(".answer-input").forEach((input) => {
    const resultIndex = Number(input.dataset.result);
    const answerIndex = Number(input.dataset.answer);
    if (cloned[resultIndex] && cloned[resultIndex].answers) {
      cloned[resultIndex].answers[answerIndex] = input.value.trim();
    }
  });
  state.results = cloned;
  return cloned;
}

function log(message) {
  const time = new Date().toLocaleTimeString();
  els.log.textContent += `[${time}] ${message}\n`;
  els.log.scrollTop = els.log.scrollHeight;
}

function setBusy(busy) {
  state.busy = busy;
  document.querySelectorAll("button").forEach((button) => {
    if (button.id !== "clearLogBtn") button.disabled = busy;
  });
}

function escapeHTML(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHTML(value).replaceAll("\n", " ");
}
