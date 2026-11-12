# -*- coding: utf-8 -*-
"""自然语言处理（NLP）服务：情感分析 / 命名实体识别 / 关键词提取 / 摘要 / 分类 / 翻译。

AI 训练师工作台内置 NLP 能力，供模型训练与推理时调用：
- 每个能力优先走 LLM（OpenAI 兼容 / Ollama），未配置 LLM 时回退到本地规则/词典（离线可用）。
- 统一返回 {"result": ..., "backend": str, "method": str}，method 标识 llm / rule。

对应 roadmap.sh AI Engineer：NLP / LLM / 文本处理。
"""
import re
from collections import Counter

from services import llm


# ============ 通用 LLM 调用封装 ============
def _llm_extract(task_desc, text, examples=""):
    """调用 LLM 做结构化文本处理，返回纯文本结果。"""
    system = (
        "你是一个自然语言处理引擎。请严格按指令输出结果，"
        "只输出最终答案本身，不要解释、不要额外文字。")
    prompt = f"{task_desc}\n\n{examples}文本：\n{text}".strip()
    res = llm.chat([{"role": "system", "content": system},
                    {"role": "user", "content": prompt}], temperature=0.0)
    return res


# ============ 1. 情感分析 ============
POS_WORDS = ["好", "棒", "优秀", "喜欢", "满意", "赞", "开心", "高兴", "推荐",
             "感谢", "精彩", "流畅", "稳定", "高效", "满意", "优秀", "很棒", "great", "good", "love"]
NEG_WORDS = ["差", "烂", "糟", "讨厌", "失望", "愤怒", "生气", "卡顿", "崩溃",
             "bug", "错误", "失败", "糟糕", "差评", "垃圾", "bad", "poor", "hate"]
NEGATE_WORDS = ["不", "没", "无", "非", "别", "莫"]


def sentiment_analysis(text):
    """情感分析：返回 positive / negative / neutral 及置信度。"""
    if not text or not text.strip():
        raise ValueError("请输入要分析的文本")
    try:
        res = _llm_extract(
            "对下面的文本做情感分析，只输出一个词：positive（积极）/ negative（消极）/ neutral（中性）。",
            text)
        label = res["content"].strip().lower()
        if "positive" in label or "积极" in label or "正面" in label:
            return {"result": {"label": "positive", "label_cn": "积极", "confidence": 0.9},
                    "backend": res["backend"], "method": "llm"}
        if "negative" in label or "消极" in label or "负面" in label:
            return {"result": {"label": "negative", "label_cn": "消极", "confidence": 0.9},
                    "backend": res["backend"], "method": "llm"}
        return {"result": {"label": "neutral", "label_cn": "中性", "confidence": 0.9},
                "backend": res["backend"], "method": "llm"}
    except Exception:
        return _sentiment_rule(text)


def _sentiment_rule(text):
    """离线情感分析（词典 + 否定词规则）。"""
    pos = sum(text.count(w) for w in POS_WORDS)
    neg = sum(text.count(w) for w in NEG_WORDS)
    # 否定词翻转：简单处理「不好」「不差」等
    for nw in NEGATE_WORDS:
        for w in POS_WORDS:
            if nw + w in text:
                pos -= 1
                neg += 1
        for w in NEG_WORDS:
            if nw + w in text:
                neg -= 1
                pos += 1
    if pos > neg:
        return {"result": {"label": "positive", "label_cn": "积极", "confidence": 0.6},
                "backend": "rule", "method": "rule"}
    if neg > pos:
        return {"result": {"label": "negative", "label_cn": "消极", "confidence": 0.6},
                "backend": "rule", "method": "rule"}
    return {"result": {"label": "neutral", "label_cn": "中性", "confidence": 0.6},
            "backend": "rule", "method": "rule"}


# ============ 2. 命名实体识别（NER） ============
def named_entity_recognition(text):
    """命名实体识别：提取人名/地名/机构/时间/数字等实体。"""
    if not text or not text.strip():
        raise ValueError("请输入要分析的文本")
    try:
        res = _llm_extract(
            "从下面文本中提取命名实体，按「类型:实体」逐行输出，类型限：人名/地名/机构/时间/日期/数字/其他。若无实体输出「无」。",
            text)
        return {"result": {"entities": res["content"].strip()},
                "backend": res["backend"], "method": "llm"}
    except Exception:
        return _ner_rule(text)


