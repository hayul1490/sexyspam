import os
import json
import time
from datetime import datetime
from flask import Flask, request, render_template, jsonify
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")

# ---------- 설정 ----------
KMA_SERVICE_KEY = os.getenv("wQI5iMcT1+S+KkSXnLn8rr9qNyoYNt6JFEwD44de3mMKMP0AYuVG9+ohcdOdLPAtZTkJWHNAjfd6S7ymMJdedQ==", "wQI5iMcT1+S+KkSXnLn8rr9qNyoYNt6JFEwD44de3mMKMP0AYuVG9+ohcdOdLPAtZTkJWHNAjfd6S7ymMJdedQ==")  # 공공데이터포털 발급키
USE_HF = os.getenv("USE_HF", "false").lower() == "true"  # HuggingFace 사용 여부
HF_MODEL = os.getenv("HF_MODEL", "gpt2")  # 예시
HF_TOKEN = os.getenv("HF_TOKEN", "")

SCHEDULE_FILE = "schedule.json"

# 미리 로컬 스케줄 파일 준비
if not os.path.exists(SCHEDULE_FILE):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)

# 간단한 도시 -> 기상청 격자(nx,ny) 매핑 (자주 쓰이는 도시)
CITY_GRID = {
    "서울": (60, 127),
    "서울시": (60, 127),
    "부산": (98, 76),
    "대구": (89, 90),
    "인천": (55, 124),
    "광주": (58, 74),
    "대전": (67, 100),
    "울산": (102, 84),
    "제주": (52, 38),
}

# ---------- 일정 관련 유틸 ----------
def load_schedules():
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_schedules(data):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_schedule(text, date_time=None):
    schedules = load_schedules()
    item = {
        "id": int(time.time() * 1000),
        "text": text,
        "datetime": date_time or datetime.now().isoformat()
    }
    schedules.append(item)
    save_schedules(schedules)
    return item

def query_schedules(query=None, date_only=None):
    schedules = load_schedules()
    res = []
    for s in schedules:
        if query and query.lower() not in s["text"].lower():
            continue
        if date_only:
            if not s["datetime"].startswith(date_only):
                continue
        res.append(s)
    return res

def delete_schedule(schedule_id):
    schedules = load_schedules()
    new = [s for s in schedules if s["id"] != schedule_id]
    save_schedules(new)
    return len(new) != len(schedules)

# ---------- 기상청(OpenAPI) 유틸 ----------
def get_vilage_forecast(nx, ny):
    """
    단기예보(getVilageFcst) 방식으로 간단하게 현재 시점에 가장 가까운 예보값을 가져옴.
    공공데이터 포털 서비스 키 필요.
    """
    # base_date와 base_time 결정: 기상청 가이드에 따름 (간단 구현)
    now = datetime.now()
    base_date = now.strftime("%Y%m%d")
    # 기상청 단기예보는 발표시간이 정해져 있으므로, 안전하게 최근 3시간 주기 중 한 타임을 고름.
    # (간단 구현: 0200, 0500, 0800, 1100, 1400, 1700, 2000, 2300)
    times = ["0200","0500","0800","1100","1400","1700","2000","2300"]
    # 현재 시간보다 이전이거나 같은 가장 최근 발표시간을 사용
    hhmm = now.strftime("%H%M")
    base_time = times[0]
    for t in times:
        if hhmm >= t:
            base_time = t

    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    params = {
        "serviceKey": KMA_SERVICE_KEY,
        "numOfRows": "2000",
        "pageNo": "1",
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": str(nx),
        "ny": str(ny),
    }

    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        return {"error": f"KMA API status {resp.status_code}"}
    try:
        j = resp.json()
    except Exception as e:
        return {"error": "invalid response from KMA", "exception": str(e)}
    # 응답 구조: response->body->items->item (배열)
    items = j.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    # 필요한 항목 추출 (T1H: 기온, PTY: 강수형태, SKY: 하늘상태)
    result = {}
    for it in items:
        cat = it.get("category")
        fcstTime = it.get("fcstTime")
        val = it.get("fcstValue")
        # 최신 시점(가장 가까운 시간)에 해당하는 값들만 추리려면 추가 로직 필요. 간단히 현재 시간 기준 같은 시간대값 우선 선택
        key = f"{cat}_{fcstTime}"
        result[key] = val
    # 간단 요약: 최신 시간(마지막 fcstTime)을 찾아 T1H, PTY, SKY 등 응답
    # (더 정교하게 하려면 가장 가까운 fcstTime을 계산)
    return {"raw": result, "base_date": base_date, "base_time": base_time}

