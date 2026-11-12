# -*- coding: utf-8 -*-
"""技能图谱学习推荐 —— ETL：从业务库抽取训练样本。

业务库（db: learning）→ 训练库（db: learning_ai）

抽取逻辑：
- 从 practice_records 聚合「学习者×技能点」交互，完成=正样本(label=1)。
- 从 learners 掌握未涉及技能随机采样，生成负样本(label=0)，控制正负比。
- assessments 的 rating 作为显式反馈(mastery)，练习对错作为隐式反馈(correct)。
- 构建技能依赖边写入 graph_edges。
- 特征(难度/画像/embedding 占位)写入 features。

用法：
    python etl_to_training.py --neg_ratio 4
"""
import argparse
import random
import time
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient, InsertOne
from pymongo.write_concern import WriteConcern

# 业务库（读）
SRC_URI = ("mongodb://learnApp:App%402026@127.0.0.1:27017,127.0.0.1:27018,"
           "127.0.0.1:27019/learning?replicaSet=rs0&authSource=learning")
# 训练库（写）
DST_URI = ("mongodb://learnApp:App%402026@127.0.0.1:27017,127.0.0.1:27018,"
           "127.0.0.1:27019/learning_ai?replicaSet=rs0&authSource=learning")

SRC = MongoClient(SRC_URI).get_database("learning")
DST = MongoClient(DST_URI, write_concern=WriteConcern(w="majority")) \
    .get_database("learning_ai")

CHUNK = 20000  # 分块写入，避免文档全驻内存（沿用原系统思想）


def bulk_write(col, docs, size=1000):
    total = 0
    for i in range(0, len(docs), size):
        batch = [InsertOne(d) for d in docs[i:i + size]]
        r = col.bulk_write(batch, ordered=False)
        total += r.inserted_count
    return total


def build_samples(neg_ratio):
    """从练习记录生成正样本，负采样生成负样本。"""
    pos = 0
    for rec in SRC.practice_records.find({}, no_cursor_timeout=True):
        for it in rec.get("skills", []):
            doc = {
                "learner_id": rec["learner_id"],
                "skill_id": it["skill_id"],
                "label": 1,
                "feedback_type": "practice",
                "correct": it.get("correct", True),
                "difficulty": it.get("difficulty", 0.5),
                "ctx": {
                    "domain": it.get("domain", ""),
                    "sub_domain": it.get("sub_domain", ""),
                    "attempt_no": it.get("attempt_no", 1),
                },
                "created_at": rec.get("finished_at", rec.get("created_at")),
            }
            DST.samples.replace_one(
                {"learner_id": doc["learner_id"], "skill_id": doc["skill_id"]},
                doc, upsert=True)
            pos += 1

    # 负采样：为每个学习者随机采样未练习技能
    learners = list(SRC.learners.find({}, {"_id": 1}))
    skills = list(SRC.skills.find({}, {"_id": 1}))
    neg = 0
    for l in learners:
        done = {s["skill_id"] for s in DST.samples.find(
            {"learner_id": l["_id"]}, {"skill_id": 1})}
        cand = [s["_id"] for s in skills if s["_id"] not in done]
        for _ in range(min(neg_ratio, len(cand))):
            sk = random.choice(cand)
            DST.samples.replace_one(
                {"learner_id": l["_id"], "skill_id": sk},
                {"learner_id": l["_id"], "skill_id": sk, "label": 0,
                 "feedback_type": "review", "created_at": datetime.now(timezone.utc)},
                upsert=True)
            neg += 1
    return pos, neg


def build_edges():
    """技能依赖 → graph_edges。"""
    docs = []
    for sk in SRC.skills.find({}, {"_id": 1, "prerequisites": 1}):
        for pre in sk.get("prerequisites", []):
            docs.append({"from_skill": pre, "to_skill": sk["_id"],
                         "rel_type": "prerequisite", "weight": 1.0})
    return bulk_write(DST.graph_edges, docs)


def build_features():
    """技能难度 + 学习者画像 → features。"""
    n = 0
    for sk in SRC.skills.find({}, {"_id": 1, "difficulty": 1, "domain": 1}):
        DST.features.replace_one(
            {"entity_type": "skill", "entity_id": sk["_id"]},
            {"entity_type": "skill", "entity_id": sk["_id"],
             "difficulty": sk.get("difficulty", 0.5),
             "sparse": {"domain_" + str(sk.get("domain", "")): 1},
             "updated_at": datetime.now(timezone.utc)}, upsert=True)
        n += 1
    for l in SRC.learners.find({}, {"_id": 1, "level": 1, "years": 1, "tags": 1}):
        DST.features.replace_one(
            {"entity_type": "learner", "entity_id": l["_id"]},
            {"entity_type": "learner", "entity_id": l["_id"],
             "level": l.get("level", "beginner"),
             "years": l.get("years", 0), "tags": l.get("tags", []),
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
