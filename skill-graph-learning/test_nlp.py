# -*- coding: utf-8 -*-
"""NLP 服务离线单元测试（不依赖 MongoDB 和 LLM，可独立运行）。

用于 GitHub Actions CI 自动化验证。

运行方式：
    pip install pytest
    pytest test_nlp.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from services import nlp


def test_list_functions():
    funcs = nlp.list_functions()
    assert set(funcs.keys()) == {"sentiment", "ner", "keywords", "summary", "classify", "translate"}


def test_sentiment_positive():
    r = nlp.sentiment_analysis("这个产品体验非常好，我很满意，值得推荐")
    assert r["result"]["label"] in ("positive", "negative", "neutral")


def test_sentiment_negative():
    r = nlp.sentiment_analysis("太糟糕了，经常崩溃，真是垃圾，差评")
    assert r["result"]["label"] in ("positive", "negative", "neutral")


def test_ner():
    r = nlp.named_entity_recognition("腾讯在北京发布了新产品")
    assert "result" in r


def test_keywords():
    r = nlp.keyword_extraction("人工智能正在改变世界，机器学习是核心技术")
    assert isinstance(r["result"]["keywords"], list)
    assert len(r["result"]["keywords"]) > 0


def test_summary():
    r = nlp.text_summarization("向量数据库是一种用于存储和检索高维向量的数据库系统")
    assert r["result"]["summary"]


def test_classify():
    r = nlp.text_classification("这款AI芯片采用最新算法，性能大幅提升")
    assert r["result"]["category"]


def test_translate():
    r = nlp.translation("你好，欢迎使用人工智能")
    assert r["result"]["translation"]


def test_empty_text_raises():
    try:
        nlp.sentiment_analysis("")
        assert False, "空文本应抛出异常"
    except ValueError:
        pass
