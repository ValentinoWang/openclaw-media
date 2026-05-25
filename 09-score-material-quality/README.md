# 09 素材质量评分 material-quality-score

素材入库质量评分：下载/拆解前先评估字段完整度、互动质量、复刻价值和风险，减少无效下载、无效分析和低价值入库。

## 目标

- 在下载或拆解前快速判断链接是否值得处理
- 给出素材质量分、复刻价值分和字段完整度分
- 标出缺字段、低互动、重复素材、权限风险等问题
- 将高分素材自动送入 01 内容采集/03 爆款拆解，低分素材进入待复核队列

## 输入

- 单条或批量作品链接
- 05 爆款雷达 的互动快照
- 07 爆款结构库 的历史结构库
- 10 字段健康诊断 的字段健康诊断结果

## 运行

```bash
cd /home/ubuntu/selfmedia-tools/09-score-material-quality
python3 cli.py --urls 'https://v.douyin.com/xxxx/' 'http://xhslink.com/o/xxxx'
```

飞书写入：

```bash
export FEISHU_APP_ID='...'
export FEISHU_APP_SECRET='...'
export FEISHU_BITABLE_URL='https://...feishu.cn/wiki/...?table=tblxxx'
export FEISHU_REQUIRED=1
python3 cli.py --urls 'https://v.douyin.com/xxxx/'
```

也可以显式传入 `--require-feishu --feishu-url 'https://...feishu.cn/wiki/...?table=tblxxx'`。飞书多维表格会自动补齐通用字段：参考链接为链接字段，四个互动数、总互动、互动比率和分数为数字字段，运行时间为日期字段；未配置飞书时仍保留本地 SQLite/JSON/Markdown 备份。

## 输出

- `outputs/quality_scores_YYYYMMDD.json`
- `outputs/review_queue_YYYYMMDD.md`
- `data/material_quality.sqlite`
- 飞书多维表格：每个素材一行，含总分、决策、字段完整度、互动质量、复刻价值

## 评分维度

- `field_completeness_score`：四个互动数、文案、封面、作者、发布时间等字段完整度
- `interaction_quality_score`：点赞、收藏、评论、分享的绝对值和比率
- `growth_score`：短期增长表现
- `recreate_value_score`：是否适合低成本复刻
- `novelty_score`：与历史样本重复程度
- `risk_score`：验证码、权限、版权、敏感话题、素材不可下载等风险

## 评分输出

```json
{
  "url": "https://example.com/post",
  "overall_score": 82,
  "decision": "deconstruct",
  "reasons": [
    "收藏率高",
    "评论有明确需求",
    "字段完整"
  ],
  "missing_fields": []
}
```

## MVP

1. 输入链接后先刷新字段，不下载媒体
2. 根据字段完整度和互动数计算基础分
3. 如果分数达到阈值，再交给 01 内容采集 下载
4. 如果需要拆解，再交给 03 爆款拆解
5. 输出跳过原因，避免黑盒丢弃

## 与现有模块的关系

- 01 内容采集 提供字段抽取和下载能力
- 03 爆款拆解 消费高分素材做拆解
- 05 爆款雷达 提供增长数据
- 06 评论选题池 提供评论需求信号
- 10 字段健康诊断 提供字段失败原因

## Scrapling 可用位置

- 在评分前快速补齐页面字段
- 对字段不完整的素材做二次采集
- 作为字段健康诊断的采集 backend 之一

## 非目标

- 不替代人工最终选题判断
- 不直接生成发布稿
- 不把低分素材永久删除
