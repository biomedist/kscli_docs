"""행정지도감사 메뉴 정의. 새 메뉴는 여기에 한 줄만 추가하면 카드가 생깁니다."""

MENU = [
    {"key": "meetings",   "title": "각종 회의실적",         "desc": "연도별 회의록과 개최 내역을 관리합니다.",        "endpoint": "meetings.list_view",  "color": "#c2410c", "icon": "📝"},
    {"key": "attendance", "title": "임원 회의 참석 현황",   "desc": "임원별 참석·불참 횟수를 자동 집계합니다.",        "endpoint": "meetings.attendance", "color": "#1d4ed8", "icon": "🙋"},
    {"key": "officers",   "title": "역대 임원·평의원 명부", "desc": "임원·평의원 명부와 역대 회장단을 목록으로 관리합니다.",              "endpoint": "officers.roster",     "color": "#047857", "icon": "👥"},
    {"key": "events",     "title": "교육·학술대회·워크숍",  "desc": "보수교육, 학술대회, 워크숍 개최 실적입니다.",      "endpoint": "events.list_view",    "color": "#b45309", "icon": "🎓"},
    {"key": "budget",     "title": "예산·결산 현황",        "desc": "수입·비용과 집행 비율을 표로 확인합니다.",        "endpoint": "finance.budget",      "color": "#7c3aed", "icon": "📊"},
    {"key": "accounts",   "title": "예금통장·카드 현황",    "desc": "보유 통장과 카드 자료를 보관합니다.",             "endpoint": "finance.accounts",    "color": "#0f766e", "icon": "💳"},
    {"key": "donations",  "title": "찬조금 내역",           "desc": "찬조금 수입과 사용 내역을 기록합니다.",           "endpoint": "finance.donations",   "color": "#be185d", "icon": "🤝"},
    {"key": "plans",      "title": "사업계획 및 실적",      "desc": "사업실적과 미진사업을 정리합니다.",               "endpoint": "plans.list_view",     "color": "#4d7c0f", "icon": "🎯"},
    {"key": "documents",  "title": "기타 서류",             "desc": "서류를 올리고 태그로 검색합니다.",                "endpoint": "documents.list_view", "color": "#334155", "icon": "📁"},
]


def get_menu(key):
    for item in MENU:
        if item["key"] == key:
            return item
    return None
