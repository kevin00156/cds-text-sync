# 工單：IDE 內看門人 + 外部 CLI（REWORK_PLAN 階段 4）

> 建立日期：2026-09-04。分支 `feat/ide-watcher-cli`，從 `main`（`1919d8d`）開出。
> 背景研究與實測數據見 [`RESEARCH_HTTP_IDE_CONTROL.md`](RESEARCH_HTTP_IDE_CONTROL.md)，
> 尤其是 3.1、3.2、3.2.1 與 3.4 節。程式規範見 [`PRINCIPLES.md`](../PRINCIPLES.md)。
> 這份工單是給接手的人（或 agent）看的，讀完應該不用再翻對話紀錄。

---

## 1. 目標與範圍

**目標**：讓外部命令列工具在「IDE 開著、使用者照常操作」的情況下，對指定的 CODESYS IDE 實例下四種命令：匯出、匯入、比對、編譯。等待命令期間 IDE 不能卡；執行命令的那幾秒 IDE 會忙，這是平台限制，接受它。

**做**：

- IDE 內一支常駐的看門人腳本（watcher），在主執行緒上輪詢命令目錄。
- 一個純 Python 的協定模組，定義命令檔、結果檔、實例登記檔的格式與原子寫入。
- 一支 CPython 3 的 CLI，能列出活著的 IDE 實例、對其中一個下命令、等結果。
- 多個 IDE 同時開的支援：每個 IDE 各跑一支看門人，各有自己的目錄。

**不做**：

- 不做 HTTP、不做 MCP。這兩個之後包在 CLI 外面。
- 不用背景執行緒，不用 `execute_on_primary_thread`（SP21 已移除），不用 `time.sleep()` 等待。
- 不用 AP SDK，不用無頭第二實例。
- 不重寫現有的匯出、匯入邏輯。看門人只是「在 IDE 裡代替人按按鈕」。

---

## 2. 已定案的決策

| 決策 | 選擇 | 理由 |
|---|---|---|
| 命令通道 | 檔案目錄 | 社群專案已驗證；IronPython 端零網路程式碼；多 IDE 時一實例一目錄最直觀 |
| 先做什麼 | 只做 CLI | MCP 之後包在 CLI 外面，不影響 IDE 端設計 |
| 等待方式 | **計時器，腳本立刻返回**（2026-09-05 改，見第 14 節） | 原本選 `system.delay(50)`，但實測它只抽送重繪與投遞型訊息，**不處理滑鼠鍵盤**，使用者看到的就是「視窗活著但點不動」。改成 WinForms `Timer` 掛在 IDE 自己的訊息迴圈上，腳本返回後 IDE 完全可用；API 物件在返回後仍有效，SP21 與 Delta 1.10 都驗過 |
| 執行緒 | 全部在主執行緒 | 物件模型只能在主執行緒呼叫；SP21 的 ScriptEngine 4.2.0.0 已拿掉 `execute_on_primary_thread` |
| 分支 | `feat/ide-watcher-cli`，worktree 在 `..\kevin-cds-text-sync-watcher` | 原本的 checkout 停在 `fix/member-creation-parent-resolution`，有未提交的 readMe.md 修改，不要碰 |

---

## 3. 接手前必須知道的現況事實

這些是實際查過的，不是印象。

1. **活著的實作是根目錄的 `Project_*.py` 加上 `codesys_*.pyw`**，合計約 7,200 行。`cds/` 套件是 REWORK_PLAN 階段 0 的骨架，裡面有 14 個 `NotImplementedError`，根目錄沒有任何腳本 import 它。**看門人要呼叫的是活著的那一套，不是 `cds.app`。**
2. 四支腳本的入口函式與它們會彈的對話框：

   | 腳本 | 入口 | 會彈的對話框 |
   |---|---|---|
   | `Project_export.py` | `main()` 做 `load_base_dir()`、`init_logging()`，再呼叫 `export_project(base_dir)` | 結尾 `system.ui.info/error`；第 107 行 `ask_yes_no("Delete Orphaned Files?")` |
   | `Project_import.py` | `import_project(projects_obj=None)`，自己做 `load_base_dir()` | 第 80 行 `ask_yes_no("Version Mismatch Warning")`；第 172 行 `ask_yes_no("Confirm Import")`；結尾 `system.ui.info` |
   | `Project_compare.py` | `compare_project()` | 結尾 `system.ui.info`，另有互動式比對視窗（`codesys_ui_diff.pyw`） |
   | `Project_Build.py` | `build_project()` | 第 62 行多個 application 時 `system.ui.choose`；結尾 `system.ui.info/error` |

   另外 `codesys_utils.pyw` 第 116 行在嚴重錯誤時會 `system.ui.error`，第 524 行電腦名稱不符時會 `ask_yes_no_cancel`。
3. `ask_yes_no` 與 `ask_yes_no_cancel` 在 `codesys_ui.pyw` 第 55 到 90 行，走的是 WinForms 的 `MessageBox.Show`，不經過 `system.ui`。四支腳本都是在函式內部才 `from codesys_ui import ask_yes_no`，所以執行期把 `sys.modules["codesys_ui"].ask_yes_no` 換掉就能攔截，不必改那個檔。
4. 每支腳本開頭會把 `sys.modules` 裡所有 `codesys_*` 模組刪掉再用 `imp.load_source` 重載 `.pyw`。看門人若用 `exec` 執行腳本檔，這段會每次跑一次，攔截函式要在 `exec` 之後、呼叫入口函式之前裝上去。
5. `load_base_dir()`（`codesys_utils.pyw` 第 455 行）讀專案屬性 `cds-sync-folder`，沒設就回傳 `(None, 錯誤訊息)`，不會彈窗。
6. 腳本用 `resolve_projects(None, globals())` 找 `projects`，所以執行腳本的命名空間必須帶著 IDE 注入的 `projects`、`system`、`online` 等全域名稱。舊的 `Project_Daemon.py`（commit `4a66c05^`）用 `globals().copy()` 再 `exec`，可以參考。
7. IronPython 2.7 的內建 `open()` 讀出來是位元組，不接受 `encoding=` 參數。讀寫 UTF-8 一律用 `io.open(path, encoding="utf-8-sig")` 或 `codecs.open`。這是 commit `82d9904` 付過學費的事。
8. ~~`cds/` 從來沒有在 IDE 裡被 import 過。~~ **2026-09-04 已驗證可以。** 把 repo 根目錄加進 `sys.path` 之後，
   `from cds.core import commands, instances, ipc` 在三個 IDE 都成功，而且完整跑完一輪
   「寫命令、讀命令、寫結果、收結果、解析目標」。驗證腳本是 [`tools/probe_cds_import.py`](../tools/probe_cds_import.py)：

   | IDE | IronPython | ScriptEngine | 結果 |
   |---|---|---|---|
   | CODESYS 3.5.21.40 | 2.7.12 | 4.2.0.0 | OK |
   | Lenze PLC Designer 3.24.0 | 2.7.7 | 4.0.0.0 | OK |
   | Delta DIADesigner-AX 1.10 | 2.7.7 | 4.0.0.0 | OK |

   `os.getpid()` 三個都有，不必退回 `System.Diagnostics`。注意這三次都是無頭跑、沒有開專案，
   證明的是模組解析與純 Python 邏輯，不是互動式 IDE 底下的行為。
9. 本機三種 IDE 的 ScriptEngine 外掛版本：Delta 1.10 是 4.0.0.0，CODESYS 3.5.20.40 是 4.1.0.0，3.5.21.40 是 4.2.0.0。`system.delay()` 三個都有。
10. ~~`--runscript` 啟動時沒有看到獨立的進度視窗。從 Tools 選單啟動時有沒有，還沒量。~~
    **2026-09-05 已量，而且進度視窗不是重點。** 兩條啟動路徑在腳本跑著的時候都一樣點不動，
    根因是 `system.delay()` 不處理滑鼠鍵盤，見第 14 節。腳本返回後兩條路都恢復正常。
