# Personal Finance Console

銀行・証券・財布・クレカをまとめて把握する **個人 CFO コンソール**。  
MoneyForward 的な自動取得は捨て、手入力と CSV 取り込みで完結させる。

---

## セットアップ

```bash
git clone <repo>
cd my_cfo
python -m venv .venv
make install   # textual をインストール
```

`finance_config.yaml` に LM Studio の接続先を設定する（`/ask` を使う場合）。

```yaml
llm:
  base_url: http://localhost:1234/v1
  model: your-model-id   # 空欄にすると自動選択
```

---

## 起動

```bash
./cfo          # CLI ループ
./cfo --tui    # TUI モード（推奨）
make run       # CLI ループ
make tui       # TUI モード
```

---

## コマンド一覧

### 資産スナップショット

| コマンド | 説明 |
|---------|------|
| `/now` | 現在の資産状況を表示 |
| `/set-bank <amount>` | 銀行残高を更新 |
| `/set-securities <amount>` | 証券評価額を更新 |

### 財布

| コマンド | 説明 |
|---------|------|
| `/cash-set <amount>` | 財布残高を実測補正 |
| `/cash-in <amount> <memo>` | 財布に入金 |
| `/cash-out <amount> <memo>` | 財布から支出 |
| `/cash` | 財布の取引履歴を表示 |
| `/atm <amount> [memo]` | 銀行→財布へATM引き出し（総資産は変わらない） |

### クレカ

| コマンド | 説明 |
|---------|------|
| `/import [dir]` | `data/inbox/card/` の CSV を一括取り込み（重複スキップ） |
| `/card [this_month\|YYYY-MM]` | カード利用集計を表示 |

### LLM 分析

| コマンド | 説明 |
|---------|------|
| `/ask <質問>` | 資産データをコンテキストに LM Studio へ問い合わせ |

---

## TUI キーバインド

| キー | 動作 |
|------|------|
| F1 | ヘルプ表示 |
| F2 | `/now` |
| F3 | `/card this_month` |
| F4 | `/cash` |
| F5 | `/atm ` をインプットにセット |
| F6 | `/ask ` をインプットにセット |
| F10 | 終了 |

---

## 総資産の定義

```
銀行残高 + 証券評価額 + 財布残高 - クレカ今月引き落とし額
```

振替（ATM引き出し等）は支出ではなく資産の移動なので総資産は変わらない。

---

## ディレクトリ構成

```
my_cfo/
├── cfo                        # 実行スクリプト
├── main.py                    # CLI エントリーポイント
├── finance_config.yaml        # LLM 接続設定
├── requirements.txt
├── Makefile
├── finance_core/
│   ├── config.py
│   ├── db.py
│   ├── llm.py
│   ├── importers/
│   │   └── credit_card_csv.py
│   └── services/
│       ├── snapshots.py
│       ├── manual_snapshots.py
│       ├── transfers.py
│       ├── now.py
│       └── ask_context.py
├── fin_console/
│   └── app.py                 # Textual TUI
├── migrations/
│   └── 001_init.sql
└── data/
    └── inbox/card/            # CSV をここに置いて /import
```

---

## CSV 取り込み

`data/inbox/card/` に明細 CSV を置いて `/import` を実行する。

- ファイルハッシュで二重取り込みを自動防止
- Shift-JIS (CP932) / UTF-8 どちらも対応
- 対応フォーマット
  - **Format A**: ヘッダー行あり、支払月をファイル名（`202604.csv` → `2026-04`）から取得
  - **Format B**: ヘッダー行なし、支払月を列から取得
