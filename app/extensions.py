"""Turn assigned capabilities into isolated DSH patches for one Agent run."""

from dataclasses import replace
from hashlib import sha256
import json

from app.config import AgentConfig
from app.permissions import Principal
from app.platform import capabilities_for_agent
from app.user_capabilities import effective_capabilities


def prepare_capabilities(
    config: AgentConfig, agent_id: str, principal: Principal | None = None,
) -> tuple[AgentConfig, str, str]:
    """Return an Agent-specific config, extra prompt text, and version hash.

    Only capabilities explicitly assigned to this Agent are materialized. The
    skill provider's default roots are disabled so another user's skills or
    host-local skills cannot appear in this web Harness.
    """
    capabilities = (effective_capabilities(principal, agent_id) if principal
                    else capabilities_for_agent(agent_id))
    serialized = json.dumps(capabilities, ensure_ascii=False, sort_keys=True)
    fingerprint = sha256(serialized.encode("utf-8")).hexdigest()
    prompts = [item["content"] for item in capabilities if item["kind"] == "prompt"]
    skills = [item for item in capabilities if item["kind"] == "skill"]
    mcps = [item for item in capabilities if item["kind"] == "mcp"]
    rows = []

    if skills:
        skill_root = config.workspace / ".dsh-skills"
        skill_root.mkdir(parents=True, exist_ok=True)
        assigned = {item["capability_id"] for item in skills}
        for old in skill_root.iterdir():
            if old.is_dir() and old.name not in assigned:
                stale = old / "SKILL.md"
                if stale.is_file():
                    stale.unlink()
        for item in skills:
            directory = skill_root / item["capability_id"]
            directory.mkdir(parents=True, exist_ok=True)
            description = json.dumps(item["name"], ensure_ascii=False)
            document = (
                f"---\nname: {item['capability_id']}\n"
                f"description: {description}\n---\n\n{item['content']}\n"
            )
            file = directory / "SKILL.md"
            if not file.exists() or file.read_text(encoding="utf-8") != document:
                file.write_text(document, encoding="utf-8")
        rows.extend([
            {"id": "web-skill-service", "name": "@deepseek-ai/dsh-skill"},
            {"id": "web-skill-filesystem", "name": "@deepseek-ai/dsh-skill-filesystem",
             "config": {"includeDefaultRoots": False,
                        "customSkillDirs": [skill_root.as_posix()], "watch": False}},
            {"id": "web-tool-skill", "name": "@deepseek-ai/dsh-tool-skill"},
        ])

    for item in mcps:
        rows.append({
            "id": f"web-mcp-{item['capability_id']}",
            "name": "@deepseek-ai/dsh-mcp-client",
            "config": {"serverName": item["capability_id"],
                       "transport": "streamable-http", "url": item["endpoint"],
                       "failOnStartupError": True},
        })

    if not rows:
        return config, "\n\n".join(prompts), fingerprint
    config.harness_home.mkdir(parents=True, exist_ok=True)
    patch = config.harness_home / f"{agent_id}.capabilities.patch.yml"
    patch_text = json.dumps([{"insert": rows}], ensure_ascii=False, indent=2)
    if not patch.exists() or patch.read_text(encoding="utf-8") != patch_text:
        patch.write_text(patch_text, encoding="utf-8")
    return replace(config, patches=(*config.patches, patch.as_posix())), "\n\n".join(prompts), fingerprint
