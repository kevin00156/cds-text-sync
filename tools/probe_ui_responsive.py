# -*- coding: utf-8 -*-
"""Manual probe: does the IDE stay usable while a script waits with system.delay()?

Run it from Tools > Scripting > Execute Script File... inside an open IDE, then
try to click menus, scroll editors and open dialogs for 45 seconds. Compare with
MODE = "sleep", which parks the primary thread in time.sleep() and is expected to
freeze the IDE on ScriptEngine 4.0/4.1 (e.g. DIADesigner-AX 1.10).

Nothing is modified; the script only writes a small log next to itself.
"""
import os
import time

MODE = "delay"          # "delay" (system.delay) or "sleep" (time.sleep)
SECONDS = 45
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_ui_responsive.log")


def log(s):
    f = open(LOG, "a")
    f.write(time.strftime("%H:%M:%S") + " " + s + "\n")
    f.close()


log("start mode=%s ui_present=%s" % (MODE, system.ui_present))
t0 = time.time()
n = 0
while time.time() - t0 < SECONDS:
    if MODE == "delay":
        system.delay(50)
    else:
        time.sleep(0.05)
    n += 1
    if n % 200 == 0:
        log("tick %d" % n)
log("done after %.1fs" % (time.time() - t0))
