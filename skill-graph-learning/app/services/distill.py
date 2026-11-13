# -*- coding: utf-8 -*-
"""知识蒸馏（简化版）：聊天记录 + 图片 → 一键生成蒸馏样本与训练数据。

设计目标：把原本分散在「数据集导入 / 知识库 / 训练运行」的链路收拢为一次调用，
前端只需上传聊天记录与图片、选一个模式，即可在当前页完成蒸馏、落库、可选训练。

支持的聊天记录格式：JSON / JSONL / CSV / TXT（自动识别）
支持的图片：base64（自动写入多模态向量库并生成图文样本）
"""
import csv
import io
import json
import re
import time
from datetime import datetime, timezone

from bson import ObjectId

from db import datasets, distill_runs, training_runs, models


def _now():
    return datetime.now(timezone.utc)


MODES = {
    "quick": {"name": "快速蒸馏", "description": "直接抽取对话问答与图片描述，速度最快，无需外部模型。"},
    "enhanced": {"name": "教师增强", "description": "在快速蒸馏基础上，调用教师模型重写参考答案（未连接模型时自动回退）。"},
}

SUPPORTED_FORMATS = [".json", ".jsonl", ".csv", ".txt", ".log"]

USER_KEYS = ("input", "question", "prompt", "query", "instruction", "q", "user", "用户", "问题")
ASSIST_KEYS = ("output", "answer", "response", "completion", "target", "a", "assistant", "助手", "回答")
USER_ROLES = {"user", "human", "q", "question", "用户", "人工"}
ASSIST_ROLES = {"assistant", "ai", "bot", "gpt", "a", "answer", "助手", "客服"}

_ROLE_RE = re.compile(r"^\s*(用户|助手|人工|客服|User|Assistant|Human|AI|Q|A|Question|Answer)\s*[:：]\s*(.+)$", re.I)


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _text_of(m):
    t = m.get("content") or m.get("text") or m.get("value") or ""
    if isinstance(t, list):
        t = " ".join(str(x.get("text", "")) for x in t if isinstance(x, dict))
    return str(t).strip()


def _from_messages(msgs, out):
    pending = None
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or m.get("from") or "").lower()
        text = _text_of(m)
        if not text:
            continue
        if role in USER_ROLES:
            pending = text
        elif role in ASSIST_ROLES and pending:
            out.append({"input": pending, "output": text, "kind": "chat"})
            pending = None


def _from_record(obj, out):
    if isinstance(obj, dict):
        for key in ("messages", "conversation", "dialog", "chat", "turns"):
            if isinstance(obj.get(key), list) and obj[key]:
                _from_messages(obj[key], out)
                return
        q = _first(obj, USER_KEYS)
        a = _first(obj, ASSIST_KEYS)
        if q and a:
            out.append({"input": q, "output": a, "kind": "chat"})
    elif isinstance(obj, str) and obj.strip():
        out.append({"input": obj.strip(), "output": "", "kind": "text"})


def _parse_text(content):
    out, pending, has_role = [], None, False
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    for line in lines:
        m = _ROLE_RE.match(line)
        if not m:
            if pending is None:
                pending = line
            else:
                pending += "\n" + line
            continue
        has_role = True
        role, text = m.group(1).lower(), m.group(2).strip()
        if role in USER_ROLES:
            if pending and out:
                out[-1]["output"] += "\n" + pending
            pending = text
        elif role in ASSIST_ROLES and pending:
            out.append({"input": pending, "output": text, "kind": "chat"})
            pending = None
    if not has_role:
        # 无角色标记：按相邻两行组成问答对
        return [{"input": lines[i], "output": lines[i + 1], "kind": "chat"}
                for i in range(0, len(lines) - 1, 2)]
    if pending and out:
        out[-1]["output"] += "\n" + pending
    return out


def _parse_csv(content):
    out = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        low = {str(k).lower(): (v or "") for k, v in row.items() if k}
        q = _first(low, USER_KEYS)
        a = _first(low, ASSIST_KEYS)
        if q or a:
            out.append({"input": q, "output": a, "kind": "chat"})
    return out


