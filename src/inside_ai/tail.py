from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

_SIG_BYTES = 256


@dataclass
class Chunk:
    offset: int
    line: bytes


class FileTail:
    """JSONL 파일에서 완성된 줄만 증분으로 읽는다.

    - 마지막 줄이 아직 쓰는 중이면(개행 없음) 다음 poll까지 보류한다.
    - 한 번에 최대 max_read 바이트만 읽는다. 남은 부분은 다음 poll에서 이어 읽는다.
    - 파일이 줄거나, 교체되거나(inode), 이미 읽은 구간의 앞·끝 바이트가 바뀌면
      처음부터 다시 읽고 reset=True를 알린다. 중복 제거는 호출자가 key로 처리한다.
    """

    def __init__(self, path: Path, start_at: int | None = None, max_read: int = 8 << 20):
        """start_at: 이 바이트 위치 이전의 완성된 줄은 건너뛴다(None이면 처음부터)."""
        self.path = path
        self.max_read = max_read
        self.offset = 0
        self._ino: int | None = None
        self._sig: bytes | None = None
        self._stamp: tuple | None = None
        self.resets = 0
        if start_at:
            try:
                st = path.stat()
            except FileNotFoundError:
                return
            self._ino = st.st_ino
            self.offset = self._last_newline_end(min(start_at, st.st_size))
            self._sig = self._signature(self.offset)

    @classmethod
    def at_end(cls, path: Path, **kw) -> "FileTail":
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            size = 0
        return cls(path, start_at=size, **kw)

    def _signature(self, offset: int) -> bytes | None:
        """이미 읽은 구간 [0, offset)의 앞·끝 바이트 지문."""
        if offset == 0:
            return None
        try:
            # 버퍼링 없이 읽어야 poll마다 수십 KB씩 미리 읽지 않는다.
            with self.path.open("rb", buffering=0) as f:
                head = f.read(min(_SIG_BYTES, offset))
                f.seek(max(0, offset - _SIG_BYTES))
                tail = f.read(min(_SIG_BYTES, offset))
        except FileNotFoundError:
            return None
        return hashlib.sha256(head + b"\0" + tail).digest()

    def _last_newline_end(self, size: int) -> int:
        """size 이전의 마지막 개행 직후 위치. 쓰는 중인 마지막 줄은 다음 poll에서 읽는다."""
        with self.path.open("rb") as f:
            pos = size
            while pos > 0:
                step = min(65536, pos)
                pos -= step
                f.seek(pos)
                block = f.read(step)
                i = block.rfind(b"\n")
                if i >= 0:
                    return pos + i + 1
        return 0

    def poll(self) -> tuple[list[Chunk], bool]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return [], False
        stamp = (st.st_ino, st.st_size, st.st_mtime_ns)
        if stamp == self._stamp:
            return [], False
        reset = False
        if (
            (self._ino is not None and st.st_ino != self._ino)
            or st.st_size < self.offset
            or (self._sig is not None and self._signature(self.offset) != self._sig)
        ):
            self.offset = 0
            self._sig = None
            self.resets += 1
            reset = True
        self._ino = st.st_ino
        if st.st_size == self.offset:
            self._stamp = stamp
            return [], reset
        with self.path.open("rb") as f:
            f.seek(self.offset)
            remaining = st.st_size - self.offset
            data = f.read(min(remaining, self.max_read))
            # 한 줄이 max_read보다 길면 개행이 나올 때까지 더 읽는다.
            while b"\n" not in data and len(data) < remaining:
                data += f.read(min(remaining - len(data), self.max_read))
        out: list[Chunk] = []
        pos = 0
        while True:
            nl = data.find(b"\n", pos)
            if nl < 0:
                break
            line = data[pos:nl]
            if line.strip():
                out.append(Chunk(self.offset + pos, line))
            pos = nl + 1
        self.offset += pos
        if pos:
            self._sig = self._signature(self.offset)
        if self.offset == st.st_size:
            self._stamp = stamp
        return out, reset


def file_mtime(path: Path) -> float:
    try:
        return os.stat(path).st_mtime
    except FileNotFoundError:
        return 0.0
