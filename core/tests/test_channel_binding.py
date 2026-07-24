"""通道→角色绑定（方案 A）测试。"""

from nianxia_core.channels import bound_profile_id, display_name
from nianxia_core.memory.store import ProfileStore
from nianxia_core.models import CharacterCard
from nianxia_core.runtime.cards import CardStore
from nianxia_core.runtime.store import load_app_settings, save_app_settings


def _bind_in_settings(root, channel, profile_id):
    s = load_app_settings(root)
    channels = dict(s.channels or {})
    cfg = dict(channels.get(channel) or {})
    cfg["profile_id"] = profile_id
    channels[channel] = cfg
    s.channels = channels
    save_app_settings(root, s)


def test_bound_profile_fallback_default(tmp_path):
    assert bound_profile_id(tmp_path, "onebot") == "default"
    assert bound_profile_id(tmp_path, "telegram", "default") == "default"


def test_bound_profile_from_settings(tmp_path):
    _bind_in_settings(tmp_path, "qqbot", "ch_qqbot")
    assert bound_profile_id(tmp_path, "qqbot") == "ch_qqbot"
    # 别的通道不受影响
    assert bound_profile_id(tmp_path, "telegram") == "default"


def test_bound_profile_blank_falls_back(tmp_path):
    _bind_in_settings(tmp_path, "weixin", "   ")
    assert bound_profile_id(tmp_path, "weixin") == "default"


def test_display_name_prefers_card(tmp_path):
    cs = CardStore(tmp_path)
    card = cs.save(CharacterCard(name="狐仙阿九"))
    ps = ProfileStore(tmp_path, "ch_onebot")
    persona = ps.load_persona()  # 自动建，默认名念念
    persona.active_card_id = card.id
    ps.save_persona(persona)

    assert display_name(tmp_path, "ch_onebot") == "狐仙阿九"  # 有卡用卡名
    assert display_name(tmp_path, "default") == "念念"          # 无卡用 persona 名


def test_channel_profile_memory_isolated(tmp_path):
    """绑定后通道 profile 的记忆与 default 物理隔离。"""
    default_store = ProfileStore(tmp_path, "default")
    ch_store = ProfileStore(tmp_path, "ch_qqbot")
    default_store.add_fact("default 的事", pinned=True)
    ch_store.add_fact("qqbot 的事", pinned=True)

    d_facts = [f.text for f in default_store.list_facts()]
    c_facts = [f.text for f in ch_store.list_facts()]
    assert "default 的事" in d_facts and "qqbot 的事" not in d_facts
    assert "qqbot 的事" in c_facts and "default 的事" not in c_facts
