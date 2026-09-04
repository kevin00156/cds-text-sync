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
| 等待方式 | `system.delay(50)` | 官方文件寫「等待期間會服務訊息迴圈」；本機在 CODESYS 3.5.21.40 與 Delta DIADesigner-AX 1.10 實測 IDE 全程可操作；`time.sleep()` 在 Delta 上會凍結 45 秒 |
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
10. `--runscript` 啟動時沒有看到獨立的進度視窗。從 Tools 選單啟動時有沒有，還沒量。

---

## 4. 架構

三個部分，每個檔案不超過 300 行（硬上限 400，見 PRINCIPLES §2）。

```
cds/core/ipc.py        目錄配置、實例編號、原子 JSON 讀寫。協定的地基。
cds/core/instances.py  實例登記檔、心跳、判活、清理陳舊登記、目標解析。
cds/core/commands.py   命令檔與結果檔的投遞與回收。
                       這三支都是純 Python，IronPython 2.7 與 CPython 3 都要能跑，
                       pytest 全覆蓋。
cds/ide/watcher.py     看門人：主迴圈、silent UI 代理、呼叫四支腳本的入口函式。
                       唯一碰 system/projects 的新程式碼。
Project_watch.py       薄入口，跟其他 Project_*.py 一樣出現在 Tools > Scripting > Scripts。
cli/cds_ide.py         CPython 3 的 CLI，只依賴 cds/core 的那三支。
tests/test_ipc.py      三支協定模組各自一個測試檔。
tests/test_instances.py
tests/test_commands.py
```

協定原本規劃成單一檔案 `cds/core/ipc.py`，寫出來 402 行，超過 PRINCIPLES §2 的硬上限。
拆成三支不是為了壓行數：目錄與檔案讀寫、誰還活著、命令怎麼交接，本來就是三件用「和」
才描述得完的事，PRINCIPLES §1 要求拆開。三支模組名稱都不跟標準函式庫撞名，
因為 IronPython 2.7 在沒有 `absolute_import` 時會先在套件內找同名模組。

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
- 「清掉陳舊登記檔」的條件比原本嚴一點：心跳超過 60 秒**而且**判活函式也認為它死了才清。
  正在跑三分鐘匯入的看門人本來就發不出心跳，只看 60 秒會把活著實例的整個目錄刪掉。
  判活對 `busy` 狀態是看 `busy_since` 有沒有超過命令逾時，所以忙碌中的實例不會被誤刪。
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

主迴圈：

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
- `system.abortable = True`。使用者按進度顯示上的 Cancel 會丟 `KeyboardInterrupt`，要接住並走正常結束（刪登記檔）。
- 每個命令的執行都包在 `try/except Exception`，錯誤寫進結果檔，迴圈繼續。看門人本身只有在 `stop` 或 Cancel 時才結束。
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
  - [ ] 驗收（還需要人）：`build` 回錯誤數。臨時專案是 `projects.create()` 建的空專案，沒有裝置也沒有 application，
        `active_application` 直接丟 `ValueError`。看門人有正確接住並回報 traceback，但「回錯誤數」這條要有 application 的真專案才驗得到。
  - [ ] 驗收（還需要人）：命令執行中 IDE 忙、結束後恢復。無頭實例沒有 UI，看不到。
- [x] **階段 3：收尾**
  - [x] CLI 逾時（exit code 3、順手把沒跑到的命令檔撤掉）、中途 Ctrl+C 不留殘檔、看門人重啟後清掉陳舊登記。
  - [x] 看門人每答完一個命令順手清一次結果目錄，不只在啟動時清。逾時的呼叫端會留下沒人收的結果檔，
        一支連跑好幾天的看門人不能一直累積。
  - [x] **修掉一個並發實測才抓到的當機**，見下面第 12 節。
  - [x] readMe 加了「Driving the IDE from a terminal」一節，寫清楚等待不卡、執行會忙，以及四個旗標各自回答哪個問題。
  - [x] 驗收（2026-09-04 無頭自動跑完）：CODESYS 3.5.21.40 開 `cds-alpha`、Delta 1.10 開 `cds-beta`，
        兩個各 60 個 POU，同時各跑一次 `export`，兩邊都成功、各自寫進自己的同步資料夾、各 60 個 `.st`，
        期間另一個行程連續跑了 401 次 `list` 去撞登記檔，兩支看門人都活著。

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
