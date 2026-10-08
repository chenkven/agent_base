const sessionToken = sessionStorage.getItem("agent_session");
if (!sessionToken) window.location.replace("/");

const app = document.getElementById("app");
const messages = document.getElementById("messages");
const scroll = document.getElementById("chat-scroll");
const textarea = document.getElementById("message");
const send = document.getElementById("send");
const status = document.getElementById("status");
const apiKeyInput = document.getElementById("model-api-key");
const providerInput = document.getElementById("model-provider");
const modelPreset = document.getElementById("model-preset");
const modelInput = document.getElementById("model-id");
const modelHint = document.getElementById("model-hint");
const agentSelect = document.getElementById("agent-select");
const engineSelect = document.getElementById("dsh-engine");
const agentCapabilities = document.getElementById("agent-capabilities");
const inspectorName = document.getElementById("inspector-agent-name");
const agentRules = document.getElementById("agent-rules");
const agentSkills = document.getElementById("agent-skills");
const agentMcps = document.getElementById("agent-mcps");
const agentTools = document.getElementById("agent-tools");
const agentTrace = document.getElementById("agent-trace");
const mobileSettingsToggle = document.getElementById("mobile-settings-toggle");
const mobileInspectorToggle = document.getElementById("mobile-inspector-toggle");
const mobileHistoryToggle = document.getElementById("mobile-history-toggle");
const settingsPanel = document.getElementById("api-key-panel");
const inspectorPanel = document.getElementById("agent-inspector");
const connectionLabel = document.getElementById("connection-label");
const adminDialog = document.getElementById("admin-dialog");
const myCapabilitiesWorkspace = document.getElementById("my-capabilities-workspace");
const apiKeyDialog = document.getElementById("api-key-dialog");
let currentUserId = "";
let currentRole = "";
let sessionId = null;
let entries = [];
let currentChatId = null;
let historyChats = [];
let serverHistoryAvailable = false;
let selectionVersion = 0;
let capabilityRequestVersion = 0;
let modelChoices = {};
let availableAgents = [];
let knownAvailableTools = [];

function setMobilePanel(panel = null) {
  const settingsOpen = panel === "settings";
  const inspectorOpen = panel === "inspector";
  settingsPanel.classList.toggle("mobile-expanded", settingsOpen);
  inspectorPanel.classList.toggle("mobile-expanded", inspectorOpen);
  mobileSettingsToggle.setAttribute("aria-expanded", String(settingsOpen));
  mobileInspectorToggle.setAttribute("aria-expanded", String(inspectorOpen));
}

function closeHistoryPanel() {
  document.querySelector(".sidebar").classList.remove("mobile-history-open");
  mobileHistoryToggle.setAttribute("aria-expanded", "false");
}

function updateActiveSelection() {
  document.getElementById("active-agent-label").textContent =
    agentSelect.selectedOptions[0]?.textContent || "未选择 Agent";
  const provider = providerInput.selectedOptions[0]?.textContent || "未选择厂家";
  document.getElementById("active-model-label").textContent =
    `${engineSelect.selectedOptions[0]?.textContent || "DSH"} · ${provider} · ${modelPreset.value || "未选择模型"}`;
}

mobileSettingsToggle.addEventListener("click", () => {
  setMobilePanel(settingsPanel.classList.contains("mobile-expanded") ? null : "settings");
});
mobileInspectorToggle.addEventListener("click", () => {
  setMobilePanel(inspectorPanel.classList.contains("mobile-expanded") ? null : "inspector");
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setMobilePanel();
    if (!adminDialog.hidden) closeAdminWorkspace();
    if (!myCapabilitiesWorkspace.hidden) closeMyCapabilitiesWorkspace();
  }
});
scroll.addEventListener("click", () => setMobilePanel());
document.getElementById("close-settings").addEventListener("click", () => setMobilePanel());
document.getElementById("close-inspector").addEventListener("click", () => setMobilePanel());
document.getElementById("open-settings-inline").addEventListener("click", () => setMobilePanel("settings"));
for (const suggestion of document.querySelectorAll(".starter-card")) {
  suggestion.addEventListener("click", () => {
    textarea.value = suggestion.dataset.prompt || "";
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  });
}
mobileHistoryToggle.addEventListener("click", () => {
  const opened = document.querySelector(".sidebar").classList.toggle("mobile-history-open");
  mobileHistoryToggle.setAttribute("aria-expanded", String(opened));
});
const providerLabels = {
  "deepseek-official": "DeepSeek", "qwen-bailian": "千问（阿里云百炼·北京）",
  openai: "OpenAI", anthropic: "Anthropic", moonshotai: "Kimi（月之暗面）", zai: "智谱 GLM",
};

function populateModelChoices(provider, selectedModel = null) {
  const choices = modelChoices[provider] || [];
  modelPreset.replaceChildren();
  for (const model of choices) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    modelPreset.append(option);
  }
  const model = selectedModel === null ? (choices[0] || "") : selectedModel;
  modelPreset.value = choices.includes(model) ? model : (choices[0] || "");
  modelInput.value = modelPreset.value;
  modelInput.hidden = true;
  updateActiveSelection();
}

async function loadCatalog(preloaded = null) {
  const [models, agents, engines] = preloaded
    ? [{ models: preloaded.models }, { agents: preloaded.agents },
       preloaded.engines ? { engines: preloaded.engines } : await api("/api/engines")]
    : await Promise.all([api("/api/models"), api("/api/agents"), api("/api/engines")]);
  const previousEngine = engineSelect.value;
  engineSelect.replaceChildren();
  for (const engine of engines.engines.filter((item) => item.enabled && item.available)) {
    const option = document.createElement("option");
    option.value = engine.id;
    option.textContent = engine.name;
    engineSelect.append(option);
  }
  engineSelect.value = [...engineSelect.options].some((item) => item.value === previousEngine)
    ? previousEngine : (engineSelect.options[0]?.value || "");
  modelChoices = {};
  for (const item of models.models.filter((item) => item.enabled && (currentRole === "admin" || item.user_enabled))) {
    (modelChoices[item.provider] ||= []).push(item.model_id);
  }
  const previousProvider = providerInput.value;
  providerInput.replaceChildren();
  for (const provider of Object.keys(modelChoices)) {
    const option = document.createElement("option");
    option.value = provider;
    option.textContent = providerLabels[provider] || provider;
    providerInput.append(option);
  }
  providerInput.value = Object.hasOwn(modelChoices, previousProvider) ? previousProvider : (providerInput.options[0]?.value || "");
  populateModelChoices(providerInput.value);
  availableAgents = agents.agents;
  const previousAgent = agentSelect.value;
  agentSelect.replaceChildren();
  for (const agent of availableAgents.filter((item) => item.enabled && item.granted)) {
    const option = document.createElement("option");
    option.value = agent.agent_id;
    option.textContent = agent.name;
    agentSelect.append(option);
  }
  agentSelect.value = [...agentSelect.options].some((item) => item.value === previousAgent)
    ? previousAgent : (agentSelect.options[0]?.value || "");
  updateActiveSelection();
  updateKeyState();
  const initial = preloaded?.initial_agent;
  await refreshAgentCapabilities(initial?.agent?.agent_id === agentSelect.value ? initial : null);
}

