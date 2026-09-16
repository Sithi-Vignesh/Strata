"""System Catalog implementation managing schemas, table metadata, and persistence."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, List, Optional, Union

from strata_engine.catalog.exceptions import (
    CatalogCorruptionError,
    CatalogError,
    ReservedNameError,
    TableAlreadyExistsError,
    TableNotFoundError,
)
from strata_engine.catalog.table import Table
from strata_engine.schema.column import Column
from strata_engine.schema.data_type import DataType
from strata_engine.schema.exceptions import InvalidColumnError
from strata_engine.schema.schema import Schema
from strata_engine.schema.serializer import TupleSerializer
from strata_engine.schema.tuple import Tuple
from strata_engine.storage.buffer_pool import BufferPoolManager
from strata_engine.storage.exceptions import StorageClosedError
from strata_engine.storage.heap_file import HeapFile
from strata_engine.storage.page_file import PageFile
from strata_engine.storage.record_id import RecordId

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
ORPHAN_FILE_PATTERN = re.compile(r"^table_([1-9][0-9]*)\.db$")
HEADER_PREFIX = "STRATA_CATALOG_V1:HWM="

# Compile-time internal system schemas
SYSTEM_TABLES_SCHEMA = Schema([
    Column("table_id", DataType.INTEGER, nullable=False),
    Column("table_name", DataType.VARCHAR, nullable=False, max_length=64),
])

SYSTEM_COLUMNS_SCHEMA = Schema([
    Column("table_id", DataType.INTEGER, nullable=False),
    Column("column_name", DataType.VARCHAR, nullable=False, max_length=64),
    Column("ordinal_position", DataType.INTEGER, nullable=False),
    Column("data_type", DataType.VARCHAR, nullable=False, max_length=16),
    Column("nullable", DataType.BOOLEAN, nullable=False),
    Column("max_length", DataType.INTEGER, nullable=True),
])


@dataclass
class TableMetadata:
    """Internal metadata descriptor for a registered table."""

    table_id: int
    name: str
    schema: Schema
    table_rid: RecordId
    column_rids: List[RecordId]


class Catalog:
    """Persistent System Catalog managing table metadata, schemas, and physical storage.

    Layout:
        <data_dir>/
          catalog/
            tables.db
            columns.db
          tables/
            table_1.db
            table_2.db
    """

    def __init__(
        self,
        data_dir: Union[Path, str],
        default_pool_size: int = 10,
    ) -> None:
        """Initialize and bootstrap or recover the System Catalog.

        Args:
            data_dir: Filesystem path to the database root directory.
            default_pool_size: Default frame pool capacity for BufferPoolManagers.

        Raises:
            CatalogCorruptionError: If catalog files, metadata headers, or descriptors are corrupted.
        """
        self._data_dir: Path = Path(data_dir).resolve()
        self._default_pool_size: int = default_pool_size
        self._closed: bool = False

        self._catalog_dir: Path = self._data_dir / "catalog"
        self._tables_dir: Path = self._data_dir / "tables"
        self._tables_db_path: Path = self._catalog_dir / "tables.db"
        self._columns_db_path: Path = self._catalog_dir / "columns.db"

        self._tables_serializer = TupleSerializer(SYSTEM_TABLES_SCHEMA)
        self._columns_serializer = TupleSerializer(SYSTEM_COLUMNS_SCHEMA)

        self._tables_meta: Dict[str, TableMetadata] = {}
        self._open_tables: Dict[str, Table] = {}

        self._hwm: int = 0
        self._header_rid: Optional[RecordId] = None

        tables_exist = self._tables_db_path.exists()
        columns_exist = self._columns_db_path.exists()

        if not tables_exist and not columns_exist:
            self._bootstrap_new_catalog()
        elif tables_exist and columns_exist:
            self._reopen_existing_catalog()
        else:
            raise CatalogCorruptionError(
                f"Partial catalog state detected in '{self._catalog_dir}'. "
                f"tables.db exists: {tables_exist}, columns.db exists: {columns_exist}."
            )

    @property
    def data_dir(self) -> Path:
        """Return the database root directory."""
        return self._data_dir

    @property
    def is_closed(self) -> bool:
        """Return whether the catalog has been closed."""
        return self._closed

    def _check_not_closed(self) -> None:
        """Raise StorageClosedError if catalog is closed."""
        if self._closed:
            raise StorageClosedError("Operation attempted on closed Catalog.")

    def _bootstrap_new_catalog(self) -> None:
        """Initialize a brand-new catalog directory and persist version descriptor."""
        self._catalog_dir.mkdir(parents=True, exist_ok=True)
        self._tables_dir.mkdir(parents=True, exist_ok=True)

        self._tables_pf = PageFile(self._tables_db_path)
        self._tables_bpm = BufferPoolManager(self._tables_pf, pool_size=5)
        self._tables_heap = HeapFile(self._tables_bpm)

        self._columns_pf = PageFile(self._columns_db_path)
        self._columns_bpm = BufferPoolManager(self._columns_pf, pool_size=5)
        self._columns_heap = HeapFile(self._columns_bpm)

        self._hwm = 0
        header_tuple = Tuple([0, f"{HEADER_PREFIX}0"], SYSTEM_TABLES_SCHEMA)
        self._header_rid = self._tables_heap.insert_record(
            self._tables_serializer.serialize(header_tuple)
        )

        self._tables_bpm.flush_all()
        self._columns_bpm.flush_all()

    def _reopen_existing_catalog(self) -> None:
        """Recover catalog metadata and table definitions from existing files."""
        self._tables_pf = PageFile(self._tables_db_path)
        self._tables_bpm = BufferPoolManager(self._tables_pf, pool_size=5)
        self._tables_heap = HeapFile(self._tables_bpm)

        self._columns_pf = PageFile(self._columns_db_path)
        self._columns_bpm = BufferPoolManager(self._columns_pf, pool_size=5)
        self._columns_heap = HeapFile(self._columns_bpm)

        # 1. Scan tables.db: find exactly one header record (table_id == 0) and user tables
        headers: List[tuple[RecordId, Tuple]] = []
        user_tables: Dict[int, tuple[str, RecordId]] = {}
        names_seen: Dict[str, int] = {}

        for rid, raw_bytes in self._tables_heap.scan_records():
            try:
                row = self._tables_serializer.deserialize(raw_bytes)
            except Exception as exc:
                raise CatalogCorruptionError(f"Corrupted record in tables.db at {rid}: {exc}") from exc

            t_id = row[0]
            t_name = row[1]

            if t_id == 0:
                headers.append((rid, row))
            elif t_id > 0:
                if not TABLE_NAME_PATTERN.match(t_name):
                    raise CatalogCorruptionError(f"Corrupted user table name '{t_name}' (ID {t_id}) in tables.db.")
                if t_name.startswith("_"):
                    raise CatalogCorruptionError(f"Reserved table name '{t_name}' in tables.db.")
                if t_id in user_tables:
                    raise CatalogCorruptionError(f"Duplicate table ID {t_id} detected in tables.db.")
                lower_name = t_name.lower()
                if lower_name in names_seen:
                    raise CatalogCorruptionError(
                        f"Duplicate case-insensitive table name '{t_name}' matches existing table ID {names_seen[lower_name]}."
                    )
                names_seen[lower_name] = t_id
                user_tables[t_id] = (t_name, rid)
            else:
                raise CatalogCorruptionError(f"Invalid negative table ID {t_id} in tables.db.")

        if len(headers) != 1:
            raise CatalogCorruptionError(
                f"Expected exactly one catalog header record (table_id=0), found {len(headers)}."
            )

        self._header_rid, header_row = headers[0]
        header_name = header_row[1]

        if not isinstance(header_name, str) or not header_name.startswith(HEADER_PREFIX):
            raise CatalogCorruptionError(
                f"Invalid or unsupported catalog version header '{header_name}'. Expected prefix '{HEADER_PREFIX}'."
            )

        hwm_str = header_name[len(HEADER_PREFIX):]
        try:
            persisted_hwm = int(hwm_str)
            if persisted_hwm < 0:
                raise ValueError("HWM is negative")
        except Exception as exc:
            raise CatalogCorruptionError(
                f"Malformed catalog HWM integer '{hwm_str}' in header: {exc}."
            ) from exc

        # 2. Scan columns.db: group column records by table_id
        columns_by_table: Dict[int, List[tuple[RecordId, Tuple]]] = {}
        for rid, raw_bytes in self._columns_heap.scan_records():
            try:
                row = self._columns_serializer.deserialize(raw_bytes)
            except Exception as exc:
                raise CatalogCorruptionError(f"Corrupted record in columns.db at {rid}: {exc}") from exc

            t_id = row[0]
            if t_id <= 0:
                raise CatalogCorruptionError(f"Invalid table_id {t_id} for column record in columns.db.")

            if t_id not in columns_by_table:
                columns_by_table[t_id] = []
            columns_by_table[t_id].append((rid, row))

        # 3. Validate and reconstruct each user table
        for t_id, (t_name, tbl_rid) in user_tables.items():
            if t_id not in columns_by_table or len(columns_by_table[t_id]) == 0:
                raise CatalogCorruptionError(f"Table '{t_name}' (ID {t_id}) has no column records in columns.db.")

            col_records = columns_by_table[t_id]
            # Sort by ordinal position
            try:
                sorted_cols = sorted(col_records, key=lambda pair: pair[1][2])
            except Exception as exc:
                raise CatalogCorruptionError(f"Error sorting columns for table {t_id}: {exc}") from exc

            # Verify ordinals: exactly 0, 1, ..., N-1
            expected_ordinals = list(range(len(sorted_cols)))
            actual_ordinals = [pair[1][2] for pair in sorted_cols]
            if actual_ordinals != expected_ordinals:
                raise CatalogCorruptionError(
                    f"Table '{t_name}' (ID {t_id}) has invalid or non-contiguous ordinals: {actual_ordinals}."
                )

            schema_cols: List[Column] = []
            col_rids: List[RecordId] = []

            for col_rid, c_row in sorted_cols:
                c_name = c_row[1]
                dt_str = c_row[3]
                nullable = c_row[4]
                max_len = c_row[5]

                try:
                    dt = DataType(dt_str)
                except ValueError:
                    raise CatalogCorruptionError(
                        f"Table '{t_name}' has unrecognized DataType string '{dt_str}' for column '{c_name}'."
                    )

                try:
                    col_obj = Column(c_name, dt, nullable=nullable, max_length=max_len)
                except InvalidColumnError as exc:
                    raise CatalogCorruptionError(
                        f"Corrupt column definition for '{c_name}' in table '{t_name}': {exc}"
                    ) from exc

                schema_cols.append(col_obj)
                col_rids.append(col_rid)

            try:
                schema_obj = Schema(schema_cols)
            except Exception as exc:
                raise CatalogCorruptionError(
                    f"Failed to reconstruct schema for table '{t_name}' (ID {t_id}): {exc}"
                ) from exc

            # Verify backing physical file exists
            expected_file = self._tables_dir / f"table_{t_id}.db"
            if not expected_file.exists():
                raise CatalogCorruptionError(
                    f"Physical storage file '{expected_file}' missing for table '{t_name}' (ID {t_id})."
                )

            meta = TableMetadata(
                table_id=t_id,
                name=t_name,
                schema=schema_obj,
                table_rid=tbl_rid,
                column_rids=col_rids,
            )
            self._tables_meta[t_name.lower()] = meta

        # 4. Reconcile HWM with orphan physical files
        physical_table_max = 0
        if self._tables_dir.exists():
            for child in self._tables_dir.iterdir():
                if child.is_file():
                    match = ORPHAN_FILE_PATTERN.match(child.name)
                    if match:
                        f_id = int(match.group(1))
                        if f_id > physical_table_max:
                            physical_table_max = f_id

        live_table_max = max(user_tables.keys(), default=0)
        self._hwm = max(persisted_hwm, live_table_max, physical_table_max)

    def _on_table_close(self, table: Table) -> None:
        """Internal callback invoked when a Table is manually closed."""
        lower_name = table.name.lower()
        if lower_name in self._open_tables and self._open_tables[lower_name] is table:
            del self._open_tables[lower_name]

    def create_table(self, name: str, schema: Schema) -> Table:
        """Create a new table with the given name and schema.

        Args:
            name: Table name matching ^[A-Za-z_][A-Za-z0-9_]{0,63}$.
            schema: Valid Schema instance.

        Returns:
            Table: Open Table instance.

        Raises:
            StorageClosedError: If catalog is closed.
            ReservedNameError: If table name begins with '_'.
            CatalogError: If name format is invalid.
            TableAlreadyExistsError: If a table with this case-insensitive name already exists.
        """
        self._check_not_closed()

        if not isinstance(name, str) or not TABLE_NAME_PATTERN.match(name):
            raise CatalogError(
                f"Invalid table name '{name}'. Names must match '^[A-Za-z_][A-Za-z0-9_]{{0,63}}$'."
            )

        if name.startswith("_"):
            raise ReservedNameError(f"Table name '{name}' is reserved. Table names starting with '_' are reserved.")

        if not isinstance(schema, Schema):
            raise TypeError(f"Expected Schema instance, got {type(schema).__name__}.")

        lower_name = name.lower()
        if lower_name in self._tables_meta:
            existing = self._tables_meta[lower_name].name
            raise TableAlreadyExistsError(
                f"Table '{name}' already exists (matches existing table '{existing}' case-insensitively)."
            )

        # Allocate monotonic candidate table_id
        candidate = self._hwm + 1
        while (self._tables_dir / f"table_{candidate}.db").exists():
            candidate += 1
        self._hwm = candidate

        # 1. Create physical table file on disk
        target_path = self._tables_dir / f"table_{candidate}.db"
        pf = PageFile(target_path)
        bpm = BufferPoolManager(pf, pool_size=self._default_pool_size)
        hf = HeapFile(bpm)

        # 2. Persist column metadata to columns.db
        col_rids: List[RecordId] = []
        for idx, col in enumerate(schema.columns):
            rec = Tuple([candidate, col.name, idx, col.data_type.value, col.nullable, col.max_length], SYSTEM_COLUMNS_SCHEMA)
            rid = self._columns_heap.insert_record(self._columns_serializer.serialize(rec))
            col_rids.append(rid)
        self._columns_bpm.flush_all()

        # 3. Persist table metadata to tables.db
        tbl_rec = Tuple([candidate, name], SYSTEM_TABLES_SCHEMA)
        tbl_rid = self._tables_heap.insert_record(self._tables_serializer.serialize(tbl_rec))
        self._tables_bpm.flush_all()

        # 4. Update catalog header record with new HWM
        if self._header_rid is not None:
            self._tables_heap.delete_record(self._header_rid)
        hdr_rec = Tuple([0, f"{HEADER_PREFIX}{self._hwm}"], SYSTEM_TABLES_SCHEMA)
        self._header_rid = self._tables_heap.insert_record(self._tables_serializer.serialize(hdr_rec))
        self._tables_bpm.flush_all()

        # 5. Instantiate Table and register in cache
        tbl = Table(candidate, name, schema, hf, on_close=self._on_table_close)
        meta = TableMetadata(
            table_id=candidate,
            name=name,
            schema=schema,
            table_rid=tbl_rid,
            column_rids=col_rids,
        )
        self._tables_meta[lower_name] = meta
        self._open_tables[lower_name] = tbl

        return tbl

    def get_table(self, name: str) -> Table:
        """Retrieve an open Table instance by case-insensitive name.

        Args:
            name: Table name.

        Returns:
            Table: Open Table instance.

        Raises:
            StorageClosedError: If catalog is closed.
            TableNotFoundError: If table does not exist or is a reserved system name.
        """
        self._check_not_closed()

        if not isinstance(name, str) or name.startswith("_"):
            raise TableNotFoundError(f"Table '{name}' does not exist.")

        lower_name = name.lower()
        if lower_name not in self._tables_meta:
            raise TableNotFoundError(f"Table '{name}' does not exist.")

        if lower_name in self._open_tables:
            tbl = self._open_tables[lower_name]
            if tbl.is_closed:
                del self._open_tables[lower_name]
            else:
                return tbl

        # Reopen closed or un-cached table
        meta = self._tables_meta[lower_name]
        tbl_path = self._tables_dir / f"table_{meta.table_id}.db"
        pf = PageFile(tbl_path)
        bpm = BufferPoolManager(pf, pool_size=self._default_pool_size)
        hf = HeapFile(bpm)
        tbl = Table(meta.table_id, meta.name, meta.schema, hf, on_close=self._on_table_close)
        self._open_tables[lower_name] = tbl
        return tbl

    def has_table(self, name: str) -> bool:
        """Return whether a user table exists by case-insensitive name."""
        if not isinstance(name, str) or name.startswith("_") or self._closed:
            return False
        return name.lower() in self._tables_meta

    def list_tables(self) -> List[str]:
        """Return a list of user table names with their original casing preserved."""
        self._check_not_closed()
        return [meta.name for meta in self._tables_meta.values()]

    def drop_table(self, name: str) -> None:
        """Drop a user table by case-insensitive name.

        Closes open table resources, deletes metadata from tables.db and columns.db,
        and removes the physical storage file. Does not decrement HWM.

        Args:
            name: Table name.

        Raises:
            StorageClosedError: If catalog is closed.
            TableNotFoundError: If table does not exist.
        """
        self._check_not_closed()

        if not isinstance(name, str) or name.startswith("_"):
            raise TableNotFoundError(f"Table '{name}' does not exist.")

        lower_name = name.lower()
        if lower_name not in self._tables_meta:
            raise TableNotFoundError(f"Table '{name}' does not exist.")

        meta = self._tables_meta[lower_name]

        # 1. Close open table instance if present
        if lower_name in self._open_tables:
            tbl = self._open_tables[lower_name]
            tbl.close()
            if lower_name in self._open_tables:
                del self._open_tables[lower_name]

        # 2. Delete metadata from tables.db and columns.db
        self._tables_heap.delete_record(meta.table_rid)
        self._tables_bpm.flush_all()

        for c_rid in meta.column_rids:
            self._columns_heap.delete_record(c_rid)
        self._columns_bpm.flush_all()

        # 3. Delete physical storage file on disk
        target_file = self._tables_dir / f"table_{meta.table_id}.db"
        if target_file.exists():
            target_file.unlink()

        # 4. Remove from in-memory metadata registry
        del self._tables_meta[lower_name]

    def close(self) -> None:
        """Close all open tables and catalog system files. Idempotent."""
        if self._closed:
            return

        self._closed = True

        # Close all active table instances
        open_instances = list(self._open_tables.values())
        for tbl in open_instances:
            try:
                tbl.close()
            except Exception:
                pass
        self._open_tables.clear()

        # Close system catalog storage
        try:
            self._tables_bpm.close()
            self._tables_pf.close()
        except Exception:
            pass

        try:
            self._columns_bpm.close()
            self._columns_pf.close()
        except Exception:
            pass

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __repr__(self) -> str:
        status = "closed" if self._closed else f"open, tables={len(self._tables_meta)}"
        return f"Catalog(data_dir='{self._data_dir}', status='{status}')"
