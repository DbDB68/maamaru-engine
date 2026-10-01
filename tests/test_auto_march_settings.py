import unittest
from unittest.mock import Mock, patch
from touken.auto_march_settings import march_policy, read_switch, apply_details
from touken.maa_adapter import Point


class MarchPolicyTests(unittest.TestCase):
    def test_thresholds_and_equipment_permission(self):
        self.assertIsNone(march_policy('light', 'continue', True, True, '横队阵'))
        p = march_policy('heavy', 'continue', True, True, '横队阵')
        self.assertEqual(p, {'medium': False, 'equipment': False, 'fatigue': True, 'formation': '横队阵'})
        self.assertTrue(march_policy('medium', 'stop', True, False, '鱼鳞阵')['equipment'])
        self.assertFalse(march_policy('medium', 'repair_stop', True, False, '鱼鳞阵')['equipment'])
        self.assertTrue(march_policy('medium', 'continue', False, True, '鱼鳞阵')['equipment'])
        self.assertTrue(march_policy('medium', 'continue', True, True, '鱼鳞阵')['medium'])
        self.assertFalse(march_policy('heavy', 'continue', True, False, '鱼鳞阵')['fatigue'])

    def test_unknown_reading_is_not_assumed_off(self):
        maa = Mock()
        maa.ocr.return_value = Point(1, 1)
        for tokens in ([], [('开', Point(1, 1)), ('关', Point(2, 2))]):
            maa.ocr_all.return_value = tokens
            self.assertIsNone(read_switch(maa, 'medium'))

    @patch('touken.auto_march_settings.time.sleep')
    def test_matching_policy_never_toggles_and_missing_title_never_clicks(self, sleep):
        maa = Mock()
        policy = march_policy('heavy', 'continue', True, True, '横队阵')
        with patch('touken.auto_march_settings.read_switch', side_effect=lambda m, k: policy[k]), patch('touken.auto_march_settings.selected_formation', return_value=True):
            self.assertTrue(apply_details(maa, policy))
            maa.click.assert_not_called()
        maa.ocr.return_value = None
        self.assertFalse(apply_details(maa, policy))
        maa.click.assert_not_called()

    @patch('touken.auto_march_settings.time.sleep')
    def test_toggle_must_be_confirmed_before_next_item(self, sleep):
        maa = Mock()
        policy = march_policy('heavy', 'continue', True, True, '横队阵')
        with patch('touken.auto_march_settings.read_switch', return_value=True):
            self.assertFalse(apply_details(maa, policy))
        maa.click.assert_called_once()

    def test_old_and_explicit_fatigue_values_reach_daily_plan(self):
        from panel.server import _daily_plan_inputs
        for mode in ('sortie', 'yosari'):
            self.assertTrue(_daily_plan_inputs({'sortie_mode': mode})[2]['stop_on_fatigue'])
            self.assertFalse(_daily_plan_inputs({'sortie_mode': mode, 'stop_on_fatigue': False})[2]['stop_on_fatigue'])
