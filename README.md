# Платформа управления ИИ-агентами

Локальный сервис, в котором можно завести агента с собственным системным промтом и запустить его на разбор веб-страницы. Бэкенд скачивает HTML, очищает его и стримит ход работы в браузер. Конфигурации агентов лежат в SQLite и переживают перезапуск контейнера.

Интерфейс: [http://127.0.0.1:8030](http://127.0.0.1:8030)

## Стек

- Python 3.11, FastAPI, Uvicorn
- Официальный клиент OpenAI с `base_url` на ProxyAPI
- httpx и BeautifulSoup — загрузка и очистка страницы
- SQLAlchemy и SQLite
- HTML, CSS и vanilla JS, обновление логов через Server-Sent Events
- Docker Compose: контейнер `backend` (FastAPI) и контейнер `frontend` (Nginx)

## Запуск

```bash
cp .env.example .env
```

Заполните в `.env` ключ, базовый адрес и идентификатор модели. Затем:

```bash
docker compose up --build
```

Откройте [http://127.0.0.1:8030](http://127.0.0.1:8030). При первом запуске пустая база сама создаёт агента «SEO-Анализ». Если в базе уже есть агенты, повторный старт их не перезаписывает.

Остановка:

```bash
docker compose down
```

База хранится в Docker-томе `seo-data`, файл внутри контейнера — `/app/data/agents.db`. Это тот же том, что у прежнего контейнера на VPS: в `compose.yaml` он объявлен как `external`, Compose его не создаёт и `docker compose down -v` его не удаляет. Если тома ещё нет: `docker volume create seo-data`. Удалить агентов вместе с томом можно только командой `docker volume rm seo-data` после остановки контейнеров.

Снаружи открыт только frontend: `127.0.0.1:8030` проксируется на Nginx (порт 80). Backend в интернет не публикуется. На VPS файл окружения уже лежит в `/root/My_project/pseudoaiagent-seo/.env`: запускайте Compose из этого каталога, тогда `env_file: .env` совпадает с прежним `--env-file`. Перед первым `docker compose up` остановите старый контейнер `pseudoaiagent-seo`, имя занято frontend.

Для Better Stack: HTTP-проверка на `GET /health` (тот же ответ у `GET /api/health`, тело `{"status":"ok"}`). Каждая проверка пишет в stdout backend строку `health status=ok` — её забирает сборщик логов контейнера.

Готовые образы для `linux/amd64` лежат в Docker Hub:

- `mdv10072026/pseudoaiagent-seo-backend:latest` — FastAPI
- `mdv10072026/pseudoaiagent-seo-frontend:latest` — Nginx

Ключ и адрес модели в образы не входят. На машине без исходников сохраните `compose.yaml` и `.env`, уберите блоки `build:` и запустите:

```bash
docker compose pull
docker compose up -d
```

Прежний единый образ `mdv10072026/pseudoaiagent-seo:latest` — версия до разделения на два контейнера.

Сервис без авторизации и рассчитан на локальный запуск. Не публикуйте порт в интернет: ключ уходит только на адрес из `PROXYAPI_BASE_URL`, а в модель отправляется текст открытых страниц.

## Конфигурация

Секреты в репозиторий не кладутся. Имена переменных:

| Переменная | Назначение |
| --- | --- |
| `PROXYAPI_KEY` | Ключ доступа ProxyAPI |
| `PROXYAPI_BASE_URL` | Базовый адрес единого API, `https://api.proxyapi.ru/v1`. Старый путь `/openai/v1` принимает только модели OpenAI |
| `PROXYAPI_MODEL` | Идентификатор модели в кабинете ProxyAPI. Платформа модель не выбирает |
| `DATABASE_PATH` | Необязательно. В Compose задано `/app/data/agents.db` |
| `LOGTAIL_SOURCE_TOKEN` | Токен источника Better Stack. Пусто — логи только в stdout контейнера |
| `LOGTAIL_HOST` | Хост приёма этого источника, со схемой `https` |
| `ADMIN_PASSWORD` | Пароль пользователя `admin`. Логин всегда `admin` |
| `SESSION_SECRET` | Необязательный секрет подписи сессии. Если пусто, берётся `ADMIN_PASSWORD` |

Внешние сервисы: ProxyAPI (HTTP API, совместимый с клиентом OpenAI) и Better Stack Logtail. Источник логов — `pseudoaiagent-seo`. Библиотека `logtail-python` отправляет журналы приложения и Uvicorn. Строка `health status=ok` по-прежнему пишется в stdout и уходит в Logtail, если токен задан.

Compose сам подхватывает `compose.override.yaml` и этими значениями перекрывает `.env`. Тестовый мок вынесен в `compose.test.yaml` и в обычный запуск не входит. Подключить его можно так: `docker compose -f compose.yaml -f compose.test.yaml up`.

## Как пользоваться

1. При открытии страницы нужен вход. Если логина нет, сервис предлагает регистрацию и показывает условия из `frontend/terms.md`. Требований к сложности пароля нет, одинаковые логины не допускаются. После входа в шапке справа видно имя пользователя: там смена пароля и выход. «Отмена» в окне смены пароля закрывает его и не сохраняет введённое.
2. У каждого пользователя свой список агентов и свои системные промты. Пользователь `admin` хранит уже существующие настройки. Новый пользователь получает копию списка `admin` на момент регистрации. Дальше списки живут отдельно. `admin` задаёт начальное состояние сервиса.
3. «Настройки агентов» в правом верхнем углу блока «Агент» открывает название, системный промт, «Сохранить агента», «+ Добавить нового агента» и «Удалить агента». Сохранение вызывает `POST /api/agents`: совпавшее имя обновляет промт, новое имя создаёт агента. Удаление стирает выбранного через `DELETE /api/agents/{id}`.
4. В блоке анализа укажите URL и нажмите «Запустить агента». Если схема не указана, подставится `https://`.
5. «Ход работы» — отдельный блок на всю ширину над «Результатом». Высоту журнала можно менять: от половины прежней фиксированной высоты почти до трёхкратной, примерно на три строки ниже этого предела. Длинный ход прокручивается. В рамках открытой вкладки предыдущие запуски остаются, между ними разделитель, каждый начинается с даты, времени и адреса страницы. После закрытия вкладки или выхода история не сохраняется. «Результат» на всю ширину — итоговый ответ в Markdown. Кнопка «Сохранить отчет» скачивает текст этого блока файлом PDF.
5. «Остановить» закрывает поток. Лимит цикла — 10 шагов.

## Что делает анализ

`GET /api/analyze` (его открывает `EventSource` в браузере) и `POST /api/analyze` с JSON `{ "url", "agent_id" }` или `agent_name` отдают один и тот же SSE-поток.

1. Сервис находит агента и проверяет, что заданы ключ, адрес и модель.
2. Скачивает страницу, не ходит на локальные и внутренние адреса, обрывает редиректы туда же, вырезает скрипты и стили, забирает Title, H1, мета-теги и текст.
3. Модель получает системный промт агента и служебный протокол шага. На шаге она пишет мысль (`THOUGHT`), действие `finish` или `fetch_url` и, если заканчивает, итог в `FINAL`.
4. `fetch_url` один раз догружает ещё одну публичную страницу. Повтор того же URL не качается снова.
5. Мысли и действия идут событиями `log`, текст итога — событиями `result` (`delta` по ходу и `full` в конце). Поток закрывается событием `done`.

Пример для терминала:

```bash
curl -N -X POST http://127.0.0.1:8030/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","agent_id":1}'
```

## API

- `GET /health` и `GET /api/health` — проверка живости для Better Stack и Docker. Ответ `{"status":"ok"}`, в лог пишется `health status=ok`
- `GET /api/docs`, `GET /api/redoc` и `GET /api/openapi.json` — Swagger, ReDoc и схема. В образе по умолчанию открыты (`EXPOSE_API_DOCS=1`). В `compose.yaml` для VPS стоит `EXPOSE_API_DOCS=0`: Nginx отвечает 404 и наружу их не отдаёт. Рабочие методы `/api/agents`, `/api/analyze` и `/api/report` при этом остаются.
- `POST /api/auth/login` — вход. Неизвестный логин отвечает 404, неверный пароль — 401. Сессия в куке `seo_session`
- `POST /api/auth/register` — регистрация и копия агентов пользователя `admin`. Повтор логина отвечает 409
- `GET /api/auth/me` — текущий логин
- `POST /api/auth/logout` — выход
- `POST /api/auth/password` — смена пароля, тело `{ "current_password", "new_password" }`
- `GET /api/agents` — `id` и `name` агентов текущего пользователя
- `GET /api/agents/{id}` — агент вместе с `system_prompt`
- `POST /api/agents` — тело `{ "name", "system_prompt" }`. Ответ включает `action`: `created` или `updated`
- `DELETE /api/agents/{id}` — удаляет агента, ответ без тела
- `GET /api/analyze?url=&agent_id=` — SSE для интерфейса
- `POST /api/analyze` — тот же SSE для JSON-клиентов
- `POST /api/report` — тело `{ "text", "title" }`, ответ — файл PDF

## Папки

```
backend/app/main.py            API; интерфейс отдаёт, только если рядом есть каталог frontend
backend/app/logging_setup.py  stdout и отправка в Better Stack Logtail
backend/app/database.py        SQLite, пустая база создаёт «SEO-Анализ»
backend/app/models.py          модель Agent
backend/app/LLM_module.py      клиент модели, его можно вызывать отдельно от платформы
backend/app/dynamic_agent.py   цикл на 10 шагов
backend/app/react.py           разбор THOUGHT / ACTION / INPUT / FINAL
backend/app/scraper.py         загрузка и очистка HTML
backend/app/report.py          сборка PDF
backend/app/fonts/             шрифт DejaVu Sans для кириллицы в PDF
backend/app/prompts.py         промт дефолтного агента и протокол шага
frontend/                      index.html, app.js, style.css, terms.md, nginx.conf, Dockerfile
compose.yaml                   сервисы backend и frontend, том seo-data, порт 127.0.0.1:8030
Dockerfile                     образ backend
.env.example
```

Локальные тесты без Docker, из каталога `backend` после установки зависимостей:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Тесты не ходят в ProxyAPI и не скачивают внешние сайты.

Модуль `backend/app/LLM_module.py` не импортирует остальное приложение. Отдельный скрипт с тем же окружением может открыть клиент так: `LLMClient(LLMConfig.from_env())`, затем `await llm.complete(messages)` или `async for token in llm.stream_chat(messages)`. Нужны переменные `PROXYAPI_KEY`, `PROXYAPI_BASE_URL` и `PROXYAPI_MODEL`.

Если анализ публичного сайта сразу пишет, что адрес локальный или внутренний, контейнер получил для этого имени частный или зарезервированный IP. Платформа такие адреса не открывает. Проверьте DNS Docker.
