# -*- coding: utf-8 -*-
"""造数脚本：模型、技能、数据集、知识文档、训练运行。

用法：
    python generate_data.py [--models 6 --skills 20 --datasets 8 --documents 30 --runs 12]

要点：
- 模型含参数配置（model_params 嵌套文档）。
- 技能含类别与提示词模板。
- 数据集含样本数组（samples[]）。
- 训练运行含参数快照（params）与指标（metrics）。
"""
import argparse
import os
import random
import time
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import MongoClient, InsertOne

URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
CLIENT = MongoClient(URI)
DB = CLIENT["trainer"]

BASE_MODELS = [
    ("Qwen2.5-7B", "llm"), ("Qwen2.5-14B", "llm"), ("DeepSeek-V3", "llm"),
    ("bge-m3", "embedding"), ("text-embedding-3-small", "embedding"),
    ("Qwen2-VL-7B", "multimodal"),
]

SKILL_POOL = [
    ("代码生成", "代码生成", "根据需求生成代码"),
    ("代码审查", "代码生成", "审查代码质量与潜在缺陷"),
    ("知识问答", "知识问答", "回答各领域知识问题"),
    ("文本摘要", "摘要", "提取文本核心要点"),
    ("机器翻译", "翻译", "多语言互译"),
    ("工具调用", "工具调用", "调用外部工具/API 完成任务"),
    ("情感分析", "文本生成", "判断文本情感倾向"),
    ("图像理解", "图像理解", "理解图像内容并描述"),
    ("逻辑推理", "知识问答", "多步逻辑推理"),
    ("创意写作", "文本生成", "生成创意性文字内容"),
    ("SQL 生成", "代码生成", "自然语言转 SQL"),
    ("数据分析", "其他", "分析数据并给出洞察"),
]

DATASET_TYPES = ["instruction", "preference", "classification", "qa", "raw"]


def gen_models(n):
    models = []
    params = []
    for i in range(n):
        name, mtype = BASE_MODELS[i % len(BASE_MODELS)]
        mid = ObjectId()
        models.append({
            "_id": mid,
            "name": "%s-%02d" % (name, i),
            "base_model": name,
            "model_type": mtype,
            "description": "演示模型 %02d" % i,
            "tags": ["演示"],
            "status": "registered",
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 90)),
            "updated_at": datetime.now(timezone.utc),
        })
        # 参数配置
        p = {
            "learning_rate": random.choice([1e-5, 2e-5, 3e-5, 5e-5]),
            "batch_size": random.choice([4, 8, 16, 32]),
            "epochs": random.choice([1, 2, 3, 5]),
            "temperature": round(random.uniform(0.5, 1.0), 2),
            "top_p": round(random.uniform(0.8, 0.95), 2),
            "max_tokens": random.choice([512, 1024, 2048]),
            "weight_decay": 0.01,
            "gradient_accumulation_steps": random.choice([1, 2, 4]),
            "optimizer": "adamw",
            "lr_scheduler": "cosine",
        }
        params.append({
            "model_id": mid,
            "params": p,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
    return models, params


def gen_skills(n, models):
    skills = []
    for i in range(n):
        name, category, desc = SKILL_POOL[i % len(SKILL_POOL)]
        skills.append({
            "_id": ObjectId(),
            "name": "%s-%02d" % (name, i),
            "category": category,
            "description": desc,
            "prompt_template": "请完成以下任务：{input}",
            "prerequisites": [],
            "model_id": random.choice(models)["_id"] if random.random() < 0.5 else None,
            "enabled": True,
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 60)),
            "updated_at": datetime.now(timezone.utc),
        })
    return skills


