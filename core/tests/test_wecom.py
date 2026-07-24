"""企业微信测试已废弃；主路径见 test_weixin.py（个人微信 iLink）。"""

import pytest


@pytest.mark.skip(reason="企业微信已改为微信机器人 iLink，见 test_weixin.py")
def test_legacy_wecom_removed():
    pass