11. **WinForms 計時器在 `--noUI` 底下也會 tick**（2026-09-05 實測）。無頭實例沒有使用者，
    所以可以讓腳本停在 `system.delay()` 裡不返回，計時器照樣跑得到。
    `tools/probe_watcher_ui.py` 的 `CDS_PROBE_KEEPALIVE=1` 就是幹這個的，讓無頭驗收跑得起來。
    **絕對不要在有 UI 的情況下開這個開關**，那正是這次要修掉的病。

---

## 4. 架構

三個部分，每個檔案不超過 300 行（硬上限 400，見 PRINCIPLES §2）。

```
cds/core/ipc.py        目錄配置、實例編號、原子 JSON 讀寫。協定的地基。
cds/core/instances.py  實例登記檔、心跳、判活、清理陳舊登記、目標解析。
cds/core/commands.py   命令檔與結果檔的投遞與回收。
                       這三支都是純 Python，IronPython 2.7 與 CPython 3 都要能跑，
                       pytest 全覆蓋。
cds/ide/watcher.py     看門人每一拍做什麼：撿命令、執行、寫結果、心跳。不含啟動與停止，
                       所以在 CPython 底下測得到。
cds/ide/session.py     把看門人裝進一個活著的 IDE 再拆下來：掛計時器、腳本返回、
                       狀態放 sys、停止。這一半全是 .NET 與 sys 狀態，測不到。
cds/ide/silent.py      沒有人可以按對話框時，怎麼把 Project_*.py 跑完。
cds/ide/messages.py    編譯完去 IDE 的訊息庫把錯誤與位置撈出來。
cds/ide/project.py     問這個 IDE 現在開著什麼：專案路徑、同步資料夾、產品名稱。
Project_watch.py       薄入口，跟其他 Project_*.py 一樣出現在 Tools > Scripting > Scripts。
cli/cds_ide.py         CPython 3 的 CLI，只依賴 cds/core 的那三支。
tools/probe_watcher_ui.py  驗收用的啟動器，給 --runscript 跑。
tests/test_ipc.py      三支協定模組各自一個測試檔。
tests/test_instances.py
tests/test_commands.py
```

協定原本規劃成單一檔案 `cds/core/ipc.py`，寫出來 402 行，超過 PRINCIPLES §2 的硬上限。
拆成三支不是為了壓行數：目錄與檔案讀寫、誰還活著、命令怎麼交接，本來就是三件用「和」
才描述得完的事，PRINCIPLES §1 要求拆開。

模組命名要注意 IronPython 2.7 在沒有 `absolute_import` 時會先在套件內找同名模組。
`cds/core/commands.py` 其實跟 Python 2 的標準函式庫 `commands` 撞名（原本這裡寫「都不撞名」，那是錯的），
但實際無害：沒有任何地方做 `import commands`，而隱式相對匯入的遮蔽只影響 `cds/core/` 套件內部。

資料流：CLI 寫命令檔，看門人在下一次輪詢撿到、執行、寫結果檔並刪命令檔，CLI 讀到結果檔就刪掉它並回報。

---

## 5. 協定規格（`cds/core/ipc.py`）

### 5.1 目錄

根目錄 `%LOCALAPPDATA%\cds-text-sync\instances\`。每個 IDE 實例一個子目錄：

```
instances\
  <instance-id>.json          實例登記檔（心跳）
  <instance-id>\
    cmd\                      CLI 寫入的命令檔
    result\                   看門人寫入的結果檔
```

`instance-id` 是「專案檔主檔名-程序編號」，例如 `softplc_copy-17340`。專案路徑取自 `projects.primary.path`，程序編號用 `os.getpid()`，IronPython 沒有的話退回 `System.Diagnostics.Process.GetCurrentProcess().Id`。

### 5.2 實例登記檔

```json
{
  "instance_id": "softplc_copy-17340",
  "pid": 17340,
  "ide": "CODESYS 3.5.21.40",
  "project_path": "C:\\...\\softplc_copy.project",
  "project_name": "softplc_copy",
  "sync_dir": "C:\\...\\sync",
  "state": "idle",
  "busy_since": null,
  "heartbeat": "2026-09-04T20:41:05",
  "started_at": "2026-09-04T20:40:00",
  "watcher_version": "..."
}
```

- 看門人每 2 秒重寫一次（心跳）。執行命令前把 `state` 改成 `busy` 並寫入 `busy_since`，做完改回 `idle`。
- CLI 判定「活著」的規則：`state` 為 `idle` 且心跳在 10 秒內，或 `state` 為 `busy` 且 `busy_since` 在 CLI 的逾時範圍內。
- **不要用 `os.kill(pid, 0)` 檢查程序**。CPython 在 Windows 上的 `os.kill` 會直接終止目標程序。要查程序存不存在就用 `ctypes` 的 `OpenProcess`，或乾脆只信心跳。
- 看門人正常結束時刪掉自己的登記檔與子目錄。啟動時清掉陳舊的登記檔。
- 實作補上兩個上面 JSON 沒列的欄位：`heartbeat_epoch` 與 `busy_since_epoch`，都是 epoch 秒的數字。
  判活是拿時間相減，直接存數字就不必去解析本地時間字串，也避開日光節約時間那一小時的模糊地帶。
  原本的 `heartbeat` 與 `busy_since` 字串保留，那是給打開檔案的人看的。
- 「清掉陳舊登記檔」的條件：**`busy` 的登記檔一律不清**，只清 `idle` 且心跳超過 60 秒的。
  （2026-09-05 改，見第 15 節。原本的條件綁在 120 秒的命令逾時上，只保護得了跑不到兩分鐘的命令，
  而真專案的匯入就是會超過。）卡在 `busy` 的實例用「再跑一次 `Project_watch.py`」清掉。
- 寫檔的覆蓋動作：有 `os.replace` 就用它（CPython 3，覆蓋是原子的），沒有就退回「先刪目標再 rename」
  （IronPython 2.7 走這條）。Windows 上 `os.rename` 碰到目標已存在會直接失敗，而登記檔每 2 秒覆寫同一個檔名。

### 5.3 命令檔與結果檔

命令檔名 `<毫秒時間戳 13 位>-<6 位隨機十六進位>.json`，看門人按檔名排序一次處理一個。結果檔同名放在 `result\`。

```json
{"id": "1725453665123-a3f9c1", "command": "import", "args": {"yes": true, "force": false}, "created_at": "..."}
```

```json
{
  "id": "1725453665123-a3f9c1",
  "ok": true,
  "command": "import",
  "started_at": "...", "finished_at": "...", "elapsed_s": 4.2,
  "messages": [{"level": "info", "text": "Import complete! ..."}],
  "stdout_tail": "…最後 200 行…",
  "error": null,
  "needs_input": null
}
```

- `ok` 為 false 時 `error` 一定有文字。腳本問了問題但命令參數沒給答案時，`ok` 為 false，`needs_input` 放問題原文與該用哪個參數回答。
- 寫檔一律先寫 `<名稱>.tmp` 再 `os.rename` 成正式名稱，讀的一方永遠看不到半個檔。`.tmp` 檔讀的一方要忽略。
- CLI 讀完結果檔就刪掉。看門人啟動時清掉 `result\` 裡超過一小時的殘留。

### 5.4 命令清單與參數

| 命令 | 參數 | 對應 | 對話框的處理 |
|---|---|---|---|
| `ping` | 無 | 看門人直接回 | 無 |
| `status` | 無 | 回登記檔內容加上 `projects.primary` 的名稱與路徑 | 無 |
| `export` | `delete_orphans`（預設 false） | `export_project(base_dir)` | 「Delete Orphaned Files?」依參數回答 |
| `import` | `yes`（必要）、`force`（預設 false） | `import_project()` | 「Confirm Import」由 `yes` 回答，沒給就回 `needs_input`；「Version Mismatch」與「Computer Mismatch」由 `force` 回答，預設是不繼續 |
| `compare` | 無 | `compare_project()` | 互動式比對視窗在 silent 模式不能開；階段 2 先確認 `compare_project()` 在沒有差異要選時走哪條路，有需要就只回摘要 |
| `build` | `app`（多個 application 時必要） | `build_project()` | `system.ui.choose` 用 `app` 名稱對應到選項索引，沒給就回 `needs_input` |
| `stop` | 無 | 看門人寫結果後結束迴圈 | 無 |

---

## 6. 看門人規格（`cds/ide/watcher.py` 與 `Project_watch.py`）

> **2026-09-05：本節的「主迴圈 + `system.delay()`」設計作廢，改成第 14 節的計時器設計。**
> silent 模式的作法、實作時發現的四件事、薄入口的規則都還有效，只有「怎麼等」變了。

原本的主迴圈（已作廢）：

```python
while running:
    cmd = ipc.next_command(inst_dir)      # 沒有就回 None
    if cmd is not None:
        run_one(cmd)                      # 寫 busy、執行、寫結果、刪命令檔、寫 idle
    ipc.heartbeat_if_due(inst_dir)        # 每 2 秒
    system.delay(50)
