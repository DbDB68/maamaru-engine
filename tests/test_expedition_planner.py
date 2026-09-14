# -*- coding: utf-8 -*-
"""可解释远征纸面规划器 v1 · 契约测试（expedition_planner）。

钉死的规矩：
- E2（元寇防垒）三硬条件：总等级 260、至少一把枪、至少三振，分别不足都不可行；
- 修行/手入剔除具体刀；受伤（含重伤）不剔除，只如实展示；
- 近侍只扣本人一振：多号机按多重集容量（2 振-1=1 可用、1 振-1=0）、
  普通/极化同位刀不连坐；身份不清 → needs_confirmation，不封家族也不伪判安全；
- same_team_exclusion_key 只管同队互斥，不参与近侍判定；
- 默认保一支队在家；显式 allow_all_teams_away 才五队全出且带醒目警告；
- 樱吹雪阈值 50（49 不算）；大成功只给定性，不编概率；
- 默认目标 加速符>小判>最缺基础资源，调用方可覆盖；
- 规则不完整的图只给 rule_incomplete；事实缺失整卷降级。
"""
import tempfile
import time
import unittest
from pathlib import Path

from touken.expedition_planner import (SAKURA_FATIGUE_MIN, load_maps,
                                       most_lacking_base_resource,
                                       normalize_goals, plan_expeditions)
from touken.honmaru_profile import build_honmaru_profile
from touken.telemetry import TelemetryStore

HASEBE = "touken_118_heshikiri_hasebe"
YARI = "touken_065_tonbokiri"        # 蜻蛉切（枪）
MIKA = "touken_003_mikazuki"         # 三日月宗近（太刀）
KOGI = "touken_005_kogitsunemaru"    # 小狐丸（太刀）
MAEDA = "touken_029_maeda"           # 前田藤四郎（短刀）

NOW = 1_757_000_000  # 现代时间戳；盘点/roster 观测在其前 15 分钟内，
                     # 不触发 24h 陈旧警告（Windows localtime 不支持负时间戳）
INVENTORY = {"木炭": 500, "玉钢": 800, "冷却材": 60, "砥石": 900}


def _store() -> TelemetryStore:
    return TelemetryStore(Path(tempfile.mkdtemp()) / "telemetry.db")


def _row(catalog_id, name, **kw):
    row = {"sword_id": catalog_id, "name_zh": name, "level": 99,
           "tou_level": 1, "survival": 50, "survival_max": 50,
           "fatigue": 100, "fatigue_max": 100, "stats": {"打击": 55},
           "kiwame_date": None, "locked": 1, "page_no": 1}
    row.update(kw)
    return row


def _slot(slot, catalog_id=MIKA, name="三日月宗近", slot_status="occupied",
          **kw):
    base = {"slot": slot, "slot_status": slot_status, "name_raw": name,
            "name": name, "name_status": "recognized",
            "sword_catalog_id": catalog_id, "sword_type": "太刀",
            "level": 99, "fatigue": 100, "survival": 50, "survival_max": 50,
            "injury": "none", "kiwame_status": "normal", "unknown_fields": []}
    base.update(kw)
    return base


def _profile(store, rows, rosters, captured_at=None):
    captured_at = NOW - 900 if captured_at is None else captured_at
    store.save_sword_snapshot(rows, owned=len(rows), capacity=300, missing=0,
                              captured_at=captured_at,
                              source="owned_inventory")
    for team_no, slots in rosters.items():
        store.record_event("team_roster.observed", {
            "team_no": team_no, "slots": slots,
            "observation_status": "complete", "source": "formation_page"})
        store._conn().execute(
            "UPDATE events SET ts = ? WHERE id = (SELECT MAX(id) FROM events)",
            (captured_at + 50,))
        store._conn().commit()
    return build_honmaru_profile(store)


def _rules(total=10, min_members=None, required=None, completeness="complete"):
    return {"total_level": total, "min_members": min_members,
            "required_types": required, "completeness": completeness,
            "unknown_aspects": ([] if completeness == "complete"
                                else ["min_members", "required_types"]),
            "server": "cn", "source": "测试规则", "verified_at": "2026-09-14"}


def _map(name, rules, duration=60, **yields):
    m = {"era": 9, "slot": 1, "name": name, "duration_min": duration,
         "exp_saniwa": 0, "exp_sword": 0, "木炭": 0, "玉钢": 0, "冷却材": 0,
         "砥石": 0, "委托符": 0, "加速符": 0, "小判": 0, "rules": rules}
    m.update(yields)
    return m


def _facts(attendant=None, training=None, repair=None):
    return {"attendant": attendant, "training": training or [],
            "repair": repair or []}


