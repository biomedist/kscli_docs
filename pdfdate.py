"""PDF 공문에서 '기안일자'를 찾아 읽어 옵니다. (글자가 들어 있는 PDF 전용 — 스캔 이미지는 읽지 못합니다)

- pypdf 가 설치되어 있지 않거나 글자를 읽지 못하면 None 을 돌려주고, 화면에서 직접 입력하도록 안내합니다.
- 먼저 '기안일자'(띄어쓰기·콜론 변형 포함) 뒤의 날짜를 찾고, 없으면 '시행 부서-번호 (날짜)' 모양의 시행일자를 대신 씁니다.
- 날짜 모양: 2026. 3. 5. / 2026.3.5 / 2026-03-05 / 2026년 3월 5일
"""
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import date

try:
    from pypdf import PdfReader
except ImportError:                      # 설치 전에도 앱은 동작하고, 날짜만 자동으로 못 채웁니다
    PdfReader = None

_SEP = "[.\\-‐‑‒–—−/·]"     # 점, 하이픈(여러 모양), 슬래시
_DATE = r"((?:19|20)\d{2})\s*(?:" + _SEP + r"|년)\s*(\d{1,2})\s*(?:" + _SEP + r"|월)\s*(\d{1,2})\s*(?:일|\.)?"
_DRAFTED = re.compile(r"기\s*안\s*일\s*자?\s*[:：]?[^0-9]{0,60}?" + _DATE)
_ENFORCED = re.compile(r"시\s*행\s+[^\n(]{0,40}?\(\s*" + _DATE + r"\s*\)")


def available():
    return PdfReader is not None


def _valid(y, m, d):
    try:
        found = date(int(y), int(m), int(d))
    except ValueError:
        return None
    return found.isoformat() if 2000 <= found.year <= date.today().year + 1 else None


def _text(path, pages=2, layout=False):
    """layout=True 이면 글자 위치(가로줄) 기준으로 읽어, 표의 '라벨 | 값'이 한 줄에 놓이게 합니다."""
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return ""
    parts = []
    for page in reader.pages[:pages]:
        try:
            if layout:
                parts.append(page.extract_text(extraction_mode="layout") or "")
            else:
                parts.append(page.extract_text() or "")
        except Exception:
            continue
    return clean("\n".join(parts))


_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))


def clean(text):
    """PDF마다 다른 글자 모양을 맞춥니다: 자모가 풀어진 한글(ㄱ+ㅏ)은 합치고, 전각 숫자·특수 하이픈은 보통 글자로,
    보이지 않는 글자는 지웁니다."""
    return unicodedata.normalize("NFKC", text).translate(_INVISIBLE).replace("\xa0", " ")


def find_in_text(text):
    """글에서 날짜를 찾아 (YYYY-MM-DD, 근거) 를 돌려줍니다. 못 찾으면 (None, None)."""
    for pattern, label in ((_DRAFTED, "기안일자"), (_ENFORCED, "시행일자")):
        for m in pattern.finditer(text):
            found = _valid(*m.groups())
            if found:
                return found, label
    return None, None


_STRICT = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)")


def guess_in_text(text):
    """'기안일자'라는 글자는 있는데 바로 옆에서 날짜를 못 찾을 때(표에서 글 순서가 섞인 경우):
    문서 앞쪽의 처음 나오는 YYYY-MM-DD 형식 날짜를 기안일로 추정합니다. 확실하지 않으므로 '추정'으로 표시됩니다."""
    if not re.search(r"기\s*안\s*일", text):
        return None
    for m in _STRICT.finditer(text):
        found = _valid(*m.groups())
        if found:
            return found
    return None


def _first_dash_date(text):
    """OCR 글에서 처음 나오는 YYYY-MM-DD 날짜 (라벨을 못 알아봤을 때의 추정용)"""
    for m in _STRICT.finditer(text):
        found = _valid(*m.groups())
        if found:
            return found
    return None


def _looks_unreadable(texts):
    """글자 층이 거의 없거나 깨진 PDF (스캔·그림 PDF)"""
    flat = re.sub(r"\s+", " ", " ".join(texts))
    return len(flat) < 20 or len(re.findall(r"[가-힣]", flat)) < 5 or "(cid:" in flat


