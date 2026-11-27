"""Разбор ответа модели: THOUGHT / ACTION / INPUT / FINAL."""

from __future__ import annotations

_LABELS = (
    ("THOUGHT:", "thought"),
    ("ACTION:", "action"),
    ("INPUT:", "input"),
    ("FINAL:", "final"),
)


class ReactParser:
    def __init__(self) -> None:
        self.pending = ""
        self.mode: str | None = None
        self._thought_parts: list[str] = []
        self._action_parts: list[str] = []
        self._input_parts: list[str] = []
        self._final_parts: list[str] = []
        self._raw_parts: list[str] = []
        self.thought_open = False

    @property
    def thought(self) -> str:
        return "".join(self._thought_parts).strip()

    @property
    def action(self) -> str:
        text = "".join(self._action_parts).strip()
        if not text:
            return ""
        token = text.split()[0].strip("`").lower()
        return token.strip(".,;:")

    @property
    def action_input(self) -> str:
        explicit = "".join(self._input_parts).strip()
        source = explicit or "".join(self._action_parts).strip()
        if not source:
            return ""
        parts = source.split()
        if explicit:
            token = parts[0]
        elif len(parts) >= 2:
            token = parts[1]
        else:
            return ""
        return token.strip("`").strip()[:2000]

    @property
    def final(self) -> str:
        return "".join(self._final_parts).strip()

    @property
    def raw(self) -> str:
        return "".join(self._raw_parts)

    def feed(self, token: str) -> list[dict]:
        if not token:
            return []
        token = token.replace("\r\n", "\n").replace("\r", "\n")
        self._raw_parts.append(token)
        self.pending += token
        if self.mode is None:
            self.pending = self.pending.lstrip(" \t\ufeff")
        events: list[dict] = []
        self._drain(events)
        return events

    def finish(self) -> list[dict]:
        events: list[dict] = []
        if self.pending:
            if self.mode is None and self.pending.strip():
                self._set_mode("final", events)
            self._append_text(self.pending, events)
            self.pending = ""
        if self.thought_open:
            events.append({"type": "thought_end"})
            self.thought_open = False
        return events

    def _drain(self, events: list[dict]) -> None:
        guard = 0
        while self.pending:
            guard += 1
            if guard > 10000:
                self._append_text(self.pending, events)
                self.pending = ""
                return
            match = self._next_label(self.pending)
            if match is not None:
                index, size, mode = match
                if index:
                    preface = self.pending[:index]
                    if self.mode is None:
                        if preface.strip():
                            self._set_mode("final", events)
                            self._append_text(preface, events)
                    else:
                        self._append_text(preface, events)
                self.pending = self.pending[index + size :]
                if self.pending.startswith(" "):
                    self.pending = self.pending[1:]
                if mode == "final" and self.pending.startswith("\n"):
                    self.pending = self.pending[1:]
                self._set_mode(mode, events)
                continue
            hold = self._hold_length(self.pending)
            ready_len = len(self.pending) - hold
            if ready_len <= 0:
                return
            if self.mode is None and len(self.pending) < 80:
                return
            if self.mode is None:
                self._set_mode("final", events)
            ready = self.pending[:ready_len]
            self._append_text(ready, events)
            self.pending = self.pending[ready_len :]

    def _set_mode(self, mode: str, events: list[dict]) -> None:
        if self.thought_open and mode != "thought":
            events.append({"type": "thought_end"})
            self.thought_open = False
        self.mode = mode
        if mode == "thought":
            self.thought_open = True

    def _append_text(self, text: str, events: list[dict]) -> None:
        if not text or self.mode is None:
            return
        if self.mode == "thought":
            self._thought_parts.append(text)
            events.append({"type": "thought_delta", "text": text})
        elif self.mode == "action":
            self._action_parts.append(text)
        elif self.mode == "input":
            self._input_parts.append(text)
        elif self.mode == "final":
            self._final_parts.append(text)
            events.append({"type": "result_delta", "text": text})

    def _next_label(self, text: str) -> tuple[int, int, str] | None:
        upper = text.upper()
        best: tuple[int, int, str] | None = None
        for label, mode in _LABELS:
            start = 0
            while True:
                index = upper.find(label, start)
                if index < 0:
                    break
                at_line = index == 0 or text[index - 1] == "\n"
                if at_line:
                    if best is None or index < best[0]:
                        best = (index, len(label), mode)
                    break
                start = index + 1
        return best

    def _hold_length(self, text: str) -> int:
        upper = text.upper()
        hold = 0
        probes = [label for label, _ in _LABELS]
        probes += ["\n" + label for label, _ in _LABELS]
        for probe in probes:
            max_k = min(len(probe) - 1, len(upper))
            for length in range(max_k, 0, -1):
                if not probe.startswith(upper[-length:]):
                    continue
                if probe[0] == "\n":
                    hold = max(hold, length)
                else:
                    before = len(upper) - length - 1
                    if before < 0 or upper[before] == "\n":
                        hold = max(hold, length)
                break
        return hold
