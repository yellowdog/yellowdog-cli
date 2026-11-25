.DEFAULT_GOAL := no_op

SRC = yellowdog_cli/*.py yellowdog_cli/utils/*.py yellowdog_cli/utils/*/*.py yellowdog_cli/commander/*.py yellowdog_cli/mcp/*.py yellowdog_cli/nouns/*.py yellowdog_cli/spec_data/*.py
SCRIPTS = scripts/*.py
TESTS = tests/*.py conftest.py
MANIFEST = LICENSE README.md
BUILD_DIST = build dist yellowdog_cli.egg-info
PYCACHE = __pycache__ yellowdog_cli/__pycache__ yellowdog_cli/utils/__pycache__ yellowdog_cli/utils/*/__pycache__
# Every extra, for 'make install' and 'make update' alike: the dev extra's
# constraints (pyproject.toml) hold for both, or each would undo the other's
# versions
EXTRAS = dev,commander,mcp,jsonnet,cloudwizard,docs
TOC_BACKUP = README.md.* README_CLOUDWIZARD.md.* yellowdog_cli/commander/README.md.* yellowdog_cli/mcp/README.md.*

build: $(SRC) $(MANIFEST)
	uv build

clean:
	rm -rf $(BUILD_DIST) $(PYCACHE) $(TOC_BACKUP) sphinx/_build

install: build
	uv pip install -U -e ".[$(EXTRAS)]"

uninstall:
	uv pip uninstall yellowdog-cli

# scripts/pre-push, which refuses unsigned commits headed for 'main', as this
# clone's pre-push hook (pre-commit's own hook is 'pre-commit install')
pre_push_hook:
	ln -sf "$$(git rev-parse --show-toplevel)/scripts/pre-push" "$$(git rev-parse --git-path hooks)/pre-push"

format: $(SRC) $(TESTS) $(SCRIPTS)
	ruff check --fix $(SRC) $(TESTS) $(SCRIPTS)
	ruff format $(SRC) $(TESTS) $(SCRIPTS)

pypi_upload: clean build
	# '--repository yellowdog-cli' maps into the correct API token for yellowdog-cli uploads
	python -m twine upload --repository yellowdog-cli dist/*

pypi_test_upload: clean build
	python -m twine upload --repository yellowdog-testpypi dist/*

pypi_check: build
	twine check dist/*

toc_all: toc toc_docs toc_cloudwizard toc_commander toc_mcp toc_development

toc: README.md
	./gh-md-toc --insert --no-backup --skip-header README.md

# Each docs/ page with the table of contents markers (a one-table page has none)
toc_docs: docs/*.md
	for f in $$(grep -l '^<!--ts-->' docs/*.md); do ./gh-md-toc --insert --no-backup --skip-header $$f; done

toc_cloudwizard: README_CLOUDWIZARD.md
	./gh-md-toc --insert --no-backup --skip-header README_CLOUDWIZARD.md

toc_commander: yellowdog_cli/commander/README.md
	./gh-md-toc --insert --no-backup --skip-header yellowdog_cli/commander/README.md

toc_mcp: yellowdog_cli/mcp/README.md
	./gh-md-toc --insert --no-backup --skip-header yellowdog_cli/mcp/README.md

toc_development: DEVELOPMENT.md
	./gh-md-toc --insert --no-backup --skip-header DEVELOPMENT.md

schema_descriptions: docs/work-requirement-property-dictionary.md
	python3 scripts/extract_schema_descriptions.py > yellowdog_cli/spec_data/descriptions.json

test:
	pytest -v -n 8

# The documentation site (the 'docs' extra): the repository's Markdown as
# HTML in sphinx/_build/html, any warning failing the build; and its image
DOCS_VERSION = $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' yellowdog_cli/_version.py)
DOCS_IMAGE = yellowdogco/cli-docs

.PHONY: docs docs_linkcheck docs_build_image docs_publish_image

docs:
	sphinx-build -E -W --keep-going -c sphinx -b html . sphinx/_build/html

# Every external link the pages make, checked over the network (by hand before
# a release, never in CI, which would fail on another site's outage); the
# report is in sphinx/_build/linkcheck/output.txt
docs_linkcheck:
	sphinx-build -c sphinx -b linkcheck . sphinx/_build/linkcheck

docs_build_image: docs
	cd sphinx && docker build . -t $(DOCS_IMAGE):$(DOCS_VERSION) --platform linux/amd64

docs_publish_image: docs_build_image
	docker push $(DOCS_IMAGE):$(DOCS_VERSION)

# PYRIGHT_PYTHON=X.Y checks the code as that Python's (default: pyproject.toml's
# pythonVersion, the oldest supported), since a branch for a newer Python is
# unreachable to a check as the oldest
pyright:
	pyright $(if $(PYRIGHT_PYTHON),--pythonversion $(PYRIGHT_PYTHON)) $(SRC)

# The package's code complexity: McCabe complexity worst first, ruff's
# function-structure counts, and function lengths. A report, never a failure;
# 'make complexity ARGS="--threshold 20 --top 20"' to change what it lists
complexity:
	python scripts/complexity_report.py $(ARGS)

# Line and branch coverage of the unit tests: a summary per file, and the
# detail in htmlcov/index.html. Code run only in a subprocess is not counted
coverage:
	pytest -n auto --cov --cov-report=term --cov-report=html

tox:
	tox

# The live system tests' configuration, checked as a run loads it, with
# nothing remote: its summary and warnings, or every problem (exit 2)
live_config:
	python tests/live/check_config.py

update:
	uv pip install -U -e ".[$(EXTRAS)]"

no_op:
	# Available targets are: build, clean, docs, docs_linkcheck, format, install, test, tox, uninstall, update, pypi_upload, pypi_check
	# For releases, use: ./release.sh (or ./release.sh --release)