```

實作時偏離上面這段的三個地方：

- **命令檔在執行前就刪掉，不是執行後。** 上面的資料流寫的是「執行、寫結果、刪命令檔」，
  但看門人如果在匯入做到一半死掉，那個匯入下次啟動會再被撿到、再跑一次。丟掉一個結果
  只是讓呼叫端等到逾時，重跑一次匯入會動到專案。所以改成讀到命令就先刪，再執行。
- **同一個 IDE 不准啟動第二支看門人。** 實例編號是專案名加程序編號，同一個 IDE 裡跑兩支
  會拿到同一個編號、搶同一個目錄。啟動時若發現同名登記檔還活著就直接報錯不啟動。
- **`SilentSystem` 移到階段 2 才寫。** 階段 1 的三個命令（`ping`、`status`、`stop`）都是看門人
  自己回答，不執行任何腳本，沒有東西需要攔截。PRINCIPLES §9 說先寫具體的東西。

硬性規定：

- 整支看門人不開執行緒、不 `time.sleep()`、不呼叫 `execute_on_primary_thread`。
- ~~`system.abortable = True`，按 Cancel 會丟 `KeyboardInterrupt`。~~ **2026-09-05 拿掉。**
  腳本已經不在跑，沒有進度顯示也沒有 Cancel 可按。停止方式改成 CLI `stop` 或再跑一次腳本。
- 每個命令的執行都包在 `try/except Exception`，錯誤寫進結果檔，看門人繼續。
- 看門人是唯一碰 `system` 與 `projects` 的新程式碼，放在 `cds/ide/`。

silent 模式的作法：

1. `SilentSystem`：一個代理物件，`__getattr__` 全部轉給真的 `system`，只有 `.ui` 換成 `SilentUI`。`SilentUI.info/warning/error` 把訊息記進結果的 `messages`；`choose` 依命令參數回答，否則丟 `NeedsInput`；`prompt/query_string/browse_directory_dialog` 一律丟 `NeedsInput`。
2. 執行某支腳本：讀檔，用 `globals().copy()` 當命名空間，把 `system` 換成 `SilentSystem`，`__name__` 設成非 `"__main__"` 的值以免腳本自己跑 `main()`，然後 `exec`。
3. `exec` 之後把 `sys.modules["codesys_ui"].ask_yes_no` 與 `ask_yes_no_cancel` 換成依命令參數回答的函式，沒答案就丟 `NeedsInput`。
4. 再呼叫入口函式。期間把 `sys.stdout` 換成「同時寫進原本 stdout 和一個緩衝區」的物件，結束後把緩衝區最後 200 行放進結果。
5. `NeedsInput` 被接住時，結果的 `ok` 是 false，`needs_input` 放問題原文與該用的參數名。

實作時發現的四件事，都寫在 `cds/ide/silent.py` 裡：

- **只換腳本自己的 `system` 不夠，`__main__.system` 也要換。** `codesys_utils.pyw` 第 517 行找 `system`
  的順序是「自己模組的 globals，再來 `__main__`」，而那些 `.pyw` 是用 `imp.load_source` 載入的，
  自己的 globals 裡沒有 `system`，所以一律走到 `__main__`。只換 exec 命名空間的話，那條路會拿到真的 UI。
- **`NeedsInput` 繼承 `BaseException` 而不是 `Exception`。** `Project_Build.py` 第 73 行把
  `system.ui.choose` 整段包在 `except Exception` 裡，如果 `NeedsInput` 是普通例外就會被吃掉，
  然後腳本會退回「編譯 active application」，等於使用者沒指定要編哪個、卻默默編了另一個。
  這跟 `KeyboardInterrupt` 不能被應用層的錯誤處理吃掉是同一個道理。
- **`exec` 要餵位元組不能餵 unicode。** 四支腳本都有 `# -*- coding: utf-8 -*-`，
  Python 2 的 `compile()` 碰到帶編碼宣告的 unicode 原始碼會直接丟 SyntaxError。所以用二進位模式讀檔，
  順手把 BOM 去掉（Python 2 的 `compile()` 也不吃 BOM）。
- **成功與失敗只能從對話框的層級判斷。** 四支腳本的 `main()` 不論成敗都回 `None`，
  唯一的訊號是它有沒有呼叫 `system.ui.error` 或 `system.ui.warning`。所以規則是：
  代理 UI 收到 `warning` 或 `error` 就算這個命令失敗。這四支腳本裡這兩個層級只出現在中止的地方，
  規則成立；以後有人加了純資訊性的 warning，這裡要跟著改。

薄入口 `Project_watch.py`：跟其他 `Project_*.py` 一樣的檔頭與模組載入方式，唯一的工作是把自己的目錄加進 `sys.path`、`import cds.ide.watcher`、呼叫 `watcher.main(globals())`。

---

## 7. CLI 規格（`cli/cds_ide.py`）

```
python cli/cds_ide.py list
python cli/cds_ide.py ping    [--target X]
python cli/cds_ide.py status  [--target X]
python cli/cds_ide.py export  [--target X] [--delete-orphans]
python cli/cds_ide.py import  [--target X] --yes [--force]
python cli/cds_ide.py compare [--target X]
python cli/cds_ide.py build   [--target X] [--app NAME]
python cli/cds_ide.py stop    [--target X]
共用選項：--timeout 秒（預設 120）、--json
```

- `--target` 的解析順序：完整 `instance-id`；專案主檔名（不分大小寫）且活著的實例只有一個；省略時活著的實例只有一個就用它。有多個符合就列出來並以 exit code 2 結束。
- Exit code：0 成功，1 命令執行失敗（含 `needs_input`），2 找不到或找不清目標，3 逾時。
- 人類可讀輸出印 `messages` 與 `error`；`--json` 印整個結果檔。
- 只依賴標準函式庫與 `cds.core.ipc`。

---

## 8. 多個 IDE 同時開

