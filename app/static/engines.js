const token = sessionStorage.getItem("agent_session");
if (!token) window.location.replace("/");
async function load() {
  const me = await fetch("/api/me", { headers: { "X-Session-Token": token } });
  if (!me.ok || (await me.json()).role !== "admin") { window.location.replace("/app"); return; }
  const response = await fetch("/api/engines", { headers: { "X-Session-Token": token } });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "引擎目录加载失败");
  const list = document.getElementById("engine-list");
  list.replaceChildren();
  for (const engine of data.engines) {
    const card = document.createElement("section");
    card.className = "engine-card";
    const title = document.createElement("h3");
    title.textContent = `${engine.name} · ${engine.version}`;
    const state = document.createElement("span");
    state.className = `pill${engine.enabled && engine.available ? "" : " off"}`;
    state.textContent = engine.enabled && engine.available ? "可选择" : "不可选择";
    const detail = document.createElement("p");
    detail.className = "muted";
    detail.textContent = `ID: ${engine.id} · Profile: ${engine.profile} · ${engine.status}`;
    const tools = document.createElement("p");
    tools.textContent = `已登记插件工具：${engine.plugin_tools.length ? engine.plugin_tools.join("、") : "暂无"}`;
    card.append(title, state, detail, tools);
    list.append(card);
  }
}
load().catch((error) => { document.getElementById("engine-status").textContent = error.message; });