async function refreshAgentCapabilities(preloaded = null) {
  const version = ++capabilityRequestVersion;
  const agentId = agentSelect.value;
  if (!agentId) {
    agentCapabilities.textContent = "当前没有可用的 Agent";
    inspectorName.textContent = "Agent 配置";
    agentRules.textContent = "当前没有可用的 Agent";
    agentSkills.textContent = "未配置";
    agentMcps.textContent = "未配置";
    return;
  }
  agentCapabilities.textContent = "正在读取 Agent 能力…";
  try {
    const data = preloaded || await api(`/api/agents/${encodeURIComponent(agentId)}/capabilities`);
    if (version !== capabilityRequestVersion) return;
    renderAgentDetails(data);
    const grouped = { prompt: [], skill: [], mcp: [] };
    for (const item of data.capabilities) grouped[item.kind]?.push(item.name);
    agentCapabilities.textContent = [
      `Prompt：${grouped.prompt.join("、") || "未配置"}`,
      `Skill：${grouped.skill.join("、") || "未配置"}`,
      `MCP：${grouped.mcp.join("、") || "未连接"}`,
    ].join("  ·  ");
  } catch (error) {
    if (version === capabilityRequestVersion) {
      agentCapabilities.textContent = `能力读取失败：${error.message}`;
      agentRules.textContent = error.message;
    }
  }
}

function inspectorCard(title, content) {
  const card = document.createElement("div");
  card.className = "inspector-card";
  const heading = document.createElement("strong");
  heading.textContent = title;
  card.append(heading);
  if (content) {
    const description = document.createElement("p");
    description.textContent = content;
    card.append(description);
  }
  return card;
}

function renderAgentDetails(data) {
  inspectorName.textContent = data.agent.name;
  agentRules.replaceChildren();
  agentSkills.replaceChildren();
  agentMcps.replaceChildren();
  const rules = [
    { name: "Agent 指令", content: data.agent.instructions },
    ...data.capabilities.filter((item) => item.kind === "prompt")
      .map((item) => ({ name: `Prompt · ${item.name}`, content: item.content })),
  ];
  for (const rule of rules) if (rule.content) agentRules.append(inspectorCard(rule.name, rule.content));
  if (data.agent.delegate_id) agentRules.append(inspectorCard("协作 Agent", data.agent.delegate_id));
  if (!agentRules.childElementCount) agentRules.textContent = "未设置额外规则";

  for (const skill of data.capabilities.filter((item) => item.kind === "skill")) {
    const details = document.createElement("details");
    details.className = "inspector-card";
    const summary = document.createElement("summary");
    summary.textContent = `${skill.name} (${skill.display_id || skill.capability_id})`;
    const content = document.createElement("p");
    content.textContent = skill.content;
    details.append(summary, content);
    agentSkills.append(details);
  }
  if (!agentSkills.childElementCount) agentSkills.textContent = "未配置 Skill";

  for (const mcp of data.capabilities.filter((item) => item.kind === "mcp")) {
    agentMcps.append(inspectorCard(mcp.name, `服务名：${mcp.display_id || mcp.capability_id}`));
  }
  if (!agentMcps.childElementCount) agentMcps.textContent = "未配置 MCP 服务";
}

function resetRunTrace() {
  knownAvailableTools = [];
  agentTools.textContent = "发送消息后显示本轮实际可用的 MCP 工具。";
  agentTrace.textContent = "发送消息后显示 DSH 的工具调用记录。";
}

function renderRunTrace(run) {
  if (Array.isArray(run?.available_tools) && run.available_tools.length) {
    knownAvailableTools = run.available_tools;
  }
  agentTools.replaceChildren();
  const mcpTools = knownAvailableTools.filter((name) => name.startsWith("mcp__"));
  for (const name of mcpTools) {
    const pill = document.createElement("span");
    pill.className = "inspector-pill";
    pill.textContent = name;
    agentTools.append(pill);
  }
  if (!mcpTools.length) agentTools.textContent = "本轮未发现已注册的 MCP 工具";
  agentTrace.replaceChildren();
  const calls = Array.isArray(run?.tool_calls) ? run.tool_calls : [];
  for (const call of calls) {
    const card = document.createElement("div");
    card.className = "inspector-card inspector-tool-row";
    const label = document.createElement("strong");
    label.textContent = `${call.kind === "mcp" ? "MCP" : call.kind === "skill" ? "Skill" : "工具"} · ${call.name}`;
    const state = document.createElement("small");
    state.textContent = call.status === "completed" ? "完成" : call.status === "error" ? "失败" : "已开始";
    if (Number.isFinite(call.duration_ms)) state.textContent += ` · ${call.duration_ms}ms`;
    card.append(label, state);
    agentTrace.append(card);
  }
  if (!calls.length) agentTrace.textContent = "本轮没有工具调用；模型直接回答。";
}

function updateKeyState() {
  const needsOwnKey = currentRole === "user" || providerInput.value !== "deepseek-official";
  const hasKey = Boolean(apiKeyInput.value.trim());
  connectionLabel.textContent = needsOwnKey ? (hasKey ? "Key 已填写" : "待填写 Key") : "服务端 Key";
  connectionLabel.classList.toggle("pending", needsOwnKey && !hasKey);
  mobileSettingsToggle.textContent = needsOwnKey && !hasKey ? "填写 Key" : "模型设置";
  apiKeyInput.placeholder = providerInput.value === "qwen-bailian"
    ? "北京地域的阿里云百炼 API Key" : "填写你自己的 API Key";
  modelHint.textContent = needsOwnKey
    ? (providerInput.value === "qwen-bailian"
      ? "千问使用北京地域的百炼按量计费 API Key，不适用 Token Plan Key；请选择列表中的模型。切换模型或 Key 后，请先点“新会话”。"
      : "聊天使用你填写的该厂家 API Key。切换厂家、模型或 Key 后，请先点“新会话”。密钥不存数据库，刷新后需重填。")
    : "管理员当前使用服务端 DeepSeek Key；也可以填写自己的 Key。切换模型或 Key 后，请先点“新会话”。";
}

