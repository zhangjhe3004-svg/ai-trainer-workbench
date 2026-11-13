# -*- coding: utf-8 -*-
"""LLM 客户端适配层：统一封装 chat 补全与 embedding 生成。

支持两种后端，通过环境变量自动切换：
1. OpenAI 兼容接口（可对接 OpenAI / DeepSeek / 通义千问 / 智谱 / Moonshot 等绝大多数大模型）
   - LLM_API_BASE:  接口地址（默认 https://api.openai.com/v1）
   - LLM_API_KEY:   API Key
   - LLM_MODEL:     对话模型名（默认 gpt-4o-mini）
   - LLM_EMBED_MODEL: 向量模型名（默认 text-embedding-3-small）
2. 本地 Ollama
   - OLLAMA_BASE_URL: Ollama 服务地址（默认 http://127.0.0.1:11434）
   - OLLAMA_MODEL:  对话模型名（默认 qwen2.5:7b）
   - OLLAMA_EMBED_MODEL: 向量模型名（默认 nomic-embed-text）

embedding 生成策略：优先走 LLM 接口（OpenAI 兼容 / Ollama 的 embeddings），
失败时回退到本地「哈希投影」降级方案（无外部依赖时仍可运行）。

所有调用均通过 requests 直连 HTTP，无重依赖。
"""
import os
import hashlib
import math
import json

import requests

# ============ 后端探测 ============
LLM_API_BASE = os.environ.get("LLM_API_BASE", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "text-embedding-3-small")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# 本地回退向量维度（哈希投影）
FALLBACK_DIM = int(os.environ.get("LLM_FALLBACK_DIM", "256"))

TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))


def _has_openai():
    return bool(LLM_API_KEY)


_ollama_available = None  # 探测缓存：None=未探测，True/False=结果


def _has_ollama():
    global _ollama_available
    if _ollama_available is not None:
        return _ollama_available
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        _ollama_available = r.status_code == 200
    except requests.RequestException:
        _ollama_available = False
    return _ollama_available


def backend():
    """返回当前后端：'openai' / 'ollama' / None（均不可用）。"""
    if _has_openai():
        return "openai"
    if _has_ollama():
        return "ollama"
    return None


# ============ 对话补全 ============
def chat(messages, temperature=0.7, max_tokens=1024, stream=False):
    """对话补全。messages: [{"role": "system"/"user"/"assistant", "content": str}, ...]

    返回 {"content": str, "backend": str, "model": str}。
    """
    b = backend()
    if b == "openai":
        return _chat_openai(messages, temperature, max_tokens)
    if b == "ollama":
        return _chat_ollama(messages, temperature, max_tokens)
    raise RuntimeError(
        "未配置 LLM 后端。请设置 LLM_API_KEY（OpenAI 兼容）或启动本地 Ollama 服务，"
        "详见 README「LLM 接入」章节。")


def _chat_openai(messages, temperature, max_tokens):
    url = f"{LLM_API_BASE}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    return {"content": content, "backend": "openai", "model": LLM_MODEL}


