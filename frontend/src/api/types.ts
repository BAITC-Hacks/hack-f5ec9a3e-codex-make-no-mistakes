// API v1. Decimal quantities are strings; null means unknown, never zero.
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export interface TableColumn { key: string; type: string; nullable: boolean }
export interface TableDescriptor { key: string; columns: TableColumn[]; sortable: string[]; filters: string[] }
export type TableRow = Record<string, JsonValue>;
export interface TablePage { table: string; items: TableRow[]; total: number; page: number; page_size: number }
export interface SourceCell {
  type: string;
  value?: JsonValue;
  formula?: string | null;
  cached_value?: JsonValue;
  number_format?: string;
}
export interface SourceRowDetail {
  id: string; sheet_id: string; row_number: number;
  cells: Record<string, SourceCell>;
  sheet_name: string; workbook_id: string; original_path: string; sha256: string;
}
