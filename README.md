# Personal Finance Console

個人の資産現在地を素早く見るためのコンソールです。  
このプロジェクトは「完璧な家計簿」ではなく、銀行・証券・財布・カード利用を分けて把握するための **個人 CFO コンソール** を目指します。

## 概要

初期フェーズでは、以下を最小構成で実装します。

- 銀行残高の手入力
- 証券評価額の手入力
- 物理財布残高の手入力
- 今月のカード利用額の集計
- 現在地の表示（`/now` 相当）

## 対象範囲

### Phase 1

- DB 初期化
- `set-bank`
- `set-securities`
- `cash-set`
- `/now` 相当の表示

### Phase 2 以降

- `cash-in` / `cash-out`
- `transfer`
- クレカ CSV 取り込み
- 簡易 CLI ループ
- `/ask` と LLM 連携

## 要件

- Python 3.11+
- SQLite3（標準ライブラリ）
- CLI ベース

## セットアップ

現時点では Phase 1 の土台のみを用意しています。  
必要なファイルは以下です。

- `main.py`
- `finance_core/db.py`
- `finance_core/services/snapshots.py`
- `migrations/001_init.sql`
- `finance_config.yaml`

## 使い方

Phase 1 では、以下のコマンド相当の処理を想定しています。

- `/set-bank 3200000`
- `/set-securities 58800000`
- `/cash-set 42000`
- `/now`

## ディレクトリ構成

```text
my_cfo/
├── main.py
├── README.md
├── finance_config.yaml
├── finance_core/
│   ├── __init__.py
│   ├── db.py
│   └── services/
│       ├── __init__.py
│       └── snapshots.py
└── migrations/
    └── 001_init.sql
```

## 実行例

```text
fin> /set-bank 3200000
fin> /set-securities 58800000
fin> /cash-set 42000
fin> /now
```

## 今後の予定

- Phase 2: 財布操作と振替
- Phase 3: クレカ CSV 取り込み
- Phase 4: 簡易 CLI ループ
- Phase 5: `/ask` と LLM 連携

## 補足

- 振替は支出ではありません
- 総資産は「銀行 + 証券 + 財布 - カード利用」で見ます
- 既存設計を勝手に広げず、段階的に実装します

