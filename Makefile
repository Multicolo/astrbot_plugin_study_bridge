# 学习桥梁 · AstrBot 插件 Makefile
#
# 依赖：
#   - Python 3.12+（AstrBot 4.24.2+ 要求 >=3.12）
#   - Node.js 20+（只在构建前端时需要）
#   - pnpm 或 npm（优先 pnpm）
#
# 若 node 不在 PATH，可显式传入：
#   make build NODE_BIN="C:/path/to/node.exe" PNPM_BIN="C:/path/to/pnpm.mjs"

PY ?= $(shell python -c "import sys;print(sys.executable)" 2>/dev/null)
ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
else
PY := .venv/bin/python
endif

NODE_BIN ?= node
PNPM_BIN ?= pnpm
NPM_BIN  ?= npm

# pnpm 作为 .mjs 脚本调用时的前缀；若系统里直接有 pnpm 可执行文件则可留空
PNPM_CMD = $(NODE_BIN) $(PNPM_BIN)

.PHONY: help venv install dev build test test-cov e2e lint format package clean run-standalone selfcheck

help:
	@echo "make venv        创建 .venv 并安装后端依赖"
	@echo "make install     安装后端 + 前端依赖"
	@echo "make dev         启动独立调试服务（不依赖 AstrBot，端口 6188）"
	@echo "make build       构建前端到 web/"
	@echo "make test        跑后端 pytest"
	@echo "make test-cov    跑后端 pytest 并输出覆盖率"
	@echo "make e2e         跑 Playwright 前端 E2E（需先 make build）"
	@echo "make lint        静态检查（python -m compileall + 关键字 grep）"
	@echo "make package     打插件 zip（用于上架/手动安装）"
	@echo "make selfcheck   插件自检（无需 AstrBot）"

venv:
	python -m venv .venv
	$(PY) -m pip install -U pip

install: venv
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install pytest pytest-asyncio pytest-cov
	cd frontend && $(PNPM_CMD) install

dev:
	$(PY) -m core.standalone

build:
	cd frontend && $(PNPM_CMD) run build

test:
	$(PY) -m pytest -q

test-cov:
	$(PY) -m pytest -q --cov=core --cov=adapters --cov-report=term-missing --cov-report=xml

e2e: build
	cd frontend && $(PNPM_CMD) run test:e2e

lint:
	$(PY) -m compileall -q core adapters main.py
	$(PY) scripts/lint_secrets.py

package:
	$(PY) scripts/package_plugin.py

selfcheck:
	$(PY) scripts/selfcheck.py

run-standalone:
	$(PY) -m core.standalone

clean:
	rm -rf .pytest_cache .coverage htmlcov coverage.xml web/*.map build dist *.zip
	rm -rf frontend/node_modules frontend/dist
