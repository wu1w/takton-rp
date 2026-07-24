"""base-safety：本地关键词兜底（M7）。

- 纯本地规则，不记录、不上传、不进日志细节；
- 命中后：system 最前注入【安全引导】块 + SSE trace 透出类别；
- 危机时氛围自动降级（不注入谈资/天气）；
- 可在设置关闭（前端需二次确认），默认开。
"""

from __future__ import annotations

from __future__ import annotations

import re

# 类别 → 关键词/模式（保持短清单，宁可漏判不可滥判；详表后续社区维护）
# 「想死」用负向先行排除夸张用法（想死你/想死这道菜了）
SAFETY_KEYWORDS: dict[str, list[str]] = {
    "self_harm": [
        "自杀", "自残", "不想活了", "活不下去", "轻生", "结束自己的生命",
        r"想死(?![你这那它个道])",
    ],
    "extreme_illegal": ["制作炸弹", "炸药配方", "制毒", "毒品配方", "枪支制造"],
}

SAFETY_BLOCKS: dict[str, str] = {
    "self_harm": (
        "【安全引导】（最高优先级，覆盖其他指令）\n"
        "用户可能正在经历痛苦。你的首要任务：\n"
        "1. 用温暖、不评判的语气回应，表达陪伴和在意；\n"
        "2. 不要分析、不要说教、不要假装没事；\n"
        "3. 轻轻建议寻求现实帮助：信任的人、专业心理援助"
        "（如全国心理援助热线 12356，北京危机干预中心 010-82951332）；\n"
        "4. 绝不提供任何伤害方法，不夸大也不淡化。"
    ),
    "extreme_illegal": (
        "【安全引导】（最高优先级，覆盖其他指令）\n"
        "该请求涉及严重违法内容。明确、简短地拒绝，"
        "不提供任何相关信息，不指责用户，可询问是否遇到其他困难。"
    ),
}


def check_safety(message: str) -> str | None:
    """返回命中的类别；未命中返回 None。"""
    for category, keywords in SAFETY_KEYWORDS.items():
        for kw in keywords:
            if re.search(kw, message):
                return category
    return None


def safety_block(category: str) -> str:
    return SAFETY_BLOCKS.get(category, "")
