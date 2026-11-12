// 技能图谱学习推荐 —— AI 训练库分片配置
// 在 mongos 上执行（分片集群）
db = db.getSiblingDB("admin");

// 1. 开启数据库分片
sh.enableSharding("learning_ai")

// 2. samples 主表：以 learner_id 哈希分片
//    推荐训练最重操作是「按学习者聚合其全部练习序列」，哈希分片让同一学习者的
//    样本落在同一分片，聚合与序列构造本地化，避免跨分片。
sh.shardCollection("learning_ai.samples",
  { learner_id: "hashed" })

// 3. features：按 entity_id 哈希分片（规模大、按实体维度访问）
sh.shardCollection("learning_ai.features",
  { entity_id: "hashed" })

// 4. graph_edges：按 from_skill 哈希分片（图遍历以出边为主）
sh.shardCollection("learning_ai.graph_edges",
  { from_skill: "hashed" })

// 5. runs 不分片：元数据量小，单副本即可，避免分片开销
//    （无需调用 shardCollection）

// ================= 验证 =================
printjson(sh.status())