apiKeyInput.addEventListener("input", updateKeyState);
agentSelect.addEventListener("change", () => {
  updateActiveSelection();
  resetRunTrace();
  refreshAgentCapabilities();
});
engineSelect.addEventListener("change", updateActiveSelection);
providerInput.addEventListener("change", () => {
  populateModelChoices(providerInput.value);
  updateKeyState();
});
modelPreset.addEventListener("change", () => {
  modelInput.value = modelPreset.value;
  updateActiveSelection();
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "X-Session-Token": sessionToken, ...(options.headers || {}) },
  });
  const data = await response.json();
  if (response.status === 401 || (response.status === 403 && data.detail === "账号已停用")) {
    sessionStorage.removeItem("agent_session");
    window.location.replace("/");
  }
  if (!response.ok) {
    const error = new Error(data.detail || `请求失败 (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function chatKey() {
  return `agent_chat_${currentUserId}`;
}

function historyKey() {
  return `agent_chat_history_${currentUserId}`;
}

function activeChatKey() {
  return `agent_active_chat_${currentUserId}`;
}

function chatTitle(items) {
  const first = items.find((item) => item.role === "你");
  return first ? first.content.replace(/\s+/g, " ").trim().slice(0, 32) : "未命名会话";
}

function persistHistory() {
  try {
    localStorage.setItem(historyKey(), JSON.stringify(historyChats));
    return true;
  } catch (_) {
    status.textContent = "历史记录保存失败，请检查浏览器存储空间";
    return false;
  }
}

function renderHistory() {
  const list = document.getElementById("chat-history");
  list.replaceChildren();
  if (!historyChats.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "发送消息后，会话会显示在这里";
    list.append(empty);
    return;
  }
  for (const chat of historyChats) {
    const row = document.createElement("div");
    row.className = `history-row${chat.id === currentChatId ? " active" : ""}`;
    const open = document.createElement("button");
    open.type = "button";
    open.className = "history-open";
    open.title = chat.title;
    open.setAttribute("aria-current", chat.id === currentChatId ? "true" : "false");
    const title = document.createElement("span");
    title.className = "history-title";
    title.textContent = chat.title;
    const time = document.createElement("small");
    time.textContent = new Date(chat.updatedAt).toLocaleString("zh-CN", {
      month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
    open.append(title, time);
    open.addEventListener("click", () => openChat(chat.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "history-delete";
    remove.title = serverHistoryAvailable ? "删除会话" : "删除本机历史记录";
    remove.setAttribute("aria-label", `删除会话：${chat.title}`);
    remove.textContent = "×";
    remove.addEventListener("click", async () => {
      const scope = serverHistoryAvailable ? "会话记录" : "本机历史记录";
      if (send.disabled || !window.confirm(`删除“${chat.title}”的${scope}？`)) return;
      remove.disabled = true;
      try {
        if (serverHistoryAvailable && chat.sessionId) {
          await api(`/api/chat/${encodeURIComponent(chat.sessionId)}`, { method: "DELETE" });
        }
      } catch (error) {
        status.textContent = `删除失败：${error.message}`;
        remove.disabled = false;
        return;
      }
      historyChats = historyChats.filter((item) => item.id !== chat.id);
      if (currentChatId === chat.id) startNewChat();
      persistHistory();
      renderHistory();
    });
    row.append(open, remove);
    list.append(row);
  }
}

function saveChat() {
  if (!entries.length) return;
  if (!currentChatId) currentChatId = crypto.randomUUID();
  const previous = historyChats.find((chat) => chat.id === currentChatId);
  const chat = {
    id: currentChatId, sessionId, entries: [...entries],
    provider: providerInput.value, model: modelInput.value.trim(),
    agentId: agentSelect.value,
    engineId: engineSelect.value,
    title: chatTitle(entries), updatedAt: Date.now(),
    serverBacked: previous?.serverBacked || false,
  };
  historyChats = [chat, ...historyChats.filter((item) => item.id !== currentChatId)];
  if (previous && !chat.sessionId) chat.sessionId = previous.sessionId;
  sessionStorage.setItem(activeChatKey(), currentChatId);
  persistHistory();
  renderHistory();
}

function formatDuration(milliseconds) {
  return `耗时 ${(milliseconds / 1000).toFixed(1)} 秒`;
}

function addMessage(role, content, kind, durationMs = null) {
  const row = document.createElement("div");
  row.className = `message-row ${kind}`;
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "你" ? "你" : "✦";
  const body = document.createElement("div");
  body.className = "message-content";
  const label = document.createElement("p");
  label.className = "message-role";
  label.textContent = role;
  const text = document.createElement("div");
  text.className = "message-text";
  text.textContent = content;
  body.append(label, text);
  if (Number.isFinite(durationMs)) {
    const duration = document.createElement("p");
    duration.className = "message-duration";
    duration.textContent = formatDuration(durationMs);
    body.append(duration);
  }
  row.append(avatar, body);
  messages.append(row);
  document.getElementById("welcome").hidden = true;
  scroll.scrollTop = scroll.scrollHeight;
}

function startNewChat() {
  if (send.disabled) return;
  closeAdminWorkspace();
  closeMyCapabilitiesWorkspace();
  selectionVersion += 1;
  currentChatId = null;
  sessionId = null;
  entries = [];
  messages.replaceChildren();
  document.getElementById("welcome").hidden = false;
  setMobilePanel();
  closeHistoryPanel();
  resetRunTrace();
  sessionStorage.removeItem(activeChatKey());
  renderHistory();
  status.textContent = "已开始新会话";
  textarea.focus();
}

function openChat(id) {
  if (send.disabled) return;
  const chat = historyChats.find((item) => item.id === id);
  if (!chat) return;
  closeAdminWorkspace();
  closeMyCapabilitiesWorkspace();
  setMobilePanel();
  closeHistoryPanel();
  selectionVersion += 1;
  const changedProvider = providerInput.value !== chat.provider;
  currentChatId = id;
  sessionId = chat.sessionId || null;
  entries = [...chat.entries];
  if (Object.hasOwn(modelChoices, chat.provider)) {
    providerInput.value = chat.provider;
    populateModelChoices(chat.provider, chat.model || "");
    if (changedProvider) apiKeyInput.value = "";
    updateKeyState();
  }
  const agentAvailable = [...agentSelect.options].some((item) => item.value === (chat.agentId || "default"));
  agentSelect.value = agentAvailable
    ? (chat.agentId || "default") : "default";
  const engineAvailable = [...engineSelect.options].some((item) => item.value === (chat.engineId || "dsh-0.1.5rc1"));
  if (engineAvailable) engineSelect.value = chat.engineId || "dsh-0.1.5rc1";
  updateActiveSelection();
  resetRunTrace();
  refreshAgentCapabilities();
  const latestRun = [...entries].reverse().find((item) => item.kind === "agent" && item.runTrace)?.runTrace;
  if (latestRun) renderRunTrace(latestRun);
  messages.replaceChildren();
  document.getElementById("welcome").hidden = entries.length > 0;
  for (const item of entries) addMessage(item.role, item.content, item.kind, item.durationMs);
  sessionStorage.setItem(activeChatKey(), id);
  renderHistory();
  status.textContent = agentAvailable
    ? "已打开历史会话；继续发送请使用原 Agent、模型和 API Key"
    : "原 Agent 已不可用；可查看历史，请新建会话后继续";
  if (chat.sessionId && serverHistoryAvailable) {
    loadServerMessages(chat.id, chat.sessionId);
  }
}

async function loadServerMessages(chatId, sessionId) {
  const version = selectionVersion;
  const initialCount = historyChats.find((item) => item.id === chatId)?.entries.length;
  try {
    const data = await api(`/api/chat/${encodeURIComponent(sessionId)}/messages`);
    if (!data.messages.length) return;
    const chat = historyChats.find((item) => item.id === chatId);
    if (!chat) return;
    if (send.disabled || chat.entries.length !== initialCount) return;
    const previousAnswers = chat.entries.filter((item) => item.kind === "agent");
    let answerIndex = 0;
    chat.entries = data.messages.map((item) => {
      const entry = {
        role: item.role === "user" ? "你" : "Agent",
        kind: item.role === "user" ? "user" : "agent",
        content: item.content,
      };
      if (entry.kind === "agent") {
        const prior = previousAnswers[answerIndex++];
        if (prior?.content === entry.content) {
          entry.durationMs = prior.durationMs;
          entry.runTrace = prior.runTrace;
        }
      }
      return entry;
    });
    persistHistory();
    if (currentChatId !== chatId || selectionVersion !== version) return;
    entries = [...chat.entries];
    messages.replaceChildren();
    for (const item of entries) addMessage(item.role, item.content, item.kind);
    const latestRun = [...entries].reverse().find((item) => item.kind === "agent" && item.runTrace)?.runTrace;
    if (latestRun) renderRunTrace(latestRun);
  } catch (error) {
    if (currentChatId === chatId) status.textContent = `显示本机历史：${error.message}`;
  }
}

async function syncHistoryFromServer() {
  const version = selectionVersion;
  try {
    const data = await api("/api/chats");
    serverHistoryAvailable = true;
    document.getElementById("history-note").textContent = "历史已同步到服务端";
    const serverIds = new Set(data.chats.map((item) => item.session_id));
    const synced = data.chats.map((item) => {
      const local = historyChats.find((chat) => chat.sessionId === item.session_id);
      return {
        id: local?.id || item.session_id,
        sessionId: item.session_id,
        entries: local?.entries || [],
        title: item.title || "未命名会话",
        provider: item.provider,
        model: item.model,
        agentId: item.agent_id || local?.agentId || "default",
        engineId: item.engine_id || local?.engineId || "dsh-0.1.5rc1",
        updatedAt: item.updated_at,
        serverBacked: true,
      };
    });
    historyChats = [...synced, ...historyChats.filter((chat) =>
      !chat.serverBacked && (!chat.sessionId || !serverIds.has(chat.sessionId)))];
    historyChats.sort((a, b) => b.updatedAt - a.updatedAt);
    persistHistory();
    renderHistory();
    if (selectionVersion === version && !currentChatId && synced.length) openChat(synced[0].id);
  } catch (_) {
    serverHistoryAvailable = false;
    document.getElementById("history-note").textContent = "历史仅保存在本机浏览器";
  }
}

function restoreChat() {
  try {
    const saved = JSON.parse(localStorage.getItem(historyKey()) || "[]");
    historyChats = Array.isArray(saved) ? saved.filter((item) =>
      item && typeof item.id === "string" && Array.isArray(item.entries)) : [];
    const oldChat = JSON.parse(sessionStorage.getItem(chatKey()) || "null");
    if (oldChat && Array.isArray(oldChat.entries) && oldChat.entries.length) {
      const existing = historyChats.some((chat) => chat.sessionId && chat.sessionId === oldChat.sessionId);
      if (!existing) {
        const id = oldChat.sessionId || crypto.randomUUID();
        historyChats.unshift({
          id, sessionId: oldChat.sessionId || null, entries: oldChat.entries,
          provider: oldChat.provider || "deepseek-official", model: oldChat.model || "",
          agentId: oldChat.agentId || "default",
          engineId: oldChat.engineId || "dsh-0.1.5rc1",
          title: chatTitle(oldChat.entries), updatedAt: Date.now(),
        });
        sessionStorage.setItem(activeChatKey(), id);
      }
      if (persistHistory()) sessionStorage.removeItem(chatKey());
    }
    renderHistory();
    const active = sessionStorage.getItem(activeChatKey());
    const selected = historyChats.find((chat) => chat.id === active) || historyChats[0];
    if (selected) openChat(selected.id);
    syncHistoryFromServer();
  } catch (_) {
    historyChats = [];
    renderHistory();
    status.textContent = "历史记录读取失败，请检查浏览器存储";
  }
}

function adminMessage(message) {
  document.getElementById("admin-result").textContent = message;
}

function fillAdminSelect(id, items, valueOf, labelOf, emptyLabel) {
  const select = document.getElementById(id);
  const previous = select.value;
  select.replaceChildren();
  if (!items.length) {
    const option = new Option(emptyLabel, "");
    select.append(option);
    return;
  }
  for (const item of items) select.append(new Option(labelOf(item), valueOf(item)));
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
}

async function refreshGrantPreview() {
  const userId = document.getElementById("grant-user").value;
  const target = document.getElementById("grant-list");
  if (!userId) { target.textContent = "暂无普通用户"; return; }
  const data = await api(`/api/admin/users/${encodeURIComponent(userId)}/agents`);
  if (document.getElementById("grant-user").value === userId) {
    target.textContent = `已授权 Agent：${data.agent_ids.join("、") || "无"}`;
  }
}

async function refreshAssignmentPreview() {
  const agentId = document.getElementById("assign-agent").value;
  const target = document.getElementById("assign-list");
  if (!agentId) { target.textContent = "暂无 Agent"; return; }
  const data = await api(`/api/admin/agents/${encodeURIComponent(agentId)}/capabilities`);
  if (document.getElementById("assign-agent").value === agentId) {
    target.textContent = `已分配能力：${data.capability_ids.join("、") || "无"}`;
  }
}

document.getElementById("grant-user").addEventListener("change", () => {
  refreshGrantPreview().catch((error) => adminMessage(error.message));
});
document.getElementById("assign-agent").addEventListener("change", () => {
  refreshAssignmentPreview().catch((error) => adminMessage(error.message));
});

let activeAdminTab = "users";
let capabilityCatalog = [];
const capabilityLabels = { prompt: "Prompt", skill: "Skill", mcp: "MCP" };
const capabilityDescriptions = {
  prompt: "为 Agent 增加明确规则。保存后，还需在“能力分配”中分配给 Agent。",
  skill: "保存 DSH Skill 内容。保存后，还需在“能力分配”中分配给 Agent。",
  mcp: "连接已运行的 Streamable HTTP MCP 服务。保存后，还需在“能力分配”中分配给 Agent。",
};

function renderCapabilityList() {
  const kind = capabilityLabels[activeAdminTab] ? activeAdminTab : "prompt";
  const list = document.getElementById("capability-list");
  list.replaceChildren();
  for (const item of capabilityCatalog.filter((entry) => entry.kind === kind)) {
    managementRow(list, `${item.name} (${item.capability_id})`,
      item.enabled ? "启用" : "停用", () => {
        document.getElementById("capability-id").value = item.capability_id;
        document.getElementById("capability-kind").value = item.kind;
        document.getElementById("capability-name").value = item.name;
        document.getElementById("capability-content").value = item.content;
        document.getElementById("capability-endpoint").value = item.endpoint;
        document.getElementById("capability-enabled").checked = item.enabled;
        document.getElementById("capability-form").scrollIntoView({ block: "start" });
      });
  }
  if (!list.childElementCount) list.textContent = `暂无${capabilityLabels[kind]}，可在上方新增。`;
}

function setAdminTab(tab) {
  if (!document.querySelector(`[data-admin-tab="${tab}"]`)) return;
  const previousTab = activeAdminTab;
  activeAdminTab = tab;
  for (const button of document.querySelectorAll("[data-admin-tab]")) {
    const selected = button.dataset.adminTab === tab;
    button.setAttribute("aria-current", selected ? "page" : "false");
  }
  for (const view of document.querySelectorAll("[data-admin-view]")) {
    view.hidden = view.dataset.adminView !== (capabilityLabels[tab] ? "capability" : tab);
  }
  if (capabilityLabels[tab]) {
    const label = capabilityLabels[tab];
    if (previousTab !== tab) document.getElementById("capability-form").reset();
    document.getElementById("capability-kind").value = tab;
    document.getElementById("capability-title").textContent = `${label} 管理`;
    document.getElementById("capability-description").textContent = capabilityDescriptions[tab];
    document.getElementById("capability-list-title").textContent = `已有 ${label}`;
    document.getElementById("capability-submit").textContent = `保存 ${label}`;
    document.getElementById("capability-content-label").textContent = `${label} 内容`;
    document.getElementById("capability-content-field").hidden = tab === "mcp";
    document.getElementById("capability-endpoint-field").hidden = tab !== "mcp";
    document.getElementById("capability-content").required = tab !== "mcp";
    document.getElementById("capability-endpoint").required = tab === "mcp";
    renderCapabilityList();
  }
  document.querySelector(".admin-content").scrollTop = 0;
  if (tab === "mcp-review") refreshUserMcps().catch((error) => adminMessage(error.message));
}

for (const button of document.querySelectorAll("[data-admin-tab]")) {
  button.addEventListener("click", () => {
    adminMessage("");
    setAdminTab(button.dataset.adminTab);
  });
}

async function refreshUsers() {
  const data = await api("/api/admin/users");
  fillAdminSelect("grant-user", data.users.filter((user) => user.role === "user"),
    (user) => user.user_id, (user) => user.user_id, "暂无普通用户");
  const container = document.getElementById("users");
  container.replaceChildren();
  for (const user of data.users) {
    const row = document.createElement("div");
    row.className = "user-row";
    const meta = document.createElement("div");
    meta.className = "user-meta";
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = user.user_id[0].toUpperCase();
    const labels = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = user.user_id;
    const caption = document.createElement("small");
    caption.textContent = `${user.role === "admin" ? "管理员" : "普通用户"} · ${user.sessions} 个会话`;
    labels.append(name, caption);
    const badge = document.createElement("span");
    badge.className = `status-pill${user.enabled ? "" : " off"}`;
    badge.textContent = user.enabled ? "已启用" : "未启用";
    meta.append(avatar, labels, badge);
    const actions = document.createElement("div");
    actions.className = "user-actions";
    if (user.user_id !== currentUserId) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.textContent = user.enabled ? "停用" : "启用";
      toggle.addEventListener("click", async () => {
        toggle.disabled = true;
        try {
          await api(`/api/admin/users/${encodeURIComponent(user.user_id)}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: !user.enabled }),
          });
          adminMessage(`${user.user_id} 已${user.enabled ? "停用" : "启用"}`);
          await refreshUsers();
        } catch (error) {
          adminMessage(error.message);
          toggle.disabled = false;
        }
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "delete";
      remove.textContent = "删除";
      remove.addEventListener("click", async () => {
        if (!window.confirm(`确定删除账号 ${user.user_id}？该用户名将不能再次注册。`)) return;
        remove.disabled = true;
        try {
          await api(`/api/admin/users/${encodeURIComponent(user.user_id)}`, { method: "DELETE" });
          adminMessage(`${user.user_id} 已删除`);
          await refreshUsers();
        } catch (error) {
          adminMessage(error.message);
          remove.disabled = false;
        }
      });
      actions.append(toggle, remove);
    }
    row.append(meta, actions);
    container.append(row);
  }
  await refreshGrantPreview();
}

