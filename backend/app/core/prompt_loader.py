from pathlib import Path
from ..core.config import settings


class PromptLoader:
    def __init__(self, prompt_dir: Path | None = None):
        self._prompt_dir = prompt_dir or settings.prompt_dir
        self._cache: dict[str, str] = {}

    def load(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]
        file_path = self._prompt_dir / f"{name}.md"
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt 文件不存在: {file_path}")
        content = file_path.read_text(encoding="utf-8")
        self._cache[name] = content
        return content

    def load_with_context(self, name: str, **kwargs) -> str:
        template = self.load(name)
        for key, value in kwargs.items():
            template = template.replace(f"{{{key}}}", str(value))
        return template


prompt_loader = PromptLoader()
