"""MuMu 显存截图通道的单元测试。dll 用 mock，真机验证走手动。"""
import ctypes
import unittest
from pathlib import Path
from unittest import mock

from touken import mumu_screen
from touken.mumu_screen import MumuScreen


def _fake_lib(frame_rgba: bytes | None = None, width: int = 4, height: int = 2,
              query_rc: int = 0, capture_rc: int = 0, handle: int = 7):
    """造一个假的 external_renderer_ipc。frame_rgba 是 w*h*4 的原始帧。"""
    lib = mock.MagicMock()
    lib.nemu_connect.return_value = handle

    def capture(h, display_id, buf_size, w_ptr, h_ptr, pixels):
        w = ctypes.cast(w_ptr, ctypes.POINTER(ctypes.c_int))
        h = ctypes.cast(h_ptr, ctypes.POINTER(ctypes.c_int))
        if buf_size == 0:
            if query_rc != 0:
                return query_rc
            w.contents.value = width
            h.contents.value = height
            return 0
        if capture_rc != 0:
            return capture_rc
        data = frame_rgba if frame_rgba is not None else bytes(buf_size)
        for i, b in enumerate(data):
            pixels[i] = b
        return 0

    lib.nemu_capture_display.side_effect = capture
    return lib


class FromAdbTests(unittest.TestCase):
    def test_standard_mumu_layout(self, ):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            shell = Path(tmp) / "MuMuPlayer" / "nx_device" / "12.0" / "shell"
            (shell / "sdk").mkdir(parents=True)
            (shell / "sdk" / "external_renderer_ipc.dll").write_bytes(b"x")
            (shell / "adb.exe").write_bytes(b"x")
            ms = MumuScreen.from_adb(str(shell / "adb.exe"), "127.0.0.1:16384")
            self.assertIsNotNone(ms)
            self.assertEqual(ms.instance_index, 0)
            self.assertEqual(ms.install_root,
                             (Path(tmp) / "MuMuPlayer").resolve())
            ms2 = MumuScreen.from_adb(str(shell / "adb.exe"), "127.0.0.1:16480")
            self.assertEqual(ms2.instance_index, 3)  # 16384 + 32*3

    def test_non_mumu_layout_returns_none(self):
        with mock.patch.object(Path, "is_file", return_value=False):
            self.assertIsNone(MumuScreen.from_adb("C:/adb/adb.exe",
                                                  "127.0.0.1:5555"))


class CaptureTests(unittest.TestCase):
    def _channel(self):
        return MumuScreen(Path("C:/MuMu"), Path("C:/MuMu/sdk/x.dll"))

    def test_capture_converts_rgba_to_bgr_and_flips(self):
        # 2x2 帧：上行[红, 绿]，下行[蓝, 白]（RGBA）
        frame = bytes([
            255, 0, 0, 255,  0, 255, 0, 255,      # 上行
            0, 0, 255, 255,  255, 255, 255, 255,  # 下行
        ])
        channel = self._channel()
        with mock.patch.object(mumu_screen.ctypes, "CDLL",
                               return_value=_fake_lib(frame, 2, 2)):
            img = channel.capture()
        self.assertIsNotNone(img)
        self.assertEqual(img.shape, (2, 2, 3))
        # 垂直翻转：原下行变第一行；RGBA→BGR：蓝(0,0,255) 仍是蓝
        self.assertEqual(list(img[0, 0]), [255, 0, 0])   # 蓝 BGR
        self.assertEqual(list(img[0, 1]), [255, 255, 255])
        self.assertEqual(list(img[1, 0]), [0, 0, 255])   # 红 BGR
        self.assertEqual(list(img[1, 1]), [0, 255, 0])   # 绿

    def test_query_failure_returns_none_and_counts(self):
        channel = self._channel()
        lib = _fake_lib(query_rc=-1)
        with mock.patch.object(mumu_screen.ctypes, "CDLL", return_value=lib):
            for _ in range(mumu_screen._MAX_FAILURES):
                self.assertIsNone(channel.capture())
        self.assertTrue(channel._dead)
        # 判死后不再碰 dll
        lib.nemu_connect.reset_mock()
        self.assertIsNone(channel.capture())
        lib.nemu_connect.assert_not_called()

    def test_connect_failure_returns_none(self):
        channel = self._channel()
        with mock.patch.object(mumu_screen.ctypes, "CDLL",
                               return_value=_fake_lib(handle=0)):
            self.assertIsNone(channel.capture())

    def test_dll_missing_marks_dead(self):
        channel = self._channel()
        with mock.patch.object(mumu_screen.ctypes, "CDLL",
                               side_effect=OSError("没有这个 dll")):
            self.assertIsNone(channel.capture())
        self.assertTrue(channel._dead)

    def test_recovery_after_transient_failure(self):
        # 一次抽风后下一次能重连恢复，不永久判死
        channel = self._channel()
        state = {"rc": -1}
        lib = _fake_lib(bytes(4 * 2 * 4), 2, 4)
        orig = lib.nemu_capture_display.side_effect

        def flaky(h, display_id, buf_size, w_ptr, h_ptr, pixels):
            if buf_size != 0 and state["rc"] != 0:
                return state["rc"]
            return orig(h, display_id, buf_size, w_ptr, h_ptr, pixels)

        lib.nemu_capture_display.side_effect = flaky
        with mock.patch.object(mumu_screen.ctypes, "CDLL", return_value=lib):
            self.assertIsNone(channel.capture())
            self.assertFalse(channel._dead)
            state["rc"] = 0  # 链路恢复了
            img = channel.capture()
        self.assertIsNotNone(img)
        self.assertEqual(img.shape, (4, 2, 3))


if __name__ == "__main__":
    unittest.main()
