from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "awwwards-jobs-scraper"
    VERSION: str = "0.1.0"
    SOURCE_URL: str = "https://www.awwwards.com/jobs/"
    REQUEST_TIMEOUT: float = 20.0

    class Config:
        env_file = ".env"

settings = Settings()
