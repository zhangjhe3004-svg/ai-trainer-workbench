# -*- coding: utf-8 -*-
"""向量化与相似度自动分配服务。

职责：
1. 把知识库文档 / 数据集样本向量化，存入 vector_index 集合（对应 Vector DB）。
2. 基于余弦相似度，在「导入数据」时自动把内容分配到最相近的技能点 / 已有文档（自动归类）。
3. 提供相似度检索（RAG 召回）：给定查询，返回最相关的知识片段。

向量检索双通道：
- MongoDB Atlas：生产环境用 $vectorSearch 原生向量检索（需 Atlas 集群 + 向量索引）。
- 本地回退：在本地 MongoDB 上读取向量后，用 Python 算余弦相似度（零额外依赖）。

"""
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone

from bson import ObjectId

from db import vector_index, documents, datasets, skills
from services import llm


def _now():
    return datetime.now(timezone.utc)


# ============ 多模态内容类型 ============
CONTENT_TYPES = ["text", "image"]  # 向量索引支持文本与图片两种内容类型


# ============ 向量化入库 ============
def index_text(source_type, source_id, text, title="", extra=None):
    """把一段文本向量化并写入向量索引。

    source_type: 'document' / 'dataset' / 'question' / 'skill'
    source_id:   对应集合的 _id 字符串
    text:        要向量化的正文
    title:       标题（用于检索展示）
    extra:       附加信息（如 skill_id、dataset_id 等）

    返回向量索引文档 _id 字符串。
    """
    emb = llm.embed(text)
    vec = emb["vectors"][0]
    doc = {
        "source_type": source_type,
        "source_id": source_id,
        "title": title or "",
        "text": text,
        "embedding": vec,
        "dim": emb["dim"],
        "embed_backend": emb["backend"],
        "embed_model": emb["model"],
        "extra": extra or {},
        "created_at": _now(),
    }
    # 同一来源幂等：先删旧向量再插入
    vector_index.delete_many({"source_type": source_type, "source_id": source_id})
    return str(vector_index.insert_one(doc).inserted_id)


def index_document(doc_id):
    """向量化一篇知识库文档。"""
    d = documents.find_one({"_id": ObjectId(doc_id)})
    if not d:
        raise ValueError("文档不存在")
    text = (d.get("title", "") + "\n" + d.get("content", "")).strip()
    return index_text("document", doc_id, text, title=d.get("title", ""),
                      extra={"model_id": str(d["model_id"]) if d.get("model_id") else None})


# ============ 多模态：图片向量化 ============
def index_image(source_type, source_id, image_b64, caption="", title="", extra=None):
    """把一张图片向量化并写入向量索引（多模态）。

    图片向量化策略：用图片的文本描述（caption）或文件名做语义向量，
    同时保存图片 base64 供检索命中后展示。离线时用 caption + 图片字节的哈希投影兜底。

    返回向量索引文档 _id 字符串。
    """
    # 语义向量：优先用 caption（图片文字描述），无 caption 时用 title
    semantic_text = (caption or title or "").strip()
    if not semantic_text:
        # 用图片 base64 的哈希做兜底向量（无语义，但保证可检索）
        semantic_text = image_b64[:200] if image_b64 else ""
    emb = llm.embed(semantic_text or "image")
    vec = emb["vectors"][0]
    doc = {
        "source_type": source_type,
        "source_id": source_id,
        "content_type": "image",
        "title": title or caption or "",
        "text": caption or "",
        "image_b64": image_b64,
        "image_mime": extra.get("mime", "image/jpeg") if extra else "image/jpeg",
        "embedding": vec,
        "dim": emb["dim"],
        "embed_backend": emb["backend"],
        "embed_model": emb["model"],
        "extra": extra or {},
        "created_at": _now(),
    }
    # 同一来源幂等：先删旧向量再插入
    vector_index.delete_many({"source_type": source_type, "source_id": source_id})
    return str(vector_index.insert_one(doc).inserted_id)


