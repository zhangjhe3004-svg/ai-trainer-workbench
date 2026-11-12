# 技能图谱学习推荐 —— AI 训练库方案

本目录为「个人成长技能图谱与学习路径推荐」系统设计了一套 MongoDB AI 训练库，
对应原电商系统的 02_schema / 03_data 风格，可直接运行。

## 系统定位

以学习者为中心的技能图谱系统：学习者围绕「技能点（skill）」展开练习与自评，
系统基于练习序列 + 技能依赖图，推荐下一步学习路径。

### 与原电商系统的映射

| 原电商实体 | 本系统实体 | 说明 |
|---|---|---|
| products | skills | 有难度/前置依赖，多规格（非结构化 specs 思想） |
| users | learners | level、年限、标签画像 |
| orders | practice_records | 一次练习覆盖多技能（明细 1~N），有状态流转 |
| reviews | assessments | rating=掌握度自评(1~5)，content=反思笔记 |

## AI 训练方向

1. **知识状态追踪（Knowledge Tracing，DKT/DKVMN）**：输入练习序列，预测掌握度。
2. **学习路径推荐**：结合技能依赖图（graph_edges）+ 当前掌握度，推荐下一技能。
3. **难度自适应**：用 difficulty + 历史表现动态调整难度。

## 文件说明

| 文件/目录 | 作用 |
|---|---|
| 00_命令清单.md | 按执行顺序汇总全部命令 |
| 01_schema/create_collections.js | 业务库 learning 建库、校验器、索引 |
| 01_schema/create_users.js | 访问控制（管理用户 + 业务账号） |
| 02_data/generate_data.py | 造数脚本（含数组 + 嵌套文档） |
| 03_query/crud.js | 七类增删改查 |
| 03_query/aggregation.js | 聚合管道统计 |
| 03_query/index_explain.js | 索引 explain() 对比 |
| create_collections.js | 训练库 learning_ai 建库、校验器、索引 |
| shard_config.js | 分片集群配置（在 mongos 上执行） |
| etl_to_training.py | ETL：正负样本抽取、建边、特征 |
| demo_run.py | 一次性演示脚本 |
| app/ | 可落地应用（网页后台 + 命令行 + 服务层） |

## 集合与索引

- **samples**：训练样本主表，`{learner_id, skill_id}` 唯一去重；按 learner/skill/label 建索引。
- **features**：技能/学习者特征与 embedding，`{entity_type, entity_id}` 唯一。
- **graph_edges**：技能依赖边，双向索引支持图遍历。
- **runs**：实验/模型元数据，不分片。

## 分片思路

- samples / features / graph_edges 均用**哈希分片**（learner_id / entity_id / from_skill），
  使「按学习者聚合序列」「按实体取特征」「图出边遍历」本地化，避免跨分片。
- runs 元数据量小，不分片。

## 执行顺序

```bash
# 1. 建库 + 索引
mongosh "mongodb://learnApp:App%402026@127.0.0.1:27017/learning_ai?authSource=learning" \
  06_ai_training/create_collections.js

# 2. 分片（在 mongos 上）
mongosh "mongodb://127.0.0.1:27017/admin" 06_ai_training/shard_config.js

# 3. ETL 抽取
python 06_ai_training/etl_to_training.py --neg_ratio 4
```

## 存储与读取流程

**写入**：practice_records → 正样本；随机负采样 → 负样本；assessments → 显式反馈；
skills.prerequisites → graph_edges；画像/难度 → features。批量分块写入，幂等 upsert。

**读取**：按 learner_id 取完整练习序列（构造时序）；按 label+created_at 切分
train/valid/test（避免泄漏）；按 graph_edges 遍历依赖图；用 features 做冷启动。
