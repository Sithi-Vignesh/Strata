export type SqlValue = string | number | boolean | null;
export type SqlRow = SqlValue[];

export interface ColumnMetadata {
  name: string;
  type: "INTEGER" | "BIGINT" | "FLOAT" | "BOOLEAN" | "VARCHAR";
  nullable: boolean;
}

export interface IndexCondition {
  column: string;
  operator: "=" | "<" | "<=" | ">" | ">=";
  literal: SqlValue;
}

export interface TableScanProfile {
  access_path: "TableScan";
  table: string;
  index: null;
  condition: null;
  metrics: { tuples_examined: number };
}

export interface IndexScanProfile {
  access_path: "IndexScan";
  table: string;
  index: string;
  condition: IndexCondition;
  metrics: {
    tree_pages_visited: number;
    leaf_entries_examined: number;
    rids_selected: number;
    rows_fetched: number;
  };
}

export type SqlProfile = TableScanProfile | IndexScanProfile;

export interface QueryResponse {
  kind: "query";
  columns: ColumnMetadata[];
  rows: SqlRow[];
  row_count: number;
  profile: SqlProfile | null;
}

export interface CommandResponse {
  kind: "command";
  affected_rows: number;
  profile: null;
}

export type SqlProfileResponse = QueryResponse | CommandResponse;

export interface HealthResponse {
  status: "ok";
  service: "strata_backend";
  engine: {
    name: "StrataEngine";
    status: "open" | "initialized";
    initialized: boolean;
  };
}

export interface BackendErrorDetail {
  code: string;
  message: string;
}
