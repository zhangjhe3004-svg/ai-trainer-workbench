# -*- coding: utf-8 -*-
"""技能点服务：增删改查 + 依赖校验。"""
from datetime import datetime, timezone

from bson import ObjectId

from db import skills, graph_edges, features


def _now():
    return datetime.now(timezone.utc)


def list_skills(keyword=None, domain=None, page=1, size=20):
    """查询技能点列表（支持关键字、领域筛选 + 分页）。"""
    cond = {}
    if keyword:
        cond["title"] = {"$regex": keyword, "$options": "i"}
    if domain:
        cond["domain"] = domain
    total = skills.count_documents(cond)
    cur = (skills.find(cond, {"title": 1, "domain": 1, "sub_domain": 1,
                              "difficulty": 1, "prerequisites": 1, "code": 1})
                 .sort("difficulty", 1)
                 .skip((page - 1) * size).limit(size))
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        rows.append(d)
    return {"total": total, "rows": rows}


def get_skill(sid):
    d = skills.find_one({"_id": ObjectId(sid)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    return d


def create_skill(title, domain, sub_domain, difficulty, prerequisites, code=None):
    """新增技能点，同步写入依赖边与特征。"""
    pre_titles = [p.strip() for p in prerequisites if p.strip()]
    # 校验前置技能存在
    missing = [p for p in pre_titles if not skills.find_one({"title": p})]
    if missing:
        raise ValueError("前置技能不存在：" + ", ".join(missing))
    if skills.find_one({"title": title}):
        raise ValueError("技能点已存在：" + title)
    code = code or ("SK-%06d" % (skills.count_documents({}) + 1))
    sid = skills.insert_one({
        "code": code, "title": title, "domain": domain, "sub_domain": sub_domain,
        "difficulty": float(difficulty), "prerequisites": pre_titles,
        "created_at": _now(),
    }).inserted_id
    # 依赖边
    for pre in pre_titles:
        pre_id = skills.find_one({"title": pre})["_id"]
        graph_edges.replace_one(
            {"from_skill": pre_id, "to_skill": sid},
            {"from_skill": pre_id, "to_skill": sid, "rel_type": "prerequisite", "weight": 1.0},
            upsert=True)
    # 特征
    features.replace_one({"entity_type": "skill", "entity_id": sid},
                         {"entity_type": "skill", "entity_id": sid,
                          "difficulty": float(difficulty), "updated_at": _now()}, upsert=True)
    return str(sid)


def update_skill(sid, title=None, domain=None, sub_domain=None, difficulty=None, prerequisites=None):
    """更新技能点，可选字段更新；改依赖时同步重建依赖边。"""
    d = skills.find_one({"_id": ObjectId(sid)})
    if not d:
        raise ValueError("技能点不存在")
    upd = {}
    if title is not None:
        upd["title"] = title
    if domain is not None:
        upd["domain"] = domain
    if sub_domain is not None:
        upd["sub_domain"] = sub_domain
    if difficulty is not None:
        upd["difficulty"] = float(difficulty)
    if prerequisites is not None:
        pre_titles = [p.strip() for p in prerequisites if p.strip()]
        missing = [p for p in pre_titles if not skills.find_one({"title": p})]
        if missing:
            raise ValueError("前置技能不存在：" + ", ".join(missing))
        upd["prerequisites"] = pre_titles
        # 重建依赖边
        graph_edges.delete_many({"to_skill": ObjectId(sid)})
        for pre in pre_titles:
            pre_id = skills.find_one({"title": pre})["_id"]
            graph_edges.replace_one(
                {"from_skill": pre_id, "to_skill": ObjectId(sid)},
                {"from_skill": pre_id, "to_skill": ObjectId(sid),
                 "rel_type": "prerequisite", "weight": 1.0}, upsert=True)
    if upd:
        skills.update_one({"_id": ObjectId(sid)}, {"$set": upd})
        if difficulty is not None:
            features.update_one({"entity_type": "skill", "entity_id": ObjectId(sid)},
                                {"$set": {"difficulty": float(difficulty), "updated_at": _now()}})
    return True


def delete_skill(sid):
    """删除技能点，级联清理依赖边与特征。"""
    r = skills.delete_one({"_id": ObjectId(sid)})
    if r.deleted_count == 0:
        raise ValueError("技能点不存在")
    graph_edges.delete_many({"$or": [{"from_skill": ObjectId(sid)}, {"to_skill": ObjectId(sid)}]})
    features.delete_one({"entity_type": "skill", "entity_id": ObjectId(sid)})
    # 同步移除其他技能对该技能的引用
    skills.update_many({"prerequisites": {"$in": [None]}}, {"$pull": {"prerequisites": None}})
    return True