def _plan(profile, maps, facts, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("inventory", INVENTORY)
    # 测试默认显式确认「无进行中远征」，不碰真实 expeditions.json
    kw.setdefault("active_expeditions", {})
    return plan_expeditions(profile, maps=maps, member_facts=facts, **kw)


def _e2_team(store, levels=(99, 99, 99), types=("枪", "太刀", "打刀")):
    """一支满足 E2 的队（默认）：枪+太刀+打刀各一振，等级可调。"""
    catalogs = {"枪": (YARI, "蜻蛉切"), "太刀": (MIKA, "三日月宗近"),
                "打刀": (HASEBE, "压切长谷部")}
    rows, slots = [], []
    for i, (lv, tp) in enumerate(zip(levels, types), start=1):
        cid, cname = catalogs[tp]
        rows.append(_row(cid, cname, level=lv))
        slots.append(_slot(i, catalog_id=cid, name=cname, sword_type=tp,
                           level=lv))
    rows.append(_row(KOGI, "小狐丸"))  # 近侍候补（不在队里）
    return rows, slots


class MapEligibilityTests(unittest.TestCase):
    """工单第七节第一条：E2 三条件分别不足都不可行，全满足才可行。"""

    def _run(self, levels=(99, 99, 99), types=("枪", "太刀", "打刀")):
        store = _store()
        rows, slots = _e2_team(store, levels, types)
        profile = _profile(store, rows, {2: slots})
        maps = {"E2": load_maps()["E2"]}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        return _plan(profile, maps, facts, allow_all_teams_away=True)

    def test_e2_all_conditions_met_is_executable(self):
        result = self._run()  # 99×3=297 ≥ 260，枪 1 振，3 振
        assignment = result["plan"]["assignments"][0]
        self.assertEqual(assignment["map_code"], "E2")
        self.assertEqual(assignment["confidence"], "executable")
        self.assertEqual(result["plan"]["confidence"], "executable")
        why = "；".join(assignment["why_eligible"])
        self.assertIn("297", why)
        self.assertIn("枪", why)
        self.assertIn("3 振", why)

    def test_e2_total_level_short_is_infeasible(self):
        result = self._run(levels=(80, 80, 80))  # 240 < 260
        self.assertEqual(result["plan"]["assignments"], [])
        reasons = "；".join(result["infeasible"][0]["reasons"])
        self.assertIn("240", reasons)
        self.assertIn("260", reasons)

    def test_e2_without_yari_is_infeasible(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row("touken_007_ishikirimaru", "石切丸")]
        slots = [_slot(1), _slot(2, catalog_id=KOGI, name="小狐丸"),
                 _slot(3, catalog_id="touken_007_ishikirimaru", name="石切丸")]
        profile = _profile(store, rows, {2: slots})
        maps = {"E2": load_maps()["E2"]}
        result = _plan(profile, maps, _facts(), allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertIn("枪", "；".join(result["infeasible"][0]["reasons"]))

    def test_e2_too_few_members_is_infeasible(self):
        store = _store()
        rows, slots = _e2_team(store, (99, 99), ("枪", "太刀"))
        slots = slots[:2]
        rows = rows[:2] + [_row(KOGI, "小狐丸")]
        profile = _profile(store, rows, {2: slots})
        maps = {"E2": load_maps()["E2"]}
        result = _plan(profile, maps, _facts(), allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertIn("最低 3 振", "；".join(result["infeasible"][0]["reasons"]))

    def test_e2_type_requirement_is_at_least_not_fixed_lineup(self):
        # 四振队（枪+三把其他）同样可行：「至少包含」不是固定阵容
        store = _store()
        rows, slots = _e2_team(store)
        rows.insert(1, _row(MAEDA, "前田藤四郎"))
        slots.append(_slot(4, catalog_id=MAEDA, name="前田藤四郎",
                           sword_type="短刀"))
        profile = _profile(store, rows, {2: slots})
        maps = {"E2": load_maps()["E2"]}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"][0]["confidence"],
                         "executable")


class AvailabilityTests(unittest.TestCase):
    """工单第七节第二条：修行/手入剔除，受伤不剔除。"""

    def _profile_one_team(self, store, injury="none"):
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        slots = [_slot(1, injury=injury)]
        return _profile(store, rows, {1: slots})

    def test_training_member_blocks_team(self):
        store = _store()
        profile = self._profile_one_team(store)
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"},
                       training=[{"sword_catalog_id": MIKA, "form": "normal"}])
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertIn("修行中", "；".join(result["infeasible"][0]["reasons"]))

    def test_repair_member_blocks_team(self):
        store = _store()
        profile = self._profile_one_team(store)
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"},
                       repair=[{"sword_catalog_id": MIKA, "form": "normal"}])
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertIn("手入中", "；".join(result["infeasible"][0]["reasons"]))

    def test_heavy_injury_does_not_block_but_is_shown(self):
        store = _store()
        profile = self._profile_one_team(store, injury="heavy")
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        assignment = result["plan"]["assignments"][0]
        self.assertEqual(assignment["confidence"], "executable")
        self.assertIn("重伤", assignment["injury_note"])
        self.assertIn("不影响远征资格", assignment["injury_note"])


class AttendantTests(unittest.TestCase):
    """工单第七节第三条：近侍只扣本人一振，多重集容量，不连坐。"""

    def _hasebe_pool(self, store, kiwame_copies, normal_copies):
        rows = [_row(HASEBE, "压切长谷部", kiwame_date="2024-01-01")
                for _ in range(kiwame_copies)]
        rows += [_row(HASEBE, "压切长谷部") for _ in range(normal_copies)]
        rows.append(_row(KOGI, "小狐丸"))
        return rows

    def test_attendant_himself_blocked_when_single_copy(self):
        # 1 振极化长谷部，当了近侍 → 容量 1-1=0，所在队不可派
        store = _store()
        rows = self._hasebe_pool(store, 1, 0)
        slots = [_slot(1, catalog_id=HASEBE, name="压切长谷部",
                       kiwame_status="kiwame")]
        profile = _profile(store, rows, {1: slots})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": HASEBE, "form": "kiwame"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertIn("近侍", "；".join(result["infeasible"][0]["reasons"]))

    def test_second_kiwame_copy_keeps_capacity_but_needs_confirmation(self):
        # 2 振极化长谷部，近侍占 1：容量证明「本丸另有一振可用」，
        # 但固定队槽位里这振是不是近侍本人无法对账 → needs_confirmation，
        # 不封家族、也不伪判「本队已用另一振」（收口票三）
        store = _store()
        rows = self._hasebe_pool(store, 2, 0)
        slots = [_slot(1, catalog_id=HASEBE, name="压切长谷部",
                       kiwame_status="kiwame")]
        profile = _profile(store, rows, {1: slots})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": HASEBE, "form": "kiwame"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["infeasible"], [])  # 家族不被封禁
        assignment = result["plan"]["assignments"][0]
        self.assertEqual(assignment["confidence"], "needs_confirmation")
        note = "；".join(assignment["uncertainties"])
        self.assertIn("无法确认", note)
        self.assertIn("另有 1 振可用", note)      # 剩余容量如实展示
        self.assertIn("换成另一振", note)
        self.assertNotIn("本队用的是另一振", note)  # 不伪装已换

    def test_normal_same_name_copy_not_implicated(self):
        # 极化 1 振当近侍，普通长谷部（同位刀不同形态）不受影响
        store = _store()
        rows = self._hasebe_pool(store, 1, 1)
        slots = [_slot(1, catalog_id=HASEBE, name="压切长谷部",
                       kiwame_status="normal")]
        profile = _profile(store, rows, {1: slots})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": HASEBE, "form": "kiwame"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        assignment = result["plan"]["assignments"][0]
        self.assertEqual(assignment["confidence"], "executable")
        self.assertEqual(assignment.get("uncertainties"), [])

    def test_identity_unclear_is_uncertain_not_family_ban(self):
        # 极化/普通各 1 振，近侍申报形态未知 → 不确定但不封整个家族
        store = _store()
        rows = self._hasebe_pool(store, 1, 1)
        slots = [_slot(1, catalog_id=HASEBE, name="压切长谷部",
                       kiwame_status="kiwame")]
        profile = _profile(store, rows, {1: slots})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": HASEBE})  # form 未知
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["infeasible"], [])  # 没有封禁
        assignment = result["plan"]["assignments"][0]
        self.assertEqual(assignment["confidence"], "needs_confirmation")
        self.assertIn("无法确认", "；".join(assignment["uncertainties"]))

    def test_attendant_missing_from_pool_degrades(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近")]
        profile = _profile(store, rows, {1: [_slot(1)]})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": HASEBE, "form": "kiwame"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("不在候选池" in w for w in result["warnings"]))


class ExclusionTests(unittest.TestCase):
    """工单第七节第四条：同队互斥独立于近侍约束。"""

    def test_same_team_exclusion_conflict_blocks_team(self):
        # 两振同名前田藤四郎同队（观测数据可疑）→ 拦下
        store = _store()
        rows = [_row(MAEDA, "前田藤四郎"), _row(MAEDA, "前田藤四郎", level=1)]
        slots = [_slot(1, catalog_id=MAEDA, name="前田藤四郎",
                       sword_type="短刀"),
                 _slot(2, catalog_id=MAEDA, name="前田藤四郎",
                       sword_type="短刀", level=1)]
        profile = _profile(store, rows, {1: slots})
        maps = {"M": _map("M", _rules())}
        result = _plan(profile, maps, _facts(), allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertIn("互斥冲突", "；".join(result["infeasible"][0]["reasons"]))

    def test_exclusion_key_does_not_feed_attendant_rule(self):
        # 近侍是极化长谷部；另一队里的普通长谷部共享同一 exclusion key，
        # 但互斥键不得被拿来实现近侍限制——普通这振照常可派
        store = _store()
        rows = [_row(HASEBE, "压切长谷部", kiwame_date="2024-01-01"),
                _row(HASEBE, "压切长谷部")]
        profile = _profile(store, rows, {
            2: [_slot(1, catalog_id=HASEBE, name="压切长谷部",
                      kiwame_status="normal")]})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": HASEBE, "form": "kiwame"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"][0]["confidence"],
                         "executable")