function managementRow(container, title, detail, onEdit) {
  const row = document.createElement("div");
  row.className = "user-row";
  const meta = document.createElement("div");
  meta.className = "user-meta";
  const text = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = title;
  const caption = document.createElement("small");
  caption.textContent = detail;
  text.append(name, caption);
  meta.append(text);
  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "secondary-button";
  edit.textContent = "编辑";
  edit.addEventListener("click", onEdit);
  row.append(meta, edit);
  container.append(row);
}

async function refreshPlatform() {
  const [models, agents, capabilities] = await Promise.all([
    api("/api/models"), api("/api/agents"), api("/api/admin/capabilities"),
  ]);
  const modelList = document.getElementById("model-list");
  modelList.replaceChildren();
  for (const item of models.models) {
    managementRow(modelList, `${item.provider} / ${item.model_id}`,
      `${item.enabled ? "启用" : "停用"} · ${item.user_enabled ? "普通用户可用" : "仅管理员"}`, () => {
        document.getElementById("manage-provider").value = item.provider;
        document.getElementById("manage-model").value = item.model_id;
        document.getElementById("manage-model-enabled").checked = item.enabled;
        document.getElementById("manage-model-users").checked = item.user_enabled;
      });
  }
  const agentList = document.getElementById("agent-list");
  fillAdminSelect("grant-agent", agents.agents.filter((item) => item.agent_id !== "default"),
    (item) => item.agent_id, (item) => `${item.name} (${item.agent_id})`, "暂无可授权 Agent");
  fillAdminSelect("assign-agent", agents.agents,
    (item) => item.agent_id, (item) => `${item.name} (${item.agent_id})`, "暂无 Agent");
  agentList.replaceChildren();
  for (const item of agents.agents) {
    managementRow(agentList, `${item.name} (${item.agent_id})`,
      `${item.enabled ? "启用" : "停用"}${item.delegate_id ? ` · 协作 ${item.delegate_id}` : ""}`, () => {
        document.getElementById("manage-agent-id").value = item.agent_id;
        document.getElementById("manage-agent-name").value = item.name;
        document.getElementById("manage-agent-instructions").value = item.instructions;
        document.getElementById("manage-agent-delegate").value = item.delegate_id || "";
        document.getElementById("manage-agent-enabled").checked = item.enabled;
      });
  }
  capabilityCatalog = capabilities.capabilities;
  fillAdminSelect("assign-capability", capabilityCatalog,
    (item) => item.capability_id,
    (item) => `${item.name} · ${item.kind.toUpperCase()} (${item.capability_id})`, "暂无能力");
  renderCapabilityList();
  await refreshAssignmentPreview();
}

