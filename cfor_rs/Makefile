CARGO  ?= cargo
DB     ?= ../finance.sqlite3
AMOUNT ?=
QUESTION ?= 今月ってカード使いすぎ？

BIN_DIR    = target/release
CLI_BIN    = $(BIN_DIR)/cfor
MCP_BIN    = $(BIN_DIR)/cfor-mcp
TUI_BIN    = $(BIN_DIR)/cfor-tui
SMOKE_DB   = /tmp/cfor_rs_smoke.sqlite3
DIST_DIR   ?= dist/cfor_rs_portable
DIST_CARD_DIR = $(DIST_DIR)/data/inbox/card
DIST_DB = $(DIST_DIR)/finance.sqlite3
DIST_SMOKE_DB = $(DIST_DIR)/portable-smoke.sqlite3

.PHONY: help build release portable portable-smoke run tui mcp now set-bank set-securities cash-set ask smoke clean-smoke clean-portable

help:
	@printf '%s\n' 'Targets:'
	@printf '%s\n' '  make build                           Debug ビルド'
	@printf '%s\n' '  make release                         Release ビルド'
	@printf '%s\n' '  make portable                        持ち運び用ディレクトリを dist/ に作成'
	@printf '%s\n' '  make portable-smoke                  持ち運び用ディレクトリ単体で import 確認'
	@printf '%s\n' '  make run                             CLI ループ起動'
	@printf '%s\n' '  make tui                             TUI モード起動'
	@printf '%s\n' '  make mcp                             MCP stdio サーバー起動'
	@printf '%s\n' '  make now                             現在の資産状況を表示'
	@printf '%s\n' '  make set-bank AMOUNT=3200000         銀行残高を更新'
	@printf '%s\n' '  make set-securities AMOUNT=58800000  証券評価額を更新'
	@printf '%s\n' '  make cash-set AMOUNT=42000           財布残高を補正'
	@printf '%s\n' '  make ask QUESTION=...                LM Studio に問い合わせ'
	@printf '%s\n' '  make smoke                           最小動作確認（temp DB）'

build:
	$(CARGO) build

release:
	$(CARGO) build --release

portable: release
	rm -rf $(DIST_DIR)
	install -d $(DIST_DIR) $(DIST_CARD_DIR)
	cp $(CLI_BIN) $(DIST_DIR)/
	cp $(TUI_BIN) $(DIST_DIR)/
	cp $(MCP_BIN) $(DIST_DIR)/
	cp finance_config.yaml $(DIST_DIR)/
	find data/inbox/card -maxdepth 1 -type f -name '*.csv' -exec cp {} $(DIST_CARD_DIR)/ \;
	touch $(DIST_CARD_DIR)/.gitkeep
	cd $(DIST_DIR) && ./cfor /now >/dev/null
	@printf '%s\n' 'Portable release created: $(DIST_DIR)'

portable-smoke: portable
	test -f $(DIST_DB)
	cd $(DIST_DIR) && ./cfor /now
	rm -f $(DIST_SMOKE_DB)
	cd $(DIST_DIR) && ./cfor --db portable-smoke.sqlite3 /import-card
	rm -f $(DIST_SMOKE_DB)

$(CLI_BIN): release

$(MCP_BIN): release

$(TUI_BIN): release

run: $(CLI_BIN)
	$(CLI_BIN) --db $(DB)

tui: $(TUI_BIN)
	$(TUI_BIN) --db $(DB)

mcp: $(MCP_BIN)
	$(MCP_BIN) --db $(DB)

now: $(CLI_BIN)
	$(CLI_BIN) --db $(DB) /now

set-bank: $(CLI_BIN)
	@test -n "$(AMOUNT)" || (printf '%s\n' 'AMOUNT is required. Example: make set-bank AMOUNT=3200000' && exit 1)
	$(CLI_BIN) --db $(DB) /set-bank $(AMOUNT)

set-securities: $(CLI_BIN)
	@test -n "$(AMOUNT)" || (printf '%s\n' 'AMOUNT is required. Example: make set-securities AMOUNT=58800000' && exit 1)
	$(CLI_BIN) --db $(DB) /set-securities $(AMOUNT)

cash-set: $(CLI_BIN)
	@test -n "$(AMOUNT)" || (printf '%s\n' 'AMOUNT is required. Example: make cash-set AMOUNT=42000' && exit 1)
	$(CLI_BIN) --db $(DB) /cash-set $(AMOUNT)

ask: $(CLI_BIN)
	$(CLI_BIN) --db $(DB) /ask "$(QUESTION)"

smoke: clean-smoke $(CLI_BIN)
	$(CLI_BIN) --db $(SMOKE_DB) /set-bank 3200000
	$(CLI_BIN) --db $(SMOKE_DB) /set-securities 58800000
	$(CLI_BIN) --db $(SMOKE_DB) /cash-set 42000
	$(CLI_BIN) --db $(SMOKE_DB) /now
	$(CLI_BIN) --db $(SMOKE_DB) /cash-in 5000 精算
	$(CLI_BIN) --db $(SMOKE_DB) /cash-out 1200 昼食
	$(CLI_BIN) --db $(SMOKE_DB) /atm 10000
	$(CLI_BIN) --db $(SMOKE_DB) /now

clean-smoke:
	rm -f $(SMOKE_DB)

clean-portable:
	rm -rf $(DIST_DIR)
