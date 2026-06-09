import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv():
        return None


def load_environment() -> None:
    load_dotenv()


def require_env(keys: list[str]) -> None:
    missing = [key for key in keys if not os.getenv(key)]
    if missing:
        raise ValueError("Missing required environment variables: " + ", ".join(missing))


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None or value == "":
        return default
    return int(value)


def _env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None or value == "":
        return default
    return float(value)


def _env_optional_float(key: str, default: float | None = None) -> float | None:
    value = os.getenv(key)
    if value is None or value == "":
        return default
    if value.lower() in {"none", "null"}:
        return None
    return float(value)


def build_generation_config(model_name: str) -> dict:
    return {
        "model_name": model_name,
        "n": _env_int("GENERATION_N", 1),
        "max_tokens": _env_int("GENERATION_MAX_TOKENS", 4096),
        "temperature": _env_float("GENERATION_TEMPERATURE", 0.1),
        "top_p": _env_optional_float("GENERATION_TOP_P", None),
        "repetition_penalty": _env_float("GENERATION_REPETITION_PENALTY", 1.1),
        "presence_penalty": _env_float("GENERATION_PRESENCE_PENALTY", 0.0),
    }
