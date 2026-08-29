# P1 去重审计报告（2026-08-29）

## 结论

在当前 `main`（脚本运行时 `3cd8116b998aa5e67f5e83b2138bfa8f40d71af1`）上，从权威审计清单解析出 163 条 P1 ID。按保守、可复现的跨域同根因规则折叠 7 个别名组（8 条重复），唯一根因数为 **155**。

去重后状态投影：未修复 129、部分修复 6、已修复 20。状态只表示源码/提交/定向测试证据已在进度记录中声明并且提交仍存在于当前 `main`；不表示发布切片或生产部署验收完成。

## 折叠组

| 根因键 | 原始 P1 ID | 保留理由 |
|---|---|---|
| review_draft_attribution | CD-06, BIZ-04 | 同一 data_review 不加载 CreationRun draft 的归因缺口 |
| material_feedback_loop | CD-14, BIZ-09 | 同一 MaterialUsage.performance_feedback_summary 无写回者 |
| reference_shots_whitelist | CPC-11, BIZ-11 | 同一候选压缩白名单剥掉 reference_shots/production_summary |
| xiaohongshu_carousel_contract | CPC-12, CC-04 | 同一 carousel 与 image_script validator 契约冲突 |
| business_stale_month_and_price | CPO-K04, CC-07, BIZ-17, CR-26 | 同一商单月份/价格硬编码腐烂根因 |
| frontmatter_model_contract | LP-11, LB-12 | 同一 frontmatter 精确校验与模型名漂移阻断手动运行 |
| model_tier_split | LP-10, LH-07 | 同一 runner/llm_common 模型档位分裂 |

其余 148 个 ID 均保持 singleton。相似主题但没有相同根因证据的条目不合并。

## 复现

```bash
python agents-results/2026-08-29/media-p1-dedup-audit/dedup_p1.py
python agents-results/2026-08-29/media-p1-dedup-audit/dedup_p1.py --json
```

算法实现和当前证据提交映射见同目录 `dedup_p1.py` 与 `p1-dedup.json`。输入只读：`pipeline-full-audit.md`、`audit-followup-review.md`、`implementation-progress.md` 及 `git log`；未修改业务代码或保护测试。