class TeamReservationTests(unittest.TestCase):
    """工单收口票四：留守判定看确认非空队，文案不得虚报五队全出。"""

    def _two_teams(self, store):
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        return _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸")]})

    def test_default_keeps_one_team_home(self):
        store = _store()
        profile = self._two_teams(store)
        maps = {"M": _map("M", _rules(), 加速符=1),
                "N": _map("N", _rules(), 小判=100)}
        facts = _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"})
        result = _plan(profile, maps, facts)
        self.assertEqual(len(result["plan"]["assignments"]), 1)
        staying = result["plan"]["staying_home"]
        self.assertIsNotNone(staying)
        self.assertEqual(len(staying["teams"]), 1)
        self.assertIn(staying["teams"][0], (1, 2))
        self.assertIn("保留至少一支", staying["reason"])

    def test_all_away_warning_only_when_nobody_stays(self):
        # 两支可派队全出 + 无其他非空队 → 警告按实际派出数说，不虚报五队
        store = _store()
        profile = self._two_teams(store)
        maps = {"M": _map("M", _rules(), 加速符=1),
                "N": _map("N", _rules(), 小判=100)}
        facts = _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(len(result["plan"]["assignments"]), 2)
        warning = result["plan"]["all_away_warning"]
        self.assertIn("没有已确认可出阵的留守队", warning)
        self.assertIn("本轮新派出 2 队", warning)
        self.assertNotIn("五队全出", warning)

    def test_nonempty_blocked_team_staying_means_no_all_away_warning(self):
        # 两队派出、另有非空队（近侍队）留守 → 不报「没人出阵」
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎"),
                _row(HASEBE, "压切长谷部", kiwame_date="2024-01-01")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸")],
            3: [_slot(1, catalog_id=HASEBE, name="压切长谷部",
                      kiwame_status="kiwame")]})  # 近侍本人所在队
        maps = {"M": _map("M", _rules(), 加速符=1),
                "N": _map("N", _rules(), 小判=100)}
        facts = _facts(attendant={"sword_catalog_id": HASEBE, "form": "kiwame"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(len(result["plan"]["assignments"]), 2)
        self.assertIsNone(result["plan"]["all_away_warning"])
        self.assertEqual(result["plan"]["staying_home"]["teams"], [3])

    def test_default_does_not_deduct_when_nonempty_team_stays(self):
        # 已有非空不可远征队（近侍队）留守 → 默认模式不再额外扣可远征队
        store = _store()
        rows = [_row(MIKA, "三日月宗近"),
                _row(HASEBE, "压切长谷部", kiwame_date="2024-01-01")]
        profile = _profile(store, rows, {
            1: [_slot(1)],  # 可远征
            2: [_slot(1, catalog_id=HASEBE, name="压切长谷部",
                      kiwame_status="kiwame")]})  # 近侍队，天然留守
        maps = {"M": _map("M", _rules(), 加速符=1)}
        facts = _facts(attendant={"sword_catalog_id": HASEBE, "form": "kiwame"})
        result = _plan(profile, maps, facts)
        self.assertEqual(len(result["plan"]["assignments"]), 1)
        self.assertEqual(result["plan"]["assignments"][0]["team_no"], 1)
        self.assertEqual(result["plan"]["staying_home"]["teams"], [2])
        # 近侍队只是不能远征，本身可作留守出阵队（收口票二/七）
        self.assertIn("可出阵队留守", result["plan"]["staying_home"]["reason"])

    def test_last_nonempty_team_stays_home_by_default(self):
        # 只有一支非空队可派 → 默认留住，谁也不出门
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        profile = _profile(store, rows, {1: [_slot(1)]})
        maps = {"M": _map("M", _rules(), 加速符=1)}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1])
        self.assertIn("只有一支", result["plan"]["staying_home"]["reason"])
        self.assertIsNone(result["plan"]["all_away_warning"])

    def test_five_nonempty_teams_all_out_reports_five(self):
        # 五支非空队全部分配 → 警告按实际说五队
        store = _store()
        cats = [(MIKA, "三日月宗近"), (KOGI, "小狐丸"), (MAEDA, "前田藤四郎"),
                (HASEBE, "压切长谷部"), ("touken_007_ishikirimaru", "石切丸")]
        rows = [_row(cid, name) for cid, name in cats]
        rows.append(_row("touken_011_imagiri_no_toshiro", "今剣"))
        rosters = {i + 1: [_slot(1, catalog_id=cid, name=name)]
                   for i, (cid, name) in enumerate(cats)}
        profile = _profile(store, rows, rosters)
        maps = {c: _map(c, _rules(), 加速符=i + 1)
                for i, c in enumerate(("M1", "M2", "M3", "M4", "M5"))}
        facts = _facts(attendant={
            "sword_catalog_id": "touken_011_imagiri_no_toshiro",
            "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(len(result["plan"]["assignments"]), 5)
        self.assertIn("本轮新派出 5 队", result["plan"]["all_away_warning"])
        self.assertIsNone(result["plan"]["staying_home"])


class SakuraTests(unittest.TestCase):
    """工单第七节第六条：49 不算飘花，50 算；无花不影响普通成功。"""

    def _run_with_fatigue(self, fatigue):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        profile = _profile(store, rows, {1: [_slot(1, fatigue=fatigue)]})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        return result["plan"]["assignments"][0]

    def test_fatigue_49_is_not_sakura(self):
        assignment = self._run_with_fatigue(49)
        self.assertEqual(assignment["great_success"]["status"], "not_favored")

    def test_fatigue_50_is_sakura(self):
        assignment = self._run_with_fatigue(50)
        self.assertEqual(assignment["great_success"]["status"], "favored")
        self.assertIn("无法精确估算",
                      assignment["great_success"]["note"])

    def test_no_flowers_never_fails_normal_success(self):
        assignment = self._run_with_fatigue(10)
        self.assertEqual(assignment["confidence"], "executable")


class GoalTests(unittest.TestCase):
    """工单第七节第七条：默认 加速符>小判>最缺资源，可覆盖。"""

    def _one_team(self, store):
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        return _profile(store, rows, {1: [_slot(1)]})

    def test_default_goals_prefer_speedup_over_koban(self):
        store = _store()
        profile = self._one_team(store)
        maps = {"FAST": _map("FAST", _rules(), 加速符=1),
                "KOBAN": _map("KOBAN", _rules(), 小判=400)}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        # 归一化后 加速符(权重3) 压过 小判(权重2)，不被绝对数值架空
        self.assertEqual(result["plan"]["assignments"][0]["map_code"], "FAST")
        goals = result["inputs"]["goals"]
        self.assertEqual([g["resource"] for g in goals],
                         ["加速符", "小判", "冷却材"])  # 冷却材 60 最缺

    def test_custom_weights_override_default(self):
        store = _store()
        profile = self._one_team(store)
        maps = {"FAST": _map("FAST", _rules(), 加速符=1),
                "KOBAN": _map("KOBAN", _rules(), 小判=400)}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, weights=["小判"],
                       allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"][0]["map_code"], "KOBAN")

    def test_most_lacking_base_resource_as_third_goal(self):
        store = _store()
        profile = self._one_team(store)
        maps = {"RES": _map("RES", _rules(), 冷却材=100),
                "DRY": _map("DRY", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertEqual(result["plan"]["assignments"][0]["map_code"], "RES")

    def test_tied_inventory_leaves_third_goal_empty(self):
        self.assertIsNone(most_lacking_base_resource(
            {"木炭": 10, "玉钢": 10, "冷却材": 50, "砥石": 50}))
        goals, notes = normalize_goals(None, {"木炭": 10, "玉钢": 10,
                                              "冷却材": 50, "砥石": 50})
        self.assertEqual([g["resource"] for g in goals], ["加速符", "小判"])
        self.assertTrue(any("并列" in n or "空缺" in n for n in notes))


class RuleHonestyTests(unittest.TestCase):
    """工单第七节第八条：规则不完整不给伪确定方案；国服表无日服顶替。"""

    def test_partial_rules_map_is_rule_incomplete_not_executable(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        profile = _profile(store, rows, {1: [_slot(1)]})
        maps = {"P": _map("P", _rules(completeness="partial"))}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        assignment = result["plan"]["assignments"][0]
        self.assertEqual(assignment["confidence"], "rule_incomplete")
        self.assertEqual(result["plan"]["confidence"], "rule_incomplete")
        self.assertIn("规则不完整",
                      "；".join(assignment["uncertainties"]))

    def test_maps_table_marks_server_and_unknowns(self):
        maps = load_maps()
        self.assertEqual(len(maps), 20)
        for code, info in maps.items():
            rules = info["rules"]
            self.assertEqual(rules["server"], "cn")  # 只有国服规则
            self.assertEqual(rules["total_level"], info["level_req"])
            if code == "E2":
                self.assertEqual(rules["completeness"], "complete")
                self.assertEqual(rules["min_members"], 3)
                self.assertEqual(rules["required_types"], {"枪": 1})
            else:
                # 没有依据的图必须标 partial，null=不知道而不是没有要求
                self.assertEqual(rules["completeness"], "partial")
                self.assertIsNone(rules["min_members"])
                self.assertIsNone(rules["required_types"])
                self.assertTrue(rules["unknown_aspects"])


class DegradationTests(unittest.TestCase):
    """工单第七节第九条：陈旧/残缺/事实缺失都要进解释并降级。"""

    def _one_team(self, store):
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        return _profile(store, rows, {1: [_slot(1)]})

    def test_missing_member_facts_degrades_everything(self):
        store = _store()
        profile = self._one_team(store)
        maps = {"M": _map("M", _rules())}
        result = _plan(profile, maps, None, allow_all_teams_away=True)
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertEqual(result["inputs"]["member_facts_status"], "missing")
        self.assertTrue(any("未提供近侍" in w for w in result["warnings"]))

    def test_stale_pool_warns(self):
        store = _store()
        profile = self._one_team(store)  # 盘点 ts=100
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, now=NOW - 900 + 25 * 3600,
                       allow_all_teams_away=True)
        self.assertTrue(any("陈旧" in w for w in result["warnings"]))

    def test_partial_roster_observation_degrades_assignment(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        store.save_sword_snapshot(rows, owned=2, capacity=300, missing=0,
                                  captured_at=100, source="owned_inventory")
        store.record_event("team_roster.observed", {
            "team_no": 1, "slots": [_slot(1)],
            "observation_status": "partial", "source": "formation_page"})
        store._conn().execute(
            "UPDATE events SET ts = 150 WHERE id = "
            "(SELECT MAX(id) FROM events)")
        store._conn().commit()
        profile = build_honmaru_profile(store)
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        assignment = result["plan"]["assignments"][0]
        self.assertEqual(assignment["confidence"], "needs_confirmation")
        self.assertIn("partial", "；".join(assignment["uncertainties"]))

    def test_pool_unavailable_warns_and_degrades(self):
        store = _store()  # 只有图鉴 → 候选池不可用
        store.save_sword_snapshot(
            [{"sword_id": "album_003", "name_zh": "三日月宗近", "stats": {}}],
            owned=204, capacity=208, missing=0, captured_at=100, source="album")
        store.record_event("team_roster.observed", {
            "team_no": 1, "slots": [_slot(1)],
            "observation_status": "complete", "source": "formation_page"})
        store._conn().execute(
            "UPDATE events SET ts = 150 WHERE id = "
            "(SELECT MAX(id) FROM events)")
        store._conn().commit()
        profile = build_honmaru_profile(store)
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        self.assertTrue(any("候选池不可用" in w for w in result["warnings"]))
        # 近侍申报对不上账 → unmatched → 不得伪装可执行
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")

    def test_unknown_slot_makes_team_uncertain(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        blind = _slot(2, catalog_id=None, name=None, name_status=None,
                      slot_status="unknown", level=None, fatigue=None,
                      survival=None, survival_max=None, injury=None,
                      kiwame_status="unknown", unknown_fields=["all"])
        profile = _profile(store, rows, {1: [_slot(1), blind]})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts, allow_all_teams_away=True)
        assignment = result["plan"]["assignments"][0]
        self.assertEqual(assignment["confidence"], "needs_confirmation")
        self.assertIn("读不出", "；".join(assignment["uncertainties"]))


class JointAssignmentTests(unittest.TestCase):
    """工单收口票一：同一远征地点同时只能派一支队，跨队联合分配。"""

    def _two_teams(self, store, swap=False):
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        rosters = {1: [_slot(1)], 2: [_slot(1, catalog_id=KOGI,
                                        name="小狐丸")]}
        if swap:  # 两队成员对调，整卷最优总分和地图集合不应变
            rosters = {1: rosters[2], 2: rosters[1]}
        return _profile(store, rows, rosters)

    def _maps(self):
        return {"A": _map("A", _rules(), 加速符=2),  # A 得分更高
                "B": _map("B", _rules(), 加速符=1)}

    def _facts(self):
        return _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"})

    def test_same_map_never_assigned_twice(self):
        store = _store()
        result = _plan(self._two_teams(store), self._maps(), self._facts(),
                       allow_all_teams_away=True)
        codes = [a["map_code"] for a in result["plan"]["assignments"]]
        self.assertEqual(len(codes), len(set(codes)))  # 不能都去 A
        self.assertEqual(sorted(codes), ["A", "B"])

    def test_higher_score_map_is_used_and_loser_explained(self):
        store = _store()
        result = _plan(self._two_teams(store), self._maps(), self._facts(),
                       allow_all_teams_away=True)
        by_team = {a["team_no"]: a for a in result["plan"]["assignments"]}
        self.assertEqual(by_team[1]["map_code"], "A")  # 部队1 先得高分图
        self.assertNotIn("occupancy_note", by_team[1])
        self.assertEqual(by_team[2]["map_code"], "B")
        note = by_team[2]["occupancy_note"]
        self.assertIn("A", note)
        self.assertIn("部队1", note)
        self.assertIn("只能派一支队", note)

    def test_team_order_does_not_change_optimal_total_or_map_set(self):
        r1 = _plan(self._two_teams(_store(), swap=False), self._maps(),
                   self._facts(), allow_all_teams_away=True)
        r2 = _plan(self._two_teams(_store(), swap=True), self._maps(),
                   self._facts(), allow_all_teams_away=True)
        total1 = sum(a["score"] or 0 for a in r1["plan"]["assignments"])
        total2 = sum(a["score"] or 0 for a in r2["plan"]["assignments"])
        self.assertAlmostEqual(total1, total2)
        set1 = {a["map_code"] for a in r1["plan"]["assignments"]}
        set2 = {a["map_code"] for a in r2["plan"]["assignments"]}
        self.assertEqual(set1, set2)

    def test_single_team_behavior_unchanged(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        profile = _profile(store, rows, {1: [_slot(1)]})
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, self._maps(), facts,
                       allow_all_teams_away=True)
        assignments = result["plan"]["assignments"]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["map_code"], "A")
        self.assertNotIn("occupancy_note", assignments[0])
        self.assertEqual(assignments[0]["alternatives"][0]["map_code"], "B")

    def test_teams_sharing_single_map_one_left_home(self):
        # 两队都只有同一图可去：一队派出，另一队如实记「图被占满」并留守
        store = _store()
        profile = self._two_teams(_store())
        maps = {"ONLY": _map("ONLY", _rules(), 加速符=1)}
        result = _plan(profile, maps, self._facts(), allow_all_teams_away=True)
        self.assertEqual(len(result["plan"]["assignments"]), 1)
        self.assertEqual(result["plan"]["assignments"][0]["map_code"], "ONLY")
        reasons = "；".join(result["infeasible"][0]["reasons"])
        self.assertIn("占满", reasons)
        self.assertIsNone(result["plan"]["all_away_warning"])  # 有一队留守


class FactsCompletenessTests(unittest.TestCase):
    """工单收口票二：缺字段 ≠ 明确为空，三类事实各有完整度语义。"""

    def _profile(self, store):
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        return _profile(store, rows, {1: [_slot(1)]})

    def _maps(self):
        return {"M": _map("M", _rules())}

    def test_attendant_only_still_degrades(self):
        # 最小反例：只传 attendant，缺 training/repair → 不得 executable
        result = _plan(self._profile(_store()), self._maps(),
                       {"attendant": {"sword_catalog_id": KOGI,
                                      "form": "normal"}},
                       allow_all_teams_away=True)
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("修行中" in w for w in result["warnings"]))
        self.assertTrue(any("手入中" in w for w in result["warnings"]))

    def test_missing_training_degrades(self):
        result = _plan(self._profile(_store()), self._maps(),
                       {"attendant": {"sword_catalog_id": KOGI,
                                      "form": "normal"},
                        "repair": []},
                       allow_all_teams_away=True)
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("修行中" in w for w in result["warnings"]))
        self.assertFalse(any("手入中事实未提供" in w
                             for w in result["warnings"]))

    def test_missing_repair_degrades(self):
        result = _plan(self._profile(_store()), self._maps(),
                       {"attendant": {"sword_catalog_id": KOGI,
                                      "form": "normal"},
                        "training": []},
                       allow_all_teams_away=True)
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("手入中" in w for w in result["warnings"]))

    def test_none_is_not_empty_list(self):
        result = _plan(self._profile(_store()), self._maps(),
                       {"attendant": {"sword_catalog_id": KOGI,
                                      "form": "normal"},
                        "training": None, "repair": []},
                       allow_all_teams_away=True)
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")

    def test_explicit_empty_lists_are_executable(self):
        result = _plan(self._profile(_store()), self._maps(),
                       _facts(attendant={"sword_catalog_id": KOGI,
                                         "form": "normal"},
                              training=[], repair=[]),
                       allow_all_teams_away=True)
        self.assertEqual(result["plan"]["confidence"], "executable")
        self.assertEqual(result["plan"]["assignments"][0]["map_code"], "M")


def _active_record(map_code="A", duration=120, dispatched_epoch=None):
    """一条未到期（默认）的派遣记录，dispatched_at 按本地时间格式化。"""
    if dispatched_epoch is None:
        dispatched_epoch = NOW - 3600
    return {"map_code": map_code, "map_name": "测试图", "era": 5, "slot": 1,
            "duration_min": duration,
            "dispatched_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(dispatched_epoch))}


class ActiveExpeditionTests(unittest.TestCase):
    """工单收口票一：正在远征的队与已占用地图纳入规划。"""

    def _two_teams(self, store):
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        return _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸")]})

    def _facts(self):
        return _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"})

    def _maps(self):
        return {"A": _map("A", _rules(), 加速符=2),
                "B": _map("B", _rules(), 加速符=1)}

    def test_active_team_excluded_and_map_occupied(self):
        # 部队2 在 A 图上远征：不得重派；A 被占用，部队1 只能去 B
        profile = self._two_teams(_store())
        result = _plan(profile, self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"2": _active_record("A")})
        assignments = result["plan"]["assignments"]
        self.assertEqual([a["team_no"] for a in assignments], [1])
        self.assertEqual(assignments[0]["map_code"], "B")
        self.assertIn("正在远征的队伍", assignments[0]["occupancy_note"])
        waiting = result["plan"]["waiting_for"]
        self.assertEqual(waiting[0]["team_no"], 2)
        self.assertIn("remain_min", waiting[0])
        self.assertIn("return_text", waiting[0])
        # 在外的队不算留守
        staying = result["plan"]["staying_home"]
        self.assertFalse(staying and 2 in staying["teams"])
        self.assertEqual(result["inputs"]["active_expeditions"]
                         ["occupied_maps"], ["A"])

    def test_expired_record_frees_team_and_map(self):
        profile = self._two_teams(_store())
        expired = _active_record("A", duration=60,
                                 dispatched_epoch=NOW - 7200)  # 已到期
        result = _plan(profile, self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"2": expired})
        self.assertEqual(len(result["plan"]["assignments"]), 2)
        self.assertEqual({a["map_code"] for a in result["plan"]["assignments"]},
                         {"A", "B"})

    def test_explicit_empty_active_is_deterministic(self):
        profile = self._two_teams(_store())
        result = _plan(profile, self._maps(), self._facts(),
                       allow_all_teams_away=True, active_expeditions={})
        active = result["inputs"]["active_expeditions"]
        self.assertEqual(active["status"], "ok")
        self.assertEqual(active["active_teams"], [])
        self.assertEqual(active["occupied_maps"], [])

    def test_unreliable_time_excludes_team_and_degrades(self):
        profile = self._two_teams(_store())
        bad = {"map_code": "A", "map_name": "测试图", "duration_min": 120,
               "dispatched_at": "垃圾时间"}
        result = _plan(profile, self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"2": bad})
        # 部队2 状态未知被排除，不静默当空闲
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [1])
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("时间不可靠" in w for w in result["warnings"]))
        self.assertEqual(result["inputs"]["active_expeditions"]
                         ["unknown_state_teams"], [2])

    def test_corrupt_structure_is_not_silently_idle(self):
        profile = self._two_teams(_store())
        result = _plan(profile, self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions=["不是队伍表"])
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("结构损坏" in w for w in result["warnings"]))
        self.assertEqual(result["inputs"]["active_expeditions"]["status"],
                         "corrupt")

    def test_active_record_missing_map_code_degrades(self):
        profile = self._two_teams(_store())
        rec = _active_record(None)
        result = _plan(profile, self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"2": rec})
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [1])
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("占用地点未知" in w for w in result["warnings"]))

    def test_all_away_warning_distinguishes_active_from_new(self):
        # 活跃队不算本丸留守：文案区分「原本已在外面」与「本轮新派出」
        profile = self._two_teams(_store())
        result = _plan(profile, self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"2": _active_record("A")})
        warning = result["plan"]["all_away_warning"]
        self.assertIn("没有已确认可出阵的留守队", warning)
        self.assertIn("本轮新派出 1 队", warning)
        self.assertIn("原本已在远征途中", warning)
        self.assertIn("部队2", warning)

    def test_waiting_for_active_expeditions_outcome(self):
        # 唯一的队在外面：没有新派遣是因为等归来，不是没图可去
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {2: [_slot(1)]})
        result = _plan(profile, self._maps(), self._facts(),
                       active_expeditions={"2": _active_record("A")})
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["outcome"],
                         "waiting_for_active_expeditions")
        self.assertEqual(result["plan"]["confidence"], "executable")
        self.assertTrue(any("归来" in e for e in result["explanation"]))

    def test_allow_all_never_redispatches_active_team(self):
        profile = self._two_teams(_store())
        result = _plan(profile, self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"2": _active_record("A")})
        self.assertNotIn(2, [a["team_no"]
                             for a in result["plan"]["assignments"]])


