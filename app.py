"""
메디행정톡 (MediAdmin Talk) — 한 파일 버전
=========================================
사용법
  1. Python 설치 (python.org, 설치할 때 "Add python.exe to PATH" 체크)
  2. 이 파일을 IDLE 또는 Thonny로 열기
  3. 아래 [1. API 키 설정]에 키 붙여넣기 (비워 두면 샘플 데이터로 동작하는 '체험 모드')
  4. F5 (실행) → 처음 한 번은 필요한 패키지 자동 설치 → 브라우저에 앱이 열림
  5. 끄기: IDLE은 Ctrl+F6 (Restart Shell), Thonny는 빨간 정지 버튼

기록 저장
  - 분석한 영수증은 이 파일과 같은 폴더의 'mediadmin_records.db'에 저장됩니다. (사진은 저장하지 않음)
  - 최근 기록은 10건까지 보여주고, 그보다 오래된 기록은 자동으로 '보관함'으로 옮깁니다.

※ 키를 넣은 뒤에는 이 파일을 깃허브 등 인터넷에 올리지 마세요.
"""

# ════════════════════════════════════════════════════════════
# 1. API 키 설정 — 따옴표 "" 안에 붙여넣기
# ════════════════════════════════════════════════════════════
DATA_GO_KR_KEY = ""      # 공공데이터포털 > 마이페이지 > 일반 인증키(Decoding)
ANTHROPIC_API_KEY = ""   # platform.claude.com > API keys (sk-ant-로 시작)
CLOVA_OCR_URL = ""       # (선택) 네이버 CLOVA OCR Invoke URL
CLOVA_OCR_SECRET = ""    # (선택) 네이버 CLOVA OCR Secret Key

CLAUDE_MODEL = "claude-sonnet-5-5"
DEMO_MODE = "auto"       # "auto": 키 없으면 데모 / "on": 항상 데모 / "off": 항상 실제 API

STORAGE = "session"        # "file": 내 PC에 기록 저장 / "session": 브라우저를 닫으면 사라짐 (인터넷 배포용)
MAX_ACTIVE_RECORDS = 10  # 최근 기록으로 보여줄 개수. 넘으면 오래된 기록부터 보관함으로 이동
ALLOW_OCR_INSTALL = False# 앱 화면에서 자동 가림(EasyOCR) 설치 버튼을 보여줄지 (인터넷 배포 버전은 False)


# ════════════════════════════════════════════════════════════
# 2. 필요한 패키지 자동 설치 (처음 한 번만)
# ════════════════════════════════════════════════════════════
import importlib.util
import subprocess
import sys

PACKAGES = {"streamlit": "streamlit", "anthropic": "anthropic", "requests": "requests",
            "pandas": "pandas", "dotenv": "python-dotenv", "streamlit_js_eval": "streamlit-js-eval"}


def install_packages():
    missing = [pip_name for mod, pip_name in PACKAGES.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        return
    print(f"[안내] 필요한 패키지를 설치하는 중이에요: {', '.join(missing)}  (1~3분)")
    result = subprocess.run([sys.executable, "-m", "pip", "install", *missing],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-2000:], result.stderr[-2000:])
        sys.exit("[오류] 설치에 실패했어요. 위 메시지를 복사해서 물어보세요.")
    print("[안내] 설치 완료!")


if __name__ == "__main__":
    install_packages()

# ── 여기부터 실제 코드 ───────────────────────────────────────
import base64
import json
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

# 같은 폴더에 .env 파일이 있으면 거기 적힌 키를 우선 사용 (없으면 위에 적은 값 사용)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass
DATA_GO_KR_KEY = os.getenv("DATA_GO_KR_KEY") or DATA_GO_KR_KEY
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY
CLOVA_OCR_URL = os.getenv("CLOVA_OCR_URL") or CLOVA_OCR_URL
CLOVA_OCR_SECRET = os.getenv("CLOVA_OCR_SECRET") or CLOVA_OCR_SECRET


def use_demo_public():
    return DEMO_MODE == "on" or (DEMO_MODE == "auto" and not DATA_GO_KR_KEY)


def use_demo_llm():
    return DEMO_MODE == "on" or (DEMO_MODE == "auto" and not ANTHROPIC_API_KEY)


# ════════════════════════════════════════════════════════════
# 3. 공공데이터 API 주소 · 지역 코드
#    (주소가 활용명세와 다르면 여기만 고치면 됩니다)
# ════════════════════════════════════════════════════════════
ENDPOINTS = {
    # 행정안전부_대한민국 공공서비스(혜택) 정보
    "gov24_list": "https://api.odcloud.kr/api/gov24/v3/serviceList",
    "gov24_detail": "https://api.odcloud.kr/api/gov24/v3/serviceDetail",
    # 한국사회보장정보원_지자체복지서비스
    "local_welfare_list": "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfarelist",
    # 건강보험심사평가원_병원정보서비스
    "hira_hosp_list": "https://apis.data.go.kr/B551182/hospInfoServicev2/getHospBasisList",
    # 건강보험심사평가원_비급여진료비정보서비스 (오퍼레이션 이름은 활용가이드에서 확인)
    "hira_nonpay_hosp": "https://apis.data.go.kr/B551182/nonPaymentDamtInfoService/getNonPaymentItemHospDtlList",
    # 국립중앙의료원_전국 약국 정보 조회 서비스 (목록 / 내 위치 주변)
    "pharm_list": "https://apis.data.go.kr/B552657/ErmctInsttInfoInqireService/getParmacyListInfoInqire",
    "pharm_near": "https://apis.data.go.kr/B552657/ErmctInsttInfoInqireService/getParmacyLcinfoInqire",
}

SIDO_CODES = {  # 심평원 시도코드
    "서울": "110000", "부산": "210000", "인천": "220000", "대구": "230000",
    "광주": "240000", "대전": "250000", "울산": "260000", "세종": "410000",
    "경기": "310000", "강원": "320000", "충북": "330000", "충남": "340000",
    "전북": "350000", "전남": "360000", "경북": "370000", "경남": "380000",
    "제주": "390000",
}
SIDO_FULLNAMES = {  # 복지로 API용 시도 이름
    "서울": "서울특별시", "부산": "부산광역시", "인천": "인천광역시", "대구": "대구광역시",
    "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
    "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
    "제주": "제주특별자치도",
}

# 데모 모드용 샘플 혜택 (설명은 예시이며, 실제 기준은 공식 공고로 확인)
SAMPLE_BENEFITS = [
    {"id": "DEMO-001", "name": "재난적의료비 지원사업", "org": "보건복지부 / 국민건강보험공단", "region": "전국",
     "target": "소득 기준을 충족하고 과도한 의료비가 발생한 환자",
     "content": "소득 대비 과도한 본인부담 의료비의 일부를 지원 (세부 기준은 공식 공고 확인)",
     "apply": "국민건강보험공단 지사 방문 또는 우편 신청",
     "docs": ["신청서", "진료비 영수증", "진료비 세부산정내역서", "소득 확인 서류"],
     "keywords": ["의료비", "입원", "중증", "고액", "본인부담"], "life": ["청년", "중장년", "노년"], "source": "DEMO"},
    {"id": "DEMO-002", "name": "본인부담상한제", "org": "국민건강보험공단", "region": "전국",
     "target": "1년간 낸 건강보험 본인부담금이 소득 분위별 상한액을 넘은 가입자",
     "content": "상한액을 초과한 본인부담금을 공단이 돌려줌 (사전급여 또는 사후환급)",
     "apply": "공단 안내문 수령 후 공단 홈페이지·지사·전화로 환급 신청",
     "docs": ["환급 신청서", "본인 명의 계좌 정보"],
     "keywords": ["본인부담", "상한", "환급", "의료비", "급여"], "life": ["청년", "중장년", "노년"], "source": "DEMO"},
    {"id": "DEMO-003", "name": "고혈압·당뇨병 등록관리 사업", "org": "시·군·구 보건소", "region": "지자체별",
     "target": "고혈압·당뇨병을 진단받은 지역 주민",
     "content": "보건소 등록 후 교육, 상담, 합병증 검사 연계 등 만성질환 관리 서비스 (지자체별 상이)",
     "apply": "관할 보건소 방문 등록", "docs": ["신분증", "진단 확인 서류(필요 시)"],
     "keywords": ["고혈압", "당뇨", "만성질환", "혈압", "혈당"], "life": ["중장년", "노년"], "source": "DEMO"},
    {"id": "DEMO-004", "name": "암환자 의료비 지원사업", "org": "보건복지부 / 보건소", "region": "전국",
     "target": "소득 기준을 충족하는 암 진단자 (기준은 공고 확인)",
     "content": "암 치료 관련 본인부담 의료비 일부 지원", "apply": "주민등록지 관할 보건소 신청",
     "docs": ["신청서", "진단서", "진료비 영수증", "통장 사본"],
     "keywords": ["암", "종양", "항암", "의료비"], "life": ["아동", "청년", "중장년", "노년"], "source": "DEMO"},
    {"id": "DEMO-005", "name": "국가건강검진 사후관리 상담", "org": "시·군·구 보건소", "region": "지자체별",
     "target": "국가건강검진에서 이상 소견이 나온 주민",
     "content": "검진 결과 상담 및 확진검사·만성질환 관리 프로그램 연계",
     "apply": "관할 보건소 방문 또는 전화 상담", "docs": ["건강검진 결과표", "신분증"],
     "keywords": ["검진", "이상", "의심", "혈압", "혈당", "콜레스테롤", "고혈압", "당뇨"],
     "life": ["청년", "중장년", "노년"], "source": "DEMO"},
    {"id": "DEMO-006", "name": "치매조기검진 및 치료관리비 지원", "org": "치매안심센터 (보건소)", "region": "지자체별",
     "target": "만 60세 이상 주민 (치료관리비는 소득 기준 별도)",
     "content": "치매 선별·진단검사 및 치료약제비 일부 지원", "apply": "관할 치매안심센터 방문",
     "docs": ["신분증", "진단서·처방전(치료비 신청 시)"],
     "keywords": ["치매", "기억", "인지"], "life": ["노년"], "source": "DEMO"},
]


# ════════════════════════════════════════════════════════════
# 4. 공공데이터 API 호출 → 공통 형식으로 변환
# ════════════════════════════════════════════════════════════
def api_get(url, params, tries=3):
    """공공데이터 API 호출. 서버가 느려 시간 초과가 나면 조금 기다렸다가 다시 시도 (최대 3번)"""
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, params={"serviceKey": DATA_GO_KR_KEY, **params}, timeout=25)
            r.raise_for_status()
            return r
        except (requests.Timeout, requests.ConnectionError):
            if attempt == tries:
                raise
            time.sleep(2 * attempt)


def xml_items(text, tag):
    root = ET.fromstring(text)
    return [{child.tag: (child.text or "").strip() for child in item} for item in root.iter(tag)]


def gov24_search(keyword, per_page=30):
    """행정안전부 공공서비스(혜택) 검색"""
    if use_demo_public():
        return [b for b in SAMPLE_BENEFITS if keyword in b["name"] or keyword in " ".join(b["keywords"])]
    params = {"page": 1, "perPage": per_page, "returnType": "JSON", "cond[서비스명::LIKE]": keyword}
    data = api_get(ENDPOINTS["gov24_list"], params).json()
    return [{
        "id": d.get("서비스ID", ""), "name": d.get("서비스명", ""), "org": d.get("소관기관명", ""),
        "region": d.get("소관기관유형", ""), "target": d.get("지원대상", ""), "content": d.get("지원내용", ""),
        "apply": d.get("신청방법", ""), "docs": [], "keywords": [keyword], "life": [],
        "url": d.get("상세조회URL", ""), "source": "행정안전부_공공서비스(혜택)",
    } for d in data.get("data", [])]


def local_welfare_search(sido, sigungu="", rows=50):
    """사회보장정보원 지자체 복지·보건 서비스 검색"""
    if use_demo_public():
        return [b for b in SAMPLE_BENEFITS if b["region"] in ("지자체별", "전국")]
    params = {"pageNo": 1, "numOfRows": rows, "ctpvNm": SIDO_FULLNAMES.get(sido, sido)}
    if sigungu:
        params["sggNm"] = sigungu
    items = xml_items(api_get(ENDPOINTS["local_welfare_list"], params).text, "servList")
    return [{
        "id": it.get("servId", ""), "name": it.get("servNm", ""),
        "org": f'{it.get("ctpvNm", "")} {it.get("sggNm", "")}'.strip(),
        "region": it.get("sggNm") or it.get("ctpvNm", ""), "target": it.get("trgterIndvdlNmArray", ""),
        "content": it.get("servDgst", ""), "apply": it.get("aplyMtdNm", ""), "docs": [],
        "keywords": [k for k in it.get("intrsThemaNmArray", "").split(",") if k],
        "life": [k for k in it.get("lifeNmArray", "").split(",") if k],
        "url": it.get("servDtlLink", ""), "source": "사회보장정보원_지자체복지서비스",
    } for it in items]


def hira_hospitals(sido, name="", rows=10):
    """심평원 병원 목록 (ykiho = 비급여 조회용 병원 고유키)"""
    if use_demo_public():
        return [{"yadmNm": "(데모) 행복내과의원", "clCdNm": "의원", "addr": f"{sido}", "ykiho": "DEMO"}]
    params = {"pageNo": 1, "numOfRows": rows, "sidoCd": SIDO_CODES.get(sido, "")}
    if name:
        params["yadmNm"] = name
    return xml_items(api_get(ENDPOINTS["hira_hosp_list"], params).text, "item")


def hira_nonpay(ykiho, rows=50):
    """심평원 병원별 비급여 항목·가격"""
    if use_demo_public() or ykiho == "DEMO":
        return [{"npayKorNm": "(데모) 도수치료", "curAmt": "70000"},
                {"npayKorNm": "(데모) 상급병실료 1인실", "curAmt": "150000"}]
    params = {"pageNo": 1, "numOfRows": rows, "ykiho": ykiho}
    return xml_items(api_get(ENDPOINTS["hira_nonpay_hosp"], params).text, "item")


def collect_candidates(sido, sigungu, keywords):
    """여러 API에서 후보 혜택을 모으기. 실패한 API는 기록만 하고 계속 진행."""
    results, errors = [], []
    try:
        results += local_welfare_search(sido, sigungu)
    except Exception as e:
        errors.append(f"지자체복지서비스: {e}")
    for kw in keywords[:5]:
        try:
            results += gov24_search(kw)
        except Exception as e:
            errors.append(f"공공서비스({kw}): {e}")
    seen, unique = set(), []
    for r in results:  # 중복 제거
        key = r["id"] or r["name"]
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique, errors


