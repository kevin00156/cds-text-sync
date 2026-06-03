# Rework Plan — 文字優先 × 批次速度

> 本分支從 `65bd26f`（最後的純文字架構，~v1.7.3）開出。目標是保留文字版的
> 「靈魂」，治好它唯一的病（慢），同時丟掉 2.x 疊上去的複雜度。
> 實作規範見 [`PRINCIPLES.md`](../PRINCIPLES.md)。

---

## 1. 診斷（為什麼這樣做）

| | 文字版 1.7.3 | XML 版 2.x |
|---|---|---|
| 事實來源 | **磁碟上的 `.st` 文字**（✓ 對） | `IDE.xml` 快照（✗ 害死可用性） |
| AI 憑空建檔 | ✓ 可以（檔案自包含） | ✗ 多半被靜默跳過 |
| 穩定性 | ✓ 高 | 中（import 受快照基準限制） |
| 速度 | ✗ 慢（逐物件跟 IDE 來回上千次） | ✓ 快（一次 `export_native`） |
| 複雜度 | 中（但有 1000+ 行巨檔） | 高（subprocess + named pipe + 雙運行時 + 遷移殘留） |

**結論**：文字版的方向對，只差速度。XML 版的速度引擎對，但其餘都是包袱。
把兩者各取一半：

> **磁碟文字當事實來源（文字版的靈魂）＋ 把 `export_native`/`import_native`
> 當「快速搬運管道」而非事實來源（XML 版的速度）。中間全是純 Python，免費。**

---

## 2. 核心架構決策

1. **單一進程，不要 subprocess、不要 named pipe。**
   2.x 為了在 CPython 3 跑重邏輯，搞了外部引擎 + 具名管道 + 雙運行時同步，這是
   它一半的複雜度來源。但 `xml.etree` / `hashlib` / `codecs` 在 IronPython 2.7
   都有 —— 1.7.3 全程在 IDE 內跑就證明可行。所以**所有東西都在 IDE 給的那個
   IronPython 進程裡跑**，零 IPC。

2. **兩層，邊界神聖（見 PRINCIPLES §4）。**
   - `cds/ide/` —— 唯一碰 CODESYS API 的薄層。只做兩件事：把整包 dump 出來、把
     一包 patch 灌回去。
   - `cds/core/` —— 純 Python，**不准 import 任何 CODESYS 東西**。吃檔案路徑/資料，
     吐資料。因此能在 CI 用 CPython 3 完整單元測試。

3. **昂貴的邊界只跨一次（見 PRINCIPLES §3）。**
   export = 一次 `project.export_native(全部物件)` → `snapshot.xml`；之後純 Python
   把 XML 拆成 `.st`。import = 純 Python 把 `.st` 組成 `import.xml` → 一次
   `project.import_native()`。慢的根因（逐物件來回）直接消滅。

4. **磁碟文字＝事實來源，快照＝過渡檔（見 PRINCIPLES §5）。**
   `snapshot.xml` 是暫存、可丟、不進 git。git 追蹤的是 `.st`/`.xml` 投影。

5. **CLI 是後話。** 先把 export/import/compare 做穩做快。要遠端驅動 IDE 再說，
   且就算要，也只加一條最小管道，不重建 2.x 那套。

---

## 3. 目標模組佈局

```
cds/
  __init__.py
  types.py            # CODESYS 物件 TYPE_GUIDS 表 + 分類（從舊 codesys_constants 移植）
  ide/                # ← 唯一碰 CODESYS API（IronPython 2.7，不進 CI）
    __init__.py
    snapshot.py       # export_native(全部) -> snapshot.xml          一次讀
    apply.py          # import_native(patch.xml) + 建立新物件         一次寫
    ui.py             # 對話框/通知（薄封裝 system.ui）
  core/               # ← 純 Python，無 CODESYS 依賴，CI 全測
    __init__.py
    model.py          # ProjectObject + 解析 snapshot.xml <-> 物件清單
    textfile.py       # 物件 <-> 磁碟 .st/.xml（canonical 格式讀寫）
    diff.py           # 磁碟 vs 快照 -> Changes（modified/added/removed）
    patch.py          # Changes -> import.xml（含「新建」節點）
    cache.py          # hash 快取，跳過未變更（移植 + 簡化舊 Merkle 機制）
  app/                # ← 編排：把 ide + core 串起來（薄）
    __init__.py
    export.py         # snapshot -> core -> 寫 .st
    import_.py        # 讀 .st -> core -> apply
    compare.py        # 同 export 前半，輸出報告不動 IDE

Project_export.py / Project_import.py / Project_compare.py / ...
                      # IDE 選單入口，每個 ~10 行，只呼叫 cds.app.*
```

每個檔案都應遠低於 PRINCIPLES §2 的 400 行硬上限。舊的 `codesys_*.pyw` 在遷移完成
前留著當參考，最後一階段刪除。

---

## 4. 資料流

**Export**
```
Project_export.py
  └─ cds.app.export.run(base_dir)
       ├─ ide.snapshot.dump(project)        -> snapshot.xml      [一次 IDE 呼叫]
       ├─ core.model.parse(snapshot.xml)    -> [ProjectObject]
       ├─ core.cache.skip_unchanged(...)    -> 只留有變動的
       └─ core.textfile.write_tree(objs, base_dir)  -> .st/.xml
```

**Import**（磁碟贏）
```
Project_import.py
  └─ cds.app.import_.run(base_dir)
       ├─ ide.snapshot.dump(project)        -> snapshot.xml      [一次 IDE 呼叫]
       ├─ core.textfile.read_tree(base_dir) -> [ProjectObject]（含磁碟新增）
       ├─ core.diff.compute(disk, snapshot) -> Changes
       ├─ core.patch.build(changes)         -> import.xml（含 <Create...> 節點）
       └─ ide.apply.apply(project, import.xml)               [一次 IDE 呼叫]
```

