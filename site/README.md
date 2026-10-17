# Lingvix — лендинг

Статический сайт (Astro 5 + Tailwind CSS) для проекта
[Lingvix](https://github.com/Pavel1778/LinguaFix).

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
├── astro.config.mjs      # site URL, интеграции (tailwind, sitemap)
├── tailwind.config.mjs
├── vercel.json           # конфиг для Vercel
├── layero.json           # конфиг для Layero
├── deploy.sh             # сборка + деплой
├── public/               # favicon, logo, og-image, robots.txt, скриншоты
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
**генерируются** из боевых корпусов `src/lingvix/data/ngrams_*.json`:

```bash
python scripts/build_demo_model.py
```

Файл нужно перегенерировать после пересборки корпусов и закоммитить: тест
`tests/test_demo_model.py` падает, если демо разошлось с продуктом.

## Деплой

### Vercel (основной)

1. Зарегистрируйтесь на <https://vercel.com> через GitHub.
2. **Add New → Project** → выберите репозиторий `LinguaFix` (он получит
   имя `Lingvix` после переименования на GitHub).
3. **Root Directory** = `site`.
4. Framework определится как Astro; build — `npm run build`, output — `dist`.
5. **Deploy**. Сайт будет на `<проект>.vercel.app`.

### Layero (зеркало для РФ)

Живой сайт — <https://linguafix.layero.app> (nginx). Публикация **не**
происходит автоматически на push: проверено 17.10.2026, зеркало отдавало сборку
от 09.10.2026 (v0.2.8.1) спустя десятки коммитов в `main`. Чтобы обновить его,
нужен вход в аккаунт Layero и ручная выкатка:

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
  "framework": "astro",
  "buildCommand": "npm run build",
  "outputDirectory": "dist"
}
```

`layero.json` не обязателен, если Layero сам определяет Astro, но для явности
он оставлен в `site/`.

## Обновление версии

Версия и ссылки на релиз живут в `src/consts.ts` (`VERSION`). При выпуске новой
версии поменяйте `VERSION` — ссылка на `.deb` и строка в Hero обновятся
автоматически. `site` в `astro.config.mjs` и `robots.txt` стоит поправить на
боевой домен после деплоя.

## Что менять

- **Скриншоты** — `public/screenshots/*.svg` это плейсхолдеры. Замените их
  реальными снимками GUI (`.png`), сохранив имена, либо обновите пути в
  `Hero.astro`.
- **OG-изображение** — `public/og-image.png` (1200×630).
