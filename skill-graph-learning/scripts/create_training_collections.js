// AI 训练师工作台 —— AI 训练库建库、校验器与索引
// db: trainer_ai（运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/trainer_ai" 本文件）
// 对应四集合：samples / features / graph_edges / runs

// ================= 1. samples（训练样本主表）=================
// 一行一条「模型 × 技能」训练交互样本
db.createCollection("samples", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["model_id", "skill_id", "label", "feedback_type", "created_at"],
    properties: {
      model_id:       { bsonType: "objectId" },
      skill_id:       { bsonType: "objectId" },
      label:          { bsonType: "int", enum: [0, 1] },       // 1=正样本 0=负样本
      feedback_type:  { enum: ["training", "eval", "review"] },
      mastery:        { bsonType: "double", minimum: 0, maximum: 5 },
      correct:        { bsonType: "bool" },
      difficulty:     { bsonType: "double", minimum: 0, maximum: 1 },
      ctx: {
        bsonType: "object",
        properties: {
          category:  { bsonType: "string" },   // 技能类别，如 "代码生成"
          attempt_no:{ bsonType: "int" }
        }
      },
      created_at:     { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ================= 2. features（技能/模型特征与画像）=================
db.createCollection("features", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["entity_type", "entity_id"],
    properties: {
      entity_type: { enum: ["skill", "model"] },
      entity_id:   { bsonType: "objectId" },
      difficulty:  { bsonType: "double" },
      model_type:  { bsonType: "string" },
      category:    { bsonType: "string" },
      tags:        { bsonType: "array", items: { bsonType: "string" } },
      dense:       { bsonType: "array", items: { bsonType: "double" } },  // embedding 向量
      sparse:      { bsonType: "object" },
      updated_at:  { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ================= 3. graph_edges（技能依赖图边）=================
db.createCollection("graph_edges", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["from_skill", "to_skill", "rel_type"],
    properties: {
      from_skill: { bsonType: "objectId" },   // 前置技能
      to_skill:   { bsonType: "objectId" },   // 后继技能
      rel_type:   { enum: ["depends_on", "related"] },
      weight:     { bsonType: "double", minimum: 0, maximum: 1 }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ================= 4. runs（训练实验元数据）=================
db.createCollection("runs", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["run_id", "model", "split"],
    properties: {
      run_id:  { bsonType: "string" },
      model:   { bsonType: "string" },        // 模型名
      split:   { enum: ["train", "valid", "test"] },
      params:  { bsonType: "object" },
      metrics: { bsonType: "object" },        // { loss, accuracy, perplexity }
      status:  { enum: ["running", "done", "failed"] },
      created_at: { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ================= 索引策略 =================
// samples：去重 + 按模型取序列 + 按技能取样本 + 按标签采样
db.samples.createIndex({ model_id: 1, skill_id: 1 },
                       { name: "uniq_model_skill", unique: true });
db.samples.createIndex({ model_id: 1, created_at: -1 },
                       { name: "idx_model_time" });
db.samples.createIndex({ skill_id: 1, created_at: -1 },
                       { name: "idx_skill_time" });
db.samples.createIndex({ label: 1, created_at: 1 },
                       { name: "idx_label_time" });

// features：定位实体特征
db.features.createIndex({ entity_type: 1, entity_id: 1 },
                        { name: "uniq_entity", unique: true });

// graph_edges：双向遍历技能依赖图
db.graph_edges.createIndex({ from_skill: 1, rel_type: 1 },
                           { name: "idx_from_rel" });
db.graph_edges.createIndex({ to_skill: 1, rel_type: 1 },
                           { name: "idx_to_rel" });
db.graph_edges.createIndex({ from_skill: 1, to_skill: 1 },
                           { name: "uniq_edge", unique: true });

// runs：按实验 + 数据集切分查询
db.runs.createIndex({ run_id: 1, split: 1 }, { name: "idx_run_split" });

printjson(db.samples.getIndexes().map(i => i.name));
printjson(db.graph_edges.getIndexes().map(i => i.name));
