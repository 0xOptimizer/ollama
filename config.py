from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen3.5:4b"
    api_keys: list[str] = []
    host: str = "0.0.0.0"
    port: int = 8000
    system_prompt: str = ""
    enable_thinking: bool = False
    request_timeout: float = 300.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()