# -*- coding: utf-8 -*-
"""
上层业务：一键日课——把每天的活儿按顺序串起来

流程（用户排的）：
  ① 登录（含登录弹窗扫地：特别登录礼物/公告 全关，不然导航全被挡）
  ② 签到（公告里的每日奖励，幂等保险）
  ③ 万屋免费鸡蛋（暖心礼包）
  ④ 演练（认人避战，赢够收工）
  ⑤ 远征（收菜 + 顺手再派）
  ⑥ 内番（安排上工，24小时的活儿早点派）
  ⑦ 锻刀（每日3炉，收完成的+点空闲的，刀位满了去刀解腾位置）
  ⑧ 刀解（白名单一把，任务奖励加速符）
  ⑨ 合成（白名单喂一把）
  ⑩ 炼糖（收件箱清狗粮 + 习合循环）
  ⑪ 出阵（配置驱动：活动=raid / 普通图=sortie / 不打=none）
  ⑫ 领任务奖励
  ⑬ 下线（还没做，可选）

设计原则：每一步独立 try + 消息关键字判成败，翻车不拖死后面，最后给真实成绩单。

冷启动血泪教训：
  login() 各步是在加载画面空点的（游戏还没到本丸），登录礼物/公告弹窗
  是之后才不紧不慢蹦出来的——所以登录后必须 _popup_sweep() 边等本丸边关弹窗。
  特别登录礼物的"今日不再弹出"和模板长得不一样，但 X 就是 通用_关闭.png。
"""

import re
import time

from ..maa_adapter import Point

# 判定步骤翻车的消息特征（别写太宽：'失败'会误伤"模板匹配失败，使用固定坐标"这种兜底）
_FAIL_RE = re.compile(r"到达.{0,8}失败|没打开|放弃|超时|翻车|没能|没等到")


def _is_fail(msg: str) -> bool:
    return bool(_FAIL_RE.search(msg))


