# -*- coding: utf-8 -*-
"""评测中心服务：黄金评测集、批量评测、自动评分、LLM-as-a-Judge、回归与 A/B 对比。

对应工程能力中的 Evaluation Pipeline：
- 黄金数据集（输入 + 预期输出 + 关键词）
- 自动化评分（精确匹配 / 关键词覆盖 / 文本相似度）
- LLM 作为裁判的多维度打分
- 回归测试与版本 A/B 对比，检测性能退化
"""
import json
import difflib
from datetime import datetime, timezone

from bson import ObjectId

from db import evalsets, eval_runs, datasets
from services import llm, nlp, trace


def _now():
    return datetime.now(timezone.utc)


def _serialize(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


# ============ 自动评分 ============
def score_case(expected, actual, keywords=None):
    """单条评分：0~1，综合精确匹配、关键词覆盖、文本相似度。"""
    e = (expected or "").strip()
    a = (actual or "").strip()
    exact = 1.0 if (e and e == a) else 0.0
    if keywords:
        keys = list(keywords)
    else:
        try:
            raw = nlp.keyword_extraction(e, top_k=5) if e else []
            if isinstance(raw, dict):
                res = raw.get("result", {})
                keys = res.get("keywords", []) if isinstance(res, dict) else []
            else:
                keys = list(raw or [])
        except Exception:
            keys = []
        keys = [str(k) for k in keys if k]
    if not keys:
        # 无可提取关键词时，退化为「字符二元组覆盖率」
        keys = [e[i:i + 2] for i in range(len(e) - 1)] or ([e] if e else [])
    kw_hit = [k for k in keys if k and k in a]
    kw_cov = len(kw_hit) / len(keys) if keys else (1.0 if a else 0.0)
    sim = difflib.SequenceMatcher(None, e, a).ratio() if (e and a) else 0.0
    score = round(0.4 * exact + 0.3 * kw_cov + 0.3 * sim, 4)
    return {
        "exact_match": exact,
        "keyword_coverage": round(kw_cov, 4),
        "keywords_hit": kw_hit,
        "similarity": round(sim, 4),
        "score": score,
    }


def judge_case(question, expected, actual):
    """LLM-as-a-Judge：让模型按正确性、完整性、相关性打 1~10 分。

    无 LLM 后端时回退到规则评分，保证评测流程可离线跑通。
    """
    schema = {"type": "object", "properties": {
        "score": {"type": "number"}, "reason": {"type": "string"}}}
    msgs = [
        {"role": "system", "content":
         "你是严格公正的 AI 评测裁判。请按正确性、完整性、相关性为模型回答打 1~10 分，"
         "只输出 JSON：{\"score\": 数字, \"reason\": 简短理由}。"},
        {"role": "user", "content":
         "问题：%s\n参考答案：%s\n模型回答：%s" % (question, expected, actual)},
    ]
    try:
        res = llm.chat_full(msgs, params={"temperature": 0.0}, json_schema=schema)
        if res.get("simulated"):
            raise RuntimeError("offline")
        raw = res["content"].strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[-1]
        data = json.loads(raw)
        s = float(data.get("score", 0))
        return {"score": round(max(0.0, min(1.0, s / 10)), 4),
                "raw_score": s, "reason": str(data.get("reason", "")),
                "source": "llm"}
    except Exception:
        base = score_case(expected, actual)
        return {"score": base["score"], "raw_score": round(base["score"] * 10, 2),
                "reason": "离线规则评分（未配置 LLM 裁判）", "source": "rule"}


# ============ 黄金评测集 ============
def list_evalsets(keyword=None, page=1, size=50):
    cond = {}
    if keyword:
        cond["name"] = {"$regex": keyword, "$options": "i"}
    skip = (int(page) - 1) * int(size)
    rows = []
    for e in evalsets.find(cond).sort("created_at", -1).skip(skip).limit(int(size)):
        d = _serialize(e)
        d["case_count"] = len(e.get("cases", []))
        d.pop("cases", None)
        rows.append(d)
    return {"rows": rows, "total": evalsets.count_documents(cond)}


def get_evalset(eid):
    return _serialize(evalsets.find_one({"_id": ObjectId(eid)}))


def create_evalset(name, description="", cases=None, tags=None):
    """创建黄金评测集。case: {input, expected, keywords?, candidate?, variables?}"""
    if not name:
        raise ValueError("评测集名称不能为空")
    if evalsets.find_one({"name": name}):
        raise ValueError("评测集名称已存在：" + name)
    norm = []
    for c in (cases or []):
        norm.append({
            "input": c.get("input", ""),
            "expected": c.get("expected", ""),
            "keywords": c.get("keywords") or [],
            "candidate": c.get("candidate", c.get("expected", "")),
            "variables": c.get("variables") or {},
        })
    return str(evalsets.insert_one({
        "name": name, "description": description or "",
        "cases": norm, "tags": tags or [],
        "created_at": _now(), "updated_at": _now(),
    }).inserted_id)


def add_cases(eid, cases):
    es = evalsets.find_one({"_id": ObjectId(eid)})
    if not es:
        raise ValueError("评测集不存在")
    norm = [{"input": c.get("input", ""), "expected": c.get("expected", ""),
             "keywords": c.get("keywords") or [],
             "candidate": c.get("candidate", c.get("expected", "")),
             "variables": c.get("variables") or {}} for c in cases]
    evalsets.update_one({"_id": ObjectId(eid)},
                        {"$push": {"cases": {"$each": norm}}, "$set": {"updated_at": _now()}})
    return len(es.get("cases", [])) + len(norm)


def delete_evalset(eid):
    r = evalsets.delete_one({"_id": ObjectId(eid)})
    if r.deleted_count == 0:
        raise ValueError("评测集不存在")
    eval_runs.delete_many({"evalset_id": ObjectId(eid)})
    return True


def import_from_dataset(eid, dataset_id, limit=100):
    """从已有数据集样本导入问答对，自动识别 input / expected 字段。"""
    es = evalsets.find_one({"_id": ObjectId(eid)})
    ds = datasets.find_one({"_id": ObjectId(dataset_id)})
    if not es or not ds:
        raise ValueError("评测集或数据集不存在")
    in_keys = ("input", "question", "prompt", "text", "content")
    out_keys = ("expected", "output", "answer", "label", "target", "completion")
    norm = []
    for s in (ds.get("samples") or [])[:int(limit)]:
        if not isinstance(s, dict):
            continue
        q = next((str(s[k]) for k in in_keys if s.get(k) is not None), "")
        a = next((str(s[k]) for k in out_keys if s.get(k) is not None), "")
        if q or a:
            norm.append({"input": q, "expected": a, "keywords": [],
                         "candidate": a, "variables": {}})
    if not norm:
        raise ValueError("数据集中未识别到可用于评测的问答字段")
    evalsets.update_one({"_id": ObjectId(eid)},
                        {"$push": {"cases": {"$each": norm}}, "$set": {"updated_at": _now()}})
    return {"imported": len(norm), "total": len(es.get("cases", [])) + len(norm)}


# ============ 评测运行 ============
def _generate_answer(case, target_type, target_id, variables):
    """按目标类型生成待测答案。"""
    if target_type == "prompt" and target_id:
        try:
            from services import prompt as prompt_svc
            r = prompt_svc.run_prompt(target_id, variables=(case.get("variables") or variables),
                                      save_trace=False)
            return r.get("content", "")
        except Exception as e:
            return "[提示词试跑失败] " + str(e)
    if target_type == "model" and target_id:
        try:
            from services import version
            r = version.infer(target_id, prompt=case.get("input", ""))
            return r.get("content", "") if isinstance(r, dict) else str(r)
        except Exception as e:
            return "[模型推理失败] " + str(e)
    if target_type == "llm":
        try:
            r = llm.chat_full([{"role": "user", "content": case.get("input", "")}],
                              params={"temperature": 0.0})
            return r["content"]
        except Exception as e:
            return "[LLM 调用失败] " + str(e)
    # sample：使用评测集自带的候选答案，保证离线也能完整演示回归对比
    return case.get("candidate") or case.get("expected", "")


def run_evaluation(evalset_id, target_type="sample", target_id=None,
                   variables=None, judge=False, name="", pass_threshold=0.6):
    """批量评测：逐条生成答案 → 自动评分 → 可选 LLM 裁判 → 汇总落库。"""
    es = get_evalset(evalset_id)
    if not es:
        raise ValueError("评测集不存在")
    cases = es.get("cases") or []
    if not cases:
        raise ValueError("评测集为空，请先添加用例")

    results, total_score, judge_total, passed = [], 0.0, 0.0, 0
    for i, c in enumerate(cases):
        actual = _generate_answer(c, target_type, target_id, variables)
        sc = score_case(c.get("expected", ""), actual, c.get("keywords"))
        row = {
            "index": i, "input": c.get("input", ""),
            "expected": c.get("expected", ""), "actual": actual,
            **sc,
        }
        if judge:
            j = judge_case(c.get("input", ""), c.get("expected", ""), actual)
            row["judge"] = j
            row["score"] = round(0.6 * sc["score"] + 0.4 * j["score"], 4)
            judge_total += j["score"]
        total_score += row["score"]
        if row["score"] >= float(pass_threshold):
            passed += 1
        results.append(row)

    n = len(results)
    summary = {
        "avg_score": round(total_score / n, 4),
        "pass_rate": round(passed / n, 4),
        "passed": passed, "total": n,
        "judge_avg": round(judge_total / n, 4) if judge else None,
        "pass_threshold": float(pass_threshold),
    }
    run_doc = {
        "name": name or ("%s · %s" % (es["name"], target_type)),
        "evalset_id": ObjectId(evalset_id),
        "evalset_name": es["name"],
        "target_type": target_type,
        "target_id": str(target_id or ""),
        "judge_enabled": bool(judge),
        "summary": summary,
        "results": results,
        "created_at": _now(),
    }
    rid = eval_runs.insert_one(run_doc).inserted_id
    try:
        trace.record("eval", model=str(target_id or target_type), status="ok",
                     ref_id=str(rid), note="%s / %d 条" % (es["name"], n))
    except Exception:
        pass
    return {"run_id": str(rid), **summary, "results": results}


def list_runs(evalset_id=None, limit=50):
    cond = {"evalset_id": ObjectId(evalset_id)} if evalset_id else {}
    rows = []
    for r in eval_runs.find(cond, {"results": 0}).sort("created_at", -1).limit(int(limit)):
        d = _serialize(r)
        d["evalset_id"] = str(d["evalset_id"]) if d.get("evalset_id") else None
        rows.append(d)
    return rows


def get_run(rid):
    r = eval_runs.find_one({"_id": ObjectId(rid)})
    if not r:
        raise ValueError("评测运行不存在")
    d = _serialize(r)
    d["evalset_id"] = str(d["evalset_id"]) if d.get("evalset_id") else None
    return d


def compare_runs(rid_a, rid_b):
    """回归对比：比较两次评测，找出提升/退化的具体用例。"""
    a, b = get_run(rid_a), get_run(rid_b)
    ra, rb = a.get("results", []), b.get("results", [])
    map_a = {x["index"]: x for x in ra}
    delta = round(b["summary"]["avg_score"] - a["summary"]["avg_score"], 4)
    improved, regressed = [], []
    for x in rb:
        old = map_a.get(x["index"])
        if not old:
            continue
        d = round(x["score"] - old["score"], 4)
        item = {"index": x["index"], "input": x.get("input", "")[:80],
                "before": old["score"], "after": x["score"], "delta": d}
        if d > 0.05:
            improved.append(item)
        elif d < -0.05:
            regressed.append(item)
    verdict = "性能回归" if delta < -0.05 else ("性能提升" if delta > 0.05 else "基本持平")
    return {
        "run_a": {"id": rid_a, "name": a.get("name"), "summary": a["summary"]},
        "run_b": {"id": rid_b, "name": b.get("name"), "summary": b["summary"]},
        "avg_score_delta": delta,
        "pass_rate_delta": round(b["summary"]["pass_rate"] - a["summary"]["pass_rate"], 4),
        "verdict": verdict,
        "improved": improved, "regressed": regressed,
    }
