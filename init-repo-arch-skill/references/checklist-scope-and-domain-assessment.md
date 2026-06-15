# Шаг workflow: assess_scope_and_domains

Оценить объём и выявить бизнес-домены до начала детального анализа. Выполняется **по каждому репозиторию в отдельности**, последовательно, в порядке `ordered_repository_names`.

Результат хранится **внутри каждого репозитория** в `domain_map`, а не глобально.

## Цель

Для каждого репозитория ответить на два вопроса:

1. **Насколько большой этот репозиторий?** — нужно выбрать стратегию анализа.
2. **Есть ли в нём явные бизнес-домены?** — если да, анализ внутри репозитория идёт домен за доменом.

## Для каждого репозитория: шаг 1 — быстрая оценка объёма

Выполнить без открытия файлов с бизнес-логикой:

```bash
# общее число файлов (без .git)
find .temp/<repo> -not -path "*/.git/*" -type f | wc -l

# структура модулей первого уровня
ls -1 .temp/<repo>/src/ 2>/dev/null || ls -1 .temp/<repo>/

# ориентировочный LOC по основным языкам
find .temp/<repo> -not -path "*/.git/*" -type f \
  \( -name "*.py" -o -name "*.go" -o -name "*.ts" -o -name "*.tsx" -o -name "*.java" -o -name "*.kt" \) \
  | xargs wc -l 2>/dev/null | tail -1
```

Определить класс объёма **этого репозитория**:

| Класс | Ориентир |
| --- | --- |
| `small` | < 5 000 файлов |
| `medium` | 5 000 – 30 000 файлов |
| `large` | 30 000 – 150 000 файлов |
| `xlarge` | > 150 000 файлов |

## Для каждого репозитория: шаг 2 — поиск бизнес-доменных границ

Просмотреть структуру репозитория на признаки явных доменных границ. **Не читать бизнес-логику** — только структурные сигналы.

### Сигналы наличия доменных границ

**Сильные (один достаточен):**

- Каталоги верхнего уровня с бизнес-именами: `apps/billing/`, `apps/auth/`, `src/notifications/` и т.п.
- Django: несколько приложений в `apps/` или разделение по `manage.py` модулям
- Явный DDD layout: `domain/<bounded-context>/` или `contexts/<name>/`
- Монорепо: `services/<name>/` или `apps/<name>/` где имена — продуктовые понятия

**Средние (два и более вместе):**

- Prefixed модели БД (`billing_*`, `auth_*`) или отдельные схемы
- Отдельные Kafka-топики с доменным префиксом
- Раздельные OpenAPI-файлы по областям
- Разные docker-compose-сервисы с продуктовыми именами

**Слабые (сами по себе не достаточны):**

- Имена папок без явного кода внутри
- Комментарии без подтверждения в структуре
- README с перечислением областей без соответствующего layout

### Когда НЕ выделять домены внутри репозитория

- Нет двух и более сильных сигналов → стратегия `per_module` (один проход).
- Репозиторий маленький (`small`) → всегда `per_module`.
- Есть технические слои (`api/`, `domain/`, `infrastructure/`) без продуктового деления → это не бизнес-домены, это DDD-архитектура. Стратегия `per_module`.
- Одно Django-приложение без явного деления на apps → `per_module`.

## Для каждого репозитория: шаг 3 — зафиксировать результат

**Если доменов нет (`per_module`):**

```bash
python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py \
  domain --progress <path> --repo <repo-name> \
  --assess --strategy per_module --volume-class <class> --total-files <N>
```

**Если домены найдены (`per_domain`):**

```bash
# 1. Зафиксировать стратегию
python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py \
  domain --progress <path> --repo django-backend \
  --assess --strategy per_domain --volume-class large --total-files 48000

# 2. Зарегистрировать каждый домен с путями внутри репозитория
python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py \
  domain --progress <path> --repo django-backend \
  --register --domain-id billing --name "Биллинг" \
  --paths "apps/billing/,apps/payments/" \
  --signal "Отдельные Django-приложения apps/billing и apps/payments"

python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py \
  domain --progress <path> --repo django-backend \
  --register --domain-id auth --name "Авторизация" \
  --paths "apps/users/,apps/auth/"

# 3. Добавить поддомены если явно видны в структуре
python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py \
  domain --progress <path> --repo django-backend \
  --add-subdomain --domain-id billing \
  --subdomain-id subscriptions --subdomain-name "Подписки"
```

## Обязательные выходы этого шага

- Для каждого `in_scope` репозитория заполнены `domain_map.assessed_at`, `strategy`, `volume_class`
- Если `strategy=per_domain`: зарегистрировано минимум 2 домена, каждый с непустым `paths`
- Шаг завершён через `advance --note "<краткий итог: repo1: per_domain 3 домена; repo2: per_module>"`

Guard не даст завершить этот шаг, пока хотя бы один in-scope репозиторий не имеет `domain_map.assessed_at`.

## Подводные камни

- Не выдумывай домены из названий папок без кода внутри.
- Не смешивай технические слои с бизнес-доменами.
- Не мельчи: 10 поддоменов из 10 Django apps — это не полезно. Объединяй смежные apps в один домен, если они решают одну продуктовую задачу.
- Один небольшой сервис с чёткой специализацией — всегда `per_module`, даже если внутри есть несколько папок.
