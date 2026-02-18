# Quick Setup Guide with uv

## Prerequisites

- Python 3.11+ installed
- uv installed (see below)

## Installation Steps

1. **Install uv:**
   ```bash
   # macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   
   # macOS with Homebrew
   brew install uv
   
   # Windows (PowerShell)
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. **Set up the project:**
   ```bash
   # Clone/navigate to the project directory
   cd linkdin-automate
   
   # Create venv and install dependencies (recommended)
   uv sync
   
   # Or manually:
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   uv pip install -r requirements.txt
   ```

3. **Install browser-use browser:**
   ```bash
   uvx browser-use install
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

5. **Set up MongoDB:**
   - Install MongoDB locally, or
   - Create MongoDB Atlas account and get connection string
   - Update `MONGODB_URI` in `.env`

6. **Run the tool:**
   ```bash
   # Make sure venv is activated
   source .venv/bin/activate
   
   # Run pipeline
   python main.py --keywords "software engineer" --location "San Francisco"
   ```

## Using uv Commands

- `uv sync` - Create venv and install dependencies from pyproject.toml
- `uv pip install <package>` - Install a package in the venv
- `uv pip list` - List installed packages
- `uv pip freeze` - Export installed packages
- `uvx <command>` - Run a command in a temporary environment (e.g., `uvx browser-use install`)
