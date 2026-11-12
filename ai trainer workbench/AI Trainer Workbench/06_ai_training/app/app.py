# -*- coding: utf-8 -*-
"""Flask 接口 + 网页界面：技能图谱学习推荐系统的完整增删改查。"""
from flask import Flask, jsonify, request, render_template

from db import init_indexes
from services import skill, learner, record

app = Flask(__name__)


def ok(data=None):
    return jsonify({"code": 0, "data": data})


def err(msg, code=400):
    return jsonify({"code": code, "msg": msg}), code


# ============ 页面 ============
@app.get("/")
def index():
    return render_template("index.html")


# ============ 技能点 ============
@app.get("/api/skills")
def api_list_skills():
    kw = request.args
    return ok(skill.list_skills(kw.get("keyword"), kw.get("domain"),
                                int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.post("/api/skills")
def api_create_skill():
    b = request.get_json()
    try:
        sid = skill.create_skill(b["title"], b.get("domain", ""), b.get("sub_domain", ""),
                                 b.get("difficulty", 0.5),
                                 b.get("prerequisites", []), b.get("code"))
        return ok({"id": sid})
    except ValueError as e:
        return err(str(e))


@app.get("/api/skills/<sid>")
def api_get_skill(sid):
    d = skill.get_skill(sid)
    return ok(d) if d else err("技能点不存在", 404)


@app.put("/api/skills/<sid>")
def api_update_skill(sid):
    b = request.get_json()
    try:
        skill.update_skill(sid, b.get("title"), b.get("domain"), b.get("sub_domain"),
                           b.get("difficulty"), b.get("prerequisites"))
        return ok()
    except ValueError as e:
        return err(str(e))


@app.delete("/api/skills/<sid>")
def api_delete_skill(sid):
    try:
        skill.delete_skill(sid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


# ============ 学习者 ============
@app.get("/api/learners")
def api_list_learners():
    kw = request.args
    return ok(learner.list_learners(kw.get("keyword"), kw.get("level"),
                                    int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.post("/api/learners")
def api_create_learner():
    b = request.get_json()
    try:
        lid = learner.create_learner(b["nickname"], b.get("level", "beginner"),
                                     b.get("years", 0), b.get("tags", []))
        return ok({"id": lid})
    except ValueError as e:
        return err(str(e))


@app.put("/api/learners/<lid>")
def api_update_learner(lid):
    b = request.get_json()
    try:
        learner.update_learner(lid, b.get("nickname"), b.get("level"),
                               b.get("years"), b.get("tags"))
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/learners/<lid>")
def api_delete_learner(lid):
    try:
        learner.delete_learner(lid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


# ============ 练习记录 ============
@app.get("/api/records")
def api_list_records():
    kw = request.args
    return ok(record.list_records(kw.get("learner_id"), kw.get("keyword"),
                                  int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.post("/api/records")
def api_create_record():
    b = request.get_json()
    try:
        rid = record.create_record(b["learner_id"], b["skill_codes"], b.get("correct_flags", []))
        return ok({"id": rid})
    except ValueError as e:
        return err(str(e))


@app.put("/api/records/<rid>")
def api_update_record(rid):
    b = request.get_json()
    try:
        record.update_record(rid, b.get("status"), b.get("score"))
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/records/<rid>")
def api_delete_record(rid):
    try:
        record.delete_record(rid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


# ============ 自评 & 推荐 ============
@app.post("/api/assessments")
def api_add_assessment():
    b = request.get_json()
    try:
        record.add_assessment(b["learner_id"], b["skill_code"],
                              b.get("rating", 4), b.get("content", ""))
        return ok()
    except ValueError as e:
        return err(str(e))


@app.get("/api/recommend/<learner_id>")
def api_recommend(learner_id):
    try:
        return ok(record.recommend(learner_id))
    except ValueError as e:
        return err(str(e), 404)


if __name__ == "__main__":
    init_indexes()
    app.run(host="127.0.0.1", port=5000, debug=False)
