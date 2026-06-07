import json
import os

# Base directory for locales
LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'locales')

_translations = {}

def load_translations(lang):
    """Load translations for a given language if not already loaded."""
    if lang not in _translations:
        file_path = os.path.join(LOCALES_DIR, f'{lang}.json')
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    _translations[lang] = json.load(f)
                except json.JSONDecodeError:
                    _translations[lang] = {}
        else:
            _translations[lang] = {}

    return _translations[lang]

def translate(key, lang="pt"):
    """
    Translates a given key into the specified language.
    If the translation is missing, it returns the key itself as a fallback.
    """
    if not key:
        return key

    translations = load_translations(lang)

    # Try to find the exact key
    if key in translations:
        return translations[key]

    # If not found, return the key as the default
    return key
