# Lingvix — лендинг

Статический сайт (Astro 5 + Tailwind CSS) для проекта
[Lingvix](https://github.com/Pavel1778/Lingvix).

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
2. **Add New → Project** → выберите репозиторий `Lingvix`.
3. **Root Directory** = `site`.
4. Framework определится как Astro; build — `npm run build`, output — `dist`.
5. **Deploy**. Сайт будет на `<проект>.vercel.app`.

### Layero (зеркало для РФ)

Проект Layero **подключён к репозиторию**: платформа сама собирает и публикует
сайт на каждом push в `main`. Репозиторий самодостаточен для сборки — на это
работает файл **`site/layero.json`**:

```json
{
  "framework": "astro",
  "buildCommand": "npm run build",
  "outputDirectory": "dist"
}
```

Проверить план сборки без выгрузки (логин не нужен):

```bash
npx layero@latest deploy --dry-run
```

**Вручную** (не обязательно, только для локальной проверки):

```bash
npx layero@latest deploy --root site
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
