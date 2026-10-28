"""Node state parsing and the compact (sinfo-style) rendering."""

from __future__ import annotations

from dataclasses import dataclass

BASE_ABBREVIATIONS = {
    "idle": "idle",
    "mixed": "mix",
    "allocated": "alloc",
    "allocated+": "alloc+",
    "down": "down",
    "error": "err",
    "future": "futr",
    "unknown": "unk",
    "completing": "comp",
    "reserved": "resv",
    "planned": "plnd",
    "maint": "maint",
    "drained": "drain",
    "draining": "drng",
    "fail": "fail",
    "failing": "failg",
    "perfctrs": "npc",
    "power_down": "pow_dn",
    "power_up": "pow_up",
}

# compact label -> style key in [styles.node_state]
LABEL_STYLE_KEYS = {
    "idle": "idle",
    "mix": "mixed",
    "alloc": "allocated",
    "comp": "completing",
    "plnd": "planned",
    "resv": "reserved",
    "down": "down",
    "drain": "drained",
    "drng": "draining",
    "fail": "fail",
    "failg": "failing",
    "maint": "maint",
    "unk": "unknown",
    "err": "error",
    "futr": "future",
}

# flag -> (sinfo suffix character, style key in [styles.node_state_flags])
FLAG_SUFFIXES: dict[str, str] = {
    "not_responding": "*",
    "powered_down": "~",
    "powering_up": "#",
    "powering_down": "%",
    "power_down": "!",
    "maintenance": "$",
    "reboot_requested": "@",
    "reboot_issued": "^",
    "planned": "-",
    "invalid_reg": "+",
}

# Flags whose presence changes the base label, like sinfo does.
_LABEL_FLAGS = ("maintenance", "drain", "fail", "completing", "reserved")


@dataclass(frozen=True)
class NodeState:
    base: str
    flags: frozenset[str]

    @classmethod
    def parse(cls, text: str | None) -> NodeState:
        """Parse ``IDLE+CLOUD+POWERED_DOWN`` (scontrol) or ``idle~`` (sinfo compact)."""
        if not text:
            return cls("unknown", frozenset())
        text = text.strip()
        if "+" in text or text.isupper():
            parts = [part.strip().lower() for part in text.split("+") if part.strip()]
            return cls(parts[0] if parts else "unknown", frozenset(parts[1:]))
        return cls._parse_compact(text)

    @classmethod
    def _parse_compact(cls, text: str) -> NodeState:
        flags: set[str] = set()
        suffix_to_flag = {suffix: flag for flag, suffix in FLAG_SUFFIXES.items()}
        while text and text[-1] in suffix_to_flag:
            flags.add(suffix_to_flag[text[-1]])
            text = text[:-1]
        text = text.lower()
        inverse = {abbr: base for base, abbr in BASE_ABBREVIATIONS.items()}
        base = inverse.get(text, text)
        if base == "drained":
            base, flags = "idle", flags | {"drain"}
        elif base == "draining":
            base, flags = "mixed", flags | {"drain"}
        return cls(base, frozenset(flags))

    @property
    def label(self) -> str:
        """Compact base label as sinfo prints it (``idle``, ``mix``, ``drng``, ...)."""
        busy = self.base in {"allocated", "mixed"} or "completing" in self.flags
        if "maintenance" in self.flags or self.base == "maint":
            return "maint"
        if "drain" in self.flags:
            return "drng" if busy else "drain"
        if "fail" in self.flags:
            return "failg" if busy else "fail"
        if "completing" in self.flags:
            return "comp"
        if "reserved" in self.flags:
            return "resv"
        return BASE_ABBREVIATIONS.get(self.base, self.base)

    @property
    def suffix(self) -> str:
        return "".join(char for flag, char in FLAG_SUFFIXES.items() if flag in self.flags)

    @property
    def compact(self) -> str:
        return f"{self.label}{self.suffix}"

    @property
    def long(self) -> str:
        return "+".join([self.base.upper(), *sorted(flag.upper() for flag in self.flags)])

    @property
    def style_key(self) -> str:
        return LABEL_STYLE_KEYS.get(self.label, self.base)

    @property
    def flag_style_keys(self) -> list[str]:
        return [flag for flag in FLAG_SUFFIXES if flag in self.flags]

    def __str__(self) -> str:
        return self.compact
