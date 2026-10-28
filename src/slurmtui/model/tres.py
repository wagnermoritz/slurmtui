"""A parsed trackable-resource (TRES) string."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TRES:
    """``cpu=16,mem=63000M,gres/gpu=4,gres/gpu:a40=4`` as numbers.

    Built by :func:`slurmtui.slurm.parsers.common.parse_tres`.
    """

    cpu: int = 0
    mem: int = 0
    node: int = 0
    billing: int = 0
    gpu: int = 0
    gpu_types: dict[str, int] = field(default_factory=dict)
    other: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (self.cpu or self.mem or self.node or self.gpu or self.other)

    @property
    def gpu_type(self) -> str | None:
        if not self.gpu_types:
            return None
        return max(self.gpu_types.items(), key=lambda item: item[1])[0]
