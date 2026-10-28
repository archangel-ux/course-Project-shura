from flask import g, request, session

from app.translations import en, kk, ru

LANGUAGES = {"kk": "Қазақша", "ru": "Русский", "en": "English"}
THEMES = ("dark", "light")
TRANSLATIONS = {"kk": kk.STRINGS, "ru": ru.STRINGS, "en": en.STRINGS}


def resolve_preferences():
    """Signed-in users get their profile settings; guests get cookies or the browser language."""
    profile = session.get("profile") if session.get("auth") else None
    profile = profile or {}

    language = profile.get("language") or request.cookies.get("lang")
    if language not in LANGUAGES:
        language = request.accept_languages.best_match(list(LANGUAGES)) or "kk"

    theme = profile.get("theme") or request.cookies.get("theme")
    if theme not in THEMES:
        theme = "dark"

    g.lang = language
    g.theme = theme


def translate(language, key, **params):
    """Translate into an explicit language (background jobs have no request)."""
    if language not in TRANSLATIONS:
        language = "kk"
    text = TRANSLATIONS[language].get(key) or TRANSLATIONS["en"].get(key) or key
    if params:
        translated = {
            name: translate(language, value) if isinstance(value, str) and value.startswith("field.") else value
            for name, value in params.items()
        }
        text = text.format(**translated)
    return text


def t(key, **params):
    return translate(getattr(g, "lang", "kk"), key, **params)


def error_text(error):
    return t(error.key, **getattr(error, "params", {}))
