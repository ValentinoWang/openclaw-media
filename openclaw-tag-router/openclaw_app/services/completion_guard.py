from __future__ import annotations

from typing import Any

from .content_flow_client import ContentFlowClient


class CompletionGuard:
    """Global completion guard for external async pipelines.

    Handlers should pass external pipeline results through this service before
    writing records or deciding pending_manual status.
    """

    def __init__(self, content_flow_client: ContentFlowClient):
        self.content_flow_client = content_flow_client

    def complete_external_result(
        self,
        *,
        kind: str,
        body: str,
        result: dict[str, Any],
        wait: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"status": "pending_manual", "reason": f"{kind} 返回非 JSON object"}
        if kind in {"content_flow_analysis", "自媒体知识"}:
            return self.complete_content_flow_analysis(body=body, result=result, wait=wait)
        return result

    def complete_content_flow_analysis(
        self,
        *,
        body: str,
        result: dict[str, Any],
        wait: bool = False,
    ) -> dict[str, Any]:
        return self.content_flow_client.complete_analysis_payload(body, result, wait=wait)
