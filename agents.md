# AGENTS.md — Personal Finance Console

このドキュメントは、LLM（Codex / GPT / Claude など）が本プロジェクトを安全かつ段階的に実装するためのガイドラインである。

仕様は`dev/spec.md`に配置している。
htmlでのuiデモは`dev/demo.html`に配置している

---

## 0. 基本方針

```text
・段階的に実装する（Phaseごと）
・既存設計を勝手に拡張しない
・仕様を「推測」しない
・動く最小構成を優先する
・人間レビュー前提で進める
```

NG例:

```text
・全部まとめて実装する
・未定義機能を勝手に追加
・複雑な設計に変える
```

---

## 1. 技術スタック

```text
言語: Python 3.11+
DB: SQLite3（標準ライブラリ）
UI: CLI（最初はprintベース）
LLM: LM Studio互換HTTP API（後段）
```

制約:

```text
・外部依存は最小限
・ORM禁止（sqlite3直書き）
・まずは単一ファイルでもOK
```

---

## 2. ドメイン理解（最重要）

### 2.1 総資産の定義

```text
総資産 = 銀行 + 証券 + 財布 - カード利用
```

### 2.2 振替（transfer）

```text
銀行 → 財布
これは支出ではない
```

```text
支出 = 資産が減る
振替 = 資産の場所が変わるだけ
```

LLMはここを間違えやすいので注意。

---

## 3. データモデル（確定仕様）

### asset_snapshots

```sql
CREATE TABLE asset_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  bank_total INTEGER NOT NULL DEFAULT 0,
  securities_total INTEGER NOT NULL DEFAULT 0,
  wallet_total INTEGER NOT NULL DEFAULT 0,
  credit_card_unbilled INTEGER NOT NULL DEFAULT 0,
  total_assets INTEGER NOT NULL DEFAULT 0,
  memo TEXT
);
```

### wallet_transactions

```sql
CREATE TABLE wallet_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_on TEXT NOT NULL,
  direction TEXT NOT NULL,
  amount INTEGER NOT NULL,
  description TEXT
);
```

### transfers

```sql
CREATE TABLE transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_on TEXT NOT NULL,
  from_account TEXT NOT NULL,
  to_account TEXT NOT NULL,
  amount INTEGER NOT NULL,
  memo TEXT
);
```

### card_transactions

```sql
CREATE TABLE card_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  used_on TEXT NOT NULL,
  merchant TEXT NOT NULL,
  amount INTEGER NOT NULL,
  payment_month TEXT
);
```

---

## 4. 実装フェーズ

### Phase 1（最優先）

```text
・DB初期化
・set-bank
・set-securities
・cash-set
・/now 表示
```

制約:

```text
・transfer禁止
・card禁止
・TUI不要
```

完了条件:

```text
数値を入力 → 総資産が正しく計算される
```

---

### Phase 2

```text
・cash-in
・cash-out
・transfer（bank ↔ wallet のみ）
```

重要:

```text
transferは支出に含めない
```

---

### Phase 3

```text
・card CSV import
・/card this_month
・/card merchants
```

制約:

```text
・分類しない
・category列は使わない
```

---

### Phase 4

```text
・簡易CLIループ
・コマンドパーサ
```

---

### Phase 5

```text
・/ask
・LM Studio連携
```

---

## 5. コマンド仕様

```text
/now
/set-bank 3200000
/set-securities 58800000
/cash-set 42000
/cash-in 5000 メモ
/cash-out 1200 昼食
/transfer bank wallet 30000 ATM
/import-card path
/card this_month
/ask 質問
```

---

## 6. 実装ルール

```text
・関数は小さく
・副作用は明示
・printで確認できる状態にする
・例外は握りつぶさない
```

---

## 7. 禁止事項

```text
・勝手にORM導入
・勝手にWeb化
・勝手に非同期化
・勝手に設計変更
```

---

## 8. 出力フォーマット

LLMは以下を必ず出力する:

```text
1. 変更ファイル一覧
2. 実装コード
3. 実行手順
4. テスト方法
```

---

## 9. テスト指針

```text
・数値計算が正しいか
・transferで総資産が変わらないか
・cash-outで総資産が減るか
```

---

## 10. 一言

```text
これは家計簿ではない
これは個人CFOコンソールである
```