def drafted_date(path, ocr_budget=None):
    """PDF 파일 경로 → (YYYY-MM-DD, 근거) 또는 (None, None)
    순서: ① 기안일자 바로 옆 날짜 (글 순서 → 가로줄 정렬 순서로 두 번) ② 기안일자는 있으나 위치가 섞인 경우의 추정 ③ 시행일자
          ④ 글자가 없는 그림 PDF는 OCR(글자 인식)로 읽기 — Tesseract 가 설치되어 있을 때만
    ocr_budget: {"left": N, "skipped": 0} — 여러 건을 한꺼번에 처리할 때 OCR 횟수를 제한(시간이 오래 걸리므로)"""
    if PdfReader is None or not path or not str(path).lower().endswith(".pdf"):
        return None, None
    try:
        texts = [_text(path)]
        try:
            texts.append(_text(path, layout=True))
        except Exception:
            pass
        enforced = None
        for t in texts:
            found, label = find_in_text(t)
            if label == "기안일자":
                return found, label
            enforced = enforced or (found, label)
        for t in texts:
            guess = guess_in_text(t)
            if guess:
                return guess, "기안일자(추정)"
        if enforced and enforced[0]:
            return enforced
        if _looks_unreadable(texts) and ocr_status()["ready"]:
            if ocr_budget is not None:
                if ocr_budget["left"] <= 0:
                    ocr_budget["skipped"] += 1
                    return None, None
                ocr_budget["left"] -= 1
            text = ocr_text(path)
            found, label = find_in_text(text)
            if label == "기안일자":
                return found, "OCR 기안일자"
            guess = _first_dash_date(text)
            if guess:
                return guess, "OCR(추정)"
        return None, None
    except Exception:
        return None, None


# ---------- OCR (글자 인식): 스캔·그림 PDF용 ----------
# 필요한 것: Tesseract 프로그램(+한국어 데이터) 과 pip 패키지 pypdfium2, pillow. 없으면 이 단계만 건너뜁니다.
_ocr_cache = {}
_WIN_DEFAULTS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    os.path.join(os.path.expanduser("~"), "Tesseract-OCR", "tesseract.exe"),
)


def _tesseract_exe():
    for candidate in (os.environ.get("TESSERACT_CMD"), shutil.which("tesseract"), *_WIN_DEFAULTS):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _run(cmd, timeout):
    flags = 0x08000000 if os.name == "nt" else 0          # 윈도우에서 까만 창이 번쩍이지 않게
    return subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=flags)


def ocr_status():
    """OCR 사용 준비 상태 → {"ready": bool, "reason": 설명, "exe": 경로, "lang": 'kor+eng' 등}"""
    if "status" in _ocr_cache:
        return _ocr_cache["status"]
    status = {"ready": False, "reason": "", "exe": None, "lang": None}
    try:
        import pypdfium2  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        status["reason"] = "pip install pypdfium2 pillow 가 필요합니다"
    else:
        exe = _tesseract_exe()
        if not exe:
            status["reason"] = "Tesseract 프로그램을 찾지 못했습니다 (설치 후 앱을 다시 실행하세요)"
        else:
            langs = set()
            try:
                out = _run([exe, "--list-langs"], 20).stdout.decode("utf-8", "replace")
                langs = {l.strip() for l in out.splitlines()[1:] if l.strip()}
            except Exception as exc:
                status["reason"] = f"Tesseract 를 실행하지 못했습니다 ({type(exc).__name__})"
            if langs:
                lang = "kor+eng" if "kor" in langs else "eng"
                status.update(ready=True, exe=exe, lang=lang,
                              reason="사용 가능 (한국어 포함)" if "kor" in langs else "사용 가능하지만 한국어 데이터가 없어 숫자 위주로 읽습니다")
            elif not status["reason"]:
                status["reason"] = "Tesseract 언어 데이터를 찾지 못했습니다"
    _ocr_cache["status"] = status
    return status


