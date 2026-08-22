# -*- coding: utf-8 -*-
"""脚本注册表冒烟测试：worker 用 fn(config_path, params) 两参数调用，
别把 (agent, config_path, params) 三参数的 builder 裸注册进去
（2026-08-22 换队长脚本崩过的坑）。"""

import inspect
import unittest

import panel.server  # noqa: F401  # import 即触发全部 register_script
from panel.script_runner import _SCRIPTS


class ScriptRegistryTests(unittest.TestCase):
    def test_every_script_fn_accepts_two_positional_args(self):
        self.assertTrue(_SCRIPTS, "注册表是空的，import 注册没跑成")
        for name, info in _SCRIPTS.items():
            fn = info["fn"]
            self.assertTrue(callable(fn), name)
            sig = inspect.signature(fn)
            required = [
                p for p in sig.parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                and p.default is p.empty
            ]
            has_varargs = any(p.kind is p.VAR_POSITIONAL
                              for p in sig.parameters.values())
            self.assertTrue(
                has_varargs or len(required) <= 2,
                f"{name}: fn 需要 {len(required)} 个位置参数，"
                "worker 只给 (config_path, params) 两个——"
                "三参数 builder 要用 _wrap_inventory 包一层")

    def test_rotate_captain_is_registered(self):
        self.assertIn("rotate_captain", _SCRIPTS)
        self.assertEqual(_SCRIPTS["rotate_captain"]["label"], "换队长")


if __name__ == "__main__":
    unittest.main()