**Compare**：跑到 `core.diff.compute` 為止，輸出報告，完全不碰 IDE 寫入。

---

## 5. 效率策略（對應你的四個目標）

1. **批次化 IDE 呼叫** — 見 §2.3。這是最大宗，單獨就能把秒數從「分鐘級」降到
   「秒級」。`ide/` 全層加起來對 IDE 的呼叫次數應該是 *常數*，與物件數無關。
2. **只處理有變動的物件** — `core.diff` 算出 Changes，import 只組變動物件的 patch；
   export 靠 `core.cache` 跳過 hash 未變的。
3. **快取/狀態重用** — `core.cache` 移植舊的 hash 快取，但簡化：一個 `cache.json`
   存 `{rel_path: content_hash}`，比對相等就跳過。不要 2.x 那種 CACHE_VERSION 遷移
   地獄。
4. **AI 協作順暢度優先（最高優先）** — 見 §6。即使犧牲一點速度也要先保證這個。

---

## 6. AI 協作：把「憑空建檔」做成一等公民

這是你最痛的點，獨立列出來，**第一階段就要驗收**：

- 磁碟上有、快照裡沒有對應物件的 `.st` → `core.diff` 標記為 `added`，
  `core.patch` 產生**建立節點**，`ide.apply` 真的在 IDE 建出來。
- **絕不靜默跳過**（PRINCIPLES §6）：若推斷不出物件種類（POU/method/GVL/DUT…），
  要在畫面與 log 明確報「檔案 X 無法判斷型別，未匯入，原因：…」，並告訴使用者怎麼修
  （例如加一行型別 pragma）。
- 種類推斷規則集中在 `core/textfile.py` 一處，可單元測試、可逐步加強。

---

## 6.5 Metadata 政策（debug 才產生）

舊版每次 export/import 都吐 `sync_metadata.json`（且進 git，時戳每跑必變 →
污染每個 PR diff），還有一堆 `*.log`。常態根本不需要。新版規則（見
`cds/settings.py`）：

| 類別 | 檔案 | 行為 |
|---|---|---|
| 永遠寫 | 內容檔 `.st`/`.xml`、`.gitattributes` | 正常產生、進 git |
| 本機快取 | `sync_cache.json` | 正常產生但 **gitignore**，不進版控 |
| **debug 才寫** | `sync_metadata.json`、`*.log` | `cds-sync-debug` 開才產生；平常摘要只進 console/popup |
| 丟棄 | `_metadata.json`/`_config.json`/`BASE_DIR` 等舊殘留 | 不再產生 |

開關：CODESYS 專案屬性 `cds-sync-debug`（存在 .project 內，不污染 git）。
`Settings.wants_metadata()` 是唯一的判斷點，app 層據此決定寫不寫。

## 7. 分階段 TODO

> 每階段獨立可跑、可測、可 commit。不要一次大爆炸。

- [ ] **階段 0 — 地基**
  - [ ] 建立 `cds/` 套件骨架（本分支已附 stub）
  - [ ] `core/types.py`：從 `codesys_constants.pyw` 移植 `TYPE_GUIDS` / `EXPORTABLE_TYPES`
  - [ ] CI：跑 `tests/` 下 `core/` 單元測試（CPython 3.12）
- [ ] **階段 1 — Export（批次讀）**
  - [ ] `ide/snapshot.py`：`export_native(全部)` → `snapshot.xml`
  - [ ] `core/model.py`：解析 snapshot.xml → ProjectObject
  - [ ] `core/textfile.py`：write_tree → `.st`/`.xml`（含種類→副檔名規則）
  - [ ] `app/export.py` 串起來；`Project_export.py` 改成薄入口
  - [ ] fixtures：一個 snapshot.xml → 預期檔案樹，做 smoke test
- [ ] **階段 2 — Compare + Import（批次寫 + 磁碟贏）**
  - [ ] `core/diff.py`：disk vs snapshot → Changes
  - [ ] `core/patch.py`：Changes → import.xml（**含建立節點**）
  - [ ] `ide/apply.py`：`import_native(import.xml)`
  - [ ] `app/compare.py` / `app/import_.py`；對應薄入口
  - [ ] **驗收 §6：AI 憑空新建一個 .st，import 後 IDE 真的出現該物件**
- [ ] **階段 3 — 快取 + 收尾**
  - [ ] `core/cache.py`：hash 跳過未變更
  - [ ] 備份/版本相容/孤兒清理等收尾功能移植（從舊 `codesys_utils.pyw` 挑必要的）
  - [ ] **刪除所有舊 `codesys_*.pyw` 與不再用的舊入口**（PRINCIPLES §7）
- [ ] **階段 4 —（可選）CLI**
  - [ ] 只有在真的需要從命令列驅動 IDE 時才做，且用最小管道。

---

## 8. 測試策略

- `core/` 全部純函式 → `tests/` 下用 pytest，CPython 3.12 在 CI 跑。
- `ide/` 需要真 IDE → 手動驗 + fixture smoke test（給定 snapshot.xml，比對輸出檔案
  樹）。fixture 放 `fixtures/`。
- 每階段結束前，CI 綠燈才算完成。

---

## 9. 不要做的事（避免重蹈 2.x）

- ✗ 不要 subprocess / named pipe / HTTP daemon（除非階段 4 證明非要不可）。
- ✗ 不要讓 XML 變成事實來源。
- ✗ 不要 1000+ 行的檔案、200 行的函式、20 個分支的 if/elif。
- ✗ 不要保留「新舊兩條路徑並存」。換掉就刪掉。
- ✗ 不要靜默跳過任何物件。
