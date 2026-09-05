# 第三階段計畫：看門人的狀態視窗、清掉被繞過的骨架

> 建立日期：2026-09-05。接在 [`PHASE2_PLAN.md`](PHASE2_PLAN.md) 之後，鐵律沿用它的第 0 段。
> 使用者不在桌面前，卡住就寫進最後一則回報。分支繼續用 `feat/ai-workflow`。

---

## 1. 看門人要有一個非常明顯的「我在跑」提示

### 1.1 為什麼

現在啟動 `Project_watch.py` 之後腳本立刻返回，IDE 看起來跟沒啟動一模一樣。使用者唯一能確認的方法是
去終端機跑 `list`。他要的是一眼就看得到：看門人活著、現在閒著還是在做哪個命令、上一個命令的結果。

### 1.2 做法：一個掛在 IDE 主視窗上的小狀態視窗

- 新檔 `cds/ide/statusform.py`，只有 WinForms，沒有邏輯。`session.main()` 掛好計時器之後在 UI 執行緒上建它，
  用 `Show()`，**絕對不能 `ShowDialog()`**（那會把腳本卡住，前一階段的整個教訓就是這個）。
- `Owner` 設成 IDE 主視窗（`Application.OpenForms[0]`），這樣它只浮在 IDE 上面、跟著 IDE 最小化，
  不會壓到別的程式。不要用 `TopMost`。
- 位置：IDE 主視窗右下角內側，記在 `%LOCALAPPDATA%\cds-text-sync\statusform.json`，使用者拖過就記住。
- 大小約 320 x 110。內容三行加一個按鈕：
  1. 第一行大字：`LISTENING` 或 `BUSY: export`，背景色閒著是綠、忙碌是橘、上一個命令失敗是紅（直到下一個命令成功）。
  2. 第二行：專案名稱與實例編號，例如 `Shm_2026.07.29  ·  Shm_2026.07.29-14012`。
  3. 第三行：`done 12 · last export ok 7.5s · up 00:41:12`，最後一次心跳的時間也放這行尾端，讓人看得出它還在動。
  4. `Stop` 按鈕，行為跟 CLI `stop` 一模一樣。使用者按視窗右上角的關閉也等於 stop。
- 更新時機：每次 tick 結束後更新（tick 本來就 250 毫秒一次，成本可忽略）；命令開始前先改成 BUSY 再執行，
  因為執行期間 IDE 會忙、畫面不會再重繪，所以 BUSY 必須在忙之前就畫上去。
- `system.ui_present` 為 False（無頭）時完全不建視窗，現有的無頭驗收與測試都不能受影響。
- 同時在 IDE 的訊息視窗留痕：啟動、停止、每個命令的開始與結束各一行 `system.write_message`，
  類別用 ScriptMessage，這樣人在 IDE 的 Messages 面板也看得到歷史。

### 1.3 不要做的

- 不要改 IDE 標題列、不要動狀態列，那些是 IDE 的。
- 不要開執行緒做動畫。`codesys_ui.pyw` 的 `show_toast` 在背景執行緒開視窗，那是舊做法，不要模仿。
- 不要把邏輯放進 statusform：它只接收「現在該顯示什麼」，判斷都在 `watcher.py`，這樣 CPython 下的測試才蓋得到。

### 1.4 驗收

- 無頭：`python -m pytest tests` 全綠；`--noUI` 下 `tools/probe_watcher_ui.py` 照舊能跑完 ping、export、stop。
- 有 UI（用 `--runscript` 開 CODESYS 3.5.21.40 跑 `tools/probe_watcher_ui.py`，`CDS_PROBE_POUS=80`）：
  視窗在腳本返回後 1 秒內出現並顯示 LISTENING；從終端機跑 `export` 時視窗變 BUSY: export，
  結束後回 LISTENING 且第三行有 `last export ok`；`stop` 後視窗消失；再啟動一次、直接關視窗，`list` 要變空。
  這一輪用前一階段留下的真實點擊儀器（`tools/` 裡那支）順便確認視窗存在時 File 選單照樣點得開。
- Delta 1.10 至少跑一次無頭以外的啟動，確認視窗出得來、位置在 IDE 右下角。

---

## 2. 清掉被看門人繞過的骨架

### 2.1 事實

`cds/app/export.py`、`import_.py`、`compare.py`，`cds/core/cache.py`、`diff.py`、`model.py`、`patch.py`、`textfile.py`，
`cds/ide/apply.py`、`snapshot.py`、`ui.py` 是 REWORK_PLAN 階段 0 留下的骨架，合計 14 個 `NotImplementedError`，
repo 裡除了它們彼此之外沒有任何東西 import 它們；`cds/settings.py` 只有這些骨架和 `tests/test_settings.py` 在用。
看門人走的是根目錄四支活著的 `Project_*.py`，這批骨架已經沒有路會經過。PRINCIPLES §7 說不留死碼。

### 2.2 做法

- 刪掉上面列的 11 個檔案與 `tests/test_settings.py`。`cds/app/` 整個目錄拿掉。`cds/core/__init__.py` 與
  `cds/ide/__init__.py` 的 docstring 改成描述現在真的住在裡面的東西（協定、看門人、silent、訊息、專案屬性）。
- `docs/REWORK_PLAN.md` 開頭加一段註記：階段 0 的骨架已於 2026-09-05 移除，原因是看門人與 CLI 直接建在
  活著的腳本上，「速度」這個動機由現有的快取處理，之後若要重啟這條線就從這份文件重新開始。不要刪這份文件。
- `readMe.md` 若有提到 `cds/app` 或骨架，改掉。
- 不要碰 `codesys_*.pyw` 與 `Project_*.py`，它們都活著，被選單和看門人兩邊用。
  `codesys_ui.pyw` 的 `show_toast`、比對視窗、設定視窗是給人從選單操作用的，也留著。

### 2.3 驗收

`python -m pytest tests` 全綠，數量只少 `test_settings.py` 那幾個；`grep -r NotImplementedError cds` 為零；
`tools/probe_watcher_ui.py` 無頭跑一輪照舊。

---

## 3. 回報

最後一則訊息：兩段各自的 commit、UI 驗收看到了什麼（視窗長什麼樣用文字描述即可）、
刪了哪些檔、測試數量前後。分支不用 push，使用者會自己處理。
