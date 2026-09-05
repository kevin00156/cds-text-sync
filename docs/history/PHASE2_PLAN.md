# 第二階段計畫：審查合併、給 AI 用、真專案跑一輪

> 建立日期：2026-09-05。前一階段的工單是 [`WATCHER_CLI_PLAN.md`](WATCHER_CLI_PLAN.md)，
> 看門人與 CLI 已在 `feat/ide-watcher-cli` 分支做完並經真實點擊驗收。
> 這份計畫由監督的 session 寫，交給執行的 agent 一路做到底。使用者這段時間不會操作桌面，
> 也不會回答問題；卡住就把卡住的原因寫進最後一則回報，不要等。

---

## 0. 鐵律（每一段都適用）

1. **不碰使用者開著的兩個 IDE 實例。** CODESYS 3.5.21.40（pid 17340，開著 `softplc_refactor.project`）與
   DIADesigner-AX 1.10（pid 14012，開著 `Shm_2026.07.29`，有未儲存的修改）都是使用者的，
   不對它們下命令、不關它們、不在裡面跑腳本。自己啟動的 IDE 實例要記住 pid，只關自己開的。
2. **不碰使用者的原始專案檔與同步資料夾。** 真專案一律用副本：
   `D:\耀捷\三明\三明分紙機\PLC\Shm_2026.07.29.project` 與
   `D:\耀捷\三明\三明分紙機\PLC\.softplc\softplc_refactor.project` 只准複製出去，
   副本放在 `%TEMP%\cds-real\` 底下，副本的 `cds-sync-folder` 屬性改指到副本旁邊的 `sync\`。
   `C:\Users\qazsskevin\Documents\repo\sunming_sliter_dev\codesys_export\` 是使用者 git 管理的同步資料夾，
   一個位元組都不准寫。
3. **不輸入、不儲存、不索取任何密碼。** 對 WSL 裡的 soft PLC 上線（login）會跳帳號密碼，
   這一步不做；設計上留給使用者自己填在本機檔案裡（見第 5 段）。凡是遇到要求憑證的對話框，
   那一步就中止並記錄，繼續其他工作。
4. **不動桌面上無關的視窗。** 真實點擊儀器拿不到前景時（前一天遇過 AORUS Control Center 蓋在最上層），
   改用 CLI 驗證並在回報裡註明，不要去關或移動別人的視窗。
5. **不用 `os.kill`。** 要關自己開的 IDE 用 `Stop-Process -Id <自己記下的 pid>`。
6. **守 [`PRINCIPLES.md`](../PRINCIPLES.md)。** 檔案 400 行硬上限、函式 60 行、兩層邊界、
   IronPython 2.7 相容。commit 訊息一句祈使句說明為什麼，跟 `main` 一致。
7. **合併與 push 已獲使用者同意**（本計畫第 1 段）。其他 repo 不 push、不 commit。
8. 臨時檔全部放 `%TEMP%\cds-*`，做完清掉。

---

## 1. 審查、修正、合併

### 1.1 審查（獨立的 reviewer agent 做）

對象：`feat/ide-watcher-cli` 相對於 `main` 的全部差異（`git diff main...HEAD`），
主要是 `cds/core/ipc.py`、`instances.py`、`commands.py`、`cds/ide/watcher.py`、`session.py`、`silent.py`、
`Project_watch.py`、`cli/cds_ide.py`、`tools/probe_watcher_ui.py` 與對應測試，約 1,100 行。

重點：

- silent 模式對四支舊腳本的攔截有沒有漏：`__main__.system` 換掉後有沒有還原、`NeedsInput` 繼承 `BaseException`
  會不會被別處的 `except BaseException` 吃掉、`exec` 餵位元組時 BOM 與編碼、成敗判斷「warning 就算失敗」的邊界。
- 登記檔與心跳的並發：Windows 檔案共用衝突的重試路徑、`prune_stale` 會不會誤刪忙碌中的實例、
  兩個 IDE 同時 `stop` 的收尾。
- 計時器 tick：重入保護、tick 內例外是否真的接住所有 `BaseException`（`SystemExit` 除外）、
  `stop` 後計時器與 `sys._cds_watcher` 是否清乾淨、再跑一次 `Project_watch.py` 的切換邏輯。
- CLI：`--target` 解析的五種情況、逾時後撤命令檔、exit code 與文件一致、`--json` 輸出可被機器解析
  （目前 `list --json` 的 JSON 是否含非 ASCII 路徑的轉義問題）。
- 測試有沒有真的蓋到上面這些，還是只蓋 happy path。
- 是否有超過 400 行的檔案、超過 60 行的函式、在 `cds/core/` 裡 import CODESYS 的東西。

產出：`%TEMP%\cds-review\findings.md`，每條寫「檔案與行號、問題、怎麼壞、建議」，
並分成「必修」「建議」「不改」三級。不要修程式碼。

### 1.2 修正與合併（實作 agent 做）

- 讀 findings，「必修」全修，「建議」自行判斷並在工單第 15 節說明取捨。修完 `python -m pytest tests` 全綠。
- 合併：`git push origin feat/ide-watcher-cli`；`gh pr create --base main --title ... --body ...`
  （`gh` 已登入 kevin00156）；PR 內文用一段話講清楚這個分支做了什麼、為什麼是計時器設計、
  真實點擊驗收的結果；`gh pr merge --merge --delete-branch=false`。
- 合併後 `git fetch origin` 並 `git branch -f main origin/main`（`main` 沒有被任何 checkout 佔用，所以可以）。
  之後的工作在新分支 `feat/ai-workflow` 上做，一樣從 `main` 開，繼續用這個 worktree。
- 不要動隔壁 `..\kevin-cds-text-sync` 那個 checkout，它停在 `fix/member-creation-parent-resolution` 且有未提交修改。

驗收：PR 已合併、`origin/main` 包含看門人與 CLI、測試全綠。

---

## 2. 讓 AI 用得上：使用說明與 skill

目標是「一個會跑 shell 的 agent 讀完就能自己完成：改 .st、同步進 IDE、編譯、看錯誤、修」。

### 2.1 產出

1. `docs/AI_WORKFLOW.md`（本 repo）：給 agent 讀的工作迴圈說明，白話，含：
   - 前提：IDE 開著專案、看門人已啟動（怎麼啟動、怎麼確認 `list` 看得到）。
   - 迴圈：編輯同步資料夾裡的 `.st` → `cds_ide.py compare` 看差異 → `cds_ide.py import --yes` →
     `cds_ide.py build [--app NAME]` → 讀結果裡的錯誤 → 修 → 再來。
   - 每個命令的 exit code 與 `--json` 結果怎麼讀；`needs_input` 出現時要補哪個旗標。
   - 什麼時候 IDE 會忙（命令執行中），為什麼那是正常的。
   - `.st` 檔的格式規則（宣告區與實作區的分隔標記、kind pragma），指到 readMe 對應段落，不要重抄。
   - 多個 IDE 時 `--target` 怎麼選。
   - 禁止事項：不要自己去改 `.project`、不要在 IDE 登入 PLC 時匯入（工具會拒絕）。
2. Claude Code skill：`skills/cds-ide/SKILL.md`（本 repo 為來源），內容是 2.1.1 的精簡版加觸發條件
   （使用者提到 CODESYS、DIADesigner、.st、PLC 程式、匯入 IDE、編譯 PLC 時觸發）。
   然後安裝到使用者層級 `%USERPROFILE%\.claude\skills\cds-ide\`（複製，不要 junction，
   因為 worktree 之後可能會被拿掉），這樣任何專案的 Claude Code 都看得到。
3. readMe 的「Driving the IDE from a terminal」一節加一句指到 `docs/AI_WORKFLOW.md`。

不要改 `sunming_sliter_dev` 那個 repo。它的 `docs/DEVELOPMENT.md` 第 9 節該怎麼補一段，寫成建議放在最後回報裡。

驗收：另開一個全新的 Claude Code session（`claude -p` 非互動即可）在任一目錄下問
「我改了一個 .st，怎麼同步進 CODESYS 並編譯」，它的回答要用到 skill 裡的命令與旗標。

---

## 3. 真專案跑一輪（用副本）

### 3.1 準備

- 建 `%TEMP%\cds-real\delta\` 與 `%TEMP%\cds-real\softplc\`，把兩個原始 `.project` 各複製一份進去
  （檔名保留），每個旁邊建 `sync\`。
- 寫一支 `tools/open_copy_and_watch.py`（給 `--runscript` 用）：開指定的副本、把 `cds-sync-folder`
  改指到旁邊的 `sync\`、走 `Project_watch.py` 一樣的啟動路徑、返回。路徑用環境變數傳。
  這支跟 `tools/probe_watcher_ui.py` 的差別只有「開既有專案」而不是「建空專案」，
  能共用的就共用，不要複製貼上。
- 啟動兩個 IDE：Delta 1.10 開 Delta 副本，CODESYS 3.5.21.40 開 softplc 副本
  （設定檔名分別是 `DIADesigner-AX 1.10` 與 `CODESYS V3.5 SP21 Patch 4`；`--culture=en`）。
  兩個看門人都要在 `cds_ide.py list` 裡看到，實例名會是副本的專案主檔名。
- 開專案時可能跳的對話框（版本不符、電腦名稱、程式庫缺失、「是否更新設定檔」），
  用 `system.prompt_answers` 或啟動器裡的處理接住，每一個都記到工單第 15 節。
  遇到要求密碼的一律中止那一步。

### 3.2 迴圈

對兩個副本各做一次，命令都帶 `--target`：

1. `export`：全部物件出來，記物件數與秒數。
2. 挑一個簡單的 POU（例如一個純邏輯的 FB），在 `.st` 裡加一個區域變數與一行無副作用的賦值。
3. `compare`：要正確回報只有那一個物件有差異。
4. `import --yes`：物件真的更新（再 `export` 一次比對內容，或用 `status`）。
   遇到版本不符或電腦名稱的確認，記下來，再用 `--force` 過。
5. `build`：這兩個專案有 application，這是工單裡「build 回錯誤數」那項唯一能驗的地方。
   多個 application 時用 `--app`，記下實際的 application 名稱。
6. 故意在那個 POU 放一個語法錯誤，`import --yes` 再 `build`：錯誤數要大於 0，結果裡要有錯誤訊息與位置。
7. 修掉，`import --yes`，`build`：錯誤數回到 0。
8. 兩個 IDE 同時各跑一次 `export`，互不干擾。
9. `stop` 兩邊，`list` 為空，關掉自己開的兩個 IDE。

### 3.3 記錄

每一步的秒數、結果、跳出來的對話框與怎麼回答，寫進 `WATCHER_CLI_PLAN.md` 新增的第 15 節。
工具本身的 bug 在這一段修掉並 commit；不屬於工具範圍的（例如專案本身的編譯警告）只記錄。

驗收：兩個副本都完整跑完 1 到 9；工單第 9 節裡「build 回錯誤數」與「命令執行中 IDE 忙」兩項打勾。

---

## 4. 選配：MCP 包裝

只有前三段都完成、而且時間還有才做。目的是給不能跑 shell 的客戶端（例如 Antigravity）用。

- `mcp/cds_ide_mcp.py`：stdio 的 MCP 伺服器，工具就是 CLI 的八個命令，每個工具內部呼叫
  `cli/cds_ide.py` 的函式（不要 shell 出去），回傳結果檔的 JSON。
- 依賴 `mcp` 套件只在 `mcp/requirements.txt`，`cds/` 與 `cli/` 不能因此多任何依賴。
- 驗收：用 `claude mcp add` 註冊後，在一個 `claude -p` 的非互動 session 裡呼叫 `list` 與 `ping`。

---

## 5. 不做但要寫清楚的：上線到 WSL soft PLC

使用者提到對 WSL 裡的 soft PLC 上線會要帳號密碼。這次不實作、不測試，原因是密碼不能經過 agent。
在最後回報裡給一段設計建議：

- 新命令 `login`、`download`、`logout`，憑證只從 `%LOCALAPPDATA%\cds-text-sync\credentials.json`
  讀（使用者自己建，永不進 git，權限只給本人），沒有這個檔就回 `needs_input` 指出檔案路徑與格式。
- 在 IDE 裡怎麼把憑證餵給登入：查 `online` 模組與 `system.prompt_answers` 能不能接住裝置使用者管理的提示，
  這是實作前要先驗的事，寫成待驗清單即可。

---

## 6. 回報格式

全部做完（或卡住）時，最後一則訊息要有：

1. 每一段的狀態：完成、部分完成、跳過，各一句話。
2. commit 與 PR 連結清單。
3. 真專案迴圈的數據表（物件數、export 秒數、build 秒數與錯誤數、跳出來的對話框）。
4. 需要使用者親自做的事，列成清單，每項一句話說明為什麼只有人能做。
5. 給 `sunming_sliter_dev` 的文件建議（一段文字，不要去改那個 repo）。
6. 第 5 段的上線設計建議與待驗清單。
