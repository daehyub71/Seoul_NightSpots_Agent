import logging
import sys

def get_logger(name: str = "nightspot") -> logging.Logger:
    """
    INFO 레벨 기본 로거 반환
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

# 기본 로거 (모듈 단독 실행 시 테스트)
if __name__ == "__main__":
    log = get_logger()
    log.info("Logger initialized (INFO level)")