def test_apis():
    """API 키가 잘 연결됐는지 확인 → 결과 문장 목록 (앱 왼쪽 메뉴의 [API 연결 확인] 버튼)"""
    lines = [f"데모 모드: {'예 (키 없음, 샘플 데이터)' if use_demo_public() else '아니요 (실제 API)'}"]
    for name, fn in [("공공서비스(혜택)", lambda: gov24_search("의료비", 3)),
                     ("지자체 복지서비스", lambda: local_welfare_search("서울", "강남구", 3)),
                     ("심평원 병원정보", lambda: hira_hospitals("서울", rows=3))]:
        try:
            lines.append(f"✅ {name}: {len(fn())}건")
        except Exception as e:
            lines.append(f"❌ {name}: {e}")
    try:
        hosp = hira_hospitals("서울", rows=1)[0]
        lines.append(f"✅ 심평원 비급여: {len(hira_nonpay(hosp.get('ykiho', ''), 3))}건")
    except Exception as e:
        lines.append(f"❌ 심평원 비급여: {e}  ← 활용가이드의 오퍼레이션 이름과 ENDPOINTS 비교")
    return lines


# ════════════════════════════════════════════════════════════
# 5. OCR — 영수증·진단서 이미지 → 정리된 데이터(JSON)
# ════════════════════════════════════════════════════════════
EXTRACT_PROMPT = """이 이미지는 한국 병원/약국의 진료비 영수증 또는 진단서입니다.
보이는 내용만 아래 JSON 형식으로 추출하세요. 보이지 않는 값은 null로 두고 절대 추측하지 마세요.
{
  "doc_type": "진료비영수증 | 진료비세부산정내역서 | 진단서 | 처방전 | 기타",
  "hospital": "요양기관명", "department": "진료과목", "visit_date": "YYYY-MM-DD", "patient_type": "외래 | 입원 | null",
  "items": [{"name": "항목명", "covered_self": 0, "covered_insurer": 0, "full_self": 0, "non_covered": 0}],
  "totals": {"covered_self": 0, "covered_insurer": 0, "full_self": 0, "non_covered": 0, "patient_pay": 0},
  "diagnosis": ["진단명 또는 상병코드"], "raw_text": "주요 원문 요약"
}
covered_self=급여 본인부담금, covered_insurer=급여 공단부담금, full_self=전액본인부담,
non_covered=비급여, patient_pay=환자부담총액. 금액은 숫자만. JSON만 출력하세요."""

DEMO_RECEIPT = {
    "doc_type": "진료비영수증", "hospital": "(체험) 행복내과의원", "department": "내과", "visit_date": "2026-10-20", "patient_type": "외래",
    "items": [
        {"name": "진찰료", "covered_self": 4500, "covered_insurer": 10500, "full_self": 0, "non_covered": 0},
        {"name": "검사료", "covered_self": 6000, "covered_insurer": 14000, "full_self": 0, "non_covered": 0},
        {"name": "초음파 진단료", "covered_self": 0, "covered_insurer": 0, "full_self": 0, "non_covered": 60000},
    ],
    "totals": {"covered_self": 10500, "covered_insurer": 24500, "full_self": 0, "non_covered": 60000, "patient_pay": 70500},
    "diagnosis": ["I10 본태성(원발성) 고혈압"],
    "raw_text": "(데모 데이터) 실제 이미지를 올리면 실제 인식 결과로 바뀝니다.",
}


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("AI 응답에서 JSON을 찾지 못했어요.")
    return json.loads(m.group(0))


def claude_client():
    import anthropic
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def ocr_with_claude(image_bytes, media_type="image/jpeg"):
    if use_demo_llm():
        return DEMO_RECEIPT
    msg = claude_client().messages.create(
        model=CLAUDE_MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(image_bytes).decode()}},
            {"type": "text", "text": EXTRACT_PROMPT}]}])
    return parse_json(msg.content[0].text)


def ocr_with_clova(image_bytes, media_type="image/jpeg"):
    """CLOVA로 글자를 읽고, Claude로 표 형태로 정리"""
    if not (CLOVA_OCR_URL and CLOVA_OCR_SECRET):
        raise RuntimeError("CLOVA OCR 키가 비어 있어요 (1. API 키 설정 확인).")
    fmt = media_type.split("/")[-1].replace("jpeg", "jpg")
    payload = {"version": "V2", "requestId": str(uuid.uuid4()), "timestamp": int(time.time() * 1000),
               "images": [{"format": fmt, "name": "receipt", "data": base64.b64encode(image_bytes).decode()}]}
    r = requests.post(CLOVA_OCR_URL, json=payload, headers={"X-OCR-SECRET": CLOVA_OCR_SECRET}, timeout=30)
    r.raise_for_status()
    fields = r.json()["images"][0].get("fields", [])
    raw = "".join(f["inferText"] + ("\n" if f.get("lineBreak") else " ") for f in fields)
    if use_demo_llm():
        return DEMO_RECEIPT
    msg = claude_client().messages.create(
        model=CLAUDE_MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": EXTRACT_PROMPT + "\n\n[OCR 텍스트]\n" + raw}])
    return parse_json(msg.content[0].text)


# ════════════════════════════════════════════════════════════
# 5-1. 개인정보 가림 — 사진을 AI로 보내기 전에 내 PC에서 먼저 가림
#      ① EasyOCR로 글자와 위치를 읽고 ② 규칙으로 개인정보를 찾아 ③ 검은 박스로 칠함
# ════════════════════════════════════════════════════════════
import hashlib
import io

from PIL import Image, ImageDraw, ImageOps

# 이 글자가 보이면, 그 오른쪽 또는 바로 아래 칸의 값을 가림
SENSITIVE_LABELS = ["환자성명", "성명", "환자명", "이름", "주민등록번호", "주민번호", "주민", "생년월일",
                    "환자번호", "등록번호", "주소", "연락처", "전화", "휴대폰", "보호자"]
RRN_RE = re.compile(r"\d{6}\s*[-~]\s*[\d*]{1,7}")                         # 주민등록번호 900101-1234567
PHONE_RE = re.compile(r"(01[016789]|0\d{1,2})\s*-?\s*\d{3,4}\s*-?\s*\d{4}")  # 전화번호
MASK_PAD = 4  # 박스를 조금 넉넉하게 칠하는 여백(픽셀)


def easyocr_ready():
    importlib.invalidate_caches()
    return importlib.util.find_spec("easyocr") is not None


def install_easyocr():
    """자동 가림 기능(EasyOCR) 설치. 처음 한 번, 5~10분."""
    result = subprocess.run([sys.executable, "-m", "pip", "install", "easyocr"], capture_output=True, text=True)
    return result.returncode == 0, (result.stdout[-1500:] + result.stderr[-1500:])


EASYOCR_MODELS = ["craft_mlt_25k.pth", "korean_g2.pth"]


def easyocr_models_ready():
    """EasyOCR 인식 모델 파일이 이미 PC에 있는지 (없으면 처음 실행 때 내려받음)"""
    folder = Path(os.environ.get("EASYOCR_MODULE_PATH", Path.home() / ".EasyOCR")) / "model"
    return all((folder / f).exists() for f in EASYOCR_MODELS)


def tesseract_ready():
    """Tesseract(가벼운 글자 인식기)와 한국어 데이터가 있는지 — 인터넷 배포 서버에서 사용"""
    try:
        import pytesseract
        return "kor" in pytesseract.get_languages(config="")
    except Exception:
        return False


def ocr_backend():
    """자동 가림에 쓸 글자 인식기: PC는 EasyOCR, 인터넷 배포 서버는 Tesseract"""
    if easyocr_ready():
        return "easyocr"
    if tesseract_ready():
        return "tesseract"
    return None


def load_image(image_bytes, max_side=2000):
    """사진 열기: 회전 정보 반영, 너무 크면 줄이기 (OCR 속도·AI 전송 용량)"""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    img.thumbnail((max_side, max_side))
    return img


NAME_LABELS = {"환자성명", "성명", "환자명", "이름", "보호자"}
ADDRESS_LABELS = {"주소"}
# 이름처럼 보여도 영수증의 제목 칸인 경우를 걸러내는 단어
HEADER_WORDS = ["진료", "기간", "과목", "영수", "계산", "금액", "합계", "급여", "부담", "병실", "환자",
                "번호", "성명", "검사", "항목", "구분", "외래", "입원", "야간", "공휴", "선택"]


def looks_like_value(label, text):
    """label 옆/아래 글자가 그 label의 '값'처럼 생겼는지 (제목 칸·진료 항목은 제외)"""
    clean = text.replace(" ", "")
    if any(lb in clean for lb in SENSITIVE_LABELS):
        return False
    if label in NAME_LABELS:  # 이름: 한글 2~4자
        return re.fullmatch(r"[가-힣]{2,4}", clean) is not None and not any(w in clean for w in HEADER_WORDS)
    if label in ADDRESS_LABELS:  # 주소: 시·구·동·로·길이 들어간 한글
        return len(clean) >= 4 and re.search(r"(시|도|구|군|동|읍|면|로|길)", clean) is not None
    return len(re.findall(r"\d", clean)) >= 4  # 번호류: 숫자 4개 이상


def find_sensitive_boxes(ocr_items, img_width, img_height=None):
    """ocr_items: [(x0, y0, x1, y1, 글자), ...] → 가릴 박스 [{box, reason, hint}, ...]"""
    found = {}

    def add(box, reason, text):
        key = tuple(box)
        if key not in found:
            if reason in NAME_LABELS:
                hint = text[:1] + "*" * max(len(text) - 1, 0)  # 이름은 첫 글자만 보여줌
            else:
                hint = "*" * min(len(text), 8)
            found[key] = {"box": list(box), "reason": reason, "hint": hint}

    def part(item, start, end):
        """한 칸에 다른 글자가 섞여 있을 때, 해당 부분만 글자 비율로 잘라낸 박스"""
        x0, y0, x1, y1, text = item
        # 한글은 넓고(1.0) 숫자·기호·공백은 좁게(0.55) 계산해서 위치를 맞춤
        widths = [1.0 if "가" <= ch <= "힣" else 0.55 for ch in text] or [1.0]
        total = sum(widths)
        a = x0 + (x1 - x0) * sum(widths[:start]) / total
        b = x0 + (x1 - x0) * sum(widths[:end]) / total
        margin = (x1 - x0) / total * 0.4  # 계산 오차를 덮도록 글자 반쯤 넉넉하게
        return (int(a - margin), y0, int(b + margin), y1)

    def extend_line(start, reason):
        """주소처럼 긴 값은 여러 조각으로 인식되므로, 값 시작점부터 같은 줄 끝(또는 다음 제목 글자 앞)까지 한 번에 가림"""
        x0, y0, x1, y1 = start[:4]
        h = max(y1 - y0, 1)
        cy = (y0 + y1) / 2
        same = [o for o in ocr_items if abs((o[1] + o[3]) / 2 - cy) < h * 0.7 and o[2] > x0]
        stops = [o[0] for o in same if o[0] > x1 and any(lb in o[4].replace(" ", "") for lb in SENSITIVE_LABELS)]
        limit = min(stops) if stops else img_width
        seg = [o for o in same if o[0] < limit and not any(lb in o[4].replace(" ", "") for lb in SENSITIVE_LABELS)]
        if seg:
            add((x0, min([y0] + [o[1] for o in seg]), max([x1] + [o[2] for o in seg]),
                 max([y1] + [o[3] for o in seg])), reason, start[4] if len(start) > 4 else "")

    # 1차: 모양으로 바로 알 수 있는 것 (주민등록번호, 전화번호)
    for item in ocr_items:
        text = item[4]
        for regex, reason in ((RRN_RE, "주민등록번호"), (PHONE_RE, "전화번호")):
            for m in regex.finditer(text):
                add(part(item, m.start(), m.end()), reason, m.group())

    # 1-2차: 영수증 위쪽(환자 정보 칸)에 따로 떨어진 7~10자리 숫자 = 환자등록번호로 보고 가림
    #        (금액은 쉼표, 날짜는 '-'가 있어서 해당되지 않음)
    if img_height:
        for item in ocr_items:
            if item[1] < img_height * 0.3 and re.fullmatch(r"\d{7,10}", item[4].replace(" ", "")):
                add(item[:4], "환자등록번호", item[4])

    # 2차: '성명', '주소' 같은 제목 글자를 찾아 그 값을 가림
    for item in ocr_items:
        x0, y0, x1, y1, text = item
        clean = text.replace(" ", "")
        label = next((lb for lb in SENSITIVE_LABELS if lb in clean), None)
        if not label:
            continue
        idx = text.find(label[-1]) + 1  # "성명: 홍길동"처럼 한 칸에 값이 같이 있는 경우
        rest = text[idx:].lstrip(" :：")
        if rest and looks_like_value(label, rest):
            add(part(item, len(text) - len(rest), len(text)), label, rest)
            if label in ADDRESS_LABELS:
                extend_line((*part(item, len(text) - len(rest), len(text)), rest), label)
            continue
        h = max(y1 - y0, 1)
        cy = (y0 + y1) / 2
        right = sorted([o for o in ocr_items if o is not item and o[0] >= x1 - 5
                        and abs((o[1] + o[3]) / 2 - cy) < h * 0.7 and o[0] - x1 < img_width * 0.35],
                       key=lambda o: o[0])
        below = sorted([o for o in ocr_items if o is not item and y1 <= o[1] <= y1 + h * 2.5
                        and o[0] < x1 and o[2] > x0], key=lambda o: o[1])
        # 오른쪽 칸 → 바로 아래 칸 순서로, 값처럼 생긴 첫 칸을 가림
        for o in right[:1] + below[:1]:
            if looks_like_value(label, o[4]):
                add(o[:4], label, o[4])
                if label in ADDRESS_LABELS:
                    extend_line(o, label)
                break
    return list(found.values())


def detect_sensitive(img, reader):
    """EasyOCR로 글자 위치를 읽고 개인정보 박스 찾기"""
    import numpy as np

    items = []
    # canvas_size: 글자 위치를 찾을 때 그림을 이 크기로 줄여서 빠르게 (기본값 2560 → 1600)
    for points, text, _conf in reader.readtext(np.array(img), canvas_size=1600):
        xs = [int(p[0]) for p in points]
        ys = [int(p[1]) for p in points]
        items.append((min(xs), min(ys), max(xs), max(ys), text))
    return find_sensitive_boxes(items, img.width, img.height)


def detect_sensitive_tesseract(img):
    """Tesseract로 글자 위치를 읽고 개인정보 박스 찾기.
    한 가지 설정만으로는 놓치는 칸이 있어서, 설정 3가지로 읽은 결과를 합쳐서 가림 (약 4초)"""
    import pytesseract

    found = []
    gray = ImageOps.grayscale(img)
    for psm, scale in ((4, 1.5), (11, 1.0), (3, 1.0)):
        g = gray.resize((int(gray.width * scale), int(gray.height * scale))) if scale != 1 else gray
        d = pytesseract.image_to_data(g, lang="kor+eng", config=f"--psm {psm}",
                                      output_type=pytesseract.Output.DICT)
        words = [(int(d["left"][i] / scale), int(d["top"][i] / scale),
                  int((d["left"][i] + d["width"][i]) / scale), int((d["top"][i] + d["height"][i]) / scale),
                  d["text"][i].strip())
                 for i in range(len(d["text"])) if d["text"][i].strip() and float(d["conf"][i]) > 0]
        # 같은 줄에서 가까운 단어끼리 하나로 묶기 ("서울특별시" "가상구" → "서울특별시 가상구")
        words.sort(key=lambda w: (w[1], w[0]))
        items = []
        for w in words:
            for k, it in enumerate(items):
                h = max(it[3] - it[1], w[3] - w[1], 1)
                if abs((it[1] + it[3]) / 2 - (w[1] + w[3]) / 2) < h * 0.5 and 0 <= w[0] - it[2] < h * 1.2:
                    items[k] = (it[0], min(it[1], w[1]), w[2], max(it[3], w[3]), it[4] + " " + w[4])
                    break
            else:
                items.append(w)
        found += find_sensitive_boxes(items, img.width, img.height)
    # 같은 항목이 여러 번 잡히면 하나만 남김
    unique, seen = [], set()
    for f in found:
        key = (f["reason"], round(f["box"][0] / 15), round(f["box"][1] / 15))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def apply_masks(img, boxes):
    """박스 위치를 검은색으로 칠한 새 이미지 (원본은 그대로)"""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    for x0, y0, x1, y1 in boxes:
        draw.rectangle([max(x0 - MASK_PAD, 0), max(y0 - MASK_PAD, 0),
                        min(x1 + MASK_PAD, img.width), min(y1 + MASK_PAD, img.height)], fill="black")
    return out


def to_jpeg(img):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def scrub(obj):
    """AI 결과에 혹시 남은 주민번호·전화번호를 한 번 더 지움 (2차 안전장치)"""
    if isinstance(obj, str):
        return PHONE_RE.sub("***-****-****", RRN_RE.sub("******-*******", obj))
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    return obj


# ════════════════════════════════════════════════════════════
# 6. 분석·매칭 (규칙 기반 — AI가 판단하지 않고 코드가 계산)
# ════════════════════════════════════════════════════════════
CHECKUP_RULES = [  # (검진 항목, 기준값, 관심 키워드) — 진단이 아니라 '확인해 볼 신호'로만 사용
    ("systolic", 140, "고혈압"), ("diastolic", 90, "고혈압"),
    ("fasting_glucose", 126, "당뇨"), ("total_cholesterol", 240, "콜레스테롤"),
]
GENERIC_KEYWORDS = {"의료비", "검진", "재활"}
DIAGNOSIS_KEYWORDS = {"I10": "고혈압", "고혈압": "고혈압", "E11": "당뇨", "E14": "당뇨", "당뇨": "당뇨",
                      "C": "암", "암": "암", "종양": "암", "F00": "치매", "G30": "치매", "치매": "치매"}


def age_to_life(age):
    return "아동" if age < 19 else "청년" if age < 35 else "중장년" if age < 65 else "노년"


def keywords_from_user(checkup, diagnoses, extra):
    kws = set(extra)
    for field, threshold, kw in CHECKUP_RULES:
        v = checkup.get(field)
        if v is not None and v >= threshold:
            kws.update([kw, "검진"])
    for d in diagnoses:
        for key, kw in DIAGNOSIS_KEYWORDS.items():
            if key.isascii():
                if d.strip().upper().startswith(key):  # 상병코드는 앞자리로 매칭
                    kws.add(kw)
            elif key in d:
                kws.add(kw)
    return sorted(kws)


def score_benefits(benefits, keywords, age, high_cost):
    """혜택마다 점수: 질환 키워드 4점, 일반 키워드 2점, 생애주기 일치 2점, 의료비 부담 1점"""
    if not benefits:
        return pd.DataFrame()
    df = pd.DataFrame(benefits)
    life = age_to_life(age)

    def text_of(row):
        return " ".join([str(row.get("name", "")), str(row.get("target", "")),
                         str(row.get("content", "")), " ".join(row.get("keywords") or [])])

    def score(row):
        text = text_of(row)
        s = sum(2 if k in GENERIC_KEYWORDS else 4 for k in keywords if k in text)
        if row.get("life") and life in row["life"]:
            s += 2
        if high_cost and any(k in text for k in ["의료비", "본인부담", "환급"]):
            s += 1
        return s

    df["score"] = df.apply(score, axis=1)
    df["matched"] = df.apply(lambda r: [k for k in keywords if k in text_of(r)], axis=1)
    return df[df["score"] > 0].sort_values("score", ascending=False).reset_index(drop=True)


def analyze_receipt(receipt):
    """영수증 금액 구조 분석"""
    t = receipt.get("totals") or {}
    items = pd.DataFrame(receipt.get("items") or [])
    covered_self = t.get("covered_self") or 0
    non_cov = t.get("non_covered") or 0
    full_self = t.get("full_self") or 0
    insurer = t.get("covered_insurer") or 0
    patient_pay = t.get("patient_pay") or (covered_self + non_cov + full_self)
    total = patient_pay + insurer
    top_non_cov = []
    if not items.empty and "non_covered" in items:
        top_non_cov = (items[items["non_covered"].fillna(0) > 0]
                       .sort_values("non_covered", ascending=False)[["name", "non_covered"]].to_dict("records"))
    return {
        "total_cost": total, "patient_pay": patient_pay, "insurer_pay": insurer, "non_covered": non_cov,
        "non_covered_ratio": round(non_cov / patient_pay * 100, 1) if patient_pay else 0,
        "insurer_ratio": round(insurer / total * 100, 1) if total else 0,
        "top_non_covered_items": top_non_cov,
        # 본인부담상한제는 급여 본인부담만 합산하므로 비급여가 크면 안내 필요
        "flag_non_covered_heavy": patient_pay > 0 and non_cov / patient_pay >= 0.5,
    }


# ════════════════════════════════════════════════════════════
# 7. 생성형 AI 안내문 (분석 결과만 받아서 쉬운 말로 설명)
# ════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """당신은 '메디행정톡'의 의료 행정 안내 도우미입니다.
규칙:
1. 제공된 [데이터] 안의 정보만 근거로 설명합니다. 데이터에 없는 지원금액·자격기준·제도를 지어내지 마세요.
2. 중학생도 이해할 수 있는 쉬운 말로, 행정 용어는 괄호로 풀이합니다. 예: 급여(건강보험이 적용되는 항목)
3. 의학적 진단이나 치료 권고는 하지 않습니다. 건강 관련 판단은 의료진 상담을 권합니다.
4. 지원 여부는 '가능성이 있다'로 표현하고, 최종 확인처(기관명·전화·사이트)를 함께 알려줍니다.
5. 답변 마지막에 '※ 실제 지원 여부와 금액은 담당 기관에서 최종 확인하세요.'를 붙입니다."""
NOTICE = "\n\n※ 실제 지원 여부와 금액은 담당 기관에서 최종 확인하세요."


def ask_claude(user_content, history=None):
    msg = claude_client().messages.create(
        model=CLAUDE_MODEL, max_tokens=1500, system=SYSTEM_PROMPT,
        messages=(history or []) + [{"role": "user", "content": user_content}])
    return msg.content[0].text


def explain_receipt(receipt, a):
    if use_demo_llm():
        lines = [f"**{receipt.get('hospital')}** ({receipt.get('visit_date')}, {receipt.get('patient_type')}) 진료비 요약 (데모)",
                 f"- 전체 진료비 약 {a['total_cost']:,}원 중 건강보험공단이 {a['insurer_pay']:,}원({a['insurer_ratio']}%)을 냈어요.",
                 f"- 내가 낸 돈은 {a['patient_pay']:,}원이고, 그중 비급여(건강보험이 안 되는 항목)가 "
                 f"{a['non_covered']:,}원({a['non_covered_ratio']}%)이에요."]
        if a["top_non_covered_items"]:
            names = ", ".join(i["name"] for i in a["top_non_covered_items"])
            lines.append(f"- 비급여 항목: {names} → 실손보험에 가입했다면 청구 대상인지 확인해 보세요.")
        lines.append("- 본인부담상한제는 '급여 본인부담금'만 합산하므로 비급여는 포함되지 않아요.")
        return "\n".join(lines) + NOTICE
    return ask_claude(f"""[데이터]
영수증 인식 결과: {json.dumps(receipt, ensure_ascii=False)}
금액 분석 결과: {json.dumps(a, ensure_ascii=False)}

[요청]
1) 이번 진료비가 어떻게 나뉘었는지(공단부담/본인부담/비급여) 3줄로 설명
2) 비급여 항목이 무엇이고 왜 건강보험이 적용되지 않는지 일반적인 의미 설명
3) 본인부담상한제·실손보험 청구 등 확인해 볼 만한 제도 안내 (비급여는 상한제 합산 대상이 아님을 정확히)
4) 보관해야 할 서류 체크리스트""")


def explain_benefits(user, matched):
    if use_demo_llm():
        if not matched:
            return "조건에 맞는 혜택을 찾지 못했어요. 지역이나 관심 질환을 바꿔 보세요."
        out = ["(데모) 해당될 수 있는 혜택이에요:\n"]
        for i, b in enumerate(matched[:5], 1):
            out.append(f"**{i}. {b['name']}** — {b['content']}\n   · 신청: {b['apply']}")
        return "\n".join(out) + NOTICE
    return ask_claude(f"""[데이터]