class ZeroDispatchOutcomeTests(unittest.TestCase):
    """工单收口票三：零派遣原因机器可读，不一律 executable。"""

    def test_no_feasible_assignment_is_infeasible(self):
        # 唯一队伍面对 total_level=999 的图：全部不可行
        store = _store()
        rows = [_row(MIKA, "三日月宗近", level=10), _row(KOGI, "小狐丸")]
        profile = _profile(store, rows, {1: [_slot(1, level=10)]})
        maps = {"HARD": _map("HARD", _rules(total=999))}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["outcome"], "no_feasible_assignment")
        self.assertEqual(result["plan"]["confidence"], "infeasible")

    def test_intentionally_staying_home_outcome(self):
        # 最后一支可行安全队被默认策略主动扣住
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        profile = _profile(store, rows, {1: [_slot(1)]})
        maps = {"M": _map("M", _rules())}
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, maps, facts)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["outcome"],
                         "intentionally_staying_home")
        self.assertEqual(result["plan"]["confidence"], "executable")
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1])


class ReserveReadinessTests(unittest.TestCase):
    """工单收口票二：留守只认「已确认可出阵」的队。"""

    def _facts(self):
        return _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"})

    def test_repair_blocked_team_is_not_reserve(self):
        # 部队2 含手入成员（坏队）：默认仍扣住真正安全的部队1，
        # 不拿坏队充数（牛老师复现的反例）
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸")]})
        facts = self._facts()
        facts["repair"] = [{"sword_catalog_id": KOGI, "form": "normal"}]
        result = _plan(profile, {"M": _map("M", _rules(), 加速符=1)}, facts)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["outcome"],
                         "intentionally_staying_home")
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1, 2])
        # allow_all 只覆盖留守偏好，不覆盖安全事实：部队2 依旧不可派
        result2 = _plan(profile, {"M": _map("M", _rules(), 加速符=1)},
                        facts, allow_all_teams_away=True)
        self.assertEqual([a["team_no"] for a in result2["plan"]["assignments"]],
                         [1])
        self.assertIn(2, [i["team_no"] for i in result2["infeasible"]])

    def test_training_blocked_team_is_not_reserve(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸")]})
        facts = self._facts()
        facts["training"] = [{"sword_catalog_id": KOGI, "form": "normal"}]
        result = _plan(profile, {"M": _map("M", _rules(), 加速符=1)}, facts)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1, 2])

    def test_heavy_injury_team_is_not_reserve_but_can_expedition(self):
        # 重伤队不挡远征但不算留守候选：默认留下健康的部队1
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸", injury="heavy")]})
        maps = {"M": _map("M", _rules(), 加速符=1),
                "N": _map("N", _rules(), 小判=100)}
        result = _plan(profile, maps, self._facts())
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1])
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [2])
        self.assertIn("重伤", result["plan"]["assignments"][0]["injury_note"])

    def test_unknown_slot_team_is_not_reserve(self):
        store = _store()
        blind = _slot(2, catalog_id=None, name=None, name_status=None,
                      slot_status="unknown", level=None, fatigue=None,
                      survival=None, survival_max=None, injury=None,
                      kiwame_status="unknown", unknown_fields=["all"])
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸"), blind]})
        maps = {"M": _map("M", _rules(), 加速符=1),
                "N": _map("N", _rules(), 小判=100)}
        result = _plan(profile, maps, self._facts())
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1])
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [2])

    def test_map_failed_team_still_counts_as_reserve(self):
        # 只是等级不够跑远征，人不伤不残：可以当日课留守队
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸", level=1),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸", level=1)]})
        maps = {"HARD": _map("HARD", _rules(total=999), 加速符=1),
                "M": _map("M", _rules(), 小判=100)}
        result = _plan(profile, maps, self._facts())
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [1])
        self.assertEqual(result["plan"]["staying_home"]["teams"], [2])
        self.assertIn("可出阵队留守",
                      result["plan"]["staying_home"]["reason"])

    def test_conflict_team_is_not_reserve(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎"), _row(MAEDA, "前田藤四郎", level=1)]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=MAEDA, name="前田藤四郎",
                      sword_type="短刀"),
                _slot(2, catalog_id=MAEDA, name="前田藤四郎",
                      sword_type="短刀", level=1)]})
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, {"M": _map("M", _rules(), 加速符=1)}, facts)
        # 冲突队不算留守 → 部队1 被默认扣住，谁也不出门
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1, 2])
        self.assertEqual(result["plan"]["confidence"], "executable")

    def test_empty_team_is_not_reserve(self):
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, slot_status="empty", catalog_id=None, name=None)]})
        facts = _facts(attendant={"sword_catalog_id": KOGI, "form": "normal"})
        result = _plan(profile, {"M": _map("M", _rules(), 加速符=1)}, facts)
        # 空队不算留守 → 部队1 被默认扣住
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1])


