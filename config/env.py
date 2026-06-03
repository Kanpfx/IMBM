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


def build_generation_config(model_name: str) -> dict:
    return {
        "model_name": model_name,
        "n": 1,
        "max_tokens": 6144,
        "temperature": 0.1,
        "top_p": None,
        "repetition_penalty": 1.1,
        "presence_penalty": 0.0,
    }