사용자 정보: {json.dumps(user, ensure_ascii=False)}
매칭된 공공 보건 혜택(점수순): {json.dumps(matched[:6], ensure_ascii=False, default=str)}

[요청]
위 혜택을 우선순위대로 소개하세요. 각 혜택마다
- 한 줄 요약 / 왜 이 사용자에게 해당될 수 있는지 / 어디서 어떻게 신청하는지
형식으로 정리하세요.""")


# ── 자주 묻는 질문 13개 (버튼을 누르면 답이 보임) ──
#    국민건강보험공단·건강보험심사평가원·금융위원회 등 공식 안내 기준 (2026년 11월 확인). 기준이 바뀌면 여기만 고치면 됨.
FAQ = [
    # ── 진료비 이해하기 ──
    {"id": "structure", "cat": "진료비 이해하기", "q": "건강보험 진료비는 어떻게 나뉘어요?",
     "answer": """**진료비 = 공단이 내는 돈 + 내가 내는 돈**이에요.

1. **급여** (건강보험이 적용되는 진료)
   - 공단부담금: 건강보험공단이 병원에 대신 내 줘요.
   - 본인부담금: 내가 내는 부분이에요. 외래 기본 비율은 **의원 30%, 병원 40%, 종합병원 50%, 상급종합병원 60%**예요. (나이·질환·지역에 따라 달라질 수 있어요)
2. **전액본인부담**: 급여 항목이지만 기준을 벗어나 내가 전부 내는 부분이에요.
3. **비급여**: 건강보험이 적용되지 않아 내가 전부 내는 진료예요. (예: 도수치료, 상급병실, 일부 초음파·MRI)

💡 비급여 가격은 병원마다 달라요. 건강보험심사평가원 누리집에서 병원별 비급여 가격을 비교할 수 있어요.""",
     "contact": "국민건강보험공단 1577-1000"},
    {"id": "terms", "cat": "진료비 이해하기", "q": "영수증에 적힌 용어가 무슨 뜻이에요?",
     "answer": """| 영수증 용어 | 쉬운 뜻 |
|---|---|
| 본인부담금 | 건강보험이 되는 진료 중 **내가 낸 돈** |
| 공단부담금 | 건강보험공단이 **대신 낸 돈** |
| 전액본인부담 | 보험 항목이지만 기준을 넘어서 **내가 전부 낸 돈** |
| 비급여 | 건강보험이 **안 되는** 진료비 |
| 선택진료료 | 예전 특진비 항목 (현재는 대부분 폐지돼 0원인 경우가 많아요) |
| 진료비 총액 | 공단 + 내가 낸 돈을 모두 더한 금액 |
| 환자부담 총액 | 내가 낸 돈 전체 (본인부담 + 전액본인부담 + 비급여) |
| 납부할 금액 | 환자부담 총액에서 이미 낸 돈을 뺀, 오늘 낼 돈 |

💡 항목별로 더 자세히 보려면 병원 원무과에서 **진료비 세부산정내역서**를 받으세요.""",
     "contact": "국민건강보험공단 1577-1000"},
    {"id": "elderly", "cat": "진료비 이해하기", "q": "65세 이상은 동네 의원 진료비가 다른가요?",
     "answer": """**네. 65세 이상은 동네 의원 외래 진료비가 적으면 정해진 금액만 내요 (노인 외래 정액제).**

| 그날 의원 총진료비 | 내가 내는 돈 |
|---|---|
| 1만 5천 원 이하 | **1,500원** |
| 1만 5천 원 초과 ~ 2만 원 이하 | 총진료비의 10% |
| 2만 원 초과 ~ 2만 5천 원 이하 | 총진료비의 20% |
| 2만 5천 원 초과 | 총진료비의 30% |

- **의원(동네 병원) 외래**에 적용돼요. 병원·종합병원은 일반 비율이 적용돼요.
- 진찰료가 오르면 같은 진료라도 위 구간이 바뀌어 본인부담이 달라질 수 있어요.""",
     "contact": "국민건강보험공단 1577-1000"},
    {"id": "referral", "cat": "진료비 이해하기", "q": "대학병원 갈 때 진료의뢰서가 꼭 필요해요?",
     "answer": """**네. 상급종합병원(대학병원 등)은 진료의뢰서가 있어야 건강보험이 적용돼요.**

- 의뢰서 없이 가면 진료는 받을 수 있지만 **진료비를 100% 내가 내요.** 나중에 의뢰서를 내도 이미 낸 돈은 돌려받기 어려워요.
- **발급**: 먼저 동네 의원·병원에서 진료받고 **진료의뢰서(요양급여의뢰서)**를 받으세요.
- 건강보험 의뢰서는 따로 유효기간이 없지만, **적힌 진료과에서만** 쓸 수 있어요.