class OccupiedMapsAreNotHoldoutTests(unittest.TestCase):
    """修票一：被活跃远征占满的图不能触发「主动留守」。"""

    def _facts(self):
        return _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"})

    def test_single_home_team_only_map_occupied_is_waiting(self):
        # 部队2 在 A 图；家里的部队1 只满足 A；默认模式
        # → 是「等归来」不是「主动留守」
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {1: [_slot(1)]})
        maps = {"A": _map("A", _rules(), 加速符=1)}
        result = _plan(profile, maps, self._facts(),
                       active_expeditions={"2": _active_record("A")})
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["outcome"],
                         "waiting_for_active_expeditions")
        self.assertNotEqual(result["plan"]["outcome"],
                            "intentionally_staying_home")
        self.assertIsNone(result["plan"]["staying_home"] and
                          result["plan"]["staying_home"].get("teams") == [1]
                          and "保留" in result["plan"]["staying_home"]
                          ["reason"] or None)
        self.assertTrue(any("归来" in e for e in result["explanation"]))

    def test_multiple_home_teams_all_maps_occupied_is_waiting(self):
        # 两支家中队，可去的 A/B 全被 active 占满 → 不能假装留守策略
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸")]})
        maps = {"A": _map("A", _rules(), 加速符=2),
                "B": _map("B", _rules(), 加速符=1)}
        result = _plan(profile, maps, self._facts(),
                       active_expeditions={"3": _active_record("A"),
                                           "4": _active_record("B")})
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["outcome"],
                         "waiting_for_active_expeditions")
        self.assertIn("占", "；".join(result["infeasible"][0]["reasons"]))

    def test_free_map_still_dispatches_and_holds_normally(self):
        # A 被占、B/C 空着：正常派遣并按需留队
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸")]})
        maps = {"A": _map("A", _rules(), 加速符=3),
                "B": _map("B", _rules(), 加速符=2),
                "C": _map("C", _rules(), 小判=100)}
        result = _plan(profile, maps, self._facts(),
                       active_expeditions={"3": _active_record("A")})
        assignments = result["plan"]["assignments"]
        self.assertEqual(result["plan"]["outcome"], "assigned")
        self.assertEqual(len(assignments), 1)
        self.assertIn(assignments[0]["map_code"], ("B", "C"))
        self.assertNotEqual(assignments[0]["map_code"], "A")
        staying = result["plan"]["staying_home"]
        self.assertEqual(len(staying["teams"]), 1)
        self.assertIn("保留", staying["reason"])


