"""对官方 DeepSeek Harness Python SDK 做一层轻量封装。"""

from deepseek_harness import DeepSeekHarness

from app.config import AgentConfig


def create_harness(config: AgentConfig) -> DeepSeekHarness:
    """集中创建 Harness，今后更换模型或叠加插件配置只改这里。"""
    config.workspace.mkdir(parents=True, exist_ok=True)
    config.harness_home.mkdir(parents=True, exist_ok=True)

    return DeepSeekHarness(
        provider="deepseek-official",
        model=config.model,
        max_tokens=config.max_tokens,
        cwd=str(config.workspace),
        dsh_home=str(config.harness_home),
        profile=config.profile,
        patches=config.patches,
    )