- 每個 IDE 各自從 Tools > Scripting 啟動一次 `Project_watch.py`（用 Execute Script File 指路徑即可，不必裝進各 IDE 的 ScriptDir）。
- 每個實例一個目錄，命令互不干擾，兩個 IDE 的命令可以同時執行。
- 同一個 `.project` 不能被兩個 IDE 開，IDE 自己會擋，CLI 不必處理。
- 看門人跑著的時候，那個 IDE 的 Scripting 選單大概不能再啟動別的腳本。這點沒驗證，階段 1 順手確認並寫進 readMe。

---

## 9. 分階段與驗收條件

每階段獨立可跑、可測、可 commit。commit 訊息跟著 `main` 上的風格：一句祈使句，說明為什麼。

- [x] **階段 0：協定**
  - [x] `cds/core/ipc.py`、`cds/core/instances.py`、`cds/core/commands.py`：目錄配置、實例登記讀寫、心跳、命令與結果的原子讀寫、陳舊檔清理、目標解析。
  - [x] `tests/test_ipc.py`、`tests/test_instances.py`、`tests/test_commands.py`：原子寫入、排序、心跳判活、目標解析的四種情況、`.tmp` 忽略。CPython 3 下 `python -m pytest` 全綠。
  - [x] 驗收：測試綠（187 個，其中 49 個是新增的）。
- [ ] **階段 1：看門人只會 ping、status、stop**
  - [x] 在 IDE 裡驗證 `import cds.core.ipc` 能過。三個 IDE 都過，見第 3 節第 8 點。
  - [x] `cds/ide/watcher.py` 主迴圈、心跳、命令分派。`SilentSystem` 移到階段 2，見第 6 節。
  - [x] `Project_watch.py` 薄入口。
  - [x] `cli/cds_ide.py` 的 `list`、`ping`、`status`、`stop`。
  - [x] `tests/test_watcher.py`、`tests/test_cds_ide_cli.py`：看門人的迴圈與生命週期用假的 `system` 驅動，
        CLI 與看門人在同一個行程裡對打，涵蓋完整往返、逾時、Ctrl+C 不留殘檔。
  - [x] 驗收（無頭部分，2026-09-04 自動跑完）：在 CODESYS 3.5.21.40 與 Delta 1.10 各起一個無頭實例、
        各跑一支看門人，`list` 看到兩個，`ping --target` 各自回得來，不給 `--target` 時以 exit code 2 列出候選，
        `stop` 之後登記檔與子目錄都消失、IDE 程序自己退出。
  - [ ] 驗收（還需要人）：專案開著的情況下重跑一次上面那串，並確認看門人跑著時人在 IDE 裡點選單、捲編輯器都不卡。
        無頭實例沒有 UI 也沒有專案，這兩件事驗不到。
  - [ ] 順手確認：看門人跑著時能不能從選單再啟動別的腳本。
- [ ] **階段 2：四個真命令**
  - [x] `cds/ide/silent.py`：代理 UI、攔截三個 `codesys_ui` 對話框、換掉 `__main__.system`、捕捉 stdout 尾巴、`NeedsInput`。
  - [x] `export`、`import`、`compare`、`build` 接上四支活著的 `Project_*.py` 的 `main()`。
  - [x] `cli/cds_ide.py` 的四個子命令與 `--delete-orphans`、`--yes`、`--force`、`--app`。
  - [x] `tests/test_silent.py`：用形狀跟真腳本一樣的替身腳本驗證命名空間、對話框作答、stdout 尾巴、還原。
  - [x] 驗收（2026-09-04 在無頭的 CODESYS 3.5.21.40 上自動跑完，用 `%TEMP%\cds-wtest\wtest.project` 這個臨時專案）：
        `export` 之後磁碟出現 `Sample.st`，內容正確；在磁碟新建 `Greeter.st` 之後 `compare` 回報「only on disk 1」；
        `import` 不帶 `--yes` 回 `needs_input`、exit code 1、沒有任何彈窗；`import --yes` 之後 `Greeter` 真的出現在 IDE 的物件樹裡。
  - [x] 驗收：`build` 回錯誤數。2026-09-05 在兩個真專案的副本上跑完，見第 16 節：
        正常 0 errors、故意放語法錯 1 error 且 exit code 1，錯誤訊息連物件與位置都回得來
        （那份細節是這一輪新增 `cds/ide/messages.py` 才有的，見 16.3）。
  - [ ] 驗收（還需要人）：命令執行中 IDE 忙、結束後恢復。無頭實例沒有 UI，看不到；
        第 14.7 節的點擊儀器量的是「命令之間」可操作，「命令執行中不可操作」那半沒有單獨量過。
- [x] **階段 3：收尾**
  - [x] CLI 逾時（exit code 3、順手把沒跑到的命令檔撤掉）、中途 Ctrl+C 不留殘檔、看門人重啟後清掉陳舊登記。
  - [x] 看門人每答完一個命令順手清一次結果目錄，不只在啟動時清。逾時的呼叫端會留下沒人收的結果檔，
        一支連跑好幾天的看門人不能一直累積。
  - [x] **修掉一個並發實測才抓到的當機**，見下面第 12 節。
  - [x] readMe 加了「Driving the IDE from a terminal」一節，寫清楚等待不卡、執行會忙，以及四個旗標各自回答哪個問題。
  - [x] 驗收（2026-09-04 無頭自動跑完）：CODESYS 3.5.21.40 開 `cds-alpha`、Delta 1.10 開 `cds-beta`，
        兩個各 60 個 POU，同時各跑一次 `export`，兩邊都成功、各自寫進自己的同步資料夾、各 60 個 `.st`，
        期間另一個行程連續跑了 401 次 `list` 去撞登記檔，兩支看門人都活著。
- [x] **階段 4：改成計時器設計（2026-09-05，見第 14 節）**
  - [x] `cds/ide/watcher.py`：主迴圈換成 `tick()`；重入保護；tick 內接住 `SystemExit` 以外的所有例外。
  - [x] `cds/ide/session.py`：`main()` 掛好計時器就返回、狀態放在 `sys._cds_watcher`、`stop()`、
        `_winforms_timer()`。跟 `watcher.py` 分開是因為這半邊全是 .NET 與 `sys` 狀態，在 CPython 底下測不到；
        分開之後 `watcher.py` 那半邊測得到，兩邊合起來原本是 328 行，也超過 PRINCIPLES §2 的 300 行軟目標。
  - [x] `Project_watch.py`：再跑一次等於 stop（切換式），跟 CLI `stop` 一樣的收尾。拿掉 `system.abortable` 與 `KeyboardInterrupt`。
  - [x] `tests/test_watcher.py` 改成驅動 tick，涵蓋：重入時第二個 tick 直接返回、tick 內例外不會外洩、
        `main()` 掛計時器後返回、再跑一次等於 stop、`stop` 命令的答案在下一拍才拆台（讓呼叫端有一整拍可以收）。
  - [x] `tools/probe_watcher_ui.py`：給 `--runscript` 用的驗收啟動器。
  - [x] 驗收（監督者自動跑，2026-09-05）：CODESYS 3.5.21.40 上看門人上線後，兩個命令之間每次真實點擊 File 選單都開出下拉；`ping`、80 個 POU 的 `export`（7.5 秒）、`stop` 全部成功；stop 後 `list` 為空、選單仍可點。Delta 1.10 上 `ping`、`export`、`stop` 同樣全過，真實點擊的儀器被桌面上一個無關的最上層視窗擋住，改由使用者當天稍後在真實專案上手動確認**可操作**。細節見 14.7 節。
  - [x] 驗收（無頭，2026-09-05 跑完）：先確認 `--noUI` 底下 WinForms 計時器真的會 tick
        （探針用 `CDS_PROBE_KEEPALIVE=1` 停在 `system.delay()` 裡，`ping` 回得來就證明計時器有跑）。
        然後階段 1 到 3 全部重跑：`list`、`ping --target`、`status`、不給 target 時 exit code 2、`stop` 後程序自己退出且不留殘檔；
        `export` 寫出 5 個 `.st`、`compare` 在同步時與有新檔時都正確、`import` 不帶 `--yes` 回 `needs_input`、`import --yes` 真的建了物件；
        CODESYS 3.5.21.40 與 Delta 1.10 各 60 個 POU 同時匯出，兩邊各 60 個 `.st`，期間 158 次 `list` 撞登記檔，
        沒有任何一次 `tick failed` 或 `heartbeat deferred`。