**의뢰서가 필요 없는 경우**
- 응급환자, 분만
- 가정의학과 진료
- 등록 장애인의 재활의학과 치료, 혈우병 환자 등

💡 예외는 병원마다 안내가 조금 다를 수 있으니 예약할 때 확인하세요.""",
     "contact": "방문할 병원 예약센터, 국민건강보험공단 1577-1000"},
    # ── 돌려받기·지원받기 ──
    {"id": "ceiling", "cat": "돌려받기·지원받기", "q": "본인부담상한제 환급은 어떻게 받아요?",
     "answer": """**1년 동안 낸 급여 본인부담금이 내 상한액을 넘으면, 넘은 돈을 공단이 돌려줘요.**

**신청 순서**
1. 공단이 대상자에게 **안내문(지급신청서)**을 보내요. 상한액은 보통 매년 8월쯤 확정돼요.
2. 아래 중 편한 방법으로 신청해요.
   - 국민건강보험공단 홈페이지 또는 모바일 앱
   - 전화 1577-1000 (본인 명의 계좌일 때)
   - 지사 방문·팩스·우편 (지급신청서 제출)
3. 본인 계좌로 받으면 **지급신청서만** 있으면 돼요. 가족·다른 사람 계좌는 위임장, 가족관계증명서 등이 더 필요해요.

**꼭 알아둘 점**
- **비급여, 전액본인부담, 상급병실(2·3인실) 입원료 등은 합산되지 않아요.**
- 지급동의계좌를 등록해 두면 다음부터는 신청 없이 자동으로 들어와요.""",
     "contact": "국민건강보험공단 1577-1000"},
    {"id": "catastrophic", "cat": "돌려받기·지원받기", "q": "병원비가 너무 많이 나왔어요. 지원받을 수 있나요?",
     "answer": """**소득에 비해 의료비 부담이 크면 '재난적의료비 지원'을 신청할 수 있어요.**

**대상 (요약)**
- 기본: 가구 소득이 기준 중위소득 100% 이하, 재산 7억 원 이하
- 본인부담 의료비가 소득 대비 기준을 넘을 때 (중위소득 100~200%는 개별심사)

**지원**: 소득 구간에 따라 본인부담 의료비의 50~80%, 연간 최대 5천만 원

**신청 기한**: 최종 진료일(퇴원일) **다음날부터 180일 이내**

**신청 방법**: 국민건강보험공단 지사 방문 (부득이하면 우편·팩스)

**필요 서류**
1. 재난적의료비 지급신청서 + 신분증, 각종 동의서 (공단 양식)
2. 진단서 (질병명·질병코드 포함), 입·퇴원확인서 또는 통원사실확인서 — 병원
3. 진료비 계산서·영수증 + 비급여 포함 세부내역서 — 병원 원무과
4. 가족관계증명서(상세) — 행정복지센터·정부24

⚠️ 실손보험으로 받은 돈은 빼고 지원돼요.""",
     "contact": "국민건강보험공단 1577-1000"},
    {"id": "special", "cat": "돌려받기·지원받기", "q": "암·희귀질환은 진료비가 줄어드나요? (산정특례)",
     "answer": """**네. '산정특례'로 등록하면 그 질환 진료비의 본인부담이 크게 줄어요.**

| 질환 | 본인부담 (건강보험 진료) |
|---|---|
| 암 | **5%** |
| 희귀질환·중증난치질환 | **10%** (5%로 낮추는 개편이 추진 중이에요) |
| 결핵 | 0% |

- **신청**: 진단받은 병원에서 의사가 **산정특례 등록 신청서**를 써 주면, 병원이 공단에 등록해 줘요.
- **기간**: 보통 5년이고, 끝나기 전에 재등록할 수 있어요.
- 비급여는 줄어들지 않아요.

💡 희귀질환 본인부담률은 바뀌는 중이라, 정확한 비율은 공단에 확인하세요.""",
     "contact": "국민건강보험공단 1577-1000"},
    {"id": "tax", "cat": "돌려받기·지원받기", "q": "병원비는 연말정산에서 돌려받을 수 있나요?",
     "answer": """**네. 직장인은 연말정산 '의료비 세액공제'로 일부를 돌려받아요.**

- **기준**: 1년 의료비가 **총급여의 3%를 넘는 부분**부터 공제돼요.
- **공제율**: 넘는 금액의 **15%** (난임 시술비 30%, 미숙아·선천성이상아 의료비 20%)
- **한도**: 본인·65세 이상·장애인·6세 이하 등은 한도가 없고, 그 밖의 가족은 연 700만 원까지예요.
- **실손보험으로 돌려받은 돈은 빼고** 계산해요.

**확인 방법**
- 국세청 **홈택스 연말정산 간소화 서비스**에 병원비가 자동으로 모여요.
- 빠진 병원비는 병원에서 **의료비 납입확인서**를 받아 회사에 내면 돼요.""",
     "contact": "국세청 126"},
    {"id": "nonpay_check", "cat": "돌려받기·지원받기", "q": "비급여 진료비가 맞게 나왔는지 확인하고 싶어요",
     "answer": """**건강보험심사평가원 '진료비 확인 서비스'로 확인을 요청할 수 있어요.**

1. 비급여로 낸 돈 중에 **건강보험이 적용됐어야 하는 항목**이 있는지 심평원이 확인해 줘요.
2. 잘못 받은 돈으로 확인되면 병원이 **돌려줘요(환불)**.
3. 신청: 건강보험심사평가원 누리집 또는 앱 (진료비 영수증·세부내역서를 준비하세요)

💡 메디행정톡의 **내 진료비 기록**에서 '비급여 비중 높음' 표시가 붙은 영수증부터 확인해 보세요.""",
     "contact": "건강보험심사평가원 1644-2000"},
    # ── 보험·서류 ──
    {"id": "silson", "cat": "보험·서류", "q": "실손보험은 어떻게 청구해요?",
     "answer": """**'실손24' 앱으로 서류 없이 청구할 수 있어요.**

**실손24로 청구하기** (병원·보건소, 2025년 10월 25일부터 의원·약국까지 확대)
1. 실손24 앱 설치 (또는 silson24.or.kr) → 본인인증
2. 보험계약 선택 → 병원 선택 → 진료일자·내역 선택
3. 청구서 작성 → 전송하면 병원이 보험사로 서류를 바로 보내요.
- 내가 간 병원이 연계됐는지는 네이버지도·카카오맵에서 '실손24'로 검색해 보세요.

**서류로 직접 청구할 때** (병원 원무과에서 발급)
- 진료비 계산서·영수증
- 진료비 세부산정내역서 (비급여 항목 확인용)
- 질병명이 적힌 서류 (처방전의 질병분류기호, 진단서 등 — 보험사·금액에 따라 달라요)

⏰ 보험금은 진료일로부터 **3년 안에** 청구해야 해요.""",
     "contact": "실손24 콜센터 1811-3000, 가입한 보험사"},
    {"id": "docs", "cat": "보험·서류", "q": "병원 서류는 어디서 발급받아요?",
     "answer": """| 서류 | 발급처 |
|---|---|
| 진료비 계산서·영수증 | 병원 원무과 (수납할 때) |
| 진료비 세부산정내역서 | 병원 원무과 (일부 병원은 앱에서도) |
| 진단서·소견서 | 진료받은 의사 (병원, 유료) |
| 입·퇴원확인서, 통원확인서 | 병원 원무과 |
| 의료비 납입확인서 (연말정산용) | 병원 원무과 |
| 가족관계증명서 | 정부24, 행정복지센터 |
| 건강보험 자격득실확인서 | 국민건강보험공단 홈페이지·앱, 정부24 |

💡 실손보험·의료비 지원을 같이 신청할 거라면, 원무과에서 **영수증과 세부산정내역서를 한 번에** 받아 두면 편해요.""",
     "contact": "각 병원 원무과"},
    # ── 건강·돌봄 ──
    {"id": "checkup", "cat": "건강·돌봄", "q": "국가건강검진은 언제, 무료로 받을 수 있나요?",
     "answer": """**만 20세 이상은 2년마다 국가 일반건강검진을 무료로 받을 수 있어요.**

- **대상**: 직장가입자, 지역세대주, 만 20세 이상 세대원·피부양자 등 (출생연도가 짝수면 짝수 해, 홀수면 홀수 해)
- **비용**: 일반건강검진은 **무료**예요. 대상이 아닌 검사를 추가하면 본인 부담이에요.

**6대 암검진**
| 암 | 대상 | 주기 | 본인부담 |
|---|---|---|---|
| 위암 | 40세 이상 | 2년 | 10% |
| 대장암 | 50세 이상 | 1년 | 무료 |
| 유방암 | 40세 이상 여성 | 2년 | 10% |
| 자궁경부암 | 20세 이상 여성 | 2년 | 무료 |
| 간암 | 40세 이상 고위험군 | 6개월 | 10% |
| 폐암 | 54~74세 고위험군 | 2년 | 10% |

- 건강보험료 하위 50%와 의료급여 수급자는 암검진도 **무료**예요.
- **대상 조회**: 국민건강보험공단 홈페이지·모바일 앱

💡 검진에서 이상 소견이 나오면 **혜택 찾기**에서 보건소 만성질환 관리 사업을 찾아보세요.""",
     "contact": "국민건강보험공단 1577-1000"},
    {"id": "ltc", "cat": "건강·돌봄", "q": "부모님 요양(장기요양등급)은 어떻게 신청해요?",
     "answer": """**혼자 일상생활이 어려운 어르신은 '노인장기요양보험' 등급을 받아 방문요양·요양원 등을 이용할 수 있어요.**

**대상**
- 만 65세 이상
- 만 65세 미만이라도 치매·뇌혈관질환·파킨슨병 등 **노인성 질병**이 있는 분

**신청 순서**
1. **신청**: 국민건강보험공단 지사 방문, 우편·팩스, 또는 노인장기요양보험 누리집
2. **방문 조사**: 공단 직원이 집으로 찾아와 몸 상태를 확인해요.
3. **의사소견서 제출**: 공단 안내에 따라 병원에서 발급받아 내요.
4. **등급 판정**: 등급판정위원회가 등급을 정하고 결과를 알려줘요.

💡 등급을 받으면 서비스 비용의 대부분을 장기요양보험이 내고, 본인은 일부만 내요. (소득에 따라 감경 가능)""",
     "contact": "국민건강보험공단 1577-1000"},
]
FAQ_CATS = ["진료비 이해하기", "돌려받기·지원받기", "보험·서류", "건강·돌봄"]


def faq_extra(faq_id, context):
    """저장된 내 영수증 기록으로 덧붙이는 한 줄"""
    context = context or {}
    r = context.get("최근_영수증")
    if faq_id == "structure" and r:
        return (f"**내 최근 영수증으로 보면** ({r['병원']}, {r['날짜']}): 총 진료비 {r['총진료비']:,}원 중 "
                f"내가 낸 돈 {r['내가낸돈']:,}원, 그중 비급여 {r['비급여']:,}원이에요.")
    if faq_id == "ceiling" and context.get("올해_급여본인부담"):
        return (f"**메디행정톡에 저장한 영수증 기준 올해 급여 본인부담금은 {context['올해_급여본인부담']:,}원**이에요. "
                "(저장한 영수증만 합산한 금액이에요)")
    if faq_id == "silson" and r and r.get("비급여"):
        return (f"**내 최근 영수증** ({r['병원']}, {r['날짜']})에서 내가 낸 돈은 {r['내가낸돈']:,}원"
                f"(비급여 {r['비급여']:,}원 포함)이에요. 실손보험에 가입했다면 청구 대상인지 확인해 보세요.")
    if faq_id == "tax" and context.get("올해_내가낸돈"):
        return f"**메디행정톡에 저장한 영수증 기준 올해 내가 낸 병원비는 {context['올해_내가낸돈']:,}원**이에요."
    return ""


def faq_text(faq_id, context=None):
    f = next(x for x in FAQ if x["id"] == faq_id)
    out = [f["answer"]]
    extra = faq_extra(faq_id, context)
    if extra:
        out += ["", "---", extra]
    out += ["", f"📞 **문의**: {f['contact']}", "", "※ 실제 지원 여부와 금액은 담당 기관에서 최종 확인하세요."]
    return "\n".join(out)


def chat_guide(question, context, history):
    """(현재 화면에서는 쓰지 않음) Claude에게 자유 질문을 할 때 사용"""
    return ask_claude(f"""[데이터]
{json.dumps(context, ensure_ascii=False, default=str)}

[사용자 질문]
{question}

신청 절차를 단계별(1단계, 2단계…)로, 필요한 서류와 발급처(정부24·병원 원무과·건강보험공단 등)를 함께 안내하세요.""",
                      history)




# ════════════════════════════════════════════════════════════
# 8. 기록 저장 (SQLite) — 영수증 분석 결과만 저장, 사진은 저장하지 않음
#    최근 기록은 MAX_ACTIVE_RECORDS(10)건까지, 넘으면 오래된 것부터 보관함으로 이동
# ════════════════════════════════════════════════════════════
import datetime as dt
import sqlite3

DB_PATH = Path(__file__).resolve().parent / "mediadmin_records.db"

SCHEMA = """CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT, visit_date TEXT, hospital TEXT, department TEXT, patient_type TEXT,
    total_cost INTEGER, patient_pay INTEGER, insurer_pay INTEGER,
    covered_self INTEGER, full_self INTEGER, non_covered INTEGER,
    items TEXT, diagnosis TEXT, explanation TEXT, archived INTEGER DEFAULT 0
)"""


def open_db(path=None):
    conn = sqlite3.connect(str(path or DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def save_record(conn, receipt, analysis, explanation, created_at=None):
    """영수증 1건 저장 → (새 기록 id, 보관함으로 옮긴 개수)"""
    t = receipt.get("totals") or {}
    visit = str(receipt.get("visit_date") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", visit):
        visit = dt.date.today().isoformat()
    cur = conn.execute(
        """INSERT INTO records (created_at, visit_date, hospital, department, patient_type, total_cost, patient_pay,
           insurer_pay, covered_self, full_self, non_covered, items, diagnosis, explanation, archived)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
        (created_at or dt.datetime.now().isoformat(timespec="seconds"), visit,
         receipt.get("hospital") or "병원 이름 미확인", receipt.get("department") or "",
         receipt.get("patient_type") or "", _int(analysis["total_cost"]), _int(analysis["patient_pay"]),
         _int(analysis["insurer_pay"]), _int(t.get("covered_self")), _int(t.get("full_self")),
         _int(analysis["non_covered"]), json.dumps(receipt.get("items") or [], ensure_ascii=False),
         json.dumps(receipt.get("diagnosis") or [], ensure_ascii=False), explanation or ""))
    conn.commit()
    return cur.lastrowid, archive_overflow(conn)


