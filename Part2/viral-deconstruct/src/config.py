from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Part2Config:
    model: str
    base_url: str
    api_key: str
    timeout: float
    feishu_bitable_url: str
    feishu_doc_folder_token: str
    feishu_wiki_parent_node_token: str
    part1_path: Path
    video_understanding_provider: str = "gpt_frames"
    qwen_model: str = "qwen3.5-omni-plus"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: str = ""
    qwen_fps: float = 2.0
    llm_api_type: str = "openai_chat_completions"


def _openclaw_config() -> dict[str, Any]:
    path = Path(os.getenv("OPENCLAW_CONFIG", "/home/ubuntu/.openclaw/openclaw.json")).expanduser()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _codex_auth() -> dict[str, Any]:
    path = Path(os.getenv("CODEX_AUTH_PATH", "/home/ubuntu/.codex/auth.json")).expanduser()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _codex_access_token() -> str:
    auth = _codex_auth()
    token = ((auth.get("tokens") or {}).get("access_token") or "").strip()
    return token


def _secret_from_openclaw(cfg: dict[str, Any], provider: str = "openai") -> str:
    # Supports common OpenClaw secret shapes without introducing a second config file.
    secrets = cfg.get("secrets") or {}
    candidates = [
        secrets.get("OPENAI_API_KEY"),
        secrets.get("openai", {}).get("apiKey") if isinstance(secrets.get("openai"), dict) else None,
        secrets.get("providers", {}).get(provider, {}).get("apiKey") if isinstance(secrets.get("providers"), dict) else None,
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip() and not value.startswith("${"):
            return value.strip()
    return ""


def _primary_model_from_openclaw(cfg: dict[str, Any]) -> str:
    primary = (((cfg.get("agents") or {}).get("defaults") or {}).get("model") or {}).get("primary")
    if isinstance(primary, str) and "/" in primary:
        return primary.split("/", 1)[1].strip()
    if isinstance(primary, str):
        return primary.strip()
    return ""


def load_config() -> Part2Config:
    cfg = _openclaw_config()
    provider_cfg = (((cfg.get("models") or {}).get("providers") or {}).get("openai") or {})
    codex_provider_cfg = (((cfg.get("models") or {}).get("providers") or {}).get("openai-codex") or {})
    qwen_provider_cfg = (((cfg.get("models") or {}).get("providers") or {}).get("qwen") or {})
    explicit_main_key = os.getenv("SELFMEDIA_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or _secret_from_openclaw(cfg)
    codex_token = _codex_access_token()
    use_codex = not explicit_main_key and bool(codex_token) and bool(codex_provider_cfg)
    return Part2Config(
        model=os.getenv("SELFMEDIA_LLM_MODEL") or os.getenv("OPENAI_MODEL") or (_primary_model_from_openclaw(cfg) if use_codex else "") or "gpt-4.1-mini",
        base_url=(os.getenv("SELFMEDIA_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or (codex_provider_cfg.get("baseUrl") if use_codex else "") or provider_cfg.get("baseUrl") or "https://api.openai.com/v1").rstrip("/"),
        api_key=explicit_main_key or (codex_token if use_codex else ""),
        timeout=float(os.getenv("SELFMEDIA_LLM_TIMEOUT", "120")),
        feishu_bitable_url=os.getenv("FEISHU_BITABLE_URL", ""),
        feishu_doc_folder_token=os.getenv("FEISHU_DOC_FOLDER_TOKEN", ""),
        feishu_wiki_parent_node_token=os.getenv("FEISHU_WIKI_PARENT_NODE_TOKEN", "QA0BwF5Yji0EvfkmOiOcBuMQnze"),
        part1_path=Path(os.getenv("SELFMEDIA_PART1_PATH", "/home/ubuntu/selfmedia-tools/Part1/content-flow")),
        video_understanding_provider=os.getenv("VIDEO_UNDERSTANDING_PROVIDER", "gpt_frames").strip().lower(),
        qwen_model=os.getenv("QWEN_MODEL") or qwen_provider_cfg.get("model") or "qwen3.5-omni-plus",
        qwen_base_url=(os.getenv("QWEN_BASE_URL") or qwen_provider_cfg.get("baseUrl") or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"),
        qwen_api_key=os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or _secret_from_openclaw(cfg, "qwen"),
        qwen_fps=float(os.getenv("QWEN_FPS", "2.0")),
        llm_api_type=os.getenv("SELFMEDIA_LLM_API_TYPE") or ("openai_codex_responses" if use_codex else "openai_chat_completions"),
    )