---

## 10. 測試方式

- `cds/core/` 那三支全部 pytest，CPython 3.12，CI 現有設定就會跑（`conftest.py` 已把 repo 根目錄放進 `sys.path`）。
- **不需要開 IDE 就能驗的 IronPython 行為，用無頭 `--runscript` 自己跑**，不必請人手動點。2026-09-04 三個 IDE 都成功：

  ```
  <exe> --profile="<設定檔名>" --noUI --runscript="<腳本絕對路徑>"
  ```

  `--noUI` 一定要配 `--profile`，少了會直接退出並印「you must specify a profile」。設定檔名就是
  `<安裝根目錄>\...\Profiles\*.profile.xml` 的主檔名。本機三個是 `CODESYS V3.5 SP21 Patch 4`、
  `PLC Designer V3.24.0`、`DIADesigner-AX 1.10`。腳本的 `print` 會進 stdout，抓得到。
  無頭實例沒有專案也沒有 UI，所以這條路驗得了模組載入與純 Python 邏輯，驗不了
  「使用者正在操作 IDE 時看門人卡不卡」——那個仍然只能手測。
- 看門人與 CLI 的整合只能手測。每次手測前先用 `tools/probe_ui_responsive.py` 確認那台 IDE 在 `system.delay()` 下可操作，這支腳本從 Tools > Scripting > Execute Script File 執行，45 秒內試著點選單。
- **這個 worktree 沒有掛進任何 IDE 的 ScriptDir**（`%LOCALAPPDATA%\CODESYS\ScriptDir\cds-text-sync` 指的是隔壁的主 repo），
  所以 worktree 裡的腳本不會出現在 Tools > Scripting 的清單裡。手測時要嘛用 Execute Script File 指絕對路徑，
  要嘛另外開一個 junction 指向這個 worktree。
- IronPython 相容性：`from __future__ import print_function`、不用型別註記、不用 f-string、不用 `pathlib`，只用標準函式庫。

---

## 11. 未決事項（實作時決定，決定了寫回這裡）

1. ~~協定模組放 `.py` 還是 `.pyw`~~：**定案 `.py`，三支都在 `cds/core/`**（見第 4 節的拆分說明）。
   2026-09-04 在三個 IDE 實測過 `import cds.core`，都成功，見第 3 節第 8 點。
2. ~~`compare` 在 silent 模式要不要保留「互動式挑選」~~：**定案不要**。`show_compare_dialog` 被換成一個
   直接回 `(None, [])` 的函式，並把那個視窗本來要列的數字寫成一則訊息（改了幾個、只在 IDE 有幾個、
   只在磁碟有幾個、搬過家幾個、一樣的幾個）。逐一物件的清單腳本本來就印在 stdout，會進 `stdout_tail`。
3. 心跳 2 秒、活著 10 秒、陳舊 60 秒這三個數字是起點，不是定案。
4. `Project_Build.py` 與 `Project_export.py` 已超過 400 行的硬上限。這張工單不動它們，但不要再往裡面加東西。
5. 登記檔的 `sync_dir` 階段 1 一律是 null。要填它得呼叫 `codesys_utils.load_base_dir()`，
   而階段 1 的看門人還沒載入那些 `.pyw` 模組。階段 2 本來就要載入，屆時順手填上。

---

## 12. 並發實測抓到的當機（2026-09-04）

兩個 IDE 同時匯出的驗收第一次跑，其中一支看門人整個死掉，登記檔連同目錄一起消失，CLI 回報「找不到 cds-alpha」。
IDE 的 stderr 留下這一行：

```
WindowsError: [Errno 13] The process cannot access the file because it is being used by another process
```

**根因是 Windows 的檔案共用規則。** 一個程序把檔案開著讀的時候，別的程序既不能刪它、也不能把另一個檔案改名蓋過它。
Python 開檔預設沒有要求 `FILE_SHARE_DELETE`。而這個協定的兩端剛好就是這樣：看門人每 2 秒把同一個登記檔覆寫一次
（先寫 `.tmp` 再改名蓋過去），CLI 每下一個命令就要把所有登記檔打開來讀一遍決定目標是誰。兩件事撞在一起的窗口只有幾微秒，
但一天下來會撞到。

撞到之後的骨牌是這樣倒的：心跳的改名丟出例外，例外一路往上衝出主迴圈，`finally` 呼叫 `shutdown()`，
`shutdown()` 要刪的正是同一個還被開著的檔案，於是又丟一次，把原本的死因蓋掉。看門人就這樣沒了。

**修法是接受這件事會發生，而不是想辦法避開它。**

- 心跳寫失敗不算致命：印一行訊息、這一輪不更新 `_last_beat`，下一輪（50 毫秒後）自己重試。讀的那一方只開檔幾微秒，
  下一輪幾乎一定成功。判活的容忍是 10 秒，中間漏幾拍沒有影響。
- 同一段話只印一次，不是每輪都印。重試是每 50 毫秒一次，全印會把 IDE 的訊息視窗洗掉。
- `shutdown()` 刪不掉登記檔也不丟例外，只印一行。留下來的陳舊登記檔會被下一支看門人的 `prune_stale` 清掉，
  而在 `finally` 裡丟例外會把真正的死因蓋掉。
- `write_json` 改名失敗時順手把自己的 `.tmp` 刪掉，不留半成品。

**驗證方式**：另外開一個程序把登記檔開著不放 8 秒，看門人印出一次 `heartbeat deferred`、重試了 128 次、
8 秒後自己恢復，`ping` 照常回得來，目錄裡沒有殘留的 `.tmp`。修之前這個情境會直接讓看門人死掉。
單元測試用注入例外的方式蓋住這三條路徑。

**還沒查證的**：讀的那一端能不能改成要求 `FILE_SHARE_DELETE` 開檔，讓這個窗口從根本消失。純 Python 做不到，
IronPython 那邊可以透過 .NET 的 `FileShare.Delete`，但 CLI 是 CPython，兩端要一致就得動 `ctypes`。
目前的容忍作法已經夠用，先不做。

---

## 13. 接手 prompt

把下面這段原封不動貼給接手的 session 或 agent：

```
你在 C:\Users\qazsskevin\Documents\repo\kevin-cds-text-sync-watcher，分支 feat/ide-watcher-cli，
從 main 開出。這是一個 git worktree；隔壁 ..\kevin-cds-text-sync 停在另一個修 bug 的分支，
有未提交的修改，不要碰它。

先讀這三份，順序照這樣：
1. docs/WATCHER_CLI_PLAN.md（這張工單，含所有已定案的決策與驗收條件）
2. docs/RESEARCH_HTTP_IDE_CONTROL.md 的 3.1、3.2、3.2.1、3.4 節（為什麼是 system.delay、為什麼不能開執行緒、實測數據）
3. PRINCIPLES.md（檔案 400 行硬上限、函式 60 行硬上限、兩層邊界、IronPython 2.7 相容規則）

然後從工單第 9 節的階段 0 開始做。規則：
- 一個階段做完、測試綠、commit，再進下一階段。不要一次全做。
- 看門人呼叫的是根目錄 Project_*.py 裡活著的函式，不是 cds/app 的 stub。
- IDE 端不開執行緒、不 time.sleep、不 execute_on_primary_thread。
- 要在 IDE 裡手測的步驟（階段 1 與階段 2 的驗收）做不到就停下來告訴我，
  把要我手動做的事列成清單，不要假裝做過。
- 工單第 11 節的未決事項，你決定了就寫回工單。
- commit 訊息一句祈使句說明為什麼，跟 main 上既有的風格一致。不要 push。

現在先回我一句你讀完後對階段 0 的理解，包含你打算把協定模組放哪裡、測試要蓋哪些情況，
然後開始。
```


