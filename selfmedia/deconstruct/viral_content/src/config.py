from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any

SELFMEDIA_ROOT = Path(__file__).resolve().parents[4]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.llm_settings import load_profile_llm_settings


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ViralDeconstructConfig:
    model: str
    base_url: str
    api_key: str
    timeout: float
    source_assets_url: str
    material_deconstructions_url: str
    feishu_doc_folder_token: str
    feishu_wiki_parent_node_token: str
    feishu_deconstruct_parent_node_token: str
    feishu_recreate_parent_node_token: str
    part1_path: Path
    llm_api_type: str = "openai_chat_completions"
    thinking: str = ""
    bin: str = ""
    agent: str = ""
    cwd: str = ""
    codex_home: str = ""


def load_config(profile_name: str = "media_analysis") -> ViralDeconstructConfig:
    llm_settings = load_profile_llm_settings(profile_name)
    return ViralDeconstructConfig(
        model=llm_settings.model,
        base_url=llm_settings.base_url,
        api_key=llm_settings.api_key,
        timeout=llm_settings.timeout,
        source_assets_url=os.getenv("MEDIA_OS_SOURCE_ASSETS_URL", ""),
        material_deconstructions_url=os.getenv("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL", ""),
        feishu_doc_folder_token=os.getenv("FEISHU_DOC_FOLDER_TOKEN", ""),
        feishu_wiki_parent_node_token=os.getenv("FEISHU_WIKI_PARENT_NODE_TOKEN", "QA0BwF5Yji0EvfkmOiOcBuMQnze"),
        feishu_deconstruct_parent_node_token=os.getenv("SELFMEDIA_DECONSTRUCT_PARENT_NODE_TOKEN", "BqzWw9xZeiBu7Kk99YqcxEJ4nuf"),
        feishu_recreate_parent_node_token=os.getenv("SELFMEDIA_RECREATE_PARENT_NODE_TOKEN", "Tm69wEqFpi76d9k53KEcqK4Rnkh"),
        part1_path=Path(
            os.getenv("SELFMEDIA_CONTENT_INGEST_PATH")
            or Path(__file__).resolve().parents[3] / "ingest" / "content_flow"
        ).expanduser(),
        llm_api_type=llm_settings.api_type,
        thinking=llm_settings.thinking,
        bin=llm_settings.bin,
        agent=llm_settings.agent,
        cwd=llm_settings.cwd,
        codex_home=llm_settings.codex_home,
    )
