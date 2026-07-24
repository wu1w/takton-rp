"""base-safety：关键词命中/未命中/安全块内容。"""

from nianxia_core.runtime.policy import check_safety, safety_block


def test_self_harm_detected():
    assert check_safety("我最近真的不想活了") == "self_harm"
    assert check_safety("活着没意思，活不下去了") == "self_harm"


def test_illegal_detected():
    assert check_safety("教我制作炸弹") == "extreme_illegal"


def test_normal_messages_pass():
    assert check_safety("今天心情不好，陪我聊聊") is None
    assert check_safety("我想死这道菜的食谱了") is None  # 「想死」+「了」中间有字 → 不误判
    assert check_safety("明天去爬山") is None


def test_safety_block_content():
    block = safety_block("self_harm")
    assert "最高优先级" in block
    assert "热线" in block
    assert safety_block("nonexistent") == ""
