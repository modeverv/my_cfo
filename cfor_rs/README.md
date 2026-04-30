# cfor — Personal Finance Console (Rust)

親プロジェクト [`my_cfoR`](../) の Rust 移植版。  
SQLite バックエンドはバイナリに同梱（`rusqlite` bundled）のため、追加インストール不要。

---

## ビルド

```bash
# Rust が未インストールの場合
brew install rust

# Debug ビルド
cargo build

# Release ビルド（推奨）
cargo build --release
```

ビルド成果物:

| バイナリ | 説明 |
|---------|------|
| `target/release/cfor` | CLI / TUI |
| `target/release/cfor-mcp` | MCP stdio サーバー |

---

## 起動

```bash
# CLI ループ（プロジェクトルートから実行）
./cfor_rs/target/release/cfor --db finance.sqlite3

# TUI モード
./cfor_rs/target/release/cfor --db finance.sqlite3 --tui

# 単発コマンド
./cfor_rs/target/release/cfor --db finance.sqlite3 /now

# MCP stdio サーバー
./cfor_rs/target/release/cfor-mcp --db finance.sqlite3
```

### Makefile から

`cfor_rs/` ディレクトリ内で実行する。デフォルトの DB は `../finance.sqlite3`（親ディレクトリ）。

```bash
cd cfor_rs
make run                             # CLI ループ
make tui                             # TUI モード
make mcp                             # MCP サーバー
make now                             # 資産状況を表示
make set-bank AMOUNT=3200000         # 銀行残高を更新
make set-securities AMOUNT=58800000  # 証券評価額を更新
make cash-set AMOUNT=42000           # 財布残高を補正
make ask QUESTION="今月の支出は？"    # LLM に問い合わせ
make smoke                           # 最小動作確認
make portable                        # dist/cfor_rs_portable に持ち運び用一式を作成
make portable-smoke                  # 持ち運び用一式だけでカードCSV import を確認
```

---

## コマンド一覧

Pythonオリジナル版と同じコマンドセット。

### 資産スナップショット

| コマンド | 説明 |
|---------|------|
| `/now` | 現在の資産状況を表示 |
| `/set-bank <amount>` | 銀行残高を更新 |
| `/set-securities <amount>` | 証券評価額を更新 |

### 財布

| コマンド | 説明 |
|---------|------|
| `/cash-set <amount>` | 財布残高を実測補正（支出ではない） |
| `/cash-in <amount> <memo>` | 財布に入金 |
| `/cash-out <amount> <memo>` | 財布から支出 |
| `/cash` | 財布の取引履歴を表示 |
| `/atm <amount> [memo]` | 銀行→財布へATM引き出し（総資産は変わらない） |
| `/transfer <from> <to> <amount> [memo]` | 振替を記録（総資産は変わらない） |

### クレカ

| コマンド | 説明 |
|---------|------|
| `/import-card [path]` | カードCSVを取り込み（省略時は `data/inbox/card/` を走査） |
| `/import [path]` | `/import-card` の別名 |
| `/card [this_month\|YYYY-MM]` | カード利用集計（`this_month` は支払月ベース） |

標準配置:

```text
cfor_rs/
├── finance_config.yaml
├── data/
│   └── inbox/
│       └── card/
│           └── 202605.csv
└── target/
    └── release/
        └── cfor
```

`/import-card` の引数を省略した場合、`finance_config.yaml` の `card_csv.default_inbox` を読み、相対パスは設定ファイルがあるディレクトリ基準で解決する。  
そのため `target/release/cfor` を直接起動しても、上位の `cfor_rs/finance_config.yaml` と `cfor_rs/data/inbox/card/` があれば取り込める。

持ち運び用ディレクトリを作る場合:

```bash
cd cfor_rs
make portable
```

生成物:

```text
cfor_rs/dist/cfor_rs_portable/
├── bin/
│   ├── cfor
│   └── cfor-mcp
├── finance_config.yaml
└── data/
    └── inbox/
        └── card/
```

このディレクトリを移動した後も、ディレクトリ直下から `./bin/cfor --db finance.sqlite3 /import-card` を実行すれば、同梱の `finance_config.yaml` を基準に `data/inbox/card/` を走査する。

### LLM 分析

