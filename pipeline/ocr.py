"""스캔 PDF에서 한국어·영어 글자와 위치를 읽는다.

기본 엔진은 macOS에서 Vision, Linux에서 Tesseract다.
페이지 왼쪽 위를 원점으로 삼고 가로·세로 위치를 각각 0~1 범위로 저장한다.
원본 SHA-256, 엔진 식별자, 렌더링 해상도가 모두 같으면 캐시를 재사용한다.
--force를 지정하면 같은 파일도 다시 읽는다.
"""
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import pypdfium2 as pdfium

from common import ROOT

CACHE = ROOT / "data" / "ocr"
DPI = 300
VISION = "apple-vision-accurate-ko-en-v1"
TESSERACT = "tesseract-kor-eng-tsv-psm11-v1"
ENGINE = VISION if sys.platform == "darwin" else TESSERACT


class OcrUnavailable(RuntimeError):
    pass


def check_engine():
    if ENGINE == VISION:
        try:
            import Quartz
            import Vision
        except ImportError as exc:
            raise OcrUnavailable("macOS Vision을 불러올 수 없습니다.") from exc
    else:
        try:
            languages = subprocess.run(["tesseract", "--list-langs"], check=True, capture_output=True, text=True).stdout.splitlines()
        except FileNotFoundError as exc:
            raise OcrUnavailable("Tesseract 실행 파일이 없습니다.") from exc
        if not {"kor", "eng"}.issubset(languages):
            raise OcrUnavailable("Tesseract 한국어(kor)·영어(eng) 언어 데이터가 필요합니다.")


def tesseract_boxes(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "kor+eng", "--dpi", str(DPI), "--psm", "11", "tsv"],
        input=buf.getvalue(), capture_output=True, check=True, timeout=120,
        env={**os.environ, "OMP_THREAD_LIMIT": os.environ.get("OMP_THREAD_LIMIT", "1")},
    )
    width, height = image.size
    boxes = []
    previous_line = None
    for row in csv.DictReader(io.StringIO(result.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row["level"] != "5" or not row["text"].strip():
            continue
        text = row["text"].strip()
        x, y = int(row["left"]), int(row["top"])
        w, h = int(row["width"]), int(row["height"])
        conf = float(row["conf"]) / 100
        line = (row["block_num"], row["par_num"], row["line_num"])
        # TSV가 같은 한국어 단어를 음절마다 나누기도 한다. 칸 사이 여백은 유지한다.
        if line == previous_line and re.fullmatch(r"[가-힣]+", text):
            prev = boxes[-1]
            gap = x - (prev["x"] + prev["w"])
            if re.fullmatch(r"[가-힣 ]+", prev["text"]) and gap <= min(h, prev["h"]):
                prev["text"] += (" " if gap > 0.4 * h else "") + text
                left, top = min(x, prev["x"]), min(y, prev["y"])
                prev.update(w=max(x + w, prev["x"] + prev["w"]) - left,
                            h=max(y + h, prev["y"] + prev["h"]) - top,
                            x=left, y=top, conf=min(conf, prev["conf"]))
                continue
        previous_line = line
        boxes.append({"text": text, "conf": conf, "x": x, "y": y, "w": w, "h": h})
    for box in boxes:
        box["x"] /= width
        box["w"] /= width
        box["y"] /= height
        box["h"] /= height
    return boxes


def _cgimage(pil_image):
    import Quartz
    from Foundation import NSData

    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def ocr_image(pil_image):
    if ENGINE == TESSERACT:
        return tesseract_boxes(pil_image)
    import Vision

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["ko-KR", "en-US"])
    req.setUsesLanguageCorrection_(False)  # 언어 보정이 상호나 숫자를 사전에 있는 단어로 바꾸지 않도록 한다.
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(_cgimage(pil_image), None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision OCR 실패: {err}")
    out = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)[0]
        b = obs.boundingBox()
        out.append({
            "text": str(cand.string()),
            "conf": round(float(cand.confidence()), 3),
            "x": round(b.origin.x, 5),
            "y": round(1 - b.origin.y - b.size.height, 5),
            "w": round(b.size.width, 5),
            "h": round(b.size.height, 5),
        })
    return out


def ocr_pdf(path, force=False):
    """PDF 전체를 OCR한다. {'engine', 'dpi', 'pages': [{'width', 'height', 'boxes': [...]}]}"""
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    directory = CACHE if ENGINE == VISION else CACHE / ENGINE
    cache = directory / f"{sha[:16]}.json"
    if cache.exists() and not force:
        cached = json.loads(cache.read_text())
        if cached.get("engine") == ENGINE and cached.get("sha256") == sha and cached.get("dpi") == DPI:
            return cached
    pdf = pdfium.PdfDocument(raw)
    pages = []
    for i in range(len(pdf)):
        page = pdf[i]
        img = page.render(scale=DPI / 72).to_pil()
        pages.append({"width": img.width, "height": img.height, "boxes": ocr_image(img)})
    result = {"engine": ENGINE, "dpi": DPI, "sha256": sha, "source": str(path.relative_to(ROOT)), "pages": pages}
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as temp:
        json.dump(result, temp, ensure_ascii=False)
    Path(temp.name).replace(cache)
    return result


if __name__ == "__main__":
    res = ocr_pdf(Path(sys.argv[1]).resolve(), force="--force" in sys.argv)
    for p in res["pages"][:1]:
        for b in sorted(p["boxes"], key=lambda b: (round(b["y"], 2), b["x"]))[:80]:
            print(f"{b['y']:.3f} {b['x']:.3f} {b['w']:.3f} {b['conf']:.2f} {b['text']}")