class DailyMixin:
    """一键日课。依赖宿主类已注册的各流程 Mixin。"""

    def daily_stream(self, logout: bool = False):
        """
        流式一键日课

        Args:
            logout: 最后是否下线（还没实现，先占坑）

        Yields:
            str: 执行状态消息
        """
        plan = self.config.get("daily", {})
        report = []

        # ========== ① 登录 + 弹窗扫地 ==========
        yield "========== ① 登录 =========="
        try:
            for msg in self._ensure_game_started():
                yield msg
            self.login()
            if self._popup_sweep():
                report.append(("登录", "✓"))
            else:
                report.append(("登录", "✗ 没到本丸"))
                yield "[日课] 登录后没等到本丸，后面大概率连环翻车"
        except Exception as exc:
            report.append(("登录", f"✗ {exc}"))
            yield f"[日课] 登录翻车: {exc}（可能已在游戏内，继续）"
        self._flush_report(report, finished=False)
        time.sleep(1.0)

        # ========== ②~⑧ 各步 ==========
        steps = [
            ("签到", lambda: self.signin_stream()),
            ("万屋", lambda: self.claim_free_gift_stream()),
            ("演练", lambda: self.practice_stream(dry_run=False)),
            ("远征", lambda: self.collect_expedition_stream(
                redispatch=plan.get("expedition_redispatch", "same"))),
            ("内番", lambda: self.naihanka_stream()),
            ("锻刀", lambda: self.forge_stream(times=plan.get("forge_times", 3))),
            ("刀解", lambda: self.dismantle_stream(max_dismantle=1)),
            ("合成", lambda: self.synthesize_stream()),
            ("任务奖励", lambda: self.claim_task_rewards_stream()),
            ("库存快照", lambda: self.status_snapshot_stream()),
        ]
        titles = {
            "签到": "② 签到",
            "万屋": "③ 万屋免费鸡蛋",
            "演练": "④ 演练",
            "远征": "⑤ 远征",
            "内番": "⑥ 内番",
            "锻刀": "⑦ 锻刀",
            "刀解": "⑧ 刀解",
            "合成": "⑨ 合成",
            "任务奖励": "⑪ 领任务奖励",
            "库存快照": "⑫ 库存快照（看板数据）",
        }

        for name, fn in steps:
            if name == "任务奖励":
                # ⑪ 出阵插在任务前面
                yield "========== ⑩ 出阵 =========="
                for msg in self._sortie_step(plan, report):
                    yield msg
                time.sleep(1.0)

            yield f"========== {titles[name]} =========="
            ok = True
            try:
                for msg in fn():
                    yield msg
                    if _is_fail(msg):
                        ok = False
            except Exception as exc:
                ok = False
                yield f"[日课] {name}翻车: {exc}"
            report.append((name, "✓" if ok else "✗"))
            self._flush_report(report, finished=False)
            time.sleep(1.0)

        # ========== ⑬ 下线 ==========
        if logout:
            yield "========== ⑬ 下线 =========="
            try:
                for msg in self.logout_stream():
                    yield msg
            except Exception as exc:
                yield f"[日课] 下线翻车: {exc}"

        # ========== 成绩单 ==========
        yield "========== 日课成绩单 =========="
        for name, status in report:
            yield f"  {name}: {status}"
        fails = [n for n, s in report if s != "✓"]
        yield "[日课] 全部跑完" + (f"，但有翻车项: {'、'.join(fails)}" if fails else "，全绿")

        # ========== 落盘最终成绩单 + 手机推送 ==========
        payload = self._flush_report(report, finished=True)
        if payload is None:
            yield "[日课] 成绩单落盘失败（不影响跑）"
        try:
            from ..notify import notify_daily_report
            if payload and notify_daily_report(payload):
                yield "[日课] 成绩单已推到手机"
            else:
                yield "[日课] 手机推送没发出去（没启用或网络问题），不影响"
        except Exception as exc:
            yield f"[日课] 手机推送翻车（不影响跑）: {exc}"

    def _flush_report(self, report, finished: bool):
        """
        成绩单落盘。每跑完一步就写一次（finished=False），防超时被杀丢数据；
        全部跑完再写终版（finished=True）。看板 Widget 吃的就是这个文件。
        """
        try:
            import json as _json
            from pathlib import Path
            status_dir = Path(__file__).resolve().parent.parent.parent / "status"
            status_dir.mkdir(exist_ok=True)
            fails = [n for n, s in report if s != "✓"]
            payload = {
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "finished": finished,
                "all_green": finished and not fails,
                "steps": [{"name": n, "status": s} for n, s in report],
            }
            (status_dir / "latest_report.json").write_text(
                _json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload
        except Exception:
            return None

    # ========== 出阵步 ==========

    def _sortie_step(self, plan, report):
        sortie_plan = plan.get("sortie", {"mode": "none"})
        mode = sortie_plan.get("mode", "none")
        try:
            if mode == "raid":
                ok = True
                for msg in self.raid_stream(
                        max_rounds=sortie_plan.get("rounds", 1),
                        team_no=sortie_plan.get("team_no")):
                    yield msg
                    if _is_fail(msg):
                        ok = False
                report.append(("出阵(活动)", "✓" if ok else "✗"))
            elif mode == "sortie":
                ok = True
                for msg in self.sortie_stream(
                        chapter=sortie_plan["chapter"],
                        map_no=sortie_plan["map_no"],
                        team_no=sortie_plan.get("team_no", 3)):
                    yield msg
                    if _is_fail(msg):
                        ok = False
                report.append(("出阵(推图)", "✓" if ok else "✗"))
            else:
                yield "[日课] 配置为不打，跳过"
        except Exception as exc:
            report.append(("出阵", f"✗ {exc}"))
            yield f"[日课] 出阵翻车: {exc}"

    # ========== 冷启动：游戏没开就先点图标 ==========

    def _ensure_game_started(self):
        """
        检查游戏开没开：在本丸就跳过；在模拟器桌面就点刀剑乱舞图标等登录按钮
        （定时任务跑的时候游戏可能关着）
        """
        self.maa.screenshot(force=True)
        if self.maa.exists("目录.png", threshold=0.7):
            yield "[日课] 游戏已在本丸，直接开跑"
            return
        pt = self.maa.template_match("刀剑乱舞.png", threshold=0.7)
        if not pt:
            yield "[日课] 既不在本丸也找不到游戏图标（在奇怪的界面？），硬试登录"
            return
        yield "[日课] 游戏没开，点图标启动..."
        self.maa.click(pt)
        for i in range(75):  # 最多等 150s
            time.sleep(2.0)
            self.maa.screenshot(force=True)
            if self.maa.exists("登录.png", threshold=0.7):
                yield f"[日课] 登录按钮出现（{i * 2 + 2}s）"
                return
        yield "[日课] 等登录按钮超时，硬试登录"

    # ========== 登录后弹窗扫地 ==========

    def _popup_sweep(self, max_rounds: int = 30) -> bool:
        """
        边等本丸边扫地：登录后本丸不安静——特别登录礼物/公告弹窗要关 X，
        远征归来/内番结束/修行结束的结算动画和对话要点点点往前推。
        连续 2 轮看到目录按钮且没弹窗可关、没动画在演，才算真正落地。

        Returns:
            是否到达本丸
        """
        clean = 0
        for _ in range(max_rounds):
            self.maa.screenshot(force=True)
            acted = False
            for tpl in ("今日不再弹出.png", "通用_关闭.png"):
                pt = self.maa.template_match(tpl, threshold=0.7)
                if pt:
                    self.maa.click(pt)
                    time.sleep(1.5)
                    acted = True
                    break
            if acted:
                clean = 0
                continue
            if self.maa.exists("目录.png", threshold=0.7):
                clean += 1
                if clean >= 2:
                    # 看着到本丸了还不算数——15:00 实测翻车教训：结算动画余波里
                    # 目录按钮看得见但点了没反应，连环导航失败。必须真开一次目录
                    # 验证界面稳了，顺手回本体本丸，才算落地。
                    if self._probe_nav_ready():
                        return True
                    clean = 0
            else:
                # 没弹窗也没目录按钮：在演结算动画/对话/加载，点跳过点往前推
                # (993,690) 是内番对话验证过的跳过点，结算动画也是点哪都前进
                self.maa.click(Point(993, 690))
                clean = 0
            time.sleep(2.0)
        return False

    def _probe_nav_ready(self) -> bool:
        """
        落地探针：本丸看着到了，再验一刀——目录能不能真打开。
        能打开就顺手点"本丸"回本体（也是后续步骤的安全出发位），返回 True。
        """
        pt = self.maa.template_match("目录.png", threshold=0.7)
        if not pt:
            return False
        self.maa.click(pt)
        for _ in range(4):
            time.sleep(0.7)
            self.maa.screenshot(force=True)
            if self.maa.exists("menu/ui目录.png"):
                self.current_location = "通用入口"
                return self.navigate_to("本丸")
        return False
