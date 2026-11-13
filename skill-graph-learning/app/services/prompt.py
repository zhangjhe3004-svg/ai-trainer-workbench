# -*- coding: utf-8 -*-
"""提示词工程服务：模板与版本管理、技巧库、变量渲染、试跑、A/B 对比、自动提示词生成。

覆盖工程实践中的：
- 系统 / 角色 / 上下文提示
- Zero-Shot / One-Shot / Few-Shot
- Chain of Thought / Self-Consistency / Tree of Thoughts / ReAct / Step-back
- Automatic Prompt Engineering（用模型生成提示词）
- 变量占位符、结构化输出、采样参数、提示词版本追踪与回归对比
"""
import json
import re
import time
from datetime import datetime, timezone

from bson import ObjectId

from db import prompts, prompt_versions
from services import llm, guardrail, trace


def _now():
    return datetime.now(timezone.utc)


# ============ 提示技巧库 ============
TECHNIQUES = {
    "zero_shot": {
        "name": "零样本提示 Zero-Shot", "group": "基础提示",
        "description": "直接给出任务指令，不提供示例，依赖模型自身能力。",
        "sampling": {"temperature": 0.3},
    },
    "one_shot": {
        "name": "单样本提示 One-Shot", "group": "示例学习",
        "description": "提供 1 个输入-输出示例，约束输出格式与风格。",
        "use_examples": 1, "sampling": {"temperature": 0.3},
    },
    "few_shot": {
        "name": "少样本提示 Few-Shot", "group": "示例学习",
        "description": "提供多个示例，让模型从演示中归纳任务模式。",
        "use_examples": 3, "sampling": {"temperature": 0.3},
    },
    "cot": {
        "name": "思维链 CoT", "group": "推理增强",
        "description": "要求模型逐步推理再给结论，显著提升复杂推理准确率。",
        "user_suffix": "请一步一步思考，先写出推理过程，再给出最终答案。",
        "sampling": {"temperature": 0.2},
    },
    "self_consistency": {
        "name": "自一致性 Self-Consistency", "group": "推理增强",
        "description": "采样多条推理路径并投票，取最一致的答案。",
        "user_suffix": "请独立给出 3 条不同的推理路径，比较后投票选出最一致的答案。",
        "sampling": {"temperature": 0.8},
    },
    "tot": {
        "name": "思维树 ToT", "group": "推理增强",
        "description": "把问题拆成多个候选思路，逐一评估后选择最优分支。",
        "user_suffix": "请列出多个候选思路，分别评估可行性，再沿最优路径给出答案。",
        "sampling": {"temperature": 0.6},
    },
    "react": {
        "name": "ReAct 推理与行动", "group": "智能体",
        "description": "按 Thought / Action / Observation 循环推理，可与工具调用配合。",
        "system_extra": "请按 Thought（思考）、Action（行动）、Observation（观察）的循环逐步推进任务。",
        "sampling": {"temperature": 0.2},
    },
    "step_back": {
        "name": "回溯提问 Step-back", "group": "推理增强",
        "description": "先抽象出问题背后的通用原理，再回到具体问题作答。",
        "user_prefix": "请先抽象出该问题涉及的通用原理或核心概念，再回答具体问题。",
        "sampling": {"temperature": 0.3},
    },
    "system": {
        "name": "系统提示 System", "group": "角色与上下文",
        "description": "用 system 消息设定全局行为边界与输出规范。",
        "sampling": {"temperature": 0.4},
    },
    "role": {
        "name": "角色提示 Role", "group": "角色与上下文",
        "description": "为模型指定专家身份，约束语气、深度与表达方式。",
        "system_extra": "请以该领域资深专家的身份作答，使用专业、准确、简洁的表达。",
        "sampling": {"temperature": 0.5},
    },
    "contextual": {
        "name": "上下文提示 Contextual", "group": "角色与上下文",
        "description": "把给定资料作为唯一事实来源，抑制幻觉。",
        "user_suffix": "请严格基于以上上下文作答，不要引入未给出的事实；资料不足时如实说明。",
        "sampling": {"temperature": 0.1},
    },
    "ape": {
        "name": "自动提示词生成 APE", "group": "自动优化",
        "description": "让模型自动生成并筛选候选提示词，再沉淀为模板。",
        "sampling": {"temperature": 0.9},
    },
}


