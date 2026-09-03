// @vitest-environment jsdom

import { describe, expect, test } from "vitest";
import { normalizeExcelRows, validateExcelUpload } from "./excel";


describe("Excel upload guardrails", () => {
  test("rejects an oversized upload before parsing", () => {
    const file = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "items.xlsx");

    expect(() => validateExcelUpload(file)).toThrow("Excel 文件不能超过 10 MB");
  });

  test("rejects more than 500 data rows", () => {
    const rows = Array.from({ length: 501 }, (_, index) => ({ detail_url: `https://std.samr.gov.cn/gb/search/gbDetailed?id=${index}` }));

    expect(() => normalizeExcelRows(rows)).toThrow("Excel 文件最多支持 500 条记录");
  });

  test("deduplicates URLs and reports empty detail urls", () => {
    const rows = normalizeExcelRows([
      { detail_url: " https://std.samr.gov.cn/gb/search/gbDetailed?id=1 ", code: "GB/T 1-2020" },
      { detail_url: "https://std.samr.gov.cn/gb/search/gbDetailed?id=1" },
      { detail_url: "not-a-supported-url" },
    ]);

    expect(rows).toEqual([
      { detail_url: "https://std.samr.gov.cn/gb/search/gbDetailed?id=1", code: "GB/T 1-2020", name: "", keyword: "excel_upload" },
    ]);
  });
});
