"""Persistent, page-backed B+ tree mapping one typed key domain to RecordIds.

Each tree owns a PageFile and BufferPoolManager.  Page 0 is a versioned
header; pages 1 onward are dedicated leaf or internal nodes.  Leaf and
internal separators use the full ``(key, RecordId)`` ordering, so duplicate
keys remain correct even when they span multiple leaves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Any, Optional, Union

from strata_engine.schema.data_type import DataType
from strata_engine.schema.serializer import INT32_MAX, INT32_MIN, INT64_MAX, INT64_MIN
from strata_engine.storage.buffer_pool import BufferPoolManager
from strata_engine.storage.exceptions import (
    BPlusTreeCorruptionError,
    InvalidKeyError,
    KeyTooLargeError,
    KeyTypeMismatchError,
    StorageClosedError,
    UnsupportedKeyTypeError,
)
from strata_engine.storage.page import PAGE_SIZE, Page
from strata_engine.storage.page_file import PageFile
from strata_engine.storage.page_id import PageId
from strata_engine.storage.record_id import RecordId


HEADER_MAGIC = b"STRBPT19"
HEADER_VERSION = 1
HEADER_FORMAT = ">8sHHQQQQQ"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
NODE_MAGIC = b"BPTN"
NODE_VERSION = 1
NODE_HEADER_FORMAT = ">4sBBHQ"
NODE_HEADER_SIZE = struct.calcsize(NODE_HEADER_FORMAT)
LEAF = 1
INTERNAL = 2
NO_PAGE = (1 << 64) - 1
RID_FORMAT = ">QQ"
RID_SIZE = struct.calcsize(RID_FORMAT)
KEY_LENGTH_FORMAT = ">H"
KEY_LENGTH_SIZE = struct.calcsize(KEY_LENGTH_FORMAT)
CHILD_SIZE = 8

_TYPE_CODES = {
    DataType.INTEGER: 1,
    DataType.BIGINT: 2,
    DataType.BOOLEAN: 3,
    DataType.VARCHAR: 4,
}
_CODE_TYPES = {value: key for key, value in _TYPE_CODES.items()}


@dataclass(frozen=True, slots=True)
class TraversalStats:
    """Deterministic structural work performed by the latest lookup/scan."""

    tree_pages_visited: int = 0
    leaf_entries_examined: int = 0


@dataclass(slots=True)
class _LeafEntry:
    key: object
    record_id: RecordId


@dataclass(slots=True)
class _Node:
    node_type: int
    entries: list[_LeafEntry]
    link: int
    children: Optional[list[int]] = None


class BPlusTree:
    """A persistent B+ tree for one supported :class:`DataType`.

    Empty trees have an allocated empty leaf root and height one.  Internal
    separator entries are the first composite entry of their right child:
    every entry in that child is greater than or equal to the separator.
    Exact duplicate ``(key, RecordId)`` insertions are no-ops and return
    ``False``; all other inserts return ``True``.
    """

    __slots__ = (
        "_path", "_page_file", "_buffer_pool", "_key_type", "_root_page_id",
        "_height", "_entry_count", "_leaf_page_count", "_tree_page_count",
        "_closed", "_header_dirty", "_last_operation_stats",
    )

    def __init__(self, path: Union[Path, str], key_type: Optional[DataType], pool_size: int, create: bool) -> None:
        if type(pool_size) is not int or pool_size < 1:
            raise ValueError("pool_size must be an integer of at least 1.")
        self._path = Path(path).resolve()
        self._closed = False
        self._header_dirty = False
        self._last_operation_stats = TraversalStats()
        self._page_file = PageFile(self._path)
        self._buffer_pool = BufferPoolManager(self._page_file, pool_size=pool_size)
        try:
            if create:
                if self._page_file.page_count != 0:
                    raise FileExistsError(f"Cannot create B+ tree in non-empty file '{self._path}'.")
                self._key_type = self._validate_key_type(key_type)
                self._root_page_id = NO_PAGE
                self._height = 0
                self._entry_count = 0
                self._leaf_page_count = 0
                self._tree_page_count = 1
                header_pid, _ = self._buffer_pool.new_page()
                if int(header_pid) != 0:
                    raise BPlusTreeCorruptionError("New B+ tree header was not allocated at page 0.")
                self._buffer_pool.unpin_page(header_pid, is_dirty=True)
                root_pid = self._allocate_node(_Node(LEAF, [], NO_PAGE))
                self._root_page_id = int(root_pid)
                self._height = 1
                self._leaf_page_count = 1
                self._tree_page_count = 2
                self._write_header()
            else:
                self._read_header(key_type)
        except Exception:
            self.close()
            raise

    @classmethod
    def create(cls, path: Union[Path, str], key_type: DataType, pool_size: int = 10) -> "BPlusTree":
        """Create a new tree at an empty explicit path."""
        return cls(path, key_type, pool_size, create=True)

    @classmethod
    def open(cls, path: Union[Path, str], key_type: Optional[DataType] = None, pool_size: int = 10) -> "BPlusTree":
        """Open an existing tree, optionally requiring its persisted key type."""
        return cls(path, key_type, pool_size, create=False)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def key_type(self) -> DataType:
        return self._key_type

    @property
    def root_page_id(self) -> PageId:
        return PageId(self._root_page_id)

    @property
    def height(self) -> int:
        return self._height

    @property
    def entry_count(self) -> int:
        return self._entry_count

    @property
    def leaf_page_count(self) -> int:
        return self._leaf_page_count

    @property
    def tree_page_count(self) -> int:
        return self._tree_page_count

    @property
    def last_operation_stats(self) -> TraversalStats:
        return self._last_operation_stats

    @property
    def is_closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed or self._buffer_pool.is_closed:
            raise StorageClosedError("Operation attempted on closed BPlusTree.")

    @staticmethod
    def _validate_key_type(key_type: Optional[DataType]) -> DataType:
        if key_type not in _TYPE_CODES:
            raise UnsupportedKeyTypeError(
                "BPlusTree supports only INTEGER, BIGINT, BOOLEAN, and VARCHAR keys."
            )
        assert isinstance(key_type, DataType)
        return key_type

    def _validate_key(self, key: object) -> None:
        if key is None:
            raise InvalidKeyError("B+ tree keys cannot be None.")
        if self._key_type == DataType.INTEGER:
            if type(key) is not int:
                raise InvalidKeyError(f"INTEGER key must be int, got {type(key).__name__}.")
            if not INT32_MIN <= key <= INT32_MAX:
                raise InvalidKeyError("INTEGER key is outside signed 32-bit range.")
        elif self._key_type == DataType.BIGINT:
            if type(key) is not int:
                raise InvalidKeyError(f"BIGINT key must be int, got {type(key).__name__}.")
            if not INT64_MIN <= key <= INT64_MAX:
                raise InvalidKeyError("BIGINT key is outside signed 64-bit range.")
        elif self._key_type == DataType.BOOLEAN:
            if type(key) is not bool:
                raise InvalidKeyError(f"BOOLEAN key must be bool, got {type(key).__name__}.")
        elif self._key_type == DataType.VARCHAR:
            if type(key) is not str:
                raise InvalidKeyError(f"VARCHAR key must be str, got {type(key).__name__}.")
            try:
                encoded = key.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise InvalidKeyError("VARCHAR key is not UTF-8 encodable.") from exc
            if len(encoded) > self.max_key_bytes:
                raise KeyTooLargeError(
                    f"VARCHAR key encodes to {len(encoded)} bytes; maximum is {self.max_key_bytes}."
                )

    @property
    def max_key_bytes(self) -> int:
        """Maximum UTF-8 key size that can also appear in an internal page."""
        return PAGE_SIZE - NODE_HEADER_SIZE - KEY_LENGTH_SIZE - RID_SIZE - CHILD_SIZE

    def _encode_key(self, key: object) -> bytes:
        self._validate_key(key)
        if self._key_type == DataType.INTEGER:
            return struct.pack(">I", int(key) + (1 << 31))
        if self._key_type == DataType.BIGINT:
            return struct.pack(">Q", int(key) + (1 << 63))
        if self._key_type == DataType.BOOLEAN:
            return b"\x01" if key else b"\x00"
        assert isinstance(key, str)
        return key.encode("utf-8")

    def _decode_key(self, data: bytes) -> object:
        try:
            if self._key_type == DataType.INTEGER:
                if len(data) != 4:
                    raise ValueError
                return struct.unpack(">I", data)[0] - (1 << 31)
            if self._key_type == DataType.BIGINT:
                if len(data) != 8:
                    raise ValueError
                return struct.unpack(">Q", data)[0] - (1 << 63)
            if self._key_type == DataType.BOOLEAN:
                if data == b"\x00":
                    return False
                if data == b"\x01":
                    return True
                raise ValueError
            return data.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError, struct.error) as exc:
            raise BPlusTreeCorruptionError("Malformed B+ tree key encoding.") from exc

    @staticmethod
    def _pair(entry: _LeafEntry) -> tuple[object, int, int]:
        return (entry.key, int(entry.record_id.page_id), entry.record_id.slot_id)

    @staticmethod
    def _validate_record_id(record_id: RecordId) -> None:
        if not isinstance(record_id, RecordId):
            raise TypeError(f"Expected RecordId, got {type(record_id).__name__}.")
        if int(record_id.page_id) > NO_PAGE or record_id.slot_id > NO_PAGE:
            raise ValueError("RecordId components exceed persistent unsigned-64-bit encoding.")

    def _leaf_entry_bytes(self, entry: _LeafEntry) -> bytes:
        encoded_key = self._encode_key(entry.key)
        self._validate_record_id(entry.record_id)
        return (
            struct.pack(KEY_LENGTH_FORMAT, len(encoded_key))
            + encoded_key
            + struct.pack(RID_FORMAT, int(entry.record_id.page_id), entry.record_id.slot_id)
        )

    def _leaf_entry_size(self, entry: _LeafEntry) -> int:
        """Return encoded leaf-cell size without constructing a full page."""
        return KEY_LENGTH_SIZE + len(self._encode_key(entry.key)) + RID_SIZE

    def _node_size(self, node: _Node) -> int:
        """Return encoded node size without allocating its padded page image."""
        size = NODE_HEADER_SIZE + sum(self._leaf_entry_size(entry) for entry in node.entries)
        if node.node_type == INTERNAL:
            if node.children is None or len(node.children) != len(node.entries) + 1:
                raise BPlusTreeCorruptionError("Internal B+ tree node has invalid child count.")
            size += len(node.entries) * CHILD_SIZE
        return size

    def _node_bytes(self, node: _Node) -> bytes:
        if node.node_type not in (LEAF, INTERNAL):
            raise BPlusTreeCorruptionError("Invalid B+ tree node type.")
        if len(node.entries) > 0xFFFF:
            raise BPlusTreeCorruptionError("B+ tree node has too many entries.")
        if node.node_type == LEAF:
            payload = b"".join(self._leaf_entry_bytes(entry) for entry in node.entries)
        else:
            if node.children is None or len(node.children) != len(node.entries) + 1:
                raise BPlusTreeCorruptionError("Internal B+ tree node has invalid child count.")
            payload = b"".join(
                self._leaf_entry_bytes(entry) + struct.pack(">Q", node.children[index + 1])
                for index, entry in enumerate(node.entries)
            )
        raw = struct.pack(NODE_HEADER_FORMAT, NODE_MAGIC, NODE_VERSION, node.node_type, len(node.entries), node.link) + payload
        if len(raw) > PAGE_SIZE:
            raise KeyTooLargeError("B+ tree node exceeds one storage page.")
        return raw + b"\x00" * (PAGE_SIZE - len(raw))

    def _decode_node(self, page: Page) -> _Node:
        raw = page.to_bytes()
        try:
            magic, version, node_type, count, link = struct.unpack_from(NODE_HEADER_FORMAT, raw, 0)
        except struct.error as exc:
            raise BPlusTreeCorruptionError("Truncated B+ tree node header.") from exc
        if magic != NODE_MAGIC or version != NODE_VERSION or node_type not in (LEAF, INTERNAL):
            raise BPlusTreeCorruptionError("Invalid B+ tree node header.")
        cursor = NODE_HEADER_SIZE
        entries: list[_LeafEntry] = []
        children: Optional[list[int]] = [link] if node_type == INTERNAL else None
        for _ in range(count):
            if cursor + KEY_LENGTH_SIZE > PAGE_SIZE:
                raise BPlusTreeCorruptionError("Truncated B+ tree key length.")
            key_length = struct.unpack_from(KEY_LENGTH_FORMAT, raw, cursor)[0]
            cursor += KEY_LENGTH_SIZE
            required = key_length + RID_SIZE + (CHILD_SIZE if node_type == INTERNAL else 0)
            if cursor + required > PAGE_SIZE:
                raise BPlusTreeCorruptionError("B+ tree cell extends past page boundary.")
            key = self._decode_key(raw[cursor : cursor + key_length])
            cursor += key_length
            page_id, slot_id = struct.unpack_from(RID_FORMAT, raw, cursor)
            cursor += RID_SIZE
            try:
                entry = _LeafEntry(key, RecordId(page_id, slot_id))
            except Exception as exc:
                raise BPlusTreeCorruptionError("Malformed RecordId in B+ tree node.") from exc
            entries.append(entry)
            if node_type == INTERNAL:
                assert children is not None
                children.append(struct.unpack_from(">Q", raw, cursor)[0])
                cursor += CHILD_SIZE
        if entries != sorted(entries, key=self._pair):
            raise BPlusTreeCorruptionError("B+ tree node entries are not sorted.")
        if node_type == INTERNAL:
            assert children is not None
            if any(child == NO_PAGE or child >= self._tree_page_count for child in children):
                raise BPlusTreeCorruptionError("Internal B+ tree node has invalid child page ID.")
        elif link != NO_PAGE and link >= self._tree_page_count:
            raise BPlusTreeCorruptionError("Leaf B+ tree node has invalid sibling page ID.")
        return _Node(node_type, entries, link, children)

    def _read_node(self, pid: int, stats: Optional[list[int]] = None) -> _Node:
        if pid == NO_PAGE or pid <= 0 or pid >= self._tree_page_count:
            raise BPlusTreeCorruptionError(f"Invalid B+ tree node page ID {pid}.")
        page = self._buffer_pool.fetch_page(PageId(pid))
        try:
            if stats is not None:
                stats[0] += 1
            return self._decode_node(page)
        finally:
            self._buffer_pool.unpin_page(PageId(pid), is_dirty=False)

    def _write_node(self, pid: int, node: _Node) -> None:
        page = self._buffer_pool.fetch_page(PageId(pid))
        dirty = False
        try:
            page.write_bytes(self._node_bytes(node))
            dirty = True
        finally:
            self._buffer_pool.unpin_page(PageId(pid), is_dirty=dirty)

    def _allocate_node(self, node: _Node) -> int:
        pid, page = self._buffer_pool.new_page()
        dirty = False
        try:
            page.write_bytes(self._node_bytes(node))
            dirty = True
            return int(pid)
        finally:
            self._buffer_pool.unpin_page(pid, is_dirty=dirty)

    def _write_header(self) -> None:
        raw = struct.pack(
            HEADER_FORMAT, HEADER_MAGIC, HEADER_VERSION, _TYPE_CODES[self._key_type],
            self._root_page_id, self._height, self._entry_count,
            self._leaf_page_count, self._tree_page_count,
        )
        page = self._buffer_pool.fetch_page(PageId(0))
        dirty = False
        try:
            page.write_bytes(raw + b"\x00" * (PAGE_SIZE - len(raw)))
            dirty = True
        finally:
            self._buffer_pool.unpin_page(PageId(0), is_dirty=dirty)
        self._header_dirty = False

    def _read_header(self, expected_key_type: Optional[DataType]) -> None:
        if self._page_file.page_count < 2:
            raise BPlusTreeCorruptionError("B+ tree file lacks a header and root page.")
        page = self._buffer_pool.fetch_page(PageId(0))
        try:
            magic, version, type_code, root, height, entries, leaves, pages = struct.unpack_from(HEADER_FORMAT, page.to_bytes(), 0)
        except struct.error as exc:
            raise BPlusTreeCorruptionError("Truncated B+ tree header.") from exc
        finally:
            self._buffer_pool.unpin_page(PageId(0), is_dirty=False)
        if magic != HEADER_MAGIC:
            raise BPlusTreeCorruptionError("Invalid B+ tree header magic.")
        if version != HEADER_VERSION:
            raise BPlusTreeCorruptionError(f"Unsupported B+ tree header version {version}.")
        if type_code not in _CODE_TYPES:
            raise BPlusTreeCorruptionError("Invalid B+ tree key type code.")
        self._key_type = _CODE_TYPES[type_code]
        if expected_key_type is not None and self._validate_key_type(expected_key_type) != self._key_type:
            raise KeyTypeMismatchError(
                f"Tree key type is {self._key_type.value}, not expected {expected_key_type.value}."
            )
        if root == NO_PAGE or root == 0 or root >= pages or pages != self._page_file.page_count:
            raise BPlusTreeCorruptionError("B+ tree header has impossible root/page-count metadata.")
        if height < 1 or leaves < 1 or pages < 2:
            raise BPlusTreeCorruptionError("B+ tree header has invalid structural counters.")
        self._root_page_id, self._height = root, height
        self._entry_count, self._leaf_page_count, self._tree_page_count = entries, leaves, pages

    def _find_leaf(self, pair: tuple[object, int, int], stats: Optional[list[int]] = None) -> tuple[int, _Node, list[int]]:
        pid = self._root_page_id
        path: list[int] = []
        while True:
            node = self._read_node(pid, stats)
            if node.node_type == LEAF:
                return pid, node, path
            assert node.children is not None
            path.append(pid)
            index = 0
            while index < len(node.entries) and self._pair(node.entries[index]) <= pair:
                index += 1
            pid = node.children[index]

    @staticmethod
    def _insert_index(entries: list[_LeafEntry], pair: tuple[object, int, int]) -> int:
        low, high = 0, len(entries)
        while low < high:
            middle = (low + high) // 2
            if BPlusTree._pair(entries[middle]) < pair:
                low = middle + 1
            else:
                high = middle
        return low

    def _fits(self, node: _Node) -> bool:
        return self._node_size(node) <= PAGE_SIZE

    def _split_leaf(self, node: _Node) -> tuple[_Node, _Node]:
        sizes = [self._leaf_entry_size(entry) for entry in node.entries]
        payload_size = sum(sizes)
        left_size = 0
        best: Optional[tuple[int, _Node, _Node]] = None
        for index in range(1, len(node.entries)):
            left_size += sizes[index - 1]
            right_size = payload_size - left_size
            left = _Node(LEAF, node.entries[:index], NO_PAGE)
            right = _Node(LEAF, node.entries[index:], node.link)
            if NODE_HEADER_SIZE + left_size <= PAGE_SIZE and NODE_HEADER_SIZE + right_size <= PAGE_SIZE:
                balance = abs(left_size - right_size)
                if best is None or balance < best[0]:
                    best = (balance, left, right)
        if best is None:
            raise KeyTooLargeError("B+ tree leaf cannot be split into two valid pages.")
        return best[1], best[2]

    def _split_internal(self, node: _Node) -> tuple[_Node, _LeafEntry, _Node]:
        assert node.children is not None
        sizes = [self._leaf_entry_size(entry) + CHILD_SIZE for entry in node.entries]
        payload_size = sum(sizes)
        left_size = 0
        best: Optional[tuple[int, _Node, _LeafEntry, _Node]] = None
        for index in range(len(node.entries)):
            left = _Node(INTERNAL, node.entries[:index], node.children[0], node.children[: index + 1])
            right = _Node(INTERNAL, node.entries[index + 1 :], node.children[index + 1], node.children[index + 1 :])
            right_size = payload_size - left_size - sizes[index]
            if NODE_HEADER_SIZE + left_size <= PAGE_SIZE and NODE_HEADER_SIZE + right_size <= PAGE_SIZE:
                balance = abs(left_size - right_size)
                if best is None or balance < best[0]:
                    best = (balance, left, node.entries[index], right)
            left_size += sizes[index]
        if best is None:
            raise KeyTooLargeError("B+ tree internal node cannot be split into two valid pages.")
        return best[1], best[2], best[3]

    def insert(self, key: object, record_id: RecordId) -> bool:
        """Insert one ``(key, RecordId)`` pair; return False for an exact duplicate."""
        self._check_open()
        self._validate_key(key)
        self._validate_record_id(record_id)
        pair = (key, int(record_id.page_id), record_id.slot_id)
        leaf_pid, leaf, path = self._find_leaf(pair)
        position = self._insert_index(leaf.entries, pair)
        if position < len(leaf.entries) and self._pair(leaf.entries[position]) == pair:
            return False
        leaf.entries.insert(position, _LeafEntry(key, record_id))
        if self._fits(leaf):
            self._write_node(leaf_pid, leaf)
        else:
            left, right = self._split_leaf(leaf)
            right_pid = self._allocate_node(right)
            left.link = right_pid
            self._write_node(leaf_pid, left)
            self._leaf_page_count += 1
            self._tree_page_count += 1
            self._propagate_split(leaf_pid, right.entries[0], right_pid, path)
        self._entry_count += 1
        self._header_dirty = True
        return True

    def _propagate_split(self, left_pid: int, separator: _LeafEntry, right_pid: int, path: list[int]) -> None:
        while path:
            parent_pid = path.pop()
            parent = self._read_node(parent_pid)
            assert parent.children is not None
            try:
                child_index = parent.children.index(left_pid)
            except ValueError as exc:
                raise BPlusTreeCorruptionError("Split child is absent from its parent.") from exc
            parent.entries.insert(child_index, separator)
            parent.children.insert(child_index + 1, right_pid)
            if self._fits(parent):
                self._write_node(parent_pid, parent)
                return
            left, promoted, right = self._split_internal(parent)
            new_right_pid = self._allocate_node(right)
            self._write_node(parent_pid, left)
            self._tree_page_count += 1
            left_pid, separator, right_pid = parent_pid, promoted, new_right_pid
        root = _Node(INTERNAL, [separator], left_pid, [left_pid, right_pid])
        new_root_pid = self._allocate_node(root)
        self._root_page_id = new_root_pid
        self._height += 1
        self._tree_page_count += 1

    def search(self, key: object) -> tuple[RecordId, ...]:
        """Return RecordIds for one key, sorted by their persistent RecordId."""
        self._check_open()
        self._validate_key(key)
        stats = [0, 0]
        pid, leaf, _ = self._find_leaf((key, 0, 0), stats)
        results: list[RecordId] = []
        while True:
            for entry in leaf.entries:
                stats[1] += 1
                if entry.key < key:
                    continue
                if entry.key > key:
                    self._last_operation_stats = TraversalStats(*stats)
                    return tuple(results)
                results.append(entry.record_id)
            if leaf.link == NO_PAGE:
                self._last_operation_stats = TraversalStats(*stats)
                return tuple(results)
            pid = leaf.link
            leaf = self._read_node(pid, stats)

    def scan_range(
        self,
        lower: Optional[object] = None,
        upper: Optional[object] = None,
        *,
        lower_inclusive: bool = True,
        upper_inclusive: bool = True,
    ) -> tuple[tuple[object, RecordId], ...]:
        """Return ordered ``(key, RecordId)`` entries within optional bounds."""
        self._check_open()
        if type(lower_inclusive) is not bool or type(upper_inclusive) is not bool:
            raise TypeError("Range inclusivity flags must be bool.")
        if lower is not None:
            self._validate_key(lower)
        if upper is not None:
            self._validate_key(upper)
        if lower is not None and upper is not None and lower > upper:
            self._last_operation_stats = TraversalStats()
            return ()
        stats = [0, 0]
        if lower is None:
            pid, leaf, _ = self._find_leaf((self._minimum_key(), 0, 0), stats)
        else:
            pid, leaf, _ = self._find_leaf((lower, 0, 0), stats)
        results: list[tuple[object, RecordId]] = []
        while True:
            for entry in leaf.entries:
                stats[1] += 1
                if lower is not None and (entry.key < lower or (entry.key == lower and not lower_inclusive)):
                    continue
                if upper is not None and (entry.key > upper or (entry.key == upper and not upper_inclusive)):
                    self._last_operation_stats = TraversalStats(*stats)
                    return tuple(results)
                results.append((entry.key, entry.record_id))
            if leaf.link == NO_PAGE:
                self._last_operation_stats = TraversalStats(*stats)
                return tuple(results)
            pid = leaf.link
            leaf = self._read_node(pid, stats)

    def _minimum_key(self) -> object:
        if self._key_type in (DataType.INTEGER, DataType.BIGINT):
            return INT32_MIN if self._key_type == DataType.INTEGER else INT64_MIN
        if self._key_type == DataType.BOOLEAN:
            return False
        return ""

    def validate_structure(self) -> None:
        """Validate reachable ordering, depth, leaf chain, and persisted counters."""
        self._check_open()
        leaves: list[tuple[int, _Node]] = []
        seen: set[int] = set()
        depths: set[int] = set()

        def subtree_min(pid: int) -> _LeafEntry:
            node = self._read_node(pid)
            while node.node_type == INTERNAL:
                assert node.children is not None
                node = self._read_node(node.children[0])
            if not node.entries:
                raise BPlusTreeCorruptionError("Non-root B+ tree subtree has an empty leaf.")
            return node.entries[0]

        def visit(pid: int, depth: int) -> None:
            if pid in seen:
                raise BPlusTreeCorruptionError("B+ tree contains a repeated child page.")
            seen.add(pid)
            node = self._read_node(pid)
            if node.node_type == LEAF:
                leaves.append((pid, node))
                depths.add(depth)
                return
            assert node.children is not None
            for index, child in enumerate(node.children):
                visit(child, depth + 1)
                if index > 0:
                    if self._pair(subtree_min(child)) != self._pair(node.entries[index - 1]):
                        raise BPlusTreeCorruptionError("Internal separator does not equal its right child minimum.")

        visit(self._root_page_id, 1)
        if depths != {self._height}:
            raise BPlusTreeCorruptionError("B+ tree leaves are not all at header height.")
        ordered_chain: list[_LeafEntry] = []
        pid = leaves[0][0]
        chain_seen: set[int] = set()
        chain_order: list[int] = []
        while pid != NO_PAGE:
            if pid in chain_seen:
                raise BPlusTreeCorruptionError("B+ tree leaf chain contains a cycle.")
            chain_seen.add(pid)
            chain_order.append(pid)
            node = self._read_node(pid)
            if node.node_type != LEAF:
                raise BPlusTreeCorruptionError("B+ tree leaf chain references an internal node.")
            ordered_chain.extend(node.entries)
            pid = node.link
        if [pid for pid, _ in leaves] != chain_order:
            raise BPlusTreeCorruptionError("B+ tree leaf chain differs from reachable leaves.")
        if ordered_chain != sorted(ordered_chain, key=self._pair):
            raise BPlusTreeCorruptionError("B+ tree leaf chain is not globally sorted.")
        if len(ordered_chain) != self._entry_count or len(leaves) != self._leaf_page_count:
            raise BPlusTreeCorruptionError("B+ tree header counters disagree with reachable structure.")

    def close(self) -> None:
        """Flush and close the tree's dedicated buffer pool and page file."""
        if self._closed:
            return
        try:
            if self._header_dirty:
                self._write_header()
            if not self._buffer_pool.is_closed:
                self._buffer_pool.close()
        finally:
            self._closed = True
            if not self._page_file.is_closed:
                self._page_file.close()

    def __enter__(self) -> "BPlusTree":
        self._check_open()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
