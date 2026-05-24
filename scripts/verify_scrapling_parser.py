import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scrapling_parser import parse_detail_meta, parse_search_results


CURRENT_STATUS = "\u73b0\u884c"
OLD_STATUS = "\u5e9f\u6b62"


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_contains(value, expected, label):
    if expected not in value:
        raise AssertionError(f"{label}: expected {expected!r} in {value!r}")


def verify_search_results():
    html = f"""
    <html>
      <body>
        <div class="panel panel-default post">
          <table class="s-title"><tr><td>
            <a tid="BV_GB" pid="GB001"><span class="en-code">GB 123-2024</span> National standard</a>
          </td></tr></table>
          <span class="s-status label">{CURRENT_STATUS}</span>
        </div>
        <div class="panel panel-default post">
          <table class="s-title"><tr><td>
            <a tid="BV_HB" pid="HB001"><span class="en-code">HB 456-2024</span> Industry standard</a>
          </td></tr></table>
          <span class="s-status label">{CURRENT_STATUS}</span>
        </div>
        <div class="panel panel-default post">
          <table class="s-title"><tr><td>
            <a tid="BV_DB" pid="DB001"><span class="en-code">DB 789-2024</span> Local standard</a>
          </td></tr></table>
          <span class="s-status label">{CURRENT_STATUS}</span>
        </div>
        <div class="panel panel-default post">
          <table class="s-title"><tr><td>
            <a tid="BV_QT" pid="QT001"><span class="en-code">QT 001-2024</span> Other standard</a>
          </td></tr></table>
          <span class="s-status label">{CURRENT_STATUS}</span>
        </div>
        <div class="panel panel-default post">
          <table class="s-title"><tr><td>
            <a tid="BV_GB" pid="GB002"><span class="en-code">GB 000-2020</span> Old standard</a>
          </td></tr></table>
          <span class="s-status label">{OLD_STATUS}</span>
        </div>
      </body>
    </html>
    """
    result = parse_search_results(html, "ai")

    assert_equal(result["panel_count"], 5, "search panel count")
    assert_equal(result["skipped_type"], 1, "search skipped type")
    assert_equal(result["skipped_status"], 1, "search skipped status")
    assert_equal(len(result["records"]), 3, "search record count")
    assert_equal(result["records"][0]["keyword"], "ai", "search keyword")
    assert_equal(result["records"][0]["code"], "GB 123-2024", "search code")
    assert_equal(
        result["records"][0]["detail_url"],
        "https://std.samr.gov.cn/gb/search/gbDetailed?id=GB001",
        "search detail url",
    )


def verify_detail_meta():
    release_label = "\u53d1\u5e03\u65e5\u671f"
    implement_label = "\u5b9e\u65bd\u65e5\u671f"
    charge_label = "\u5f52\u53e3\u5355\u4f4d"
    release_unit_label = "\u4e3b\u7ba1\u90e8\u95e8"
    draft_unit_label = "\u8d77\u8349\u5355\u4f4d"
    drafter_label = "\u8d77\u8349\u4eba"
    scope_label = "\u9002\u7528\u8303\u56f4"
    english_label = "\u82f1\u6587\u540d\u79f0"
    replace_label = "\u66ff\u4ee3\u60c5\u51b5"

    html = f"""
    <html>
      <body>
        <dl><dt>{release_label}</dt><dd>2024-01-01</dd></dl>
        <dl><dt>{implement_label}</dt><dd>2024-02-01</dd></dl>
        <dl><dt>{charge_label}</dt><dd>National Committee</dd></dl>
        <dl><dt>{release_unit_label}</dt><dd>State Agency</dd></dl>
        <dl><dt>{draft_unit_label}</dt><dd><a>Unit A</a><a>Unit B</a></dd></dl>
        <dl><dt>{drafter_label}</dt><dd><span>Alice</span><span>Bob</span></dd></dl>
        <h2>{scope_label}</h2><p>Applies to parser verification.</p>
        <dl><dt>{english_label}</dt><dd>English Standard Name</dd></dl>
        <dl><dt>{replace_label}</dt><dd>Replaces GB 1-2020</dd></dl>
        <div class="referencedStandards"><table><tr><td>GB/T 1.1</td></tr></table></div>
      </body>
    </html>
    """
    xpaths = {
        "release_date": f'//dt[contains(text(), "{release_label}")]/following-sibling::dd[1]',
        "implement_date": f'//dt[contains(text(), "{implement_label}")]/following-sibling::dd[1]',
        "charge_unit": f'//dt[contains(text(), "{charge_label}")]/following-sibling::dd[1]',
        "release_unit": f'//dt[contains(text(), "{release_unit_label}")]/following-sibling::dd[1]',
        "draft_unit": f'//dt[contains(text(), "{draft_unit_label}")]/following-sibling::dd[1]/a',
        "drafter": f'//dt[contains(text(), "{drafter_label}")]/following-sibling::dd[1]/span',
        "scope": f'//h2[contains(text(), "{scope_label}")]/following-sibling::p[1]',
        "english_name": f'//dt[contains(text(), "{english_label}")]/following-sibling::dd[1]',
        "replace_info": f'//dt[contains(text(), "{replace_label}")]/following-sibling::dd[1]',
        "reference": '//div[contains(@class, "referencedStandards")]//table',
        "empty_field": "",
    }
    result = parse_detail_meta(
        html,
        xpaths,
        "https://std.samr.gov.cn/gb/search/gbDetailed?id=GB001",
        "\u56fd\u6807",
    )

    assert_equal(result["release_date"], "2024-01-01", "detail release date")
    assert_equal(result["implement_date"], "2024-02-01", "detail implement date")
    assert_equal(result["charge_unit"], "National Committee", "detail charge unit")
    assert_equal(result["release_unit"], "State Agency", "detail release unit")
    assert_equal(result["draft_unit"], "Unit A\uff1bUnit B", "detail draft unit")
    assert_equal(result["drafter"], "Alice\uff1bBob", "detail drafter")
    assert_equal(result["scope"], "Applies to parser verification.", "detail scope")
    assert_equal(result["english_name"], "English Standard Name", "detail english name")
    assert_equal(result["replace_info"], "Replaces GB 1-2020", "detail replace info")
    assert_contains(result["reference"], "GB/T 1.1", "detail reference")
    assert_equal(result["empty_field"], None, "detail empty xpath")


def verify_detail_meta_storage_fallback():
    old_value = os.environ.get("STD_SCRAPLING_STORAGE_FILE")
    release_label = "\u53d1\u5e03\u65e5\u671f"
    standard_type = "\u56fd\u6807"
    with tempfile.TemporaryDirectory() as storage_file_dir:
        try:
            os.environ["STD_SCRAPLING_STORAGE_FILE"] = storage_file_dir
            result = parse_detail_meta(
                f"<html><body><dl><dt>{release_label}</dt><dd>2024-03-01</dd></dl></body></html>",
                {"release_date": f'//dt[contains(text(), "{release_label}")]/following-sibling::dd[1]'},
                "https://std.samr.gov.cn/gb/search/gbDetailed?id=GB002",
                standard_type,
            )
            assert_equal(result["release_date"], "2024-03-01", "detail storage fallback")
        finally:
            if old_value is None:
                os.environ.pop("STD_SCRAPLING_STORAGE_FILE", None)
            else:
                os.environ["STD_SCRAPLING_STORAGE_FILE"] = old_value


def main():
    verify_search_results()
    verify_detail_meta()
    verify_detail_meta_storage_fallback()
    print("scrapling parser verification passed")


if __name__ == "__main__":
    main()
