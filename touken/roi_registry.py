# -*- coding: utf-8 -*-
"""代码 ROI 注册表：策展的「读取型识别区域」白名单。

这里收录的区域只干一件事：从画面里读信息（OCR 读文字、模板匹配取证据）。
刻意**不收**两类坐标：
  - 点击坐标：点错了等于替用户乱点屏幕；
  - 安全门闩（重伤拦截、名单保护那类判定区域）：走差了会出事故，
    只准走代码评审，不给面板留覆盖入口。

坐标系全是 xyxy 像素 (x1, y1, x2, y2)，按 1280×720 标定。
这份注册表是模板工坊「代码 ROI」页的读侧真相源；流程代码里写死的
常量应等于 default（tests/test_roi_overrides.py 盯着防漂移）。
"""

# 每个条目：id（点分层级）、label（人话名）、used_in（代码出处 文件:行）、
# purpose（读这个区域干嘛）、default（xyxy tuple）
ROI_REGISTRY = [
    {
        "id": "sword_inventory.title",
        "label": "刀剑男士一览·页面标题",
        "used_in": "touken/flows/sword_inventory.py:42",
        "purpose": "确认站在「刀剑男士一览」页（标题 OCR 探针）",
        "default": (400, 15, 880, 50),
    },
    {
        "id": "sword_inventory.owned",
        "label": "刀剑男士一览·所持计数",
        "used_in": "touken/flows/sword_inventory.py:43",
        "purpose": "读标题栏「所持刀剑 196/200」，推总页数",
        "default": (640, 15, 1065, 50),
    },
    {
        "id": "sword_inventory.list",
        "label": "刀剑男士一览·列表区",
        "used_in": "touken/flows/sword_inventory.py:44",
        "purpose": "整列 OCR 读每行档案（名字/等级/双血条/九项属性）",
        "default": (130, 145, 1120, 660),
    },
    {
        "id": "sword_inventory.album_title",
        "label": "刀帐图鉴·页面标题",
        "used_in": "touken/flows/sword_inventory.py:92",
        "purpose": "确认站在「刀帐」图鉴 tab（标题 OCR 探针）",
        "default": (400, 15, 880, 50),
    },
    {
        "id": "sword_inventory.album_collect",
        "label": "刀帐图鉴·收集计数",
        "used_in": "touken/flows/sword_inventory.py:93",
        "purpose": "读标题栏收集度「n/n」，只对收集度不读等级",
        "default": (790, 15, 1070, 50),
    },
    {
        "id": "sword_inventory.album_grid",
        "label": "刀帐图鉴·卡牌网格",
        "used_in": "touken/flows/sword_inventory.py:94",
        "purpose": "网格整区 OCR，对刀帐收集表（刀名+极化标记）",
        "default": (100, 115, 1280, 665),
    },
    {
        "id": "formation_editor.list",
        "label": "部队编成·选人列表区",
        "used_in": "touken/flows/formation_editor.py:89",
        "purpose": "选人列表整列 OCR（名字/疲劳/等级分行归位）",
        "default": (60, 100, 1240, 700),
    },
    {
        "id": "smith.capacity",
        "label": "锻刀屋·所持计数",
        "used_in": "touken/flows/smith.py:418",
        "purpose": "读顶栏「所持刀剣 196/200」，锻满前收手",
        "default": (960, 45, 1100, 85),
    },
    {
        "id": "smith.board_name",
        "label": "锻刀屋·显现榜卡牌区",
        "used_in": "touken/flows/smith.py:416",
        "purpose": "结算榜整区 OCR 读刀名（避开左缘花字和底部积分条）",
        "default": (150, 40, 1240, 620),
    },
    {
        "id": "smith.board_mark",
        "label": "锻刀屋·显现榜身份证",
        "used_in": "touken/flows/smith.py:417",
        "purpose": "读榜右下「显现积分」——确认这是同一张榜",
        "default": (880, 625, 1250, 705),
    },
    {
        "id": "sortie.obtain_banner",
        "label": "出阵掉落·预告横幅",
        "used_in": "touken/flows/sortie.py:791",
        "purpose": "读掉刀预告横幅「发现了新的刀剑男士！」——掉刀最早信号",
        "default": (100, 280, 1180, 460),
    },
    {
        "id": "sortie.name_plate",
        "label": "出阵掉落·刀种名牌",
        "used_in": "touken/flows/sortie.py:796",
        "purpose": "读左下对话框名牌「打刀 大和守安定」，按刀种+名字记账",
        "default": (0, 480, 430, 710),
    },
]


def registry_index() -> dict:
    """id → 条目，给按 id 查默认/出处用。"""
    return {entry["id"]: entry for entry in ROI_REGISTRY}
