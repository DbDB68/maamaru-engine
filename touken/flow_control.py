# -*- coding: utf-8 -*-
"""玩法流程的受控退出信号。"""


class FlowAborted(RuntimeError):
    """玩法已安全收尾，但因游戏状态异常不能算作正常完成。"""
