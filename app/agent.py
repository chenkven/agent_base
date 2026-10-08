"""对官方 DeepSeek Harness Python SDK 做一层轻量封装。"""

from deepseek_harness import DeepSeekHarness

from app.config import AgentConfig


def create_harness(
    config: AgentConfig, *, api_key: str | None = None,
    provider: str = "deepseek-official", model: str | None = None,
    isolate_other_keys: bool = False,
    request_timeout_seconds: float | None = None,
) -> DeepSeekHarness:
    """集中创建 Harness，今后更换模型或叠加插件配置只改这里。"""
    config.workspace.mkdir(parents=True, exist_ok=True)
    config.harness_home.mkdir(parents=True, exist_ok=True)
    # The web profile declares multiple routes. Do not let pi-ai discover
    # unrelated keys inherited from the server process.
    provider_env = {
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "MOONSHOT_API_KEY": "",
        "ZAI_API_KEY": "",
        "ZHIPU_API_KEY": "",
        "DASHSCOPE_API_KEY": "",
        "QWEN_TOKEN_PLAN_API_KEY": "",
        "QWEN_TOKEN_PLAN_CN_API_KEY": "",
    } if isolate_other_keys or (provider != "deepseek-official" and api_key) else {}
    if provider != "deepseek-official":
        provider_env.update({"DEEPSEEK_API_KEY": "", "USER_MODEL_API_KEY": api_key or ""})

    timeout = ({"request_timeout_seconds": request_timeout_seconds}
               if request_timeout_seconds is not None else {})
    return DeepSeekHarness(
        provider=provider,
        model=model or config.model,
        max_tokens=config.max_tokens,
        cwd=str(config.workspace),
        dsh_home=str(config.harness_home),
        dsh_bin=config.dsh_bin,
        profile=config.profile,
        patches=config.patches,
        api_key=api_key if provider == "deepseek-official" else None,
        env=provider_env,
        **timeout,
    )
