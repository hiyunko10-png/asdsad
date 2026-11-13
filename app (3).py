"""우리집 함께 — Streamlit 가족 집안일 보드.
실행: pip install -r requirements.txt && streamlit run app.py
GitHub에는 이 파일과 requirements.txt만 올리세요.
배포/데이터베이스 설정은 앱의 '설치·배포 안내'에서 확인할 수 있습니다.
"""
from __future__ import annotations

import copy
import hashlib
import re
import secrets
import uuid
from datetime import date, datetime, timezone

import requests
import streamlit as st

st.set_page_config(page_title="우리집 함께", page_icon="🏡", layout="wide")

SQL = """-- Supabase SQL Editor에서 한 번 실행하세요.
create table if not exists public.family_boards (
  id text primary key,
  payload jsonb not null,
  revision bigint not null default 0
);
alter table public.family_boards enable row level security;
-- 공개 접근 정책은 만들지 않습니다. 서버의 service_role 키로만 접근합니다.
revoke all on table public.family_boards from anon, authenticated;
grant select, insert, update on table public.family_boards to service_role;
"""


def config():
    try:
        return str(st.secrets.get("SUPABASE_URL", "")).strip(), str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return "", ""


def blank_board():
    return {"name": "우리 가족", "members": [], "tasks": []}


class Conflict(Exception):
    pass


class Store:
    def __init__(self, url, key, board_id):
        self.url = url.rstrip("/") + "/rest/v1/family_boards"
        self.headers = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
        self.board_id = board_id

    def request(self, method, **kwargs):
        try:
            response = requests.request(method, self.url, headers=self.headers, timeout=15, **kwargs)
        except requests.RequestException:
            raise RuntimeError("저장소 연결에 실패했습니다. 네트워크와 Supabase URL을 확인하세요.") from None
        if response.status_code == 409:
            raise Conflict("이미 만들어진 가족 공간입니다.")
        if not response.ok:
            raise RuntimeError(f"저장소 요청 실패 (HTTP {response.status_code}). Secrets, SQL 설정과 프로젝트 상태를 확인하세요.")
        return response.json() if response.content else []

    def load(self):
        rows = self.request("GET", params={"id": "eq." + self.board_id, "select": "payload,revision"})
        return (rows[0]["payload"], rows[0]["revision"]) if rows else (None, None)

    def create(self):
        self.request("POST", json={"id": self.board_id, "payload": blank_board(), "revision": 0})

    def save(self, board, revision):
        headers = dict(self.headers, Prefer="return=representation")
        try:
            result = requests.patch(self.url, headers=headers,
                params={"id": "eq." + self.board_id, "revision": "eq." + str(revision)},
                json={"payload": board, "revision": revision + 1}, timeout=15)
        except requests.RequestException:
            raise RuntimeError("저장 응답을 받지 못했습니다. 새로고침으로 저장 여부를 먼저 확인하세요.") from None
        if not result.ok:
            raise RuntimeError(f"저장에 실패했습니다 (HTTP {result.status_code}). 새로고침 후 확인하세요.")
        if not result.json():
            raise Conflict("다른 가족이 먼저 수정했습니다. 최신 내용을 불러온 뒤 다시 시도하세요.")


