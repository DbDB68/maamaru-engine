# -*- coding: utf-8 -*-
"""头像认人：刀帐一览行带里 matchTemplate 小脸模板。

模板在 resource/base/image/头像/，命名 {番号}_{普|极}_{名字}[_{tag}].png
（带中伤 tag 的 4 张：莺丸/明石国行/烛台切光忠/鹤丸国永），全部裁自
MuMu 运行帧（同源合规）。番号→sword_id 的桥接走文件名里的中文名过
sword_db.find_by_name——sword_db 没有番号字段，中文名是唯一可靠的桥；
名册接不住的模板加载时如实记下跳过，不静默。
"""

import re
from pathlib import Path

from . import sword_db

_AVATAR_FILE_RE = re.compile(r"^(\d{4})_(普|极)_(.+?)(?:_([^_]+))?$")

# 身份采纳阈值：2026-09-21 真帧试配（.tmp/avatar_probe.py）161 张全量
# 匹配，真值全部榜首 0.9355~1.0000，次高（撞脸王堀川国广）最高 0.7549，
# margin ≥0.19——0.88/0.08 离两端都有富余。
SCORE_MIN = 0.88
MARGIN_MIN = 0.08
# 形态结论的加门槛：同刀普极两张都在库里时，命中形态要压过另一形态这么多
FORM_MARGIN_MIN = 0.05

# 形态结论总开关：2026-09-21 离线校准（.tmp/avatar_calib.py，sweep 40 页
# 真帧 vs 快照 #19 badge 已确认形态）只有 54/79 一致——25 把双形态刀疑似
# 普/极模板标签贴反（0122_普_狮子王 对 badge 确认极化的帧打 1.0000，而
# 普极模板互贴仅 0.54，两张脸确实不同；山姥切国广同页普极两振的命中正好
# 交叉）。模板库修正前形态结论一律不下（观测照记）；修正后翻 True 并重跑
# 校准，对 badge 已确认行 100% 一致才准留 True。
AVATAR_FORM_ENABLED = False

_TEMPLATE_CACHE = {}


def load_avatar_templates(resource_dir):
    """加载头像模板，按资源目录进程内缓存。返回 (templates, skipped)：
    templates 每项 {no, form, name, tag, sword_id, name_zh, path, img}；
    skipped 是 [(文件名, 原因)]——文件名不合规/名册接不住/图读不出，
    如实记下不静默。"""
    key = str(resource_dir)
    if key in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[key]
    import cv2
    import numpy as np
    folder = Path(resource_dir) / "image" / "头像"
    templates, skipped = [], []
    for path in sorted(folder.glob("*.png")):
        m = _AVATAR_FILE_RE.match(path.stem)
        if not m:
            skipped.append((path.name, "文件名不合 番号_形态_名字[_tag] 格式"))
            continue
        no, form, name, tag = m.groups()
        found = sword_db.find_by_name(name, fuzzy=False)
        if not found:
            skipped.append((path.name, f"名册接不住「{name}」"))
            continue
        sword_id, info = found
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8),
                           cv2.IMREAD_COLOR)
        if img is None:
            skipped.append((path.name, "图片读不出来"))
            continue
        templates.append({"no": no, "form": form, "name": name, "tag": tag,
                          "sword_id": sword_id,
                          "name_zh": info.get("name_zh") or info["name"],
                          "path": path, "img": img})
    _TEMPLATE_CACHE[key] = (templates, skipped)
    return templates, skipped


def match_avatar(band_img, templates):
    """行带图里找最佳头像：全量 matchTemplate(TM_CCOEFF_NORMED)。

    返回 {sword_id, name_zh, form, tag, score, margin, forms_in_library,
    form_rival_score} 或 None（图空/无模板/模板全比带大）。
    margin = 榜首分 − 次高分（次高取不同 sword_id——同刀普极/中伤差分
    不该稀释身份 margin）；forms_in_library 是该刀在库里的形态集合，
    form_rival_score 是同刀另一形态的最高分（单形态库为 None），
    两个字段给形态结论的保守门槛用。
    """
    import cv2
    if band_img is None or getattr(band_img, "size", 0) == 0 or not templates:
        return None
    scores = []
    for tpl in templates:
        img = tpl["img"]
        if img.shape[0] > band_img.shape[0] or img.shape[1] > band_img.shape[1]:
            continue
        res = cv2.matchTemplate(band_img, img, cv2.TM_CCOEFF_NORMED)
        _mn, mx, _ml, _loc = cv2.minMaxLoc(res)
        scores.append((float(mx), tpl))
    if not scores:
        return None
    scores.sort(key=lambda s: s[0], reverse=True)
    top_score, top_tpl = scores[0]
    second = next((s for s, t in scores[1:]
                   if t["sword_id"] != top_tpl["sword_id"]), 0.0)
    rivals = [s for s, t in scores
              if t["sword_id"] == top_tpl["sword_id"]
              and t["form"] != top_tpl["form"]]
    return {"sword_id": top_tpl["sword_id"], "name_zh": top_tpl["name_zh"],
            "form": top_tpl["form"], "tag": top_tpl["tag"],
            "score": round(top_score, 4),
            "margin": round(top_score - second, 4),
            "forms_in_library": sorted({t["form"] for t in templates
                                        if t["sword_id"]
                                        == top_tpl["sword_id"]}),
            "form_rival_score": round(max(rivals), 4) if rivals else None}


def avatar_identity_adopted(hit) -> bool:
    """头像身份是否够格采纳（捞回/对不上报警用；互证不卡阈值，分数入证即可）"""
    return bool(hit) and hit["score"] >= SCORE_MIN \
        and hit["margin"] >= MARGIN_MIN


def avatar_form_status(hit):
    """头像形态结论（保守）：该刀库里普极两张都有 + 命中分 ≥ SCORE_MIN +
    压过同刀另一形态 ≥ FORM_MARGIN_MIN 才下结论，其余一律 None 只记观测。
    中伤 tag 不影响结论（身份照认、形态照给，tag 已在观测里）。
    总开关 AVATAR_FORM_ENABLED 关闭期间（模板库普/极标签待修正）一律 None。"""
    if not AVATAR_FORM_ENABLED or not hit:
        return None
    if set(hit.get("forms_in_library") or ()) != {"普", "极"}:
        return None
    rival = hit.get("form_rival_score")
    if rival is None:
        return None
    if hit["score"] >= SCORE_MIN and hit["score"] - rival >= FORM_MARGIN_MIN:
        return "normal" if hit["form"] == "普" else "kiwame"
    return None