class WaitingOutcomeRelevanceTests(unittest.TestCase):
    """极小修票：waiting 只在与活跃占图直接相关时使用。"""

    def _facts(self):
        return _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"})

    def test_mixed_occupied_blocked_and_hard_failed_is_waiting(self):
        # 精确反例：部队3 在 A；部队1 只满足 A（被占）→ occupied-only 阻塞；
        # 部队2 对所有图纯硬失败 → 仍应 waiting 等部队3，而非 no_feasible
        store = _store()
        rows = [_row(MIKA, "三日月宗近", level=50),
                _row(KOGI, "小狐丸", level=1),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1, level=50)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸", level=1)]})
        maps = {"A": _map("A", _rules(total=30), 加速符=1),
                "B": _map("B", _rules(total=999), 小判=100)}
        result = _plan(profile, maps, self._facts(),
                       active_expeditions={"3": _active_record("A")})
        plan = result["plan"]
        self.assertEqual(plan["assignments"], [])
        self.assertEqual(plan["outcome"], "waiting_for_active_expeditions")
        self.assertEqual(plan["confidence"], "executable")
        self.assertTrue(any("部队3" in e and "归来" in e
                            for e in result["explanation"]))
        # 两支家中队各自的原因都必须保留：部队1 是占图，部队2 是硬失败
        reasons = {i["team_no"]: "；".join(i["reasons"])
                   for i in result["infeasible"]}
        self.assertIn("占用", reasons[1])
        self.assertIn("硬条件", reasons[2])
        self.assertNotIn("占用", reasons[2])

    def test_irrelevant_occupied_map_with_pure_hard_fail_is_no_feasible(self):
        # 活跃队占的是无关地图 X；家中队对 A/B 全部纯硬失败
        # → 不能仅因 away 非空就 waiting
        store = _store()
        rows = [_row(MIKA, "三日月宗近", level=1),
                _row(KOGI, "小狐丸", level=1),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1, level=1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸", level=1)]})
        maps = {"A": _map("A", _rules(total=999)),
                "B": _map("B", _rules(total=999))}
        result = _plan(profile, maps, self._facts(),
                       active_expeditions={"3": _active_record("X")})
        plan = result["plan"]
        self.assertEqual(plan["assignments"], [])
        self.assertEqual(plan["outcome"], "no_feasible_assignment")
        self.assertEqual(plan["confidence"], "infeasible")

    def test_all_nonempty_observed_teams_away_is_waiting(self):
        # 已观测非空队全在外面（roster 只有远征中的部队2）
        store = _store()
        rows = [_row(MIKA, "三日月宗近"), _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {2: [_slot(1)]})
        result = _plan(profile, {"A": _map("A", _rules())}, self._facts(),
                       active_expeditions={"2": _active_record("A")})
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["outcome"],
                         "waiting_for_active_expeditions")