def index_all_documents():
    """批量向量化所有知识库文档（初始化/重建向量库）。"""
    count = 0
    for d in documents.find({}):
        try:
            index_document(str(d["_id"]))
            count += 1
        except Exception:
            continue
    return count


# ============ 相似度计算与自动分配 ============
_skill_anchor_cache = {"ts": None, "anchors": []}


def _skill_vectors(force=False):
    """获取所有模型技能（skill）的「锚向量」，用于自动归类。

    带进程内缓存，避免每次归类都重新生成所有技能向量。
    返回 list[{"skill_id": str, "title": str, "vec": [...]}]
    """
    if not force and _skill_anchor_cache["anchors"]:
        return _skill_anchor_cache["anchors"]

    anchors = []
    for sk in skills.find({}):
        sid = str(sk["_id"])
        title = sk.get("name", "")
        category = sk.get("category", "")
        desc = sk.get("description", "")
        text = f"{title} {category} {desc}".strip()
        # 优先用已索引向量
        cached = vector_index.find_one({"source_type": "skill", "source_id": sid})
        if cached and cached.get("embedding"):
            vec = cached["embedding"]
        else:
            vec = llm.embed(text)["vectors"][0]
        anchors.append({"skill_id": sid, "title": title, "vec": vec})

    _skill_anchor_cache["anchors"] = anchors
    return anchors


def index_all_skills():
    """批量向量化所有模型技能（作为自动归类的锚点）。"""
    count = 0
    for sk in skills.find({}):
        sid = str(sk["_id"])
        title = sk.get("name", "")
        category = sk.get("category", "")
        desc = sk.get("description", "")
        text = f"{title} {category} {desc}".strip()
        try:
            index_text("skill", sid, text, title=title,
                       extra={"category": category})
            count += 1
        except Exception:
            continue
    _skill_anchor_cache["anchors"] = []  # 失效缓存
    return count


