"""アウトライン化された PDF を OCR で読む。**層に依存しない。**

⚠️ **これはテキスト抽出より保証が一段弱い。** 狛江市の歳入事項別明細（2020〜2022）は
文字がベクタパスへアウトライン化されており（Tj が1つも無く、グリフが曲線として
描かれている）、テキスト抽出が原理的に成立しない。OCR はその代替で、
**誤読が混ざる前提**で使う。誤読の検出は呼び出し側の責務 —
金額を原典 CSV と突合し、一致した科目からだけ名称を採る（fudoki の取り込みの柱
「切り捨てを成功として扱わない」の OCR 版）。

エンジンは llama.cpp（MIT）+ GLM-OCR（GGUF）。版は mise が pin し、重みは
`ocr-model.toml` が URL + SHA-256 で固定する。provenance には両方を記録すること —
どちらが変わっても同じ原典から違う抽出物が出るので、冪等判定の材料になる。

⚠️ **`llama-server` ではなく `llama-mtmd-cli` をページごとに起動する。**
実測（2026-08-29、同じ3ページを順序を入れ替えて2回）で、1ページあたりの
壁時計時間の差は +2.1 秒 / -0.1 秒（平均 +1.0 秒、推論本体は約 40 秒）で、
測定順による揺れと同じ大きさだった。常駐プロセスの生存管理を
パイプラインへ持ち込むと「サーバが落ちたのか抽出が失敗したのか」の切り分けが要る。
1秒でそれを買わない。

⚠️ **ページ全体を1枚で渡さない。** 渡すと読めはするが、表の格子が忠実に出ない。
実測では科目の3段（款・項・目）が2列に潰れ、款と項と目が同じ列に並んだ
（値そのものは正しく読めているので、壊れるのは階層だけ）。
**必要な列だけを切り出して1枚へ横に並べる** — 列が少ないほど格子が忠実になり、
画像も小さくなるので速い（実測: ページ全体 39.8 秒 → 切り出し 15.5 秒）。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import tempfile
import tomllib
import urllib.request
from collections.abc import Iterator

DPI = 300
PROMPT = "Table Recognition:"      # 公式のモデルカードが表の認識に指定しているもの
BINARY = "llama-mtmd-cli"
DECLARATION = pathlib.Path(__file__).with_name("ocr-model.toml")
# 重みは commit しない（2.3 GB）。repo の外に置き、SHA-256 で同一性を担保する。
CACHE = pathlib.Path.home() / ".cache" / "fudoki" / "ocr-models"
# 切り出した列の間に入れる余白（px）。**列を接して並べない** —
# 接すると隣の列の数字が同じセルへ吸われる
GAP_PX = 24


def weights_version() -> str:
    """重みとレンダリング解像度だけの指紋。**バイナリを呼ばない。**

    例: `GLM-OCR-f16-b06675e983db+mmproj-9c4b58e33e31@300dpi`

    ⚠️ **engine_version() から切り出してあるのは、エンジンが無い環境でも
    ここまでは確定できるため。** 冪等判定をエンジンの版ごと諦めると、
    重みや DPI を差し替えても古い抽出物が黙って生き残る
    （`extract_revenue_accounts.ingest` がこの関数で見る）。
    """
    parts = "+".join(f"{name}-{spec['sha256'][:12]}" for name, spec in _declaration().items())
    return f"{parts}@{DPI}dpi"


def engine_version() -> str:
    """provenance に記録する識別子。

    例: `llamacpp-b9616+GLM-OCR-f16-b06675e983db+mmproj-9c4b58e33e31@300dpi`

    エンジンの版・重み・レンダリング解像度のどれが変わっても文字列が変わる。
    llama.cpp の版はバイナリ自身に聞く（mise.toml の宣言を写すと、
    宣言と実際に動いたものがずれても気づけない）。
    """
    out = subprocess.run([BINARY, "--version"], capture_output=True, check=True)  # noqa: S603
    text = (out.stderr or out.stdout).decode()
    m = re.search(r"version:\s*(\S+)", text)
    if not m:
        raise RuntimeError(f"{BINARY} --version から版を読めない: {text[:200]!r}")
    return f"llamacpp-b{m.group(1)}+{weights_version()}"


def _declaration() -> dict[str, dict]:
    """`ocr-model.toml`。名前は engine_version() の文字列に出るので短くしてある"""
    raw = tomllib.loads(DECLARATION.read_text(encoding="utf-8"))
    return {"GLM-OCR-f16": raw["model"], "mmproj": raw["mmproj"]}


def _weight(spec: dict) -> pathlib.Path:
    """宣言された重みを返す。無ければ取得し、**SHA-256 が宣言と違えば止める**。

    ⚠️ 途中で切れた取得を成功として扱わない。壊れた重みは落ちずに
    「少し違う抽出物」を出すので、検査しないと provenance だけが正しく見える。
    """
    path = CACHE / spec["url"].rsplit("/", 1)[-1]
    if path.exists() and _sha256(path) == spec["sha256"]:
        return path
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    # ⚠️ **途中で死んだときも消す。** timeout や切断で抜けると最大 1.8 GB の
    # `.part` がキャッシュに残る。次回は `wb` で切り詰めるので誤成功にはならないが、
    # 失敗するたびに置き土産が増える
    try:
        with urllib.request.urlopen(spec["url"], timeout=60) as res, tmp.open("wb") as f:  # noqa: S310
            while chunk := res.read(1 << 20):
                f.write(chunk)
        if tmp.stat().st_size != spec["bytes"] or _sha256(tmp) != spec["sha256"]:
            raise RuntimeError(f"取得した重みが宣言と一致しない: {spec['url']}")
        tmp.rename(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def tables_of(pdf: pathlib.Path, pages: list[int],
              columns: list[tuple[float, float]]) -> Iterator[str]:
    """指定したページを OCR し、HTML の `<table>` を返す。

    columns は残す列の x 範囲（PDF ポイント）。**宣言した順に横へ並べる**ので、
    出力の列の順番は呼び出し側が知っている。
    ⚠️ **ページ範囲ではなくページの列を受ける。** テキストで読めたページを
    OCR に掛けるのは、遅いだけでなく保証を弱める。
    """
    model = _weight(_declaration()["GLM-OCR-f16"])
    mmproj = _weight(_declaration()["mmproj"])
    for page_no in pages:
        with tempfile.TemporaryDirectory() as td:
            image = _composite(pdf, page_no, columns, pathlib.Path(td))
            out = subprocess.run(  # noqa: S603
                [BINARY, "-m", str(model), "--mmproj", str(mmproj), "--image", str(image),
                 "-p", PROMPT, "--temp", "0", "-n", "4096", "-c", "8192"],
                capture_output=True, check=True,
            ).stdout.decode()
        # ⚠️ **`-n` の上限に達しても終了コードは 0。** check=True では切り捨てを検出できない。
        # 検出は html_table.grid()（閉じていない <table> / <tr> / <td> を例外にする）が持つ —
        # ここで文字列を再検査すると同じ事実を2箇所で宣言することになる
        yield out


def _composite(pdf: pathlib.Path, page_no: int, columns: list[tuple[float, float]],
               work: pathlib.Path) -> pathlib.Path:
    """列ごとに描画して1枚へ横に並べる。PGM のまま扱う（stb_image が読む）。

    ⚠️ **PNG にしない。** 合成に画像ライブラリが要る。PGM（P5）は
    ヘッダと生バイトだけなので、標準ライブラリで切って繋げる。
    """
    scale = DPI / 72.0
    strips = []
    for i, (lo, hi) in enumerate(columns):
        base = work / f"c{i}"
        subprocess.run(  # noqa: S603
            ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", str(DPI), "-gray",
             "-x", str(int(lo * scale)), "-y", "0", "-W", str(int((hi - lo) * scale)),
             str(pdf), str(base)],
            check=True,
        )
        strips.append(_read_pgm(next(work.glob(f"c{i}-*.pgm"))))
    heights = {h for _, h, _ in strips}
    if len(heights) != 1:
        raise RuntimeError(f"切り出した列の高さが揃わない: {heights}")
    height = heights.pop()
    width = sum(w for w, _, _ in strips) + GAP_PX * (len(strips) - 1)
    rows = bytearray()
    for y in range(height):
        for i, (w, _, px) in enumerate(strips):
            if i:
                rows += b"\xff" * GAP_PX      # 紙と同じ白。黒帯は罫線に見える
            rows += px[y * w:(y + 1) * w]
    out = work / "composite.pgm"
    out.write_bytes(b"P5\n%d %d\n255\n" % (width, height) + bytes(rows))
    return out


def _read_pgm(path: pathlib.Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if data[:2] != b"P5":
        raise RuntimeError(f"P5 の PGM ではない: {path}")
    fields: list[int] = []
    i = 2
    while len(fields) < 3:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] != b"\n":
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        fields.append(int(data[i:j]))
        i = j
    width, height, _maxval = fields
    return width, height, data[i + 1:i + 1 + width * height]
