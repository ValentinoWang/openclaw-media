from __future__ import annotations

__all__ = [
    "build_evidence_store",
    "evidence_store_prompt",
    "prepare_asset_manifest",
    "run_evidence_dag",
    "run_engagement_comments_interaction_pipeline",
    "run_keyframe_observation_facts_pipeline",
    "run_keyframe_observation_pipeline",
    "run_modality_pipelines",
    "run_ocr_pipeline",
    "run_source_copy_pipeline",
    "run_speech_audio_pipeline",
    "run_temporal_pacing_pipeline",
    "run_visual_asset_pipeline",
]


def __getattr__(name: str):
    if name in __all__:
        from . import modality_dag

        return getattr(modality_dag, name)
    raise AttributeError(name)
