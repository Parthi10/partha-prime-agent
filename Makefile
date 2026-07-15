.PHONY: install lint typecheck test docker-config

install:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

lint:
	ruff check .

format:
	ruff format .

typecheck:
	pyright

test:
	pytest

docker-config:
	docker compose config
