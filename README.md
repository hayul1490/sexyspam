# AI 콘솔 어시스턴트

간단한 Flask 기반 콘솔형 웹 챗봇.  
기능: 대화, 일정 저장/조회/삭제, 기상청 단기예보 연동(한국).

## 준비
1. 공공데이터포털(data.go.kr)에서 '기상청_단기예보 조회서비스' 또는 '동네예보' 오픈 API를 신청하여 Service Key 발급.
   - 발급된 키를 `KMA_SERVICE_KEY` 환경변수로 설정.
2. (선택) Hugging Face 모델 쓰려면 `USE_HF=true`, `HF_MODEL`(모델명), `HF_TOKEN`(토큰) 설정.

## 로컬 실행 (예)
```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
export KMA_SERVICE_KEY="발급받은키"
python app.py
# 브라우저에서 http://127.0.0.1:5000 접속