def list_techniques():
    out = []
    for key, t in TECHNIQUES.items():
        row = dict(t)
        row["key"] = key
        out.append(row)
    return out


# ============ 变量与渲染 ============
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def extract_variables(*texts):
    """从一段或多段文本中提取 {{变量}} 名。"""
    names = []
    for t in texts:
        for n in _VAR_RE.findall(t or ""):
            if n not in names:
                names.append(n)
    return names


def _substitute(text, variables):
    variables = variables or {}
    missing = []

    def _rep(m):
        key = m.group(1)
        if key in variables and variables[key] is not None:
            return str(variables[key])
        missing.append(key)
        return m.group(0)

    return _VAR_RE.sub(_rep, text or ""), missing


def build_messages(tpl, variables=None, technique=None):
    """把模板渲染为 LLM messages，并应用指定提示技巧。

    返回 {"messages", "variables", "missing", "technique"}。
    """
    tech_key = technique or tpl.get("technique") or "zero_shot"
    cfg = TECHNIQUES.get(tech_key, TECHNIQUES["zero_shot"])
    variables = variables or {}

    system, m1 = _substitute(tpl.get("system_prompt", ""), variables)
    body, m2 = _substitute(tpl.get("content", ""), variables)

    if cfg.get("system_extra"):
        system = (system + "\n" + cfg["system_extra"]).strip()
    if cfg.get("user_prefix"):
        body = cfg["user_prefix"] + "\n\n" + body

    n = cfg.get("use_examples", 0)
    examples = (tpl.get("examples") or [])[:n] if n else []
    if examples:
        blocks = []
        for i, ex in enumerate(examples, 1):
            blocks.append("示例 %d\n输入：%s\n输出：%s" %
                          (i, ex.get("input", ""), ex.get("output", "")))
        body = "请参考以下示例：\n\n" + "\n\n".join(blocks) + "\n\n现在请处理：\n" + body

    if cfg.get("user_suffix"):
        body = body + "\n\n" + cfg["user_suffix"]

    messages = []
    if system.strip():
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": body})

    missing = []
    for x in m1 + m2:
        if x not in missing:
            missing.append(x)
    return {
        "messages": messages,
        "variables": extract_variables(tpl.get("system_prompt", ""), tpl.get("content", "")),
        "missing": missing,
        "technique": tech_key,
    }


