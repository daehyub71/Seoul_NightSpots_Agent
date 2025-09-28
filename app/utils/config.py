import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class Settings:
    def __init__(self):
        # 서울시 Open API
        self.SEOUL_OPENAPI_KEY = os.getenv("SEOUL_OPENAPI_KEY") or "환경변수 없음"
        # 카카오맵 API
        self.KAKAO_API_KEY = os.getenv("KAKAO_API_KEY") or "환경변수 없음"
        # Azure OpenAI 관련 키들
        self.AOAI_ENDPOINT = os.getenv("AOAI_ENDPOINT") or "환경변수 없음"
        self.AOAI_API_KEY = os.getenv("AOAI_API_KEY") or "환경변수 없음"
        self.AOAI_DEPLOYMENT = os.getenv("AOAI_DEPLOYMENT") or "환경변수 없음"

    def as_dict(self):
        return {
            "SEOUL_OPENAPI_KEY": self.SEOUL_OPENAPI_KEY,
            "KAKAO_API_KEY": self.KAKAO_API_KEY,  # ✅ 추가됨
            "AOAI_ENDPOINT": self.AOAI_ENDPOINT,
            "AOAI_API_KEY": self.AOAI_API_KEY,
            "AOAI_DEPLOYMENT": self.AOAI_DEPLOYMENT,
        }

# 전역 settings 객체
settings = Settings()

if __name__ == "__main__":
    from logger import get_logger
    log = get_logger("config")
    log.info("환경 변수 로딩 결과:")
    for k, v in settings.as_dict().items():
        log.info(f"{k} = {v}")
