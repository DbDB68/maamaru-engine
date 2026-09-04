"""默认日课模板：保留日课专属编排，复用现有执行方法，不另写玩法。"""
import copy


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
        if params.get("watch"):
            yield from workflow.NODE_REGISTRY["forge"]["run"](agent, params, config_path)
        else:
            yield from agent.forge_stream(times=int(params.get("times", 3)))

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
        "desc": "按日课的地图和次数出阵；战斗设置沿用对应玩法的配置。也可以选择不出阵。",
        "category": "battle", "params": fields, "run": daily_sortie,
        "detail": [*workflow.NODE_REGISTRY["sortie"].get("detail", []), sortie_status], "template_only": True})