def auto_assign_skill(text, top_k=3):
    """根据文本内容，自动匹配最相近的技能点（相似度分配）。

    返回 [{"skill_id", "title", "score"}, ...]，按相似度降序，最多 top_k 个。
    """
    anchors = _skill_vectors()
    if not anchors:
        return []
    qvec = llm.embed(text)["vectors"][0]
    scored = []
    for a in anchors:
        s = llm.cosine(qvec, a["vec"])
        scored.append({"skill_id": a["skill_id"], "title": a["title"], "score": round(s, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def assign_document_skill(doc_id, auto=True):
    """为一篇文档自动归类到最相近的模型技能（更新其 skill_id 标记）。

    若 auto=True 且文档未指定技能，则按相似度自动归到最相近的技能。
    返回匹配结果列表。
    """
    d = documents.find_one({"_id": ObjectId(doc_id)})
    if not d:
        raise ValueError("文档不存在")
    text = (d.get("title", "") + " " + d.get("content", "")).strip()
    matches = auto_assign_skill(text, top_k=1)
    if matches:
        best = matches[0]
        if best["score"] >= 0.0:  # 始终归到最相近
            documents.update_one({"_id": ObjectId(doc_id)},
                                 {"$set": {"auto_assigned": True,
                                           "assign_skill_id": best["skill_id"],
                                           "assign_score": best["score"]}})
    return matches


def assign_dataset_skill(dataset_id):
    """为数据集内的样本批量自动归类（统计每类样本最相近技能分布）。"""
    ds = datasets.find_one({"_id": ObjectId(dataset_id)})
    if not ds:
        raise ValueError("数据集不存在")
    samples = ds.get("samples", [])
    anchors = _skill_vectors()
    stats = {}
    for s in samples[:20]:  # 最多取样 20 条避免过慢
        if isinstance(s, dict):
            text = " ".join(str(v) for v in s.values())[:500]
        else:
            text = str(s)[:500]
        qvec = llm.embed(text)["vectors"][0]
        best = None
        for a in anchors:
            score = llm.cosine(qvec, a["vec"])
            if best is None or score > best["score"]:
                best = {"skill_id": a["skill_id"], "score": score}
        if best:
            stats[best["skill_id"]] = stats.get(best["skill_id"], 0) + 1
    # 转为可读结果
    result = []
    for sid, cnt in sorted(stats.items(), key=lambda x: -x[1]):
        sk = skills.find_one({"_id": ObjectId(sid)}, {"name": 1})
        result.append({"skill_id": sid, "title": sk["name"] if sk else None, "count": cnt})
    return result


# ============ 相似度检索（RAG 召回，支持多模态） ============
def search_similar(query, limit=5, source_type=None, use_atlas=False, content_type=None):
    """相似度检索：返回与 query 最相关的知识片段（文本 + 图片）。

    content_type: None（全部）/ 'text' / 'image'
    use_atlas=True 时走 MongoDB Atlas $vectorSearch（需集群支持），
    否则本地读取向量算余弦相似度。
    """
    qvec = llm.embed(query)["vectors"][0]

    if use_atlas:
        return _search_atlas(qvec, limit, source_type)

    # 本地余弦回退
    cond = {}
    if source_type:
        cond["source_type"] = source_type
    if content_type:
        cond["content_type"] = content_type
    rows = []
    for v in vector_index.find(cond, {"embedding": 1, "title": 1, "text": 1,
                                      "content_type": 1, "image_b64": 1, "image_mime": 1,
                                      "source_type": 1, "source_id": 1, "extra": 1}):
        if not v.get("embedding"):
            continue
        score = llm.cosine(qvec, v["embedding"])
        row = {
            "source_type": v["source_type"],
            "source_id": v["source_id"],
            "content_type": v.get("content_type", "text"),
            "title": v.get("title", ""),
            "text": (v.get("text", "") or "")[:300],
            "score": round(score, 4),
            "extra": v.get("extra", {}),
        }
        # 图片内容附带 base64 供前端展示
        if v.get("content_type") == "image" and v.get("image_b64"):
            row["image"] = f"data:{v.get('image_mime', 'image/jpeg')};base64,{v['image_b64']}"
        rows.append(row)
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:limit]


def _search_atlas(qvec, limit, source_type):
    """MongoDB Atlas 原生向量检索（生产环境）。

    需先在 Atlas 对 vector_index.embedding 建立 knnVector 索引：
    {
      "mappings": {"dynamic": true, "fields": {"embedding": {
        "type": "knnVector", "dimensions": 1536, "similarity": "cosine"}}}
    }
    """
    pipeline = [
        {"$vectorSearch": {
            "index": "vector_idx",
            "path": "embedding",
            "queryVector": qvec,
            "numCandidates": limit * 10,
            "limit": limit,
        }},
        {"$project": {"embedding": 0}},
    ]
    if source_type:
        pipeline.insert(0, {"$match": {"source_type": source_type}})
    rows = []
    for v in vector_index.aggregate(pipeline):
        rows.append({
            "source_type": v["source_type"],
            "source_id": v["source_id"],
            "title": v.get("title", ""),
            "text": (v.get("text", "") or "")[:300],
            "score": round(v.get("score", 0.0), 4),
            "extra": v.get("extra", {}),
        })
    return rows


# ============ RAG 问答 ============
def rag_chat(question, history=None, top_k=5):
    """基于知识库的 RAG 问答：先检索相关片段，再交给 LLM 生成回答。

    支持多模态：检索到的图片片段会附带描述（text/caption）进入上下文，
    返回的 sources 中带 image（base64 data URL）供前端展示。

    返回 {"answer", "backend", "model", "sources": [...]}。
    """
    sources = search_similar(question, limit=top_k)
    context_parts = []
    for i, s in enumerate(sources):
        if s.get("content_type") == "image":
            context_parts.append(f"[{i+1}] [图片] {s['title'] or '未命名'}: {s['text'] or '（图片，无文字描述）'}")
        else:
            context_parts.append(f"[{i+1}] {s['title'] or '未命名'}: {s['text']}")
    context = "\n\n".join(context_parts)

    system = (
        "你是一个基于多模态知识库的智能助手。请根据下面提供的【参考资料】回答用户问题。"
        "资料可能包含文本片段和图片描述。"
        "若资料不足以回答，请如实说明，不要编造。\n\n"
        f"【参考资料】\n{context or '（暂无相关资料）'}"
    )
    messages = [{"role": "system", "content": system}]
    if history:
        messages += history
    messages.append({"role": "user", "content": question})

    res = llm.chat(messages)
    return {
        "answer": res["content"],
        "backend": res["backend"],
        "model": res["model"],
        "sources": sources,
    }


def save_conversation(conversation_id, role, content, meta=None):
    """保存 LLM 对话历史。"""
    from db import llm_conversations
    return str(llm_conversations.insert_one({
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "meta": meta or {},
        "created_at": _now(),
    }).inserted_id)


def list_conversations(conversation_id, limit=50):
    from db import llm_conversations
    cur = llm_conversations.find({"conversation_id": conversation_id},
                                 {"_id": 0, "role": 1, "content": 1, "created_at": 1}) \
        .sort("created_at", 1).limit(limit)
    return list(cur)


# ============ RAG 进阶：分块 / 混合检索 / 查询重写 / 重排 / 溯源 ============
CHUNK_STRATEGIES = {
    "fixed": {"name": "固定长度分块", "description": "按固定字符数切分，可设重叠，简单稳定。"},
    "paragraph": {"name": "段落分块", "description": "按空行/换行切分，保留语义完整性。"},
    "recursive": {"name": "递归字符分块", "description": "依次按段落、句子、字符递归切分，兼顾长度与语义。"},
    "sentence": {"name": "句子分块", "description": "按中文句号/问号/感叹号切分。"},
}


def list_chunk_strategies():
    return [dict(v, key=k) for k, v in CHUNK_STRATEGIES.items()]


def chunk_text(text, strategy="recursive", size=400, overlap=50):
    """把长文本切成知识片段，返回 [{"index", "text", "length"}]。"""
    text = (text or "").strip()
    if not text:
        return []
    if strategy not in CHUNK_STRATEGIES:
        raise ValueError("不支持的分块策略：" + str(strategy))
    size, overlap = max(50, int(size)), max(0, int(overlap))

    if strategy == "paragraph":
        units = [u.strip() for u in re.split(r"\n\s*\n|\n", text) if u.strip()]
    elif strategy == "sentence":
        units = [u.strip() for u in re.split(r"(?<=[。！？!?.;；])", text) if u.strip()]
    elif strategy == "fixed":
        step = max(1, size - overlap)
        return [{"index": i, "text": text[s:s + size], "length": len(text[s:s + size])}
                for i, s in enumerate(range(0, len(text), step))]
    else:  # recursive：先段落，再句子，最后按长度兜底
        paras = [u.strip() for u in re.split(r"\n\s*\n|\n", text) if u.strip()]
        units = []
        for p in paras:
            if len(p) <= size:
                units.append(p)
            else:
                sents = [x.strip() for x in re.split(r"(?<=[。！？!?.;；])", p) if x.strip()]
                buf = ""
                for s in sents:
                    if len(buf) + len(s) <= size:
                        buf += s
                    else:
                        if buf:
                            units.append(buf)
                        while len(s) > size:
                            units.append(s[:size])
                            s = s[size - overlap:]
                        buf = s
                if buf:
                    units.append(buf)

    merged, buf = [], ""
    for u in units:
        if len(buf) + len(u) <= size:
            buf += u
        else:
            if buf:
                merged.append(buf)
            buf = u[-size:] if len(u) > size else u
    if buf:
        merged.append(buf)
    return [{"index": i, "text": t, "length": len(t)} for i, t in enumerate(merged)]


def _tokenize(text):
    """轻量分词：中文单字 + 英文/数字词。"""
    return re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", (text or "").lower())


def bm25_scores(query, docs, k1=1.5, b=0.75):
    """标准 BM25 打分（纯 Python，无额外依赖）。"""
    if not docs:
        return []
    tokenized = [_tokenize(d) for d in docs]
    q_terms = _tokenize(query)
    avgdl = sum(len(t) for t in tokenized) / len(tokenized) or 1.0
    n = len(docs)
    out = []
    for t in tokenized:
        tf, dl, s = Counter(t), len(t), 0.0
        for q in q_terms:
            f = tf.get(q, 0)
            if not f:
                continue
            df = sum(1 for x in tokenized if q in x)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        out.append(round(s, 6))
    return out


def _all_vector_rows(content_type=None, source_type=None):
    cond = {}
    if content_type:
        cond["content_type"] = content_type
    if source_type:
        cond["source_type"] = source_type
    rows = []
    for v in vector_index.find(cond, {"embedding": 1, "title": 1, "text": 1,
                                      "content_type": 1, "image_b64": 1, "image_mime": 1,
                                      "source_type": 1, "source_id": 1, "extra": 1}):
        row = {
            "source_type": v.get("source_type", ""),
            "source_id": v.get("source_id", ""),
            "content_type": v.get("content_type", "text"),
            "title": v.get("title", ""),
            "text": (v.get("text", "") or "")[:400],
            "extra": v.get("extra", {}),
            "embedding": v.get("embedding"),
        }
        if row["content_type"] == "image" and v.get("image_b64"):
            row["image"] = f"data:{v.get('image_mime', 'image/jpeg')};base64,{v['image_b64']}"
        rows.append(row)
    return rows


def hybrid_search(query, limit=5, alpha=0.5, content_type=None):
    """混合检索：向量余弦 + BM25 关键词，用 RRF 倒数排名融合。

    alpha: 向量通道权重（0~1）。返回按融合分数排序的结果，附带各通道分数。
    """
    rows = _all_vector_rows(content_type)
    if not rows:
        return []
    qvec = llm.embed(query)["vectors"][0]
    vec_scores = [llm.cosine(qvec, r["embedding"]) if r.get("embedding") else 0.0
                  for r in rows]
    kw_scores = bm25_scores(query, [r["title"] + " " + r["text"] for r in rows])

    vec_order = sorted(range(len(rows)), key=lambda i: vec_scores[i], reverse=True)
    kw_order = sorted(range(len(rows)), key=lambda i: kw_scores[i], reverse=True)
    vec_rank = {idx: rk for rk, idx in enumerate(vec_order)}
    kw_rank = {idx: rk for rk, idx in enumerate(kw_order)}

    out = []
    for i, r in enumerate(rows):
        fused = alpha / (60 + vec_rank[i]) + (1 - alpha) / (60 + kw_rank[i])
        item = {k: v for k, v in r.items() if k != "embedding"}
        item["score"] = round(fused, 6)
        item["vector_score"] = round(vec_scores[i], 4)
        item["bm25_score"] = round(kw_scores[i], 4)
        out.append(item)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:int(limit)]


def rewrite_query(question, n=2):
    """查询重写：生成更利于检索的改写/扩展查询；无 LLM 时做规则扩展。"""
    try:
        res = llm.chat_full([
            {"role": "system", "content": "你是检索查询改写助手。请给出 %d 个更利于知识检索的改写查询，只输出 JSON 数组字符串。" % n},
            {"role": "user", "content": question},
        ], params={"temperature": 0.3},
            json_schema={"type": "array", "items": {"type": "string"}})
        if res.get("simulated"):
            raise RuntimeError("offline")
        raw = res["content"].strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[-1]
        data = json.loads(raw)
        variants = [str(x) for x in data if x][:n]
        if variants:
            return {"original": question, "variants": variants, "source": "llm"}
    except Exception:
        pass
    return {
        "original": question,
        "variants": [question + " 原理 说明", question + " 如何 实现"][:n],
        "source": "rule",
    }


def rerank(query, results, limit=5):
    """重排序：把原检索分归一化后，与查询词覆盖率做加权融合（0.6 / 0.4）。"""
    terms = set(_tokenize(query))
    base = [max(0.0, float(r.get("score", 0.0))) for r in results]
    hi = max(base) if base else 0.0
    if hi <= 0:
        hi = 1.0
    out = []
    for r, s in zip(results, base):
        text = (r.get("title", "") + " " + r.get("text", ""))
        toks = set(_tokenize(text))
        cover = len(terms & toks) / len(terms) if terms else 0.0
        item = dict(r)
        item["rerank_score"] = round(0.6 * (s / hi) + 0.4 * cover, 6)
        item["term_coverage"] = round(cover, 4)
        out.append(item)
    out.sort(key=lambda x: x["rerank_score"], reverse=True)
    return out[:int(limit)]


def rag_chat_advanced(question, top_k=5, strategy="hybrid", do_rewrite=False,
                      do_rerank=True, history=None):
    """进阶 RAG：查询重写 → 混合检索 → 重排序 → 带引用编号生成 → 答案溯源。"""
    rewritten = rewrite_query(question) if do_rewrite else {
        "original": question, "variants": [], "source": "off"}
    probe = rewritten["variants"][0] if rewritten["variants"] else question
    if strategy == "hybrid":
        hits = hybrid_search(probe, limit=max(int(top_k) * 2, int(top_k)))
    else:
        hits = search_similar(probe, limit=max(int(top_k) * 2, int(top_k)))
    if do_rerank:
        hits = rerank(question, hits, limit=int(top_k))
    else:
        hits = hits[:int(top_k)]

    parts = []
    for i, s in enumerate(hits, 1):
        tag = "[图片] " if s.get("content_type") == "image" else ""
        parts.append("[%d] %s%s: %s" % (i, tag, s.get("title") or "未命名",
                                        s.get("text") or "（无文字描述）"))
    context = "\n\n".join(parts)
    system = (
        "你是基于知识库回答的助手。请严格依据【参考资料】作答，并在引用处标注编号如 [1]。"
        "资料不足时如实说明，不要编造。\n\n【参考资料】\n" + (context or "（暂无相关资料）")
    )
    messages = [{"role": "system", "content": system}]
    if history:
        messages += history
    messages.append({"role": "user", "content": question})
    res = llm.chat_full(messages, params={"temperature": 0.2})

    cited = set()
    for m in re.findall(r"\[(\d+)\]", res["content"]):
        try:
            k = int(m)
            if 1 <= k <= len(hits):
                cited.add(k)
        except ValueError:
            pass
    if not cited:
        cited = set(range(1, min(3, len(hits)) + 1))
    citations = [{
        "index": i, "title": hits[i - 1].get("title", ""),
        "content_type": hits[i - 1].get("content_type", "text"),
        "snippet": (hits[i - 1].get("text") or "")[:160],
        "score": hits[i - 1].get("score", 0),
    } for i in sorted(cited)]

    try:
        from services import trace
        trace.record("rag", model=res.get("model", ""),
                     prompt_tokens=res.get("prompt_tokens", 0),
                     completion_tokens=res.get("completion_tokens", 0),
                     cost_usd=res.get("cost_usd", 0),
                     status="ok", backend=res.get("backend", ""),
                     note="strategy=%s" % strategy)
    except Exception:
        pass

    return {
        "answer": res["content"], "backend": res.get("backend"),
        "model": res.get("model"), "simulated": res.get("simulated", False),
        "sources": hits, "citations": citations,
        "rewritten_query": rewritten, "strategy": strategy,
        "tokens": res.get("total_tokens", 0), "cost_usd": res.get("cost_usd", 0),
    }

