.PHONY: help venv install test docs serve-docs build build-pypi publish-pypi gh-pages clean

help:
	@echo "Available targets:"
	@echo "  venv         Create Python virtual environment in .venv"
	@echo "  install      Install all dependencies into .venv"
	@echo "  test         Run all unit tests with pytest in .venv"
	@echo "  docs         Build documentation with mkdocs"
	@echo "  serve-docs   Serve documentation locally with mkdocs"
	@echo "  build        Build the package (wheel and sdist)"
	@echo "  build-pypi   Build the package for PyPI (wheel and sdist)"
	@echo "  publish-pypi Publish the package to PyPI"
	@echo "  gh-pages     Deploy documentation to GitHub Pages"
	@echo "  clean        Remove build, dist, and cache files"

venv:
	@test -d .venv || python3 -m venv .venv
	@. .venv/bin/activate && pip install --upgrade pip

install: venv
	@. .venv/bin/activate && pip install -e ".[dev]"

test: venv
	@. .venv/bin/activate && pytest --maxfail=3 --disable-warnings -v

docs: venv
	@. .venv/bin/activate && mkdocs build

serve-docs: venv
	@. .venv/bin/activate && mkdocs serve

build: venv
	@. .venv/bin/activate && python -m build

build-pypi: build

publish-pypi: build
	@. .venv/bin/activate && twine upload dist/*

gh-pages: docs
	@. .venv/bin/activate && mkdocs gh-deploy --force

clean:
	rm -rf .venv dist build *.egg-info .pytest_cache __pycache__ .mypy_cache site

