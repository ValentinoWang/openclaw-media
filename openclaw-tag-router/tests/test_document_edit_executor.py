from __future__ import annotations

from copy import deepcopy

from openclaw_app.services.document_edit_executor import DocumentEditExecutor


BODY = {
    "schemaVersion": "media.document.body.v1",
    "blocks": [
        {"id": "p1", "type": "paragraph", "content": [{"type": "text", "text": "old term"}]},
        {"id": "protected-1", "type": "paragraph", "protected": True, "content": [{"type": "text", "text": "old term"}]},
    ],
}


class Store:
    def __init__(self):
        self.claimed = True
        self.completed = []
        self.failed = []

    def claim_generating_revision(self, context, artifact_id, revision):
        if not self.claimed:
            return None
        self.claimed = False
        return {"bodyAuthority": self.authority, "baseRevision": 1, "documentId": "doc-1"}

    def complete_revision(self, context, artifact_id, revision, body, receipt):
        self.completed.append((artifact_id, revision, body, receipt))

    def fail_revision(self, context, artifact_id, revision, error_code, message):
        self.failed.append((artifact_id, revision, error_code, message))


class Documents:
    def __init__(self):
        self.writes = []

    def get_document_revision(self, context, artifact_id, revision):
        return {"data": {"revision": {"body": deepcopy(BODY)}}}

    def save_generated_revision(self, context, artifact_id, revision, body, receipt):
        self.writes.append((artifact_id, revision, body, receipt))


def _context():
    return type("Context", (), {"tenant_id": "tenant-1"})()


def _instruction():
    return {"intent_operations": [{"op": "replace_terms", "old_text": "old", "new_text": "new"}]}


def test_internal_revision_applies_exact_replace_and_reports_protected_skip():
    store, documents = Store(), Documents()
    store.authority = "internal"
    result = DocumentEditExecutor(store, documents).execute(_context(), "artifact-1", 2, _instruction())

    assert result["status"] == "ready"
    assert store.completed[0][2]["blocks"][0]["content"][0]["text"] == "new term"
    assert result["receipt"]["appliedCount"] == 1
    assert result["receipt"]["applied"] == [
        {"operation": "replace_text", "blockId": "p1"}
    ]
    assert result["receipt"]["protectedSkipped"] == []


def test_lark_revision_uses_lark_writer_and_protected_match_becomes_manual_action():
    store, documents = Store(), Documents()
    store.authority = "lark"
    result = DocumentEditExecutor(store, documents).execute(
        _context(), "artifact-1", 2,
        {"intent_operations": [{"op": "replace_terms", "old_text": "old", "new_text": "new"}]},
    )

    assert result["status"] == "ready"
    assert len(documents.writes) == 1
    assert result["receipt"]["manualActions"]


def test_failed_generation_is_stable_and_repeated_execution_does_not_write_twice():
    store, documents = Store(), Documents()
    store.authority = "internal"
    executor = DocumentEditExecutor(store, documents)
    first = executor.execute(_context(), "artifact-1", 2, None)
    second = executor.execute(_context(), "artifact-1", 2, None)

    assert first["status"] == second["status"] == "failed"
    assert first["errorCode"] == second["errorCode"] == "document_edit_generator_unavailable"
    assert len(store.failed) == 1
