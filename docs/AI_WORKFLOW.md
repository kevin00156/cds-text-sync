# 給 agent 的工作迴圈：改 `.st`、同步進 IDE、編譯、看錯誤、修

這份是寫給「會跑 shell 但看不到 IDE 畫面」的人或 agent 看的。目標是讓你自己完成一輪
「改程式、進 IDE、編譯、讀錯誤、再修」，不必請人去點選單。

CODESYS 的專案檔是二進位的，你改不了。你能改的是同步資料夾裡的 `.st` 文字檔，
再叫 IDE 把它們讀進去。IDE 必須是開著的——這套工具是「代替人按按鈕」，不是無頭編譯器。

---

## 0. 前提：IDE 開著、看門人啟動了

人要先做兩件事，你做不到：打開 CODESYS 或 DIADesigner、開好專案，
然後從 **Tools > Scripting** 跑一次 `Project_watch.py`。那支腳本會立刻結束，
IDE 照常可以用，但它留下了一個監聽器。

你這邊確認它在：

```
python cli/cds_ide.py list
```

看得到一行就對了，長這樣：

```
Shm_2026.07.29-14012    idle    D:\...\Shm_2026.07.29.project
```

**什麼都沒有的話就停下來，請人去啟動 `Project_watch.py`。** 不要自己想辦法啟動它，
從命令列開一個新的 IDE 實例是開不了人家已經開著的那個專案的（專案檔會被鎖住）。

同步資料夾在哪，問 `status`：

```
python cli/cds_ide.py status --json
```

回來的 JSON 裡 `data.sync_dir` 就是那個資料夾的絕對路徑。**這是你唯一該編輯的地方。**
如果它是 `null`，代表那個專案沒設 `cds-sync-folder` 屬性，請人去設，你不要猜。

---

## 1. 迴圈

```
編輯 sync_dir 底下的 .st
        ↓
python cli/cds_ide.py compare          看差異，什麼都不會被改
        ↓
python cli/cds_ide.py import --yes     把磁碟上的改動送進 IDE
        ↓
python cli/cds_ide.py build            編譯，看錯誤數
        ↓
有錯 → 讀錯誤訊息 → 回到第一步
```

每一步都先看 exit code，再看輸出。

### `compare`：先看清楚再動手

```
python cli/cds_ide.py compare
```

它只讀不寫。人類可讀的輸出有兩層：一行摘要（改了幾個、只在 IDE 有幾個、只在磁碟有幾個），
以及腳本印出來的逐物件清單。用 `--json` 的話，摘要在 `messages`，逐物件清單在 `stdout_tail`。

**改完之後先 compare 一次是好習慣**，因為它會告訴你 IDE 那邊是不是也有人動過。
如果同一個物件兩邊都改了，匯入會以磁碟為準覆蓋掉 IDE 那邊。

### `import`：磁碟蓋過 IDE

```
python cli/cds_ide.py import --yes
```

`--yes` 是必要的，那是「我確定要改這個專案」的意思。不帶它的話命令會回 `needs_input`、
exit code 1，**而且 IDE 裡什麼都不會變**——這是設計，不是失敗。

匯入是**磁碟贏**。磁碟上有、IDE 裡沒有的檔案會被建立成新物件；兩邊都有但內容不同的，
以磁碟為準。這也是為什麼不確定的時候要先 `compare`。

### `build`：編譯，拿錯誤數

```
python cli/cds_ide.py build
python cli/cds_ide.py build --app MyApplication     # 專案有多個 application 時
```

結果的 `messages` 裡會有 application 名稱、錯誤數、警告數、耗時。錯誤數大於 0 時
exit code 是 1，錯誤的詳細內容（訊息、物件、行號）在 `stdout_tail` 裡。

專案有多個 application 而你沒給 `--app` 的話，會回 `needs_input` 並列出可選的名字。

### `export`：從 IDE 倒出來

```
python cli/cds_ide.py export
```

方向相反：把 IDE 裡的東西寫成 `.st` 檔。你通常在開工前跑一次，確保磁碟上的檔案是最新的；
或者在匯入之後跑一次，確認 IDE 真的收下了你的改動。

---

## 2. 怎麼讀結果

### exit code

| Code | 意思 | 你該做什麼 |
|---|---|---|
| 0 | 成功 | 往下走 |
| 1 | 命令失敗，或缺一個旗標 | 讀 `error` 與 `needs_input`，補旗標或修錯誤 |
| 2 | 找不到、或找不清是哪個 IDE | 跑 `list` 看有幾個，用 `--target` 指定 |
| 3 | 等結果等到逾時 | 加大 `--timeout`（預設 120 秒），大專案的匯入會超過 |

### `--json` 的結構

