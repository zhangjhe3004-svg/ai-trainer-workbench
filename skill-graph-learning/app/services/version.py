# -*- coding: utf-8 -*-
"""模型版本管理服务：训练产出 → 版本生成 → 对比 → 发布 → 回滚。

AI 训练师的核心工作流之一：
1. 训练完成后自动生成一个模型版本（记录版本号、来源训练、指标快照、状态）。
2. 支持多版本并存，横向对比指标选优。
3. 可发布（标记为线上可用）、下线、回滚。

"""
from datetime import datetime, timezone

from bson import ObjectId

from db import model_versions, models, training_runs, evaluations


def _now():
    return datetime.now(timezone.utc)


VERSION_STATUS = ["draft", "released", "archived"]


# ============ 版本生成 ============
def create_version(model_id, run_id=None, note="", metrics=None):
    """从训练运行生成一个模型版本。

    若 run_id 提供，则自动携带该训练的指标快照与参数。
    版本号自动递增（同一模型下的 v1, v2, v3 ...）。
    """
    if not models.find_one({"_id": ObjectId(model_id)}):
        raise ValueError("模型不存在")

    # 自动递增版本号
    last = model_versions.find_one({"model_id": ObjectId(model_id)},
                                   sort=[("version", -1)])
    ver = (last["version"] + 1) if last else 1

    doc = {
        "model_id": ObjectId(model_id),
        "version": ver,
        "run_id": ObjectId(run_id) if run_id else None,
        "note": note or "",
        "metrics": metrics or {},
        "status": "draft",  # draft / released / archived
        "created_at": _now(),
        "updated_at": _now(),
    }
    vid = model_versions.insert_one(doc).inserted_id
    # 更新模型的 current_version 指针
    models.update_one({"_id": ObjectId(model_id)},
                      {"$set": {"current_version": ver, "updated_at": _now()}})
    return str(vid)


def create_version_from_run(run_id, note=""):
    """训练完成后，基于训练运行自动生成版本（携带指标快照）。"""
    run = training_runs.find_one({"_id": ObjectId(run_id)})
    if not run:
        raise ValueError("训练运行不存在")
    metrics = run.get("metrics", {})
    params = run.get("params", {})
    vid = create_version(run["model_id"], run_id=run_id, note=note, metrics=metrics)
    # 补充参数快照
    model_versions.update_one({"_id": ObjectId(vid)},
                              {"$set": {"params": params, "updated_at": _now()}})
    return vid


# ============ 版本查询 ============
def list_versions(model_id=None, status=None, page=1, size=50):
    cond = {}
    if model_id:
        cond["model_id"] = ObjectId(model_id)
    if status:
        cond["status"] = status
    total = model_versions.count_documents(cond)
    cur = model_versions.find(cond, {"model_id": 1, "version": 1, "run_id": 1,
                                     "note": 1, "metrics": 1, "status": 1,
                                     "created_at": 1}) \
        .sort([("model_id", 1), ("version", -1)]).skip((page - 1) * size).limit(size)
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        d["model_id"] = str(d["model_id"])
        d["run_id"] = str(d["run_id"]) if d.get("run_id") else None
        m = models.find_one({"_id": ObjectId(d["model_id"])}, {"name": 1, "base_model": 1})
        d["model_name"] = m["name"] if m else None
        d["version_label"] = "v%d" % d["version"]
        rows.append(d)
    return {"total": total, "rows": rows}


def get_version(vid):
    d = model_versions.find_one({"_id": ObjectId(vid)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    d["model_id"] = str(d["model_id"])
    d["run_id"] = str(d["run_id"]) if d.get("run_id") else None
    return d


# ============ 版本状态流转 ============
def release_version(vid):
    """发布版本（标记为线上可用）。同一模型只允许一个 released 版本，旧的自动归档。"""
    v = model_versions.find_one({"_id": ObjectId(vid)})
    if not v:
        raise ValueError("版本不存在")
    # 归档同模型其他 released 版本
    model_versions.update_many(
        {"model_id": v["model_id"], "status": "released"},
        {"$set": {"status": "archived", "updated_at": _now()}})
    model_versions.update_one({"_id": ObjectId(vid)},
                              {"$set": {"status": "released", "updated_at": _now()}})
    # 更新模型状态为 ready
    models.update_one({"_id": v["model_id"]}, {"$set": {"status": "ready", "updated_at": _now()}})
    return True


def archive_version(vid):
    """归档版本（下线）。"""
    model_versions.update_one({"_id": ObjectId(vid)},
                              {"$set": {"status": "archived", "updated_at": _now()}})
    return True


def delete_version(vid):
    r = model_versions.delete_one({"_id": ObjectId(vid)})
    if r.deleted_count == 0:
        raise ValueError("版本不存在")
    return True


# ============ 版本对比 ============
def compare_versions(model_id):
    """对比同一模型的所有版本指标（横向对比选优）。"""
    cur = model_versions.find({"model_id": ObjectId(model_id)},
                              {"version": 1, "metrics": 1, "status": 1,
                               "note": 1, "created_at": 1}) \
        .sort("version", 1)
    rows = []
    for v in cur:
        rows.append({
            "version": "v%d" % v["version"],
            "status": v.get("status"),
            "metrics": v.get("metrics", {}),
            "note": v.get("note", ""),
            "created_at": v.get("created_at"),
        })
    # 提取所有指标名（用于横向对比）
    metric_names = set()
    for r in rows:
        metric_names.update(r["metrics"].keys())
    return {"rows": rows, "metrics": sorted(metric_names)}


def get_released_version(model_id):
    """获取模型的已发布版本（用于线上推理）。"""
    v = model_versions.find_one({"model_id": ObjectId(model_id), "status": "released"})
    if not v:
        return None
    v["_id"] = str(v["_id"])
    v["model_id"] = str(v["model_id"])
    return v


# ============ 模型推理（指定版本） ============
def infer(model_id, version=None, prompt=""):
    """基于模型某版本做推理（对话）。

    若未指定 version，则使用已发布版本。
    实际调用 LLM 生成回答；若未配置 LLM，则返回模拟结果。
    """
    if not prompt:
        raise ValueError("请输入推理内容")

    # 确定版本
    if version is not None:
        ver = model_versions.find_one({"model_id": ObjectId(model_id), "version": int(version)})
    else:
        ver = model_versions.find_one({"model_id": ObjectId(model_id), "status": "released"})
    if not ver:
        raise ValueError("未找到可用版本，请先训练并发布模型版本")

    # 组装系统提示（携带技能与知识）
    m = models.find_one({"_id": ObjectId(model_id)}, {"name": 1, "base_model": 1})
    skills = list(_get_model_skills(model_id))
    system = f"你是模型「{m['name']}」（基座 {m['base_model']}）的推理实例。"
    if skills:
        system += " 你具备以下技能：" + "、".join(skills)

    try:
        from services import llm
        res = llm.chat([{"role": "system", "content": system},
                        {"role": "user", "content": prompt}])
        return {"answer": res["content"], "backend": res["backend"],
                "model_name": m["name"], "version": "v%d" % ver["version"],
                "skills": skills}
    except Exception:
        # 未配置 LLM 时返回模拟结果
        return {"answer": f"[本地推理] 模型「{m['name']}」v{ver['version']} 对「{prompt}」的回复（当前由内置引擎生成）",
                "backend": "simulate",
                "model_name": m["name"], "version": "v%d" % ver["version"],
                "skills": skills}


def _get_model_skills(model_id):
    from db import skills
    for s in skills.find({"model_id": ObjectId(model_id), "enabled": True}, {"name": 1}):
        yield s["name"]
