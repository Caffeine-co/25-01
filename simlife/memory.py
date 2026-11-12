"""小型透明的情景记忆检索。无需向量数据库或云服务。

按文本相关性、显著度和时间新近度排序。
这不是完整语义搜索，只适合作为本工程的教学基线。
"""
from __future__ import annotations
import math
import re
from .model import LifeState, Memory


def terms(text: str) -> set[str]:
    text = text.casefold()
    english = re.findall(r'[a-z0-9_]+', text)
    # 中文、日文等缺少空格分词的文本，用字符二元组做最小检索基线。
    letters = ''.join(c for c in text if '\u3400' <= c <= '\u9fff' or
                      '\u3040' <= c <= '\u30ff')
    pairs = [letters[i:i + 2] for i in range(len(letters) - 1)]
    return set(english + pairs + list(letters))


def retrieve(life: LifeState, query: str, minute: int, limit: int = 5) -> list[Memory]:
    if limit < 1:
        return []
    query_terms = terms(query)
    ranked = []
    for memory in life.memories:
        memory_terms = terms(memory.text)
        overlap = (len(query_terms & memory_terms) /
                   max(1, len(query_terms | memory_terms)))
        age_days = max(0, minute - memory.minute) / 1440
        recency = math.exp(-age_days / 7)
        score = 3 * overlap + 0.4 * memory.salience + 0.2 * recency
        ranked.append((score, memory.minute, memory))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [memory for _, _, memory in ranked[:limit]]


def summarize_known_facts(life: LifeState, limit: int = 12) -> list[dict]:
    """对外只展示人物自己的认知，不读取世界事实。"""
    rows = sorted(life.facts.items(), key=lambda item: item[1].get('seen', 0), reverse=True)
    return [{"key": key, **value} for key, value in rows[:limit]]
