# Makefile for Granum Development Workflow

# Variables
VENV_NAME := granum_env
PYTHON := python3
PIP := $(VENV_NAME)/bin/pip
PORT := 8050

# Targets

.PHONY: help setup install run clean

help:
	@echo "Granum Development Workflow"
	@echo "---------------------------"
	@echo "make setup   - Create virtual environment and install dependencies"
	@echo "make run     - Start the Granum application (automatically kills previous instance)"
	@echo "make clean   - Remove virtual environment and build artifacts"

setup:
	$(PYTHON) -m venv $(VENV_NAME)
	@echo "Virtual environment created."
	@echo "Installing dependencies..."
	$(VENV_NAME)/bin/pip install --upgrade pip
	$(VENV_NAME)/bin/pip install -e .
	@echo "Dependencies installed."

install: setup
	@echo "Project installed in editable mode."

run:
	@echo "Checking for existing process on port $(PORT)..."
	-@kill $$(lsof -t -i :$(PORT)) 2>/dev/null || true
	@echo "Starting Granum application..."
	$(VENV_NAME)/bin/python -m src.__main__

clean:
	@echo "Cleaning up..."
	rm -rf $(VENV_NAME)
	rm -rf *.egg-info
	rm -rf __pycache__
	@echo "Cleanup complete."
