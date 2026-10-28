"""Apply the site configuration to parsed records: node groups, hardware labels, resource classes."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any

from slurmtui.config.schema import Config, HardwareRule, HardwareTypeConfig, NodeGroup
from slurmtui.model.records import Job, Node, Partition, UsageRecord
from slurmtui.patterns import any_matches, pattern_match

log = logging.getLogger(__name__)


class _Captures:
    """Exposes regex groups as attributes so ``{feature.1}`` works in ``str.format``."""

    def __init__(self, match: re.Match[str] | None, whole: str) -> None:
        self._match = match
        self._whole = whole

    def __getattr__(self, name: str) -> str:
        if name.isdigit():
            index = int(name)
            if index == 0:
                return self._match.group(0) if self._match else self._whole
            if self._match is None or index > (self._match.re.groups or 0):
                return ""
            return self._match.group(index) or ""
        raise AttributeError(name)

    def __str__(self) -> str:
        return self._whole

    def __format__(self, spec: str) -> str:
        return format(self._whole, spec)


class _SafeContext(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def _render(template: str, context: dict[str, Any]) -> str:
    try:
        return template.format_map(_SafeContext(context)).strip()
    except (ValueError, IndexError, AttributeError) as exc:
        log.warning("bad label template %r: %s", template, exc)
        return ""


class Deriver:
    """Derivation rules compiled from a :class:`Config`."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.groups: Sequence[NodeGroup] = config.node_groups
        self.ungrouped = config.ungrouped_name
        self._node_cache: dict[str, str] = {}
        self._partition_cache: dict[str, str] = {}

    # -- node groups ----------------------------------------------------------

    def group_for_node(self, name: str) -> str:
        cached = self._node_cache.get(name)
        if cached is None:
            cached = self.ungrouped
            for group in self.groups:
                if any_matches(group.nodes, name):
                    cached = group.name
                    break
            self._node_cache[name] = cached
        return cached

    def group_for_partition(self, partition: str) -> str:
        cached = self._partition_cache.get(partition)
        if cached is None:
            cached = self.ungrouped
            for group in self.groups:
                if any_matches(group.partitions, partition):
                    cached = group.name
                    break
            self._partition_cache[partition] = cached
        return cached

    def group_for_job(self, node_list: Sequence[str], partition: str) -> str:
        if node_list:
            return self.group_for_node(node_list[0])
        # a job may list several partitions; the first one that maps wins
        for candidate in partition.split(","):
            group = self.group_for_partition(candidate.strip())
            if group != self.ungrouped:
                return group
        return self.ungrouped

    # -- hardware labels ------------------------------------------------------

    def _match_rule(self, rule: HardwareRule, node: Node) -> dict[str, Any] | None:
        context: dict[str, Any] = {}
        if rule.gres_type is not None:
            if node.gpu_gres_type is None:
                return None
            match = pattern_match(rule.gres_type, node.gpu_gres_type)
            if match is None:
                return None
            context["gres_type"] = _Captures(match, node.gpu_gres_type)
        if rule.feature is not None:
            hit = None
            for token in node.features:
                match = pattern_match(rule.feature, token)
                if match is not None:
                    hit = _Captures(match, token)
                    break
            if hit is None:
                return None
            context["feature"] = hit
        if rule.features is not None:
            joined = ",".join(node.features)
            match = pattern_match(rule.features, joined)
            if match is None:
                return None
            context["features"] = _Captures(match, joined)
        if rule.node is not None:
            match = pattern_match(rule.node, node.name)
            if match is None:
                return None
            context["node"] = _Captures(match, node.name)
        if rule.partition is not None:
            hit = None
            for partition in node.partitions:
                match = pattern_match(rule.partition, partition)
                if match is not None:
                    hit = _Captures(match, partition)
                    break
            if hit is None:
                return None
            context["partition"] = hit
        return context

    def _base_context(self, node: Node) -> dict[str, Any]:
        return {
            "gres_type": node.gpu_gres_type or "",
            "node": node.name,
            "arch": node.arch or "",
            "cpus": node.cpus_total,
            "sockets": node.sockets,
            "cores": node.cores_per_socket,
            "threads": node.threads_per_core,
        }

    def _label(self, kind: HardwareTypeConfig, node: Node) -> str:
        base = self._base_context(node)
        for rule in kind.rules:
            context = self._match_rule(rule, node)
            if context is not None:
                label = _render(rule.label, {**base, **context})
                if label:
                    return label
        return _render(kind.fallback, base)

    def gpu_type(self, node: Node) -> str | None:
        if not node.gpus_total:
            return None
        return self._label(self.config.hardware.gpu_type, node) or None

    def cpu_type(self, node: Node) -> str:
        return self._label(self.config.hardware.cpu_type, node)

    # -- resource classes -----------------------------------------------------

    def is_gpu_job(self, partition: str, gpus: int) -> bool:
        usage = self.config.usage
        if usage.gpu_hours_when == "partition":
            return any(any_matches(usage.gpu_partitions, part.strip()) for part in partition.split(","))
        return gpus > 0

    # -- apply ---------------------------------------------------------------

    def derive_nodes(self, nodes: Iterable[Node], partitions: Iterable[Partition]) -> list[Node]:
        by_name = {partition.name: partition for partition in partitions}
        result: list[Node] = []
        for node in nodes:
            max_time: timedelta | None = None
            avail = "up"
            for name in node.partitions:
                partition = by_name.get(name)
                if partition is None:
                    continue
                if partition.state != "UP":
                    avail = "down"
                if partition.max_time is not None and (max_time is None or partition.max_time > max_time):
                    max_time = partition.max_time
            result.append(
                replace(
                    node,
                    node_group=self.group_for_node(node.name),
                    gpu_type=self.gpu_type(node),
                    cpu_type=self.cpu_type(node),
                    max_time=max_time,
                    avail=avail,
                )
            )
        return result

    def derive_jobs(self, jobs: Iterable[Job]) -> list[Job]:
        return [
            replace(
                job,
                node_group=self.group_for_job(job.node_list, job.partition),
                is_gpu_job=self.is_gpu_job(job.partition, job.gpus),
            )
            for job in jobs
        ]

    def usage_group(self, record: UsageRecord) -> str:
        return self.group_for_job(record.node_list, record.partition)