def ocr_text(path, psm=6, scale=3.0, raise_errors=False):
    """PDF 첫 쪽을 그림으로 만들어 글자 인식한 결과 (준비가 안 되었거나 실패하면 빈 글)"""
    st = ocr_status()
    if not st["ready"]:
        return ""
    try:
        import pypdfium2 as pdfium
        with open(path, "rb") as fh:
            pdf = pdfium.PdfDocument(fh.read())
        try:
            image = pdf[0].render(scale=scale).to_pil().convert("L")
        finally:
            pdf.close()
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "page.png")
            image.save(png)
            proc = _run([st["exe"], png, "stdout", "-l", st["lang"], "--psm", str(psm)], 120)
        return clean(proc.stdout.decode("utf-8", "replace"))
    except Exception:
        if raise_errors:          # 점검 스크립트에서 원인을 보여 주기 위해
            raise
        return ""


def diagnose(path, ocr_budget=None):
    """못 읽은 PDF의 이유와 글 일부를 돌려줍니다. → {"reason": 코드, "label": 설명, "snippet": 글 일부}"""
    if PdfReader is None:
        return {"reason": "no_lib", "label": "pypdf 가 설치되지 않았습니다 (pip install pypdf)", "snippet": ""}
    if not path or not str(path).lower().endswith(".pdf"):
        return {"reason": "not_pdf", "label": "PDF 파일이 아니라 읽을 수 없습니다", "snippet": ""}
    try:
        text = _text(path)
        try:
            layout_text = _text(path, layout=True)
        except Exception:
            layout_text = text
    except Exception as exc:
        return {"reason": "error", "label": f"파일을 열지 못했습니다 ({type(exc).__name__})", "snippet": ""}
    flat = re.sub(r"\s+", " ", text).strip()
    hangul = len(re.findall(r"[가-힣]", flat))
    if len(flat) < 20 or hangul < 5 or "(cid:" in flat or "\ufffd" in flat:
        base = ("글자를 읽을 수 없습니다 (스캔·이미지 PDF이거나 글자가 그림으로 들어 있음)" if len(flat) < 20
                else "글자가 깨져서 읽힙니다 (PDF 안의 글꼴 정보 문제)")
        st = ocr_status()
        if not st["ready"]:
            return {"reason": "no_text", "label": f"{base} · OCR 사용 불가: {st['reason']}", "snippet": flat[:200]}
        if ocr_budget is not None:
            if ocr_budget["left"] <= 0:
                return {"reason": "no_text", "label": f"{base} · OCR 은 시간이 걸려 처음 몇 건만 시도했습니다", "snippet": ""}
            ocr_budget["left"] -= 1
        ocr = ocr_text(path)
        shown = re.sub(r"\s+", " ", ocr).strip()
        return {"reason": "ocr_fail", "label": f"{base} · OCR 로 읽어 봤지만 날짜를 찾지 못했습니다",
                "snippet": ("[OCR이 읽은 글] " + shown[:200]) if shown else "[OCR이 아무것도 읽지 못함]"}
    squeezed = re.sub(r"\s+", "", flat)
    pos = squeezed.find("기안일")
    if pos < 0:
        return {"reason": "no_label", "label": "글자는 읽혔지만 '기안일자'가 없습니다", "snippet": flat[:200]}
    # 라벨 주변 글을 원래 모양(공백·줄바꿈 포함)으로 보여 주기 위해 원문에서 다시 찾음
    m = re.search(r"기\s*안\s*일", layout_text)
    around = re.sub(r"[ \t]{2,}", " | ", layout_text[max(0, m.start() - 60): m.start() + 160]) if m else flat[:200]
    return {"reason": "label_no_date", "label": "'기안일자'는 있지만 바로 뒤에서 날짜를 읽지 못했습니다",
            "snippet": around.replace("\n", " ⏎ ")}


def full_text(path, pages=40):
    """PDF 앞쪽 여러 쪽의 글 전체 (사업계획서 등에서 내용을 옮길 때). 못 읽으면 빈 글."""
    if PdfReader is None:
        return ""
    try:
        return _text(path, pages=pages)
    except Exception:
        return ""
