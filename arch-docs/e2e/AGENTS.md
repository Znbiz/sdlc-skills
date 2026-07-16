# AGENTS.md — Документация для AI-агентов

## О проекте

**qa-automation** — фреймворк для автоматизированного тестирования продуктов компании Tropass.

### Стек технологий

- **Python**: 3.13.2+
- **Менеджер пакетов**: Poetry
- **Тестирование**: pytest, allure-pytest
- **UI-автоматизация**: Playwright (chromium)
- **API-тесты**: httpx
- **Валидация данных**: pydantic, pydantic-settings
- **Генерация тестовых данных**: polyfactory, faker
- **Логирование**: structlog
- **Ретраи**: stamina
- **Linting/Formatting**: ruff, mypy
- **Pre-commit**: pre-commit

## Структура проекта

```
e2e/
├── tests/                          # Основной код тестов
│   ├── conftest.py                 # Глобальные фикстуры pytest
│   ├── settings.py                 # Конфигурация и настройки
│   ├── httpx_client.py             # HTTP-клиент для API тестов
│   ├── external/                   # Клиенты внешних сервисов
│   │   ├── keycloak_api.py         # Keycloak авторизация
│   │   ├── api_gateway.py          # API Gateway сервис
│   │   ├── core_backend_api.py     # Core Backend API
│   │   └── market_backend_api.py   # Marketplace Backend API
│   ├── core/                       # Тесты Core продукта
│   │   ├── ui_tests/               # UI тесты
│   │   │   ├── test_authorization/
│   │   │   ├── test_card_controls/
│   │   │   ├── test_headers/
│   │   │   ├── test_my_models/
│   │   │   ├── test_my_tags/
│   │   │   └── test_my_trails/
│   │   └── pages/                  # Page Objects для Core
│   ├── marketplace/                # Тесты Marketplace
│   │   ├── marketplace_tests/
│   │   │   ├── test_authorization/
│   │   │   ├── test_cart/
│   │   │   ├── test_filters_and_sorting/
│   │   │   ├── test_model_menu/
│   │   │   ├── test_search_field/
│   │   │   └── test_user_data/
│   │   └── pages/                  # Page Objects для Marketplace
│   ├── passport/                   # Тесты Passport (auth service)
│   │   ├── passport_tests/
│   │   │   ├── test_passport_buttons/
│   │   │   ├── test_password_recovery/
│   │   │   └── test_registration/
│   │   └── pages/                  # Page Objects для Passport
│   ├── admin_market/               # Тесты Admin Market
│   │   ├── admin_market_tests/
│   │   │   ├── test_authorization/
│   │   │   ├── test_filters/
│   │   │   ├── test_general_information_tab/
│   │   │   ├── test_headers/
│   │   │   └── test_model_card_tab/
│   │   └── pages/                  # Page Objects для Admin Market
│   ├── test_models/                # Тесты управления ML-моделями
│   │   ├── ui_tests/
│   │   ├── api_tests/
│   │   ├── admin_core_page/
│   │   └── steps/                  # Шаги для создания ML-моделей
│   ├── chat_tropass/               # Тесты чат-бота
│   ├── editor/                     # Тесты Editor
│   │   ├── editor_tests/
│   │   │   └── test_authorization/
│   │   └── pages/                  # Page Objects для Editor
│   └── artifacts/                  # Тестовые файлы
│       ├── models/                 # ML-модели для тестов
│       └── test_files/             # Файлы для загрузки (pdf, png, mp4, etc.)
├── pyproject.toml                  # Конфигурация Poetry и инструментов
├── docker-compose.yml              # Docker конфигурация
├── Dockerfile                      # Docker образ для тестов
├── Justfile                        # Just команды (альтернатива Make)
```

## Запуск тестов

### Локальный запуск

```bash
# Установка зависимостей
poetry install

# Запуск всех тестов
poetry run pytest

# Запуск с отчётом Allure
poetry run pytest --alluredir=./allure-results
poetry run allure serve ./allure-results

# Запуск только UI тестов
poetry run pytest -m "not api"

# Запуск только API тестов
poetry run pytest -m "api"

# Запуск smoke тестов
poetry run pytest -m "smoke"

# Запуск regression тестов
poetry run pytest -m "regression"

# Запуск тестов с видео
poetry run pytest --browser=chromium

# Запуск в headless режиме (по умолчанию)
poetry run pytest

# Запуск в headed режиме (для отладки)
poetry run pytest --headed

# Запуск тестов в параллельном режиме
poetry run pytest -n auto
```

### Запуск через Docker

```bash
docker-compose up --build
```

### Запуск через Just

```bash
just test          # Запустить все тесты
just test-smoke    # Запустить smoke тесты
just test-ui       # Запустить UI тесты
just test-api      # Запустить API тесты
```

## Маркеры pytest

- `@pytest.mark.smoke` — Smoke тесты
- `@pytest.mark.regression` — Regression тесты
- `@pytest.mark.slow` — Медленные тесты
- `@pytest.mark.api` — API тесты

