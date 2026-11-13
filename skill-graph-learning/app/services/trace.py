# -*- coding: utf-8 -*-
"""可观测性服务：统一记录 LLM 调用追踪，汇总 token、成本与延迟。

对应工程能力中的 Tracing / LLMOps / 延迟与成本优化。
提示词试跑、批量评测、RAG 问答、模型推理等链路都会写入同一份 trace。
"""
from datetime import datetime, timezone, timedelta

from db import traces


def _now():
    return datetime.now(timezone.utc)


def record(kind, model="", prompt_tokens=0, completion_tokens=0,
           cost_usd=0.0, latency_ms=0, status="ok", backend="",
           ref_id="", note="", error=""):
    """写入一条调用追踪。

    kind: prompt / eval / rag / infer / chat / guard
    status: ok / error / blocked
    """
    doc = {
        "kind": kind,
        "model": model or "unknown",
        "backend": backend or "",
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(prompt_tokens or 0) + int(completion_tokens or 0),
        "cost_usd": float(cost_usd or 0),
        "latency_ms": int(latency_ms or 0),
        "status": status,
        "ref_id": str(ref_id or ""),
        "note": note or "",
        "error": error or "",
        "created_at": _now(),
    }
    return str(traces.insert_one(doc).inserted_id)


def list_traces(kind=None, status=None, limit=50):
    """按时间倒序列出调用记录。"""
    cond = {}
    if kind:
        cond["kind"] = kind
    if status:
        cond["status"] = status
    rows = []
    for t in traces.find(cond).sort("created_at", -1).limit(int(limit)):
        t["_id"] = str(t["_id"])
        rows.append(t)
    return rows


def summary(days=7):
    """看板汇总：调用量、成功率、token、成本、平均延迟，以及按类型/模型/日期分组。"""
    since = _now() - timedelta(days=int(days))
    base = list(traces.find({"created_at": {"$gte": since}}))
    total = len(base)
    ok = sum(1 for t in base if t.get("status") == "ok")
    tokens = sum(t.get("total_tokens", 0) for t in base)
    cost = sum(t.get("cost_usd", 0) for t in base)
    lat = [t.get("latency_ms", 0) for t in base] or [0]

    by_kind, by_model, by_day = {}, {}, {}
    for t in base:
        k = t.get("kind", "other")
        g = by_kind.setdefault(k, {"calls": 0, "tokens": 0, "cost": 0.0})
        g["calls"] += 1
        g["tokens"] += t.get("total_tokens", 0)
        g["cost"] += t.get("cost_usd", 0)
        m = t.get("model", "unknown")
        by_model[m] = by_model.get(m, 0) + 1
        d = t.get("created_at")
        key = d.strftime("%Y-%m-%d") if d else "unknown"
        g2 = by_day.setdefault(key, {"calls": 0, "tokens": 0})
        g2["calls"] += 1
        g2["tokens"] += t.get("total_tokens", 0)

    for v in by_kind.values():
        v["cost"] = round(v["cost"], 6)
    return {
        "window_days": int(days),
        "calls": total,
        "success": ok,
        "errors": total - ok,
        "success_rate": round(ok / total, 4) if total else 0.0,
        "total_tokens": tokens,
        "cost_usd": round(cost, 6),
        "avg_latency_ms": round(sum(lat) / len(lat), 1),
        "by_kind": by_kind,
        "by_model": by_model,
        "by_day": dict(sorted(by_day.items())),
    }


def clear():
    """清空追踪记录。"""
    return traces.delete_many({}).deleted_count
