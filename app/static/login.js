const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const result = document.getElementById("auth-result");
const loginTab = document.getElementById("tab-login");
const registerTab = document.getElementById("tab-register");

function hidePasswords() {
  for (const button of document.querySelectorAll("[data-password-toggle]")) {
    document.getElementById(button.dataset.passwordToggle).type = "password";
    button.textContent = "显示";
    button.setAttribute("aria-label", "显示密码");
    button.setAttribute("aria-pressed", "false");
  }
}

for (const button of document.querySelectorAll("[data-password-toggle]")) {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordToggle);
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    button.textContent = visible ? "隐藏" : "显示";
    button.setAttribute("aria-label", visible ? "隐藏密码" : "显示密码");
    button.setAttribute("aria-pressed", String(visible));
  });
}

function showResult(message, success = false) {
  result.textContent = message;
  result.classList.toggle("success", success);
}

function switchTab(register) {
  hidePasswords();
  loginForm.hidden = register;
  registerForm.hidden = !register;
  loginTab.setAttribute("aria-selected", String(!register));
  registerTab.setAttribute("aria-selected", String(register));
  document.getElementById("auth-title").textContent = register ? "创建普通用户账号" : "登录账号";
  showResult("");
  document.getElementById(register ? "register-username" : "login-username").focus();
}

loginTab.addEventListener("click", () => switchTab(false));
registerTab.addEventListener("click", () => switchTab(true));

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = loginForm.querySelector('button[type="submit"]');
  button.disabled = true;
  showResult("");
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("login-username").value.trim(),
        password: document.getElementById("login-password").value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `登录失败 (${response.status})`);
    sessionStorage.setItem("agent_session", data.session_token);
    if (data.bootstrap) {
      sessionStorage.setItem("agent_bootstrap", JSON.stringify(data.bootstrap));
      sessionStorage.setItem("agent_bootstrap_token", data.session_token);
    }
    document.getElementById("login-password").value = "";
    window.location.replace("/app");
  } catch (error) {
    showResult(error.message);
    button.disabled = false;
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("register-username").value.trim();
  const password = document.getElementById("register-password").value;
  const confirm = document.getElementById("register-confirm").value;
  if (password !== confirm) {
    showResult("两次输入的密码不一致");
    return;
  }
  const button = registerForm.querySelector('button[type="submit"]');
  button.disabled = true;
  showResult("");
  try {
    const response = await fetch("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `注册失败 (${response.status})`);
    document.getElementById("register-password").value = "";
    document.getElementById("register-confirm").value = "";
    hidePasswords();
    showResult(`账号 ${data.user_id} 已创建，等待管理员启用后即可登录。`, true);
  } catch (error) {
    showResult(error.message);
  } finally {
    button.disabled = false;
  }
});

const previous = sessionStorage.getItem("agent_session");
if (previous) {
  fetch("/api/me", { headers: { "X-Session-Token": previous } })
    .then((response) => {
      if (response.ok) window.location.replace("/app");
      else sessionStorage.removeItem("agent_session");
    })
    .catch(() => {});
}
