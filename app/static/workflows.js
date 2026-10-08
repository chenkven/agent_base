const token = sessionStorage.getItem("agent_session");
if (!token) window.location.replace("/");

const $ = (id) => document.getElementById(id);
let workflows = [];
let engines = [];
let agents = [];
let models = [];
let selectedId = null;
const capabilityCache = new Map();

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "X-Session-Token": token, ...(options.headers || {}) },
  });
  const data = await response.json();
  if (response.status === 401) { window.location.replace("/"); throw new Error("请重新登录"); }
  if (!response.ok) throw new Error(data.detail || `请求失败 (${response.status})`);
  return data;
}

function option(value, label) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  return item;
}

function setStatus(id, message) { $(id).textContent = message; }

function fillEngineChoices() {
  const current = $("workflow-engine").value;
  $("workflow-engine").replaceChildren();
  for (const engine of engines.filter((item) => item.enabled && item.available)) {
    $("workflow-engine").append(option(engine.id, engine.name));
  }
  if ([...$("workflow-engine").options].some((item) => item.value === current)) {
    $("workflow-engine").value = current;
  }
  for (const card of $("steps").children) refreshPluginTools(card);
}

function fillModels() {
  const provider = $("run-provider").value;
  $("run-model").replaceChildren();
  for (const item of models.filter((item) => item.provider === provider && item.enabled)) {
    $("run-model").append(option(item.model_id, item.model_id));
  }
}

async function mcpCapabilities(agentId) {
  if (!capabilityCache.has(agentId)) {
    const data = await api(`/api/agents/${encodeURIComponent(agentId)}/capabilities`);
    capabilityCache.set(agentId, data.capabilities.filter((item) => item.kind === "mcp"));
  }
  return capabilityCache.get(agentId);
}

async function refreshMcpChoices(card, selected = "") {
  const target = card.querySelector(".step-mcp");
  target.replaceChildren();
  try {
    for (const item of await mcpCapabilities(card.querySelector(".step-agent").value)) {
      target.append(option(item.capability_id, `${item.name} (${item.scope})`));
    }
    if (selected) target.value = selected;
  } catch (error) { setStatus("editor-status", error.message); }
}

function refreshPluginTools(card, selected = "") {
  const target = card.querySelector(".step-plugin");
  const engine = engines.find((item) => item.id === $("workflow-engine").value);
  target.replaceChildren();
  for (const tool of engine?.plugin_tools || []) target.append(option(tool, tool));
  if (selected) target.value = selected;
}

function showStepFields(card) {
  const kind = card.querySelector(".step-kind").value;
  card.querySelector(".agent-fields").hidden = kind !== "agent";
  card.querySelector(".mcp-fields").hidden = kind !== "mcp_tool";
  card.querySelector(".plugin-fields").hidden = kind !== "plugin_tool";
  syncRunRequirements();
}

function syncRunRequirements() {
  const steps = [...$("steps").children];
  const needsModel = steps.some((card) => card.querySelector(".step-kind").value !== "mcp_tool");
  $("run-model-fields").hidden = !needsModel;
  $("mcp-only-note").hidden = needsModel || steps.length === 0;
}

