"""Buffer pool page replacement policies.

Provides the Replacer abstract base class and ClockReplacer implementation
using the deterministic CLOCK (Second-Chance) eviction algorithm.
"""

from abc import ABC, abstractmethod
from typing import List, Optional


class Replacer(ABC):
    """Abstract base class for buffer frame replacement policies."""

    @abstractmethod
    def victim(self) -> Optional[int]:
        """Select and return a frame ID to evict, or None if no frames can be evicted."""
        raise NotImplementedError

    @abstractmethod
    def pin(self, frame_id: int) -> None:
        """Remove a frame from victim eligibility when pinned."""
        raise NotImplementedError

    @abstractmethod
    def unpin(self, frame_id: int) -> None:
        """Add a frame to victim eligibility when unpinned."""
        raise NotImplementedError

    @abstractmethod
    def size(self) -> int:
        """Return the number of unpinned frames currently tracked."""
        raise NotImplementedError


class ClockReplacer(Replacer):
    """CLOCK (Second-Chance) replacement policy for buffer pool frames.

    Tracks unpinned frames and determines which frame should be evicted
    using a circular clock hand with reference bits.
    """

    __slots__ = ("_capacity", "_clock_hand", "_in_replacer", "_ref_bits")

    def __init__(self, capacity: int) -> None:
        """Initialize a ClockReplacer with a fixed capacity.

        Args:
            capacity: Maximum number of frames that can be tracked (must be >= 1).

        Raises:
            ValueError: If capacity < 1.
            TypeError: If capacity is not an int or is a bool.
        """
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError(f"capacity must be an integer, got {type(capacity).__name__}.")
        if capacity < 1:
            raise ValueError(f"capacity must be at least 1, got {capacity}.")

        self._capacity: int = capacity
        self._clock_hand: int = 0
        self._in_replacer: List[bool] = [False] * capacity
        self._ref_bits: List[bool] = [False] * capacity

    @property
    def capacity(self) -> int:
        """Return the maximum frame capacity of the replacer."""
        return self._capacity

    def _validate_frame_id(self, frame_id: int) -> None:
        """Validate that frame_id is a valid integer in [0, capacity)."""
        if isinstance(frame_id, bool) or not isinstance(frame_id, int):
            raise TypeError(f"frame_id must be an integer, got {type(frame_id).__name__}.")
        if frame_id < 0 or frame_id >= self._capacity:
            raise ValueError(
                f"frame_id {frame_id} out of bounds [0, {self._capacity})."
            )

    def victim(self) -> Optional[int]:
        """Select and return a victim frame ID to evict using the CLOCK algorithm.

        Iterates starting from current clock hand position:
        - If a frame is in the replacer:
          - If ref_bit is True, clears it to False (second chance).
          - If ref_bit is False, selects this frame as the victim, removes it
            from the replacer, advances the clock hand, and returns frame_id.

        Returns:
            int frame_id of selected victim, or None if no frames are unpinned.
        """
        if self.size() == 0:
            return None

        # At most two full passes around the clock are required
        total_checks = self._capacity * 2
        while total_checks > 0:
            curr_frame = self._clock_hand
            self._clock_hand = (self._clock_hand + 1) % self._capacity
            total_checks -= 1

            if self._in_replacer[curr_frame]:
                if self._ref_bits[curr_frame]:
                    # Given a second chance; clear reference bit
                    self._ref_bits[curr_frame] = False
                else:
                    # Found victim: clear from replacer and return
                    self._in_replacer[curr_frame] = False
                    return curr_frame

        return None

    def pin(self, frame_id: int) -> None:
        """Remove a frame from victim eligibility when pinned.

        Args:
            frame_id: Frame index in [0, capacity).
        """
        self._validate_frame_id(frame_id)
        self._in_replacer[frame_id] = False
        self._ref_bits[frame_id] = False

    def unpin(self, frame_id: int) -> None:
        """Add a frame to victim eligibility when unpinned.

        Sets the reference bit to True.

        Args:
            frame_id: Frame index in [0, capacity).
        """
        self._validate_frame_id(frame_id)
        self._in_replacer[frame_id] = True
        self._ref_bits[frame_id] = True

    def size(self) -> int:
        """Return the number of unpinned frames currently tracked."""
        return sum(1 for is_in in self._in_replacer if is_in)

    def contains(self, frame_id: int) -> bool:
        """Check whether a frame is currently eligible for eviction."""
        self._validate_frame_id(frame_id)
        return self._in_replacer[frame_id]

    def __repr__(self) -> str:
        return (
            f"ClockReplacer(capacity={self._capacity}, "
            f"unpinned={self.size()}, hand={self._clock_hand})"
        )
