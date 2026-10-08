"""读取本地配置，并为 Harness 指定独立的工作目录和数据目录。"""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AgentConfig:
    model: str
    profile: str
    max_tokens: int | None
    workspace: Path
    harness_home: Path
    patches: tuple[str, ...]
    has_api_key: bool
    dsh_bin: str | None = None

    @classmethod
    def load(cls) -> "AgentConfig":
        load_dotenv(PROJECT_ROOT / ".env", override=False)

        # 官方接口使用 SDK 默认地址；空字符串不能作为自定义地址传给运行时。
        if not os.getenv("DEEPSEEK_BASE_URL", "").strip():
            os.environ.pop("DEEPSEEK_BASE_URL", None)

        raw_max_tokens = os.getenv("AGENT_MAX_TOKENS", "").strip()
        max_tokens = int(raw_max_tokens) if raw_max_tokens else None
        if max_tokens is not None and max_tokens <= 0:
            raise ValueError("AGENT_MAX_TOKENS 必须是正整数")

        patch_dir = PROJECT_ROOT / "config"
        patches = tuple(str(path) for path in sorted(patch_dir.glob("*.patch.yml")))

        return cls(
            model=os.getenv("AGENT_MODEL", "deepseek-v4-flash").strip(),
            profile=os.getenv("AGENT_PROFILE", "sdk").strip(),
            max_tokens=max_tokens,
            workspace=(PROJECT_ROOT / "workspace").resolve(),
            harness_home=(PROJECT_ROOT / ".harness").resolve(),
            patches=patches,
            has_api_key=bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        )
