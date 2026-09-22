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
        "purpose": "整列 OCR 读每行档案（兜底路径；主路径走逐格精读）",
        "default": (130, 145, 1120, 660),
    },
    # ── 逐格精读 25 格（2026-09-20 模板工坊手工框定，5 行 × 5 字段）──
    {
        "id": "sword_inventory.row1.name",
        "label": "刀剑男士一览·一号位刀名",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第一行刀名，过 sword_db 名册匹配",
        "default": (160, 202, 402, 233),
    },
    {
        "id": "sword_inventory.row1.levels",
        "label": "刀剑男士一览·一号位等级块",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第一行 刀剑/乱舞等级+生存/疲劳双血条",
        "default": (400, 141, 523, 234),
    },
    {
        "id": "sword_inventory.row1.date",
        "label": "刀剑男士一览·一号位显现日期",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第一行显现日期（年 + 月/日）",
        "default": (1023, 141, 1103, 232),
    },
    {
        "id": "sword_inventory.row1.stats",
        "label": "刀剑男士一览·一号位数值带",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第一行九项属性带，按 9 等分逐格 OCR（防数字胶连）",
        "default": (521, 144, 1026, 231),
    },
    {
        "id": "sword_inventory.row1.badge",
        "label": "刀剑男士一览·一号位徽章",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第一行行首刀种+花数圆徽，走模板匹配（美术字 OCR 读不了）",
        "default": (170, 143, 231, 205),
    },
    {
        "id": "sword_inventory.row2.name",
        "label": "刀剑男士一览·二号位刀名",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第二行刀名，过 sword_db 名册匹配",
        "default": (162, 303, 398, 335),
    },
    {
        "id": "sword_inventory.row2.levels",
        "label": "刀剑男士一览·二号位等级块",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第二行 刀剑/乱舞等级+生存/疲劳双血条",
        "default": (399, 242, 523, 333),
    },
    {
        "id": "sword_inventory.row2.date",
        "label": "刀剑男士一览·二号位显现日期",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第二行显现日期（年 + 月/日）",
        "default": (1023, 242, 1105, 333),
    },
    {
        "id": "sword_inventory.row2.stats",
        "label": "刀剑男士一览·二号位数值带",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第二行九项属性带，按 9 等分逐格 OCR（防数字胶连）",
        "default": (521, 244, 1025, 331),
    },
    {
        "id": "sword_inventory.row2.badge",
        "label": "刀剑男士一览·二号位徽章",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第二行行首刀种+花数圆徽，走模板匹配（美术字 OCR 读不了）",
        "default": (170, 243, 232, 306),
    },
    {
        "id": "sword_inventory.row3.name",
        "label": "刀剑男士一览·三号位刀名",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第三行刀名，过 sword_db 名册匹配",
        "default": (162, 403, 399, 434),
    },
    {
        "id": "sword_inventory.row3.levels",
        "label": "刀剑男士一览·三号位等级块",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第三行 刀剑/乱舞等级+生存/疲劳双血条",
        "default": (399, 343, 523, 435),
    },
    {
        "id": "sword_inventory.row3.date",
        "label": "刀剑男士一览·三号位显现日期",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第三行显现日期（年 + 月/日）",
        "default": (1023, 342, 1105, 434),
    },
    {
        "id": "sword_inventory.row3.stats",
        "label": "刀剑男士一览·三号位数值带",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第三行九项属性带，按 9 等分逐格 OCR（防数字胶连）",
        "default": (521, 345, 1024, 431),
    },
    {
        "id": "sword_inventory.row3.badge",
        "label": "刀剑男士一览·三号位徽章",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第三行行首刀种+花数圆徽，走模板匹配（美术字 OCR 读不了）",
        "default": (170, 345, 233, 406),
    },
    {
        "id": "sword_inventory.row4.name",
        "label": "刀剑男士一览·四号位刀名",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第四行刀名，过 sword_db 名册匹配",
        "default": (162, 504, 400, 534),
    },
    {
        "id": "sword_inventory.row4.levels",
        "label": "刀剑男士一览·四号位等级块",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第四行 刀剑/乱舞等级+生存/疲劳双血条",
        "default": (398, 443, 522, 536),
    },
    {
        "id": "sword_inventory.row4.date",
        "label": "刀剑男士一览·四号位显现日期",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第四行显现日期（年 + 月/日）",
        "default": (1023, 443, 1104, 533),
    },
    {
        "id": "sword_inventory.row4.stats",
        "label": "刀剑男士一览·四号位数值带",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第四行九项属性带，按 9 等分逐格 OCR（防数字胶连）",
        "default": (521, 446, 1024, 532),
    },
    {
        "id": "sword_inventory.row4.badge",
        "label": "刀剑男士一览·四号位徽章",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第四行行首刀种+花数圆徽，走模板匹配（美术字 OCR 读不了）",
        "default": (169, 444, 232, 507),
    },
    {
        "id": "sword_inventory.row5.name",
        "label": "刀剑男士一览·五号位刀名",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第五行刀名，过 sword_db 名册匹配",
        "default": (161, 604, 400, 637),
    },
    {
        "id": "sword_inventory.row5.levels",
        "label": "刀剑男士一览·五号位等级块",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第五行 刀剑/乱舞等级+生存/疲劳双血条",
        "default": (398, 544, 522, 637),
    },
    {
        "id": "sword_inventory.row5.date",
        "label": "刀剑男士一览·五号位显现日期",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "逐格读第五行显现日期（年 + 月/日）",
        "default": (1025, 544, 1103, 636),
    },
    {
        "id": "sword_inventory.row5.stats",
        "label": "刀剑男士一览·五号位数值带",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第五行九项属性带，按 9 等分逐格 OCR（防数字胶连）",
        "default": (521, 546, 1025, 633),
    },
    {
        "id": "sword_inventory.row5.badge",
        "label": "刀剑男士一览·五号位徽章",
        "used_in": "touken/flows/sword_inventory.py:55",
        "purpose": "第五行行首刀种+花数圆徽，走模板匹配（美术字 OCR 读不了）",
        "default": (171, 546, 232, 608),
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
        "used_in": "touken/flows/formation_editor.py:100",
        "purpose": "选人列表整列 OCR（名字/疲劳/等级分行归位）",
        "default": (60, 40, 1240, 700),
    },
    {
        "id": "formation_editor.list_title",
        "label": "部队编成·选人列表标题",
        "used_in": "touken/flows/formation_editor.py:93",
        "purpose": "确认「刀剑男士选择」列表已开/已关（标题 OCR 探针）",
        "default": (450, 0, 830, 110),
    },
    {
        "id": "formation_editor.title",
        "label": "部队编成·页面标题",
        "used_in": "touken/flows/formation_editor.py:95",
        "purpose": "确认站在「部队编成」页（标题 OCR 探针，与 navigator 一致）",
        "default": (480, 0, 800, 60),
    },
    {
        "id": "formation_editor.team_select_title",
        "label": "部队选择·页面标题",
        "used_in": "touken/flows/formation_editor.py:97",
        "purpose": "确认站在「部队选择」页（出阵/远征入口的选人外壳）",
        "default": (506, 1, 774, 55),
    },
    {
        "id": "formation_editor.name_band",
        "label": "选人列表·姓名竖带",
        "used_in": "touken/flows/formation_editor.py:106",
        "purpose": "整列 OCR 里只取这带内的 token 当名字（y 跨度无语义，只用 x）",
        "default": (100, 40, 300, 700),
    },
    {
        "id": "formation_editor.level_band",
        "label": "选人列表·等级竖带",
        "used_in": "touken/flows/formation_editor.py:107",
        "purpose": "「刀剑 N级」小字所在列，靠 label 配对防乱舞等级冒充（只用 x）",
        "default": (440, 40, 620, 700),
    },
    {
        "id": "formation_editor.fatigue_band",
        "label": "选人列表·疲劳竖带",
        "used_in": "touken/flows/formation_editor.py:108",
        "purpose": "「疲劳 N/M」小字所在列，按内容格式与等级区分（只用 x）",
        "default": (440, 40, 640, 700),
    },
    {
        "id": "formation_editor.filter_open",
        "label": "选人列表·筛选/排序按钮带",
        "used_in": "touken/flows/formation_editor.py:163",
        "purpose": "OCR 定位「筛选/排序」按钮（点开筛选面板的入口）",
        "default": (600, 60, 1100, 140),
    },
    {
        "id": "formation_editor.filter_title",
        "label": "筛选面板·标题",
        "used_in": "touken/flows/formation_editor.py:165",
        "purpose": "确认筛选面板开着（标题 OCR 探针）",
        "default": (400, 60, 640, 130),
    },
    {
        "id": "formation_editor.filter_panel",
        "label": "筛选面板·整区",
        "used_in": "touken/flows/formation_editor.py:167",
        "purpose": "面板内按文字 exact 找按钮的默认范围",
        "default": (100, 50, 1180, 670),
    },
    {
        "id": "formation_editor.filter_types",
        "label": "筛选面板·刀种按钮区",
        "used_in": "touken/flows/formation_editor.py:169",
        "purpose": "找「打刀」等刀种按钮（真机行 y≈226/300）",
        "default": (130, 140, 1140, 470),
    },
    {
        "id": "formation_editor.filter_form_row",
        "label": "筛选面板·初/极按钮行",
        "used_in": "touken/flows/formation_editor.py:171",
        "purpose": "找「初」「极」按钮（真机 y≈450，下缘别卡 440 之上）",
        "default": (130, 410, 1140, 500),
    },
    {
        "id": "formation_editor.filter_confirm",
        "label": "筛选面板·确定按钮",
        "used_in": "touken/flows/formation_editor.py:173",
        "purpose": "找「确定」按钮（真机 y≈623）",
        "default": (400, 540, 880, 680),
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