document.getElementById("model-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const provider = document.getElementById("manage-provider").value;
  const model = document.getElementById("manage-model").value.trim();
  try {
    await api(`/api/admin/models/${encodeURIComponent(provider)}/${encodeURIComponent(model)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: document.getElementById("manage-model-enabled").checked,
        user_enabled: document.getElementById("manage-model-users").checked,
      }),
    });
    adminMessage(`模型 ${provider}/${model} 已保存`);
    await Promise.all([refreshPlatform(), loadCatalog()]);
  } catch (error) { adminMessage(error.message); }
});

document.getElementById("agent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const agentId = document.getElementById("manage-agent-id").value.trim();
  try {
    await api(`/api/admin/agents/${encodeURIComponent(agentId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: document.getElementById("manage-agent-name").value.trim(),
        instructions: document.getElementById("manage-agent-instructions").value,
        delegate_id: document.getElementById("manage-agent-delegate").value.trim() || null,
        enabled: document.getElementById("manage-agent-enabled").checked,
      }),
    });
    adminMessage(`Agent ${agentId} 已保存`);
    await Promise.all([refreshPlatform(), loadCatalog()]);
  } catch (error) { adminMessage(error.message); }
});

document.getElementById("agent-grant-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const userId = document.getElementById("grant-user").value.trim().toLowerCase();
  const agentId = document.getElementById("grant-agent").value.trim();
  const granted = document.getElementById("grant-enabled").checked;
  try {
    await api(`/api/admin/users/${encodeURIComponent(userId)}/agents/${encodeURIComponent(agentId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ granted }),
    });
    const data = await api(`/api/admin/users/${encodeURIComponent(userId)}/agents`);
    document.getElementById("grant-list").textContent = `${userId} 已授权：${data.agent_ids.join("、") || "无"}`;
    adminMessage(`${userId} 对 ${agentId} 的授权已${granted ? "开启" : "关闭"}`);
  } catch (error) { adminMessage(error.message); }
});

document.getElementById("capability-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const capabilityId = document.getElementById("capability-id").value.trim();
  try {
    await api(`/api/admin/capabilities/${encodeURIComponent(capabilityId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: document.getElementById("capability-kind").value,
        name: document.getElementById("capability-name").value.trim(),
        content: document.getElementById("capability-content").value,
        endpoint: document.getElementById("capability-endpoint").value.trim(),
        enabled: document.getElementById("capability-enabled").checked,
      }),
    });
    adminMessage(`能力 ${capabilityId} 已保存`);
    await refreshPlatform();
    await refreshAgentCapabilities();
  } catch (error) { adminMessage(error.message); }
});

