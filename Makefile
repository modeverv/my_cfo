PYTHON ?= python3
DB ?= finance.sqlite3
QUESTION ?= 今月ってカード使いすぎ？

.PHONY: help install init run tui mcp now set-bank set-securities cash-set ask compile test smoke clean-test-db

help:
	@printf '%s\n' 'Targets:'
	@printf '%s\n' '  make init                         Initialize SQLite DB'
	@printf '%s\n' '  make install                      Install dependencies'
	@printf '%s\n' '  make run                          Start CLI loop'
	@printf '%s\n' '  make tui                          Start TUI mode'
	@printf '%s\n' '  make mcp                          Start MCP stdio server'
	@printf '%s\n' '  make now                          Show current assets'
	@printf '%s\n' '  make set-bank AMOUNT=3200000       Set bank balance'
	@printf '%s\n' '  make set-securities AMOUNT=58800000 Set securities total'
	@printf '%s\n' '  make cash-set AMOUNT=42000         Set wallet balance'
	@printf '%s\n' '  make ask QUESTION=...              Ask LM Studio'
	@printf '%s\n' '  make test                         Run unit tests'
	@printf '%s\n' '  make smoke                         Run minimal verification with temp DB'

install:
	$(PYTHON) -m pip install -r requirements.txt
	chmod +x cfo

init:
	$(PYTHON) main.py --db $(DB) /now

run:
	$(PYTHON) main.py --db $(DB)

tui:
	$(PYTHON) main.py --db $(DB) --tui

mcp:
	$(PYTHON) -m finance_mcp.server --db $(DB)

now:
	$(PYTHON) main.py --db $(DB) /now

set-bank:
	@test -n "$(AMOUNT)" || (printf '%s\n' 'AMOUNT is required. Example: make set-bank AMOUNT=3200000' && exit 1)
	$(PYTHON) main.py --db $(DB) /set-bank $(AMOUNT)

set-securities:
	@test -n "$(AMOUNT)" || (printf '%s\n' 'AMOUNT is required. Example: make set-securities AMOUNT=58800000' && exit 1)
	$(PYTHON) main.py --db $(DB) /set-securities $(AMOUNT)

cash-set:
	@test -n "$(AMOUNT)" || (printf '%s\n' 'AMOUNT is required. Example: make cash-set AMOUNT=42000' && exit 1)
	$(PYTHON) main.py --db $(DB) /cash-set $(AMOUNT)

ask:
	$(PYTHON) main.py --db $(DB) /ask "$(QUESTION)"

compile:
	$(PYTHON) -m compileall main.py finance_core finance_mcp

test:
	$(PYTHON) -m unittest discover -s tests

smoke: clean-test-db
	$(PYTHON) main.py --db /tmp/my_cfo_make_smoke.sqlite3 /set-bank 3200000
	$(PYTHON) main.py --db /tmp/my_cfo_make_smoke.sqlite3 /set-securities 58800000
	$(PYTHON) main.py --db /tmp/my_cfo_make_smoke.sqlite3 /cash-set 42000
	$(PYTHON) main.py --db /tmp/my_cfo_make_smoke.sqlite3 /now

clean-test-db:
	rm -f /tmp/my_cfo_make_smoke.sqlite3
