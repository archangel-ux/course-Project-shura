import re
import string
import unittest
from pathlib import Path

from app.translations import en, kk, ru

APP_DIR = Path(__file__).resolve().parents[1] / "app"
# Keys passed to t(...) directly, plus keys stored in data and translated later (errors, field names, nav labels)
KEY_PATTERNS = (
    re.compile(r"""\bt\(\s*['"]([a-z_]+\.[A-Za-z0-9_]+)['"]"""),
    re.compile(r"""['"]((?:err|field|msg|note|nav|filter|movement)\.[A-Za-z0-9_]+)['"]"""),
)


def used_keys():
    keys = set()
    for path in list(APP_DIR.rglob("*.html")) + list(APP_DIR.rglob("*.py")):
        if "translations" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in KEY_PATTERNS:
            keys.update(pattern.findall(text))
    return {key for key in keys if not key.endswith("_")}


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class TranslationTest(unittest.TestCase):
    def test_all_languages_have_same_keys(self):
        self.assertEqual(set(kk.STRINGS) ^ set(ru.STRINGS), set())
        self.assertEqual(set(kk.STRINGS) ^ set(en.STRINGS), set())

    def test_every_used_key_is_translated(self):
        missing = sorted(key for key in used_keys() if key not in kk.STRINGS)
        self.assertEqual(missing, [])

    def test_dynamic_keys_exist(self):
        for key in ("auth.check_signup", "auth.check_recovery", "pref.theme_dark", "pref.theme_light",
                    "movement.IN", "movement.OUT", "movement.ADJUST"):
            self.assertIn(key, kk.STRINGS)

    def test_placeholders_match(self):
        for key, text in kk.STRINGS.items():
            for other in (ru.STRINGS, en.STRINGS):
                self.assertEqual(placeholders(text), placeholders(other[key]), key)


if __name__ == "__main__":
    unittest.main()
