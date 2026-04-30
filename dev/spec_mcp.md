# Personal Finance Console — MCP 実装メモ v0.1

> 目的は、LLM が既存の個人 CFO コアを **MCP 経由で安全に扱えるようにする** こと。  
> ここでは新しい業務ロジックを増やさず、既存の `finance_core` を薄く公開する。

---

## 1. 目的

このメモは、LLM から次の操作を **ツールとして** 呼べるようにするための仕様である。

```text
- 現在地の参照
- カード / 財布 / 振替の集計参照
- 銀行・証券・財布の手入力更新
- 財布の入出金
- 振替の記録
- クレカ CSV の取り込み
- LLM 向けコンテキスト生成
```

MCP では、LLM に SQL を直接触らせない。  
必ず `finance_core` の関数を経由する。

---

## 2. 既存コアとの対応関係

```text
現在地           → finance_core.services.now
スナップショット → finance_core.services.snapshots
手入力更新       → finance_core.services.manual_snapshots
振替             → finance_core.services.transfers
クレカ集計       → finance_core.services.ask_context
CSV 取り込み     → finance_core.importers.credit_card_csv
コマンド入口     → finance_core.services.commands
```

MCP はこの上に薄く乗せる。

---

## 3. 設計方針

### やること

```text
- 読み取り用ツールを分ける
- 更新用ツールを分ける
- import は明示的に実行する
- LLM 用コンテキストは集計済みデータだけ返す
- 振替と支出を混同しない
```

### やらないこと

```text
- 生の SQLite をそのまま公開しない
- LLM に任意 SQL を実行させない
- カテゴリ分類を勝手に増やさない
- 自動取得やスクレイピングを追加しない
```

---

## 4. MCP ツール一覧

### 4.1 読み取り系

#### `finance.now`
現在の資産状況を返す。

```text
入力: なし
出力: 総資産 / 銀行残高 / 証券評価額 / 財布残高 / カード利用
```

例。

```json
{
  "total_assets": 61812000,
  "bank_total": 3200000,
  "securities_total": 58800000,
  "wallet_total": 42000,
  "credit_card_unbilled": 230000
}
```

---

#### `finance.card_summary`
カード利用の月次集計を返す。

```text
入力:
- month: "this_month" または "YYYY-MM"

出力:
- 合計
- 加盟店別集計
- 高額決済一覧
```

例。

```json
{
  "month": "2026-04",
  "total": 230000,
  "by_merchant": [
    {"merchant": "Amazon", "total": 120000}
  ],
  "large_transactions": [
    {"used_on": "2026-04-03", "merchant": "Amazon", "amount": 120000}
  ]
}
```

---

#### `finance.wallet_summary`
財布の月次集計を返す。

```text
入力:
- month: "this_month" または "YYYY-MM"

出力:
- 現金支出合計
- 高額現金支出一覧
```

---

#### `finance.recent_transfers`
最近の振替一覧を返す。

```text
入力:
- limit: int (default 10)

出力:
- occurred_on
- from_account
- to_account
- amount
- memo
```

---

### 4.2 更新系

#### `finance.set_bank`
銀行残高を更新する。

```text
入力:
- amount: int
```

例。

```json
{"amount": 3200000}
```

戻り値。

```json
{
  "ok": true,
  "snapshot": { ... }
}
```

---

#### `finance.set_securities`
証券評価額を更新する。

```text
入力:
- amount: int
```

---

#### `finance.cash_set`
財布残高を実測値で補正する。

```text
入力:
- amount: int
```

注意。

```text
- これは補正
- 現金支出ではない
```

---

#### `finance.cash_in`
財布に現金を入れる。

```text
入力:
- amount: int
- memo: str
```

---

#### `finance.cash_out`
財布から現金を使う。

```text
入力:
- amount: int
- memo: str
```

注意。

```text
- 財布残高を下回る場合はエラー
- これは支出
```

---

#### `finance.transfer`
振替を記録する。

```text
入力:
- from_account: "bank" | "wallet" | "securities" | "card"
- to_account:   "bank" | "wallet" | "securities" | "card"
- amount: int
- memo: str | null
```

注意。

```text
- 振替は支出ではない
- bank → wallet は wallet_transactions にも記録する
- wallet → bank は財布残高不足ならエラー
```

---

### 4.3 取り込み系

#### `finance.import_card`
クレカ CSV を取り込む。

```text
入力:
- path: str (省略可)
```

戻り値。

```json
{
  "imported": 82,
  "skipped": 3,
  "files": 1,
  "errors": []
}
```

注意。

```text
- 同一ファイルの重複 import は避ける
- 行単位の重複もスキップする

呼び出し例:

1) 引数無し: デフォルトの inbox を走査（`/import` と同等）

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {"name": "finance.import_card", "arguments": {}}
}
```

2) ファイル指定:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {"name": "finance.import_card", "arguments": {"path": "/path/to/202604.csv"}}
}
```
```

---

### 4.4 LLM コンテキスト系

#### `finance.build_context`
`/ask` 用の集計済みコンテキストを返す。

```text
入力:
- question: str

出力:
- 現在の資産状況
- 今月のカード利用
- 今月の現金支出
- 最近の振替
```

重要。

```text
- 生データを全部返さない
- 推測材料は集計済みに限定する
- 振替と支出を分けて書く
```

---

## 5. 使用イメージ

### 5.1 読み取り

```text
LLM → finance.now()
LLM → finance.card_summary(month="this_month")
LLM → finance.wallet_summary(month="this_month")
```

### 5.2 更新

```text
LLM → finance.set_bank(amount=3200000)
LLM → finance.set_securities(amount=58800000)
LLM → finance.cash_set(amount=42000)
LLM → finance.transfer(from_account="bank", to_account="wallet", amount=30000, memo="ATM")
```

### 5.3 相談

```text
LLM → finance.build_context(question="今月ってカード使いすぎ？")
LLM → そのコンテキストを使って回答生成
```

---

## 6. エラー設計

### 返し方

```text
- 入力不正はエラーで返す
- 0 未満の金額は拒否する
- 未知の口座名は拒否する
- 財布残高不足は拒否する
```

### 例

```json
{
  "ok": false,
  "error": "財布残高が不足しています (現在: 1,000円)"
}
```

---

## 7. LLM から見た注意点

```text
- 支出と振替を混同しない
- 銀行→財布は支出ではない
- カード利用は支払月で集計する
- 相談時は集計済みデータのみで判断する
```

---

## 8. 実装の最小順序

### Phase 1

```text
- finance.now
- finance.set_bank
- finance.set_securities
- finance.cash_set
```

### Phase 2

```text
- finance.cash_in
- finance.cash_out
- finance.transfer
```

### Phase 3

```text
- finance.import_card
- finance.card_summary
- finance.wallet_summary
```

### Phase 4

```text
- finance.build_context
- /ask から MCP 経由の分析へ接続
```

---

## 9. 実装メモ

```text
- MCP ツールは finance_core の wrapper として実装する
- DB スキーマは直接公開しない
- 返り値は dict / JSON に揃える
- 画面表示用の整形は UI 側でやる
```

---

## 10. 一言

```text
LLM に何でもやらせるのではなく、
安全な道具を渡して扱わせる。
```