def parse_chat(content, filename="", limit=500):
    """解析聊天记录，返回问答样本列表。纯函数，可离线单测。"""
    content = (content or "").strip()
    lower = (filename or "").lower()
    fmt, out, warning = "txt", [], ""

    if lower.endswith(".csv"):
        fmt = "csv"
        out = _parse_csv(content)
    elif lower.endswith(".jsonl") or (content.startswith("{") and "\n" in content
                                     and all(l.strip().startswith("{") for l in content.splitlines() if l.strip())):
        fmt = "jsonl"
        for line in content.splitlines():
            line = line.strip()
            if line:
                try:
                    _from_record(json.loads(line), out)
                except json.JSONDecodeError:
                    warning = "部分 JSONL 行格式有误，已跳过"
    elif lower.endswith(".json") or content.startswith(("[", "{")):
        fmt = "json"
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    _from_record(item, out)
            elif isinstance(data, dict):
                for key in ("data", "records", "items", "samples", "conversations"):
                    if isinstance(data.get(key), list):
                        for item in data[key]:
                            _from_record(item, out)
                        break
                else:
                    _from_record(data, out)
        except json.JSONDecodeError:
            out = _parse_text(content)
            fmt = "txt"
    else:
        out = _parse_text(content)

    # 只保留成对样本，并做长度裁剪
    pairs = [s for s in out if s.get("input") and s.get("output")][:int(limit)]
    return {"samples": pairs, "format": fmt, "raw_count": len(out),
            "warning": warning}


def preview(chat_text="", filename="", images=None, limit=500):
    """上传后预览：只解析不落库。"""
    r = parse_chat(chat_text, filename, limit)
    imgs = [{"name": (im.get("name") or "图片"), "mime": im.get("mime") or "image/jpeg",
             "b64": im.get("b64") or ""} for im in (images or [])]
    r["images"] = len(imgs)
    r["image_previews"] = [
        {"name": x["name"], "url": "data:%s;base64,%s" % (x["mime"], x["b64"])}
        for x in imgs[:6] if x["b64"]
    ]
    r["preview"] = r["samples"][:5]
    return r


def _image_samples(images, chat_count):
    """图片 → 图文样本 + 多模态向量库。返回 (样本, 已向量化数量)。"""
    out, indexed = [], 0
    for i, im in enumerate(images or []):
        b64 = im.get("b64") or ""
        if not b64:
            continue
        name = im.get("name") or ("图片 %d" % (i + 1))
        mime = im.get("mime") or "image/jpeg"
        caption = (im.get("caption") or "").strip() or ("[图片素材] %s" % name)
        try:
            from services import vector
            vector.index_image("distill", str(ObjectId()), b64,
                               caption=caption, title=name, extra={"mime": mime})
            indexed += 1
        except Exception:
            pass
        out.append({
            "input": "请描述图片内容并说明可用信息：%s" % name,
            "output": caption, "kind": "image", "has_image": True,
            "image_name": name, "image_mime": mime,
        })
    return out, indexed


def _teacher_enhance(samples, teacher_model, limit=20):
    """教师模型重写参考答案；未连接外部模型时保留原答案。"""
    from services import llm
    out = []
    for i, s in enumerate(samples):
        if i < limit and s.get("kind") == "chat":
            msgs = [
                {"role": "system", "content": "你是教师模型，请把下面的原始回答改写成更准确、结构清晰的参考答案，只输出答案本身。"},
                {"role": "user", "content": "问题：%s\n原始回答：%s" % (s["input"], s["output"])},
            ]
            try:
                r = llm.chat_full(msgs, params={"temperature": 0.3})
                if not r.get("simulated"):
                    s = dict(s, output=r["content"], teacher=teacher_model or "configured")
            except Exception:
                pass
        out.append(s)
    return out


