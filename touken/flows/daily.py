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

from ..runtime_paths import STATUS_DIR

from ..maa_adapter import Point, roi_4to4
from . import naihanka_report

# 白名单：带着"失败/停/跳过"等字样、但其实没翻车的消息，先放行再判红。
# （判红宁可严一点：没跑成的步骤必须如实 ✗，不许"没跑却标绿"——
#   2026-08-24 演练阵形页卡死，连环翻车 7 步成绩单却全绿的教训）
_PASS_RE = re.compile(
    r"模板匹配.{0,12}失败.{0,12}固定坐标|"  # 万屋购买按钮模板没中，兜底固定坐标
    r"已达到停止条件|"                      # 挖地/出阵按约定主动收工
    r"今天签过了|今天已经刀解过了|"          # 幂等跳过
    r"没有远征回来|没有启用常用安排|没有可领奖励|"
    r"无需重复挑战|"                        # 演练胜场已够
    r"可能派遣失败也可能已回本丸|"           # 远征结果不确定，日志里另有 ⚠️ 详述
    r"这局当死板版刷|"                      # 南瓜剪影库没加载，降级刷不是翻车
    r"收场再补|"                            # 挖地开工小判没读到，收工时补拍
    r"小判金额未识别|"                      # 异去提灯补充已成功，只是金额没读出来
    r"游戏自动行军已经停止|"                # 游戏自身的保护性停军，脚本会安全收尾
    r"不影响"                               # 明确标注不影响主线的旁路失败（快照/推送等）
)

# 判定步骤翻车的消息特征：没 x 到/找不到/未配置/停止/，停 收场等都是各流程
# 自己约定的"中止"话术，一律判红；个别误伤用上面的白名单捞回来。
_FAIL_RE = re.compile(
    r"失败|翻车|没能|没等到|没打开|没找到|没出现|没看到|没读到|没读全|没识别|"
    r"找不到|未配置|尚未配置|配置里没有|未开始|未找到|未识别|未确认|未检测|"
    r"无法|不可用|停止|卡死|卡在|强制停|没生效|没回来|"
    r"，停(?=[，。]|$)|超时|放弃|刀装未满警告|"
    r"可能成了也可能没成"
)


def _is_fail(msg: str) -> bool:
    if _PASS_RE.search(msg):
        return False
    return bool(_FAIL_RE.search(msg))


def _is_success_status(status: str) -> bool:
    """Detailed successes such as ``✓ 本次领取成功`` are still green."""
    return str(status).lstrip().startswith("✓")


def _practice_report_status(msg: str, current=None):
    """演练专项判分：打了却一场没赢（认不出人/阵形卡死/全输）不算绿。"""
    if "无需重复挑战，收工" in msg:
        return "✓ 已有胜场够数"
    if "收工：本次新赢 0 场" in msg:
        return "✗ 一场没赢"
    return current


def _equip_warning_status(msg: str, current=None):
    if "刀装未满警告" not in msg:
        return current
    if "没能安全取消" in msg:
        return "✗ 刀装未满，取消整备失败，出阵停止"
    return "⚠ 刀装未满，已取消出阵并跳过"


def _shop_report_status(msg: str, current=None):
    if "今日暖心礼包已售罄" in msg:
        return "✓ 此前已领取（售罄）"
    if "领取成功" in msg:
        return "✓ 本次领取成功"
    if "未找到暖心礼包" in msg:
        return "✗ 未找到暖心礼包"
    if "未识别到领取按钮" in msg:
        return "✗ 未识别到领取按钮，未点击"
    if "未检测到0价格弹窗" in msg:
        return "✗ 未确认0价，已取消"
    return current