```json
{
  "ok": true,
  "command": "build",
  "elapsed_s": 7.4,
  "messages": [{"level": "info", "text": "MyApp\nErrors: 0\nWarnings: 2"}],
  "stdout_tail": "…腳本印出來的最後 200 行…",
  "error": null,
  "needs_input": null,
  "data": null
}
```

- `messages` 是 IDE 本來要彈給人看的對話框內容，`level` 是 `info`、`warning` 或 `error`。
- `stdout_tail` 是細節：compare 的逐物件差異、build 的錯誤清單都在這裡。
- `error` 有值就代表失敗，`ok` 一定是 false。
- `needs_input` 有值代表「有個問題沒人回答」，裡面的 `arg` 直接告訴你該補哪個旗標。
- `data` 只有 `status` 和 `list` 會填。

### `needs_input` 出現時

不要重試同一個命令，也不要猜。照 `arg` 補旗標：

| `arg` | 補上 | 那個問題是 |
|---|---|---|
| `yes` | `--yes` | 「確定要把 N 個改動匯入 IDE 嗎？」 |
| `force` | `--force` | 版本不符，或這個同步資料夾是別台電腦匯出的 |
| `app` | `--app <名稱>` | 專案有多個 application，要編哪一個 |
| `delete_orphans` | `--delete-orphans` | 匯出時，同步資料夾裡有 IDE 已經沒有的檔案，要刪嗎 |

`--force` 要特別小心：版本不符的意思是那份同步資料夾是別的腳本版本產生的，
硬做下去有可能出非預期的結果。不確定就停下來問人，不要自己 `--force`。

---

## 3. 命令執行中 IDE 會忙，那是正常的

看門人等待命令的時候不佔用 IDE，人照樣可以打字。但**命令真正在跑的那幾秒到幾十秒，
IDE 會停止回應**——匯出、匯入、編譯都是這樣。原因是 CODESYS 的物件模型只能在 UI 執行緒上呼叫，
這是平台的性質，工具改不了。

對你的影響有兩個。一是不要在一個命令還沒回來的時候送下一個，等它回來。
二是大專案的匯入或編譯可能超過預設的 120 秒逾時，該加大就加大：

```
python cli/cds_ide.py import --yes --timeout 600
```

---

## 4. 多個 IDE 同時開著

`list` 會列出全部。有超過一個的時候，每個命令都要指定 `--target`，
不指定的話會以 exit code 2 結束並列出候選：

```
python cli/cds_ide.py build --target Shm_2026.07.29
```

`--target` 收兩種值：完整的 instance id（例如 `Shm_2026.07.29-14012`），
或專案主檔名（不分大小寫）。專案名有多個 IDE 開著同名專案時才需要用完整 id。

---

## 5. `.st` 檔的格式

一個檔案就是一個物件，宣告區和實作區用一行標記分開：

```
FUNCTION_BLOCK Counter
VAR
    count : INT;
END_VAR

// === IMPLEMENTATION ===
count := count + 1;
```

檔案開頭可能有 `//% cds-text-sync.<key>=<value>` 的 pragma 行，那些是 kind 與建置屬性，
匯入時會被讀走。**不要自己刪掉或改寫 pragma 行**，除非你確定要改那個屬性。
完整說明在 readMe 的
[Sync Pragmas in `.st` Files](../readMe.md#-sync-pragmas-in-st-files) 與
[Type Profiles](../readMe.md#-type-profilesprofilesdefaultjson) 兩節。

**在磁碟上新建一個 `.st` 檔就等於在 IDE 裡新建一個物件。** 檔案放在哪個資料夾，
物件就會出現在 IDE 裡對應的位置。

---

## 6. 不要做的事

- **不要改 `.project` 檔。** 那是二進位的，你改了會壞掉。
- **不要改同步資料夾以外的東西。** `sync_cache.json` 是機器本地的快取，不要碰也不要提交。
- **PLC 在線上（logged in）時不要匯入。** 工具會自己擋下來並告訴你，別想繞過；
  上線狀態下 IDE 拒絕所有物件的建立、搬移與刪除。
- **不要自己去啟動或關閉 IDE。** 開著的專案是人的工作現場。
- **不要在不確定的時候用 `--force`。** 它是用來壓過安全檢查的，壓過去就沒有第二道防線。

---

## 7. 一輪完整的例子

```bash
# 這個 IDE 開著什麼、同步資料夾在哪
python cli/cds_ide.py status --json

# 先確保磁碟是最新的
python cli/cds_ide.py export

# 改一個 POU（用你平常編輯檔案的方式）
#   <sync_dir>/Application/POUs/Counter.st

# 看看只有它變了
python cli/cds_ide.py compare

# 送進 IDE
python cli/cds_ide.py import --yes

# 編譯
python cli/cds_ide.py build --json

# 錯誤數不是 0 的話，錯誤清單在 stdout_tail，修完回到第三步
```