---

## 14. 2026-09-05 修正：`system.delay()` 不處理使用者輸入，改成計時器設計

### 14.1 使用者回報

從 Tools 選單啟動 `Project_watch.py` 之後，功能正常，但 IDE 主視窗點不動；按進度顯示上的 Cancel 腳本就停。跟 1.6.x 那支 daemon 沒有實質差別。

### 14.2 根因（已用真實輸入實測）

前一天的實測儀器只量了三件事：Windows 有沒有判定視窗凍結、送達型訊息有沒有回應、投遞的「最小化」訊息有沒有被處理。三個都過，所以下了「可操作」的結論。這個結論是錯的，因為那三個訊號都不是使用者輸入。

2026-09-05 換成真的滑鼠：每 5 秒把 IDE 拉到前景，對選單列最左邊的 File 點一下，看有沒有長出下拉視窗（WinForms 的下拉是一個獨立的頂層視窗，用 `EnumWindows` 數得到）。結果：

| 情境 | 腳本開始前 | `system.delay(50)` 迴圈期間 |
|---|---|---|
| 選單路徑（用計時器在沒有腳本脈絡時呼叫「Execute Script File...」命令，跟點選單同一條路） | 下拉會開 | **每次都開不出來** |
| 啟動參數路徑（`--runscript`） | 未量到基準 | **每次都開不出來** |

也就是說，`system.delay()` 抽送的是重繪、計時器、送達型與投遞型的非輸入訊息，滑鼠鍵盤被過濾掉。這解釋了為什麼看門人回得了 CLI（訊息迴圈在轉）、視窗不會變成「沒有回應」、但人就是點不動。兩條啟動路徑都一樣，所以「改用 `--runscript` 啟動」也不是解法。這跟 2012 年官方講的「主執行緒是腳本的」一致：只要腳本還在跑，UI 就不是使用者的。

只在 CODESYS 3.5.21.40 上做了真實點擊測試；Delta 1.10 沒有量輸入，但機制相同，不另外假設它會不一樣。

### 14.3 解法：讓腳本結束，把工作掛在 IDE 自己的訊息迴圈上

`Project_watch.py` 啟動時建立一個 WinForms `Timer`（間隔 200 到 500 毫秒），把 tick 處理器掛上去，然後**立刻返回**。腳本結束後進度顯示消失、IDE 完全回到使用者手上；每次 tick 在 IDE 自己的訊息迴圈上跑，做的事跟原本主迴圈一輪一樣：撿命令、執行、寫結果、心跳。

這條路的前提是「腳本返回後 CODESYS 的 API 物件還能用」。2012 年官方警告過返回後暫存狀態會被清掉，所以實測了兩輪，SP21（ScriptEngine 4.2.0.0）與 Delta 1.10（4.0.0.0）都過：

| 檢查 | 返回後 | 使用者又從選單跑了另一支腳本之後 |
|---|---|---|
| 抓在手上的 `projects.primary.path` | OK | OK |
| 抓在手上的 `primary.get_children()` | OK | OK |
| 抓在手上的 `system.write_message` | OK | OK |
| 抓在手上的 `system.delay(10)` | OK | OK |
| `__main__.projects` 仍是同一個物件 | 是 | 是 |

另外實測到一件事：腳本返回後前 10 到 15 秒 IDE 可能還在忙（例如剛建完專案在載入程式庫），計時器要等它閒下來才會開始 tick。這不是問題，只是別把「第一個 tick 沒馬上來」當成故障。

### 14.4 設計規則

- **狀態放在 `sys` 的屬性上**（例如 `sys._cds_watcher`），不要放在腳本模組的全域。1.6.x 的 daemon 就是這樣做的，原因是腳本結束後模組命名空間不保證還在，而 `sys` 一定在。計時器物件也要放在裡面，免得被回收。
- **重入保護。** 匯入、編譯這種命令會抽送訊息（對話框、`system.delay`、進度），抽送期間計時器會再 tick。tick 一進來先看 busy 旗標，busy 就直接返回。
- **tick 內接住一切。** WinForms 的 tick 處理器丟出沒接住的例外，會直接變成 IDE 的執行緒例外對話框，可能把 IDE 帶下去。tick 要用 `except BaseException` 接住（`SystemExit` 除外），寫進結果檔或 log，然後繼續。`NeedsInput` 是 `BaseException` 的子類，在命令層就已經接住，不會漏到這裡。
- **停止方式有兩種**：CLI `stop`，以及再跑一次 `Project_watch.py`（切換式，跟 1.6.x 一樣）。兩種都走同一個收尾：停計時器、刪登記檔與目錄、清 `sys` 上的狀態。原本的「按 Cancel 停止」沒有了，因為腳本已經不在跑；`system.abortable` 那行拿掉。
- **心跳照舊在 tick 裡做。** 命令執行中發不出心跳，登記檔的 `busy` 狀態已經處理這件事（第 5.2 節）。
- **不開執行緒、不 `time.sleep()`、不 `execute_on_primary_thread`** 這三條不變。tick 本身就在 UI 執行緒上，不需要任何跨執行緒的東西。
- **同一個 IDE 只准一支**：啟動時檢查 `sys` 上有沒有活著的狀態；有就當作「再跑一次 = stop」。

### 14.5 驗收怎麼做

監督者手上有一套會做真實點擊的儀器（PowerShell，`SetForegroundWindow` 加 `mouse_event` 點 File 選單，數下拉視窗）。流程：

1. 用 `--runscript` 啟動 CODESYS 3.5.21.40，跑 `tools/probe_watcher_ui.py`：它建臨時專案、設 `cds-sync-folder`、走 `Project_watch.py` 的啟動路徑、返回。
2. 儀器每 5 秒點一次 File 選單，要求每次都開得出下拉。
3. 期間從外面跑 `cds_ide.py ping`、`export`、`stop`，三個都要成功；`export` 期間那幾秒點不開是正常的，之後要恢復。
4. `stop` 之後登記檔消失，選單仍可點。

前一天的「已驗收」項目裡凡是寫「IDE 可操作」的，都要以這一輪為準重新驗。

### 14.6 對研究筆記的影響

`RESEARCH_HTTP_IDE_CONTROL.md` 第 3.2.1 節的結論「可操作」已加註更正。社群專案 Codesys-MCP-SP21-plus 宣稱 `system.delay()` 讓 UI 可互動，這個說法以本機實測來看不成立。

### 14.7 驗收結果（2026-09-05 凌晨，監督者自動跑）

儀器：`SetForegroundWindow` 加 `mouse_event` 對選單列最左邊的 File 做真實點擊，用 `EnumWindows` 數有沒有長出下拉視窗；同時從外面用 `cli/cds_ide.py` 下命令。啟動器是 `tools/probe_watcher_ui.py`，`CDS_PROBE_POUS=80`。

