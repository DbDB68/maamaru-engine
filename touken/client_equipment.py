"""国服装备编号与预设名称对应；未校准编号保留原值，不按日服编号猜。

刀装依据 2026-10-03 国服客户端 swr_equip_l_<编号> 原图核对。
2026-10-03 17:25 完整 party/list 库存与玩家逐类所持数量核对：
普通刀装仅校准已确认的特上，水炮兵三品级；新春轻步/轻骑分别 3/4 个。
马匹 01–08 经玩家确认；白毛 5/5、鹿毛 13/3、青毛 25/1（未装备/装备）。
御守 1/2 沿用客户端道具库存的既有校准。其他名称待逐项确认。
祝号马依据玩家同一把刀祝九→祝一的九次换装日志逐条校准（17:29–17:32）。
3155 经玩家确认为御守·桃，客户端记录普/极压切各装备一个。
此处只翻译读取结果，不参与装备点击或替换。
"""

from copy import deepcopy


EQUIPMENT_NAMES = {
    3: ("troop", "投石兵·特上"),
    6: ("troop", "枪兵·特上"),
    9: ("troop", "轻步兵·特上"),
    12: ("troop", "重步兵·特上"),
    15: ("troop", "盾兵·特上"),
    18: ("troop", "轻骑兵·特上"),
    21: ("troop", "重骑兵·特上"),
    24: ("troop", "精锐兵·特上"),
    27: ("troop", "弓兵·特上"),
    30: ("troop", "铳兵·特上"),
    34: ("troop", "水炮兵·中"),
    35: ("troop", "水炮兵·上"),
    36: ("troop", "水炮兵·特上"),
    109: ("troop", "轻步兵·新春"),
    118: ("troop", "轻骑兵·新春"),
    130: ("troop", "铳兵·新春"),
    10001: ("horse", "01王庭"),
    10002: ("horse", "02三国黑"),
    10003: ("horse", "03松风"),
    10004: ("horse", "04小云雀"),
    10005: ("horse", "05高楯黑"),
    10006: ("horse", "06花柑子"),
    10007: ("horse", "07青海波"),
    10008: ("horse", "08望月"),
    11011: ("horse", "白毛"),
    11021: ("horse", "鹿毛"),
    11031: ("horse", "青毛"),
    11041: ("horse", "祝一号"),
    11042: ("horse", "祝二号"),
    11043: ("horse", "祝三号"),
    11044: ("horse", "祝四号"),
    11045: ("horse", "祝五号"),
    11046: ("horse", "祝六号"),
    11047: ("horse", "祝七号"),
    11048: ("horse", "祝八号"),
    11049: ("horse", "祝九号"),
}
TREASURE_NAMES: dict[int, str] = {}
CHARM_NAMES = {1: "御守", 2: "御守·极", 3155: "御守·桃"}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def name_client_assets(assets: dict) -> dict:
    """兼容已保存的原始观察；保留实例编号和未知字段，不改写历史记录。"""
    result = deepcopy(assets)
    for row in result.get("equip", []):
        match = EQUIPMENT_NAMES.get(_number(row.get("equip_id")))
        if match:
            row["kind"], row["name"] = match
    for row in result.get("artifact", []):
        name = TREASURE_NAMES.get(_number(row.get("artifact_id")))
        if name:
            row["name"] = name
    for row in result.get("sword", []):
        name = CHARM_NAMES.get(_number(row.get("item_id")))
        if name:
            row["charm_name"] = name
    return result
