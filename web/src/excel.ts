import type { DirectGrabItem } from "./types";

export const MAX_EXCEL_UPLOAD_BYTES = 10 * 1024 * 1024;
export const MAX_EXCEL_UPLOAD_ROWS = 500;

const DETAIL_URL_PATTERN = /^https?:\/\/std\.samr\.gov\.cn\/gb\/search\/gbDetailed\?[^\s"'<>]+$/i;

export function validateExcelUpload(file: File): void {
  if (file.size > MAX_EXCEL_UPLOAD_BYTES) {
    throw new Error("Excel 文件不能超过 10 MB");
  }
}

export function normalizeExcelRows(rows: Array<Record<string, unknown>>): DirectGrabItem[] {
  if (rows.length > MAX_EXCEL_UPLOAD_ROWS) {
    throw new Error("Excel 文件最多支持 500 条记录");
  }

  const seen = new Set<string>();
  const items: DirectGrabItem[] = [];
  for (const row of rows) {
    const detailUrl = String(row.detail_url ?? "").trim();
    if (!DETAIL_URL_PATTERN.test(detailUrl) || seen.has(detailUrl)) {
      continue;
    }
    seen.add(detailUrl);
    items.push({
      detail_url: detailUrl,
      code: String(row.code ?? "").trim(),
      name: String(row.name ?? "").trim(),
      keyword: String(row.keyword ?? "").trim() || "excel_upload",
    });
  }
  return items;
}
