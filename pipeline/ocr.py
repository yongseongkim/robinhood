"""스캔·이미지 PDF OCR (macOS Vision 프레임워크, 로컬 처리 — 외부로 전송하지 않음).

- 페이지를 300dpi로 렌더링(pypdfium2) → Vision VNRecognizeTextRequest(ko-KR, en-US, 정확도 우선)
- 결과(글자, 신뢰도, 위치)는 data/ocr/<sha256 앞 16자리>.json에 캐시한다. 원본 PDF가 같으면 다시 OCR하지 않는다.
- 좌표는 페이지 기준 0~1 정규화, 원점은 왼쪽 위.
"""
import hashlib
import io
import json
import sys

import pypdfium2 as pdfium
import Quartz
import Vision
from Foundation import NSData

from common import ROOT

CACHE = ROOT / "data" / "ocr"
DPI = 300
ENGINE = "apple-vision-accurate-ko-en-v1"


def _cgimage(pil_image):
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def ocr_image(pil_image):
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["ko-KR", "en-US"])
    req.setUsesLanguageCorrection_(False)  # 상호·숫자를 사전 단어로 '고치지' 않게
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
    cache = CACHE / f"{sha[:16]}.json"
    if cache.exists() and not force:
        cached = json.loads(cache.read_text())
        if cached.get("engine") == ENGINE:
            return cached
    pdf = pdfium.PdfDocument(raw)
    pages = []
    for i in range(len(pdf)):
        page = pdf[i]
        img = page.render(scale=DPI / 72).to_pil()
        pages.append({"width": img.width, "height": img.height, "boxes": ocr_image(img)})
    result = {"engine": ENGINE, "dpi": DPI, "sha256": sha, "source": str(path.relative_to(ROOT)), "pages": pages}
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    from pathlib import Path
    res = ocr_pdf(Path(sys.argv[1]).resolve(), force="--force" in sys.argv)
    for p in res["pages"][:1]:
        for b in sorted(p["boxes"], key=lambda b: (round(b["y"], 2), b["x"]))[:80]:
            print(f"{b['y']:.3f} {b['x']:.3f} {b['w']:.3f} {b['conf']:.2f} {b['text']}")
