# CCTWW(透過CCTV猜目前在哪裡？)

透過交通部公開的xml資料，獲取所有在公路上的cctv資訊以及鏡頭。用選擇的方法讓玩家猜測！

## CCTV 可用池

第二版會在背景分批檢查 CCTV，將可用狀態、品質分數、檢查時間與失敗原因寫入獨立的 `cctv_health` 表。遊戲選題優先從 12 小時內確認可用的鏡頭抽取；池內資料不足時，最多即時檢查 5 支候選，不會無限重試。

部署既有資料庫時，必須先套用：

```text
sqldata/migrations/20260924_add_cctv_health_pool.sql
```

應用啟動後會先將可用池補到至少 50 支。候選 CCTV 會先依 `road_name` 分組，每條道路隨機取一支；批次仍有空位時，才依序加入同道路的第二支、第三支，避免資料庫前段或單一道路造成題目偏差。完成初始池後，每 60 秒處理 5 支尚未檢查或需要重查的 CCTV。現行背景工作設計以單一應用程序為準；若使用多個 Uvicorn worker，各程序會重複執行檢查，部署時應先維持單 worker，或將背景工作拆成獨立服務。

同一局的新題目會排除已出現過的道路與最終顯示名稱；每題的四個選項也會同時依道路名稱與顯示名稱去重。

`quality_score` 只用於觀測，不取代原本的 HTTP、decode、亮度、暗部比例與影像細節合格規則。

# 這裡是dev，如果合併請找這裡

## 指令速記
pip freeze > requirements.txt 輸出環境的插件記錄到requirement
pip install -r requirements.txt 輸入requirement環境內所有插件
deactivate 離開環境

## 切換到此專案環境

# 切記測試時，將環境切換到專案內目前環境。

1. Powershell  執行 .venv/Scripts/activate.ps1  
2. 確認目前terminal開頭帶有(.venv)，代表進入環境
3. 如果不確定專案使否有新插件，執行pip install -r requirements.txt 安裝所有表上的插件做檢查
4. 如果有安裝插件，請使用 "pip freeze > requirements.txt " 將新增的插件更新到表上
5. 離開環境使用deactivate。
