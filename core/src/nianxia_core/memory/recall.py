"""回忆唤起：消息与记忆的相关度评分（热路径纯规则，无 LLM）。

评分：消息与事实文本的字符 bigram 重叠数；子串直接命中加权。
阈值之上才进【唤起的相关记忆】块，避免每轮都塞。
"""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def _lcs_len(a: str, b: str) -> int:
    """最长公共子串长度（短文本用 DP 足够快）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def score_fact(message: str, fact_text: str) -> int:
    msg = message.lower()
    fact = fact_text.lower()
    if not msg or not fact:
        return 0
    if msg in fact or fact in msg:
        return 10 + len(fact)

    score = 0
    grams = {msg[i : i + 2] for i in range(len(msg) - 1)}
    for g in grams:
        if len(g.strip()) < 2:
            continue
        if g in fact:
            score += 1

    # 关键词重合加权：「花生」这类 2+ 字重合是强信号
    lcs = _lcs_len(msg, fact)
    if lcs >= 2:
        score += lcs * 2
    return score


def recall_relevant(
    message: str,
    items: list[T],
    text_of: Callable[[T], str],
    limit: int = 3,
    threshold: int = 3,
) -> list[tuple[T, int]]:
    """返回分数 ≥ threshold 的前 limit 条，按分数降序。"""
    scored = [(it, score_fact(message, text_of(it))) for it in items]
    hits = [(it, s) for it, s in scored if s >= threshold]
    hits.sort(key=lambda x: x[1], reverse=True)
    return hits[:limit]
