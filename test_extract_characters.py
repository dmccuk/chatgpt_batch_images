import sys
import types

import pytest


playwright_module = types.ModuleType("playwright")
sync_api_module = types.ModuleType("playwright.sync_api")
pandas_module = types.ModuleType("pandas")
msvcrt_module = types.ModuleType("msvcrt")


class _DummyTimeoutError(Exception):
    pass


sync_api_module.sync_playwright = lambda: None
sync_api_module.TimeoutError = _DummyTimeoutError
playwright_module.sync_api = sync_api_module


class _DummyDataFrame:
    def fillna(self, value):
        return self

    def iterrows(self):
        return iter(())


pandas_module.read_csv = lambda *args, **kwargs: _DummyDataFrame()

sys.modules.setdefault("playwright", playwright_module)
sys.modules.setdefault("playwright.sync_api", sync_api_module)
sys.modules.setdefault("pandas", pandas_module)
sys.modules.setdefault("msvcrt", msvcrt_module)


import chatgpt_batch_images as cbi


@pytest.fixture(autouse=True)
def _clear_name_variants():
    original = cbi.NAME_VARIANTS
    cbi.NAME_VARIANTS = {}
    try:
        yield
    finally:
        cbi.NAME_VARIANTS = original


def test_extract_characters_plain_name():
    char_map = {"ayda": "ayda.png"}
    prompt = "A portrait of Ayda in the engine room."

    tags, files, clean = cbi.extract_characters(prompt, char_map)

    assert tags == ["ayda"]
    assert files == ["ayda.png"]
    assert clean == prompt


def test_extract_characters_mixed_case_tagged():
    char_map = {"ayda": "ayda.png"}
    prompt = "[@Ayda] Focus on AYDa during the mission."

    tags, files, clean = cbi.extract_characters(prompt, char_map)

    assert tags == ["ayda"]
    assert files == ["ayda.png"]
    assert clean == "Focus on AYDa during the mission."


def test_extract_characters_possessive_name():
    char_map = {"ayda": "ayda.png"}
    prompt = "Capture Ayda's determined expression."

    tags, files, clean = cbi.extract_characters(prompt, char_map)

    assert tags == ["ayda"]
    assert files == ["ayda.png"]
    assert clean == prompt
