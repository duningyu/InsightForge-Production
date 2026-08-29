.PHONY: install dev test run mcp compile clean

install:
	python -m pip install -e ".[dev]"

dev:
	uvicorn app.main:app --reload

test:
	pytest -q

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

mcp:
	python -m app.mcp_server

compile:
	python -m compileall -q app

clean:
	rm -rf .pytest_cache app/__pycache__ app/services/__pycache__ tests/__pycache__ data/*.sqlite3