# ============ 模板 CRUD ============
def _serialize(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


def list_prompts(keyword=None, technique=None, page=1, size=50):
    cond = {}
    if keyword:
        cond["$or"] = [{"name": {"$regex": keyword, "$options": "i"}},
                       {"description": {"$regex": keyword, "$options": "i"}}]
    if technique:
        cond["technique"] = technique
    skip = (int(page) - 1) * int(size)
    cur = prompts.find(cond).sort("created_at", -1).skip(skip).limit(int(size))
    rows = [_serialize(p) for p in cur]
    return {"rows": rows, "total": prompts.count_documents(cond), "page": int(page), "size": int(size)}


def get_prompt(pid):
    return _serialize(prompts.find_one({"_id": ObjectId(pid)}))


def create_prompt(name, content, system_prompt="", technique="zero_shot",
                  description="", examples=None, sampling=None,
                  json_schema=None, tags=None, note="创建模板"):
    """创建提示词模板并写入 v1 版本快照。"""
    if not name or not content:
        raise ValueError("模板名称与正文不能为空")
    if technique not in TECHNIQUES:
        raise ValueError("不支持的提示技巧：" + str(technique))
    if prompts.find_one({"name": name}):
        raise ValueError("模板名称已存在：" + name)

    samp = dict(llm.SAMPLING_DEFAULTS)
    samp.update(TECHNIQUES[technique].get("sampling", {}))
    samp.update(sampling or {})

    doc = {
        "name": name,
        "description": description or "",
        "technique": technique,
        "technique_label": TECHNIQUES[technique]["name"],
        "system_prompt": system_prompt or "",
        "content": content,
        "variables": extract_variables(system_prompt, content),
        "examples": examples or [],
        "sampling": samp,
        "json_schema": json_schema,
        "tags": tags or [],
        "version": 1,
        "created_at": _now(),
        "updated_at": _now(),
    }
    pid = prompts.insert_one(doc).inserted_id
    _write_version(pid, doc, 1, note)
    return str(pid)


def _write_version(pid, snapshot, version, note=""):
    snap = dict(snapshot)
    snap.pop("_id", None)
    return str(prompt_versions.insert_one({
        "prompt_id": pid,
        "version": int(version),
        "snapshot": snap,
        "note": note or "",
        "created_at": _now(),
    }).inserted_id)


def update_prompt(pid, fields=None, note="更新模板"):
    """更新模板并自动生成新版本快照（可回溯）。"""
    p = prompts.find_one({"_id": ObjectId(pid)})
    if not p:
        raise ValueError("模板不存在")
    fields = fields or {}
    allowed = ["name", "description", "technique", "system_prompt", "content",
               "examples", "sampling", "json_schema", "tags"]
    changes = {k: v for k, v in fields.items() if k in allowed}
    if "technique" in changes and changes["technique"] not in TECHNIQUES:
        raise ValueError("不支持的提示技巧")
    merged = dict(p)
    merged.update(changes)
    if "technique" in changes:
        merged["technique_label"] = TECHNIQUES[changes["technique"]]["name"]
    if "sampling" in changes:
        s = dict(p.get("sampling") or llm.SAMPLING_DEFAULTS)
        s.update(changes["sampling"] or {})
        merged["sampling"] = s
    merged["variables"] = extract_variables(merged.get("system_prompt", ""), merged.get("content", ""))
    merged["version"] = int(p.get("version", 1)) + 1
    merged["updated_at"] = _now()
    for k in ("_id",):
        merged.pop(k, None)
    prompts.update_one({"_id": ObjectId(pid)}, {"$set": merged})
    _write_version(ObjectId(pid), merged, merged["version"], note)
    return merged["version"]


def delete_prompt(pid):
    r = prompts.delete_one({"_id": ObjectId(pid)})
    if r.deleted_count == 0:
        raise ValueError("模板不存在")
    prompt_versions.delete_many({"prompt_id": ObjectId(pid)})
    return True


# ============ 版本管理 ============
def list_versions(pid):
    rows = []
    for v in prompt_versions.find({"prompt_id": ObjectId(pid)}).sort("version", -1):
        v["_id"] = str(v["_id"])
        v["prompt_id"] = str(v["prompt_id"])
        rows.append(v)
    return rows


def get_version(vid):
    v = prompt_versions.find_one({"_id": ObjectId(vid)})
    if not v:
        raise ValueError("版本不存在")
    v["_id"] = str(v["_id"])
    v["prompt_id"] = str(v["prompt_id"])
    return v


def restore_version(pid, vid):
    """把模板回滚到指定版本（回滚本身也生成一个新版本）。"""
    v = get_version(vid)
    snap = dict(v["snapshot"])
    allowed = ["name", "description", "technique", "system_prompt", "content",
               "examples", "sampling", "json_schema", "tags"]
    fields = {k: snap[k] for k in allowed if k in snap}
    return update_prompt(pid, fields, note="回滚自 v%s" % v["version"])


# ============ 预览 / 试跑 / A/B ============
def preview(pid, variables=None, technique=None):
    p = get_prompt(pid)
    if not p:
        raise ValueError("模板不存在")
    r = build_messages(p, variables, technique)
    r["name"] = p["name"]
    r["sampling"] = p.get("sampling", {})
    r["json_schema"] = p.get("json_schema")
    return r


def run_prompt(pid, variables=None, technique=None, guard=False, save_trace=True):
    """试跑模板：渲染 → 可选护栏 → LLM 调用 → 记录追踪。"""
    p = get_prompt(pid)
    if not p:
        raise ValueError("模板不存在")
    r = build_messages(p, variables, technique)
    user_text = r["messages"][-1]["content"]
    guard_result = None
    if guard:
        guard_result = guardrail.scan(user_text)
        if guard_result["action"] == "block":
            if save_trace:
                trace.record("prompt", model=p["name"], status="blocked",
                             ref_id=pid, note=";".join(guard_result["reasons"]))
            return {"blocked": True, "guard": guard_result, "content": "",
                    "messages": r["messages"]}
        # 脱敏后的文本替换进最后一条消息
        r["messages"][-1]["content"] = guard_result["clean_text"]

    params = dict(p.get("sampling") or {})
    tech_cfg = TECHNIQUES.get(r["technique"], {})
    for k, v in tech_cfg.get("sampling", {}).items():
        params.setdefault(k, v)

    start = time.time()
    try:
        res = llm.chat_full(r["messages"], params=params,
                            json_schema=p.get("json_schema"))
        status, error = "ok", ""
    except Exception as e:
        res = {"content": "调用失败：" + str(e), "backend": "error",
               "model": "", "prompt_tokens": 0, "completion_tokens": 0,
               "total_tokens": 0, "cost_usd": 0, "simulated": True}
        status, error = "error", str(e)
    latency = int((time.time() - start) * 1000)

    if save_trace:
        trace.record("prompt", model=res.get("model", ""),
                     prompt_tokens=res.get("prompt_tokens", 0),
                     completion_tokens=res.get("completion_tokens", 0),
                     cost_usd=res.get("cost_usd", 0), latency_ms=latency,
                     status=status, backend=res.get("backend", ""),
                     ref_id=pid, note=p["name"], error=error)

    return {
        "blocked": False,
        "prompt_id": pid,
        "name": p["name"],
        "technique": r["technique"],
        "messages": r["messages"],
        "content": res["content"],
        "backend": res.get("backend"),
        "model": res.get("model"),
        "simulated": res.get("simulated", False),
        "tokens": res.get("total_tokens", 0),
        "cost_usd": res.get("cost_usd", 0),
        "latency_ms": latency,
        "status": status,
        "guard": guard_result,
        "error": error,
    }


def compare(pid_a, pid_b, variables=None):
    """A/B 对比两个模板（或同一模板的不同技巧），输出长度/耗时/token 差异。"""
    a = run_prompt(pid_a, variables)
    b = run_prompt(pid_b, variables)
    return {
        "a": a, "b": b,
        "delta": {
            "length": len(b.get("content", "")) - len(a.get("content", "")),
            "tokens": b.get("tokens", 0) - a.get("tokens", 0),
            "latency_ms": b.get("latency_ms", 0) - a.get("latency_ms", 0),
        },
        "recommend": "B" if (b.get("tokens", 0) > 0 and
                             b.get("latency_ms", 0) <= a.get("latency_ms", 0)) else "A",
    }


# ============ 自动提示词生成 APE ============
def auto_generate(task, n=3, constraints=""):
    """用模型生成候选提示词；无后端时返回内置候选，保证离线可用。"""
    n = max(1, min(int(n), 5))
    prompt = ("你是提示词工程专家。请为下面的任务生成 %d 个彼此风格不同的高质量提示词，"
              "每个提示词应包含明确的角色、指令、约束与输出格式。"
              "以 JSON 数组形式返回，每项含 title 与 content 两个字段。\n"
              "任务：%s\n附加约束：%s" % (n, task, constraints or "无"))
    schema = {"type": "array", "items": {"type": "object",
              "properties": {"title": {"type": "string"}, "content": {"type": "string"}}}}
    try:
        res = llm.chat_full([{"role": "user", "content": prompt}],
                            params={"temperature": 0.9}, json_schema=schema)
        if res.get("simulated"):
            raise RuntimeError("offline")
        raw = res["content"].strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[-1]
        data = json.loads(raw)
        candidates = [x for x in data if isinstance(x, dict) and x.get("content")][:n]
    except Exception:
        candidates = [
            {"title": "专家角色型", "content": "你是该领域资深专家。请针对「{{task}}」给出专业、结构化的回答，先结论后论据。"},
            {"title": "思维链型", "content": "请针对「{{task}}」逐步推理：先拆解关键要素，再逐项分析，最后给出结论。"},
            {"title": "少样本型", "content": "请参考以下示例的格式与风格，完成「{{task}}」：\n示例输入：...\n示例输出：..."},
            {"title": "结构化输出型", "content": "请处理「{{task}}」，只输出 JSON，字段包含 result、reason、confidence。"},
            {"title": "上下文约束型", "content": "请严格基于给定资料回答「{{task}}」，不得引入外部事实；资料不足时说明。"},
        ][:n]
    return {"task": task, "candidates": candidates,
            "count": len(candidates),
            "note": "可将任一候选直接保存为模板，再用 A/B 对比选出效果最好的版本。"}
