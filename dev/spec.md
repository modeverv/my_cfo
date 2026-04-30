# Personal Finance Console — 設計・実装メモ v0.2

> 自分用 MoneyForward 代替。  
> 初期MVPでは自動取得を捨てる。銀行残高・証券評価額は手入力、クレカ利用履歴はCSV取り込み、物理財布はIN/OUTと振替で管理する。

---

## 1. 目的

このアプリは「完璧な家計簿」ではなく、**個人財務の現在地を素早く見るためのTUI**である。

初期MVPで見たいものは次の4つ。

```text
1. 銀行残高の現在地
2. 証券口座評価額の現在地
3. 今月のクレカ利用額と内訳
4. 物理財布の残高・現金支出
```

さらに重要な概念として、**振替**を明示的に扱う。

```text
銀行 → 財布
これは支出ではない。
資産の置き場所が変わっただけ。
```

総資産は次の式で見る。

```text
銀行残高
+ 証券評価額
+ 物理財布残高
- クレカ未払い/今月利用額
= 現在の実質純資産
```

---

## 2. 初期MVPのスコープ

### やること

```text
銀行残高      → MoneyForward無料版などを見て手入力
証券評価額    → SBI証券ポートフォリオを見て手入力
クレカ明細    → CSV取り込み
財布残高      → 手入力・現金IN/OUTで管理
振替          → 銀行→財布などを明示的に記録
/ask          → 集計済みデータをLM Studioに渡して分析
```

### 初期MVPではやらないこと

```text
銀行CSV自動取得
証券CSV自動取得
Seleniumスクレイピング
Amazon明細取得
細かすぎるカテゴリ分類
複式簿記レベルの会計処理
```

---

## 3. 操作イメージ

```text
fin> /set-bank 3200000
銀行残高を 3,200,000円 に更新しました

fin> /set-securities 58800000
証券評価額を 58,800,000円 に更新しました

fin> /cash-set 42000
財布残高を 42,000円 に設定しました

fin> /transfer bank wallet 30000
銀行から財布へ 30,000円を振替として記録しました

fin> /cash-out 1200 昼食
財布から 1,200円 支出しました: 昼食

fin> /import-card data/inbox/card/rakuten_2026-04.csv
82件のカード明細を取り込みました

fin> /now
総資産:        61,812,000円
銀行残高:       3,200,000円
証券評価額:    58,800,000円
財布残高:          42,000円
カード利用:      -230,000円

fin> /ask 今月ってカード使いすぎ？何に多く使ってる？
```

---

## 4. 全体構成

```text
personal_finance_console/
├── fin_console/
│   ├── app.py
│   ├── commands/
│   │   ├── now.py
│   │   ├── card.py
│   │   ├── wallet.py
│   │   ├── transfer.py
│   │   ├── snapshot.py
│   │   ├── ask.py
│   │   └── import_cmd.py
│   └── widgets/
│       ├── main_pane.py
│       ├── side_pane.py
│       └── input_bar.py
│
├── finance_core/
│   ├── config.py
│   ├── db.py
│   ├── importers/
│   │   ├── base.py
│   │   └── credit_card_csv.py
│   ├── services/
│   │   ├── snapshots.py
│   │   ├── wallet.py
│   │   ├── transfers.py
│   │   ├── cards.py
│   │   ├── assets.py
│   │   └── ask_context.py
│   └── llm.py
│
├── scripts/
│   └── import_inbox.py
│
├── migrations/
│   └── 001_init.sql
│
├── data/
│   ├── inbox/card/
│   ├── archive/
│   └── failed/
│
├── finance_config.yaml
└── README.md
```

---

## 5. DB設計

PostgreSQL想定。SQLiteでも実装可能だが、ZK側と揃えるならPostgreSQLでよい。

---

### 5.1 `accounts`

銀行・証券・財布・カードをすべて「口座」として扱う。

```sql
CREATE TABLE accounts (
  id SERIAL PRIMARY KEY,
  account_key TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('bank', 'securities', 'wallet', 'credit_card')),
  institution TEXT,
  currency TEXT DEFAULT 'JPY',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

初期データ例。

```sql
INSERT INTO accounts (account_key, name, type, institution) VALUES
  ('bank_main', 'メイン銀行', 'bank', 'MoneyForward手入力'),
  ('sbi_main', 'SBI証券', 'securities', 'SBI証券'),
  ('wallet_main', '物理財布', 'wallet', 'cash'),
  ('card_main', 'メインカード', 'credit_card', 'manual_csv');
