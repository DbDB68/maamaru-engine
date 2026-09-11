"""默认日课模板：保留日课专属编排，复用现有执行方法，不另写玩法。"""
import copy

RECIPE_KEYS = ("recipe_charcoal", "recipe_steel", "recipe_coolant", "recipe_whetstone")


def recipe_fields():
    """锻刀配方四个数字字段（配置页锻刀脚本和一键日课共用）"""
    names = zip(RECIPE_KEYS, ("木炭", "玉钢", "冷却材", "砥石"))
    return [{"key": key, "type": "number", "label": f"配方·{zh}",
             "default": 700, "min": 10, "max": 999,
             **({"help": "点火前自动把配比设成这四个数。游戏会记住上次配方，"
                         "一致时跳过不重设。"} if i == 0 else {})}
            for i, (key, zh) in enumerate(names)]


def recipe_from_params(params):
    """从面板参数读配方；缺键/越界（10~999）返回 None（= 用配置文件里的配方）"""
    out = []
    for key in RECIPE_KEYS:
        try:
            v = int(params.get(key))
        except (TypeError, ValueError):
            return None
        if not 10 <= v <= 999:
            return None
        out.append(v)
    return out


def make_template(settings, config, daily_steps):
    daily = (settings.get("params", {}).get("daily") or {})
    wanted = daily.get("steps") or daily.get("only") or daily_steps
    mapping = {"登录": "login", "签到": "signin", "万屋": "free_gift",
               "演练": "practice", "远征": "expedition", "内番": "naihanka",
               "锻刀": "forge", "刀解": "dismantle", "合成": "synthesize",
               "出阵": "daily_sortie", "任务奖励": "task_rewards", "库存快照": "snapshot"}
    nodes = []
    for step in daily_steps:
        if step not in wanted:
            continue
        params = {}
        if step == "锻刀":
            params = {"times": config.get("daily", {}).get("forge_times", 3)}
        elif step == "出阵":
            params = {k: copy.deepcopy(v) for k, v in daily.items() if k not in ("steps", "only", "after")}
            params.setdefault("sortie_mode", "none")
        nodes.append({"type": mapping[step], "params": params,
                      "on_error": "stop" if step == "登录" else "continue"})
    return {"id": "builtin-daily", "name": "一键日课", "nodes": nodes,
            "after": daily.get("after") or "none", "daily_mode": True}


def install_daily_template(workflow, scripts, *, _load_settings, config, daily_steps, plan_inputs):
    workflow.daily_template_provider = lambda: make_template(_load_settings(), config, daily_steps)

    def daily_login(agent, params, config_path):
        if not (yield from agent._ensure_game_started()):
            yield "[日课] ✗ 游戏没有启动，日课停止"
            return
        agent.login()
        if not agent._popup_sweep():
            yield "[日课] ✗ 登录后没到本丸，日课停止"
        else:
            yield "[日课] ✓ 已登录本丸"

    def daily_practice(agent, params, config_path):
        saved = (_load_settings().get("params", {}).get("practice") or {})
        fallback = getattr(agent, "config", {}).get("daily", {}).get("practice", {})
        values = {**(saved or fallback), **params}
        team = values.get("team_no")
        yield from agent.practice_stream(dry_run=False,
            team_no=int(team) if team not in (None, "") else None,
            formation_mode=values.get("formation_mode"), formation=values.get("formation"))

    def daily_expedition(agent, params, config_path):
        routes = plan_inputs({})[4]
        yield from agent._daily_expedition_step(routes)

    def daily_snapshot(agent, params, config_path):
        yield from agent._closing_snapshot_stream(getattr(agent, "_workflow_forge_ran", False))

    def daily_dismantle(agent, params, config_path):
        yield from agent._dismantle_step()

    def daily_forge(agent, params, config_path):
        recipe = recipe_from_params(params)
        if params.get("watch"):
            yield from workflow.NODE_REGISTRY["forge"]["run"](agent, params, config_path)
        else:
            yield from agent.forge_stream(times=int(params.get("times", 3)), recipe=recipe)

    def daily_sortie(agent, params, config_path):
        plan = plan_inputs(params)[2]
        if plan.get("mode") == "none":
            yield "[日课] ⏭ 按安排不出阵"
            return
        report = []
        yield from agent._sortie_step({"sortie": plan}, report)
        for name, status in report:
            yield f"[日课] {name}: {status}"

    def sortie_status(message, previous):
        return "⏭ 按安排不出阵" if message == "[日课] ⏭ 按安排不出阵" else previous

    for name, callback in (("login", daily_login), ("practice", daily_practice),
                           ("expedition", daily_expedition), ("snapshot", daily_snapshot),
                           ("dismantle", daily_dismantle), ("forge", daily_forge)):
        workflow.NODE_REGISTRY[name]["daily_run"] = callback
    fields = [copy.deepcopy(f) for f in scripts["daily"]["params"] if f["key"] not in ("steps", "after")]
    fields.append({"key": "pumpkin_watch", "type": "text", "label": "南瓜目标刀剑",
                   "swords": True, "default": "", "placeholder": "多个名字用逗号分隔",
                   "visibleWhen": {"key": "sortie_mode", "is": "pumpkin"}})
    workflow.register_node({"type": "daily_sortie", "label": "日课出阵",
        "desc": "按日课的地图和次数出阵；行军、阵形和伤势处理由本节点自己的设置决定，与「配置」页无关。也可以选择不出阵。",
        "category": "battle", "params": fields, "run": daily_sortie,
        "detail": [*workflow.NODE_REGISTRY["sortie"].get("detail", []), sortie_status], "template_only": True})
