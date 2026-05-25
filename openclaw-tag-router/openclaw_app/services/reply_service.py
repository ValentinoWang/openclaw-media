from __future__ import annotations


class ReplyService:
    @staticmethod
    def archived(tag: str, local_path: str, feishu_doc: str = "") -> str:
        lines = ["已归档。", f"标签：{tag}", f"本地路径：{local_path}"]
        if feishu_doc:
            lines.append(f"飞书文档：{feishu_doc}")
        return "\n".join(lines)

    @staticmethod
    def pending(reason: str, local_path: str = "") -> str:
        lines = ["处理失败，但原始内容已保存。", "状态：pending_manual", f"原因：{reason}"]
        if local_path:
            lines.append(f"本地路径：{local_path}")
        return "\n".join(lines)

    @staticmethod
    def append_warning(reply: str, warning: str) -> str:
        return "\n".join([reply, f"附加信息：{warning}"])