# ---------- AI 응답 처리 (플레이스홀더 or HF) ----------
def ai_reply(user_message):
    """
    간단 플레이스홀더 챗봇. USE_HF=True 이고 HF_TOKEN 설정되어 있으면 Hugging Face Inference를 호출하도록 해두었음.
    (Hugging Face 사용 시 추가 환경변수 필요)
    """
    # 1) 매우 간단한 규칙 기반 확장: 일정 관련 문장 파악
    low = user_message.lower()
    # 일정 추가 의도 예시: "일정 추가", "내일 3시에 약속 추가", "오늘 시험 일정 추가해줘: 수학"
    if any(w in low for w in ["일정 추가", "추가해", "일정 등록", "스케줄 추가", "추가해줘"]):
        # 가능한 경우: "일정 추가: 수업 내일 3시"
        # 간단 파싱: 따옴표나 ":" 이후를 일정 텍스트로 저장
        text = user_message
        # try split by ':' or '추가'
        if ":" in user_message:
            _, tail = user_message.split(":",1)
            text = tail.strip()
        item = add_schedule(text)
        return f"일정이 저장되었어: \"{item['text']}\" (id: {item['id']})"
    if any(w in low for w in ["내 일정", "일정 보여줘", "오늘 일정", "내일 일정", "무슨 일정"]):
        # 날짜 검사
        date_str = None
        if "오늘" in low:
            date_str = datetime.now().strftime("%Y-%m-%d")
        elif "내일" in low:
            date_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        # query word
        q = None
        if "무슨" in low:
            q = ""
        items = query_schedules(query=q, date_only=(date_str.replace("-","") if date_str else None))
        if not items:
            return "지금 저장된 일정이 없어."
        lines = [f"- {s['datetime']}: {s['text']}" for s in items]
        return "저장된 일정:\n" + "\n".join(lines)
    # 2) 날씨 질문이면 간단 안내 (키워드 기반)
    if any(w in low for w in ["날씨", "기온", "비와", "비 와", "비오", "오늘 서울", "오늘"]):
        # 도시명 추출 (간단 매칭)
        city = None
        for c in CITY_GRID.keys():
            if c in user_message:
                city = c
                break
        if not city:
            city = "서울"
        nx, ny = CITY_GRID.get(city, CITY_GRID["서울"])
        kma = get_vilage_forecast(nx, ny)
        if "error" in kma:
            return "기상청 API 호출에 문제가 있어. 서비스 키와 네트워크를 확인해줘."
        # try produce simple human message: look for T1H and PTY of nearest time
        raw = kma.get("raw", {})
        # find latest fcstTime present
        times = sorted({k.split("_")[-1] for k in raw.keys()})
        if not times:
            return "기상청에서 데이터가 없어."
        nearest = times[-1]
        temp = raw.get(f"T1H_{nearest}") or raw.get(f"T1H_{nearest}", "알 수 없음")
        pty = raw.get(f"PTY_{nearest}", "0")
        sky = raw.get(f"SKY_{nearest}", None)
        # PTY 코드: 0(없음) 1(비) 2(비/눈) 3(눈) 4(소나기)
        pty_map = {"0":"강수 없음","1":"비","2":"비/눈","3":"눈","4":"소나기"}
        p_msg = pty_map.get(str(pty), "알 수 없음")
        return f"{city} 기준 {kma.get('base_date')} {kma.get('base_time')} 발표 (예보시각 {nearest}):\n기온: {temp}°C\n강수: {p_msg}"
    # 3) HuggingFace Inference (옵션)
    if USE_HF and HF_TOKEN:
        try:
            headers = {"Authorization": f"Bearer {HF_TOKEN}"}
            hf_url = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
            payload = {"inputs": user_message}
            r = requests.post(hf_url, headers=headers, json=payload, timeout=15)
            if r.status_code == 200:
                data = r.json()
                # HF 모델 형식 다양하므로 안전하게 문자열 합치기
                if isinstance(data, list):
                    text = data[0].get("generated_text") or str(data[0])
                elif isinstance(data, dict):
                    text = data.get("generated_text") or str(data)
                else:
                    text = str(data)
                return text
        except Exception as e:
            return f"HuggingFace 호출 중 오류: {e}"
    # 4) 기본 대답(플레이스홀더)
    return "응? 잘 모르겠어. 일정 추가/조회 또는 '오늘 서울 날씨'처럼 물어봐줘!"

# ---------- 라우트 ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json() or {}
    msg = body.get("message", "")
    if not msg:
        return jsonify({"error":"no message"}), 400
    reply = ai_reply(msg)
    return jsonify({"reply": reply})

@app.route("/api/schedules", methods=["GET"])
def api_get_schedules():
    return jsonify(load_schedules())

@app.route("/api/schedules", methods=["POST"])
def api_add_schedule():
    data = request.get_json() or {}
    text = data.get("text")
    dt = data.get("datetime")
    if not text:
        return jsonify({"error":"text required"}), 400
    item = add_schedule(text, dt)
    return jsonify(item), 201

@app.route("/api/schedules/<int:sch_id>", methods=["DELETE"])
def api_delete_schedule(sch_id):
    ok = delete_schedule(sch_id)
    return jsonify({"deleted": ok})

# ---------- 간단 헬스체크 ----------
@app.route("/health")
def health():
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
