# -*- coding: utf-8 -*-
"""AI 训练师工作台 —— 完整运行演示。

单文件演示：建库建集合 → 注册模型 → 调配参数 → 扩展技能 → 导入数据 → 训练 → 评测。
不依赖副本集，连接本机独立 mongod（127.0.0.1:27017），可通过 MONGO_URI 覆盖。

运行：python demo_run.py
"""
import os
from datetime import datetime, timezone

from pymongo import MongoClient

client = MongoClient(os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"),
                     serverSelectionTimeoutMS=5000)
# 业务库 + 训练库
biz = client["trainer"]
ai = client["trainer_ai"]


def line(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def step1_init():
    """建集合 + 索引。"""
    line("【步骤1】建库、建集合与索引")
    for c in ["models", "model_params", "skills", "datasets", "documents", "training_runs"]:
        biz[c].drop()
    for c in ["samples", "features", "graph_edges", "runs"]:
        ai[c].drop()

    biz.models.create_index([("name", 1)], name="uniq_model_name", unique=True)
    biz.model_params.create_index([("model_id", 1)], name="idx_param_model")
    biz.training_runs.create_index([("model_id", 1), ("created_at", -1)], name="idx_run_model_time")
    ai.samples.create_index([("model_id", 1), ("skill_id", 1)], name="uniq_model_skill", unique=True)
    ai.graph_edges.create_index([("from_skill", 1), ("to_skill", 1)], name="uniq_edge", unique=True)
    print("  业务库 training_runs 索引:", [n for n in biz.training_runs.index_information() if n != "_id_"])
    print("  训练库 samples 索引:", [n for n in ai.samples.index_information() if n != "_id_"])


def step2_register_model():
    """注册模型 + 调配参数。"""
    line("【步骤2】注册模型 + 调配参数")
    mid = biz.models.insert_one({
        "name": "医疗问答助手-v1", "base_model": "Qwen2.5-7B", "model_type": "llm",
        "description": "医疗领域问答模型", "tags": ["医疗", "问答"],
        "status": "registered", "created_at": datetime.now(timezone.utc),
    }).inserted_id
    biz.model_params.insert_one({
        "model_id": mid,
        "params": {"learning_rate": 2e-5, "batch_size": 8, "epochs": 3,
                   "temperature": 0.3, "top_p": 0.9, "max_tokens": 1024},
        "created_at": datetime.now(timezone.utc),
    })
    print("  模型:", biz.models.find_one({"_id": mid}, {"name": 1, "base_model": 1}))
    print("  参数:", biz.model_params.find_one({"model_id": mid}, {"params": 1})["params"])
    return mid


def step3_skills(mid):
    """扩展技能 + 挂载到模型。"""
    line("【步骤3】扩展技能 + 挂载")
    skills = [
        ("医疗问诊", "知识问答", "回答医疗问诊问题"),
        ("病历摘要", "摘要", "生成病历摘要"),
        ("用药建议", "知识问答", "给出用药建议"),
    ]
    for name, cat, desc in skills:
        sid = biz.skills.insert_one({
            "name": name, "category": cat, "description": desc,
            "model_id": mid, "enabled": True,
            "created_at": datetime.now(timezone.utc),
        }).inserted_id
        print("  技能:", name, "→ 挂载到模型")
    print("  模型技能数:", biz.skills.count_documents({"model_id": mid}))


def step4_dataset():
    """导入训练数据集。"""
    line("【步骤4】导入训练数据集")
    did = biz.datasets.insert_one({
        "name": "医疗问诊数据", "dataset_type": "qa", "format": "json",
        "samples": [
            {"instruction": "发烧怎么办", "output": "多休息并就医"},
            {"instruction": "如何预约挂号", "output": "通过APP预约"},
        ],
        "sample_count": 2, "created_at": datetime.now(timezone.utc),
    }).inserted_id
    print("  数据集:", biz.datasets.find_one({"_id": did}, {"name": 1, "sample_count": 1}))
    return did


def step5_train(mid, did):
    """发起训练 + 执行 + 产出指标。"""
    line("【步骤5】发起训练 + 执行 + 评测")
    rid = biz.training_runs.insert_one({
        "name": "医疗问诊微调v1", "model_id": mid, "dataset_id": did,
        "task_type": "fine_tuning", "params": {"learning_rate": 2e-5, "epochs": 3},
        "mode": "simulate", "status": "running", "progress": 0.0,
        "logs": [], "created_at": datetime.now(timezone.utc),
    }).inserted_id

    # 模拟训练
    import math
    epochs = 3
    for epoch in range(1, epochs + 1):
        for step in range(1, 11):
            g = (epoch - 1) * 10 + step
            loss = round(4.0 * math.exp(-0.5 * g / 30) + 0.05, 4)
            biz.training_runs.update_one({"_id": rid},
                {"$set": {"progress": round(g / 30, 4)},
                 "$push": {"logs": {"epoch": epoch, "step": g, "loss": loss}}})

    metrics = {"final_loss": 0.45, "accuracy": 0.88, "perplexity": 1.56}
    biz.training_runs.update_one({"_id": rid},
        {"$set": {"status": "completed", "progress": 1.0, "metrics": metrics}})
    biz.models.update_one({"_id": mid}, {"$set": {"status": "ready"}})
    for metric, value in metrics.items():
        biz.evaluations.insert_one({"run_id": rid, "metric": metric, "value": value,
                                    "created_at": datetime.now(timezone.utc)})
    print("  训练结果:", metrics)
    print("  模型状态:", biz.models.find_one({"_id": mid}, {"status": 1})["status"])


def main():
    line("AI 训练师工作台 · 运行演示")
    print("连接 MongoDB:", client.server_info()["version"])
    step1_init()
    mid = step2_register_model()
    step3_skills(mid)
    did = step4_dataset()
    step5_train(mid, did)
    line("演示完成")


if __name__ == "__main__":
    main()