def board_key(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_token(token):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{24,128}", token))


def due_state(task, today):
    if task["done"]:
        return "완료"
    if not task.get("due"):
        return "예정"
    if task["due"] < today.isoformat():
        return "기한 지남"
    return "오늘까지" if task["due"] == today.isoformat() else "예정"


st.markdown("""<style>
.stApp {background-color: #f6f8fb;}
.block-container {max-width: 1120px; padding-top: 2rem;}
h1, h2, h3 {color: #19334b;}
[data-testid="stMetric"] {background: white; border: 1px solid #dce5ef; border-radius: 16px; padding: 16px;}
.stButton>button {border-radius: 10px; min-height: 44px;}
</style>""", unsafe_allow_html=True)

st.title("🏡 우리집 함께")
st.caption("집안일은 나누고, 함께하는 시간은 늘려요.")

with st.expander("📖 설치·배포 안내 / 가족 데이터 저장 설정"):
    st.markdown("""### 1. GitHub → Streamlit 배포
1. GitHub 저장소에 **app.py**, **requirements.txt** 두 파일을 올립니다.
2. Streamlit Community Cloud에서 해당 저장소를 선택하고 메인 파일을 `app.py`로 지정합니다.
3. 우선 설정 없이 배포하면 **체험 모드**로 실행됩니다. 체험 데이터는 접속 세션 안에서만 유지됩니다.

### 2. 가족끼리 공유하려면 Supabase 연결
1. Supabase 프로젝트를 만들고 SQL Editor에서 아래 SQL을 실행합니다.
2. 프로젝트 URL과 서버 전용 **service_role 키**를 확인합니다.
3. Streamlit 앱 관리 화면의 **Settings → Secrets**에 아래 형식으로 입력하고 앱을 재시작합니다.
4. '새 가족 만들기'에서 초대 코드를 만들고 가족에게 **앱 주소와 코드**를 전달합니다.

**중요:** service_role 키를 GitHub에 올리거나 가족에게 전달하지 마세요. Secrets에만 보관합니다.
공유 초대 코드를 아는 사람은 해당 가족의 모든 내용을 읽고 수정할 수 있습니다.
개인별 권한·본인 인증 기능은 없으므로 신뢰할 수 있는 가족끼리만 사용하고 민감한 정보는 입력하지 마세요.
""")
    st.code(SQL, language="sql")
    st.code('SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"\nSUPABASE_SERVICE_ROLE_KEY = "YOUR_SERVICE_ROLE_KEY"', language="toml")
    st.caption("로컬 실행: pip install -r requirements.txt → streamlit run app.py. 로컬 Secrets는 .streamlit/secrets.toml에 두고 Git에 커밋하지 마세요. 초대 코드는 분실 시 복구할 수 없으므로 안전하게 보관하세요.")

url, api_key = config()
cloud = bool(url and api_key)
if bool(url) != bool(api_key):
    st.error("Supabase URL과 service_role 키를 모두 설정해야 합니다.")
    st.stop()
if not cloud:
    st.warning("체험 모드 · 데이터는 현재 접속 세션에만 저장됩니다. 다른 기기와 공유되지 않으며 세션이 종료되면 사라질 수 있습니다. 실제 가족 사용은 위 안내에 따라 Supabase를 연결하세요.")

with st.sidebar:
    st.header("우리 가족 공간")
    if cloud:
        st.success("공유 저장소 연결 설정됨")
        if not st.session_state.get("family_token"):
            join, create = st.tabs(["가족 참여", "새 가족 만들기"])
            with join:
                with st.form("join"):
                    token = st.text_input("가족 초대 코드", type="password")
                    if st.form_submit_button("참여하기", use_container_width=True):
                        token = token.strip()
                        if not valid_token(token):
                            st.error("초대 코드 형식을 확인하세요.")
                        else:
                            try:
                                found, _ = Store(url, api_key, board_key(token)).load()
                                if found is None:
                                    st.error("일치하는 가족 공간이 없습니다. 코드를 확인하세요.")
                                else:
                                    st.session_state.family_token = token
                                    st.rerun()
                            except RuntimeError as exc:
                                st.error(str(exc))
            with create:
                st.caption("안전한 무작위 초대 코드를 생성합니다.")
                if st.button("새 가족 공간 만들기", use_container_width=True):
                    token = secrets.token_urlsafe(24)
                    try:
                        Store(url, api_key, board_key(token)).create()
                        st.session_state.family_token = token
                        st.rerun()
                    except (RuntimeError, Conflict) as exc:
                        st.error(str(exc))
        else:
            with st.expander("초대 코드 확인"):
                st.code(st.session_state.family_token, language=None)
                st.caption("신뢰하는 가족에게만 공유하세요. 개인별 로그인 대신 사용하는 비밀 코드입니다.")
            if st.button("가족 공간 나가기"):
                st.session_state.pop("family_token", None)
                st.rerun()
    else:
        st.caption("체험 모드에서는 새로 추가한 가족과 할 일을 자유롭게 테스트할 수 있어요.")

if cloud and not st.session_state.get("family_token"):
    st.info("왼쪽 메뉴에서 가족 공간을 만들거나 초대 코드로 참여하세요. 모바일에서는 상단 메뉴로 사이드바를 열 수 있습니다.")
    st.stop()

store = Store(url, api_key, board_key(st.session_state.family_token)) if cloud else None
try:
    if cloud:
        board, revision = store.load()
        if board is None:
            st.error("가족 공간을 찾을 수 없습니다. 나간 뒤 다시 참여하세요.")
            st.stop()
    else:
        if "demo_board" not in st.session_state:
            st.session_state.demo_board = blank_board()
        board = copy.deepcopy(st.session_state.demo_board)
        revision = 0
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()


def commit(updated):
    try:
        if cloud:
            store.save(updated, revision)
        else:
            st.session_state.demo_board = copy.deepcopy(updated)
        st.session_state.notice = "변경 사항을 저장했어요."
        st.rerun()
    except (RuntimeError, Conflict) as exc:
        st.error(str(exc))
        st.stop()


if st.session_state.get("notice"):
    st.success(st.session_state.pop("notice"))
with st.sidebar:
    st.divider()
    if st.button("↻ 최신 내용 불러오기", use_container_width=True):
        st.rerun()
    st.caption("다른 가족의 변경은 새로고침 시 반영됩니다. 동시 수정 충돌은 감지하여 덮어쓰지 않습니다.")
    st.caption("화면의 담당자를 바꾸는 것은 개인별 로그인이나 접근 제한이 아닙니다.")

# 한국 날짜를 사용해 서버 시간대 차이를 피합니다.
from zoneinfo import ZoneInfo

today = datetime.now(ZoneInfo("Asia/Seoul")).date()
tasks = board["tasks"]
members = board["members"]
st.subheader(board["name"])
remaining = [t for t in tasks if not t["done"]]
cols = st.columns(3)
cols[0].metric("남은 집안일", len(remaining))
cols[1].metric("오늘까지", sum(t.get("due") == today.isoformat() for t in remaining))
cols[2].metric("완료", len(tasks) - len(remaining))
if tasks:
    st.progress((len(tasks) - len(remaining)) / len(tasks), text="가족 전체 완료율")

list_tab, add_tab, settings_tab = st.tabs(["📋 할 일 목록", "➕ 할 일 추가", "👨‍👩‍👧 가족 관리"])
with add_tab:
    with st.form("add_task", clear_on_submit=True):
        title = st.text_input("어떤 일을 할까요?", max_chars=100, placeholder="예: 저녁 설거지")
        assignee = st.selectbox("담당자", ["미지정"] + members)
        priority = st.selectbox("중요도", ["보통", "높음", "낮음"])
        has_due = st.checkbox("마감일 지정", value=True)
        due = st.date_input("마감일 (지정을 해제하면 저장되지 않아요)", value=today)
        note = st.text_area("메모", max_chars=1000, placeholder="필요한 준비물이나 방법을 적어주세요.")
        submitted = st.form_submit_button("할 일 등록", type="primary", use_container_width=True)
    if submitted:
        if not title.strip():
            st.error("할 일 제목을 입력하세요.")
        elif len(tasks) >= 500:
            st.error("가족 공간당 500개까지 등록할 수 있습니다. 불필요한 완료 항목을 삭제하세요.")
        else:
            board["tasks"].append({"id": uuid.uuid4().hex, "title": title.strip(), "assignee": assignee,
                "priority": priority, "due": due.isoformat() if has_due else None, "note": note.strip(),
                "done": False, "created_at": datetime.now(timezone.utc).isoformat(), "completed_at": None})
            commit(board)

with list_tab:
    a, b = st.columns(2)
    who = a.selectbox("담당자 필터", ["전체", "미지정"] + members)
    status = b.selectbox("상태 필터", ["진행 중", "전체", "완료", "기한 지남", "오늘까지"])
    search = st.text_input("할 일 검색", placeholder="제목 또는 메모로 검색")
    visible = [t for t in tasks if (who == "전체" or t["assignee"] == who)
        and (status == "전체" or (status == "진행 중" and not t["done"])
             or (status == "완료" and t["done"]) or (status in ["기한 지남", "오늘까지"] and due_state(t, today) == status))
        and search.casefold() in (t["title"] + " " + t.get("note", "")).casefold()]
    visible.sort(key=lambda t: (t["done"], t.get("due") or "9999-12-31", {"높음": 0, "보통": 1, "낮음": 2}.get(t["priority"], 1)))
    if not visible:
        st.info("표시할 할 일이 없어요. 새 할 일을 등록하거나 필터를 바꿔보세요.")
    for task in visible:
        tid = task["id"]
        with st.container(border=True):
            st.markdown("**" + task["title"].replace("\n", " ") + "**")
            state = due_state(task, today)
            st.caption(f"{task['assignee']} · {task['priority']} · {task.get('due') or '마감일 없음'} · {state}")
            if task.get("note"):
                st.text(task["note"])
            if st.button("↩ 다시 할 일로" if task["done"] else "✓ 완료하기", key="toggle_" + tid):
                task["done"] = not task["done"]
                task["completed_at"] = datetime.now(timezone.utc).isoformat() if task["done"] else None
                commit(board)
            with st.expander("수정 / 삭제"):
                with st.form("edit_" + tid):
                    new_title = st.text_input("제목", value=task["title"], max_chars=100)
                    options = ["미지정"] + members
                    new_owner = st.selectbox("담당자", options, index=options.index(task["assignee"]) if task["assignee"] in options else 0)
                    priorities = ["보통", "높음", "낮음"]
                    new_priority = st.selectbox("중요도", priorities, index=priorities.index(task["priority"]))
                    new_has_due = st.checkbox("마감일 지정", value=bool(task.get("due")))
                    new_due = st.date_input("마감일", value=date.fromisoformat(task["due"]) if task.get("due") else today)
                    new_note = st.text_area("메모", value=task.get("note", ""), max_chars=1000)
                    save = st.form_submit_button("수정 저장")
                if save:
                    if not new_title.strip():
                        st.error("제목을 입력하세요.")
                    else:
                        task.update(title=new_title.strip(), assignee=new_owner, priority=new_priority,
                            due=new_due.isoformat() if new_has_due else None, note=new_note.strip())
                        commit(board)
                confirmed = st.checkbox("이 할 일을 영구 삭제합니다", key="confirm_" + tid)
                if st.button("할 일 삭제", key="delete_" + tid, disabled=not confirmed):
                    board["tasks"] = [t for t in tasks if t["id"] != tid]
                    commit(board)

with settings_tab:
    with st.form("family_name"):
        name = st.text_input("가족 공간 이름", value=board["name"], max_chars=40)
        if st.form_submit_button("이름 저장"):
            if name.strip():
                board["name"] = name.strip()
                commit(board)
            else:
                st.error("이름을 입력하세요.")
    with st.form("member_add", clear_on_submit=True):
        member = st.text_input("구성원 이름 또는 별명", max_chars=20)
        if st.form_submit_button("구성원 추가"):
            member = member.strip()
            if not member or member in ["전체", "미지정"]:
                st.error("다른 이름을 입력하세요. '전체', '미지정'은 사용할 수 없습니다.")
            elif member in members:
                st.error("이미 등록된 이름입니다.")
            elif len(members) >= 30:
                st.error("구성원은 30명까지 등록할 수 있습니다.")
            else:
                board["members"].append(member)
                commit(board)
    st.markdown("#### 구성원별 현재 업무")
    if not members:
        st.info("함께할 가족을 먼저 등록하세요.")
    for person in members:
        count = sum(t["assignee"] == person and not t["done"] for t in tasks)
        st.write(f"{person} · 남은 할 일 {count}개")
    if members:
        with st.expander("구성원 삭제"):
            removed = st.selectbox("삭제할 구성원", members)
            confirmed = st.checkbox("해당 구성원을 삭제하고 담당 업무를 '미지정'으로 변경합니다")
            if st.button("구성원 삭제", disabled=not confirmed):
                board["members"].remove(removed)
                for task in tasks:
                    if task["assignee"] == removed:
                        task["assignee"] = "미지정"
                commit(board)

st.caption("우리집 함께 · 마감일 기준: 한국 시간 · 자동 알림은 제공하지 않습니다.")
