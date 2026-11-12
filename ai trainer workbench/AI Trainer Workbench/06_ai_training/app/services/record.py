# -*- coding: utf-8 -*-
"""练习记录服务：增删改查 + 自评 + 路径推荐。"""
from datetime import datetime, timezone

from bson import ObjectId

from db import practice_records, assessments, skills, learners, samples


def _now():
    return datetime.now(timezone.utc)


def list_records(learner_id=None, keyword=None, page=1, size=20):
    cond = {}
    if learner_id:
        cond["learner_id"] = ObjectId(learner_id)
    if keyword:
        cond["record_no"] = {"$regex": keyword, "$options": "i"}
    total = practice_records.count_documents(cond)
    cur = practice_records.find(cond, {"record_no": 1, "learner_id": 1, "status": 1,
                                       "score": 1, "finished_at": 1, "skills": 1}) \
        .sort("finished_at", -1).skip((page - 1) * size).limit(size)
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        d["learner_id"] = str(d["learner_id"])
        d["skill_count"] = len(d.get("skills", []))
        rows.append(d)
    return {"total": total, "rows": rows}


def get_record(rid):
    d = practice_records.find_one({"_id": ObjectId(rid)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    d["learner_id"] = str(d["learner_id"])
    return d


def create_record(learner_id, skill_codes, correct_flags):
    """录入一条练习记录：learner_id + 技能编码列表 + 对错列表。"""
    if not learners.find_one({"_id": ObjectId(learner_id)}):
        raise ValueError("学习者不存在")
    skill_items = []
    for i, code in enumerate(skill_codes):
        sk = skills.find_one({"code": code})
        if not sk:
            raise ValueError("技能不存在：" + code)
        correct = correct_flags[i] if i < len(correct_flags) else True
        skill_items.append({
            "skill_id": sk["_id"], "correct": bool(correct),
            "difficulty": sk.get("difficulty", 0.5), "attempt_no": 1,
            "domain": sk.get("domain", ""), "sub_domain": sk.get("sub_domain", ""),
        })
    now = _now()
    rid = practice_records.insert_one({
        "record_no": "PR" + now.strftime("%Y%m%d%H%M%S%f"),
        "learner_id": ObjectId(learner_id),
        "skills": skill_items,
        "score": sum(1 for s in skill_items if s["correct"]) / len(skill_items),
        "status": "completed",
        "timeline": [{"status": "completed", "at": now}],
        "finished_at": now,
    }).inserted_id
    # 实时同步训练样本（正样本）
    for s in skill_items:
        samples.replace_one(
            {"learner_id": ObjectId(learner_id), "skill_id": s["skill_id"]},
            {"learner_id": ObjectId(learner_id), "skill_id": s["skill_id"],
             "label": 1, "feedback_type": "practice", "correct": s["correct"],
             "difficulty": s["difficulty"], "created_at": now}, upsert=True)
    return str(rid)


def update_record(rid, status=None, score=None):
    d = practice_records.find_one({"_id": ObjectId(rid)})
    if not d:
        raise ValueError("练习记录不存在")
    upd = {}
    if status is not None:
        upd["status"] = status
    if score is not None:
        upd["score"] = float(score)
    if upd:
        practice_records.update_one({"_id": ObjectId(rid)}, {"$set": upd})
    return True


def delete_record(rid):
    r = practice_records.delete_one({"_id": ObjectId(rid)})
    if r.deleted_count == 0:
        raise ValueError("练习记录不存在")
    return True


def add_assessment(learner_id, skill_code, rating, content=""):
    """新增自评。"""
    sk = skills.find_one({"code": skill_code})
    if not sk:
        raise ValueError("技能不存在：" + skill_code)
    if not (1 <= float(rating) <= 5):
        raise ValueError("评分需在 1~5 之间")
    aid = assessments.insert_one({
        "learner_id": ObjectId(learner_id), "skill_id": sk["_id"],
        "rating": float(rating), "content": content, "created_at": _now(),
    }).inserted_id
    # 同步训练样本的 mastery（显式反馈）
    samples.update_one(
        {"learner_id": ObjectId(learner_id), "skill_id": sk["_id"]},
        {"$set": {"mastery": float(rating), "feedback_type": "assess"}})
    return str(aid)


def recommend(learner_id):
    """路径推荐：返回前置已满足且未学的技能。"""
    oid = ObjectId(learner_id)
    lr = learners.find_one({"_id": oid})
    if not lr:
        raise ValueError("学习者不存在")
    done_titles = set()
    for rec in practice_records.find({"learner_id": oid}):
        for s in rec.get("skills", []):
            sk = skills.find_one({"_id": s["skill_id"]})
            if sk:
                done_titles.add(sk["title"])
    result = []
    for sk in skills.find({}):
        if sk["title"] in done_titles:
            continue
        pre_ok = all(p in done_titles for p in sk.get("prerequisites", []))
        if pre_ok:
            result.append({"code": sk["code"], "title": sk["title"],
                           "difficulty": sk.get("difficulty", 0.5)})
    result.sort(key=lambda x: x["difficulty"])
    return {"learner": lr["nickname"], "mastered": sorted(done_titles), "recommend": result}