## Фикстуры

### Основные фикстуры (conftest.py)

- `page` — Playwright страница с автоматическим скриншотом при падении
- `context_with_video` — Browser контекст с записью видео
- `browser` — Chromium браузер
- `httpx_client` — HTTP клиент для API запросов
- `keycloak_api_service` — Сервис для работы с Keycloak
- `keycloak_user_token` — Получение токена пользователя
- `core_backend_api_service` — Core Backend API сервис
- `market_backend_api_service` — Marketplace Backend API сервис
- `api_gateway_service` — API Gateway сервис
- `get_user_id_from_keycloak` — Получение ID пользователя из токена

## Конфигурация

Настройки загружаются из `.env` файла через pydantic-settings.

### Основные переменные окружения

```bash
# Токены
API_TOKEN_HEADER_VALUE=your_token
API_GATEWAY_TOKEN=your_gateway_token

# Настройки браузера (опционально)
HEADLESS=true

# URLs настраиваются в tests/settings.py
```

### Классы настроек (tests/settings.py)

- `BrowserSettings` — настройки браузера (headless, директории для скриншотов/видео)
- `FirstUser`, `SecondUser`, `AdminUser`, `ModelTestUser` — тестовые пользователи
- `CoreUISettings` — URL Core UI
- `CoreBackendSettings` — настройки Core Backend API
- `MarketplaceSettings` — настройки Marketplace
- `PassportSettings` — настройки Passport (авторизация)
- `AdminMarketSettings` — настройки Admin Market
- `ApiGatewaySettings` — настройки API Gateway

## Паттерны проектирования

### Page Object Model

Каждая страница приложения представлена классом с методами для взаимодействия:

``` python
from playwright.sync_api import Page

class LoginPage:
    def __init__(self, page: Page):
        self.page = page
        self.login_input = page.locator("#login")
        self.password_input = page.locator("#password")
        self.login_button = page.locator("button[type='submit']")

    def login(self, login: str, password: str):
        self.login_input.fill(login)
        self.password_input.fill(password)
        self.login_button.click()
```

### API Service Pattern

API эндпоинты инкапсулированы в сервисные классы:

```python
@dataclasses.dataclass
class CoreBackendApiService:
    httpx_client: HttpxClientService

    def get_models(self) -> list[ModelSchema]:
        return self.httpx_client.make_request(
            method="get",
            path="api/rest/mlmodels/",
            response_schema=ModelSchema,
            is_response_list=True,
        )
```

### Data Classes для API схем

Используются pydantic модели для валидации API ответов:

```python
class ModelSchema(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
```

## Написание тестов

### Структура теста

```python
import allure
import pytest
from playwright.sync_api import Page, expect

class TestFeature:
    @allure.step
    @pytest.mark.smoke
    def test_feature_name(self, page: Page, login_user: MyModelsPage) -> None:
        """Описание теста.

        Task: https://youtrack.../issue/XXX
        Kiwi TCMS: https://kiwi.../case/XXX

        Предварительные условия:
        - Пользователь авторизован

        Ожидаемый результат:
        1. Шаг 1
        2. Шаг 2
        """
        with allure.step("1. Действие"):
            # Код

        with allure.step("2. Проверка"):
            expect(some_locator).to_be_visible()
```

### Allure аннотации

- `@allure.step` — шаг в отчёте
- `@allure.title` — название теста
- `@allure.description` — описание
- `@allure.feature` — функциональность
- `@allure.story` — пользовательская история
- `allure.attach()` — прикрепление файлов

## Линтинг и типизация

```bash
# Проверка типов
poetry run mypy tests/

# Форматирование
poetry run ruff format tests/

# Линтинг
poetry run ruff check tests/

# Pre-commit хуки
poetry run pre-commit run --all-files
```

## Полезные команды

```bash
# Установка pre-commit хуков
poetry run pre-commit install

# Запуск тестов с конкретным маркером
poetry run pytest -m "smoke and not slow"

# Запуск конкретного теста
poetry run pytest tests/core/ui_tests/test_authorization/test_authorization.py::TestAuthorization::test_authorization_in_core

# Запуск тестов с отладкой (headed mode)
poetry run pytest --headed --browser=chromium

# Генерация отчёта
poetry run allure generate ./allure-results --clean
poetry run allure open ./allure-results
```

## Известные ограничения

- Требуется Python 3.13.2+
- Для UI тестов требуется установленный Playwright браузер: `playwright install chromium`
- Некоторые тесты требуют специальных токенов и доступа к staging окружению
- Видео запись тестов может занимать значительное место на диске

## Ссылки

- YouTrack: https://youtrack.tropass.online/
- Kiwi TCMS: https://kiwi.tropass.me/
- Chat: https://chat.tropass.online/
- Market: https://market.stage.tropass.me/
- Core: https://core.stage.tropass.me/
- Passport: https://passport.stage.tropass.me/