class AmbiguousOccupancyReserveTests(unittest.TestCase):
    """修票二：修行/手入身份不清的多号机不能充当已确认留守。"""

    def _profile_with_ambiguous_kogi(self, store):
        # 两振同型极化小狐丸；部队2 只能 ambiguous 链到这两振且等级低
        # （跑不了图，会留在家里）；部队1 健康可派
        rows = [_row(MIKA, "三日月宗近"),
                _row(KOGI, "小狐丸", level=1, kiwame_date="2024-01-01"),
                _row(KOGI, "小狐丸", level=1, kiwame_date="2024-01-01"),
                _row(MAEDA, "前田藤四郎")]
        return _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸", level=1,
                      kiwame_status="kiwame")]})

    def _maps(self):
        return {"M": _map("M", _rules(total=50), 加速符=1)}

    def test_repair_ambiguous_copy_is_not_reserve(self):
        facts = _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"},
                       repair=[{"sword_catalog_id": KOGI, "form": "kiwame"}])
        result = _plan(self._profile_with_ambiguous_kogi(_store()),
                       self._maps(), facts)
        # 部队2 不算已确认留守 → 默认扣住健康的部队1，谁也不派
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertEqual(result["plan"]["staying_home"]["teams"], [1, 2])
        reason = result["plan"]["staying_home"]["reason"]
        self.assertIn("部队2", reason)
        self.assertIn("出阵状态不可确认", reason)

    def test_training_ambiguous_copy_is_not_reserve(self):
        facts = _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"},
                       training=[{"sword_catalog_id": KOGI, "form": "kiwame"}])
        result = _plan(self._profile_with_ambiguous_kogi(_store()),
                       self._maps(), facts)
        self.assertEqual(result["plan"]["assignments"], [])
        self.assertIn("出阵状态不可确认",
                      result["plan"]["staying_home"]["reason"])

    def test_attendant_ambiguous_copy_still_reserve(self):
        # 近侍身份不清只影响远征资格；近侍本人本来就能随队出阵，
        # 不失去留守资格 → 部队1 照常派出，部队2 算可出阵留守
        facts = _facts(attendant={"sword_catalog_id": KOGI})  # 形态未知
        result = _plan(self._profile_with_ambiguous_kogi(_store()),
                       self._maps(), facts)
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [1])
        self.assertIn("可出阵队留守",
                      result["plan"]["staying_home"]["reason"])

    def test_form_mismatch_evidence_is_not_blocked(self):
        # 手入申报的是极化小狐丸，部队2 槽位确认是普通形态（不同组）：
        # 形态证据足以证明当前槽位不是被占用者，不误拦留守资格
        store = _store()
        rows = [_row(MIKA, "三日月宗近"),
                _row(KOGI, "小狐丸", level=1, kiwame_date="2024-01-01"),
                _row(KOGI, "小狐丸", level=1),
                _row(MAEDA, "前田藤四郎")]
        profile = _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸", level=1,
                      kiwame_status="normal")]})
        facts = _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"},
                       repair=[{"sword_catalog_id": KOGI, "form": "kiwame"}])
        result = _plan(profile, self._maps(), facts)
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [1])
        self.assertIn("可出阵队留守",
                      result["plan"]["staying_home"]["reason"])


