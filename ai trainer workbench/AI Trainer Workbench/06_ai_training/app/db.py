# -*- coding: utf-8 -*-
"""连接层：MongoDB 连接、业务库与训练库集合句柄。"""
from pymongo import MongoClient
from pymongo.write_concern import WriteConcern

URI = "mongodb://127.0.0.1:27017"

client = MongoClient(URI, serverSelectionTimeoutMS=5000)

# 业务库 learning
biz = client["learning"]
skills = biz.skills
learners = biz.learners
practice_records = biz.practice_records
assessments = biz.assessments

# 训练库 learning_ai
ai = client["learning_ai"]
samples = ai.samples
features = ai.features
graph_edges = ai.graph_edges
runs = ai.runs


def init_indexes():
    """建库后调用一次，确保索引存在（幂等）。"""
    practice_records.create_index([("learner_id", 1), ("finished_at", -1)], name="idx_learner_time")
    assessments.create_index([("skill_id", 1), ("created_at", -1)], name="idx_skill_time")
    samples.create_index([("learner_id", 1), ("skill_id", 1)], name="uniq_learner_skill", unique=True)
    samples.create_index([("learner_id", 1), ("created_at", -1)], name="idx_learner_time")
    samples.create_index([("label", 1), ("created_at", 1)], name="idx_label_time")
    graph_edges.create_index([("from_skill", 1), ("to_skill", 1)], name="uniq_edge", unique=True)