def _write_dataset(name, samples, note):
    doc = {
        "name": name,
        "description": note,
        "dataset_type": "distilled",
        "samples": samples,
        "tags": ["蒸馏", "多模态"],
        "source": "distill",
        "created_at": _now(),
        "updated_at": _now(),
    }
    return str(datasets.insert_one(doc).inserted_id)


def run_distill(chat_text="", filename="", images=None, mode="quick",
                teacher_model="", dataset_name="", save_dataset=True,
                run_training=False, model_id=None, limit=500):
    """一键蒸馏：解析 → 图片向量化 → 可选教师增强 → 落库 → 可选训练 → 记录历史。"""
    if mode not in MODES:
        raise ValueError("不支持的蒸馏模式：" + str(mode))
    t0 = time.time()
    parsed = parse_chat(chat_text, filename, limit)
    chat_samples = parsed["samples"]
    img_samples, indexed = _image_samples(images or [], len(chat_samples))

    if not chat_samples and not img_samples:
        raise ValueError("未解析到可用内容，请检查聊天记录格式或上传图片")

    if mode == "enhanced":
        chat_samples = _teacher_enhance(chat_samples, teacher_model)

    samples = []
    for i, s in enumerate(chat_samples + img_samples):
        row = dict(s)
        row.setdefault("kind", "chat")
        row["index"] = i
        samples.append(row)

    name = (dataset_name or "").strip() or ("蒸馏数据 %s" % _now().strftime("%m%d-%H%M%S"))
    if datasets.find_one({"name": name}):
        name = name + "-" + str(ObjectId())[-5:]

    did = None
    if save_dataset or run_training:
        did = _write_dataset(name, samples,
                             "由知识蒸馏生成（%s 模式）" % MODES[mode]["name"])

    train_result = None
    if run_training:
        mid = model_id
        if not mid:
            m = models.find_one({}, {"_id": 1})
            mid = str(m["_id"]) if m else None
        if not mid:
            raise ValueError("执行训练需要模型，请先在页内选择模型")
        from services import finetune, training
        rid = finetune.create_finetune_run(
            name="蒸馏训练 · " + name, model_id=mid, dataset_id=did,
            method="distill",
            overrides={"teacher_model": teacher_model or "内置引擎",
                       "student_model": mid,
                       "distill_temperature": 2.0},
            mode="simulate", description="由知识蒸馏页直接发起")
        training.execute_run(rid)
        run = training_runs.find_one({"_id": ObjectId(rid)}) or {}
        train_result = {
            "run_id": rid,
            "status": run.get("status"),
            "progress": run.get("progress", 0),
            "metrics": run.get("metrics", {}),
        }

    result = {
        "mode": mode,
        "mode_label": MODES[mode]["name"],
        "format": parsed["format"],
        "chat_pairs": len(chat_samples),
        "image_count": len(images or []),
        "image_indexed": indexed,
        "sample_count": len(samples),
        "dataset_id": did,
        "dataset_name": name,
        "train": train_result,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "warning": parsed.get("warning", ""),
        "preview": [{k: v for k, v in s.items() if k != "image_b64"} for s in samples[:8]],
        "image_previews": [
            {"name": im.get("name") or "图片",
             "url": "data:%s;base64,%s" % (im.get("mime") or "image/jpeg", im.get("b64") or "")}
            for im in (images or [])[:6] if im.get("b64")
        ],
        "created_at": _now(),
    }
    rid = distill_runs.insert_one(dict(result)).inserted_id
    result["id"] = str(rid)
    return result


def list_runs(limit=50):
    rows = []
    for r in distill_runs.find({}, {"preview": 0, "image_previews": 0}) \
            .sort("created_at", -1).limit(int(limit)):
        r["_id"] = str(r["_id"])
        rows.append(r)
    return rows


def get_run(rid):
    r = distill_runs.find_one({"_id": ObjectId(rid)})
    if not r:
        raise ValueError("蒸馏记录不存在")
    r["_id"] = str(r["_id"])
    return r


def delete_run(rid):
    r = distill_runs.delete_one({"_id": ObjectId(rid)})
    if r.deleted_count == 0:
        raise ValueError("蒸馏记录不存在")
    return True