| 項目 | CODESYS 3.5.21.40 | Delta DIADesigner-AX 1.10 |
|---|---|---|
| 看門人上線（`list` 看到自己的 pid） | 建完 80 個 POU 後約 +125 秒 | 約 +81 到 +105 秒 |
| 上線後、命令之間點 File 選單 | 開得出來（連續多次，只有一次緊接在 ping 後失敗） | 儀器失效，見下 |
| `ping` | 成功 | 成功 |
| `export`（80 個 POU） | 成功，IDE 內 7.5 秒 | 成功，IDE 內 6.3 到 7.2 秒 |
| `stop` 後 `list` | 空 | 空 |
| `stop` 後點 File 選單 | 開得出來 | 儀器失效，見下 |

另外驗了「從選單啟動」這條路的計時器會不會被收掉：用啟動腳本裡的計時器去呼叫「Execute Script File...」命令跑一支只掛計時器就返回的腳本，命令返回後那支腳本的計時器照樣 tick，`projects` 與 `system` 照樣可用（tick 1、5、20 都 OK）。所以 `Project_watch.py` 從 Tools 選單啟動後返回，看門人會活著。

Delta 的點擊儀器失效的原因：桌面上開著一個「AORUS Control Center」視窗（使用者自己的程式，約 00:47 出現在最上層），`SetForegroundWindow` 對 Delta 視窗一直回 False，WinForms 的 MenuStrip 在視窗不是作用中時會吞掉點擊，改成投遞 Alt+F 訊息也只會把 File 反白、不開下拉。這跟看門人無關：連 `stop` 之後、沒有任何腳本在跑的時候也點不開。監督者沒有動那個視窗。

還需要人的兩件事：在 Delta 1.10 上從 Tools 選單啟動 `Project_watch.py`，點個 30 秒選單確認可操作；在有 application 的真專案上跑一次 `build` 看錯誤數。

**第一件當天稍後由使用者做完了。** 他在自己的真實專案 `Shm_2026.07.29` 上，從 Delta 1.10 的 Tools 選單啟動
`Project_watch.py`，回報 **IDE 內確實可操作**。同時從外面量到登記檔正常、`list` 看得到、`status` 往返 57 毫秒，
證明計時器確實在 IDE 自己的訊息迴圈上 tick。這補上了 4.0.0.0 這一版原本只能靠「機制相同」推論的那一格：
計時器設計在 ScriptEngine 4.0.0.0 與 4.2.0.0 兩個大版本上都有真人資料。

---

## 15. 審查後的修正與取捨（2026-09-05）

獨立的 reviewer 對 `feat/ide-watcher-cli` 相對 `main` 的全部差異做了審查，結論是必修 3 條、建議 11 條、
不改 8 條。**必修與建議全部採納並修掉了**，理由是建議裡有好幾條正好卡在第二階段要做的事情上：
AI 工作迴圈要靠 `status` 問同步資料夾在哪、要靠 `list` 挑目標、要靠 `build --app` 編對的 application，
這三件事在修之前都不成立。

### 必修

**腳本放棄卻沒開對話框時，命令會回報成功。** `Project_import.py` 有兩條放棄路徑只 `print()` 就返回，
不經過 `system.ui`。判斷成敗的規則是「代理 UI 有沒有收到 warning 或 error」，於是找不到失敗訊號，
`ok` 是 true、exit code 0。對 agent 來說這是最壞的一種錯：它會以為匯入成功、接著去編譯，
編的是沒被更新過的舊程式碼。兩層都補了：`Outcome.error_text()` 多一條規則，整輪跑完連一則 `info`
都沒有就算失敗（四支腳本成功時一定會呼叫一次 `system.ui.info`，所以不會誤判）；
`Project_import.py` 那兩行 `print` 改成 `system.ui.warning`，讓訊息本身帶出原因。

**`run_one` 有三行在 `try` 外面，出事就把實例永久卡在 `busy`。** 寫結果、清結果目錄、寫回 idle
三個動作都在保護範圍外，任何一個丟例外，登記檔就停在 `busy`。之後 120 秒一到 CLI 判它死了、
`list` 看不到它，而 `prune_stale` 又因為心跳是新的而不清它——沒有任何一方會自己修好。
現在全部搬進 `try`，「寫回 idle」放在 `finally`，`prune_results` 也容忍檔案在列出後才被刪掉
（CLI 讀到結果就立刻刪，那個窗口是真的）。

**`prune_stale` 會刪掉正在執行長命令的實例。** 原本的保護是「心跳過期**而且** `is_alive` 也說它死了」，
而 `is_alive` 對 `busy` 看的是 120 秒的命令逾時。所以保護只在命令跑不到兩分鐘時成立，
而第三階段要跑的正是真專案的匯入。改成 **`busy` 的登記檔一律不清**，只清 idle 且心跳過期的。
把「清死人留下的檔案」跟「判斷命令跑太久」綁在同一個數字上本來就是錯的，那是兩件事。
卡在 `busy` 的實例改用「再跑一次 `Project_watch.py`」清掉。

### 建議

全部照做，其中幾條值得記下為什麼：

- **`--timeout` 在同一支 CLI 裡有兩種意思。** `list` 拿它當忙碌容忍度，`run_on_target` 卻先用寫死的
  120 秒過濾一次。使用者調高 `--timeout` 的目的正是要等長命令，結果 `list` 看得到、`ping` 說找不到。
- **登記檔的專案欄位永遠停在啟動那一刻。** 關掉專案再開另一個不必重啟看門人，但 `list` 顯示的還是舊名字。
  現在每次心跳順手重讀 `projects.primary`，`instance_id` 保留出生時的名字（它是目錄名）。
- **`sync_dir` 從頭到尾是 null。** 新增 `cds/ide/project.py`，直接讀 `cds-sync-folder` 專案屬性，
  相對路徑照 `load_base_dir` 的規則對專案檔解析。不透過 `load_base_dir()` 本身，因為它會停下來問
  電腦名稱不符——那不是計時器 tick 該做的事。`ide` 欄位也改成以執行檔名開頭，
  因為 Delta 1.10 與 Lenze 3.24 的 `sys.version` 都是 IronPython 2.7.7，分不出來。
- **`compare` 的逐物件差異在人類可讀輸出裡被丟掉。** CLI 原本只在失敗時印 `stdout_tail`，
  而 compare 找到差異時是成功。現在 compare 一律印，readMe 的說法才站得住。
- **對話框標題沒有測試綁住。** 新增一個測試去掃四支腳本與共用 `.pyw` 裡所有 `ask_yes_no(` 的字面標題，
  斷言它們跟 `silent.YES_NO` 兩邊完全一致。誰改了標題，測試會紅，而不是等到 export 開始每次都失敗。
- **第一次 `build --app` 可能被無聲忽略。** `Project_Build.py` 只在專案屬性
  `cds-text-sync-multipleApps` 為真時才顯示選擇器，而它是在選完之後才更新那個旗標。
  新增第二個 application 之後的第一次 build 會直接編 active application 並回報成功。
  不動那支舊腳本，改成在看門人這端核對結果訊息裡有沒有出現 `--app` 指定的名字，沒有就判失敗並說明原因。
- **`stop` 的結果只活 250 毫秒。** CLI 現在在等待時順手看登記檔還在不在；不在就代表看門人走了。
  對 `stop` 而言那就是成功，對其他命令而言是「看門人在回答前就停了」的失敗，
  兩種都比枯等 120 秒後印「逾時」好。

### 一條做了但要講清楚界線的

reviewer 提到「`self.busy` 擋不住使用者手動跑腳本」：使用者從 Tools 選單跑 `Project_export.py` 的時候，
如果 IDE 抽送到計時器訊息，tick 就會在旁邊開始跑另一支腳本，兩邊搶 `sys.modules`、`__main__.system`
與 `sys.stdout`。reviewer 自己註明沒有驗證這會不會真的發生。

