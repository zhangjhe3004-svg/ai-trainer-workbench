// AI 训练师工作台 —— 业务库建库、校验器与索引
// db: trainer（运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/trainer" 本文件）
// 对应 A 卷 2.2 方向一：创建数据库和集合

// ============ 1. models 模型注册表（含数组 + 嵌套文档）============
db.createCollection("models", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["name", "base_model", "model_type", "status", "created_at"],
    properties: {
      name:        { bsonType: "string" },
      base_model:  { bsonType: "string" },
      model_type:  { enum: ["llm", "embedding", "vision", "multimodal"] },
      description: { bsonType: "string" },
      tags:        { bsonType: "array", items: { bsonType: "string" } },
      status:      { enum: ["registered", "training", "ready", "deprecated"] },
      created_at:  { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ============ 2. model_params 参数配置（嵌套文档）============
db.createCollection("model_params", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["model_id", "params", "created_at"],
    properties: {
      model_id:   { bsonType: "objectId" },
      params:     { bsonType: "object" },  // 核心超参数（嵌套文档）
      created_at: { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ============ 3. skills 模型技能（能力扩展）============
db.createCollection("skills", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["name", "category", "created_at"],
    properties: {
      name:            { bsonType: "string" },
      category:        { bsonType: "string" },
      description:     { bsonType: "string" },
      prompt_template: { bsonType: "string" },
      prerequisites:   { bsonType: "array", items: { bsonType: "string" } },  // 依赖
      model_id:        { bsonType: ["objectId", "null"] },
      enabled:         { bsonType: "bool" },
      created_at:      { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ============ 4. training_runs 训练运行（含数组 + 嵌套文档）============
db.createCollection("training_runs", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["name", "model_id", "dataset_id", "status", "created_at"],
    properties: {
      name:       { bsonType: "string" },
      model_id:   { bsonType: "objectId" },
      dataset_id: { bsonType: "objectId" },
      task_type:  { enum: ["fine_tuning", "lora", "rlhf", "rag", "embedding", "eval"] },
      params:     { bsonType: "object" },      // 参数快照（嵌套文档）
      mode:       { enum: ["simulate", "real"] },
      status:     { enum: ["pending", "running", "completed", "failed"] },
      progress:   { bsonType: "double", minimum: 0, maximum: 1 },
      logs:       { bsonType: "array", items: { bsonType: "object" } },  // 训练日志
      metrics:    { bsonType: "object" },
      created_at: { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ============ 索引（对应 A 卷 2.2 第 5 项）============
// 模型：名称唯一 + 按类型/状态
db.models.createIndex({ name: 1 }, { name: "uniq_model_name", unique: true });
db.models.createIndex({ model_type: 1, created_at: -1 }, { name: "idx_model_type_time" });
// 参数：按模型
db.model_params.createIndex({ model_id: 1 }, { name: "idx_param_model" });
// 技能：名称唯一 + 按类别
db.skills.createIndex({ name: 1 }, { name: "uniq_skill_name", unique: true });
db.skills.createIndex({ category: 1 }, { name: "idx_skill_category" });
// 训练运行：按模型 + 时间倒序（ESR 原则：等值在前、排序在后）
db.training_runs.createIndex({ model_id: 1, created_at: -1 }, { name: "idx_run_model_time" });
db.training_runs.createIndex({ status: 1, created_at: -1 }, { name: "idx_run_status" });

printjson(db.models.getIndexes().map(i => i.name));
printjson(db.training_runs.getIndexes().map(i => i.name));