_ENTITY_RULES = [
    ("日期", r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?"),
    ("时间", r"\d{1,2}[:时]\d{1,2}([:分]\d{1,2})?[分]?"),
    ("数字", r"\d+(?:\.\d+)?%?"),
]


def _ner_rule(text):
    """离线 NER（正则规则 + 常见机构/地名词典）。"""
    entities = []
    for etype, pat in _ENTITY_RULES:
        for m in re.finditer(pat, text):
            entities.append({"type": etype, "value": m.group()})
    # 常见地名/机构
    for place in ["北京", "上海", "广州", "深圳", "杭州", "成都", "中国", "美国"]:
        if place in text:
            entities.append({"type": "地名", "value": place})
    for org in ["腾讯", "阿里", "百度", "华为", "字节跳动", "OpenAI", "Google"]:
        if org in text:
            entities.append({"type": "机构", "value": org})
    # 去重
    seen, uniq = set(), []
    for e in entities:
        k = (e["type"], e["value"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return {"result": {"entities": uniq or "无"}, "backend": "rule", "method": "rule"}


# ============ 3. 关键词提取 ============
_STOPWORDS = set("的 了 和 是 在 我 你 他 她 它 我们 你们 他们 这 那 与 或 及 也 都 而 但 就 很 更 最 有 没 不 把 被 对 从 到 上 下 中 里 外 一个 什么 怎么 为什么 因为 所以 如果 然后 可以 需要 已经 还 又 用于 支持 以及 其中 通过 进行 成为 能够 这样 那样 这些 那些".split())

# 常用中文关键词词典（最大匹配分词用，可自行扩展）
_KEYWORD_DICT = [
    "人工智能", "机器学习", "深度学习", "自然语言处理", "神经网络", "大语言模型",
    "向量数据库", "知识库", "检索增强", "相似度", "推荐系统", "算法", "模型", "数据",
    "训练", "推理", "语义", "文本", "图像", "多模态", "技术", "系统", "应用", "开发",
    "学习", "核心", "改变", "世界", "存储", "检索", "高性能", "芯片", "性能", "提升",
    "医疗", "教育", "金融", "科技", "互联网", "智能", "语言", "处理", "生成", "理解",
    "编码", "翻译", "摘要", "分类", "情感", "分析", "实体", "识别", "提取", "关键词",
]


def _max_match_segment(text):
    """最大正向匹配分词：优先匹配词典中的长词。"""
    words = []
    i = 0
    n = len(text)
    while i < n:
        matched = False
        # 从最长词开始尝试匹配（词典按长度降序）
        for w in _KEYWORD_DICT:
            if text.startswith(w, i):
                words.append(w)
                i += len(w)
                matched = True
                break
        if not matched:
            # 未匹配到词典词：英文数字作为整体，否则跳过单字
            if text[i].isalnum() and not ('\u4e00' <= text[i] <= '\u9fa5'):
                j = i
                while j < n and (text[j].isalnum()) and not ('\u4e00' <= text[j] <= '\u9fa5'):
                    j += 1
                words.append(text[i:j])
                i = j
            else:
                i += 1
    return words


def keyword_extraction(text, top_k=5):
    """关键词提取：返回 top_k 个关键词。"""
    if not text or not text.strip():
        raise ValueError("请输入要分析的文本")
    try:
        res = _llm_extract(
            f"从下面文本中提取 {top_k} 个关键词，用顿号「、」分隔，只输出关键词本身。",
            text)
        kws = [k.strip() for k in re.split(r"[、,，;；]", res["content"]) if k.strip()]
        return {"result": {"keywords": kws[:top_k]}, "backend": res["backend"], "method": "llm"}
    except Exception:
        return _keyword_rule(text, top_k)


def _keyword_rule(text, top_k):
    """离线关键词提取（词典最大匹配分词 + 词频 + 停用词过滤）。"""
    tokens = _max_match_segment(text)
    counter = Counter(t for t in tokens if t.lower() not in _STOPWORDS and len(t) > 1)
    kws = [w for w, _ in counter.most_common(top_k)]
    return {"result": {"keywords": kws}, "backend": "rule", "method": "rule"}


# ============ 4. 文本摘要 ============
def text_summarization(text, max_len=100):
    """文本摘要：生成精简摘要。"""
    if not text or not text.strip():
        raise ValueError("请输入要摘要的文本")
    try:
        res = _llm_extract(
            f"用不超过 {max_len} 字概括下面文本的核心内容，直接输出摘要。",
            text)
        return {"result": {"summary": res["content"].strip()},
                "backend": res["backend"], "method": "llm"}
    except Exception:
        return _summarize_rule(text, max_len)


def _summarize_rule(text, max_len):
    """离线摘要（取首段/前 N 字，截断）。"""
    s = re.sub(r"\s+", " ", text).strip()
    summary = s[:max_len] + ("…" if len(s) > max_len else "")
    return {"result": {"summary": summary}, "backend": "rule", "method": "rule"}


# ============ 5. 文本分类 ============
DEFAULT_CATEGORIES = ["科技", "财经", "医疗", "教育", "娱乐", "体育", "政治", "其他"]


def text_classification(text, categories=None):
    """文本分类：归到给定类别之一。"""
    if not text or not text.strip():
        raise ValueError("请输入要分类的文本")
    cats = categories or DEFAULT_CATEGORIES
    cat_str = "、".join(cats)
    try:
        res = _llm_extract(
            f"将下面文本分类到以下类别之一：{cat_str}。只输出一个类别名。",
            text)
        label = res["content"].strip()
        if label not in cats:
            # 尝试模糊匹配
            label = next((c for c in cats if c in label), cats[-1])
        return {"result": {"category": label, "categories": cats},
                "backend": res["backend"], "method": "llm"}
    except Exception:
        return _classify_rule(text, cats)


_CATEGORY_KEYWORDS = {
    "科技": ["AI", "人工智能", "算法", "芯片", "软件", "编程", "互联网", "科技"],
    "财经": ["股票", "基金", "金融", "经济", "投资", "银行", "市场"],
    "医疗": ["医院", "医生", "疾病", "治疗", "药物", "健康", "手术"],
    "教育": ["学校", "老师", "学生", "课程", "考试", "学习", "教育"],
    "娱乐": ["电影", "明星", "音乐", "游戏", "综艺", "娱乐"],
    "体育": ["足球", "篮球", "比赛", "运动员", "奥运", "体育"],
    "政治": ["政府", "政策", "国家", "选举", "外交", "政治"],
}


def _classify_rule(text, cats):
    """离线分类（关键词匹配）。"""
    best, best_score = cats[-1], 0
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if cat not in cats:
            continue
        score = sum(text.count(k) for k in kws)
        if score > best_score:
            best, best_score = cat, score
    return {"result": {"category": best, "categories": cats},
            "backend": "rule", "method": "rule"}


# ============ 6. 机器翻译 ============
def translation(text, target_lang="英文"):
    """机器翻译：把文本翻译到目标语言（默认中译英）。"""
    if not text or not text.strip():
        raise ValueError("请输入要翻译的文本")
    try:
        res = _llm_extract(
            f"将下面的文本翻译成{target_lang}，只输出翻译结果。",
            text)
        return {"result": {"translation": res["content"].strip(), "target_lang": target_lang},
                "backend": res["backend"], "method": "llm"}
    except Exception:
        return _translate_rule(text, target_lang)


_SIMPLE_DICT = {
    "你好": "Hello", "谢谢": "Thank you", "再见": "Goodbye", "好的": "OK",
    "人工智能": "Artificial Intelligence", "机器学习": "Machine Learning",
    "深度学习": "Deep Learning", "自然语言处理": "Natural Language Processing",
    "向量数据库": "Vector Database", "知识库": "Knowledge Base",
}


def _translate_rule(text, target_lang):
    """离线翻译（简易词典直译，仅演示）。"""
    if target_lang in ("英文", "英语", "en", "English"):
        out = text
        for zh, en in _SIMPLE_DICT.items():
            out = out.replace(zh, en)
        return {"result": {"translation": out, "target_lang": target_lang},
                "backend": "rule", "method": "rule"}
    # 其他语言未配置规则，返回提示
    return {"result": {"translation": text, "target_lang": target_lang,
                       "note": "离线模式仅支持中译英，配置 LLM 后可支持更多语言"},
            "backend": "rule", "method": "rule"}


# ============ 汇总 ============
NLP_FUNCTIONS = {
    "sentiment": {"name": "情感分析", "desc": "判断文本情感倾向（积极/消极/中性）"},
    "ner": {"name": "命名实体识别", "desc": "提取人名/地名/机构/时间/数字等实体"},
    "keywords": {"name": "关键词提取", "desc": "提取文本核心关键词"},
    "summary": {"name": "文本摘要", "desc": "生成文本精简摘要"},
    "classify": {"name": "文本分类", "desc": "将文本归类到预设类别"},
    "translate": {"name": "机器翻译", "desc": "将文本翻译到目标语言"},
}

_HANDLERS = {
    "sentiment": lambda p: sentiment_analysis(p.get("text", "")),
    "ner": lambda p: named_entity_recognition(p.get("text", "")),
    "keywords": lambda p: keyword_extraction(p.get("text", ""), int(p.get("top_k", 5))),
    "summary": lambda p: text_summarization(p.get("text", ""), int(p.get("max_len", 100))),
    "classify": lambda p: text_classification(p.get("text", ""), p.get("categories")),
    "translate": lambda p: translation(p.get("text", ""), p.get("target_lang", "英文")),
}


def run_nlp(function, params=None):
    """统一 NLP 入口：根据功能名分发。

    function: sentiment / ner / keywords / summary / classify / translate
    params: dict，各功能所需参数（text 必填）。
    """
    if function not in _HANDLERS:
        raise ValueError("不支持的 NLP 功能：" + function)
    return _HANDLERS[function](params or {})


def list_functions():
    """列出所有可用 NLP 功能。"""
    return NLP_FUNCTIONS