def _chat_ollama(messages, temperature, max_tokens):
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    r = requests.post(url, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    content = data.get("message", {}).get("content", "")
    return {"content": content, "backend": "ollama", "model": OLLAMA_MODEL}


# ============ 多模态对话（文本 + 图片） ============
def chat_vision(prompt, image_b64=None, image_url=None, mime="image/jpeg",
                temperature=0.7, max_tokens=1024):
    """多模态对话：文本 + 图片输入，返回图片理解/描述。

    image_b64: 图片 base64（不含 data: 前缀）
    image_url: 图片 URL（与 image_b64 二选一）
    返回 {"content", "backend", "model"}。
    """
    b = backend()
    if b == "openai":
        return _chat_vision_openai(prompt, image_b64, image_url, mime, temperature, max_tokens)
    if b == "ollama":
        return _chat_vision_ollama(prompt, image_b64, temperature, max_tokens)
    raise RuntimeError(
        "未配置多模态 LLM 后端。图片理解需 OpenAI 兼容视觉模型或本地 Ollama（如 llava/qwen2-vl）。"
        "详见 README「LLM 接入」章节。")


def _chat_vision_openai(prompt, image_b64, image_url, mime, temperature, max_tokens):
    url = f"{LLM_API_BASE}/chat/completions"
    image_input = None
    if image_b64:
        image_input = {"type": "image_url",
                       "image_url": {"url": f"data:{mime};base64,{image_b64}"}}
    elif image_url:
        image_input = {"type": "image_url", "image_url": {"url": image_url}}
    content = [{"type": "text", "text": prompt}]
    if image_input:
        content.append(image_input)
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return {"content": data["choices"][0]["message"]["content"],
            "backend": "openai", "model": LLM_MODEL}


def _chat_vision_ollama(prompt, image_b64, temperature, max_tokens):
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    r = requests.post(url, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return {"content": data.get("message", {}).get("content", ""),
            "backend": "ollama", "model": OLLAMA_MODEL}


# ============ embedding 生成 ============
def embed(texts):
    """把一段或一批文本转为向量。

    texts: str 或 list[str]
    返回: {"vectors": list[list[float]], "backend": str, "model": str, "dim": int}

    策略：优先 OpenAI 兼容 /embeddings，其次 Ollama /api/embed，最后本地哈希投影兜底。
    """
    if isinstance(texts, str):
        single = True
        texts = [texts]
    else:
        single = False

    # 1) OpenAI 兼容接口
    if _has_openai():
        try:
            vecs = _embed_openai(texts)
            return {"vectors": vecs, "backend": "openai", "model": LLM_EMBED_MODEL,
                    "dim": len(vecs[0])}
        except Exception:
            pass  # 回退

    # 2) Ollama
    if _has_ollama():
        try:
            vecs = _embed_ollama(texts)
            return {"vectors": vecs, "backend": "ollama", "model": OLLAMA_EMBED_MODEL,
                    "dim": len(vecs[0])}
        except Exception:
            pass  # 回退

    # 3) 本地哈希投影兜底（离线可用）
    vecs = [_hash_embed(t) for t in texts]
    return {"vectors": vecs, "backend": "hash", "model": "hash-projection",
            "dim": FALLBACK_DIM}


def _embed_openai(texts):
    url = f"{LLM_API_BASE}/embeddings"
    payload = {"model": LLM_EMBED_MODEL, "input": texts}
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    data = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in data]


def _embed_ollama(texts):
    url = f"{OLLAMA_BASE_URL}/api/embed"
    vecs = []
    for t in texts:
        r = requests.post(url, json={"model": OLLAMA_EMBED_MODEL, "input": t}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        vecs.append(data["embeddings"][0])
    return vecs


def _hash_embed(text):
    """本地哈希投影：把文本映射为 FALLBACK_DIM 维归一化向量。

    用 n-gram 哈希做特征，保证语义相近的文本（共享词/字符）得到相近向量。
    这是本地降级实现，接入真实 embedding 模型后可获得更准确的语义检索。
    """
    dim = FALLBACK_DIM
    vec = [0.0] * dim
    text = text or ""
    # 字符 n-gram（1~3）
    for n in (1, 2, 3):
        for i in range(len(text) - n + 1):
            gram = text[i:i + n]
            h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
    # L2 归一化
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


# ============ 完整采样参数 / 结构化输出 / 成本估算 ============
# 对应提示词工程中的 LLM Configuration：
# Sampling Parameters（temperature / top_k / top_p）、
# Output Control（max_tokens / stop）、
# Repetition Penalties（frequency / presence penalty）。
SAMPLING_DEFAULTS = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "max_tokens": 1024,
    "stop": [],
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "repetition_penalty": 1.0,
    "seed": None,
}

# 每百万 token 的美元单价（可用环境变量覆盖，缺省按 gpt-4o-mini 近似）
PRICE_IN = float(os.environ.get("LLM_PRICE_IN", "0.15"))
PRICE_OUT = float(os.environ.get("LLM_PRICE_OUT", "0.6"))


def estimate_tokens(text):
    """轻量 token 估算：中文按 1 字 1 token，其余按 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return int(cjk + (len(text) - cjk) / 4) + 1


def estimate_cost(prompt_tokens, completion_tokens):
    """按配置单价估算单次调用成本（美元）。"""
    return round((prompt_tokens * PRICE_IN + completion_tokens * PRICE_OUT) / 1_000_000, 6)


def _offline_response(messages, json_schema=None):
    """未连接外部模型服务时，由内置规则引擎生成结果。"""
    last = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last = m.get("content", "")
            break
    if isinstance(last, list):
        last = " ".join(x.get("text", "") for x in last if isinstance(x, dict))
    if json_schema:
        props = (json_schema or {}).get("properties", {})
        sample = {k: ("[本地示例]" + str(k)) for k in props}
        return json.dumps(sample or {"result": "[本地引擎输出]"}, ensure_ascii=False)
    return ("[本地引擎] 当前未连接外部模型服务，以下结果由内置规则引擎生成。"
            "接入 LLM_API_KEY 或本地 Ollama 后将返回模型回答。\n"
            "输入摘要：" + (last[:120] or "(空)"))


def chat_full(messages, params=None, json_schema=None):
    """完整采样参数的对话补全，支持结构化输出（JSON 约束）。

    params 可覆盖 SAMPLING_DEFAULTS 中任意项；json_schema 传入时强制 JSON 输出。
    返回 {"content", "backend", "model", "prompt_tokens", "completion_tokens",
          "total_tokens", "cost_usd", "simulated"}。
    未连接外部服务时返回内置引擎结果（simulated=True）。
    """
    p = dict(SAMPLING_DEFAULTS)
    p.update({k: v for k, v in (params or {}).items() if v is not None})
    msgs = [dict(m) for m in messages]
    if json_schema:
        schema_hint = json.dumps(json_schema, ensure_ascii=False)
        msgs.insert(0, {"role": "system",
                        "content": "你必须只输出合法 JSON，且字段严格遵循以下 JSON Schema：\n" + schema_hint})

    b = backend()
    if b == "openai":
        payload = {
            "model": LLM_MODEL,
            "messages": msgs,
            "temperature": p["temperature"],
            "top_p": p["top_p"],
            "max_tokens": p["max_tokens"],
            "frequency_penalty": p["frequency_penalty"],
            "presence_penalty": p["presence_penalty"],
        }
        if p.get("stop"):
            payload["stop"] = p["stop"]
        if p.get("seed") is not None:
            payload["seed"] = p["seed"]
        if json_schema:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
        r = requests.post(f"{LLM_API_BASE}/chat/completions", json=payload,
                          headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        model, simulated = LLM_MODEL, False
    elif b == "ollama":
        options = {
            "temperature": p["temperature"],
            "top_p": p["top_p"],
            "top_k": p["top_k"],
            "num_predict": p["max_tokens"],
            "repeat_penalty": p["repetition_penalty"],
        }
        if p.get("stop"):
            options["stop"] = p["stop"]
        if p.get("seed") is not None:
            options["seed"] = p["seed"]
        payload = {"model": OLLAMA_MODEL, "messages": msgs,
                   "stream": False, "options": options}
        if json_schema:
            payload["format"] = "json"
        r = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        content = data.get("message", {}).get("content", "")
        model, simulated = OLLAMA_MODEL, False
    else:
        content = _offline_response(msgs, json_schema)
        model, simulated = "local-engine", True

    pt = estimate_tokens("".join(str(m.get("content", "")) for m in msgs))
    ct = estimate_tokens(content)
    return {
        "content": content, "backend": b or "offline", "model": model,
        "prompt_tokens": pt, "completion_tokens": ct,
        "total_tokens": pt + ct, "cost_usd": estimate_cost(pt, ct),
        "simulated": simulated,
    }


# ============ 相似度 ============
def cosine(a, b):
    """余弦相似度。"""
    if len(a) != len(b):
        raise ValueError("向量维度不一致")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


if __name__ == "__main__":
    # 自检：打印后端与 embedding 维度
    print("后端探测:", backend() or "无（未配置 LLM）")
    r = embed(["什么是向量数据库", "MongoDB 如何做向量检索"])
    print("embedding 后端:", r["backend"], "模型:", r["model"], "维度:", r["dim"])
    print("两条文本余弦相似度:", round(cosine(r["vectors"][0], r["vectors"][1]), 4))