| コマンド | 説明 |
|---------|------|
| `/ask <質問>` | 資産データをコンテキストに LM Studio へ問い合わせ |

---

## TUI キーバインド

| キー | 動作 |
|------|------|
| F1 | `/help` |
| F2 | `/now` |
| F3 | `/card` |
| F4 | `/cash` |
| F5 | `/atm 10000` |
| PageUp / PageDown | 出力ログをスクロール |
| F10 | 終了 |

---

## MCP サーバー

JSON-RPC 2.0 over stdio。プロトコルバージョン `2024-11-05`。

```bash
./cfor_rs/target/release/cfor-mcp --db finance.sqlite3
```

MCPクライアント設定例:

```json
{
  "mcpServers": {
    "my-cfo": {
      "command": "/Users/seijiro/Sync/sync_work/me/my_cfoR/cfor_rs/target/release/cfor-mcp",
      "args": ["--db", "/Users/seijiro/Sync/sync_work/me/my_cfoR/finance.sqlite3"]
    }
  }
}
```

公開ツール:

| MCP tool | 説明 |
|----------|------|
| `finance.now` | 現在の資産状況をJSONで返す |
| `finance.card_summary` | カード利用の月次集計 |
| `finance.wallet_summary` | 財布の月次支出集計 |
| `finance.recent_transfers` | 最近の振替一覧 |
| `finance.set_bank` | 銀行残高を更新 |
| `finance.set_securities` | 証券評価額を更新 |
| `finance.cash_set` | 財布残高を実測補正 |
| `finance.cash_in` | 財布へ入金 |
| `finance.cash_out` | 財布から支出 |
| `finance.transfer` | 振替を記録 |
| `finance.import_card` | クレカCSVを取り込み |
| `finance.build_context` | `/ask` 用の集計済みコンテキストを生成 |

MCP resource `finance://usage-guide` に呼び出し例と重要ルールを収録。旧URI `finance://usage-image` も互換対応。

---

## 総資産の定義

```
総資産 = 銀行残高 + 証券評価額 + 財布残高 − クレカ今月引き落とし額
```

ATM引き出し等の振替は支出でなく資産移動なので、総資産は変わらない。

---

## ディレクトリ構成

```
cfor_rs/
├── Cargo.toml
├── Makefile
├── README.md
└── src/
    ├── lib.rs                      # ライブラリルート（bin から参照）
    ├── main.rs                     # CLI / TUI エントリーポイント
    ├── bin/
    │   └── mcp.rs                  # MCP サーバーエントリーポイント
    ├── db.rs                       # SQLite 接続・スキーマ初期化
    ├── config.rs                   # finance_config.yaml 読み込み
    ├── display.rs                  # Unicode 表示幅計算・列整形
    ├── llm.rs                      # LM Studio HTTP クライアント
    ├── models.rs                   # データ型定義・金額フォーマット
    ├── error.rs                    # エラー型
    ├── commands.rs                 # コマンドパース・ディスパッチ
    ├── services/
    │   ├── snapshots.rs            # スナップショット CRUD
    │   ├── manual_snapshots.rs     # 手動更新ロジック
    │   ├── transfers.rs            # 振替ロジック
    │   ├── now.rs                  # 表示フォーマット
    │   └── ask_context.rs          # LLM 用コンテキスト構築
    ├── importers/
    │   └── credit_card_csv.rs      # CSV 自動検出・取り込み
    ├── tui/
    │   └── app.rs                  # ratatui TUI
    └── mcp/
        └── server.rs               # MCP JSON-RPC ハンドラー
```

---

## 主要依存クレート

| クレート | 用途 |
|---------|------|
| `rusqlite` (bundled) | SQLite（システム依存なし） |
| `ratatui` + `crossterm` | TUI |
| `reqwest` (blocking) | LM Studio HTTP |
| `serde` / `serde_json` / `serde_yaml` | シリアライズ |
| `encoding_rs` | CP932 / UTF-8 デコード |
| `sha2` + `hex` | CSVファイルハッシュ |
| `unicode-width` + `unicode-normalization` | 全角対応 |
| `clap` | CLI 引数パース |
| `chrono` | 日付処理 |
| `shlex` | コマンド文字列パース |
