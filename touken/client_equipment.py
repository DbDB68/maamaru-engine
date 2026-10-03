"""国服装备编号与预设名称对应；未校准编号保留原值，不按日服编号猜。

刀装依据 2026-10-03 国服客户端 swr_equip_l_<编号> 原图核对。
御守 1/2 沿用客户端道具库存的既有校准。其他名称待逐项确认。
此处只翻译读取结果，不参与装备点击或替换。
"""

from copy import deepcopy


EQUIPMENT_NAMES = {
    15: ("troop", "盾兵·特上"),
    30: ("troop", "铳兵·特上"),
    34: ("troop", "水炮兵·中"),
    35: ("troop", "水炮兵·上"),
    36: ("troop", "水炮兵·特上"),
}
TREASURE_NAMES: dict[int, str] = {}
CHARM_NAMES = {1: "御守", 2: "御守·极"}


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