def archive_overflow(conn, limit=None):
    """최근 기록이 limit건을 넘으면, 가장 먼저 저장한 기록부터 보관함으로 이동"""
    limit = limit or MAX_ACTIVE_RECORDS
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM records WHERE archived=0 ORDER BY created_at DESC, id DESC").fetchall()]
    overflow = ids[limit:]
    if overflow:
        conn.executemany("UPDATE records SET archived=1 WHERE id=?", [(i,) for i in overflow])
        conn.commit()
    return len(overflow)


def load_records(conn, include_archived=True):
    sql = "SELECT * FROM records" + ("" if include_archived else " WHERE archived=0")
    df = pd.read_sql_query(sql + " ORDER BY visit_date DESC, id DESC", conn)
    if not df.empty:
        df["items"] = df["items"].apply(lambda s: json.loads(s or "[]"))
        df["diagnosis"] = df["diagnosis"].apply(lambda s: json.loads(s or "[]"))
        df["month"] = df["visit_date"].str[:7]
        df["self_covered"] = df["covered_self"] + df["full_self"]
    return df


def delete_record(conn, record_id):
    conn.execute("DELETE FROM records WHERE id=?", (int(record_id),))
    conn.commit()


def delete_all(conn, archived_only=False):
    conn.execute("DELETE FROM records" + (" WHERE archived=1" if archived_only else ""))
    conn.commit()


def make_receipt(hospital, dept, visit, rows, diagnosis=None, ptype="외래"):
    """예시 기록용 영수증 만들기. rows = [(항목, 급여총액, 본인부담률, 비급여)]"""
    items = []
    for name, covered, rate, nc in rows:
        self_part = int(round(covered * rate, -1))
        items.append({"name": name, "covered_self": self_part, "covered_insurer": covered - self_part,
                      "full_self": 0, "non_covered": nc})
    totals = {k: sum(i[k] for i in items) for k in ("covered_self", "covered_insurer", "full_self", "non_covered")}
    totals["patient_pay"] = totals["covered_self"] + totals["full_self"] + totals["non_covered"]
    return {"doc_type": "진료비영수증", "hospital": hospital, "department": dept, "visit_date": visit,
            "patient_type": ptype, "items": items, "totals": totals, "diagnosis": diagnosis or []}


SAMPLE_VISITS = [  # 예시 기록 12건 (가상의 병원) — 10건을 넘으므로 오래된 2건은 보관함으로 이동
    ("튼튼정형외과의원", "정형외과", "2025-12-08", [("진찰료", 18000, .3, 0), ("영상진단료", 25000, .3, 0),
                                              ("재활 및 물리치료료", 15000, .3, 0), ("도수치료", 0, 0, 80000)]),
    ("맑은눈안과의원", "안과", "2026-01-15", [("진찰료", 17500, .3, 0), ("검사료", 32000, .3, 0)]),
    ("샘플대학교병원", "내분비내과", "2026-02-03", [("진찰료", 24380, .6, 0), ("검사료", 85600, .6, 0),
                                            ("초음파 진단료", 0, 0, 120000)], ["E11 2형 당뇨병"]),
    ("하늘내과의원", "내과", "2026-03-11", [("진찰료", 17500, .3, 0), ("주사료", 8000, .3, 0)]),
    ("튼튼정형외과의원", "정형외과", "2026-04-22", [("진찰료", 12000, .3, 0), ("재활 및 물리치료료", 15000, .3, 0),
                                              ("도수치료", 0, 0, 80000)]),
    ("샘플대학교병원", "내분비내과", "2026-05-07", [("진찰료", 24380, .6, 0), ("검사료", 64000, .6, 0)], ["E11 2형 당뇨병"]),
    ("미소치과의원", "치과", "2026-06-19", [("진찰료", 15000, .3, 0), ("처치 및 수술료", 45000, .3, 0),
                                       ("레진 충전", 0, 0, 150000)]),
    ("샘플대학교병원", "영상의학과", "2026-07-02", [("CT 진단료", 180000, .6, 0), ("MRI 진단료", 0, 0, 450000)]),
    ("하늘내과의원", "내과", "2026-08-14", [("진찰료", 17500, .3, 0), ("검사료", 22000, .3, 0)], ["I10 고혈압"]),
    ("샘플대학교병원", "내분비내과", "2026-09-05", [("진찰료", 24380, .6, 0), ("검사료", 85600, .6, 0)], ["E11 2형 당뇨병"]),
    ("맑은눈안과의원", "안과", "2026-10-20", [("진찰료", 17500, .3, 0), ("검사료", 32000, .3, 0),
                                       ("다초점 렌즈 검사", 0, 0, 50000)]),
    ("샘플대학교병원", "내분비내과", "2026-11-10", [("진찰료", 24380, .6, 0), ("주사료", 6250, .6, 0),
                                            ("검사료", 85600, .6, 0), ("영상진단료", 32400, .6, 0),
                                            ("초음파 진단료", 0, 0, 120000), ("제증명료", 0, 0, 20000)], ["E11 2형 당뇨병"]),
]


def add_sample_records(conn):
    moved = 0
    for hospital, dept, visit, rows, *dx in SAMPLE_VISITS:
        receipt = make_receipt(hospital, dept, visit, rows, dx[0] if dx else None)
        _, n = save_record(conn, receipt, analyze_receipt(receipt), "", created_at=visit + "T12:00:00")
        moved += n
    return moved


def won(n):
    return f"{int(n or 0):,}원"


# ── 약국 찾기 (국립중앙의료원_전국 약국 정보 조회 서비스, data.go.kr/data/15000576) ──
WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일", "공휴일"]

SAMPLE_PHARMACIES = [  # 체험 모드용 가상 약국 (서울시청 근처)
    {"dutyName": "(체험) 시청앞약국", "dutyAddr": "서울특별시 중구 세종대로 110 인근", "dutyTel1": "02-000-0001",
     "wgs84Lat": "37.5658", "wgs84Lon": "126.9772", **{f"dutyTime{d}s": "0900" for d in range(1, 7)},
     **{f"dutyTime{d}c": "2100" for d in range(1, 7)}},
    {"dutyName": "(체험) 광화문24시약국", "dutyAddr": "서울특별시 종로구 세종대로 170 인근", "dutyTel1": "02-000-0002",
     "wgs84Lat": "37.5720", "wgs84Lon": "126.9768", **{f"dutyTime{d}s": "0000" for d in range(1, 9)},
     **{f"dutyTime{d}c": "2400" for d in range(1, 9)}},
    {"dutyName": "(체험) 을지로온누리약국", "dutyAddr": "서울특별시 중구 을지로 100 인근", "dutyTel1": "02-000-0003",
     "wgs84Lat": "37.5660", "wgs84Lon": "126.9910", **{f"dutyTime{d}s": "0830" for d in range(1, 6)},
     **{f"dutyTime{d}c": "1900" for d in range(1, 6)}},
    {"dutyName": "(체험) 종로건강약국", "dutyAddr": "서울특별시 종로구 종로 200 인근", "dutyTel1": "02-000-0004",
     "wgs84Lat": "37.5704", "wgs84Lon": "126.9921", **{f"dutyTime{d}s": "1000" for d in range(1, 8)},
     **{f"dutyTime{d}c": "2200" for d in range(1, 8)}},
]


def check_api_error(text):
    """공공데이터포털 오류 응답을 알아듣기 쉬운 말로 바꿈"""
    for code, msg in [
        ("SERVICE_ACCESS_DENIED", "이 API는 아직 활용신청이 안 돼 있어요. 공공데이터포털에서 "
                                  "'국립중앙의료원_전국 약국 정보 조회 서비스'를 활용신청해 주세요."),
        ("SERVICE_KEY_IS_NOT_REGISTERED", "인증키가 아직 등록되지 않았어요. 활용신청 후 1~2시간 뒤에 다시 해 보세요."),
        ("LIMITED_NUMBER_OF_SERVICE_REQUESTS", "오늘 쓸 수 있는 호출 횟수를 다 썼어요. 내일 다시 해 보세요."),
        ("NO_OPENAPI_SERVICE", "API 주소를 찾지 못했어요. ENDPOINTS의 약국 주소를 확인해 주세요."),
    ]:
        if code in text:
            raise RuntimeError(msg)


def _hhmm(v):
    v = re.sub(r"\D", "", str(v or ""))
    return v.zfill(4) if v else ""


def normalize_pharmacy(p, day):
    """API 응답(목록·위치 조회 모두)을 같은 모양으로 정리. day: 1(월)~7(일), 8(공휴일)"""
    lat = p.get("wgs84Lat") or p.get("latitude")
    lon = p.get("wgs84Lon") or p.get("longitude")
    start = _hhmm(p.get(f"dutyTime{day}s") or p.get("startTime"))
    end = _hhmm(p.get(f"dutyTime{day}c") or p.get("endTime"))
    try:
        dist = float(p.get("distance")) if p.get("distance") not in (None, "") else None
    except ValueError:
        dist = None
    return {"name": p.get("dutyName", ""), "addr": p.get("dutyAddr", ""), "tel": p.get("dutyTel1", ""),
            "lat": float(lat) if lat else None, "lon": float(lon) if lon else None,
            "start": start, "end": end, "dist_km": dist}


def is_open(p, now):
    """지금 영업 중인지: True / False / None(정보 없음). 새벽까지 여는 곳(예: 2600)도 처리"""
    if not (p["start"] and p["end"]):
        return None
    cur = now.hour * 100 + now.minute
    s, e = int(p["start"]), int(p["end"])
    return s <= cur < e or (e > 2400 and cur < e - 2400)


def distance_km(lat1, lon1, lat2, lon2):
    import math
    r = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def today_code(now=None):
    """국립중앙의료원 요일 코드: 1(월)~7(일)"""
    return (now or dt.datetime.now()).weekday() + 1


def pharmacies_near(lat, lon, rows=30, now=None):
    """내 위치 기준 가까운 약국"""
    day = today_code(now)
    if use_demo_public():
        raw = SAMPLE_PHARMACIES
    else:
        r = api_get(ENDPOINTS["pharm_near"], {"WGS84_LON": lon, "WGS84_LAT": lat, "pageNo": 1, "numOfRows": rows})
        check_api_error(r.text)
        raw = xml_items(r.text, "item")
    out = [normalize_pharmacy(p, day) for p in raw]
    for p in out:
        if p["dist_km"] is None and p["lat"] is not None:
            p["dist_km"] = distance_km(lat, lon, p["lat"], p["lon"])
    return sorted(out, key=lambda p: (p["dist_km"] is None, p["dist_km"] or 0))


def pharmacies_in_region(sido, sigungu="", name="", rows=60, now=None):
    """시도·시군구(·약국 이름)로 약국 찾기 — 오늘 요일 기준 운영시간 포함"""
    day = today_code(now)
    if use_demo_public():
        raw = [p for p in SAMPLE_PHARMACIES if name in p["dutyName"]]
    else:
        params = {"Q0": SIDO_FULLNAMES.get(sido, sido), "QT": day, "ORD": "NAME", "pageNo": 1, "numOfRows": rows}
        if sigungu:
            params["Q1"] = sigungu
        if name:
            params["QN"] = name
        r = api_get(ENDPOINTS["pharm_list"], params)
        check_api_error(r.text)
        raw = xml_items(r.text, "item")
    return [normalize_pharmacy(p, day) for p in raw]


# ════════════════════════════════════════════════════════════
# 9. 화면 (Streamlit) — 파란색 테마, 버튼으로 페이지 이동
# ════════════════════════════════════════════════════════════
import html as html_lib

BLUE, BLUE_DARK, BLUE_LIGHT, BLUE_PALE = "#2563EB", "#1E3A8A", "#93C5FD", "#EAF1FF"

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
html, body, [data-testid="stAppViewContainer"], .stMarkdown, button, input, textarea, select {
  font-family: 'Pretendard', -apple-system, 'Malgun Gothic', sans-serif !important; }
