PYTHON ?= python3.11
VENV := .venv
VENV_PY := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

.PHONY: setup test

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install -U pip
	$(VENV_PIP) install -e ".[dev]"

test:
	$(VENV_PY) -m pytest -q
