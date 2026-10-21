# Скриншоты / Screenshots

Это **реальные снимки** GUI, а не плейсхолдеры. Их делает
`scripts/make_screenshots.py`: скрипт строит настоящее окно `KlyrshiftWindow`,
даёт GTK разложить виджеты и рендерит дерево в PNG через `Gtk.WidgetPaintable`
и `Gsk.CairoRenderer`. То есть на картинках тот же интерфейс, который видит
пользователь, отрисованный самим GTK.

## Как пересобрать

Нужны GTK4/libadwaita и дисплей (в headless-окружении — `xvfb-run`):

```bash
sudo apt-get install -y xvfb python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
PYTHONPATH=/usr/lib/python3/dist-packages xvfb-run -a \
    .venv/bin/python scripts/make_screenshots.py docs/screenshots
```

Интерпретатор должен видеть зависимости проекта (`tomli-w` и сам `klyrshift`),
поэтому это `python` из окружения проекта, а не системный `python3`.

Скрипт перезаписывает три файла ниже и завершается с ошибкой, если какой-то
экран не удалось отрисовать.

| Файл | Экран |
|---|---|
| `main-window.png` | Главное окно: большая кнопка вкл/выкл, режим auto/manual/hybrid |
| `advanced-settings.png` | Advanced: триггеры, T9, раскладка по приложениям, исключения |
| `dictionary.png` | Словарь: добавление и удаление слов |
