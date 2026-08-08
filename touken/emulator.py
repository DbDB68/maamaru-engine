# -*- coding: utf-8 -*-
"""
MuMu 模拟器自启动 —— ADB 连不上时把模拟器自己拉起来

MuMu 12 的命令行管家：nx_main/MuMuManager.exe
  启动实例:  MuMuManager.exe control -v 0 launch
  查状态:    MuMuManager.exe info -v all（is_android_started）

血泪实测两条：
  1. 冷启动到 ADB 可用要约 4 分钟（轮询上限给 6 分钟）
  2. 实例起来后必须 adb connect 一次设备才会出现，光等着没用
"""

import json
import subprocess
import time


def _run(cmd, timeout=30):
    # CREATE_NO_WINDOW：无控制台父进程（worker/打包exe）里裸起
    # adb.exe/MuMuManager.exe（控制台程序）会弹窗抢焦点，必须隐藏
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(cmd, capture_output=True, timeout=timeout,
                          encoding="utf-8", errors="replace", creationflags=flags)


def adb_alive(adb_path: str, address: str) -> bool:
    try:
        r = _run([adb_path, "-s", address, "shell", "echo", "ok"], timeout=15)
        return (r.stdout or "").strip() == "ok"
    except Exception:
        return False


def ensure_emulator(adb_path: str, address: str, manager_path: str = None,
                    instance: int = 0, emit=print, max_wait_s: int = 360) -> bool:
    """确保模拟器在线：已经在跑秒回 True；没在跑就拉起来等开机"""
    if adb_alive(adb_path, address):
        return True
    if not manager_path:
        emit("[模拟器] ADB 连不上，也没配 MuMuManager 路径，没法自启动")
        return False

    emit(f"[模拟器] ADB 连不上，正在启动模拟器（实例 {instance}）...")
    try:
        r = _run([manager_path, "control", "-v", str(instance), "launch"], timeout=60)
        if r.returncode != 0 or '"errcode": 0' not in (r.stdout or ""):
            emit(f"[模拟器] 启动命令失败: {(r.stdout or r.stderr or '').strip()}")
            return False
    except Exception as exc:
        emit(f"[模拟器] 启动命令异常: {exc}")
        return False

    # 等安卓系统起来（实测约 4 分钟）
    deadline = time.time() + max_wait_s
    booted = False
    while time.time() < deadline:
        try:
            info = _run([manager_path, "info", "-v", "all"], timeout=30)
            d = json.loads(info.stdout or "{}")
            if d.get(str(instance), {}).get("is_android_started"):
                booted = True
                break
        except Exception:
            pass
        emit("[模拟器] 开机中，再等等...")
        time.sleep(10)
    if not booted:
        emit("[模拟器] 等了 6 分钟还没开完机，放弃")
        return False

    # adb connect（不 connect 设备不出现）+ 等系统 boot_completed
    for _ in range(24):
        _run([adb_path, "connect", address], timeout=15)
        if adb_alive(adb_path, address):
            try:
                r = _run([adb_path, "-s", address, "shell",
                          "getprop", "sys.boot_completed"], timeout=15)
                if (r.stdout or "").strip() == "1":
                    emit("[模拟器] 开机完毕，ADB 已连接 ✓")
                    return True
            except Exception:
                pass
        time.sleep(5)
    emit("[模拟器] 系统起了但 ADB/开机检查过不去，放弃")
    return False


def shutdown_emulator(manager_path: str, instance: int = 0, emit=print) -> bool:
    """关闭模拟器实例（跑完日课的'用完即走'可选项）"""
    try:
        r = _run([manager_path, "control", "-v", str(instance), "shutdown"],
                 timeout=60)
        ok = '"errcode": 0' in (r.stdout or "")
        if not ok:
            emit(f"[模拟器] 关闭命令失败: {(r.stdout or r.stderr or '').strip()}")
        return ok
    except Exception as exc:
        emit(f"[模拟器] 关闭异常: {exc}")
        return False


def sleep_computer(emit=print) -> bool:
    """电脑休眠（可选项！用户被 MAA 黑过屏，这功能必须手动勾才会触发）"""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                         creationflags=flags)
        return True
    except Exception as exc:
        emit(f"[日课] 休眠命令失败: {exc}")
        return False
