FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (e.g., CBC solver for Pyomo, build-essential for CmdStan compilation)
RUN apt-get update && apt-get install -y coinor-cbc build-essential && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md wsgi.py run_server.py ./
COPY src/ src/

# Install the application and dependencies
# We install with -e (editable) so we can run directly from source in /app
RUN pip install --no-cache-dir -e .

# Install and compile CmdStan backend for Prophet/cmdstanpy
RUN python -c "import cmdstanpy; cmdstanpy.install_cmdstan()"

# Expose the port the app runs on
EXPOSE 8050

# Command to run the application directly from source
# This ensures it uses the files in /app/src, not site-packages
# In production, we use gunicorn and bind to the port expected by Render
CMD gunicorn wsgi:server --bind 0.0.0.0:${PORT:-8050} --timeout 720 --workers 1
