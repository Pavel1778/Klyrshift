# Klyrshift — лендинг

Статический сайт (Astro 7 + Tailwind CSS 4) для проекта
[Klyrshift](https://github.com/Pavel1778/Klyrshift).

## Локальный запуск

```bash
cd site
npm install
npm run dev        # http://localhost:4321
```

Сборка и предпросмотр:

```bash
npm run build      # dist/
npm run preview
```

## Структура

```
site/
├── astro.config.mjs      # site URL, интеграции (tailwind через @tailwindcss/vite, sitemap)
├── vercel.json           # конфиг для Vercel
├── layero.json           # конфиг для Layero (framework, сборка, nodeVersion)
├── .nvmrc                # версия Node для локальной разработки (24)
├── deploy.sh             # сборка + деплой
├── public/               # favicon, logo, og-image, robots.txt
└── src/
    ├── consts.ts         # URL-ы (repo, releases, .deb) и версия
    ├── data/             # demo-model.json — генерируется, не правится руками
    ├── layouts/Base.astro
    ├── components/       # 10 секций + CodeBlock
    ├── pages/index.astro
    └── styles/global.css
```

## Живое демо

Секция «Попробовать» (`src/components/Demo.astro`) повторяет логику детектора в
TypeScript, чтобы посетитель мог исправить текст без установки. Её входные
данные — словарь и биграммы — лежат в `src/data/demo-model.json` и
**генерируются** из боевых корпусов `src/klyrshift/data/ngrams_*.json`:

```bash
python scripts/build_demo_model.py
```

Файл нужно перегенерировать после пересборки корпусов и закоммитить: тест
`tests/test_demo_model.py` падает, если демо разошлось с продуктом.

## Деплой

### Vercel (основной)

1. Зарегистрируйтесь на <https://vercel.com> через GitHub.
2. **Add New → Project** → выберите репозиторий `Klyrshift` (он получит
   имя `Klyrshift` после переименования на GitHub).
3. **Root Directory** = `site`.
4. Framework определится как Astro; build — `npm run build`, output — `dist`.
5. **Deploy**. Сайт будет на `<проект>.vercel.app`.

### Layero (зеркало для РФ)

Живой сайт — <https://klyrshift.layero.app> (nginx). Публикация **не**
происходит автоматически на push: зеркало выкатывается вручную и отставало от
`main`. Чтобы обновить его, нужен вход в аккаунт Layero и ручная выкатка:

```bash
npx layero@latest login          # интерактивно, либо задайте LAYERO_TOKEN
npx layero@latest deploy --root site
```

Проверить план сборки без выгрузки и без логина:

```bash
npx layero@latest deploy --dry-run
```

Репозиторий самодостаточен для сборки — на это работает файл
**`site/layero.json`**:

```json
{
  "$schema": "https://layero.ru/schema/layero-v2.json",
  "framework": "astro",
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "nodeVersion": "24"
}
```

`nodeVersion` обязателен, и указывать надо **мажор** (`"24"`), а не патч.
Причина: Layero держит по одной сборке на мажор и обновляет патч внутри неё сам
— в их же примере лога `[config] node=22.18.0 (.nvmrc)` при `.nvmrc` = `22`.
То есть линия 22 у Layero — это `22.18.0`, а Astro 7 требует `>=22.22.0`
(`engines.node`), поэтому сборка падала ещё до компиляции, и пин `22.22.0` её
не лечит: платформа всё равно отдаёт патч своей сборки. Безопасен только мажор,
у которого **вся** линейка выше порога Astro: `24.0.0 >= 22.22.0`, тогда как
`22.0.0 < 22.22.0`. Поэтому `site/layero.json`, `site/.nvmrc` и CI названы
мажором `24`, а `tests/test_layero_config.py` проверяет это правило и упадёт,
если пин опустится до линии, которую Layero собирает ниже порога.

Оговорка про приоритет: документация Layero противоречит сама себе — страница
`layero.json` говорит «всё, что указано в файле, платформа обязана применить», а
страница «Версии Node.js и Python» ставит **настройку проекта** в панели выше
файлов репозитория. Проверьте, что в панели (Проект → Настройки → Версия Node.js)
стоит «Авто» или `24`: если там жёстко выбрана 22, панель перекроет
`layero.json`, и сборка снова упадёт. По логу сборки видно, что применилось:
строка `[config] node=24 (layero.json)`, иначе будет назван перекрывший источник.

## Обновление версии

Версия и ссылки на релиз живут в `src/consts.ts` (`VERSION`). При выпуске новой
версии поменяйте `VERSION` — ссылка на `.deb` и строка в Hero обновятся
автоматически. `site` в `astro.config.mjs` и `robots.txt` стоит поправить на
боевой домен после деплоя.

## Что менять

- **Скриншоты** — в Hero стоит inline-мок `WindowMock.astro` (реальный SVG, не
  картинка), а реальные снимки GUI лежат в корневом `docs/screenshots/`
  (`main-window.png`, `advanced-settings.png`, `dictionary.png`). Пересобрать:
  `python scripts/make_screenshots.py` (нужен дисплей, в CI — под `xvfb-run`).
  Старые неиспользуемые `public/screenshots/*.svg` удалены.
- **OG-изображение** — `public/og-image.png` (1200×630), соцпревью для ссылок.
  Генерируется: `python scripts/make_og_image.py` (нужен собранный сайт для
  шрифтов и `chromium`). Тест `tests/test_og_image.py` падает, если картинка
  пустая, не того размера или показывает старое имя.
- **Версия** — `src/consts.ts` (`VERSION`), должна совпадать с
  `pyproject.toml`.
- **Демо-модель** — `src/data/demo-model.json`, генерируется
  `python scripts/build_demo_model.py` (см. «Живое демо»).
