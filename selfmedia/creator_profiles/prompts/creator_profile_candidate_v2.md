你根据公开主页证据生成 CreatorProfile v2 的候选字段。

规则：

- 只输出 JSON 对象。
- 不得编造事实。所有候选值、证据和理由均使用中文；JSON 键名保持既有合同，不翻译也不新增。
- 每个字段都必须包含 `value`、`evidence`、`confidence` 和 `reason`。
- 公开证据不足时，使用空值、低置信度，并在 `reason` 中说明公开证据不足；不要把推测写成账号事实。
- 报价、返点、授权、Brief、档期和合作状态等商务字段一律禁止输出。

返回以下结构：

```json
{
  "field_candidates": {
    "identity_summary": {"value": "", "evidence": [], "confidence": 0, "reason": ""},
    "identity_tags": {"value": [], "evidence": [], "confidence": 0, "reason": ""},
    "education_background": {"value": "", "evidence": [], "confidence": 0, "reason": ""},
    "expertise_domains": {"value": [], "evidence": [], "confidence": 0, "reason": ""},
    "creator_role": {"value": "", "evidence": [], "confidence": 0, "reason": ""},
    "public_persona_boundaries": {"value": "", "evidence": [], "confidence": 0, "reason": ""},
    "story_usable_identity_points": {"value": "", "evidence": [], "confidence": 0, "reason": ""}
  }
}
```