document.getElementById("capability-assign-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const agentId = document.getElementById("assign-agent").value.trim();
  const capabilityId = document.getElementById("assign-capability").value.trim();
  const assigned = document.getElementById("assign-enabled").checked;
  try {
    await api(`/api/admin/agents/${encodeURIComponent(agentId)}/capabilities/${encodeURIComponent(capabilityId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assigned }),
    });
    const data = await api(`/api/admin/agents/${encodeURIComponent(agentId)}/capabilities`);
    document.getElementById("assign-list").textContent =
      `${agentId} 已分配：${data.capability_ids.join("、") || "无"}`;
    adminMessage(`${agentId} 的 ${capabilityId} 能力已${assigned ? "分配" : "取消"}`);
    if (agentSelect.value === agentId) await refreshAgentCapabilities();
  } catch (error) { adminMessage(error.message); }
});

function closeAdminWorkspace() {
  adminDialog.hidden = true;
  app.classList.remove("admin-open");
}

document.getElementById("admin-trigger").addEventListener("click", () => {
  closeMyCapabilitiesWorkspace();
  closeHistoryPanel();
  setMobilePanel();
  setAdminTab("users");
  adminMessage("");
  adminDialog.hidden = false;
  app.classList.add("admin-open");
  refreshUsers().catch((error) => adminMessage(error.message));
  refreshPlatform().catch((error) => adminMessage(error.message));
});
document.getElementById("close-admin").addEventListener("click", closeAdminWorkspace);

async function refreshUserMcps() {
  const target = document.getElementById("user-mcp-review-list");
  const data = await api("/api/admin/user-mcps");
  target.replaceChildren();
  if (!data.mcps.length) { target.textContent = "暂无用户 MCP"; return; }
  for (const item of data.mcps) {
    const row = document.createElement("div");
    row.className = "user-row";
    const info = document.createElement("div");
    info.className = "user-meta";
    const labels = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = `${item.user_id} · ${item.name} (${item.capability_id})`;
    const endpoint = document.createElement("small");
    endpoint.textContent = `${item.endpoint} · ${item.approved ? "已批准" : "待审核"}${item.enabled ? "" : " · 已停用"}`;
    labels.append(name, endpoint);
    info.append(labels);
    const button = document.createElement("button");
    button.className = "secondary-button";
    button.type = "button";
    button.textContent = item.approved ? "撤销批准" : "批准连接";
    button.addEventListener("click", async () => {
      if (!window.confirm(`${item.approved ? "撤销" : "批准"} ${item.user_id} 的 MCP 地址？\n${item.endpoint}`)) return;
      button.disabled = true;
      try {
        await api(`/api/admin/users/${encodeURIComponent(item.user_id)}/mcps/${encodeURIComponent(item.capability_id)}/approval`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: !item.approved }),
        });
        adminMessage(`已${item.approved ? "撤销" : "批准"} ${item.user_id} 的 ${item.capability_id}`);
        await refreshUserMcps();
      } catch (error) { adminMessage(error.message); button.disabled = false; }
    });
    row.append(info, button);
    target.append(row);
  }
}

let activeMyTab = "prompt";
let myCapabilityCatalog = [];
const myDescriptions = {
  prompt: "编写自己的对话规则，保存后在“绑定 Agent”中启用。",
  skill: "编写 DSH Skill 内容，保存后在“绑定 Agent”中启用；ID 仅用小写字母、数字和连接符。",
  mcp: "填写你运行的 Streamable HTTP MCP 地址。管理员审核地址后，已绑定的 Agent 才会连接。",
};

function myCapMessage(message) {
  document.getElementById("my-cap-result").textContent = message;
}

function setMyTab(tab) {
  if (!["prompt", "skill", "mcp", "assign"].includes(tab)) return;
  const previous = activeMyTab;
  activeMyTab = tab;
  for (const button of document.querySelectorAll("[data-my-tab]")) {
    button.setAttribute("aria-current", button.dataset.myTab === tab ? "page" : "false");
  }
  document.querySelector('[data-my-view="catalog"]').hidden = tab === "assign";
  document.querySelector('[data-my-view="assign"]').hidden = tab !== "assign";
  if (tab !== "assign") {
    if (previous !== tab) document.getElementById("my-cap-form").reset();
    document.getElementById("my-cap-kind-title").textContent = `我的 ${capabilityLabels[tab]}`;
    document.getElementById("my-cap-description").textContent = myDescriptions[tab];
    document.getElementById("my-cap-list-title").textContent = `已有 ${capabilityLabels[tab]}`;
    document.getElementById("my-cap-submit").textContent = `保存 ${capabilityLabels[tab]}`;
    document.getElementById("my-cap-content-field").hidden = tab === "mcp";
    document.getElementById("my-cap-endpoint-field").hidden = tab !== "mcp";
    document.getElementById("my-cap-content").required = tab !== "mcp";
    document.getElementById("my-cap-endpoint").required = tab === "mcp";
    renderMyCatalog();
  }
  myCapabilitiesWorkspace.querySelector(".admin-content").scrollTop = 0;
}

function renderMyCatalog() {
  const list = document.getElementById("my-cap-list");
  list.replaceChildren();
  for (const item of myCapabilityCatalog.filter((entry) => entry.kind === activeMyTab)) {
    const row = document.createElement("div");
    row.className = "user-row";
    const meta = document.createElement("div");
    meta.className = "user-meta";
    const labels = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${item.name} (${item.capability_id})`;
    const detail = document.createElement("small");
    detail.textContent = `${item.enabled ? "启用" : "停用"}${item.kind === "mcp" ? (item.approved ? " · 已审核" : " · 待审核") : ""}`;
    labels.append(title, detail);
    meta.append(labels);
    const actions = document.createElement("div");
    actions.className = "user-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "编辑";
    edit.addEventListener("click", () => {
      document.getElementById("my-cap-id").value = item.capability_id;
      document.getElementById("my-cap-name").value = item.name;
      document.getElementById("my-cap-content").value = item.content;
      document.getElementById("my-cap-endpoint").value = item.endpoint;
      document.getElementById("my-cap-enabled").checked = item.enabled;
      document.getElementById("my-cap-form").scrollIntoView({ block: "start" });
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete";
    remove.textContent = "删除";
    remove.addEventListener("click", async () => {
      if (!window.confirm(`删除自己的能力“${item.name}”？相关 Agent 绑定也会移除。`)) return;
      remove.disabled = true;
      try {
        await api(`/api/my/capabilities/${encodeURIComponent(item.capability_id)}`, { method: "DELETE" });
        myCapMessage(`${item.name} 已删除`);
        await refreshMyCatalog();
        await refreshAgentCapabilities();
      } catch (error) { myCapMessage(error.message); remove.disabled = false; }
    });
    actions.append(edit, remove);
    row.append(meta, actions);
    list.append(row);
  }
  if (!list.childElementCount && activeMyTab !== "assign") {
    list.textContent = `暂无 ${capabilityLabels[activeMyTab]}，可在上方新建。`;
  }
}

async function refreshMyAssignments() {
  const agentId = document.getElementById("my-assign-agent").value;
  const target = document.getElementById("my-assign-list");
  if (!agentId) { target.textContent = "暂无可用 Agent"; return; }
  const data = await api(`/api/my/agents/${encodeURIComponent(agentId)}/capabilities`);
  if (document.getElementById("my-assign-agent").value === agentId) {
    target.textContent = `已绑定：${data.capability_ids.join("、") || "无"}`;
  }
}

async function refreshMyCatalog() {
  const [catalog, agents] = await Promise.all([api("/api/my/capabilities"), api("/api/agents")]);
  myCapabilityCatalog = catalog.capabilities;
  fillAdminSelect("my-assign-agent", agents.agents.filter((item) => item.enabled && item.granted),
    (item) => item.agent_id, (item) => `${item.name} (${item.agent_id})`, "暂无可用 Agent");
  fillAdminSelect("my-assign-capability", myCapabilityCatalog,
    (item) => item.capability_id, (item) => `${item.name} · ${item.kind.toUpperCase()}`, "暂无个人能力");
  renderMyCatalog();
  await refreshMyAssignments();
}

function closeMyCapabilitiesWorkspace() {
  myCapabilitiesWorkspace.hidden = true;
  app.classList.remove("capabilities-open");
}

document.getElementById("capabilities-trigger").addEventListener("click", () => {
  closeAdminWorkspace();
  closeHistoryPanel();
  setMobilePanel();
  setMyTab("prompt");
  myCapMessage("");
  myCapabilitiesWorkspace.hidden = false;
  app.classList.add("capabilities-open");
  refreshMyCatalog().catch((error) => myCapMessage(error.message));
});
document.getElementById("close-my-capabilities").addEventListener("click", closeMyCapabilitiesWorkspace);
for (const button of document.querySelectorAll("[data-my-tab]")) {
  button.addEventListener("click", () => { myCapMessage(""); setMyTab(button.dataset.myTab); });
}
document.getElementById("my-cap-new").addEventListener("click", () => document.getElementById("my-cap-form").reset());
document.getElementById("my-assign-agent").addEventListener("change", () => {
  refreshMyAssignments().catch((error) => myCapMessage(error.message));
});
document.getElementById("my-cap-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const capabilityId = document.getElementById("my-cap-id").value.trim();
  try {
    await api(`/api/my/capabilities/${encodeURIComponent(capabilityId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: activeMyTab,
        name: document.getElementById("my-cap-name").value.trim(),
        content: document.getElementById("my-cap-content").value,
        endpoint: document.getElementById("my-cap-endpoint").value.trim(),
        enabled: document.getElementById("my-cap-enabled").checked,
      }),
    });
    await refreshMyCatalog();
    await refreshAgentCapabilities();
    const saved = myCapabilityCatalog.find((item) => item.capability_id === capabilityId);
    myCapMessage(saved?.kind === "mcp" && !saved.approved
      ? "MCP 已保存，等待管理员审核地址；审核后还需绑定 Agent。"
      : "能力已保存；请在“绑定 Agent”中选择使用范围。");
  } catch (error) { myCapMessage(error.message); }
});
document.getElementById("my-assign-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const agentId = document.getElementById("my-assign-agent").value;
  const capabilityId = document.getElementById("my-assign-capability").value;
  try {
    await api(`/api/my/agents/${encodeURIComponent(agentId)}/capabilities/${encodeURIComponent(capabilityId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assigned: document.getElementById("my-assign-enabled").checked }),
    });
    await refreshMyAssignments();
    if (agentSelect.value === agentId) await refreshAgentCapabilities();
    myCapMessage("绑定已保存，下一条消息将按最新能力运行。");
  } catch (error) { myCapMessage(error.message); }
});
document.getElementById("api-key-confirm").addEventListener("click", () => apiKeyDialog.close());
apiKeyDialog.addEventListener("close", () => {
  if (window.matchMedia("(max-width:700px)").matches) setMobilePanel("settings");
  apiKeyInput.scrollIntoView({ behavior: "smooth", block: "center" });
  apiKeyInput.focus();
});
document.getElementById("reset-password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const userId = document.getElementById("reset-user-id").value.trim();
  const password = document.getElementById("reset-password").value;
  try {
    await api(`/api/admin/users/${encodeURIComponent(userId)}/password`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    document.getElementById("reset-password").value = "";
    adminMessage(`${userId} 的密码已重置，原登录已失效`);
  } catch (error) {
    adminMessage(error.message);
  }
});

document.getElementById("new-chat").addEventListener("click", () => {
  startNewChat();
});
document.getElementById("logout").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); }
  finally {
    apiKeyInput.value = "";
    if (currentUserId) sessionStorage.removeItem(chatKey());
    if (currentUserId) sessionStorage.removeItem(activeChatKey());
    sessionStorage.removeItem("agent_session");
    window.location.replace("/");
  }
});
textarea.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    document.getElementById("chat-form").requestSubmit();
  }
});
document.getElementById("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = textarea.value.trim();
  if (!prompt || send.disabled) return;
  const apiKey = apiKeyInput.value.trim();
  const provider = providerInput.value;
  const model = modelInput.value.trim();
  if (!apiKey && (currentRole === "user" || provider !== "deepseek-official")) {
    status.textContent = "请填写所选模型厂家的 API Key";
    document.getElementById("api-key-provider-name").textContent = providerInput.selectedOptions[0].textContent;
    apiKeyDialog.showModal();
    return;
  }
  if (!model && provider !== "deepseek-official") {
    status.textContent = "请填写所选厂家的模型 ID";
    modelInput.focus();
    return;
  }
  setMobilePanel();
  entries.push({ role: "你", content: prompt, kind: "user" });
  addMessage("你", prompt, "user");
  saveChat();
  textarea.value = "";
  send.disabled = true;
  const startedAt = performance.now();
  const updateElapsed = () => {
    status.textContent = `Agent 正在思考… ${formatDuration(performance.now() - startedAt)}`;
  };
  updateElapsed();
  const timer = window.setInterval(updateElapsed, 100);
  try {
    const response = await api("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: prompt, session_id: sessionId, api_key: apiKey || undefined,
        provider, model: model || undefined, agent_id: agentSelect.value,
        engine_id: engineSelect.value,
      }),
    });
    const durationMs = performance.now() - startedAt;
    sessionId = response.session_id;
    const runTrace = {
      available_tools: response.available_tools?.length ? response.available_tools : knownAvailableTools,
      tool_calls: response.tool_calls,
    };
    entries.push({ role: "Agent", content: response.answer, kind: "agent", durationMs, runTrace });
    addMessage("Agent", response.answer, "agent", durationMs);
    renderRunTrace(runTrace);
    saveChat();
    status.textContent = `完成 · ${formatDuration(durationMs)}`;
  } catch (error) {
    const durationMs = performance.now() - startedAt;
    entries.push({ role: "错误", content: error.message, kind: "error", durationMs });
    addMessage("错误", error.message, "error", durationMs);
    saveChat();
    status.textContent = error.status === 409
      ? `请点击“新会话”后重新发送 · ${formatDuration(durationMs)}`
      : `请求失败，可重试 · ${formatDuration(durationMs)}`;
  } finally {
    window.clearInterval(timer);
    send.disabled = false;
    textarea.focus();
  }
});

