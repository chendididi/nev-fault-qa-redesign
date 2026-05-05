# 论文实验设计

本文实验部分建议围绕“检索是否准、引用是否可信、延迟是否可接受、部署是否稳定”四个问题展开。

## 实验 1：检索消融实验

目的：证明系统不是简单向量检索，而是通过混合检索和重排序提高维修证据命中率。

对比方法：

- Dense：仅向量召回。
- Dense+Keyword：向量召回加关键词召回。
- Dense+Rerank：向量召回加重排序。
- Hybrid+Rerank：向量召回、关键词召回和重排序。

指标：

- Hit@1、Hit@3、Hit@5。
- MRR。
- nDCG@5。
- Citation Accuracy@K。

论文配图：`fig_retrieval_ablation.png`。

## 实验 2：证据分数与延迟分布

目的：解释不同故障问题在检索分数、重排分数和延迟上的分布，支撑“可信证据链”和“低延迟优化”的叙事。

分析对象：

- top vector score。
- top rerank score。
- keyword coverage@k。
- latency。
- query category。

论文配图：

- `fig_score_pairplot.png`。
- `fig_latency_dashboard.png`。

## 实验 3：知识库向量空间可视化

目的：展示维修知识库分块后在 embedding 空间中形成了与子系统相关的结构，而不是无组织文本堆积。

分析对象：

- 当前 PostgreSQL/pgvector 中的 chunks。
- PCA 二维投影。
- 文本长度、故障码数量、领域词数量、embedding norm。
- 子系统类别：快充/慢充、BMS/电池、高压安全、电驱/热管理、通信/控制等。

论文配图：

- `fig_chunk_embedding_projection.png`。
- `fig_chunk_feature_pairplot.png`。

## 实验 4：端到端案例分析

目的：展示一个真实维修问题如何经过问题解析、检索、重排序、上下文构造、模型生成和引用溯源。

建议案例：

- 快充互锁异常。
- BMS 绝缘电阻低。
- READY 不上电。
- CAN 通信故障。
- 仪表报警图片问答。

正文中应展示：

- 用户问题。
- Top-3 检索证据。
- 结构化诊断答案。
- 引用来源。
- 系统是否触发 fallback 或缓存。

## 运行命令

如果已有评测 CSV，只生成论文图：

```bash
cd /home/chendi2721/nev-fault-qa-redesign/.claude/worktrees/quizzical-perlman-40d40e
DATABASE_URL='postgresql+psycopg://nev:nev_password@localhost:5432/nev_fault_qa' \
  apps/api/.venv/bin/python apps/api/experiments/paper_experiments.py
```

如果需要重新跑检索评测，再生成论文图：

```bash
cd apps/api
DATABASE_URL='postgresql+psycopg://nev:nev_password@localhost:5432/nev_fault_qa' \
  .venv/bin/python evaluate_retrieval.py \
  --variant all \
  --out retrieval_eval_results.csv \
  --summary-out retrieval_eval_summary.json

cd ../..
DATABASE_URL='postgresql+psycopg://nev:nev_password@localhost:5432/nev_fault_qa' \
  apps/api/.venv/bin/python apps/api/experiments/paper_experiments.py
```

注意：`hybrid_rerank` 在 CPU 上会很慢。课程论文优先使用已有全量 `hybrid_rerank` 结果和当前知识库向量可视化；如果服务器 GPU 可用，再重跑完整消融。
