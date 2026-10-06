"""Persistent index descriptors and table-local operational bindings."""

from dataclasses import dataclass

from strata_engine.schema.data_type import DataType
from strata_engine.storage.b_plus_tree import BPlusTree
from strata_engine.storage.record_id import RecordId


@dataclass(frozen=True, slots=True)
class IndexMetadata:
    """Catalog-owned persistent identity for one single-column index."""

    index_id: int
    name: str
    table_id: int
    column_ordinal: int
    key_type: DataType
    index_rid: RecordId


@dataclass(slots=True)
class TableIndex:
    """Open tree binding owned and closed by a :class:`Table`."""

    index_id: int
    name: str
    column_ordinal: int
    key_type: DataType
    tree: BPlusTree
