"""SiloDSS local development server entry point."""

from src.view.view import app

if __name__ == "__main__":
    app.run(debug=True, port=8050)
