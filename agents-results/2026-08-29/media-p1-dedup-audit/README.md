# OpenClaw Media P1 去重审计

运行：

```bash
python agents-results/2026-08-29/media-p1-dedup-audit/dedup_p1.py
python agents-results/2026-08-29/media-p1-dedup-audit/dedup_p1.py --json > /tmp/p1-dedup.json
```

算法：从 `pipeline-full-audit.md` 按 `#### <ID>｜<标题>` 区块解析严重度为 P1 的条目；以 ID 保留完整原始轨迹。仅将权威审计中可证明为同一根因的跨域复述放入固定别名组，其他相似文字不合并。每组状态以当前 `main` 历史中存在的进度文档所列提交覆盖 baseline 状态；混合组为“部分修复”。

本次基线：`raw_p1=163`，当前 P1 区块中 8 个固定高置信别名组折叠 8 条重复，得到 **`unique_dedup_p1=155`**。这不是“已完成”数；它是去除跨领域重复后的问题根因数。脚本区分“已修复”和“部分覆盖”：后者表示源码与定向测试存在，但缺生产运行或正式验收证据。当前主线提交由脚本实时读取。
