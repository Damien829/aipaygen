"""Tests for the 6 new MCP tools added to reach 250 total."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ── cron_explain ─────────────────────────────────────────────────────────────

class TestCronExplain:
    def _call(self, expression):
        from mcp_tools.utility_tools import cron_explain
        return cron_explain.__wrapped__(expression)

    def test_every_5_minutes(self):
        r = self._call("*/5 * * * *")
        assert "expression" in r
        assert "every 5 minutes" in r["natural"].lower()

    def test_midnight_daily(self):
        r = self._call("0 0 * * *")
        assert "0:00" in r["natural"]

    def test_specific_day(self):
        r = self._call("30 14 * * 1")
        assert "Monday" in r["natural"]

    def test_invalid_expression(self):
        r = self._call("bad input")
        assert "error" in r

    def test_five_fields(self):
        r = self._call("0 * * * *")
        assert r["fields"]["minute"] == "0"
        assert r["fields"]["hour"] == "*"

    def test_monthly(self):
        r = self._call("0 9 1 * *")
        assert "day 1" in r["natural"]


# ── color_palette ────────────────────────────────────────────────────────────

class TestColorPalette:
    def _call(self, base_color, count=5, palette_type="monochromatic"):
        from mcp_tools.utility_tools import color_palette
        return color_palette.__wrapped__(base_color, count, palette_type)

    def test_monochromatic(self):
        r = self._call("#3498db")
        assert len(r["colors"]) == 5
        assert all(c.startswith("#") for c in r["colors"])

    def test_complementary(self):
        r = self._call("ff0000", count=3, palette_type="complementary")
        assert len(r["colors"]) == 3

    def test_analogous(self):
        r = self._call("#00ff00", count=4, palette_type="analogous")
        assert len(r["colors"]) == 4

    def test_invalid_hex(self):
        r = self._call("xyz")
        assert "error" in r

    def test_max_count(self):
        r = self._call("#000000", count=50)
        assert len(r["colors"]) == 20

    def test_base_color_in_response(self):
        r = self._call("3498db")
        assert r["base_color"] == "#3498db"


# ── lorem_ipsum ──────────────────────────────────────────────────────────────

class TestLoremIpsum:
    def _call(self, paragraphs=1, style="classic"):
        from mcp_tools.utility_tools import lorem_ipsum
        return lorem_ipsum.__wrapped__(paragraphs, style)

    def test_single_paragraph(self):
        r = self._call(1)
        assert "Lorem ipsum" in r["text"]
        assert r["paragraphs"] == 1

    def test_multiple_paragraphs(self):
        r = self._call(3)
        assert r["paragraphs"] == 3
        assert "\n\n" in r["text"]

    def test_words_style(self):
        r = self._call(2, "words")
        assert "word_count" in r

    def test_max_paragraphs(self):
        r = self._call(20)
        assert r["paragraphs"] == 10


# ── password_generate ────────────────────────────────────────────────────────

class TestPasswordGenerate:
    def _call(self, length=16, include_symbols=True, count=1):
        from mcp_tools.utility_tools import password_generate
        return password_generate.__wrapped__(length, include_symbols, count)

    def test_default(self):
        r = self._call()
        assert len(r["password"]) == 16
        assert r["strength"] == "strong"

    def test_short_password(self):
        r = self._call(length=8)
        assert len(r["password"]) == 8
        assert r["strength"] == "weak"

    def test_no_symbols(self):
        r = self._call(include_symbols=False)
        pw = r["password"]
        assert pw.isalnum()

    def test_multiple(self):
        r = self._call(count=5)
        assert len(r["passwords"]) == 5

    def test_min_length(self):
        r = self._call(length=2)
        assert len(r["password"]) == 8  # clamped to min 8

    def test_max_length(self):
        r = self._call(length=500)
        assert len(r["password"]) == 128  # clamped to max 128

    def test_uniqueness(self):
        r = self._call(count=10)
        assert len(set(r["passwords"])) == 10  # all unique


# ── html_to_text ─────────────────────────────────────────────────────────────

class TestHtmlToText:
    def _call(self, html):
        from mcp_tools.data_tools import html_to_text
        return html_to_text.__wrapped__(html)

    def test_basic_html(self):
        r = self._call("<p>Hello <b>world</b></p>")
        assert "Hello world" in r["text"]

    def test_strips_scripts(self):
        r = self._call("<p>Visible</p><script>var x = 1;</script><p>Also visible</p>")
        assert "var x" not in r["text"]
        assert "Visible" in r["text"]
        assert "Also visible" in r["text"]

    def test_strips_styles(self):
        r = self._call("<style>body{color:red}</style><p>Content</p>")
        assert "color:red" not in r["text"]
        assert "Content" in r["text"]

    def test_entities(self):
        r = self._call("<p>A &amp; B</p>")
        assert "A & B" in r["text"]

    def test_word_count(self):
        r = self._call("<p>one two three</p>")
        assert r["word_count"] == 3

    def test_empty_html(self):
        r = self._call("")
        assert r["text"] == ""


# ── csv_to_json ──────────────────────────────────────────────────────────────

class TestCsvToJson:
    def _call(self, csv_text, delimiter=",", has_header=True):
        from mcp_tools.data_tools import csv_to_json
        return csv_to_json.__wrapped__(csv_text, delimiter, has_header)

    def test_basic_csv(self):
        r = self._call("name,age\nAlice,30\nBob,25")
        assert r["row_count"] == 2
        assert r["columns"] == ["name", "age"]
        assert r["data"][0]["name"] == "Alice"

    def test_no_header(self):
        r = self._call("a,b\nc,d", has_header=False)
        assert r["row_count"] == 2
        assert r["data"] == [["a", "b"], ["c", "d"]]

    def test_tab_delimiter(self):
        r = self._call("name\tage\nAlice\t30", delimiter="\t")
        assert r["data"][0]["name"] == "Alice"

    def test_empty_csv(self):
        r = self._call("")
        assert "error" in r

    def test_single_row_with_header(self):
        r = self._call("name,age\nAlice,30")
        assert r["row_count"] == 1
