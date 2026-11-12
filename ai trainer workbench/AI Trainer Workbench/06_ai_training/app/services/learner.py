# -*- coding: utf-8 -*-
"""学习者服务：增删改查。"""
from datetime import datetime, timezone

from bson import ObjectId

from db import learners, features, practice_records, assessments


def _now():
    return datetime.now(timezone.utc)


def list_learners(keyword=None, level=None, page=1, size=20):
    cond = {}
    if keyword:
        cond["nickname"] = {"$regex": keyword, "$options": "i"}
    if level:
        cond["level"] = level
    total = learners.count_documents(cond)
    cur = learners.find(cond, {"nickname": 1, "level": 1, "years": 1, "tags": 1}) \
        .sort("_id", 1).skip((page - 1) * size).limit(size)
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        rows.append(d)
    return {"total": total, "rows": rows}


def get_learner(lid):
    d = learners.find_one({"_id": ObjectId(lid)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    return d


def create_learner(nickname, level="beginner", years=0, tags=None):
    if learners.find_one({"nickname": nickname}):
        raise ValueError("学习者已存在：" + nickname)
    lid = learners.insert_one({
        "nickname": nickname, "level": level, "years": int(years),
        "tags": tags or [], "created_at": _now(),
    }).inserted_id
    features.replace_one({"entity_type": "learner", "entity_id": lid},
                         {"entity_type": "learner", "entity_id": lid,
                          "level": level, "years": int(years), "tags": tags or [],
                          "updated_at": _now()}, upsert=True)
    return str(lid)


def update_learner(lid, nickname=None, level=None, years=None, tags=None):
    d = learners.find_one({"_id": ObjectId(lid)})
    if not d:
        raise ValueError("学习者不存在")
    upd = {}
    if nickname is not None:
        upd["nickname"] = nickname
    if level is not None:
        upd["level"] = level
    if years is not None:
        upd["years"] = int(years)
    if tags is not None:
        upd["tags"] = tags
    if upd:
        learners.update_one({"_id": ObjectId(lid)}, {"$set": upd})
        features.update_one({"entity_type": "learner", "entity_id": ObjectId(lid)},
                            {"$set": {**upd, "updated_at": _now()}})
    return True


def delete_learner(lid):
    """删除学习者，级联清理其练习、自评与特征。"""
    oid = ObjectId(lid)
    r = learners.delete_one({"_id": oid})
    if r.deleted_count == 0:
        raise ValueError("学习者不存在")
    practice_records.delete_many({"learner_id": oid})
    assessments.delete_many({"learner_id": oid})
    features.delete_one({"entity_type": "learner", "entity_id": oid})
    from db import samples
    samples.delete_many({"learner_id": oid})
    return True
