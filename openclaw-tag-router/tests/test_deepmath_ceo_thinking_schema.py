import unittest

from openclaw_app.services.deepmath_ceo_thinking_schema import (
    APPROVALS,
    DECISION_STATES,
    DECISIONS,
    EXECUTION_STATES,
    INBOX,
    PROPOSAL_STATES,
    feishu_field_payload,
    schema_manifest,
    validate_schema,
)


class DeepMathCeoThinkingSchemaTest(unittest.TestCase):
    def test_canonical_schema_is_valid_and_has_exactly_three_tables(self):
        validate_schema()
        manifest = schema_manifest()
        self.assertEqual(manifest["version"], 2)
        self.assertEqual(manifest["base_name"], "DeepMath CEO Thinking")
        self.assertEqual([table["name"] for table in manifest["tables"]], ["思考收件箱", "决策池", "审批记录"])

    def test_schema_does_not_create_a_formal_task_source(self):
        table_names = {table["name"] for table in schema_manifest()["tables"]}
        self.assertNotIn("任务池", table_names)
        self.assertNotIn("正式任务表", table_names)

    def test_select_options_are_human_facing_names(self):
        for table in schema_manifest()["tables"]:
            for field in table["fields"]:
                for option in field.get("options", []):
                    self.assertFalse(option.startswith("opt"))

    def test_approval_schema_has_three_independent_state_groups(self):
        fields = {field.name: field for field in APPROVALS.fields}
        self.assertNotIn("审批状态", fields)
        self.assertEqual(fields["提案状态"].options, PROPOSAL_STATES)
        self.assertEqual(fields["审批决定"].options, DECISION_STATES)
        self.assertEqual(fields["执行状态"].options, EXECUTION_STATES)
        self.assertEqual(
            {
                "提案ID", "提案版本", "提案项序号", "参数指纹", "提案过期时间",
                "执行键", "执行尝试", "上游请求ID", "最后回读时间", "执行结果",
            } <= fields.keys(),
            True,
        )

    def test_feishu_payload_uses_names_and_live_link_targets(self):
        table_ids = {"思考收件箱": "tblInbox", "决策池": "tblDecisions", "审批记录": "tblApprovals"}
        source = next(field for field in INBOX.fields if field.name == "来源")
        source_payload = feishu_field_payload(source, table_ids)
        self.assertEqual(
            [item["name"] for item in source_payload["property"]["options"]],
            ["私聊", "群聊", "语音", "截图", "文件", "链接"],
        )
        decision_link = next(field for field in DECISIONS.fields if field.name == "关联思考")
        self.assertEqual(feishu_field_payload(decision_link, table_ids)["type"], 18)
        self.assertEqual(
            feishu_field_payload(decision_link, table_ids)["property"],
            {"table_id": "tblInbox", "multiple": False},
        )
        approval_link = next(field for field in APPROVALS.fields if field.name == "关联决策")
        self.assertEqual(
            feishu_field_payload(approval_link, table_ids)["property"]["table_id"],
            "tblDecisions",
        )

    def test_link_payload_rejects_missing_live_target(self):
        link = next(field for field in DECISIONS.fields if field.name == "关联思考")
        with self.assertRaises(ValueError):
            feishu_field_payload(link, {})


if __name__ == "__main__":
    unittest.main()
