"""旧 OneBot 测试改为跳过提示；主路径见 test_qqbot.py。

保留文件以免外部引用路径断裂；行为已迁移到官方 QQ 机器人。
"""

import pytest


@pytest.mark.skip(reason="QQ 主路径已改为官方 AppID+AppSecret，见 test_qqbot.py")
def test_legacy_onebot_removed():
    pass
