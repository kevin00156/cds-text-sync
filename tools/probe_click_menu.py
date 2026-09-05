# -*- coding: utf-8 -*-
"""Click an IDE's File menu for real, repeatedly, and say whether it opened.

The measurement that decided the watcher's design (WATCHER_CLI_PLAN.md 14.2):
a window can be repainting, answering sent messages and processing posted ones
while still refusing every click, because system.delay() does not pump input.
Nothing short of real mouse input tells you which.

    python tools/probe_click_menu.py --pid 1234 --seconds 60 --every 5

It brings the window to the front, clicks a few pixels into the menu bar, and
counts the top-level windows the process owns before and after. A menu drop-down
is a window of its own, so one more window means the click landed. Escape closes
it again.

CPython 3 and ctypes; runs outside the IDE, never inside it. Reports the
windows it can see, so it doubles as "is the status form there?".
"""
from __future__ import print_function

import argparse
import ctypes
import ctypes.wintypes as wintypes
import sys
import time

user32 = ctypes.windll.user32

WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_ESCAPE = 0x1B
MENU_DY = 40  # from the top of the window frame to the menu bar
KEYEVENTF_KEYUP = 0x0002

ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def windows_of(pid):
    """Every visible top-level window the process owns, as (hwnd, title)."""
    found = []

    def visit(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append((hwnd, _title(hwnd)))
        return True

    user32.EnumWindows(ENUMPROC(visit), 0)
    return found


def _title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd) + 1
    buffer = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buffer, length)
    return buffer.value


def main_window(pid):
    """The biggest visible window the process owns: the IDE itself."""
    best, best_area = None, -1
    for hwnd, _title_text in windows_of(pid):
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)
        if area > best_area:
            best, best_area = hwnd, area
    return best


def is_hung(hwnd):
    """Windows' own verdict — true when it has stopped serving messages."""
    return bool(user32.IsHungAppWindow(hwnd))


def answers_sent_messages(hwnd, timeout_ms=1000):
    result = ctypes.c_ulong()
    return bool(user32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0,
                                           SMTO_ABORTIFHUNG, timeout_ms,
                                           ctypes.byref(result)))


def click_file_menu(pid, hwnd):
    """One real click on the menu bar. True when a drop-down appeared."""
    before = len(windows_of(pid))
    if not user32.SetForegroundWindow(hwnd):
        return None  # something else owns the foreground; not our answer to give
    time.sleep(0.3)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    # Into the menu bar. CODESYS 3.5.21 puts it ~40px below the frame top;
    # 55 lands between the menu and the toolbar and clicks nothing, and 75
    # hits a toolbar button and opens a dialog. On a different IDE, check
    # this offset before believing a "blocked" verdict.
    user32.SetCursorPos(rect.left + 30, rect.top + MENU_DY)
    time.sleep(0.1)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.5)
    opened = len(windows_of(pid)) > before
    user32.keybd_event(VK_ESCAPE, 0, 0, 0)
    user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.2)
    return opened


def run(pid, seconds, every):
    hwnd = main_window(pid)
    if hwnd is None:
        print("no visible window for pid %d" % pid)
        return 2
    print("window 0x%X  %r" % (hwnd, _title(hwnd)))
    for handle, title in windows_of(pid):
        print("  sees: 0x%X  %r" % (handle, title))

    opened = blocked = refused = 0
    deadline = time.time() + seconds
    while time.time() < deadline:
        verdict = click_file_menu(pid, hwnd)
        stamp = time.strftime("%H:%M:%S")
        if verdict is None:
            refused += 1
            print("%s  no foreground (something else is on top)" % stamp)
        elif verdict:
            opened += 1
            print("%s  menu opened   hung=%s sent=%s"
                  % (stamp, is_hung(hwnd), answers_sent_messages(hwnd)))
        else:
            blocked += 1
            print("%s  MENU BLOCKED  hung=%s sent=%s"
                  % (stamp, is_hung(hwnd), answers_sent_messages(hwnd)))
        time.sleep(every)

    print("opened %d, blocked %d, no-foreground %d" % (opened, blocked, refused))
    return 0 if blocked == 0 and opened > 0 else 1


def children_of(hwnd):
    """The texts of a window's child controls, in creation order."""
    found = []

    def visit(child, _lparam):
        found.append(_title(child))
        return True

    user32.EnumChildWindows(hwnd, ENUMPROC(visit), 0)
    return found


def find_window(pid, title):
    for hwnd, text in windows_of(pid):
        if text == title:
            return hwnd
    return None


def watch_labels(pid, title, seconds, out_path=None):
    """Follow what a window says, printing only when it changes.

    Written for the status window: this is how "did it really say BUSY while
    the export ran" gets answered from outside the IDE.
    """
    seen = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        hwnd = find_window(pid, title)
        line = " | ".join(children_of(hwnd)[:3]) if hwnd else "(no window)"
        if not seen or seen[-1] != line:
            seen.append(line)
        time.sleep(0.4)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(seen))
    for line in seen:
        print(line.encode("ascii", "replace").decode("ascii"))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pid", type=int, required=True,
                        help="the IDE process to click at")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--every", type=float, default=5.0)
    parser.add_argument("--list", action="store_true",
                        help="just show the windows and stop")
    parser.add_argument("--watch", metavar="TITLE",
                        help="follow that window's labels instead of clicking")
    parser.add_argument("--out", help="also write --watch output to this file")
    ns = parser.parse_args(argv)
    if ns.list:
        for hwnd, title in windows_of(ns.pid):
            print("0x%X  %r" % (hwnd, title))
        return 0
    if ns.watch:
        return watch_labels(ns.pid, ns.watch, ns.seconds, ns.out)
    return run(ns.pid, ns.seconds, ns.every)


if __name__ == "__main__":
    sys.exit(main())