class BrokenActiveRecordTests(unittest.TestCase):
    """修票三：队号已知但记录损坏必须排除该队；解析边界不崩溃。"""

    def _two_teams(self, store):
        rows = [_row(MIKA, "三日月宗近"), _row(KOGI, "小狐丸"),
                _row(MAEDA, "前田藤四郎")]
        return _profile(store, rows, {
            1: [_slot(1)],
            2: [_slot(1, catalog_id=KOGI, name="小狐丸")]})

    def _maps(self):
        return {"A": _map("A", _rules(), 加速符=2),
                "B": _map("B", _rules(), 加速符=1)}

    def _facts(self):
        return _facts(attendant={"sword_catalog_id": MAEDA, "form": "normal"})

    def test_broken_entry_excludes_known_team(self):
        result = _plan(self._two_teams(_store()), self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"2": "broken"})
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [1])
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertEqual(result["inputs"]["active_expeditions"]
                         ["unknown_state_teams"], [2])
        self.assertTrue(any("结构损坏" in w for w in result["warnings"]))

    def test_invalid_team_key_degrades_without_fabricating(self):
        result = _plan(self._two_teams(_store()), self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"x": _active_record("A")})
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("无法识别的队伍键" in w
                            for w in result["warnings"]))
        # 不伪造队号：unknown_state/active 里都没有 x
        active = result["inputs"]["active_expeditions"]
        self.assertEqual(active["active_teams"], [])
        self.assertEqual(active["unknown_state_teams"], [])

    def test_non_finite_and_bool_duration_are_unknown_end(self):
        for bad_duration in (float("nan"), float("inf"), True):
            rec = _active_record("A")
            rec["duration_min"] = bad_duration
            result = _plan(self._two_teams(_store()), self._maps(),
                           self._facts(), allow_all_teams_away=True,
                           active_expeditions={"2": rec})
            self.assertEqual(result["inputs"]["active_expeditions"]
                             ["unknown_state_teams"], [2])
            self.assertEqual([a["team_no"]
                              for a in result["plan"]["assignments"]], [1])

    def test_unhashable_map_code_is_unknown_location_not_crash(self):
        rec = _active_record("A")
        rec["map_code"] = ["A"]  # 不可哈希：按地点未知处理
        result = _plan(self._two_teams(_store()), self._maps(), self._facts(),
                       allow_all_teams_away=True,
                       active_expeditions={"2": rec})
        self.assertEqual(result["plan"]["confidence"], "needs_confirmation")
        self.assertTrue(any("占用地点未知" in w for w in result["warnings"]))
        self.assertEqual([a["team_no"] for a in result["plan"]["assignments"]],
                         [1])


if __name__ == "__main__":
    unittest.main()