```

---

### 5.2 `asset_snapshots`

銀行残高・証券評価額・財布残高などの「現在地」を記録する。

```sql
CREATE TABLE asset_snapshots (
  id SERIAL PRIMARY KEY,
  as_of_date DATE NOT NULL,
  bank_total NUMERIC NOT NULL DEFAULT 0,
  securities_total NUMERIC NOT NULL DEFAULT 0,
  wallet_total NUMERIC NOT NULL DEFAULT 0,
  credit_card_unbilled NUMERIC NOT NULL DEFAULT 0,
  total_assets NUMERIC NOT NULL DEFAULT 0,
  memo TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_asset_snapshots_date ON asset_snapshots(as_of_date DESC);
```

`total_assets` は次で計算する。

```text
bank_total + securities_total + wallet_total - credit_card_unbilled
```

---

### 5.3 `wallet_transactions`

物理財布の現金IN/OUTを記録する。

```sql
CREATE TABLE wallet_transactions (
  id SERIAL PRIMARY KEY,
  occurred_on DATE NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('in', 'out', 'set')),
  amount NUMERIC NOT NULL,
  description TEXT,
  category TEXT,
  related_transfer_id INT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_wallet_transactions_date ON wallet_transactions(occurred_on DESC);
```

意味。

```text
in   = 財布に現金が入った
out  = 財布から現金を使った
set  = 財布残高を実測値で補正した
```

---

### 5.4 `transfers`

資産の置き場所が変わっただけの移動を記録する。

```sql
CREATE TABLE transfers (
  id SERIAL PRIMARY KEY,
  occurred_on DATE NOT NULL,
  from_account_id INT REFERENCES accounts(id),
  to_account_id INT REFERENCES accounts(id),
  amount NUMERIC NOT NULL,
  memo TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_transfers_date ON transfers(occurred_on DESC);
```

例。

```text
銀行 → 財布 30,000円
証券 → 銀行 100,000円
銀行 → 証券 200,000円
```

重要:

```text
transferは支出でも収入でもない。
総資産計算では相殺される。
```

---

### 5.5 `card_transactions`

クレカ利用履歴。

```sql
CREATE TABLE card_transactions (
  id SERIAL PRIMARY KEY,
  account_id INT REFERENCES accounts(id),
  used_on DATE NOT NULL,
  posted_on DATE,
  merchant TEXT NOT NULL,
  description TEXT,
  amount NUMERIC NOT NULL,
  category TEXT,
  raw_category TEXT,
  payment_month TEXT,
  source_import_id INT,
  raw_json JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_card_transactions_used_on ON card_transactions(used_on DESC);
CREATE INDEX idx_card_transactions_payment_month ON card_transactions(payment_month);
CREATE INDEX idx_card_transactions_merchant ON card_transactions(merchant);
```

---

### 5.6 `imports`

CSV二重取り込み防止。

```sql
CREATE TABLE imports (
  id SERIAL PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_name TEXT,
  file_path TEXT NOT NULL,
  file_hash TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT,
  imported_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 6. コマンド設計

### 6.1 現在地

```text
/now
```

最新の `asset_snapshots` を表示する。

---

### 6.2 手入力スナップショット

```text
/set-bank <amount>
/set-securities <amount>
/cash-set <amount>
```

それぞれ現在地を更新する。

実装方針:

```text
最新snapshotを取得
指定項目だけ更新
total_assetsを再計算
新しいasset_snapshots行としてINSERT
```

更新履歴を残すため、既存行をUPDATEしない。

---

### 6.3 財布操作

```text
/cash-in <amount> <memo>
/cash-out <amount> <memo>
/cash-set <amount>
/cash
```

例。

```text
/cash-out 1200 昼食
/cash-in 5000 立替精算
/cash-set 42000
```

`/cash-set` は実測補正。

---

### 6.4 振替

```text
/transfer <from> <to> <amount> [memo]
```

例。

```text
/transfer bank wallet 30000 ATM引き出し
/transfer bank securities 200000 NISA積立
/transfer securities bank 100000 分配金移動
```

alias。

```text
bank       = bank_main
wallet     = wallet_main
securities = sbi_main
card       = card_main
```

銀行→財布の場合は、同時に `wallet_transactions` に `direction='in'` を作る。

---

### 6.5 クレカ

```text
/import-card <path>
/card this_month
/card 2026-04
/card merchants
/card categories
```

---

### 6.6 LLM分析

```text
/ask <text>
```

例。

```text
/ask 今月ってカード使いすぎ？何に多く使ってる？
/ask 今の資産状況は生活費に対して安全？
/ask 財布支出を含めて今月の変動費はどう？
```

---

## 7. サービス設計

### 7.1 snapshot更新

```python
def get_latest_snapshot(conn) -> dict:
    ...


def insert_snapshot(conn, bank_total=None, securities_total=None, wallet_total=None,
                    credit_card_unbilled=None, memo=None) -> dict:
    latest = get_latest_snapshot(conn) or defaults

    new = latest.copy()
    if bank_total is not None:
        new['bank_total'] = bank_total
    if securities_total is not None:
        new['securities_total'] = securities_total
    if wallet_total is not None:
        new['wallet_total'] = wallet_total
    if credit_card_unbilled is not None:
        new['credit_card_unbilled'] = credit_card_unbilled

    new['total_assets'] = (
        new['bank_total'] + new['securities_total'] + new['wallet_total']
        - new['credit_card_unbilled']
    )

    INSERT INTO asset_snapshots ...
    return new
```

---

### 7.2 財布残高計算

初期MVPでは `asset_snapshots.wallet_total` を正とする。  
`wallet_transactions` は履歴・内訳用。

```python
def cash_out(conn, amount, memo):
    latest = get_latest_snapshot(conn)
    new_wallet = latest['wallet_total'] - amount
    INSERT wallet_transactions(direction='out')
    insert_snapshot(wallet_total=new_wallet, memo=f"cash-out: {memo}")
```

```python
def cash_in(conn, amount, memo):
    latest = get_latest_snapshot(conn)
    new_wallet = latest['wallet_total'] + amount
    INSERT wallet_transactions(direction='in')
    insert_snapshot(wallet_total=new_wallet, memo=f"cash-in: {memo}")
```

---

### 7.3 振替処理

```python
def transfer(conn, from_key, to_key, amount, memo):
    from_account = resolve_account(from_key)
    to_account = resolve_account(to_key)

    INSERT INTO transfers(...)

    if from=bank and to=wallet:
        wallet += amount
        bank -= amount
        INSERT wallet_transactions(direction='in', related_transfer_id=transfer_id)
        insert_snapshot(bank_total=new_bank, wallet_total=new_wallet)

    elif from=wallet and to=bank:
        wallet -= amount
        bank += amount
        INSERT wallet_transactions(direction='out', related_transfer_id=transfer_id)
        insert_snapshot(bank_total=new_bank, wallet_total=new_wallet)

    elif from=bank and to=securities:
        bank -= amount
        securities += amount
        insert_snapshot(bank_total=new_bank, securities_total=new_sec)

    else:
        # MVPでは未対応でもよい
```

注意:

```text
証券評価額は市場変動で増減するため、transferで増やした値は暫定。
実際の評価額は /set-securities で後から上書きする。
```

---

### 7.4 クレカ未払い額

MVPでは今月のカード利用額を `credit_card_unbilled` として扱う。

```python
def refresh_card_unbilled(conn, month):
    total = SUM(card_transactions.amount WHERE payment_month = month)
    insert_snapshot(credit_card_unbilled=total, memo=f"card refresh {month}")
```

---

## 8. `/ask` コンテキスト

LLMには生データを全部渡さず、集計結果だけ渡す。

```python
def build_finance_context(conn, question: str) -> str:
    now = get_latest_snapshot(conn)
    card_this = get_card_month_summary(conn, current_month())
    card_prev = get_card_month_summary(conn, previous_month())
    wallet = get_wallet_month_summary(conn, current_month())
    transfers = get_recent_transfers(conn, limit=10)

    return f"""
## 現在の資産状況
総資産: {now['total_assets']}円
銀行残高: {now['bank_total']}円
証券評価額: {now['securities_total']}円
財布残高: {now['wallet_total']}円
カード未払い/今月利用: {now['credit_card_unbilled']}円

## 今月のカード利用
合計: {card_this['total']}円
カテゴリ別: {card_this['by_category']}
加盟店別: {card_this['by_merchant']}
高額決済: {card_this['large_transactions']}

## 前月比較
前月カード合計: {card_prev['total']}円
差額: {card_this['total'] - card_prev['total']}円

## 今月の現金支出
財布支出合計: {wallet['cash_out_total']}円
主な現金支出: {wallet['large_cash_out']}

## 最近の振替
{transfers}
"""
```

プロンプト。

```python
def build_ask_prompt(context: str, question: str) -> str:
    return f"""
あなたは個人の財務管理を補助するアシスタントです。
以下のデータだけを根拠に回答してください。
推測する場合は、推測であることを明示してください。

{context}

---
質問: {question}

回答方針:
- まず結論を短く述べる
- 数値根拠を出す
- 支出・振替・資産変動を混同しない
- 増加要因・注意点を箇条書きにする
- 不明な点は不明と言う
"""
```

---

## 9. TUIレイアウト

```text
┌─ Finance Console ────────────────────────────────────────┐
│ as_of: 2026-04-30 | total: 61.8M | card: 230K | wallet:42K │
├──────────────────────────┬───────────────────────────────┤
│ Main                     │ Side                          │
│ /now, /card, /ask結果     │ 最近の支出・振替・高額決済      │
│                          │                               │
├──────────────────────────┴───────────────────────────────┤
│ fin> _                                                    │
├───────────────────────────────────────────────────────────┤
│ F1Help F2Now F3Card F4Cash F5Transfer F6Ask F10Quit       │
└───────────────────────────────────────────────────────────┘
```

---

## 10. 実装フェーズ

### Phase 1: DB + 手入力snapshot

- [ ] `migrations/001_init.sql`
- [ ] `finance_config.yaml`
- [ ] `finance_core/db.py`
- [ ] `finance_core/services/snapshots.py`
- [ ] CLIで `/set-bank`, `/set-securities`, `/cash-set`, `/now` 相当の関数確認

完了条件:

```text
銀行残高・証券評価額・財布残高を手入力し、/now 相当のサマリが出る
```

---

### Phase 2: 財布・振替

- [ ] `wallet_transactions`
- [ ] `transfers`
- [ ] `/cash-in`
- [ ] `/cash-out`
- [ ] `/transfer bank wallet amount`
- [ ] `/cash`

完了条件:

```text
銀行→財布の振替が支出として扱われず、総資産が変わらない
財布からのcash-outでは総資産が減る
```

---

### Phase 3: クレカCSV取り込み

- [ ] `imports`
- [ ] `credit_card_csv.py`
- [ ] `/import-card`
- [ ] `/card this_month`
- [ ] `refresh_card_unbilled()`

完了条件:

```text
CSVを取り込み、今月のカード利用額が /now に反映される
```

---

### Phase 4: TUI

- [ ] `fin_console/app.py`
- [ ] `/now`
- [ ] `/card this_month`
- [ ] `/cash`
- [ ] `/transfer`
- [ ] `/import-card`
- [ ] `?`

完了条件:

```text
TUIから主要操作ができる
```

---

### Phase 5: `/ask`

- [ ] `finance_core/llm.py`
- [ ] `build_finance_context()`
- [ ] `/ask`

完了条件:

```text
/ask 今月ってカード使いすぎ？
に対して、カード・財布・振替を区別して回答する
```

---

### Phase 6: 後回し拡張

- [ ] 銀行CSV取り込み
- [ ] 証券CSV取り込み
- [ ] Selenium半自動取得
- [ ] Amazon明細取り込み
- [ ] 配当・分配金管理
- [ ] NISA成長投資枠・積立枠の管理

---

## 11. LLM実装エージェントへの指示テンプレート

```text
以下の設計メモに従って、Phase 1だけ実装してください。
一気に全Phaseを実装しないでください。

制約:
- DBスキーマとsnapshot更新ロジックを優先
- まずTUIは作らない
- 手入力で /now 相当が出るところまで
- 既存設計を勝手に拡張しない
- 完了条件を満たしたか最後にチェックリストで報告する

対象ファイル:
#file:personal_finance_console_implementation_notes.md
```

---

## 12. MVP完成イメージ

```text
fin> /set-bank 3200000
fin> /set-securities 58800000
fin> /cash-set 42000
fin> /import-card data/inbox/card/rakuten_2026-04.csv

fin> /now
総資産:        61,812,000円
銀行残高:       3,200,000円
証券評価額:    58,800,000円
財布残高:          42,000円
カード利用:      -230,000円

fin> /transfer bank wallet 30000 ATM
銀行→財布 30,000円を振替しました
総資産は変わりません

fin> /cash-out 1200 昼食
財布から 1,200円支出しました
総資産が 1,200円減りました

fin> /ask 今月ってカード使いすぎ？何に多く使ってる？
カード利用は先月比で増えています。主因はAmazonと車関連です。
ただし銀行→財布の30,000円は振替なので支出には含めません。
```

---

## 13. 一言で言うと

```text
銀行・証券は手入力でよい。
カードはCSVでよい。
財布はIN/OUTと振替でよい。

重要なのは、支出と振替を混同せず、
今の資産現在地をTUIで即座に見られること。
```

