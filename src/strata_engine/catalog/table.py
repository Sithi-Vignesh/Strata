"""Relational Table abstraction backed by HeapFile and Schema."""

from typing import Any, Callable, Iterator, Optional, Sequence, Tuple as PyTuple, Union

from strata_engine.schema.exceptions import SchemaMismatchError
from strata_engine.schema.schema import Schema
from strata_engine.schema.serializer import TupleSerializer
from strata_engine.schema.tuple import Tuple
from strata_engine.catalog.index import TableIndex
from strata_engine.catalog.exceptions import CatalogCorruptionError
from strata_engine.storage.exceptions import InsufficientSpaceError, StorageClosedError
from strata_engine.storage.heap_file import HeapFile
from strata_engine.storage.record_id import RecordId


class Table:
    """Relational table interface providing typed tuple operations over a HeapFile.

    A Table encapsulates a Schema, a dedicated HeapFile (and its BufferPoolManager/PageFile),
    and a TupleSerializer.
    """

    __slots__ = (
        "_table_id",
        "_name",
        "_schema",
        "_heap_file",
        "_serializer",
        "_closed",
        "_on_close",
        "_indexes",
    )

    def __init__(
        self,
        table_id: int,
        name: str,
        schema: Schema,
        heap_file: HeapFile,
        on_close: Optional[Callable[["Table"], None]] = None,
        indexes: Sequence[TableIndex] = (),
    ) -> None:
        """Initialize a Table instance.

        Args:
            table_id: Unique integer identifier for this table.
            name: Case-preserving logical table name.
            schema: Schema defining the table's columns and types.
            heap_file: Backing HeapFile storage for record data.
            on_close: Optional callback invoked when the table is closed.

        Raises:
            TypeError: If arguments are of invalid types.
            StorageClosedError: If the backing heap file or buffer pool is closed.
        """
        if not isinstance(table_id, int):
            raise TypeError(f"Expected int table_id, got {type(table_id).__name__}.")
        if not isinstance(name, str):
            raise TypeError(f"Expected str name, got {type(name).__name__}.")
        if not isinstance(schema, Schema):
            raise TypeError(f"Expected Schema instance, got {type(schema).__name__}.")
        if not isinstance(heap_file, HeapFile):
            raise TypeError(f"Expected HeapFile instance, got {type(heap_file).__name__}.")

        if heap_file.buffer_pool_manager.is_closed:
            raise StorageClosedError("Cannot initialize Table with a closed storage manager.")

        self._table_id: int = table_id
        self._name: str = name
        self._schema: Schema = schema
        self._heap_file: HeapFile = heap_file
        self._serializer: TupleSerializer = TupleSerializer(schema)
        self._closed: bool = False
        self._on_close: Optional[Callable[["Table"], None]] = on_close
        self._indexes: list[TableIndex] = list(indexes)

    @property
    def table_id(self) -> int:
        """Return the unique integer identifier of this table."""
        return self._table_id

    @property
    def name(self) -> str:
        """Return the case-preserving logical name of this table."""
        return self._name

    @property
    def schema(self) -> Schema:
        """Return the immutable Schema of this table."""
        return self._schema

    @property
    def heap_file(self) -> HeapFile:
        """Return the backing HeapFile."""
        return self._heap_file

    @property
    def is_closed(self) -> bool:
        """Return whether this table instance has been closed."""
        return self._closed or self._heap_file.buffer_pool_manager.is_closed

    @property
    def indexes(self) -> tuple[TableIndex, ...]:
        """Open operational index bindings attached to this table."""
        return tuple(self._indexes)

    def index_for_column(self, column_name: str) -> Optional[TableIndex]:
        """Return the deterministic live index binding for one table column.

        Resolves ``column_name`` with the table schema's normal
        case-insensitive identifier rules.  If more than one index covers the
        column, the lowest persistent index ID is selected.
        """
        self._check_not_closed()
        ordinal = self._schema.column_index(column_name)
        matches = (index for index in self._indexes if index.column_ordinal == ordinal)
        return min(matches, key=lambda index: index.index_id, default=None)

    def _attach_index(self, index: TableIndex) -> None:
        """Catalog-internal attachment after successful create/backfill."""
        self._check_not_closed()
        self._indexes.append(index)

    def _check_not_closed(self) -> None:
        """Raise StorageClosedError if operations are attempted on a closed table."""
        if self._closed or self._heap_file.buffer_pool_manager.is_closed:
            raise StorageClosedError(
                f"Operation attempted on closed table '{self._name}' (ID {self._table_id})."
            )

    def insert(self, row: Union[Tuple, Sequence[Any]]) -> RecordId:
        """Insert a typed Tuple or sequence of values into the table.

        Args:
            row: Tuple instance or sequence of Python values matching self.schema.

        Returns:
            RecordId: Address of the newly inserted record.

        Raises:
            StorageClosedError: If the table or underlying storage is closed.
            SchemaMismatchError: If row is a schema-bound Tuple with a conflicting schema.
            TupleArityError: If value count does not match schema column count.
            TypeMismatchError: If any value does not match expected DataType.
            NullConstraintError: If None is supplied for a non-nullable column.
            ValueOutOfRangeError: If integer or VARCHAR length boundaries are exceeded.
            TupleSizeError: If serialized tuple exceeds 4084 bytes.
        """
        self._check_not_closed()

        if isinstance(row, Tuple):
            if row.schema is not None and row.schema.fingerprint != self._schema.fingerprint:
                raise SchemaMismatchError(
                    f"Cannot insert Tuple with schema fingerprint 0x{row.schema.fingerprint:08X} "
                    f"into Table '{self._name}' with schema fingerprint 0x{self._schema.fingerprint:08X}."
                )
            values = row.values
        elif isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            values = tuple(row)
        else:
            raise TypeError(f"Expected Tuple or Sequence of values, got {type(row).__name__}.")

        data = self._serializer.serialize(values)
        rid = self._heap_file.insert_record(data)
        inserted: list[tuple[TableIndex, Any]] = []
        try:
            for index in self._indexes:
                value = values[index.column_ordinal]
                if value is not None:
                    index.tree.insert(value, rid)
                    inserted.append((index, value))
        except Exception:
            for index, value in reversed(inserted):
                try:
                    index.tree.delete(value, rid)
                except Exception:
                    pass
            try:
                self._heap_file.delete_record(rid)
            except Exception:
                pass
            raise
        return rid

    def get(self, record_id: RecordId) -> Tuple:
        """Retrieve a typed Tuple by its RecordId.

        Args:
            record_id: Immutable RecordId specifying (page_id, slot_id).

        Returns:
            Tuple: Deserialized typed tuple bound to self.schema.

        Raises:
            StorageClosedError: If the table or storage is closed.
            RecordNotFoundError: If slot is deleted or unallocated.
            CorruptRecordError: If binary data on page is corrupted.
            SchemaMismatchError: If stored record fingerprint does not match table schema.
        """
        self._check_not_closed()
        data = self._heap_file.get_record(record_id)
        return self._serializer.deserialize(data)

    def delete(self, record_id: RecordId) -> None:
        """Delete a record by its RecordId.

        Args:
            record_id: Immutable RecordId specifying (page_id, slot_id).

        Raises:
            StorageClosedError: If the table or storage is closed.
            RecordNotFoundError: If slot is already deleted or unallocated.
        """
        self._check_not_closed()
        row = self.get(record_id)
        removed: list[tuple[TableIndex, Any]] = []
        try:
            for index in self._indexes:
                value = row[index.column_ordinal]
                if value is None:
                    continue
                if not index.tree.delete(value, record_id):
                    raise CatalogCorruptionError(
                        f"Index '{index.name}' lacks expected entry for record {record_id}."
                    )
                removed.append((index, value))
        except Exception:
            for index, value in removed:
                try:
                    index.tree.insert(value, record_id)
                except Exception:
                    pass
            raise
        try:
            self._heap_file.delete_record(record_id)
        except Exception:
            for index, value in removed:
                try:
                    index.tree.insert(value, record_id)
                except Exception:
                    pass
            raise

    def update(self, record_id: RecordId, row: Tuple) -> RecordId:
        """Replace one row, preserving its RID when its source page can hold it.

        A valid replacement that cannot fit its existing page is relocated by
        this table layer.  Attached indexes are transitioned to the final RID.
        """
        self._check_not_closed()
        if not isinstance(record_id, RecordId):
            raise TypeError(f"Expected RecordId instance, got {type(record_id).__name__}.")
        if not isinstance(row, Tuple):
            raise TypeError(f"Expected Tuple instance, got {type(row).__name__}.")
        if row.schema is not None and row.schema.fingerprint != self._schema.fingerprint:
            raise SchemaMismatchError(
                f"Cannot update Table '{self._name}' with Tuple schema fingerprint "
                f"0x{row.schema.fingerprint:08X}; expected 0x{self._schema.fingerprint:08X}."
            )

        old_row = self.get(record_id)
        old_data = self._serializer.serialize(old_row.values)
        new_data = self._serializer.serialize(row.values)
        old_keys = self._index_keys(old_row)
        new_keys = self._index_keys(row)

        try:
            self._heap_file.update_record(record_id, new_data)
        except InsufficientSpaceError:
            return self._relocate_update(record_id, new_data, old_keys, new_keys)

        actions: list[tuple[str, TableIndex, Any, RecordId]] = []
        try:
            for index, old_key in old_keys:
                new_key = _key_for_index(new_keys, index)
                if old_key == new_key:
                    continue
                if old_key is not None:
                    self._remove_index_entry(index, old_key, record_id)
                    actions.append(("removed", index, old_key, record_id))
                if new_key is not None:
                    self._add_index_entry(index, new_key, record_id)
                    actions.append(("added", index, new_key, record_id))
        except Exception:
            try:
                self._heap_file.update_record(record_id, old_data)
            except Exception:
                pass
            self._undo_index_actions(actions)
            raise
        return record_id

    def _relocate_update(
        self,
        old_rid: RecordId,
        new_data: bytes,
        old_keys: list[tuple[TableIndex, Any]],
        new_keys: list[tuple[TableIndex, Any]],
    ) -> RecordId:
        """Relocate a replacement after same-page capacity is exhausted."""
        new_rid = self._heap_file.insert_record(new_data)
        actions: list[tuple[str, TableIndex, Any, RecordId]] = []
        try:
            # Retain old entries until every new entry exists, minimizing data loss.
            for index, new_key in new_keys:
                if new_key is not None:
                    self._add_index_entry(index, new_key, new_rid)
                    actions.append(("added", index, new_key, new_rid))
            for index, old_key in old_keys:
                if old_key is not None:
                    self._remove_index_entry(index, old_key, old_rid)
                    actions.append(("removed", index, old_key, old_rid))
            self._heap_file.delete_record(old_rid)
        except Exception:
            self._undo_index_actions(actions)
            try:
                self._heap_file.delete_record(new_rid)
            except Exception:
                pass
            raise
        return new_rid

    def _index_keys(self, row: Tuple) -> list[tuple[TableIndex, Any]]:
        return [(index, row[index.column_ordinal]) for index in self._indexes]

    @staticmethod
    def _add_index_entry(index: TableIndex, key: Any, record_id: RecordId) -> None:
        if not index.tree.insert(key, record_id):
            raise CatalogCorruptionError(
                f"Index '{index.name}' already contains entry for record {record_id}."
            )

    @staticmethod
    def _remove_index_entry(index: TableIndex, key: Any, record_id: RecordId) -> None:
        if not index.tree.delete(key, record_id):
            raise CatalogCorruptionError(
                f"Index '{index.name}' lacks expected entry for record {record_id}."
            )

    @staticmethod
    def _undo_index_actions(actions: list[tuple[str, TableIndex, Any, RecordId]]) -> None:
        for action, index, key, record_id in reversed(actions):
            try:
                if action == "added":
                    index.tree.delete(key, record_id)
                else:
                    index.tree.insert(key, record_id)
            except Exception:
                pass

    def scan(self) -> Iterator[PyTuple[RecordId, Tuple]]:
        """Iterate over all active typed records in the table.

        Yields:
            tuple[RecordId, Tuple]: Pair of (record_id, deserialized_tuple).

        Raises:
            StorageClosedError: If the table or storage is closed.
        """
        self._check_not_closed()
        for rid, data in self._heap_file.scan_records():
            yield rid, self._serializer.deserialize(data)

    def count(self) -> int:
        """Return the number of active records in the table via linear scan."""
        self._check_not_closed()
        return sum(1 for _ in self.scan())

    def close(self) -> None:
        """Close this table and release underlying storage resources.

        Flushes dirty pages in the table's BufferPoolManager and closes its PageFile.
        Idempotent; safe to call multiple times.
        """
        if self._closed:
            return

        self._closed = True
        try:
            for index in self._indexes:
                try:
                    index.tree.close()
                except Exception:
                    pass
            bpm = self._heap_file.buffer_pool_manager
            if not bpm.is_closed:
                bpm.close()
            if not bpm.page_file.is_closed:
                bpm.page_file.close()
        finally:
            if self._on_close:
                self._on_close(self)

    def __repr__(self) -> str:
        status = "closed" if self.is_closed else "open"
        return f"Table(id={self._table_id}, name='{self._name}', status='{status}')"


def _key_for_index(keys: list[tuple[TableIndex, Any]], target: TableIndex) -> Any:
    return next(key for index, key in keys if index is target)