function addStep(data = {}) {
  if ($("steps").children.length >= 8) { setStatus("editor-status", "最多 8 个步骤"); return; }
  const card = document.createElement("div");
  card.className = "step";
  card.innerHTML = `
    <div class="step-header"><strong class="step-number"></strong><button class="danger step-remove" type="button">删除步骤</button></div>
    <div class="step-fields">
      <label>步骤名称<input class="step-name" maxlength="80" placeholder="例如：检索资料"></label>
      <label>类型<select class="step-kind"><option value="agent">Agent</option><option value="mcp_tool">MCP 工具</option><option value="plugin_tool">DSH 插件工具</option></select></label>
      <label>使用 Agent<select class="step-agent"></select></label>
      <div class="wide agent-fields"><label>本步指令<textarea class="step-instruction" rows="3" maxlength="4000" placeholder="可使用 {{input}}、{{previous}}、{{step1}}"></textarea></label></div>
      <div class="wide mcp-fields"><div class="step-fields"><label>已授权 MCP<select class="step-mcp"></select></label><label>工具名<input class="step-mcp-tool" placeholder="例如 search" maxlength="128"></label></div><label>工具参数 JSON<textarea class="step-arguments" rows="3" placeholder='{"query":"{{previous}}"}'></textarea></label></div>
      <div class="wide plugin-fields"><label>已登记插件工具<select class="step-plugin"></select></label><label>调用要求<textarea class="step-plugin-instruction" rows="2" maxlength="4000" placeholder="描述要交给该工具完成的任务"></textarea></label><p class="hint">运行时会检查 DSH 轨迹中该工具是否成功调用。</p></div>
    </div>`;
  const agent = card.querySelector(".step-agent");
  for (const item of agents) agent.append(option(item.agent_id, item.name));
  card.querySelector(".step-kind").value = data.kind || "agent";
  card.querySelector(".step-name").value = data.name || "";
  agent.value = data.agent_id || agents[0]?.agent_id || "default";
  card.querySelector(".step-instruction").value = data.kind === "agent" ? data.instruction || "" : "";
  card.querySelector(".step-plugin-instruction").value = data.kind === "plugin_tool" ? data.instruction || "" : "";
  card.querySelector(".step-mcp-tool").value = data.kind === "mcp_tool" ? data.tool_name || "" : "";
  card.querySelector(".step-arguments").value = JSON.stringify(data.arguments || {}, null, 2);
  card.querySelector(".step-kind").addEventListener("change", () => {
    showStepFields(card);
    refreshMcpChoices(card);
    refreshPluginTools(card);
  });
  agent.addEventListener("change", () => refreshMcpChoices(card));
  card.querySelector(".step-remove").addEventListener("click", () => {
    card.remove(); renumber(); syncRunRequirements();
  });
  $("steps").append(card);
  showStepFields(card);
  syncRunRequirements();
  renumber();
  refreshMcpChoices(card, data.capability_id || "");
  refreshPluginTools(card, data.kind === "plugin_tool" ? data.tool_name : "");
}

function renumber() {
  [...$("steps").children].forEach((card, index) => {
    card.querySelector(".step-number").textContent = `步骤 ${index + 1}`;
  });
}

function collectSteps() {
  return [...$("steps").children].map((card, index) => {
    const kind = card.querySelector(".step-kind").value;
    const base = {
      kind, name: card.querySelector(".step-name").value.trim(),
      agent_id: card.querySelector(".step-agent").value,
    };
    if (kind === "agent") base.instruction = card.querySelector(".step-instruction").value.trim();
    if (kind === "mcp_tool") {
      base.capability_id = card.querySelector(".step-mcp").value;
      base.tool_name = card.querySelector(".step-mcp-tool").value.trim();
      try { base.arguments = JSON.parse(card.querySelector(".step-arguments").value || "{}"); }
      catch (_) { throw new Error(`步骤 ${index + 1} 的工具参数不是有效 JSON`); }
    }
    if (kind === "plugin_tool") {
      base.tool_name = card.querySelector(".step-plugin").value;
      base.instruction = card.querySelector(".step-plugin-instruction").value.trim();
    }
    return base;
  });
}