class DailyMixin:
    """一键日课。依赖宿主类已注册的各流程 Mixin。"""

    def daily_stream(self, logout: bool = False, only=None, after: str = None,
                     sortie_override: dict = None, practice_override: dict = None,
                     expedition_override: list = None):
        """
        流式一键日课

        Args:
            logout: 最后是否下线（老参数，等价于 after="logout"）
            only: 只跑指定步骤（名字列表，如 ["签到","演练","出阵"]），
                  None = 全跑。面板勾选功能用的就是这个。
            after: 跑完干啥（可选，默认啥也不干——被黑屏吓过，必须手动选）：
                  "none"     啥也不干
                  "logout"   退出游戏
                  "shutdown" 退出游戏 + 关模拟器
                  "sleep"    退出游戏 + 关模拟器 + 电脑休眠
            sortie_override: 覆盖出阵安排（面板传的），如
                  {"mode":"none"} / {"mode":"raid","rounds":3} /
                  {"mode":"sortie","chapter":1,"map_no":1,"loops":2,"team_no":3}

        Yields:
            str: 执行状态消息
        """
        if after is None:
            after = "logout" if logout else "none"
        plan = self.config.get("daily", {})
        if sortie_override is not None:
            plan = dict(plan)
            plan["sortie"] = sortie_override
        if practice_override:
            plan = dict(plan)
            plan["practice"] = dict(practice_override)
        report = []
        wanted = set(only) if only else None

        def _w(name):
            return wanted is None or name in wanted

        # 断点续跑时往往不会勾「登录」。因此不能把更新检查寄托在登录步骤里；
        # 先于任何日课导航验一次，之后每个步骤开始前再验，避免把弹窗背后
        # 露出来的「目录」误当成可操作的本丸。
        update_state = yield from self._daily_update_gate()
        if update_state is None:
            yield "[日课] 游戏更新没有恢复完成，本次日课停止"
            return

        # ========== ① 登录 + 弹窗扫地 ==========
        if _w("登录"):
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
        # （开工/收工的例行盘点已砍掉：完整快照融进锻刀收工顺手拍，
        #   顶栏五资源靠各循环的 quick_peek 顺路更新，不再专程跑腿）
        steps = [
            ("签到", lambda: self.signin_stream()),
            ("万屋", lambda: self.claim_free_gift_stream()),
            ("演练", lambda: self.practice_stream(
                dry_run=False,
                team_no=plan.get("practice", {}).get("team_no"),
                formation_mode=plan.get("practice", {}).get("formation_mode"),
                formation_strategy=plan.get("practice", {}).get("formation_strategy"),
                formation=plan.get("practice", {}).get("formation"))),
            ("远征", lambda: self._daily_expedition_step(
                expedition_override,
                fallback_redispatch=plan.get("expedition_redispatch", "same"))),
            ("内番", lambda: self.naihanka_stream()),
            ("锻刀", lambda: self.forge_stream(times=plan.get("forge_times", 3))),
            ("刀解", lambda: self._dismantle_step()),
            ("合成", lambda: self.synthesize_stream()),
            ("任务奖励", lambda: self.claim_task_rewards_stream()),
            ("库存快照", lambda: self._closing_snapshot_stream(_w("锻刀"))),
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

        # 出阵插到任务奖励前面（就算没勾任务奖励，单勾出阵也能跑）
        seq = []
        for name, fn in steps:
            if name == "任务奖励":
                seq.append(("出阵", None))
            seq.append((name, fn))

        for name, fn in seq:
            if not _w(name):
                continue
            update_state = yield from self._daily_update_gate()
            if update_state is None:
                report.append((name, "✗ 游戏更新未完成"))
                yield f"[日课] 更新恢复失败，未开始{name}；后续步骤停止"
                break
            if name == "出阵":
                yield "========== ⑩ 出阵 =========="
                self.set_progress("daily:出阵")
                for msg in self._sortie_step(plan, report):
                    yield msg
                time.sleep(1.0)
                continue

            yield f"========== {titles[name]} =========="
            self.set_progress("daily:" + name)
            ok = True
            detail_status = None
            try:
                for msg in fn():
                    yield msg
                    if _is_fail(msg):
                        ok = False
                    if name == "万屋":
                        detail_status = _shop_report_status(msg, detail_status)
                    if name == "演练":
                        detail_status = _practice_report_status(msg, detail_status)
            except Exception as exc:
                ok = False
                yield f"[日课] {name}翻车: {exc}"
            report.append((name, detail_status or ("✓" if ok else "✗")))
            self._flush_report(report, finished=False)
            time.sleep(1.0)

        # ========== ⑬ 下线 ==========
        if after in ("logout", "shutdown", "sleep"):
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
        fails = [n for n, s in report if not _is_success_status(s)]
        yield "[日课] 全部跑完" + (f"，但有翻车项: {'、'.join(fails)}" if fails else "，全绿")

        # ========== 落盘最终成绩单 + 手机推送 ==========
        payload = self._flush_report(report, finished=True)
        if payload is None:
            yield "[日课] 成绩单落盘失败（不影响跑）"
        try:
            from ..notify import notify_daily_report, notify_destination
            destination = notify_destination()
            if payload and notify_daily_report(payload):
                yield (f"[日课] 成绩单已发送到 ntfy 频道「{destination}」；"
                       "手机订阅该频道后才能收到")
            elif not destination:
                yield "[日课] 未配置 ntfy 频道，成绩单只保存在本机"
            else:
                yield "[日课] ntfy 频道发送失败（网络或服务问题），成绩单已保存在本机"
        except Exception as exc:
            yield f"[日课] 手机推送翻车（不影响跑）: {exc}"

        # ========== ⑭ 收尾（可选项，推完成绩单才干，休眠放最后）==========
        if after in ("shutdown", "sleep"):
            yield "[日课] 关模拟器..."
            try:
                from ..emulator import shutdown_emulator
                mgr = self.config.get("emulator_manager")
                inst = int(self.config.get("emulator_instance", 0))
                if mgr and shutdown_emulator(mgr, inst):
                    yield "[日课] ✓ 模拟器已关闭，辛苦了"
                else:
                    yield "[日课] ⚠️ 模拟器没关成（没配管家路径？），你手动关一下"
            except Exception as exc:
                yield f"[日课] 关模拟器翻车（不影响成绩单）: {exc}"
        if after == "sleep":
            yield "[日课] 😴 成绩单已推送，电脑 10 秒后休眠，晚安"
            time.sleep(10)
            try:
                from ..emulator import sleep_computer
                sleep_computer()
            except Exception as exc:
                yield f"[日课] 休眠翻车: {exc}"

    def _daily_update_gate(self):
        """日课导航前的更新门卫；兼容只勾中间步骤的断点续跑。"""
        self.maa.screenshot(force=True)
        recovered = yield from self.recover_game_update_stream()
        if recovered is None:
            return None
        if recovered:
            yield "[日课] 游戏更新完成，先清理登录弹窗再继续日课"
            if not self._popup_sweep():
                yield "[日课] 更新后没能确认本丸已可操作"
                return None
            yield "[日课] ✓ 本丸已恢复，可以继续当前步骤"
        return recovered

    def _flush_report(self, report, finished: bool):
        """
        成绩单落盘。每跑完一步就写一次（finished=False），防超时被杀丢数据；
        全部跑完再写终版（finished=True）。看板 Widget 吃的就是这个文件。
        """
        try:
            import json as _json
            from pathlib import Path
            status_dir = STATUS_DIR
            status_dir.mkdir(exist_ok=True)
            fails = [n for n, s in report if not _is_success_status(s)]
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

    def _dismantle_step(self):
        """日课的刀解步：今天已经解过（比如锻刀收刀腾位置顺手解的）就跳过"""
        from .smith import dismantled_today
        if dismantled_today():
            yield "[日课] ✓ 今天已经刀解过了（锻刀收刀腾位置时顺手解的），这步跳过"
            return
        yield from self.dismantle_stream(max_dismantle=1)

    def _daily_expedition_step(self, routes, fallback_redispatch="same"):
        """收菜后按独立“远征”的常用安排补派；不读取自动排班。"""
        if routes is None:
            # 非面板调用保持旧配置兼容。
            yield from self.collect_expedition_stream(
                redispatch=fallback_redispatch)
            return

        yield from self.collect_expedition_stream(redispatch=None)
        if not routes:
            yield "[远征] 没有启用常用安排，本次只收取归来奖励"
            return

        from .expedition import _load_exp_record
        records = _load_exp_record()
        for route in routes:
            team = int(route["team_no"])
            record = records.get(str(team), {})
            try:
                started = time.mktime(time.strptime(
                    record["dispatched_at"], "%Y-%m-%d %H:%M:%S"))
                remain = max(0, int(
                    started + int(record["duration_min"]) * 60 - time.time()))
            except (KeyError, TypeError, ValueError):
                remain = 0
            if remain > 0:
                yield (f"[远征] 部队{team}仍在外面（约剩 {remain // 60} 分钟），"
                       "按常用安排跳过")
                continue
            if not route.get("era") or not route.get("map_slot"):
                yield f"[远征] 常用安排地图 {route.get('map_code')} 不存在，无法派遣"
                continue
            yield (f"[远征] 按常用安排派部队{team}去 {route['map_code']}"
                   f"「{route.get('map_name') or ''}」")
            yield from self.expedition_stream(
                era=int(route["era"]), map_slot=int(route["map_slot"]),
                team_no=team)

    def _sortie_step(self, plan, report):
        sortie_plan = plan.get("sortie", {"mode": "none"})
        mode = sortie_plan.get("mode", "none")
        try:
            if mode == "raid":
                ok = True
                equip_status = None
                for msg in self.raid_stream(
                        max_rounds=sortie_plan.get("rounds", 1),
                        team_no=sortie_plan.get("team_no"),
                        auto_buy_ticket=sortie_plan.get("auto_buy_ticket", False),
                        max_buys=sortie_plan.get("max_buys")):
                    yield msg
                    if _is_fail(msg):
                        ok = False
                    equip_status = _equip_warning_status(msg, equip_status)
                status = equip_status or ("✓" if ok else "✗")
                report.append(("出阵(活动)", status))
            elif mode == "sortie":
                ok = True
                equip_status = None
                for msg in self.sortie_stream(
                        chapter=sortie_plan["chapter"],
                        map_no=sortie_plan["map_no"],
                        team_no=sortie_plan.get("team_no", 3),
                        max_loops=sortie_plan.get("loops", 1),
                        auto_march=sortie_plan.get("auto_march", True),
                        formation_mode=sortie_plan.get("formation_mode", "manual"),
                        formation_strategy=sortie_plan.get("formation_strategy", "fixed"),
                        formation=sortie_plan.get("formation", "鱼鳞阵"),
                        repair_threshold=sortie_plan.get("repair_threshold", "light"),
                        injury_action=sortie_plan.get("repair_on_injury", "continue"),
                        auto_equip=sortie_plan.get("auto_equip", True),
                        retreat_before_boss=sortie_plan.get(
                            "retreat_before_boss", False),
                        rotate_captain=sortie_plan.get("rotate_captain", False),
                        rotate_captain_margin=sortie_plan.get(
                            "rotate_captain_margin", 10)):
                    yield msg
                    if _is_fail(msg):
                        ok = False
                    equip_status = _equip_warning_status(msg, equip_status)
                status = equip_status or ("✓" if ok else "✗")
                report.append(("出阵(推图)", status))
            elif mode == "pumpkin":
                ok = True
                equip_status = None
                watch = sortie_plan.get("watch_names") or []
                for msg in self.pumpkin_stream(
                        team_no=sortie_plan.get("team_no", 3),
                        difficulty=sortie_plan.get("difficulty", 1),
                        watch_names=watch or None,
                        max_skips=sortie_plan.get("max_skips", 4),
                        auto_refill=False):
                    yield msg
                    if _is_fail(msg):
                        ok = False
                    equip_status = _equip_warning_status(msg, equip_status)
                status = equip_status or ("✓" if ok else "✗")
                report.append(("出阵(南瓜)", status))
            elif mode == "yosari":
                ok = True
                equip_status = None
                for msg in self.yosari_stream(
                        map_no=sortie_plan.get("map_no", 1),
                        team_no=sortie_plan.get("team_no", 3),
                        max_loops=sortie_plan.get("loops", 1),
                        auto_refill=sortie_plan.get("auto_refill", False),
                        auto_march=sortie_plan.get("auto_march", True),
                        formation_mode=sortie_plan.get("formation_mode", "manual"),
                        formation_strategy=sortie_plan.get("formation_strategy", "fixed"),
                        formation=sortie_plan.get("formation", "鱼鳞阵"),
                        repair_threshold=sortie_plan.get("repair_threshold", "light"),
                        injury_action=sortie_plan.get("repair_on_injury", "continue"),
                        auto_equip=sortie_plan.get("auto_equip", True),
                        rotate_captain=sortie_plan.get("rotate_captain", False),
                        rotate_captain_margin=sortie_plan.get(
                            "rotate_captain_margin", 10)):
                    yield msg
                    if _is_fail(msg):
                        ok = False
                    equip_status = _equip_warning_status(msg, equip_status)
                status = equip_status or ("✓" if ok else "✗")
                report.append(("出阵(异去)", status))
            elif mode == "osaka":
                ok = True
                equip_status = None
                for msg in self.osaka_stream(
                        max_floors=sortie_plan.get("loops", 1),
                        team_no=sortie_plan.get("team_no", 3),
                        select_floor=sortie_plan.get("select_floor", False),
                        target_floor=sortie_plan.get("target_floor", 81),
                        formation_mode=sortie_plan.get("formation_mode", "manual"),
                        formation_strategy=sortie_plan.get("formation_strategy", "fixed"),
                        formation=sortie_plan.get("formation", "鱼鳞阵"),
                        repair_threshold=sortie_plan.get("repair_threshold", "light"),
                        injury_action=sortie_plan.get("repair_on_injury", "continue"),
                        auto_equip=sortie_plan.get("auto_equip", True)):
                    yield msg
                    if _is_fail(msg):
                        ok = False
                    equip_status = _equip_warning_status(msg, equip_status)
                status = equip_status or ("✓" if ok else "✗")
                report.append(("出阵(大阪城)", status))
            else:
                yield "[日课] 配置为不打，跳过"
        except Exception as exc:
            report.append(("出阵", f"✗ {exc}"))
            yield f"[日课] 出阵翻车: {exc}"

    # ========== 收工盘点（锻刀拍过就不重复跑腿） ==========

    def _closing_snapshot_stream(self, forge_ran: bool):
        """日课收尾的家底盘点：锻刀步骤收工时已经顺手拍过完整快照（含小判），
        跑了锻刀就跳过；锻刀被跳过的话才专程导航拍一次。"""
        if forge_ran:
            yield "[日课] 锻刀收工时已顺手盘点过家底（含小判），收工快照不再专程跑腿"
            return
        for msg in self.status_snapshot_stream(phase="after"):
            yield msg

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
        pt = self.maa.template_match("刀剑乱舞.png", threshold=0.8)
        if not pt:
            yield "[日课] 既不在本丸也找不到游戏图标（在奇怪的界面？），硬试登录"
            return

        # ⚠️ 广告担保层（7-29 实测翻车：模拟器广告里的像素跟图标模板撞脸，
        # 点下去直接触发下载了个别的游戏）。模板只是 55x55 图标图，没有文字，
        # 所以点击前必须 OCR 验明正身：真桌面图标正下方写着「刀剑乱舞」，广告没有。
        guard = roi_4to4(
            max(0, pt.x - 80), pt.y + 10,
            min(1280, pt.x + 80), min(720, pt.y + 110),
        )
        if not self.maa.ocr("刀剑乱舞", guard):
            yield "[日课] ⚠️ 找到疑似图标但底下没写「刀剑乱舞」——怕是广告，没敢点"
            return

        yield "[日课] 游戏没开，点图标启动（OCR 验明正身 ✓）..."
        self.maa.click(pt)
        for i in range(75):  # 最多等 150s
            time.sleep(2.0)
            self.maa.screenshot(force=True)
            if self.maa.exists("登录.png", threshold=0.7):
                yield f"[日课] 登录按钮出现（{i * 2 + 2}s）"
                return
            # 版本更新框会挡在登录前（「检测到更新」→ 选线路），偶尔查一次
            if i % 6 == 3:
                upd = self.maa.ocr("线路一", roi_4to4(200, 300, 900, 600))
                if upd:
                    yield "[日课] 检测到游戏更新，选线路一更新..."
                    self.maa.click(upd)
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
            # 内番报告屏：谁+1 在这儿，先读再点穿（自然收工的横幅在本丸随机蹦）
            if self.maa.ocr("内番报告", roi_4to4(*naihanka_report.REPORT_TITLE_ROI)):
                for msg in self._collect_report_gains():
                    print(msg)
                time.sleep(1.0)
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
