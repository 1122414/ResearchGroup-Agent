import logging
import sys
from datetime import datetime
from pathlib import Path

BACKEND_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
FRONTEND_LOG_DIR = BACKEND_LOG_DIR


class DailyDirectoryHandler(logging.FileHandler):
    def __init__(self, base_dir: Path, filename: str, mode: str = "a", encoding: str = "utf-8"):
        self.base_dir = base_dir
        self._filename = filename
        self._mode = mode
        self._encoding = encoding
        self._current_date = None
        self._current_path = None
        log_path = self._resolve_path()
        super().__init__(log_path, mode=mode, encoding=encoding)

    def _resolve_path(self) -> Path:
        now = datetime.now()
        date_folder = f"{now.month}.{now.day}"
        day_dir = self.base_dir / date_folder
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / self._filename

    def emit(self, record: logging.LogRecord) -> None:
        now = datetime.now()
        current_date = (now.month, now.day)
        if self._current_date != current_date:
            self._current_date = current_date
            new_path = self._resolve_path()
            if self._current_path != new_path:
                self._current_path = new_path
                self.close()
                self.baseFilename = str(new_path)
                self.stream = self._open()
        super().emit(record)


class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str, use_color: bool = False):
        super().__init__(fmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color:
            color = self.COLORS.get(record.levelname, "")
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


DEFAULT_FMT = "%(asctime)s | %(levelname)-8s | %(filename)s:%(funcName)s:%(lineno)d | %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    backend_handler = DailyDirectoryHandler(BACKEND_LOG_DIR, "backend.log")
    backend_handler.setLevel(level)
    backend_handler.setFormatter(logging.Formatter(DEFAULT_FMT, datefmt=DATE_FMT))
    root.addHandler(backend_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = ColoredFormatter(DEFAULT_FMT, use_color=sys.platform != "win32")
    console_handler.setFormatter(console_formatter)
    root.addHandler(console_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)

    root.info("Logging system initialized | backend_dir=%s | level=%s", BACKEND_LOG_DIR, log_level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


logger = get_logger("researchgroup")
