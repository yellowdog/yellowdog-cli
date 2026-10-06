.DEFAULT_GOAL := no_op

SRC = yellowdog_cli/*.py yellowdog_cli/utils/*.py yellowdog_cli/utils/*/*.py yellowdog_cli/commander/*.py yellowdog_cli/mcp/*.py yellowdog_cli/spec_data/*.py
SCRIPTS = scripts/*.py
TESTS = tests/*.py conftest.py
MANIFEST = LICENSE README.md
BUILD_DIST = build dist yellowdog_cli.egg-info
PYCACHE = __pycache__ yellowdog_cli/__pycache__ yellowdog_cli/utils/__pycache__ yellowdog_cli/utils/*/__pycache__
TOC_BACKUP = README.md.* README_CLOUDWIZARD.md.* yellowdog_cli/commander/README.md.* yellowdog_cli/mcp/README.md.*

build: $(SRC) $(MANIFEST)
	uv build

clean:
	rm -rf $(BUILD_DIST) $(PYCACHE) $(TOC_BACKUP)

install: build
	uv pip install -U -e ".[commander,mcp,jsonnet,cloudwizard]"

uninstall:
	uv pip uninstall yellowdog-cli

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

toc_all: toc toc_cloudwizard toc_commander toc_mcp

toc: README.md
	./gh-md-toc --insert --skip-header README.md

toc_cloudwizard: README_CLOUDWIZARD.md
	./gh-md-toc --insert --skip-header README_CLOUDWIZARD.md

toc_commander: yellowdog_cli/commander/README.md
	./gh-md-toc --insert --skip-header yellowdog_cli/commander/README.md

toc_mcp: yellowdog_cli/mcp/README.md
	./gh-md-toc --insert --skip-header yellowdog_cli/mcp/README.md

schema_descriptions: README.md
	python3 scripts/extract_schema_descriptions.py > yellowdog_cli/spec_data/descriptions.json

test:
	pytest -v

pyright:
	pyright $(SRC)

tox:
	tox

update:
	uv pip install -U -e ".[dev,commander,mcp,jsonnet,cloudwizard]"

no_op:
	# Available targets are: build, clean, format, install, test, tox, uninstall, update, pypi_upload, pypi_check
	# For releases, use: ./release.sh (or ./release.sh --release)
