.PHONY: help commit check_venv
REQUIREMENT_SOURCE_FILES := $(shell ls requirements*.in)
REQUIREMENT_FILES := $(REQUIREMENT_SOURCE_FILES:.in=.txt)

gitrev := $(shell git rev-parse --short=10 HEAD)
VENV_NAME := venv
now := $(shell date --utc +%Y%m%dT%H%MZ)
github3_version:=1.1.0-$(now)-$(gitrev)
image_to_use := offboard-slim

.DEFAULT: help


help:
	@echo "Makefile targets:"
	@echo "	help 	this message"
	@echo "	install	setup venv"
	@echo "	commit	ensure all derived files up to date"
	@false

# set up dev environment
check_venv:
ifeq ($(VIRTUAL_ENV),)
	$(error "Run from a virtualenv (try 'make install && source venv/bin/activate')")
endif

install: venv requirements.txt
	( . venv/bin/activate && pip install -U pip && pip install -r requirements.txt )

venv:
	python3 -m venv venv

# get everything ready for a clean commit
commit: check_venv exceptions_schema.json $(REQUIREMENT_FILES)

# are we ready for a clean (prod) build
.PHONY: no-local-mods
no-local-mods:
	echo ":$$(git status --porcelain --untracked-files=no):"
	git status
	test -z "$$(git status --porcelain --untracked-files=no)" || $(warning "You have uncommitted files, so can not do a prod build") true

# make sure schema is current. Will rebuild too often, but with same
# output, so no changes visible in git
exceptions_schema.json: report-tls-certs
	./report-tls-certs --generate-schema >$@

# support routines

# local build rules
%.txt: %.in
	pip-compile --quiet --generate-hashes $<

requirements-dev.txt: requirements.txt
requirements-vscode.txt: requirements-dev.txt

# Docker image rules

# Constants set for production, can be overridden for dev
gcr_repository ?= certificate-certainty
prod_image ?= cc-cont-x86_64


# Make sure we know if we built image from a dirty repo
gitrev := $(shell bash -c "echo $$(git rev-parse --short=10 HEAD)$$(test -n "$$(git status --porcelain --untracked-files=no)" && echo -dirty)")
now := $(shell date --utc +%Y%m%dT%H%MZ)
image_tag := $(now)-$(gitrev)

# build needs special things:
#   - build packages (buildx)
build-dev: $(REQUIREMENT_FILES)
	docker buildx build \
		-t cc-cont:$(image_tag) \
		-t cc-cont:latest \
		-f Dockerfile.special .

# x86_64 is the production build, so also use latest tag for upload
build: check_cpu $(REQUIREMENT_FILES)
	-rm -f latest-prod-image.txt
	docker buildx build --platform linux/amd64 \
		-t $(prod_image):latest \
		-t $(prod_image):$(image_tag) \
		-f Dockerfile.special .
build-prod: no-local-mods build

# run prod image locally
run run-prod: check_cpu latest-prod-image.txt
	docker run --platform linux/amd64 --rm $(prod_image):$$(cat latest-prod-image.txt)

# NB the SPREADSHEET_GUID is a false positive for `detect-secrets`, and
# handled as such in the baseline
run-dev:
	docker run -it --rm \
		-e GCS_PREFIX=dev/ \
		-e SPREADSHEET_GUID="1QVYbry2mokSAu_Ii74-DPsCAVka2CU1JBSXiYx8iKS4" \
		cc-cont:latest \
		bash

# keep tag of latest prod image in a file for reference
# we don't use `latest` as we also want multiple versions on GCP for rollboack
latest-prod-image.txt:
	docker images --format "{{.Tag}}" $(prod_image):20* | sort -r | head -1 > $@

# GCP publish targets
# Push latest prod image
push-to-gcr: latest-prod-image.txt
	docker tag $(prod_image):$$(cat latest-prod-image.txt) us-central1-docker.pkg.dev/hwine-cc-dev/$(gcr_repository)/$(prod_image):$$(cat latest-prod-image.txt)
	docker push us-central1-docker.pkg.dev/hwine-cc-dev/$(gcr_repository)/$(prod_image):$$(cat latest-prod-image.txt)

configure-GAR-credentials-for-docker:
	gcloud auth configure-docker us-central1-docker.pkg.dev

login-service-account:
	gcloud auth application-default login --no-launch-browser


# If we're on a arm64 processor, we need to ensure the qemu emulater has been enabled
check_cpu:
	@$(SHELL) -c "set -eu ; \
		if test $$(uname -p) = 'aarch64' && ! ( update-binfmts --display | grep --quiet '^qemu-x86_64 (enabled):' ) ; then \
			echo \"no x86_64 emulation available, try 'sudo update-binfmts --enable qemu-x86_64'\" ;\
			false ; \
		fi"