function renderList() {
  const list = $("workflow-list");
  list.replaceChildren();
  for (const workflow of workflows) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `side-item${workflow.workflow_id === selectedId ? " active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = workflow.name;
    const detail = document.createElement("small");
    detail.textContent = `${workflow.steps.length} 步 · ${workflow.engine_id}`;
    button.append(title, detail);
    button.addEventListener("click", () => selectWorkflow(workflow.workflow_id));
    list.append(button);
  }
  if (!workflows.length) list.textContent = "还没有工作流。";
}

function selectWorkflow(id) {
  const workflow = workflows.find((item) => item.workflow_id === id);
  if (!workflow) return;
  selectedId = id;
  $("workflow-name").value = workflow.name;
  $("workflow-description").value = workflow.description;
  $("workflow-engine").value = workflow.engine_id;
  $("steps").replaceChildren();
  for (const step of workflow.steps) addStep(step);
  $("delete-workflow").hidden = false;
  $("run-output").hidden = true;
  $("run-steps").replaceChildren();
  setStatus("editor-status", "已打开工作流");
  renderList();
  refreshRunHistory();
}

function resetEditor() {
  selectedId = null;
  $("workflow-name").value = "";
  $("workflow-description").value = "";
  $("steps").replaceChildren();
  addStep();
  $("delete-workflow").hidden = true;
  $("run-output").hidden = true;
  $("run-steps").replaceChildren();
  $("run-history").replaceChildren();
  setStatus("editor-status", "新工作流尚未保存");
  renderList();
}

function showRun(run) {
  const list = $("run-steps");
  list.replaceChildren();
  for (const step of run.steps) {
    const box = document.createElement("div");
    box.className = `run-step ${step.status}`;
    const heading = document.createElement("strong");
    heading.textContent = `${step.index + 1}. ${step.name} · ${step.status} · ${step.duration_ms ?? 0} ms`;
    const output = document.createElement("p");
    output.className = "muted";
    output.textContent = step.error || step.output || "等待结果";
    box.append(heading, output);
    list.append(box);
  }
  $("run-output").hidden = false;
  $("run-output").textContent = run.error || run.output || "没有输出";
  setStatus("run-status", `运行 ${run.status} · ID ${run.run_id}`);
}

async function refreshRunHistory() {
  const workflowId = selectedId;
  if (!workflowId) return;
  try {
    const data = await api(`/api/workflows/${workflowId}/runs`);
    if (workflowId !== selectedId) return;
    const list = $("run-history");
    list.replaceChildren();
    for (const run of data.runs) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "side-item";
      button.textContent = `${new Date(run.started_at).toLocaleString()} · ${run.status} · ${run.engine_id}`;
      button.addEventListener("click", async () => {
        try { showRun(await api(`/api/workflow-runs/${run.run_id}`)); }
        catch (error) { setStatus("run-status", error.message); }
      });
      list.append(button);
    }
    if (!data.runs.length) list.textContent = "尚无运行记录";
  } catch (error) { setStatus("run-status", error.message); }
}

$("new-workflow").addEventListener("click", resetEditor);
$("add-step").addEventListener("click", () => addStep());
$("workflow-engine").addEventListener("change", () => {
  for (const card of $("steps").children) refreshPluginTools(card);
});
$("run-provider").addEventListener("change", fillModels);
$("save-workflow").addEventListener("click", async () => {
  const button = $("save-workflow");
  button.disabled = true;
  try {
    const body = {
      name: $("workflow-name").value.trim(),
      description: $("workflow-description").value.trim(),
      engine_id: $("workflow-engine").value, steps: collectSteps(),
    };
    const response = await api(selectedId ? `/api/workflows/${selectedId}` : "/api/workflows", {
      method: selectedId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    selectedId = response.workflow_id;
    workflows = (await api("/api/workflows")).workflows;
    selectWorkflow(selectedId);
    setStatus("editor-status", "工作流已保存");
  } catch (error) { setStatus("editor-status", error.message); }
  finally { button.disabled = false; }
});
$("delete-workflow").addEventListener("click", async () => {
  if (!selectedId || !window.confirm("删除这个工作流及其运行记录？")) return;
  try {
    await api(`/api/workflows/${selectedId}`, { method: "DELETE" });
    workflows = (await api("/api/workflows")).workflows;
    resetEditor();
  } catch (error) { setStatus("editor-status", error.message); }
});
$("run-workflow").addEventListener("click", async () => {
  if (!selectedId) { setStatus("run-status", "请先保存工作流"); return; }
  const button = $("run-workflow");
  button.disabled = true;
  setStatus("run-status", "正在执行，请等待各步骤完成…");
  try {
    const run = await api(`/api/workflows/${selectedId}/runs`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input: $("run-input").value.trim(), provider: $("run-provider").value,
        model: $("run-model").value, api_key: $("run-key").value.trim() || undefined,
      }),
    });
    showRun(run);
    refreshRunHistory();
  } catch (error) { setStatus("run-status", error.message); }
  finally { button.disabled = false; }
});

async function initialize() {
  const [bootstrap, saved] = await Promise.all([api("/api/bootstrap"), api("/api/workflows")]);
  engines = bootstrap.engines;
  agents = bootstrap.agents.filter((item) => item.enabled && item.granted);
  models = bootstrap.models.filter((item) => item.enabled && (bootstrap.user.role === "admin" || item.user_enabled));
  workflows = saved.workflows;
  fillEngineChoices();
  $("run-provider").replaceChildren();
  for (const provider of [...new Set(models.map((item) => item.provider))]) {
    $("run-provider").append(option(provider, provider));
  }
  fillModels();
  if (workflows.length) selectWorkflow(workflows[0].workflow_id);
  else resetEditor();
}
initialize().catch((error) => setStatus("editor-status", error.message));
