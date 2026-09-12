"""コピー元ファイルのSHA-256計算。

内容一致の判定はサイズとSHA-256で行い、ハッシュは各側で計算する。ネットワークを
通るのはハッシュ値だけであり、比較のためにファイル本体を転送し直すことはない。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def file_digest(path: Path) -> str:
    """ファイルのSHA-256を16進文字列で返す。読めない場合は ``OSError`` を送出する。"""

    hasher = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            chunk = file.read(_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
