# backend/app/core/ — Infrastructure Layer

## OVERVIEW
Backend infrastructure: configuration management, LLM provider abstraction, prompt loading, and logging. All services depend on this layer.

## STRUCTURE
```
core/
├── config.py            # pydantic-settings: 60+ config knobs, role-based model routing
├── llm_provider.py      # LLMProvider ABC + MockLLMProvider + OpenAICompatibleProvider
├── prompt_loader.py     # Markdown prompt files → cached strings with template substitution
├── logger.py            # Daily-rotating file handler + colored console output
└── logging_middleware.py # FastAPI request/response logging with X-Request-ID
```

## WHERE TO LOOK
| Component | File | Key Lines |
|-----------|------|-----------|
| Settings singleton | `config.py:12` | `class Settings(BaseSettings)` — `.env` auto-load, `@lru_cache`, case-insensitive |
| LLM factory | `llm_provider.py:336` | `create_llm_provider()` — mock_mode branch |
| Mock responses | `llm_provider.py:26` | `MockLLMProvider` — role-based deterministic output |
| OpenAI client | `llm_provider.py:230` | `OpenAICompatibleProvider` — httpx + retry + cost tracking |
| Prompt cache | `prompt_loader.py:12` | `PromptLoader.load()` — in-memory cache, template substitution |
| Logger setup | `logger.py:15` | `setup_logger()` — daily rotation, colored console |

## CONVENTIONS
- **pydantic-settings**: `BaseSettings` with `Config.env_file`, `case_sensitive=False`, `extra="ignore"`
- **Role-based model routing**: `settings.get_model_for_role(role)` → different models per advisor/graduate/subagent
- **Lazy cost tracking import**: LLM providers import `cost_tracker` at call time to avoid circular deps
- **Temperature by role**: advisor=0.3, graduate/subagent=0.7
- **Retry logic**: `settings.llm_max_retries` (default 3) on HTTP errors

## ANTI-PATTERNS
- Never instantiate LLMProvider directly — always use `create_llm_provider()`
- Never hardcode API keys — use `settings.llm_api_key`
- Don't bypass prompt_loader for prompt text (use `prompt_loader.load("name")`)

## NOTES
- `.env` lives at repo root, config.py navigates up 4 levels to find it
- Default: `MOCK_MODE=true` — entire system runs without API keys
- CORS origins loaded from `.env` via `settings.parsed_cors_origins`
