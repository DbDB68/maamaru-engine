# -*- coding: utf-8 -*-
"""
上层业务：手入（修复）——黑名单版

规矩（用户亲授）：
  1. 修复列表里每把刀的名字都是文字，OCR 认名字，不认图标
     （中伤/重伤的章会盖住极化樱花，图标路线天生残废）
  2. 黑名单 = 碰瓷队的极化太刀——他们带伤上班是故意的
     （中伤挨打触发真剑必杀），看到名字就跳过，绝对不修
  3. speedup_teams 里的部队（默认部队三=挖地队）：
     行首编号是"三之x"的，修的时候勾加速符秒修，修完继续打；
     其他队的就慢慢修，加速符省着
"""

import re
import time

from ..maa_adapter import roi_4to4, Point
from .. import sword_db

_TEAM_NUMERAL = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}


class RepairMixin:
    """手入。依赖宿主类的 navigate_to_stream、_click_point。"""

    def repair_stream(self, dry_run: bool = False, blacklist: list = None,
                      use_speedup: bool = None, speedup_teams: list = None):
        """
        流式手入：扫描修复列表，黑名单跳过，其余修掉

        Args:
            dry_run: True=只扫描报决策，一个按钮都不点（认人考试模式）
            blacklist: 运行时覆盖黑名单，None 则读配置
            speedup_teams: 运行时覆盖使用加速符的部队，None 则读配置

        Yields:
            str: 执行状态消息
        """
        # 给连续出阵等上层流程读取；每次调用都重新开始统计。
        self.last_repair_stats = {"repaired": 0, "speedups": 0, "skipped": 0}
        cfg = self.config.get("repair", {})
        if not cfg:
            yield "[手入] 未配置手入"
            return

        # 黑名单：运行时覆盖 > 配置
        if blacklist is None:
            blacklist = cfg.get("blacklist", [])
        bl_ids = set()
        for zh in blacklist:
            r = sword_db.find_by_name(zh)
            if r:
                bl_ids.add(r[0])
        if use_speedup is False:
            speedup_teams = []
        elif speedup_teams is None:
            speedup_teams = cfg.get("speedup_teams", [])
        speedup_marks = [_TEAM_NUMERAL[t] + "之" for t in speedup_teams
                         if t in _TEAM_NUMERAL]

        yield f"[手入] 黑名单 {len(blacklist)} 人（解析出 {len(bl_ids)} 个ID），" \
              f"加速部队标记 {speedup_marks or '无'}"

        # ========== 1. 导航到修复 ==========
        yield "[手入] 正在导航到修复..."
        for nav_msg in self.navigate_to_stream("修复"):
            yield nav_msg
        if self.current_location != "修复":
            yield "[手入] 到达修复失败"
            return
        time.sleep(1.0)

        # 修复落地页是「修复状况」（手入槽列表），要点空闲槽才进选人界面
        if not self._open_select_screen(cfg):
            yield "[手入] 没有空闲修复槽（都在修？）或选人界面没打开，停"
            return

        # ========== 2. 逐页扫描 ==========
        seen = set()          # 扫过的行（编号+名字），翻页去重
        repaired = 0
        skipped = 0
        no_new_pages = 0

        for page in range(10):  # 安全上限
            page_new = 0
            rows, junk = self._scan_page(cfg)
            if junk:
                yield f"[手入] （本页过滤掉的乱码/伤势章：{junk}）"
            for row in rows:
                prefix, name, name_y = row["prefix"], row["name"], row["y"]

                key = f"{prefix}|{name}"
                if key in seen:
                    continue
                seen.add(key)
                page_new += 1

                # ---- 决策 ----
                hit = sword_db.find_by_name(name)
                sid = hit[0] if hit else None
                std_name = hit[1]["name_zh"] if hit else name
                is_black = (sid in bl_ids) or any(b in name for b in blacklist)
                need_speed = any(mark in prefix for mark in speedup_marks)

                if is_black:
                    skipped += 1
                    self.last_repair_stats["skipped"] = skipped
                    if hasattr(self, "record_event"):
                        self.record_event("repair.skipped", name=std_name,
                                          sword_id=sid, team_mark=prefix,
                                          reason="blacklist")
                    yield f"[手入] {prefix} {std_name} → 黑名单（碰瓷队带伤上班），跳过"
                    continue

                tag = "修+加速符" if need_speed else "修（不用加速符）"
                if dry_run:
                    yield f"[手入] {prefix} {std_name} → {tag} [演习]"
                    continue

                # ---- 真修 ----
                yield f"[手入] {prefix} {std_name} → {tag}"
                ok = False
                for fix_msg in self._repair_one(cfg, name_y, need_speed):
                    yield fix_msg
                    if fix_msg.endswith("已开工"):
                        ok = True
                if ok:
                    repaired += 1
                    self.last_repair_stats["repaired"] = repaired
                    if need_speed:
                        self.last_repair_stats["speedups"] += 1
                    if hasattr(self, "record_event"):
                        self.record_event("repair.queued", name=std_name,
                                          sword_id=sid, team_mark=prefix,
                                          speedup=need_speed)
                    if need_speed:
                        # 游戏的奇怪缓存：加速手入已经完成，但如果立刻去编队，
                        # 伤势章仍可能残留。必须离开手入再重新进入一次，等价于
                        # 把人从手入室“接出来”，编队状态才会刷新。
                        yield f"[手入] {std_name} 已加速修好，重新进入手入刷新编队状态..."
                        for nav_msg in self.navigate_to_stream("本丸"):
                            yield nav_msg
                        if self.current_location != "本丸":
                            yield "[手入] 加速修复后没能返回本丸，无法确认伤势已刷新，停"
                            return
                        for nav_msg in self.navigate_to_stream("修复"):
                            yield nav_msg
                        if self.current_location != "修复":
                            yield "[手入] 加速修复后没能重新进入手入，无法接回成员，停"
                            return
                        yield f"[手入] ✓ 已重新进入手入，{std_name} 的伤势状态应已刷新"
                    # 修完会退回修复状况页，重新点槽进选人界面；
                    # 列表也会重排，本页剩下的行作废重新扫
                    if not self._open_select_screen(cfg):
                        yield "[手入] 修完后没能重新打开选人界面，停"
                        return
                    break
                else:
                    yield f"[手入] {std_name} 没能修成，跳过它继续"
            else:
                # 本页 5 行都处理完没被打断 → 翻页
                pass

            if page_new == 0:
                no_new_pages += 1
                if no_new_pages >= 2:
                    break
            else:
                no_new_pages = 0

            if dry_run:
                # 演习模式翻页继续认人
                self._scroll_list(cfg)
                time.sleep(1.0)
                continue
            # 真修模式：列表变了，直接重扫当前页，不翻页
            if page_new == 0:
                self._scroll_list(cfg)
                time.sleep(1.0)

        if dry_run:
            yield f"[手入] 演习结束：共认出 {len(seen)} 把待修刀，" \
                  f"黑名单跳过 {skipped} 把"
        else:
            yield f"[手入] ✅ 完事：修了 {repaired} 把，黑名单跳过 {skipped} 把"
        return

    # ==================== 内部 ====================

    def _open_select_screen(self, cfg) -> bool:
        """在修复状况页点空闲槽，等刀剑男士选择界面打开"""
        free_ocr = cfg["free_slot_ocr"]
        free_roi = roi_4to4(*free_ocr["roi"])
        ui_ocr = cfg["select_ui_ocr"]
        ui_roi = roi_4to4(*ui_ocr["roi"])

        free = None
        for _ in range(6):
            self.maa.screenshot(force=True)
            free = self.maa.ocr(expected=free_ocr["expected"], roi=free_roi)
            if free:
                break
            time.sleep(0.5)
        if not free:
            return False
        self.maa.click(free)
        time.sleep(1.0)

        for _ in range(10):
            self.maa.screenshot(force=True)
            if self.maa.ocr(expected=ui_ocr["expected"], roi=ui_roi):
                time.sleep(0.5)
                return True
            time.sleep(0.5)
        return False

    def _scan_page(self, cfg) -> tuple:
        """
        整列 OCR 当前可见的行：名字列 + 编号列，按 y 坐标配对。
        翻页后行位置不对齐固定网格，所以不用固定行位，
        OCR 结果自带的中心点 y 就是行的位置。

        列里会混进伤势章文字（中伤/重伤）和乱码，
        名字必须过 sword_db 字典验证才算数，编号必须
        符合"三之x"格式才保留——认不出的宁可跳过不乱修。

        Returns:
            (rows, junk) — rows: [{"prefix","name","y"}]；junk: 被过滤的文本
        """
        # 翻页后画面变了，必须强制截图，不然 OCR 读的是旧缓存图
        self.maa.screenshot(force=True)
        names = self.maa.ocr_all(roi_4to4(*cfg["name_col_roi"]))
        prefixes = self.maa.ocr_all(roi_4to4(*cfg["prefix_col_roi"]))

        # 编号列先过滤：只留"三之x"格式的
        valid_prefixes = [
            (p.strip(), pt) for p, pt in prefixes
            if re.match(r"^[一二三四五]之[一二三四五六]$", p.strip())
        ]

        rows, junk = [], []
        for name, pt in names:
            name = name.strip()
            # 名字至少 2 个汉字，且必须在刀剑字典里查得到
            if len(name) < 2 or not sword_db.find_by_name(name):
                junk.append(name)
                continue
            best_prefix, best_dy = "", 40
            for pfx, ppt in valid_prefixes:
                dy = abs(ppt.y - pt.y)
                if dy < best_dy:
                    best_prefix, best_dy = pfx, dy
            rows.append({"prefix": best_prefix, "name": name, "y": pt.y})
        return rows, junk

    def _scroll_list(self, cfg):
        x1, y1 = cfg["scroll_from"]
        x2, y2 = cfg["scroll_to"]
        # 滑动要快于 400ms 会被游戏吞掉，实测 800ms 才稳
        self.maa.swipe(x1, y1, x2, y2, 800)

    def _repair_one(self, cfg, name_y: int, need_speed: bool):
        """点选择 → （可选）勾加速符 → 修复开始 → 确认"""
        sx = cfg["select_btn_x"]
        self.maa.click(Point(sx, name_y + cfg["select_offset_y"]))
        time.sleep(1.2)

        if need_speed:
            # 优先 OCR 找"使用"二字，复选框在它左边；找不到再用固定坐标
            use_ocr = cfg.get("speedup_use_ocr")
            pt = None
            if use_ocr:
                self.maa.screenshot(force=True)
                pt = self.maa.ocr(expected=use_ocr["expected"],
                                  roi=roi_4to4(*use_ocr["roi"]))
            if pt:
                self.maa.click(Point(pt.x - 33, pt.y))
            else:
                cx, cy = cfg["speedup_checkbox"]
                self.maa.click(Point(cx, cy))
            time.sleep(0.5)

        self.maa.screenshot(force=True)
        start = self.maa.template_match(cfg["start_button"]["template"])
        if not start:
            yield "[手入] 找不到修复开始按钮"
            return
        self.maa.click(start)
        time.sleep(1.2)

        # 可能有二次确认弹窗（确定/确认都试试）
        self.maa.screenshot(force=True)
        for tpl in ("通用_确定.png", "team/是.png"):
            confirm = self.maa.template_match(tpl)
            if confirm:
                self.maa.click(confirm)
                time.sleep(1.0)
                break

        yield "[手入] 已开工"