[data-testid="stAppViewContainer"] { background: #F5F8FF; }
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] { visibility: hidden; }
.block-container { max-width: 1080px; padding-top: 1.4rem; padding-bottom: 4rem; }
h1, h2, h3 { color: #0F172A; letter-spacing: -0.02em; }
.stButton > button { border-radius: 12px; font-weight: 600; padding: .55rem 1rem; border: 1px solid #D6E2FB; }
.stButton > button[kind="primary"] { box-shadow: 0 4px 14px rgba(37, 99, 235, .25); }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 18px !important; border-color: #E3EAF8 !important;
  background: #FFFFFF; }
[data-testid="stFileUploaderDropzone"] { border: 2px dashed #93C5FD; background: #F8FBFF; border-radius: 16px; }
[data-testid="stExpander"] details { border-radius: 14px; border-color: #E3EAF8; background: #fff; }

.mt-brand { font-size: 22px; font-weight: 800; color: #1E3A8A; padding-top: 6px; white-space: nowrap; }
.mt-brand b { color: #2563EB; }
.mt-pill { display: inline-block; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px;
  background: #EAF1FF; color: #1D4ED8; margin-left: 6px; vertical-align: middle; }
.mt-hero { background: linear-gradient(135deg, #1E40AF 0%, #2563EB 55%, #3B82F6 100%); color: #fff;
  border-radius: 24px; padding: 38px 40px; margin: 8px 0 22px; position: relative; overflow: hidden; }
.mt-hero:after { content: ""; position: absolute; right: -60px; top: -60px; width: 260px; height: 260px;
  border-radius: 50%; background: rgba(255,255,255,.08); }
.mt-hero h1 { color: #fff; font-size: 32px; line-height: 1.3; margin: 0 0 10px; font-weight: 800; }
.mt-hero p { color: #DBEAFE; font-size: 16px; margin: 0; }
.mt-card { background: #fff; border: 1px solid #E3EAF8; border-radius: 18px; padding: 20px 22px; min-height: 150px; margin-bottom: 10px; }
.mt-card .icon { font-size: 26px; }
.mt-card .title { font-size: 17px; font-weight: 700; color: #0F172A; margin: 8px 0 4px; }
.mt-card .desc { font-size: 14px; color: #64748B; line-height: 1.55; }
.mt-stat { background: #fff; border: 1px solid #E3EAF8; border-radius: 18px; padding: 16px 20px; }
.mt-stat .label { font-size: 13px; color: #64748B; }
.mt-stat .value { font-size: 24px; font-weight: 800; color: #0F172A; margin-top: 2px; }
.mt-stat .sub { font-size: 12.5px; color: #2563EB; margin-top: 2px; }
.mt-stat.blue { background: #2563EB; border-color: #2563EB; }
.mt-stat.blue .label, .mt-stat.blue .sub { color: #DBEAFE; }
.mt-stat.blue .value { color: #fff; }
.mt-section { font-size: 20px; font-weight: 800; color: #0F172A; margin: 26px 0 10px; }
.mt-muted { color: #64748B; font-size: 14px; }
.mt-steps { display: flex; gap: 8px; margin: 6px 0 18px; }
.mt-step { flex: 1; display: flex; align-items: center; gap: 10px; background: #fff; border: 1px solid #E3EAF8;
  border-radius: 14px; padding: 10px 14px; font-size: 14px; color: #94A3B8; font-weight: 600; }
.mt-step .num { width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; background: #EEF2F7; color: #94A3B8; font-size: 13px; flex: none; }
.mt-step.done { color: #1D4ED8; } .mt-step.done .num { background: #DBEAFE; color: #1D4ED8; }
.mt-step.now { color: #fff; background: #2563EB; border-color: #2563EB; }
.mt-step.now .num { background: #fff; color: #2563EB; }
.mt-rec-title { font-size: 16.5px; font-weight: 700; color: #0F172A; }
.mt-chip { display: inline-block; font-size: 12px; padding: 2px 9px; border-radius: 999px; background: #EAF1FF;
  color: #1D4ED8; margin: 4px 4px 0 0; font-weight: 600; }
.mt-chip.gray { background: #F1F5F9; color: #475569; }
.mt-chip.warn { background: #FEF3C7; color: #92400E; }
.mt-chip.open { background: #DCFCE7; color: #166534; }
.mt-faq-cat { font-size: 13px; font-weight: 700; color: #2563EB; margin: 14px 0 6px; }
.mt-amount { text-align: right; font-size: 20px; font-weight: 800; color: #0F172A; }
.mt-amount small { display: block; font-size: 12.5px; font-weight: 500; color: #64748B; }
.mt-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.mt-table th { text-align: left; color: #64748B; font-weight: 600; padding: 8px 10px; border-bottom: 1px solid #E3EAF8; }
.mt-table td { padding: 9px 10px; border-bottom: 1px solid #F1F5F9; color: #0F172A; }
.mt-table td.num, .mt-table th.num { text-align: right; }
.mt-note { background: #EAF1FF; border-radius: 14px; padding: 14px 18px; color: #1E3A8A; font-size: 14px; line-height: 1.6; }
.mt-footer { margin-top: 40px; padding-top: 18px; border-top: 1px solid #E3EAF8; color: #94A3B8; font-size: 12.5px; }
@media (max-width: 640px) { .mt-hero { padding: 28px 22px; } .mt-hero h1 { font-size: 24px; }
  .mt-steps { flex-wrap: wrap; } .mt-step { flex: 1 1 45%; } }
</style>
"""

PAGES = [("home", "홈"), ("analyze", "영수증 분석"), ("records", "내 진료비 기록"),
         ("benefits", "혜택 찾기"), ("pharmacy", "약국 찾기"), ("faq", "자주 묻는 질문")]
STEPS = ["사진 올리기", "개인정보 가리기", "확인하기", "분석 결과"]


def esc(s):
    return html_lib.escape(str(s or ""))


def render_app():
    import streamlit as st

    st.set_page_config(page_title="메디행정톡", page_icon="🏥", layout="wide")
    ss = st.session_state
    defaults = {"page": "home", "step": 1, "up_bytes": None, "file_key": None, "final_boxes": [],
                "manual_boxes": {}, "result": None, "uploader_nonce": 0, "benefit_result": None,
                "chat": [], "include_archived": True, "auto_found": {}}
    for k, v in defaults.items():
        ss.setdefault(k, v)

    # ── 저장소 연결 ──
    if STORAGE == "session":
        if "db" not in ss:
            ss.db = open_db(":memory:")
        conn = ss.db
    else:
        conn = open_db()

    # ── 공통 도우미 ──
    def html(s):
        st.markdown(s, unsafe_allow_html=True)

    def wide(fn, *args, **kwargs):
        """Streamlit 버전에 따라 '가로로 꽉 채우기' 옵션 이름이 달라서 둘 다 시도"""
        try:
            return fn(*args, width="stretch", **kwargs)
        except TypeError:
            return fn(*args, use_container_width=True, **kwargs)

    def go(page, **extra):
        ss.page = page
        for k, v in extra.items():
            ss[k] = v

    def reset_wizard():
        ss.step, ss.up_bytes, ss.file_key, ss.final_boxes, ss.result = 1, None, None, [], None
        ss.uploader_nonce += 1

    def stat(col, label, value, sub="", blue=False):
        col.markdown(f'<div class="mt-stat{" blue" if blue else ""}"><div class="label">{esc(label)}</div>'
                     f'<div class="value">{esc(value)}</div><div class="sub">{esc(sub)}</div></div>',
                     unsafe_allow_html=True)

    def items_table(items):
        rows = "".join(
            f"<tr><td>{esc(i.get('name'))}</td><td class='num'>{won(i.get('covered_self'))}</td>"
            f"<td class='num'>{won(i.get('covered_insurer'))}</td><td class='num'>{won(i.get('non_covered'))}</td></tr>"
            for i in items if any(_int(i.get(k)) for k in ("covered_self", "covered_insurer", "full_self", "non_covered")))
        return ("<table class='mt-table'><tr><th>항목</th><th class='num'>내가 낸 돈(급여)</th>"
                "<th class='num'>공단이 낸 돈</th><th class='num'>비급여</th></tr>" + rows + "</table>")

    @st.cache_resource(show_spinner=False)
    def get_reader():  # 글자 인식 모델은 한 번만 불러와서 재사용
        import easyocr
        return easyocr.Reader(["ko", "en"], gpu=False, verbose=False)  # verbose=False: IDLE 창에 진행 막대를 찍지 않음

    @st.cache_data(show_spinner=False)
    def detect_cached(jpeg_bytes, backend):  # 같은 사진은 다시 인식하지 않음
        img = load_image(jpeg_bytes)
        if backend == "tesseract":
            return detect_sensitive_tesseract(img)
        return detect_sensitive(img, get_reader())

    html(CSS)

    # ── 상단 메뉴 ──
    try:
        nav = st.columns([2.1, 0.7, 1.1, 1.3, 1.0, 1.0, 1.1], vertical_alignment="center")
    except TypeError:
        nav = st.columns([2.1, 0.7, 1.1, 1.3, 1.0, 1.0, 1.1])
    pill = '<span class="mt-pill">체험 모드</span>' if use_demo_llm() else ""
    nav[0].markdown(f'<div class="mt-brand">🏥 메디<b>행정톡</b>{pill}</div>', unsafe_allow_html=True)
    for col, (key, label) in zip(nav[1:], PAGES):
        with col:
            wide(st.button, label, key=f"nav_{key}", type="primary" if ss.page == key else "secondary",
                 on_click=go, args=(key,))

    records_all = load_records(conn, include_archived=True)
    active = records_all[records_all["archived"] == 0] if not records_all.empty else records_all

    # ════════════════ 홈 ════════════════
    if ss.page == "home":
        html('<div class="mt-hero"><h1>진료비 영수증,<br>이제 쉽게 읽어요</h1>'
             '<p>영수증 사진 한 장이면 내가 낸 돈과 공단이 낸 돈을 나눠 보여주고,<br>'
             '받을 수 있는 공공 보건 혜택과 신청 방법까지 알려드려요.</p></div>')
        cards = [("📸", "영수증 분석", "사진을 올리면 개인정보는 먼저 가리고, 항목별 금액을 쉬운 말로 풀어드려요.",
                  "analyze", "영수증 분석 시작"),
                 ("📊", "내 진료비 기록", "지금까지 저장한 영수증을 병원별·월별로 모아서 한눈에 보여드려요.",
                  "records", "기록 보러 가기"),
                 ("🎁", "공공 보건 혜택", "지역·나이·검진 결과에 맞는 의료비 지원과 보건소 사업을 찾아드려요.",
                  "benefits", "혜택 찾기"),
                 ("💊", "근처 약국", "내 위치나 지역으로 지금 문 연 약국과 운영시간을 지도에서 보여드려요.",
                  "pharmacy", "약국 찾기")]
        cols = st.columns(4)
        for col, (icon, title, desc, page, btn) in zip(cols, cards):
            with col:
                html(f'<div class="mt-card"><div class="icon">{icon}</div><div class="title">{title}</div>'
                     f'<div class="desc">{desc}</div></div>')
                wide(st.button, btn, key=f"home_{page}", type="primary" if page == "analyze" else "secondary",
                     on_click=go, args=(page,))

        html('<div class="mt-section">올해 내 진료비</div>')
        year = str(dt.date.today().year)
        this_year = records_all[records_all["visit_date"].str.startswith(year)] if not records_all.empty else records_all
        c = st.columns(4)
        if this_year.empty:
            stat(c[0], "총 진료비", "0원", "아직 기록이 없어요", blue=True)
            stat(c[1], "내가 낸 돈", "0원")
            stat(c[2], "공단이 낸 돈", "0원")
            stat(c[3], "병원 방문", "0회")
        else:
            stat(c[0], "총 진료비", won(this_year["total_cost"].sum()), f"{year}년 기준", blue=True)
            stat(c[1], "내가 낸 돈", won(this_year["patient_pay"].sum()),
                 f"비급여 {won(this_year['non_covered'].sum())} 포함")
            stat(c[2], "공단이 낸 돈", won(this_year["insurer_pay"].sum()), "건강보험이 대신 냈어요")
            stat(c[3], "병원 방문", f"{len(this_year)}회", f"병원 {this_year['hospital'].nunique()}곳")

        html('<div class="mt-section">최근 기록</div>')
        if active.empty:
            with st.container(border=True):
                html('<div class="mt-muted">아직 저장된 영수증이 없어요. 첫 영수증을 분석해 보세요.</div>')
        else:
            for _, r in active.head(3).iterrows():
                with st.container(border=True):
                    a, b = st.columns([3, 1])
                    a.markdown(f'<div class="mt-rec-title">{esc(r.hospital)}</div>'
                               f'<span class="mt-chip">{esc(r.visit_date)}</span>'
                               f'<span class="mt-chip gray">{esc(r.department or r.patient_type or "진료")}</span>',
                               unsafe_allow_html=True)
                    b.markdown(f'<div class="mt-amount">{won(r.patient_pay)}<small>내가 낸 돈</small></div>',
                               unsafe_allow_html=True)
            wide(st.button, "전체 기록 보기 →", key="home_all", on_click=go, args=("records",))

    # ════════════════ 영수증 분석 (4단계) ════════════════
    elif ss.page == "analyze":
        html('<div class="mt-section" style="margin-top:14px">영수증 분석</div>')
        steps_html = "".join(
            f'<div class="mt-step {"now" if i == ss.step else "done" if i < ss.step else ""}">'
            f'<span class="num">{"✓" if i < ss.step else i}</span>{name}</div>'
            for i, name in enumerate(STEPS, 1))
        html(f'<div class="mt-steps">{steps_html}</div>')

        # ── 1단계: 사진 올리기 ──
        if ss.step == 1:
            left, right = st.columns([3, 2])
            with left:
                with st.container(border=True):
                    st.markdown("#### 영수증 사진을 올려주세요")
                    up = st.file_uploader("진료비 계산서·영수증, 진단서 사진 (jpg, png)", type=["jpg", "jpeg", "png"],
                                          key=f"uploader_{ss.uploader_nonce}")
                    if up:
                        wide(st.image, up.getvalue())
            with right:
                html('<div class="mt-card"><div class="title">📌 잘 찍는 방법</div><div class="desc">'
                     '• 영수증 전체가 화면에 들어오게<br>• 그림자·빛 반사 없이 밝은 곳에서<br>'
                     '• 글자가 흐리지 않게 초점 맞추기<br><br>'
                     '🔒 다음 단계에서 이름·주민번호·연락처를 <b>내 PC에서 먼저 가린 뒤</b> 분석해요. '
                     '사진은 저장하지 않아요.</div></div>')
            st.write("")
            b1, b2 = st.columns([1, 1])
            if use_demo_llm():
                if wide(b1.button, "체험용 예시로 결과 보기", key="demo_result"):
                    receipt = DEMO_RECEIPT
                    analysis = analyze_receipt(receipt)
                    text = explain_receipt(receipt, analysis)
                    rid, moved = save_record(conn, receipt, analysis, text)
                    ss.result = {"receipt": receipt, "analysis": analysis, "text": text, "id": rid, "moved": moved}
                    ss.step = 4
                    st.rerun()
            if wide(b2.button, "다음: 개인정보 가리기 →", key="to_step2", type="primary", disabled=up is None):
                raw = up.getvalue()
                ss.up_bytes = to_jpeg(load_image(raw))
                ss.file_key = hashlib.md5(raw).hexdigest()[:12]
                ss.step = 2
                st.rerun()

        # ── 2단계: 개인정보 가리기 ──
        elif ss.step == 2:
            img = load_image(ss.up_bytes)
            boxes = []
            left, right = st.columns([1, 1])
            with left:
                with st.container(border=True):
                    st.markdown("#### ① 자동으로 찾아 가리기")
                    backend = ocr_backend()
                    if backend:
                        found = ss.auto_found.get(ss.file_key)  # None = 아직 안 찾아봄
                        # 모델이 준비돼 있으면 2단계에 들어오자마자 자동으로 찾음
                        auto_start = backend == "tesseract" or easyocr_models_ready()
                        if found is None and not auto_start:
                            st.caption("처음 한 번은 인식 모델을 내려받느라 몇 분 걸릴 수 있어요(진행 상황은 IDLE 창에 보여요). "
                                       "기다리기 싫으면 아래 ② 직접 가리기만 써도 돼요.")
                        if found is None and (auto_start or wide(st.button, "🔍 자동으로 찾기", key="auto_find",
                                                                 type="primary")):
                            with st.spinner("이름·주민등록번호·연락처·주소를 찾아서 가리는 중…"):
                                try:
                                    ss.auto_found[ss.file_key] = detect_cached(ss.up_bytes, backend)
                                except Exception as e:
                                    ss.auto_found[ss.file_key] = []
                                    ss.auto_error = str(e)
                            st.rerun()
                        elif found:
                            st.success(f"개인정보 {len(found)}곳을 자동으로 가렸어요. 체크를 풀면 그 부분은 가리지 않아요.",
                                       icon="🔒")
                            for i, f in enumerate(found):
                                if st.checkbox(f"{f['reason']}  ·  {f['hint']}", value=True,
                                               key=f"auto_{ss.file_key}_{i}"):
                                    boxes.append(f["box"])
                        elif found is not None:
                            if ss.get("auto_error"):
                                st.error(f"자동 가림 중 오류가 났어요: {ss.pop('auto_error')}")
                            st.warning("자동으로 찾은 개인정보가 없어요. 아래 ② 직접 가리기로 가려 주세요.")
                    elif not ALLOW_OCR_INSTALL:
                        st.info("자동 가림 기능을 불러오지 못했어요. 아래 ② 직접 가리기로 가려 주세요.")
                    else:
                        st.info("자동 가림 기능을 처음 한 번 설치해야 해요 (5~10분). 설치 전에도 아래에서 직접 가릴 수 있어요.")
                        if st.button("자동 가림 기능 설치하기", key="install_ocr"):
                            with st.spinner("설치 중이에요. 창을 닫지 마세요…"):
                                ok, log = install_easyocr()
                            if ok:
                                st.rerun()
                            st.error("설치에 실패했어요. 아래 내용을 복사해서 물어보세요.")
                            st.code(log)
                with st.container(border=True):
                    st.markdown("#### ② 놓친 곳 직접 가리기")
                    manual = ss.manual_boxes.setdefault(ss.file_key, [])
                    pending = None
                    auto_ok = bool(ss.auto_found.get(ss.file_key))
                    if st.toggle("가릴 영역 직접 지정하기", value=not auto_ok, key=f"manual_on_{ss.file_key}"):
                        st.caption("슬라이더로 빨간 테두리를 맞춘 뒤 [이 영역 가리기]를 누르세요.")
                        c1, c2 = st.columns(2)
                        lx = c1.slider("왼쪽 위치 (%)", 0, 100, 0, key="m_left")
                        ty = c1.slider("위쪽 위치 (%)", 0, 100, 0, key="m_top")
                        w = c2.slider("너비 (%)", 1, 100, 30, key="m_w")
                        h = c2.slider("높이 (%)", 1, 100, 8, key="m_h")
                        pending = [int(img.width * lx / 100), int(img.height * ty / 100),
                                   int(img.width * min(lx + w, 100) / 100), int(img.height * min(ty + h, 100) / 100)]
                        if wide(st.button, "이 영역 가리기", key="add_manual"):
                            manual.append(pending)
                            st.rerun()
                    else:
                        st.caption("자동으로 놓친 곳이 있으면 켜서 직접 가릴 수 있어요.")
                    if manual and wide(st.button, f"직접 가린 곳 지우기 ({len(manual)})", key="clear_manual"):
                        manual.clear()
                        st.rerun()
                    boxes += manual
            with right:
                preview = apply_masks(img, boxes)
                if pending:
                    ImageDraw.Draw(preview).rectangle(pending, outline="red", width=max(img.width // 250, 3))
                with st.container(border=True):
                    st.markdown(f"#### 미리보기 · 가린 곳 {len(boxes)}개")
                    wide(st.image, preview, caption="빨간 테두리 = 지금 지정 중인 영역" if pending
                         else "검은 상자 = 가린 곳")
            b1, _, b2 = st.columns([1, 1, 1])
            if wide(b1.button, "← 사진 다시 올리기", key="back_1"):
                reset_wizard()
                st.rerun()
            if wide(b2.button, "다음: 확인하기 →", key="to_step3", type="primary"):
                ss.final_boxes = boxes
                ss.step = 3
                st.rerun()

        # ── 3단계: 확인하기 ──
        elif ss.step == 3:
            masked = apply_masks(load_image(ss.up_bytes), ss.final_boxes)
            left, right = st.columns([3, 2])
            with left:
                with st.container(border=True):
                    wide(st.image, masked, caption=f"AI로 보낼 이미지 · 가린 곳 {len(ss.final_boxes)}개")
            with right:
                html('<div class="mt-card"><div class="title">🔒 보내기 전에 확인해 주세요</div><div class="desc">'
                     '왼쪽 이미지<b>만</b> 분석에 사용돼요.<br>원본 사진은 어디에도 저장되지 않아요.<br><br>'
                     '• 이름이 가려졌나요?<br>• 주민등록번호·연락처·주소가 가려졌나요?<br>'
                     '• 금액과 항목 이름은 보이나요?</div></div>')
                st.write("")
                ok = st.checkbox("확인했어요. 이 이미지로 분석할게요.", key="confirm_send")
                engine = "claude"
                if CLOVA_OCR_URL and CLOVA_OCR_SECRET:
                    engine = st.radio("글자 인식 방식", ["claude", "clova"], horizontal=True,
                                      format_func=lambda x: {"claude": "Claude", "clova": "CLOVA OCR"}[x])
                if wide(st.button, "분석 시작", key="run_analysis", type="primary", disabled=not ok):
                    done = False
                    with st.spinner("영수증을 읽고 쉬운 말로 정리하는 중…"):
                        try:
                            fn = ocr_with_clova if engine == "clova" else ocr_with_claude
                            receipt = scrub(fn(to_jpeg(masked), "image/jpeg"))
                            analysis = analyze_receipt(receipt)
                            text = scrub(explain_receipt(receipt, analysis))
                            rid, moved = save_record(conn, receipt, analysis, text)
                            ss.result = {"receipt": receipt, "analysis": analysis, "text": text,
                                         "id": rid, "moved": moved}
                            ss.up_bytes = None  # 분석이 끝나면 사진은 메모리에서도 지움
                            ss.step = 4
                            done = True
                        except Exception as e:
                            st.error(f"분석 중 오류가 났어요: {e}")
                    if done:
                        st.rerun()
                if wide(st.button, "← 가림 다시 하기", key="back_2"):
                    ss.step = 2
                    st.rerun()

        # ── 4단계: 결과 ──
        elif ss.step == 4 and ss.result:
            res = ss.result
            r, a = res["receipt"], res["analysis"]
            msg = "분석이 끝났어요. 내 진료비 기록에 저장했어요."
            if res.get("moved"):
                msg += f" (최근 기록이 {MAX_ACTIVE_RECORDS}건을 넘어서 가장 오래된 {res['moved']}건은 보관함으로 옮겼어요)"
            st.success(msg, icon="✅")
            with st.container(border=True):
                html(f'<div class="mt-rec-title" style="font-size:20px">{esc(r.get("hospital"))}</div>'
                     f'<span class="mt-chip">{esc(r.get("visit_date"))}</span>'
                     f'<span class="mt-chip gray">{esc(r.get("department") or r.get("patient_type") or "진료")}</span>'
                     + ('<span class="mt-chip warn">비급여 비중 높음</span>' if a["flag_non_covered_heavy"] else ""))
            c = st.columns(4)
            stat(c[0], "총 진료비", won(a["total_cost"]), "", blue=True)
            stat(c[1], "내가 낸 돈", won(a["patient_pay"]), f"비급여 {a['non_covered_ratio']}%")
            stat(c[2], "공단이 낸 돈", won(a["insurer_pay"]), f"총 진료비의 {a['insurer_ratio']}%")
            stat(c[3], "비급여", won(a["non_covered"]), "건강보험이 안 되는 항목")
            left, right = st.columns([1, 1])
            with left:
                with st.container(border=True):
                    st.markdown("#### 항목별 금액")
                    html(items_table(r.get("items") or []))
            with right:
                with st.container(border=True):
                    st.markdown("#### 쉽게 풀어보면")
                    st.markdown(res["text"])
            b1, b2, b3 = st.columns(3)
            wide(b1.button, "📊 내 진료비 기록 보기", key="res_records", on_click=go, args=("records",))
            if wide(b2.button, "🎁 이 진료로 받을 수 있는 혜택", key="res_benefit", type="primary"):
                ss.page = "benefits"
                st.rerun()
            if wide(b3.button, "📸 다른 영수증 분석", key="res_new"):
                reset_wizard()
                st.rerun()
        else:
            reset_wizard()
            st.rerun()

    # ════════════════ 내 진료비 기록 ════════════════
    elif ss.page == "records":
        html('<div class="mt-section" style="margin-top:14px">내 진료비 기록</div>')
        if records_all.empty:
            with st.container(border=True):
                html('<div style="text-align:center;padding:30px 0"><div style="font-size:40px">🧾</div>'
                     '<div class="mt-rec-title">아직 저장된 영수증이 없어요</div>'
                     '<div class="mt-muted">영수증을 분석하면 자동으로 이곳에 쌓여요.</div></div>')
                e1, e2 = st.columns(2)
                wide(e1.button, "영수증 분석하러 가기", key="rec_go", type="primary", on_click=go, args=("analyze",))
                if wide(e2.button, "예시 기록으로 둘러보기", key="rec_sample"):
                    add_sample_records(conn)
                    st.rerun()
        else:
            n_arch = int((records_all["archived"] == 1).sum())
            top = st.columns([3, 2])
            top[0].markdown(f'<div class="mt-muted">최근 기록 <b>{len(active)}</b>건 · 보관함 <b>{n_arch}</b>건 · '
                            f'최근 기록은 {MAX_ACTIVE_RECORDS}건까지 보여주고, 넘으면 오래된 것부터 보관함으로 옮겨요.</div>',
                            unsafe_allow_html=True)
            ss.include_archived = top[1].toggle("보관함 기록도 합계에 포함", value=ss.include_archived)
            df = records_all if ss.include_archived else active

            c = st.columns(4)
            stat(c[0], "총 진료비", won(df["total_cost"].sum()), f"{len(df)}건 · {df['visit_date'].min()} ~", blue=True)
            stat(c[1], "내가 낸 돈", won(df["patient_pay"].sum()))
            stat(c[2], "공단이 낸 돈", won(df["insurer_pay"].sum()))
            nc_ratio = round(df["non_covered"].sum() / max(df["patient_pay"].sum(), 1) * 100, 1)
            stat(c[3], "비급여", won(df["non_covered"].sum()), f"내가 낸 돈의 {nc_ratio}%")

            import altair as alt
            g1, g2 = st.columns([3, 2])
            with g1:
                with st.container(border=True):
                    st.markdown("#### 월별 내가 낸 돈")
                    m = df.groupby("month")[["self_covered", "non_covered"]].sum().reset_index()
                    long = m.melt("month", var_name="kind", value_name="amount")
                    long["구분"] = long["kind"].map({"self_covered": "급여 본인부담", "non_covered": "비급여"})
                    chart = alt.Chart(long).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
                        x=alt.X("month:N", title=None, axis=alt.Axis(labelAngle=0)),
                        y=alt.Y("amount:Q", title=None, axis=alt.Axis(format=",d")),
                        color=alt.Color("구분:N", scale=alt.Scale(domain=["급여 본인부담", "비급여"],
                                                                range=[BLUE, BLUE_LIGHT]),
                                        legend=alt.Legend(orient="top", title=None)),
                        tooltip=[alt.Tooltip("month:N", title="월"), alt.Tooltip("구분:N"),
                                 alt.Tooltip("amount:Q", title="금액(원)", format=",d")],
                    ).properties(height=280)
                    wide(st.altair_chart, chart)
            with g2:
                with st.container(border=True):
                    st.markdown("#### 병원별 내가 낸 돈")
                    hosp = (df.groupby("hospital").agg(visits=("id", "count"), pay=("patient_pay", "sum"))
                            .reset_index().sort_values("pay", ascending=False))
                    bars = alt.Chart(hosp).mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5,
                                                    color=BLUE).encode(
                        y=alt.Y("hospital:N", sort="-x", title=None),
                        x=alt.X("pay:Q", title=None, axis=alt.Axis(format=",d")),
                        tooltip=[alt.Tooltip("hospital:N", title="병원"), alt.Tooltip("visits:Q", title="방문(회)"),
                                 alt.Tooltip("pay:Q", title="내가 낸 돈(원)", format=",d")],
                    ).properties(height=280)
                    wide(st.altair_chart, bars)

            year = str(dt.date.today().year)
            year_self = int(records_all.loc[records_all["visit_date"].str.startswith(year), "self_covered"].sum())
            html(f'<div class="mt-note">💡 <b>{year}년 급여 본인부담금 합계는 {won(year_self)}이에요.</b> '
                 '1년 동안 낸 급여 본인부담금이 소득 수준별 상한액을 넘으면 국민건강보험공단이 넘은 금액을 돌려줘요'
                 '(본인부담상한제). 비급여는 합산되지 않아요. 내 상한액은 국민건강보험공단(1577-1000)에서 확인하세요.'
                 '<br><span style="font-size:12.5px">※ 여기 저장한 영수증만 합산한 금액이에요.</span></div>')

            def record_card(r, archived=False):
                with st.container(border=True):
                    a_, b_ = st.columns([3, 1])
                    chips = (f'<span class="mt-chip">{esc(r.visit_date)}</span>'
                             f'<span class="mt-chip gray">{esc(r.department or r.patient_type or "진료")}</span>')
                    if r.patient_pay and r.non_covered / r.patient_pay >= 0.5:
                        chips += '<span class="mt-chip warn">비급여 비중 높음</span>'
                    if archived:
                        chips += '<span class="mt-chip gray">보관함</span>'
                    a_.markdown(f'<div class="mt-rec-title">{esc(r.hospital)}</div>{chips}', unsafe_allow_html=True)
                    b_.markdown(f'<div class="mt-amount">{won(r.patient_pay)}<small>총 {won(r.total_cost)} 중 내가 낸 돈'
                                f'</small></div>', unsafe_allow_html=True)
                    with st.expander("자세히 보기"):
                        html(items_table(r["items"]))
                        if r.diagnosis:
                            st.caption("진단: " + ", ".join(r.diagnosis))
                        if r.explanation:
                            st.markdown(r.explanation)
                        if st.button("이 기록 삭제", key=f"del_{r.id}"):
                            delete_record(conn, r.id)
                            st.rerun()

            html('<div class="mt-section">최근 기록</div>')
            for _, r in active.iterrows():
                record_card(r)

            archived_df = records_all[records_all["archived"] == 1]
            with st.expander(f"🗄️ 보관함 ({len(archived_df)}건) — 최근 {MAX_ACTIVE_RECORDS}건보다 오래된 기록"):
                if archived_df.empty:
                    st.caption("보관된 기록이 없어요.")
                for _, r in archived_df.iterrows():
                    record_card(r, archived=True)
                if not archived_df.empty and st.button("보관함 비우기", key="clear_archive"):
                    delete_all(conn, archived_only=True)
                    st.rerun()
            with st.expander("⚙️ 기록 관리"):
                st.caption("기록은 이 PC의 'mediadmin_records.db' 파일에만 저장돼요. 사진은 저장하지 않아요."
                           if STORAGE == "file" else "기록은 지금 브라우저 창에만 임시로 저장돼요.")
                if st.button("모든 기록 삭제", key="clear_all"):
                    delete_all(conn)
                    st.rerun()

    # ════════════════ 혜택 찾기 ════════════════
    elif ss.page == "benefits":
        html('<div class="mt-section" style="margin-top:14px">나에게 맞는 공공 보건 혜택</div>')
        last_dx = ", ".join(active.iloc[0]["diagnosis"]) if not active.empty else ""
        if ss.result and ss.result["receipt"].get("diagnosis"):
            last_dx = ", ".join(ss.result["receipt"]["diagnosis"])
        left, right = st.columns([2, 3])
        with left:
            with st.container(border=True):
                with st.form("profile", border=False):
                    st.markdown("#### 내 정보")
                    c1, c2 = st.columns(2)
                    sido = c1.selectbox("시·도", list(SIDO_CODES))
                    sigungu = c2.text_input("시·군·구", placeholder="예: 강남구")
                    age = st.number_input("나이", 0, 120, 55)
                    st.markdown("**건강검진 수치** (아는 것만)")
                    c3, c4 = st.columns(2)
                    sys_bp = c3.number_input("수축기 혈압", 0, 300, 0)
                    dia_bp = c4.number_input("이완기 혈압", 0, 200, 0)
                    glu = c3.number_input("공복혈당", 0, 600, 0)
                    chol = c4.number_input("총콜레스테롤", 0, 600, 0)
                    dx = st.text_input("진단명 / 상병코드", value=last_dx, help="최근 영수증의 진단이 자동으로 들어가요")
                    interest = st.multiselect("관심 분야", ["의료비", "검진", "만성질환", "암", "치매", "재활"])
                    high_cost = st.checkbox("최근 의료비 부담이 큰 편이에요")
                    submitted = st.form_submit_button("혜택 찾기", type="primary")
        if submitted:
            checkup = {k: v or None for k, v in {"systolic": sys_bp, "diastolic": dia_bp,
                                                 "fasting_glucose": glu, "total_cholesterol": chol}.items()}
            keywords = keywords_from_user(checkup, [d for d in dx.split(",") if d.strip()],
                                          [("고혈압" if i == "만성질환" else i) for i in interest])
            with st.spinner("공공데이터에서 혜택을 찾는 중…"):
                cands, errs = collect_candidates(sido, sigungu, keywords or ["의료비"])
                ranked = score_benefits(cands, keywords, age, high_cost)
                matched = ranked.to_dict("records") if not ranked.empty else []
                user = {"지역": f"{sido} {sigungu}", "나이": age, "키워드": keywords, "의료비부담": high_cost}
                summary = explain_benefits(user, matched)
            ss.benefit_result = {"keywords": keywords, "matched": matched, "summary": summary, "errors": errs}
        with right:
            br = ss.benefit_result
            if not br:
                html('<div class="mt-card"><div class="icon">🎁</div><div class="title">왼쪽에 정보를 입력해 주세요</div>'
                     '<div class="desc">행정안전부·한국사회보장정보원의 공공데이터에서 지역과 건강 상태에 맞는 '
                     '의료비 지원, 보건소 사업을 찾아드려요.</div></div>')
            else:
                for e in br["errors"]:
                    st.warning(f"일부 정보를 불러오지 못했어요: {e}")
                html("".join(f'<span class="mt-chip">#{esc(k)}</span>' for k in br["keywords"]))
                with st.container(border=True):
                    st.markdown("#### 한눈에 보기")
                    st.markdown(br["summary"])
                html(f'<div class="mt-section" style="font-size:17px">찾은 혜택 {len(br["matched"])}건</div>')
                for b in br["matched"][:8]:
                    with st.container(border=True):
                        html(f'<div class="mt-rec-title">{esc(b.get("name"))}</div>'
                             f'<span class="mt-chip gray">{esc(b.get("org"))}</span>'
                             + "".join(f'<span class="mt-chip">{esc(k)}</span>' for k in (b.get("matched") or [])))
                        st.markdown(f"{b.get('content') or ''}\n\n**신청** · {b.get('apply') or '담당 기관 문의'}")
                        if b.get("docs"):
                            st.caption("필요 서류: " + ", ".join(b["docs"]))
                        if b.get("url"):
                            st.markdown(f"[자세히 보기 ↗]({b['url']})")

    # ════════════════ 약국 찾기 ════════════════
    elif ss.page == "pharmacy":
        now = dt.datetime.now()
        html('<div class="mt-section" style="margin-top:14px">근처 약국 찾기</div>')
        html(f'<div class="mt-muted">오늘({WEEKDAY_NAMES[now.weekday()]}요일) 운영시간을 기준으로 '
             '지금 문 연 약국을 알려드려요. 국립중앙의료원 공공데이터를 사용해요.</div>')
        st.write("")
        mode = st.radio("찾는 방법", ["📍 내 위치로 찾기", "🗺️ 지역으로 찾기"], horizontal=True,
                        label_visibility="collapsed", key="pharm_mode")

        def run_search(fn, *args, **kwargs):
            with st.spinner("약국을 찾는 중…"):
                try:
                    ss.pharm_result = {"list": fn(*args, **kwargs), "error": None}
                except Exception as e:
                    ss.pharm_result = {"list": [], "error": str(e)}

        if mode.startswith("📍"):
            with st.container(border=True):
                st.markdown("#### 내 위치 주변 약국")
                st.caption("버튼을 누르면 브라우저가 위치 사용을 물어봐요. **허용**을 눌러 주세요. 위치는 저장하지 않아요.")
                try:
                    from streamlit_js_eval import get_geolocation
                    js_ok = True
                except ImportError:
                    js_ok = False
                if not js_ok:
                    st.info("위치 기능을 쓰려면 프로그램을 껐다가(Ctrl+F6) 다시 켜 주세요(F5). 필요한 부품이 자동으로 설치돼요. "
                            "지금은 '지역으로 찾기'를 쓸 수 있어요.")
                elif wide(st.button, "📍 내 위치로 약국 찾기", key="pharm_loc", type="primary"):
                    ss.want_loc, ss.my_loc = True, None
                if js_ok and ss.get("want_loc") and not ss.get("my_loc"):
                    loc = get_geolocation()
                    if loc and loc.get("coords"):
                        ss.my_loc = (loc["coords"]["latitude"], loc["coords"]["longitude"])
                        ss.want_loc = False
                        run_search(pharmacies_near, *ss.my_loc)
                        st.rerun()
                    elif loc and loc.get("error"):
                        ss.want_loc = False
                        st.warning("위치를 가져오지 못했어요. 브라우저 주소창 왼쪽 자물쇠 아이콘에서 위치 권한을 허용하거나, "
                                   "'지역으로 찾기'를 써 주세요.")
                    else:
                        st.caption("⏳ 위치를 확인하는 중이에요…")
        else:
            with st.container(border=True):
                with st.form("pharm_region", border=False):
                    st.markdown("#### 지역으로 찾기")
                    c1, c2, c3 = st.columns([1, 1, 1])
                    p_sido = c1.selectbox("시·도", list(SIDO_FULLNAMES))
                    p_sgg = c2.text_input("시·군·구", placeholder="예: 강남구")
                    p_name = c3.text_input("약국 이름 (선택)", placeholder="예: 온누리")
                    if st.form_submit_button("약국 찾기", type="primary"):
                        ss.my_loc = None
                        run_search(pharmacies_in_region, p_sido, p_sgg.strip(), p_name.strip())

        pr = ss.get("pharm_result")
        if pr:
            if pr["error"]:
                st.error(pr["error"], icon="⚠️")
            elif not pr["list"]:
                st.warning("조건에 맞는 약국을 찾지 못했어요. 시·군·구 이름을 확인하거나 범위를 넓혀 보세요.")
            else:
                items = pr["list"]
                for p in items:
                    p["open"] = is_open(p, now)
                    if p["dist_km"] is None and ss.get("my_loc") and p["lat"] is not None:
                        p["dist_km"] = distance_km(*ss.my_loc, p["lat"], p["lon"])
                n_open = sum(1 for p in items if p["open"])
                top = st.columns([3, 2])
                top[0].markdown(f'<div class="mt-muted">약국 <b>{len(items)}</b>곳 · 지금 영업 중 <b>{n_open}</b>곳 '
                                f'({now:%H:%M} 기준)</div>', unsafe_allow_html=True)
                only_open = top[1].toggle("지금 문 연 곳만 보기", value=True, key="pharm_only_open")
                shown = [p for p in items if p["open"] or not only_open]

                pts = [p for p in shown if p["lat"] is not None]
                if pts:
                    with st.container(border=True):
                        map_df = pd.DataFrame({"lat": [p["lat"] for p in pts], "lon": [p["lon"] for p in pts],
                                               "color": ["#2563EB" if p["open"] else "#94A3B8" for p in pts]})
                        if ss.get("my_loc"):
                            map_df.loc[len(map_df)] = [ss.my_loc[0], ss.my_loc[1], "#EF4444"]
                        try:
                            st.map(map_df, latitude="lat", longitude="lon", color="color", size=25, zoom=14)
                        except TypeError:
                            st.map(map_df[["lat", "lon"]])
                        st.caption("🔵 영업 중  ⚪ 영업 종료·정보 없음" + ("  🔴 내 위치" if ss.get("my_loc") else ""))

                if not shown:
                    st.info("지금 영업 중인 약국이 없어요. '지금 문 연 곳만 보기'를 끄면 전체 목록을 볼 수 있어요.")
                for p in shown[:30]:
                    with st.container(border=True):
                        a_, b_ = st.columns([3, 1])
                        if p["open"] is True:
                            chip = '<span class="mt-chip open">영업 중</span>'
                        elif p["open"] is False:
                            chip = '<span class="mt-chip gray">영업 종료</span>'
                        else:
                            chip = '<span class="mt-chip gray">운영시간 정보 없음</span>'
                        hours = (f'오늘 {p["start"][:2]}:{p["start"][2:]} ~ {p["end"][:2]}:{p["end"][2:]}'
                                 if p["start"] and p["end"] else "오늘 운영 정보 없음")
                        a_.markdown(f'<div class="mt-rec-title">{esc(p["name"])}</div>{chip}'
                                    f'<span class="mt-chip">{esc(hours)}</span>'
                                    f'<div class="mt-muted" style="margin-top:6px">{esc(p["addr"])}</div>',
                                    unsafe_allow_html=True)
                        dist = (f'{p["dist_km"] * 1000:.0f}m' if p["dist_km"] < 1 else f'{p["dist_km"]:.1f}km') \
                            if p["dist_km"] is not None else ""
                        tel = re.sub(r"[^\d-]", "", p["tel"] or "")
                        b_.markdown(f'<div class="mt-amount">{esc(dist)}<small>'
                                    + (f'<a href="tel:{tel}">📞 {esc(tel)}</a>' if tel else "") + '</small></div>',
                                    unsafe_allow_html=True)
                st.caption("※ 운영시간은 약국이 신고한 정보예요. 방문 전에 전화로 확인하면 가장 정확해요.")

    # ════════════════ 자주 묻는 질문 ════════════════
    elif ss.page == "faq":
        html('<div class="mt-section" style="margin-top:14px">자주 묻는 질문</div>')
        html('<div class="mt-muted">사람들이 가장 많이 궁금해하는 13가지를 모았어요. 질문을 누르면 답이 보여요.</div>')
        st.write("")
        context = {}
        if not active.empty:
            r0 = active.iloc[0]
            context["최근_영수증"] = {"병원": r0.hospital, "날짜": r0.visit_date, "총진료비": int(r0.total_cost),
                                 "내가낸돈": int(r0.patient_pay), "비급여": int(r0.non_covered)}
        if not records_all.empty:
            year_rows = records_all[records_all["visit_date"].str.startswith(str(dt.date.today().year))]
            context["올해_급여본인부담"] = int(year_rows["self_covered"].sum())
            context["올해_내가낸돈"] = int(year_rows["patient_pay"].sum())
        sel = ss.setdefault("faq_sel", FAQ[0]["id"])
        left, right = st.columns([2, 3])
        with left:
            for cat in FAQ_CATS:
                html(f'<div class="mt-faq-cat">{cat}</div>')
                for f in [x for x in FAQ if x["cat"] == cat]:
                    wide(st.button, f["q"], key=f"faq_{f['id']}", type="primary" if f["id"] == sel else "secondary",
                         on_click=go, args=("faq",), kwargs={"faq_sel": f["id"]})
        with right:
            cur = next(x for x in FAQ if x["id"] == sel)
            with st.container(border=True):
                html(f'<span class="mt-chip">{cur["cat"]}</span><div class="mt-rec-title" '
                     f'style="font-size:20px;margin:8px 0 6px">Q. {esc(cur["q"])}</div>')
                st.markdown(faq_text(sel, context))

    html('<div class="mt-footer">데이터 출처: 공공데이터포털(행정안전부, 한국사회보장정보원, 건강보험심사평가원) · '
         '메디행정톡은 정보 안내 서비스이며 의학적·법적 판단을 대신하지 않아요. '
         '실제 지원 여부와 금액은 담당 기관에서 확인하세요.</div>')


# ════════════════════════════════════════════════════════════
# 10. 실행 — F5를 누르면 여기서 앱을 켭니다
# ════════════════════════════════════════════════════════════
THEME_ARGS = ["--theme.base=light", "--theme.primaryColor=#2563EB", "--theme.backgroundColor=#F5F8FF",
              "--theme.secondaryBackgroundColor=#EAF1FF", "--theme.textColor=#0F172A",
              "--browser.gatherUsageStats=false", "--client.toolbarMode=minimal"]

if __name__ == "__main__":
    from streamlit import runtime

    if runtime.exists():          # Streamlit이 이 파일을 실행 중 → 화면 그리기
        render_app()
    else:                         # IDLE/Thonny에서 F5로 실행 → Streamlit 켜기
        # 처음 실행할 때 나오는 이메일 질문을 건너뛰도록 빈 설정 파일을 만들어 둠
        cred = Path.home() / ".streamlit" / "credentials.toml"
        if not cred.exists():
            cred.parent.mkdir(parents=True, exist_ok=True)
            cred.write_text('[general]\nemail = ""\n', encoding="utf-8")
        print("[안내] 앱을 켭니다. 브라우저가 안 열리면 http://localhost:8501 로 접속하세요.")
        from streamlit.web import cli as stcli
        sys.argv = ["streamlit", "run", str(Path(__file__).resolve()), *THEME_ARGS]
        sys.exit(stcli.main())
