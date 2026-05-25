from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any

SELFMEDIA_ROOT = Path(__file__).resolve().parents[3]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.llm_settings import load_main_llm_settings, load_qwen_settings


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ViralDeconstructConfig:
    model: str
    base_url: str
    api_key: str
    timeout: float
    feishu_bitable_url: str
    feishu_doc_folder_token: str
    feishu_wiki_parent_node_token: str
    feishu_deconstruct_parent_node_token: str
    feishu_recreate_parent_node_token: str
    part1_path: Path
    video_understanding_provider: str = "gpt_frames"
    qwen_model: str = "qwen3.5-omni-plus"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_api_key: str = ""
    qwen_fps: float = 2.0
    llm_api_type: str = "openai_chat_completions"
    thinking: str = ""


def load_config() -> ViralDeconstructConfig:
    main_llm = load_main_llm_settings()
    qwen = load_qwen_settings()
    return ViralDeconstructConfig(
        model=main_llm.model,
        base_url=main_llm.base_url,
        api_key=main_llm.api_key,
        timeout=main_llm.timeout,
        feishu_bitable_url=os.getenv("MEDIA_OS_VIRAL_URL") or os.getenv("FEISHU_BITABLE_URL", ""),
        feishu_doc_folder_token=os.getenv("FEISHU_DOC_FOLDER_TOKEN", ""),
        feishu_wiki_parent_node_token=os.getenv("FEISHU_WIKI_PARENT_NODE_TOKEN", "QA0BwF5Yji0EvfkmOiOcBuMQnze"),
        feishu_deconstruct_parent_node_token=os.getenv("SELFMEDIA_DECONSTRUCT_PARENT_NODE_TOKEN", "BqzWw9xZeiBu7Kk99YqcxEJ4nuf"),
        feishu_recreate_parent_node_token=os.getenv("SELFMEDIA_RECREATE_PARENT_NODE_TOKEN", "Tm69wEqFpi76d9k53KEcqK4Rnkh"),
        part1_path=Path(os.getenv("SELFMEDIA_CONTENT_INGEST_PATH", "/home/ubuntu/selfmedia-tools/01-ingest-content-flow")),
        video_understanding_provider=os.getenv("VIDEO_UNDERSTANDING_PROVIDER", "hybrid").strip().lower(),
        qwen_model=qwen.model,
        qwen_base_url=qwen.base_url,
        qwen_api_key=qwen.api_key,
        qwen_fps=qwen.fps,
        llm_api_type=main_llm.api_type,
        thinking=main_llm.thinking,
    )
