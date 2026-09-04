# 研究筆記：不靠 IronPython、用 HTTP 伺服器讓 AI 控制 CODESYS IDE，可行嗎？

> 調查日期：2026-09-04。
> 本文只引用第一手來源（CODESYS 官方線上說明、CODESYS Store、CODESYS Forge 官方人員回覆、GitHub 專案自己的 README 與原始碼、本機安裝檔的實際內容）。
> 每句事實旁邊都附來源連結。凡是我自己的推論，一律標成 **推測**。
> 查不到的事項集中在第 7 節。

---

## 1. 結論摘要

「從零寫一個 HTTP 伺服器來控制 CODESYS IDE」這個方向本身是對的，而且 CODESYS 官方已經自己做了一個：從 2026 年 4 月起，官方推出「CODESYS Development System MCP Server」，讓 AI 助手用 MCP 協定讀寫「目前開啟中的專案」，但它只支援 V3.5 SP22 以上，而且要付費訂閱 Professional Developer Edition（PDE，每年 550 歐元起）（[官方文件](https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/_idemcp_start_page.html)、[Store 頁面](https://store.codesys.com/en/codesys-mcp-server.html)）。

但是「不要依賴 IronPython」這個目標，在你的機器上幾乎做不到。原因是 CODESYS 的物件模型（Automation Platform 的 API）只允許在主執行緒（UI 執行緒）上呼叫，這是平台本身的限制，跟用哪種語言無關；官方人員在 Forge 上講得很清楚：「腳本 API 本質上綁在主執行緒，因為它呼叫的是 Automation Platform 的 API」（[Forge 60039f2d35](https://forge.codesys.com/forge/talk/Engineering/thread/60039f2d35/)）。換句話說，IDE 會卡住不是 IronPython 的錯，而是任何進入 IDE 物件模型的呼叫都會卡住 UI，包含官方 MCP Server 自己（社群工具作者實測：「MCP 呼叫與 CODESYS 主執行緒會一直被卡住，直到腳本結束」，[codesys-mcp-scriptengine-runner](https://github.com/AccruedInnovation/codesys-mcp-scriptengine-runner)）。

不用 IronPython 的唯一正規路徑是購買 Automation Platform SDK（AP SDK）寫 C# 外掛（plug-in）。官方人員說「買了 AP SDK 就能用 C# 開發」（[Forge 9776](https://forge.codesys.com/forge/redirect/forum?lan=en&thread=9776)），但這個 SDK 不在 Store 上零售、採一次買斷授權、需要聯絡業務（[codesys.com 授權頁](https://www.codesys.com/device-manufacturers/codesys-for-you/licence-devices/)），而且外掛能否載入 Delta 與 Lenze 的改版 IDE 我查不到任何官方保證。

因此我的建議是：保留目前「磁碟文字為事實來源」的設計，把 IDE 內的 IronPython 縮到只剩一個約 100 行的「看門人」腳本（watcher），它用官方 API `system.delay()` 在主執行緒上輪詢並幫 IDE 抽送訊息迴圈，HTTP 或 MCP 介面則放到外部的 CPython 或 Node 程序。這正是社群專案 Codesys-MCP-SP21-plus 已驗證能在 SP19 到 SP22 上運作的模式（[watcher.py](https://raw.githubusercontent.com/phobicdotno/Codesys-MCP-SP21-plus/main/src/scripts/watcher.py)）。這樣做 IronPython 仍在，但它只剩「薄薄一層轉接頭」，而且不會再重蹈 2.x 那套「雙運行時同步」的複雜度（見第 5 節與 [REWORK_PLAN.md](REWORK_PLAN.md)）。

---

## 2. CODESYS 的自動化介面盤點

### 2.1 總表

| 介面 | 是什麼 | 取得方式與費用 | 語言 | 能否碰「目前開啟的專案」 | 是否阻塞 IDE 主執行緒 | 來源 |
|---|---|---|---|---|---|---|
| ScriptEngine（IronPython 腳本） | IDE 內建的 Python 腳本引擎，執行時自動 `from scriptengine import *` | 免費，內含於 Development System | IronPython 2.7.12（SP20、SP21）；Delta 1.8 與 1.10 為 2.7.7 | 可以 | 會（腳本在主執行緒跑） | [官方文件](https://content.helpme-codesys.com/en/CODESYS%20Scripting/_script_scripting_with_codesys.html)、[Scripting 4.1 版本說明](https://api-de.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release_Notes_CODESYS_Scripting_4100.html)、本機 DLL 版本（見 2.7 節） |
| Automation Platform SDK（AP SDK） | 用 .NET 寫 IDE 外掛（plug-in）的開發套件，可新增編輯器、精靈、指令 | 買斷授權，附文件、SDK 與授權碼；不在 Store 零售，需洽業務 | C#（.NET Framework 4.8，見 2.3 節） | 可以 | 進入物件模型的呼叫必須在主執行緒 | [Forge 9776](https://forge.codesys.com/forge/redirect/forum?lan=en&thread=9776)、[授權頁](https://www.codesys.com/device-manufacturers/codesys-for-you/licence-devices/)、[產品頁](https://www.codesys.com/device-manufacturers/codesys-for-you/your-tool-customizations/) |
| CODESYS.exe 命令列 | 啟動時帶參數開專案、跑腳本、比對專案 | 免費 | 任何能起程序的語言 | 不行（每次都是新程序） | 不影響你開著的那個 IDE | [命令列文件](https://content.helpme-codesys.com/en/CODESYS%20Development%20System/_cds_commandline.html) |
| 官方 Development System MCP Server | 官方 MCP 伺服器，AI 助手可讀寫目前開啟的專案 | 需 SP22 以上與 PDE 訂閱（1 人 550 歐元/年，5 人 2,750 歐元/年） | MCP（stdio） | 可以 | 會（見第 3 節） | [文件](https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/_idemcp_start_page.html)、[Store](https://store.codesys.com/en/codesys-mcp-server.html)、[PDE 價格](https://store.codesys.com/en/engineering/professional-developer-edition.html) |
| Automation Server | 雲端或自建的 PLC 機群管理平台（部署、監控、版本庫） | 訂閱 | — | 不行，它管的是控制器不是專案編輯 | 不相關 | [文件](https://content.helpme-codesys.com/en/CODESYS%20Automation%20Server/_cas_start_page.html) |
| CODESYS Git、SVN、Test Manager | IDE 內的版本控制與測試外掛；Test Manager 與 SVN 會把自己的物件加進 ScriptEngine | PDE 訂閱 | 透過 ScriptEngine 呼叫 | 可以 | 同 ScriptEngine | [Git 文件](https://content.helpme-codesys.com/en/CODESYS%20Git/_git_start_page.html)、[Scripting 文件](https://content.helpme-codesys.com/en/CODESYS%20Scripting/_script_scripting_with_codesys.html) |

以上任何一項都沒有文件記載「對外的 HTTP 或 REST 介面能編輯專案」。Automation Server 文件首頁與 Git 文件首頁都沒有提到 REST API；唯一的官方遠端介面是 MCP，而且是本機 stdio（[MCP 文件](https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/_idemcp_start_page.html)）。

### 2.2 ScriptEngine 與 AP SDK 是同一套物件模型嗎？

官方沒有一句話直接寫「外掛能做腳本能做的一切」。但有三段官方人員的說明可以拼起來：

1. 腳本 API 「本質上綁在主執行緒，因為它呼叫的是 Automation Platform 的 API」（M. Schaber，[Forge 60039f2d35](https://forge.codesys.com/forge/talk/Engineering/thread/60039f2d35/)）。
2. ScriptEngine 外掛本身提供官方的 Automation Platform API（`IScriptEngine`、`IScriptExecutor`），外掛可以用它啟動腳本，也可以用 `IScriptDriver.OnDriverLoad()` 把自己的物件用 `executor.ProvideObjectForScript()` 塞給腳本（M. Schaber，[Forge 5554](https://forge.codesys.com/forge/redirect/forum?lan=en&thread=5554)）。
3. 官方文件寫「ScriptEngine 的 API 可以用 Automation Platform 的 API 擴充」，Test Manager 與 SVN 就是這樣加物件的（[Scripting 文件](https://content.helpme-codesys.com/en/CODESYS%20Scripting/_script_scripting_with_codesys.html)）。

**推測**：腳本 API 是包在 Automation Platform API 外面的一層薄殼。所以 C# 外掛理論上能做腳本能做的一切（建 POU、寫 ST、匯入匯出 PLCopen XML、編譯、讀訊息、登入下載），而且只多不少。但這是推論，不是官方保證。

### 2.3 AP SDK 的取得、.NET 版本、簽章與改版 IDE 相容性

- 取得方式：官方寫「Automation Platform 採買斷授權；購買工具套件時你會拿到文件、SDK，以及製作附加元件或獨立工具所需的授權碼」（[授權頁](https://www.codesys.com/device-manufacturers/codesys-for-you/licence-devices/)）。我在 Store 搜尋「automation platform」與「platforms sdk」都找不到可購買的 SDK 品項（[搜尋 1](https://store.codesys.com/en/catalogsearch/result/?q=automation+platform)、[搜尋 2](https://store.codesys.com/en/catalogsearch/result/?q=platforms+sdk)）。價格與是否要求合作夥伴身分：查不到（見第 7 節）。
- .NET 版本：本機 `CODESYS 3.5.21.40\CODESYS\Common\CODESYS.exe.config` 寫 `.NETFramework,Version=v4.8`；Delta `DIADesigner-AX 1.10` 的 `DIADesigner-AX.exe.config` 也是 v4.8。SP21 版本說明有一條「RepTool.exe 需要的 .NET Framework 從 4.6.2 改成 4.8」（CDS-92777，[SP21 Release Notes](https://api-www.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release-Notes-CODESYS-35210.html)）。所以外掛要用 .NET Framework 4.8，不是 .NET 8。
- 外掛簽章：官方文件只規範「套件」（.package）的安裝：未簽章或自簽的套件，必須勾選「Allow unsigned and self-signed packages」才能裝（[安裝套件文件](https://content.helpme-codesys.com/en/CODESYS%20Development%20System/_cds_installing_package.html)）。另外「沒有對應授權的外掛不會被載入，IDE 執行中每五分鐘檢查一次授權」（[套件與授權管理](https://content.helpme-codesys.com/en/CODESYS%20Development%20System/_cds_struct_managing_packages_and_licenses.html)，命令列參數 `--skipunlicensedplugins` 也對應這件事）。我找不到任何文件說「外掛 DLL 本身必須簽章才會載入」。
- Forge 的 AP Unittest Framework 說明：外掛專案要「把 solution 與 csproj 的參考改成你自己安裝的 Automation Platform SDK」，而且只支援用官方相依注入機制宣告的相依（[AP Unittest Howto](https://forge.codesys.com/tol/ap-unittest/wiki/Howto/?version=2)）。這證實 SDK 是一份要安裝在本機的東西，不是 NuGet 套件。
- 改版 IDE 相容性：本機 Delta 1.10 的 `Engine.dll` 是 3.5.18.50，Lenze PLC Designer 4.0.1 的 `Engine.dll` 是 3.5.19.70，三者的 `PlugIns\{GUID}\{版本}` 目錄結構完全相同（本機檔案清單）。**推測**：外掛在改版 IDE 上能不能載入，取決於它參考的核心組件版本，跟一般 CODESYS 之間的相容規則一樣。官方相容規則：查不到（第 7 節）。
- 「S17 creating a scriptable plug-in」範例：查不到這個編號。Forge 上官方人員兩次提到 Developer Network 的文章「How to make a scriptable plugin」（[Forge 5554](https://forge.codesys.com/forge/redirect/forum?lan=en&thread=5554)、[Forge 60039f2d35](https://forge.codesys.com/forge/talk/Engineering/thread/60039f2d35/)）。**推測**：Developer Network 是 SDK 客戶才能進的站。

### 2.4 CODESYS.exe 命令列參數

官方文件列出的參數（[命令列文件](https://content.helpme-codesys.com/en/CODESYS%20Development%20System/_cds_commandline.html)）：

| 參數 | 用途（官方文字摘要） |
|---|---|
| `--project`、`--projectarchive` | 啟動並開啟指定專案或專案封存檔 |
| `--compare`、`--ignorewhitespace`、`--ignorecomments`、`--ignoreproperties` | 比對兩個專案 |
| `--culture`、`--profile`、`--additionalfolder` | 介面語言、啟動設定檔、多版本並存時指定實例 |
| `--runscript`、`--scriptargs`、`--noUI`、`--enablescripttracing`、`--textPrompts` | 啟動時跑腳本、傳參數、不開 UI、逐行顯示腳本、把對話框改成命令列輸入 |
| `--signaturethumbprint`、`--enforcesignedcompiledlibraries`、`--timestampingserverurl` | 程式庫簽章相關 |
| `--skipunlicensedplugins`、`--enableEventLog`、`--ForceDisconnectAfterInactivity` | 不載入無授權外掛、記錄到事件檢視器、閒置自動斷線 |

重點：文件裡**沒有任何參數能跟已經在跑的 IDE 實例通訊**（沒有 single-instance 訊息、沒有 named pipe）。`--noUI` 的行為是「CODESYS 啟動、執行腳本、不開主視窗，然後結束」（[命令列跑腳本文件](https://content.helpme-codesys.com/en/CODESYS%20Scripting/_cds_starting_script_via_command_line.html)）。`--profile` 的字串必須跟「說明 > 關於」顯示的完全一致，引號也算（[Forge ef1cb47eea](https://forge.codesys.com/forge/talk/Engineering/thread/ef1cb47eea/)）。

同一個 .project 被兩個實例開啟會怎樣：官方文件沒有寫。社群成員在 Forge 說 `.project.~u` 是「阻止其他 IDE 實例同時開啟同一份程式碼的鎖檔」，而且 IDE 每秒都會寫它一次（[Forge aca5362fc0](https://forge.codesys.com/forge/talk/Engineering/thread/aca5362fc0/)，非官方人員）。社群 MCP 工具作者的實務結論一致：「CODESYS 實際上是單實例應用程式」，所以他們用號誌把所有呼叫序列化（[CodesysMcpNet](https://github.com/BartK1990/CodesysMcpNet)）；另一篇教學也說「MCP 伺服器改專案時，IDE 必須先關掉那個專案」（[controlbyte 部落格](https://controlbyte.tech/blog/codesys-mcp-server-claude-ai-plc/)，二手來源）。

### 2.5 腳本執行環境的版本：有 IronPython 3 嗎？

沒有。證據如下：

- Scripting 4.1.0.0 的官方版本說明：「CODESYS Scripting 4.1.0.0 現在使用 IronPython 2.7.12」，同時「基於安全理由移除 IronPython 的 PIP 套件管理器」（[Release Notes Scripting 4.1.0.0](https://api-de.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release_Notes_CODESYS_Scripting_4100.html)）。
- 本機實際檔案：`CODESYS 3.5.20.40` 與 `3.5.21.40` 的 `LacBinaries\GAC_MSIL\IronPython\` 都只有 2.7.12；Delta 1.8 與 1.10 只有 2.7.7；Lenze 4.0.1 同時有 2.7.7 與 2.7.12。三台一般版 CODESYS 與兩家改版都找不到任何 IronPython 3 的 DLL。
- SP21 與 SP22 的完整版本說明裡，找不到 Scripting、IronPython、Python 3 的任何條目（[SP21](https://api-www.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release-Notes-CODESYS-35210.html)、[SP22](https://api-www.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release_Notes_CODESYS_35220.html)）。
- 歷史脈絡：2011 年官方人員 M. Schaber 宣布腳本語言時寫「因為 IronPython 3 預計年底推出，我們先嵌入 2.6.2，一有新版就盡快遷移」（[Forge d155f6e32a](https://forge.codesys.com/forge/talk/Engineering/thread/d155f6e32a/)）。十五年後仍是 2.7。
- 「Options > Scripting」裡有沒有 Python 版本切換：查不到這個選項的文件。CPython 或 Python.NET 支援：查不到。

所以「IronPython 是遺產技術」這個判斷是對的，而且短期內看不到官方換掉它的跡象。

### 2.6 官方 Development System MCP Server 的細節

- 官方文件原文：「MCP Server 透過本機的標準輸入輸出（stdio）通訊」；「任何本機設定好的 MCP 相容客戶端都能用它讀取並修改目前開啟的 CODESYS 專案，套用的是登入 IDE 那個使用者的權限」；「目前只支援 Structured Text，圖形語言的物件只能讀不能建立或修改」；「CODESYS V3 復原變更的手段有限，建議搭配檔案式專案儲存與 Git」；「內部測試中 Claude 模型的 ST 程式碼品質最好」（[文件首頁](https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/_idemcp_start_page.html)）。
- 工具清單共 20 個，例如 `create_or_replace_structured_text_object`、`replace_text_in_structured_text`、`check_for_errors`、`browse_project_tree`、`search_in_files_by_regex`、`add_or_remove_library`、`add_or_remove_program_call_in_task`、`get_device_and_io_configuration`（[工具頁](https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/_idemcp_mcp_tools_and_ressources.html)）。注意沒有「編譯後下載到 PLC」、沒有「匯入 PLCopen XML」。
- Store：版本 1.0.0.0，需要 Development System V3.5.22.1 以上、需要 PDE 訂閱、只能透過 CODESYS Installer 下載、不含技術支援（[Store 頁](https://store.codesys.com/en/codesys-mcp-server.html)）。文件站顯示目前文件版本為 V1.1.0.0（2026 年 7 月）（[文件索引](https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/index.html)）。
- 官方產品頁（頁面在調查時回傳 429，以下引自搜尋引擎摘要）：「自 2026 年 4 月 28 日起可透過 CODESYS Installer 取得，需 PDE 授權」；「可搭配 Claude、ChatGPT、GitHub Copilot 等 MCP 相容模型」（[AI 產品頁](https://www.codesys.com/products/engineering/ai-supported-engineering/)、[版本頁](https://www.codesys.com/ecosystem/release-lifecycle/releases-updates/development-system-mcp-server/)）。
- 它怎麼接上 IDE：文件沒寫。社群工具 codesys-mcp-scriptengine-runner 的 README 顯示，它在「執行中的 CODESYS」裡用執行期註冊的方式加一個 `run_codesys_script` 工具，授權要到「Tools > Options > MCP Server」設定，而且「MCP 呼叫與 CODESYS 主執行緒會一直被卡住直到腳本結束」、「主執行緒上的 ScriptEngine 呼叫沒有安全的硬逾時，卡住的腳本會卡住 IDE」（[README](https://raw.githubusercontent.com/AccruedInnovation/codesys-mcp-scriptengine-runner/main/README.md)）。**推測**：官方 MCP Server 是 IDE 內的外掛，AI 客戶端啟動的 stdio 程序只是轉接橋，工具真正執行在 IDE 主執行緒。

對你的意義：Delta DIADesigner-AX 1.10 的核心是 3.5.18.50，Lenze 是 3.5.19.70（本機 Engine.dll 版本），離 SP22 很遠，官方 MCP Server 在這兩台改版 IDE 上不可用。

### 2.7 本機安裝版本實測表

| IDE | 主程式版本 | Engine.dll | ScriptEngine 外掛版本 | IronPython | .NET（主程式 config） |
|---|---|---|---|---|---|
| CODESYS 3.5.19.10 | 3.5.19.10 | — | 4.0.0.0 | （GAC 目錄下未列出） | — |
| CODESYS 3.5.20.40 | 3.5.20.40 | — | 4.1.0.0 | 2.7.12 | — |
| CODESYS 3.5.21.40 | 3.5.21.40 | 3.5.21.40 | 4.2.0.0 | 2.7.12 | .NET Framework 4.8 |
| Delta DIADesigner-AX 1.8 | 1.8.0.280 | — | 4.0.0.0 | 2.7.7 | — |
| Delta DIADesigner-AX 1.10 | 1.10.0.9242 | 3.5.18.50 | 4.0.0.0 | 2.7.7 | .NET Framework 4.8 |
| Lenze PLC Designer 4.0.1 | 4.0.1.33999 | 3.5.19.70 | 4.1.0.0 | 2.7.7 與 2.7.12 | — |

來源：本機 `C:\Program Files` 下各 DLL 與 exe 的檔案版本資訊（PowerShell `VersionInfo`）。

---

## 3. 阻塞問題的真正成因

### 3.1 阻塞來自物件模型，不是來自 IronPython

- 2012 年 M. Schaber（官方）在「Python and threads」串裡說：可以在腳本裡開執行緒，但「我們不正式支援，風險自負」；「CODESYS 內部大多數 API 不是執行緒安全的，只能從主執行緒呼叫」；`print` 與腳本 API 「只能從主執行緒驅動，因為牽涉到 UI」；「主執行緒一旦從腳本返回，一些暫存狀態會被清掉」，所以主執行緒必須留在腳本裡；V3.5 SP1 起 `system` 物件新增 `execute_on_primary_thread`，可以把程式碼排回主執行緒（[Forge bf82e8cece](https://forge.codesys.com/forge/talk/Engineering/thread/bf82e8cece/)）。
- 同一位官方人員在另一串說：「IronPython 本身不依賴主執行緒」，但「標準腳本 API 本質上綁在主執行緒（UI 執行緒），因為它呼叫 Automation Platform 的 API」；如果只想在背景跑純 .NET 與 Python 標準庫，可以用 `IScriptExecutor` 但不要呼叫 `LoadScriptDrivers()`（[Forge 60039f2d35](https://forge.codesys.com/forge/talk/Engineering/thread/60039f2d35/)）。

結論很明確：**IDE 卡住是 Automation Platform 物件模型的性質。** 換成 C# 外掛，一樣要把每一次物件模型呼叫排回 UI 執行緒；外掛能做到的是「兩次呼叫之間 UI 活著」，做不到「呼叫進行中 UI 也活著」。HTTP 的收送本身可以在背景執行緒，這一點不論腳本或外掛都一樣。

### 3.2 官方提供的兩個「讓 UI 活著」的工具，以及 SP21 拿掉了其中一個

腳本 API 參考手冊裡 `system` 物件有兩個相關方法。官方文件站對自動抓取回傳 403，改用瀏覽器實際開啟後取得原文（[官方 ScriptSystem 頁](https://content.helpme-codesys.com/en/ScriptingEngine/ScriptSystem.html)，頁面內容對應 4.2.0.0，因為它列有「Version added: 4.2.0.0」的屬性）：

- `system.delay(milliseconds)`：官方原文「Delays the script for the specified amount of milliseconds. The message loop is served during the wait to allow background tasks to be processed. The actual duration of the delay will not meet hard realtime requirements.」也就是等待期間會抽送訊息迴圈，但時間精度不保證。
- `system.execute_on_primary_thread(code, async)`：**目前的官方頁面已經沒有這個方法**。舊版說明（引自 Schneider Machine Expert 鏡射站的搜尋摘要）寫「可從非主執行緒安全呼叫，依賴主執行緒處理它的訊息佇列」，`async` 為真時立即返回（[Schneider 鏡射頁](https://product-help.schneider-electric.com/Machine%20Expert/V1.1/en/ScriptEngine/topics/system.htm)）。

同一頁還有一條值得注意：`system.abortable` 的說明寫「自 V3.5.5.0 起腳本預設可中止，使用者可以按進度顯示（progress display）上的 Cancel 按鈕中止腳本」。這表示腳本執行期間 IDE 會顯示一個進度視窗。`system.delay()` 抽訊息時，這個進度視窗會不會擋住主視窗的操作，官方文件沒寫；Codesys-MCP-SP21-plus 的作者宣稱 UI 可互動，但我沒有親自實測（第 7 節）。

本機實測 DLL 字串（PowerShell 直接讀取檔案）：

- `CODESYS 3.5.21.40\CODESYS\Common\ScriptEngine3.dll`（4.2.0.0）含有字串 `'system.execute_on_primary_thread' is no longer supported` 與 `'system.process_messageloop' is no longer supported`。
- `CODESYS 3.5.20.40` 的 `ScriptEngine3.dll`（4.1.0.0）與 `3.5.19.10` 的（4.0.0.0）都**沒有**這兩句，只有方法本身的名稱。

社群專案 Codesys-MCP 的 README 也記錄：「CODESYS 在 SP21 系列的某個版本移除了 `se.system.execute_on_primary_thread()`」，呼叫會得到 `Marshal error: The functionality 'system.execute_on_primary_thread(...)' is no longer supported`（[Codesys-MCP README](https://raw.githubusercontent.com/luke-harriman/Codesys-MCP/main/README.md)）。SP21 與 SP22 的官方版本說明沒有記載這項移除（見 2.5 節）。

所以有兩種在 IDE 內「常駐、等待外部命令、UI 不死」的寫法，兩者都已有公開原始碼驗證：

| 寫法 | 機制 | 適用版本 | 已驗證的專案 |
|---|---|---|---|
| A. 背景執行緒 + 排回主執行緒 | 腳本開一條背景執行緒每 50 毫秒輪詢命令目錄，每個命令用 `system.execute_on_primary_thread()` 排回 UI 執行緒執行，主腳本開完執行緒就返回，UI 自由 | SP19、SP20，以及 Delta 1.8 與 1.10（ScriptEngine 4.0.0.0） | [luke-harriman/Codesys-MCP watcher.py](https://raw.githubusercontent.com/luke-harriman/Codesys-MCP/main/src/scripts/watcher.py) |
| B. 主執行緒輪詢 + `system.delay()` | 腳本永遠不返回，在主執行緒上 `while True` 輪詢命令目錄，每輪呼叫 `system.delay(50)`，由它「服務訊息迴圈、讓 UI 保持互動」；作者注解寫明「為什麼不用背景執行緒？因為 SP21+ 拿掉了 `execute_on_primary_thread()`」 | SP19、SP21、SP22（README 宣稱） | [phobicdotno/Codesys-MCP-SP21-plus watcher.py](https://raw.githubusercontent.com/phobicdotno/Codesys-MCP-SP21-plus/main/src/scripts/watcher.py) |

注意寫法 A 違反 2012 年官方「主執行緒返回後狀態會被清掉」的警告，但作者實測在 SP19 與 SP20 可用；寫法 B 完全符合官方模型，而且相容範圍最廣。**推測**：你要同時支援 Delta（4.0.0.0）、Lenze（4.1.0.0）與一般 SP21（4.2.0.0），寫法 B 是唯一一套程式碼通吃的方案。

### 3.2.1 本機實測：輪詢時 IDE 到底能不能操作（2026-09-04）

方法：用 `--runscript` 啟動一個全新的 IDE 實例，腳本在主執行緒上迴圈 45 秒，每輪用 `system.delay(50)` 或 `time.sleep(0.05)` 等待。外部用 PowerShell 每秒檢查主視窗三件事：Windows 是否判定它凍結（`IsHungAppWindow`）、送達型訊息有沒有回應（`SendMessageTimeout`）、投遞型訊息有沒有被處理（投遞「最小化」再檢查視窗是否真的縮小，然後還原）。投遞型訊息只有真正的訊息迴圈才會處理，所以那一項最能代表使用者的滑鼠鍵盤有沒有被吃掉。腳本同時記錄自己所在的執行緒：四組都是 ManagedThreadId 1，而且主視窗的 `InvokeRequired` 為 False，證明腳本確實跑在 UI 執行緒上。

| IDE | 等待方式 | 45 秒內主視窗狀態 | 結論 |
|---|---|---|---|
| CODESYS 3.5.21.40（ScriptEngine 4.2.0.0） | `system.delay(50)` | 未凍結、送達型與投遞型訊息都有處理、視窗可最小化還原 | 可操作 |
| CODESYS 3.5.21.40 | `time.sleep(0.05)` | 同上 | 可操作（見下方說明） |
| Delta DIADesigner-AX 1.10（ScriptEngine 4.0.0.0） | `system.delay(50)` | 同上 | 可操作 |
| Delta DIADesigner-AX 1.10 | `time.sleep(0.05)` | 腳本開始後數秒即被判定凍結，整段 45 秒無回應 | 凍結 |

兩點補充：

- 3.5.21.40 連 `time.sleep()` 都不會凍結，這和 Delta 1.10 不同。**推測**：4.2.0.0 的腳本執行器在每行 Python 之間的中止檢查（`abort_autocheck`）順便抽送了訊息，或者 IronPython 2.7.12 的 `sleep` 實作在 STA 執行緒上會抽送訊息。不管原因是哪個，跨版本可靠的寫法仍然是 `system.delay()`，因為它在 4.0.0.0 上也成立。
- 輪詢的 CPU 成本很低：45 秒的 `system.delay(50)` 迴圈大約多用 1 到 2 秒的處理器時間，相當於單核的 2% 到 4%。

限制：這四組都是用 `--runscript` 在啟動時執行腳本。從 Tools 選單啟動腳本的路徑我沒有量測到，因為 UI 自動化在 CODESYS 的 WinForms 選單上失敗，而且第二個 3.5.21.40 實例一開就跳出「有未儲存的專案資料可以復原」的對話框（指向使用者正開著的專案），我沒有回答它就把測試實例關掉了。兩種啟動方式的腳本都跑在 UI 執行緒上，經過同一個 ScriptEngine 執行器，我預期行為相同，但這是推測。手動驗證用的腳本放在 [`tools/probe_ui_responsive.py`](../tools/probe_ui_responsive.py)：從 Tools > Scripting > Execute Script File 執行它，45 秒內試著點選單和捲動編輯器。

### 3.3 無頭（headless）第二實例的限制

`--noUI --runscript` 的官方行為是「腳本跑完就結束」（[文件](https://content.helpme-codesys.com/en/CODESYS%20Scripting/_cds_starting_script_via_command_line.html)）。要讓它常駐，腳本自己不返回就行，Forge 上「CODESYS 可以無頭啟動並執行 Python 腳本」也是官方 Scripting 專案的說法（[Forge Scripting 首頁](https://forge.codesys.com/tol/scripting/home/Home/)）。限制：

- 它不能開你 IDE 裡正在開的那個專案（鎖檔，見 2.4 節，社群證據）。
- 每次呼叫起一個新程序的做法（codesys-mcp-toolkit、CodesysMcpNet、uiff）啟動成本高，因此這些專案都把呼叫序列化。
- 授權與記憶體：官方沒有文件說明第二個實例的授權或記憶體限制（第 7 節）。

### 3.4 這個 repo 自己做過的兩次常駐服務

git 歷史裡有兩次在 IDE 內常駐的嘗試，兩次的阻塞行為不同，剛好印證 3.1 與 3.2 節：

| 版本 | 做法 | IDE 會不會卡 | 下場 |
|---|---|---|---|
| 1.6.x 的 `Project_Daemon.py`（commit `4f63ab9`，2026-02 加入；`4a66c05`，2026-03-12 移除） | WinForms 的 `Timer` 每 100 毫秒觸發一次，掛在 IDE 自己的訊息迴圈上；腳本啟動計時器後立刻返回 | 不會，因為腳本已經結束 | 腳本返回後 `projects` 等物件會失效，所以寫了一整套 `resolve_projects` 去重新找活著的物件，這正是官方警告的「主執行緒返回後暫存狀態被清掉」。後來以「未使用的除錯腳本」為由移除 |
| 2.5.1 的 reverse-pipe daemon（commit `caf09e3`） | 主執行緒 `while running: time.sleep(0.5)`，背景執行緒或輪詢去接具名管道，重邏輯放在外部 CPython 3 | 會，因為 `time.sleep()` 期間沒有人抽送訊息迴圈 | 被 [REWORK_PLAN.md](REWORK_PLAN.md) 判定為複雜度來源而廢棄 |

**推測**：使用者印象中「常駐腳本會卡住 IDE」來自 2.5.1 那一版，根因是用 `time.sleep()` 等待而不是 `system.delay()`。把等待方式換掉，並且不讓腳本返回，就是 3.2 節的寫法 B。

---

## 4. 開源與社群專案清單

星數與最後推送日期取自 GitHub API（`gh repo view`，2026-09-04）。

| 專案 | 語言 | 星數 / 最後推送 | 授權 | 做法 | 支援的操作 | 怎麼處理 UI 執行緒 | 狀態 |
|---|---|---|---|---|---|---|---|
| [CODESYS 官方 Development System MCP Server](https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/_idemcp_start_page.html) | 非開源 | 1.0.0.0（Store），文件 1.1.0.0 | PDE 訂閱 | IDE 內外掛，stdio MCP | 讀寫 ST、建立或取代物件、正規搜尋、檢查錯誤、程式庫、任務指派、裝置樹（20 個工具） | 在主執行緒執行，呼叫期間 UI 卡住（社群實測） | 需 SP22.1 以上 |
| [johannesPettersson80/codesys-mcp-toolkit](https://github.com/johannesPettersson80/codesys-mcp-toolkit) | TypeScript | 121 / 2025-05-24 | MIT | 每次呼叫起 `CODESYS.exe` 跑腳本 | open/create/save project、create_pou、set_pou_code、create_method、create_property、compile | 新程序，與你的 IDE 無關；IDE 內不能開同一專案 | 一年多沒動 |
| [johannesPettersson80/codesys-api](https://github.com/johannesPettersson80/codesys-api) | Python 3 | 30 / 2025-08-25 | MIT | 外部 HTTP 伺服器（0.0.0.0:8080）＋ 常駐 CODESYS 實例跑 `PERSISTENT_SESSION.py` | session、專案開關存、compile、POU 建立修改、任意腳本 | 常駐實例，不是你的 IDE | 一年沒動 |
| [luke-harriman/Codesys-MCP](https://github.com/luke-harriman/Codesys-MCP) | Python 腳本 + TypeScript | 69 / 2026-05-31 | MIT | 持久 UI 實例 + 檔案 IPC 看門人（寫法 A） | 41 個工具：專案、POU、程式庫、裝置樹、上線、讀寫變數、下載、封存 | 背景執行緒 + `execute_on_primary_thread` | README 明寫 SP21+ 只能無頭 |
| [phobicdotno/Codesys-MCP-SP21-plus](https://github.com/phobicdotno/Codesys-MCP-SP21-plus) | TypeScript + IronPython | 16 / 2026-09-03 | MIT | 上者的分支，看門人改成主執行緒 `system.delay()` 輪詢（寫法 B） | 100 多支腳本，含 `export_native`、`import_native`、`export_plcopen_xml`、`import_plcopen_xml`、`get_compile_messages`、`download_to_device`、`source_download` | 主執行緒輪詢，`system.delay(50)` 抽訊息 | 活躍，最近一天有推送 |
| [Zhangmingjun-Huarui/Codesys-MCP](https://github.com/Zhangmingjun-Huarui/Codesys-MCP) | Python | 4 / 2026-04-14 | MIT | 同 luke-harriman 模式（Rev2.1.0） | 同上 | 同上 | 少量 |
| [BartK1990/CodesysMcpNet](https://github.com/BartK1990/CodesysMcpNet) | C#（ASP.NET Core 10）+ Python 腳本 | 1 / 2026-08-06 | MIT | 外部 .NET 服務（127.0.0.1:5088）同時提供 REST 與 MCP，每次呼叫起 `CODESYS.exe --runscript` | structure、POU/GVL/DUT/ENUM 讀與建、compile | 號誌序列化；「CODESYS 實際上是單實例」 | 新 |
| [AccruedInnovation/codesys-mcp-scriptengine-runner](https://github.com/AccruedInnovation/codesys-mcp-scriptengine-runner) | Python + .NET 4.8 | 0 / 2026-08-13 | MIT | 在官方 MCP Server 1.1 內用執行期註冊加一個 `run_codesys_script` 工具 | 任意 IronPython 腳本 | 明寫「MCP 呼叫與主執行緒卡住直到腳本結束」 | 需 3.5.22.20 |
| [uiff/Codesys-MCP-Server](https://github.com/uiff/Codesys-MCP-Server) | TypeScript | 1 / 2026-07-10 | MIT | 每次呼叫 `--noUI --runscript` | 21 個工具：專案、程式碼、任務、程式庫、build 帶結構化錯誤、裝置與 IO | 序列化，新程序 | 測試於 SP22 |
| [YGSSNB/My_Tool_CodesysMcp](https://github.com/YGSSNB/My_Tool_CodesysMcp) | C#（.NET 10 WPF）+ Python 腳本 | 0 / 2026-08-28 | 未標示 | 常駐 HTTP MCP（127.0.0.1:5180/mcp）驅動 Inovance InoProShop（CODESYS 改版）與一般 CODESYS | 41 個工具 | 未說明 | 新；證明腳本路線可跑改版 IDE |
| [efranceschetti/festo-codesys-mcp](https://github.com/efranceschetti/festo-codesys-mcp) | TypeScript | 1 / 2026-08-26 | MIT | 預設離線產生 ST 與驗證過的 PLCopen XML；設定路徑後可用腳本引擎驅動 CODESYS | 產生 ST、DUT、GVL、PLCopen XML、靜態分析；可選 12 個 IDE 工具 | 未說明 | 新 |
| [tekinaDev/codesys-mcp](https://github.com/tekinaDev/codesys-mcp) | 文件 | 5 / 2026-01-29 | 未標示 | VS Code 裝 `@codesys/mcp-toolkit` 的設定教學 | 同 toolkit | 同 toolkit | 教學 |
| [greenforge-labs/codescribe](https://github.com/greenforge-labs/codescribe) | IronPython 2.7 | 30 / 2026-08-05 | Apache-2.0 | IDE 內五支腳本做工具列按鈕，匯出 `.st` 與原生 XML、匯入回去 | 匯出匯入 POU、GVL、DUT、方法、屬性、動作、視覺化、裝置等；範本專案 | 在主執行緒跑，執行中卡 UI | 活躍；測試於 SP11 |
| [ArthurkaX/cds-text-sync](https://github.com/ArthurkaX/cds-text-sync) | IronPython | 93 / 2026-08-17 | MIT | IDE 內腳本，匯出 ST、外部工具或 LLM 編輯後同步回去 | export、import、compare | 同上 | 活躍；本 repo（kevin00156/cds-text-sync）為其分支 |
| [tkucic/codesys_workflow_automation](https://github.com/tkucic/codesys_workflow_automation) | IronPython | 22 / 2026-06-11 | MIT | IDE 內腳本 | 存檔並匯出 PLCopen XML 或原生 XML；從 JSON 建 POU 與型別 | 同上 | 低頻維護 |
| [johannesPettersson80/trust-platform](https://github.com/johannesPettersson80/trust-platform) | Rust | 221 / 2026-09-04 | Apache-2.0 | 獨立的 ST 語言伺服器、執行時、瀏覽器 IDE，PLCopen XML 匯入匯出 | 不碰 CODESYS IDE | 不相關 | 非常活躍（鄰近專案） |
| [Serhioromano/vscode-st](https://github.com/Serhioromano/vscode-st) | TypeScript | 203 / 2026-09-03 | MIT | VS Code 的 ST 語法、片段、大綱；LSP 在路線圖上 | 不同步 CODESYS | 不相關 | 活躍（鄰近） |
| [ControlForge-Systems/controlforge-structured-text](https://github.com/ControlForge-Systems/controlforge-structured-text) | TypeScript | 22 / 2026-08-14 | MIT | VS Code 的 ST 語言支援，含診斷與補全 | 不同步 CODESYS | 不相關 | 活躍（鄰近） |
| [beremiz/beremiz](https://github.com/beremiz/beremiz) | Python | 432 / 2026-09-01 | GPL | 獨立的開源 IEC 61131-3 IDE | 與 CODESYS 無關 | 不相關 | 鄰近 |
| [thiagoralves/OpenPLC_v3](https://github.com/thiagoralves/OpenPLC_v3) | C++ | 1,570 / 2026-04-04 | GPL-3.0 | 開源 PLC 執行時，2026-04-04 起停止維護改由 v4 接手 | 與 CODESYS 無關 | 不相關 | 鄰近 |

另有 `JasonHe/TM753-Codesys-MCP`（INVT Invtmatic Studio 改版 IDE 搭配 Codesys-MCP 的 Codex 技能）、`VeselovValery/codesys_ai_agent`（LangChain 代理，0 星）、`GaGa-Yin/rung-mcp-references`（某 `codesys-mcp-suite` 的參考資料），均為個位數星，只列名不細述（GitHub 搜尋 `gh search repos`）。

**JIDIEN Sync**：在 jidien.com 首頁、最新消息、LinkedIn 與 Facebook 的搜尋結果、以及 GitHub 上，都找不到「JIDIEN Sync」或它的實作方式（[jidien.com](https://www.jidien.com/zh_tw/)）。**推測**：從你描述的「127.0.0.1:18080、`/create_object`、`/import_pou`、`/build`、IDE 不卡」以及 Delta 1.10 是 ScriptEngine 4.0.0.0（仍支援 `execute_on_primary_thread`）來看，它最可能是第 3.2 節寫法 A 或寫法 B 的變體加上一個 IronPython 內建的 HTTP 伺服器（2012 年那串 Forge 就有人用 Bottle 框架在腳本裡跑 HTTP 伺服器成功），也可能是 C# 外掛。無法查證。

---

## 5. 四種架構方案比較

先把 [REWORK_PLAN.md](REWORK_PLAN.md) 記下的教訓放在眼前：2.x 為了在 CPython 3 跑重邏輯，做了「subprocess + named pipe + 雙運行時同步」，是它「一半的複雜度來源」，於是 §9 明文「不要 subprocess、named pipe、HTTP daemon（除非階段 4 證明非要不可）」。下面每個方案都對照這條。

| 方案 | 需要什麼 | 呼叫進行中 IDE 會不會卡 | 兩次呼叫之間 IDE 活不活 | Delta 與 Lenze 可攜性 | 工作量 | 主要風險 |
|---|---|---|---|---|---|---|
| 1. C# AP SDK 外掛，程序內跑 HTTP 或 MCP，排回 UI 執行緒 | 買 AP SDK（非零售、買斷、洽業務）、Visual Studio、.NET Framework 4.8；簽章非必要但套件安裝要勾允許未簽章 | 會（物件模型呼叫必須在 UI 執行緒） | 活 | 未知；核心版本 3.5.18.50 與 3.5.19.70 差異大，可能要各編一版 | 高（新語言、新 SDK、新部署管道） | SDK 買不到或太貴；改版 IDE 相容性沒有官方保證；每版 IDE 都要重建 |
| 2. 薄的 IDE 內看門人（IronPython，寫法 B）+ 外部 CPython 或 Node 程序擁有 HTTP 或 MCP | 免費；一支約 100 行的 IronPython 腳本；外部程序用你熟的語言 | 會（同上） | 活（`system.delay()` 抽訊息迴圈） | 好：ScriptEngine 4.0.0.0 到 4.2.0.0 都有 `system.delay()`；同型專案已在 Inovance 與 INVT 改版上跑 | 中 | IronPython 沒消失，只是變薄；檔案 IPC 要處理逾時與殘留；違反 REWORK_PLAN §9 的字面，但不違反它的精神（見下文） |
| 3. 無頭第二實例 `--noUI --runscript` 常駐 HTTP | 免費 | 不會（是另一個程序） | 不相關 | 好 | 中 | 不能碰你 IDE 開著的專案（鎖檔）；等於做「另一個 IDE」，不是「控制你的 IDE」；第二實例的授權與記憶體沒有文件 |
| 4. 純檔案同步（現況）+ 外部 MCP 只碰檔案，需要時觸發 IDE 內匯入 | 免費；現有程式碼 | 匯入那一下會卡 | 活（平常沒有腳本在跑） | 最好 | 最低 | 「觸發匯入」這一步仍需人按一下，或需要方案 2 的看門人 |

### 5.1 為什麼方案 1 不划算

不是技術不行，是門檻與可攜性。SDK 不在 Store（2.3 節），要跟業務談；外掛在 Delta 1.10（核心 3.5.18.50）與 Lenze（3.5.19.70）能否直接載入沒有官方規則；而你換來的好處只有「HTTP 伺服器用 C# 寫」，因為 UI 卡住的問題並不會因此消失（3.1 節）。

### 5.2 方案 2 與 REWORK_PLAN 的關係

2.x 的問題不是「有兩個程序」，而是「重邏輯跑在外面，兩邊要同步狀態」。方案 2 的分工完全不同：

- IDE 內只有看門人：讀命令檔、呼叫 `cds.app.export` 或 `cds.app.import_`、寫結果檔、`system.delay(50)`。沒有任何業務邏輯。
- 事實來源仍是磁碟上的 `.st`（REWORK_PLAN §2.4）。外部程序只做三件事：對 AI 提供 MCP 或 HTTP 工具、讀寫 `.st` 檔、把「請匯入」或「請匯出」這兩個命令丟到命令目錄。
- `cds/core/` 仍是純 Python，仍在 CI 上用 CPython 3.12 測。

所以它是 REWORK_PLAN §7 的「階段 4：只加一條最小管道」，而不是回到 2.x。

### 5.3 方案 3 的定位

它適合 CI（例如 PR 進來就無頭編譯一次）。它不適合「AI 幫我改我現在開著的專案」，因為兩個實例不能開同一個專案（2.4 節社群證據）。codesys-mcp-toolkit、CodesysMcpNet、uiff 三個專案都是這種模式，也都要求 IDE 先關掉專案。

---

## 6. 建議

1. **不要為了擺脫 IronPython 去買 AP SDK。** 卡 UI 的根因在物件模型（3.1 節），換語言換不掉。SDK 的取得與改版 IDE 相容性都沒有公開保證（2.3 節）。
2. **採方案 4 加方案 2 的「最小看門人」。** 具體是：
   - 在 `cds/ide/` 新增一支 `watcher.py`，照 Codesys-MCP-SP21-plus 的寫法 B：主執行緒 `while True`，輪詢一個命令目錄，每輪 `system.delay(50)`；命令只有 `export`、`import`、`compare`、`build` 四種，各自呼叫現有的 `cds.app.*`。
   - 外部程序（建議 CPython 3，跟 CI 同一個環境）提供 MCP 工具：`read_st`、`write_st`、`sync_to_ide`（寫命令檔、等結果檔）、`build`。AI 平常只碰檔案，只有 `sync_to_ide` 才會讓 IDE 卡幾秒。
   - 用 `system.delay()` 而不用 `execute_on_primary_thread`，因為前者在 4.0.0.0 到 4.2.0.0 都在，後者在 SP21 被拿掉（3.2 節）。
3. **把「呼叫期間會卡」寫進使用說明。** 這是平台性質；官方 MCP Server 也一樣（2.6 節）。設計上把每次同步的工作量壓到最小（REWORK_PLAN §5 的批次化）就是在縮短卡住的時間。
4. **留意 SP22 以上的官方 MCP Server。** 等 Delta 與 Lenze 的改版跟上 SP22，官方工具會直接覆蓋「AI 讀寫開啟中的專案」這個需求，你的工具的差異化就只剩「磁碟文字為事實來源、可進 Git、可離線」。這剛好是官方文件自己建議搭配的東西（「建議使用檔案式專案儲存與 Git」）。
5. **不要投入方案 3 當主線。** 它與「控制你開著的 IDE」互斥。

---

## 7. 未能查證的事項

1. AP SDK 的價格、是否要求合作夥伴或裝置製造商身分、目前對應哪個 CODESYS 版本。Store 沒有品項，產品頁在調查期間回傳 429，只能靠搜尋摘要。
2. 外掛（plug-in）DLL 是否需要程式碼簽章才會被 IDE 載入。只找到「套件」安裝時對未簽章的處理，以及「無授權外掛不載入」的規定。
3. 以一般 CODESYS 3.5.x 編譯的外掛能否載入 Delta DIADesigner-AX 或 Lenze PLC Designer 的官方相容規則。
4. 「S17 creating a scriptable plug-in」這個範例的存在。只找到官方人員提到 Developer Network 文章「How to make a scriptable plugin」。
5. `execute_on_primary_thread` 與 `process_messageloop` 被移除的官方版本說明。DLL 字串與社群 README 都證實 SP21 已移除，但 SP21、SP22 的 Release Notes 沒有條目，Scripting 4.2.0.0 的版本說明頁不存在（回傳 404）。
6. 同一 `.project` 被兩個實例開啟的官方鎖檔行為。只有社群成員說明 `.~u` 是鎖檔。
7. 無頭第二實例的授權與記憶體限制。
8. 官方 MCP Server 的 stdio 程序如何連到 IDE 程序（named pipe 或其他）。文件只說 stdio，社群 README 顯示工具在 IDE 主執行緒執行。
9. 「Options > Scripting」是否存在任何 Python 版本切換。文件與本機檔案都沒有 IronPython 3 的跡象，但我沒有實際打開該選項頁確認。
10. JIDIEN Sync 的任何公開資訊。
11. `execute_on_primary_thread()` 的官方 API 參考原文。目前的官方 ScriptSystem 頁面已不列這個方法（`system.delay()` 的原文已用瀏覽器取得，見 3.2 節），舊版說明只能引用 Schneider 鏡射站的搜尋摘要。
12. 腳本在主執行緒上用 `system.delay()` 輪詢時 IDE 是否可操作：已在 Delta 1.10 與 CODESYS 3.5.21.40 上用 `--runscript` 實測為可操作（3.2.1 節），而且沒有出現獨立的進度視窗。尚未實測的是「從 Tools 選單啟動」這條路徑，以及看門人執行期間能不能再從選單啟動別的腳本。

---

## 8. 來源清單

官方文件（content.helpme-codesys.com）

- MCP Server 首頁：https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/_idemcp_start_page.html
- MCP Server 工具清單：https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/_idemcp_mcp_tools_and_ressources.html
- MCP Server 文件索引（版本 1.1.0.0）：https://content.helpme-codesys.com/en/CODESYS%20Development%20System%20MCP%20Server/index.html
- 命令列參數：https://content.helpme-codesys.com/en/CODESYS%20Development%20System/_cds_commandline.html
- 從命令列啟動腳本：https://content.helpme-codesys.com/en/CODESYS%20Scripting/_cds_starting_script_via_command_line.html
- Scripting in CODESYS：https://content.helpme-codesys.com/en/CODESYS%20Scripting/_script_scripting_with_codesys.html
- 用腳本存取 CODESYS 功能：https://content.helpme-codesys.com/en/CODESYS%20Scripting/_cds_access_cds_func_in_python_scripts.html
- 安裝套件（簽章）：https://content.helpme-codesys.com/en/CODESYS%20Development%20System/_cds_installing_package.html
- 套件與授權管理：https://content.helpme-codesys.com/en/CODESYS%20Development%20System/_cds_struct_managing_packages_and_licenses.html
- Automation Server：https://content.helpme-codesys.com/en/CODESYS%20Automation%20Server/_cas_start_page.html
- CODESYS Git：https://content.helpme-codesys.com/en/CODESYS%20Git/_git_start_page.html
- ScriptingEngine API 索引（抓取受限）：https://content.helpme-codesys.com/en/ScriptingEngine/index.html

官方 Store 與 codesys.com

- MCP Server Store 頁：https://store.codesys.com/en/codesys-mcp-server.html
- Professional Developer Edition 價格：https://store.codesys.com/en/engineering/professional-developer-edition.html
- AI 產品頁（429，引自搜尋摘要）：https://www.codesys.com/products/engineering/ai-supported-engineering/
- MCP Server 版本頁（429）：https://www.codesys.com/ecosystem/release-lifecycle/releases-updates/development-system-mcp-server/
- Automation Platform 產品頁（429，引自搜尋摘要）：https://www.codesys.com/device-manufacturers/codesys-for-you/your-tool-customizations/
- 授權模式（買斷）：https://www.codesys.com/device-manufacturers/codesys-for-you/licence-devices/
- Store 搜尋：https://store.codesys.com/en/catalogsearch/result/?q=automation+platform 、https://store.codesys.com/en/catalogsearch/result/?q=platforms+sdk
- Scripting 4.1.0.0 Release Notes：https://api-de.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release_Notes_CODESYS_Scripting_4100.html
- SP21 Release Notes：https://api-www.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release-Notes-CODESYS-35210.html
- SP22 Release Notes：https://api-www.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release_Notes_CODESYS_35220.html
- SP21 Patch 4 Release Notes（未簽章套件外掛顯示錯誤）：https://api-www.codesys.com/fileadmin/user_upload/CODESYS_Group/Ecosystem/Up-to-Date/Releases-Lifecycle/Release-Updates/Release-Notes/Release-Notes-CODESYS-352140.html

CODESYS Forge（官方人員回覆）

- Python and threads（M. Schaber，2012）：https://forge.codesys.com/forge/talk/Engineering/thread/bf82e8cece/
- How to run python script via plugin?（M. Schaber）：https://forge.codesys.com/forge/talk/Engineering/thread/60039f2d35/
- Execute custom object commands in python script（M. Schaber）：https://forge.codesys.com/forge/redirect/forum?lan=en&thread=5554
- Using ScriptEngine in C#（mkeller）：https://forge.codesys.com/forge/redirect/forum?lan=en&thread=9776
- The new scripting language in V3（M. Schaber，2011）：https://forge.codesys.com/forge/talk/Engineering/thread/d155f6e32a/
- --noUI 與 --profile 引號問題：https://forge.codesys.com/forge/talk/Engineering/thread/ef1cb47eea/
- .project.~u 鎖檔（社群成員）：https://forge.codesys.com/forge/talk/Engineering/thread/aca5362fc0/
- Scripting 專案首頁：https://forge.codesys.com/tol/scripting/home/Home/
- AP Unittest Framework Howto：https://forge.codesys.com/tol/ap-unittest/wiki/Howto/?version=2

OEM 鏡射的 API 參考（引自搜尋摘要）

- Schneider Machine Expert ScriptEngine `system`：https://product-help.schneider-electric.com/Machine%20Expert/V1.1/en/ScriptEngine/topics/system.htm

GitHub 專案（README 與原始碼）

- https://github.com/luke-harriman/Codesys-MCP 與 https://raw.githubusercontent.com/luke-harriman/Codesys-MCP/main/src/scripts/watcher.py
- https://github.com/phobicdotno/Codesys-MCP-SP21-plus 與 https://raw.githubusercontent.com/phobicdotno/Codesys-MCP-SP21-plus/main/src/scripts/watcher.py
- https://github.com/AccruedInnovation/codesys-mcp-scriptengine-runner
- https://github.com/johannesPettersson80/codesys-mcp-toolkit
- https://github.com/johannesPettersson80/codesys-api
- https://github.com/BartK1990/CodesysMcpNet
- https://github.com/uiff/Codesys-MCP-Server
- https://github.com/YGSSNB/My_Tool_CodesysMcp
- https://github.com/efranceschetti/festo-codesys-mcp
- https://github.com/tekinaDev/codesys-mcp
- https://github.com/Zhangmingjun-Huarui/Codesys-MCP
- https://github.com/greenforge-labs/codescribe
- https://github.com/ArthurkaX/cds-text-sync
- https://github.com/tkucic/codesys_workflow_automation
- https://github.com/johannesPettersson80/trust-platform
- https://github.com/Serhioromano/vscode-st
- https://github.com/ControlForge-Systems/controlforge-structured-text
- https://github.com/beremiz/beremiz
- https://github.com/thiagoralves/OpenPLC_v3
- GitHub 主題頁：https://github.com/topics/codesys

二手來源（只用來佐證，不作主要依據）

- controlbyte 部落格（toolkit 需關閉專案）：https://controlbyte.tech/blog/codesys-mcp-server-claude-ai-plc/

本機檔案（PowerShell 讀取）

- `C:\Program Files\CODESYS 3.5.21.40\CODESYS\Common\ScriptEngine3.dll`（4.2.0.0，含「no longer supported」字串）
- `C:\Program Files\CODESYS 3.5.20.40\CODESYS\Common\ScriptEngine3.dll`（4.1.0.0）
- `C:\Program Files\CODESYS 3.5.19.10\CODESYS\Common\ScriptEngine3.dll`（4.0.0.0）
- 各 IDE 的 `LacBinaries\GAC_MSIL\IronPython\` 版本目錄、`Common\Engine.dll`、`Common\*.exe.config`
- `C:\Program Files\Delta Industrial Automation\DIAStudio\DIADesigner-AX 1.8` 與 `1.10`、`C:\Program Files\Lenze\PlcDesigner\4.0.1.33999`