def gen_datasets(n):
    datasets = []
    for i in range(n):
        dtype = DATASET_TYPES[i % len(DATASET_TYPES)]
        samples = []
        for j in range(random.randint(3, 20)):
            samples.append({
                "instruction": "演示指令 %d-%d" % (i, j),
                "output": "演示输出 %d-%d" % (i, j),
            })
        datasets.append({
            "_id": ObjectId(),
            "name": "训练数据集-%02d" % i,
            "description": "演示数据集",
            "dataset_type": dtype,
            "format": "json",
            "tags": ["演示", dtype],
            "samples": samples,
            "sample_count": len(samples),
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 60)),
            "updated_at": datetime.now(timezone.utc),
        })
    return datasets


def gen_documents(n, models):
    docs = []
    for i in range(n):
        docs.append({
            "_id": ObjectId(),
            "title": "知识文档-%02d" % i,
            "content": "这是第 %d 篇知识文档的内容，用于注入给模型作为 RAG 知识源。" % i,
            "model_id": random.choice(models)["_id"] if random.random() < 0.6 else None,
            "doc_type": random.choice(["note", "article", "reference", "example"]),
            "summary": "知识文档摘要 %d" % i,
            "tags": ["知识库"],
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 60)),
            "updated_at": datetime.now(timezone.utc),
        })
    return docs


def gen_runs(n, models, datasets):
    runs = []
    for i in range(n):
        status = random.choice(["pending", "completed", "completed", "completed"])
        progress = 1.0 if status == "completed" else 0.0
        runs.append({
            "_id": ObjectId(),
            "name": "训练运行-%02d" % i,
            "model_id": random.choice(models)["_id"],
            "dataset_id": random.choice(datasets)["_id"],
            "task_type": random.choice(["fine_tuning", "lora", "rag", "embedding"]),
            "params": {"learning_rate": 2e-5, "batch_size": 8, "epochs": 3},
            "mode": "simulate",
            "status": status,
            "progress": progress,
            "metrics": {"final_loss": round(random.uniform(0.5, 2.0), 4),
                        "accuracy": round(random.uniform(0.7, 0.95), 4)} if status == "completed" else {},
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30)),
            "updated_at": datetime.now(timezone.utc),
        })
    return runs


def bulk_write(col, docs, size=1000):
    total = 0
    for i in range(0, len(docs), size):
        r = col.bulk_write([InsertOne(d) for d in docs[i:i + size]], ordered=False)
        total += r.inserted_count
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=int, default=6)
    ap.add_argument("--skills", type=int, default=20)
    ap.add_argument("--datasets", type=int, default=8)
    ap.add_argument("--documents", type=int, default=30)
    ap.add_argument("--runs", type=int, default=12)
    args = ap.parse_args()

    t0 = time.time()
    models, params = gen_models(args.models)
    bulk_write(DB.models, models)
    bulk_write(DB.model_params, params)
    print("[1/5] models %d 条 + params %d 条，耗时 %.1f s" % (len(models), len(params), time.time() - t0))

    t1 = time.time()
    sk = gen_skills(args.skills, models)
    bulk_write(DB.skills, sk)
    print("[2/5] skills %d 条，耗时 %.1f s" % (len(sk), time.time() - t1))

    t2 = time.time()
    ds = gen_datasets(args.datasets)
    bulk_write(DB.datasets, ds)
    print("[3/5] datasets %d 条，耗时 %.1f s" % (len(ds), time.time() - t2))

    t3 = time.time()
    dc = gen_documents(args.documents, models)
    bulk_write(DB.documents, dc)
    print("[4/5] documents %d 条，耗时 %.1f s" % (len(dc), time.time() - t3))

    t4 = time.time()
    runs = gen_runs(args.runs, models, ds)
    bulk_write(DB.training_runs, runs)
    print("[5/5] training_runs %d 条，耗时 %.1f s" % (len(runs), time.time() - t4))

    print("合计 %d 条，总耗时 %.1f s"
          % (len(models) + len(params) + len(sk) + len(ds) + len(dc) + len(runs), time.time() - t0))


if __name__ == "__main__":
    main()
