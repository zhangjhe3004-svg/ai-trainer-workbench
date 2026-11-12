# -*- coding: utf-8 -*-
"""AI 训练师工作台 —— ETL：从业务库抽取训练样本。

业务库（db: trainer）→ 训练库（db: trainer_ai）

抽取逻辑：
- 从 training_runs 聚合「模型×技能」训练交互，完成=正样本(label=1)。
- 从 models 未涉及技能随机采样，生成负样本(label=0)，控制正负比。
- 构建技能依赖边写入 graph_edges。
- 特征(难度/画像/embedding 占位)写入 features。

用法：
    python etl_to_training.py --neg_ratio 4
"""
import argparse
import os
import random
import time
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient, InsertOne
from pymongo.write_concern import WriteConcern

URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")

SRC = MongoClient(URI).get_database("trainer")
DST = MongoClient(URI, write_concern=WriteConcern(w="majority")) \
    .get_database("trainer_ai")

CHUNK = 20000


def bulk_write(col, docs, size=1000):
    total = 0
    for i in range(0, len(docs), size):
        batch = [InsertOne(d) for d in docs[i:i + size]]
        r = col.bulk_write(batch, ordered=False)
        total += r.inserted_count
    return total


def build_samples(neg_ratio):
    """从训练运行生成正样本，负采样生成负样本。"""
    pos = 0
    for run in SRC.training_runs.find({}, no_cursor_timeout=True):
        for skill in run.get("skills", []):
            doc = {
                "model_id": run["model_id"],
                "skill_id": skill["skill_id"],
                "label": 1,
                "feedback_type": "training",
                "correct": skill.get("correct", True),
                "difficulty": skill.get("difficulty", 0.5),
                "ctx": {
                    "category": skill.get("category", ""),
                    "attempt_no": skill.get("attempt_no", 1),
                },
                "created_at": run.get("created_at"),
            }
            DST.samples.replace_one(
                {"model_id": doc["model_id"], "skill_id": doc["skill_id"]},
                doc, upsert=True)
            pos += 1

    # 负采样：为每个模型随机采样未训练技能
    models = list(SRC.models.find({}, {"_id": 1}))
    skills = list(SRC.skills.find({}, {"_id": 1}))
    neg = 0
    for m in models:
        done = {s["skill_id"] for s in DST.samples.find(
            {"model_id": m["_id"]}, {"skill_id": 1})}
        cand = [s["_id"] for s in skills if s["_id"] not in done]
        for _ in range(min(neg_ratio, len(cand))):
            sk = random.choice(cand)
            DST.samples.replace_one(
                {"model_id": m["_id"], "skill_id": sk},
                {"model_id": m["_id"], "skill_id": sk, "label": 0,
                 "feedback_type": "review", "created_at": datetime.now(timezone.utc)},
                upsert=True)
            neg += 1
    return pos, neg


def build_edges():
    """技能依赖 → graph_edges。"""
    docs = []
    for sk in SRC.skills.find({}, {"_id": 1, "prerequisites": 1}):
        for pre_name in sk.get("prerequisites", []):
            pre = SRC.skills.find_one({"name": pre_name})
            if pre:
                docs.append({"from_skill": pre["_id"], "to_skill": sk["_id"],
                             "rel_type": "depends_on", "weight": 1.0})
    return bulk_write(DST.graph_edges, docs)


def build_features():
    """技能类别 + 模型类型 → features。"""
    n = 0
    for sk in SRC.skills.find({}, {"_id": 1, "category": 1}):
        DST.features.replace_one(
            {"entity_type": "skill", "entity_id": sk["_id"]},
            {"entity_type": "skill", "entity_id": sk["_id"],
             "category": sk.get("category", ""),
             "sparse": {"cat_" + str(sk.get("category", "")): 1},
             "updated_at": datetime.now(timezone.utc)}, upsert=True)
        n += 1
    for m in SRC.models.find({}, {"_id": 1, "model_type": 1, "tags": 1}):
        DST.features.replace_one(
            {"entity_type": "model", "entity_id": m["_id"]},
            {"entity_type": "model", "entity_id": m["_id"],
             "model_type": m.get("model_type", "llm"),
             "tags": m.get("tags", []),
             "updated_at": datetime.now(timezone.utc)}, upsert=True)
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--neg_ratio", type=int, default=4)
    args = ap.parse_args()

    t0 = time.time()
    pos, neg = build_samples(args.neg_ratio)
    print("[1/3] samples 正样本 %d / 负样本 %d，耗时 %.1f s"
          % (pos, neg, time.time() - t0))

    t1 = time.time()
    e = build_edges()
    print("[2/3] graph_edges %d 条，耗时 %.1f s" % (e, time.time() - t1))

    t2 = time.time()
    f = build_features()
    print("[3/3] features %d 条，耗时 %.1f s" % (f, time.time() - t2))


if __name__ == "__main__":
    main()