if (sessionToken) {
  let loginBootstrap = null;
  try { loginBootstrap = JSON.parse(sessionStorage.getItem("agent_bootstrap") || "null"); }
  catch (_) { /* Fall back to the server after a damaged browser cache. */ }
  const cachedToken = sessionStorage.getItem("agent_bootstrap_token");
  sessionStorage.removeItem("agent_bootstrap");
  sessionStorage.removeItem("agent_bootstrap_token");
  const entry = cachedToken === sessionToken && loginBootstrap?.user && Array.isArray(loginBootstrap.models)
    && Array.isArray(loginBootstrap.agents)
    ? Promise.resolve(loginBootstrap) : api("/api/bootstrap");
  entry.then(async (bootstrap) => {
    const user = bootstrap.user;
    currentUserId = user.user_id;
    currentRole = user.role;
    document.getElementById("user-name").textContent = user.user_id;
    document.getElementById("user-role").textContent = user.role === "admin" ? "管理员" : "普通用户";
    document.getElementById("avatar").textContent = user.user_id[0].toUpperCase();
    document.getElementById("admin-trigger").hidden = user.role !== "admin";
    document.getElementById("engine-management-link").hidden = user.role !== "admin";
    document.getElementById("api-key-panel").hidden = false;
    app.hidden = false;
    await loadCatalog(bootstrap);
    if (window.matchMedia("(min-width: 1200px)").matches) setMobilePanel("inspector");
    restoreChat();
  }).catch((error) => { status.textContent = error.message; });
}