`cds/ide/silent.py` 加了一個模組層級的旗標 `silent.running()`，`tick()` 看到就直接返回。
**但它擋不住 reviewer 描述的那個情境**，因為使用者手動跑的腳本走的是 IDE 自己的執行器，
根本不經過 `silent.run`，這個模組看不到它。目前沒有已知的辦法從計時器裡偵測到那種腳本。
這個旗標實際擋住的是「另一個呼叫端」——例如第四段要包的 MCP，或別處建出來的第二個 `Watcher`。
程式碼裡的 docstring 已經照這個界線寫，沒有誇大。

### 沒改的

reviewer 的「不改」八條照收。另外更正第 4 節的一句話：那裡寫「三支模組名稱都不跟標準函式庫撞名」，
對 `cds/core/commands.py` 而言是錯的（Python 2 有 `commands` 模組）。實際無害，因為沒有任何地方做
`import commands`，而隱式相對匯入的遮蔽只影響 `cds/core/` 套件內部。

### 檔案大小

`cds/ide/watcher.py` 修完一度到 339 行，把「問這個 IDE 現在開著什麼」抽成 `cds/ide/project.py`
之後回到 292 行，抽出來的那支也因此可以獨立測。`cds/ide/silent.py` 是 319 行，
超過 PRINCIPLES §2 的 300 行軟目標、在 400 行硬上限內，這裡選擇不拆：
剩下的候選接縫（stdout 攔截、對話框作答表）拆出來都只有四五十行，
分開之後兩邊都還是得一起讀才看得懂那件事，不划算。

---

## 16. 真專案跑一輪（2026-09-05，用副本）

依 `PHASE2_PLAN.md` 第 3 段。兩個真專案各複製一份到 `%TEMP%\cds-real\`，
`cds-sync-folder` 指到副本旁邊的 `sync\`，原始檔與使用者 git 管理的
`sunming_sliter_dev\codesys_export\` 一個位元組都沒有被寫過。
使用者自己開著的那個 IDE 全程只被 `list` 讀到，沒有收過任何命令。

啟動器是 `tools/open_copy_and_watch.py`（`--noUI --runscript`，加
`CDS_OPEN_KEEPALIVE=1` 讓無頭行程不要在腳本返回後就退出）。

### 16.1 數據

兩個副本的物件數一樣（229），因為 softplc 是 Shm 專案的重構分支。

| 步驟 | softplc 副本（CODESYS 3.5.21.40） | delta 副本（DIADesigner-AX 1.10） |
|---|---|---|
| `export`（全新） | 229 個物件，IDE 內 59.66 秒 | 229 個物件，IDE 內 56.60 秒 |
| 磁碟上的 `.st` | 228 個 | 228 個 |
| `compare`（改了一個 POU 之後） | 正確回報 M:1 =:228，50.58 秒 | 正確回報 M:1 =:228，47.12 秒 |
| `import` 不帶 `--yes` | `needs_input`、exit 1、IDE 沒變 | 同左（softplc 上驗過即可） |
| `import --yes` | 更新 1、相同 228，58.92 秒 | 更新 1、相同 228，約 65 秒 |
| `build`（正常） | 0 errors、101 warnings、23.33 秒 | 0 errors、101 warnings、32.45 秒 |
| `build`（故意放語法錯） | 1 error、90 warnings、9.62 秒、exit 1 | 未做（softplc 上驗過） |
| 修好之後 `build` | 0 errors、101 warnings、10.12 秒 | — |
| 兩邊同時 `export` | 兩邊都成功，`list` 兩邊同時 `busy`，總共 62 秒 | |

改的物件是 `Application/Function Blocks/FB_LowPass.st`，加一個 `DINT` 區域變數
與一行 `_diCallCount := _diCallCount + 1;`。語法錯是把那行的 `1` 拿掉。

`stop` 之後兩個實例的登記檔與目錄都消失，IDE 程序自己退出，`list` 只剩使用者那一個。

### 16.2 跳出來的對話框，以及怎麼接住的

**`UpgradeProjectConfirmation`（Delta 1.10）。** delta 副本是 DIADesigner-AX 1.8 建的，
1.10 開它會問「要不要升級儲存格式」。無頭模式的預設答案是「不要」，而「不要」的意思是
**不開了**，`projects.open()` 直接丟 `Do not upgrade the older version project`。

一開始以為這是 `projects.open()` 的 `update_flags` 參數管的，試了 `SilentMode|UpdateAll`、
`UpdateAll`、`NoUpdates` 全都一樣被擋。它不是更新旗標，是一個提示。
把 `system.prompt_handling` 設成 `LogMessageKeys | LogSimplePrompts | ProcessScriptPrompts`
之後，訊息鍵就印在 stderr 上了，然後
`system.prompt_answers["UpgradeProjectConfirmation"] = PromptResult.Yes` 就過了。
這套作法寫在 `tools/watch_harness.py` 的 `answer_prompts()`，`LogMessageKeys` 保持開著，
所以下一個沒被預先回答的提示會自己把鍵名印出來，不必再猜一次。

**升級之後 `save()` 丟 `NullReferenceException`（Delta 1.10）。** 存檔失敗，
換成 `projects.primary` 重新拿 handle 也一樣。`cds-sync-folder` 屬性在記憶體裡已經設好，
看門人讀的就是記憶體裡那份，所以存檔失敗不影響這一輪。啟動器改成存檔失敗只印一行繼續
（`watch_harness.try_save()`）。**這件事沒有查到根因**，只知道是 Delta 1.10 無頭、
專案剛升級過這個組合。CODESYS 3.5.21.40 沒有這個問題，而且 Delta 上的
`export`、`import`、`build` 後續全部正常——那些腳本內部也會呼叫 `save()`，卻沒有出事，
所以問題應該只出在升級後的第一次存檔。

`--yes`、`--force`、`--app`、`--delete-orphans` 這一輪都沒有被觸發到需要 `--force` 的情況：
兩個副本的同步資料夾都是這一輪自己匯出的，版本與電腦名稱都相符。

### 16.3 這一輪改掉的工具問題

**`build` 只回錯誤數，不回錯誤在哪。** `Project_Build.py` 把逐條錯誤整理成一張表，
但只有在專案開了 `cds-sync-debug` 屬性時才寫進 `build_<App>.log`，平常只印
「1 errors, 90 warnings」。對看不到 IDE 的呼叫端來說，知道有錯卻不知道錯在哪，
等於沒辦法修——而 `docs/AI_WORKFLOW.md` 已經告訴 agent「錯誤的詳細內容在 `stdout_tail` 裡」。

新增 `cds/ide/messages.py`：編譯完直接去 IDE 自己的訊息庫讀
（`system.get_message_objects(BUILD_CATEGORY, Severity.Error|Warning|FatalError)`），
格式化成 `severity  text  (物件, 位置)` 接在 `stdout_tail` 後面，錯誤排在警告前面，
上限 200 行。不動 `Project_Build.py`。實測輸出：

```
error    Expression expected instead of ';'  (FB_LowPass, at 5)
warning  The code 'GVL_AO.iAO[1];' has no effect. Is this the intent?  (AIO_2, at 4819)
```

`IScriptMessage` 的成員名稱在不同 ScriptEngine 版本可能不一樣，所以格式化整段寫得保守：
拿不到就退回 `str()`，整組拿不到就回空清單，絕不因為「錯誤格式化失敗」而讓一次編譯報不出來。

### 16.4 不屬於工具範圍、只記錄的

softplc 與 delta 兩個副本正常編譯都是 **101 個警告**，其中大量是
`The code 'GVL_AO.iAO[n];' has no effect. Is this the intent?`（`AIO_2` 裡）。
這是專案本身的程式碼，不是同步工具造成的，這次沒有動它。
