# Bundled dictionaries

Klyrshift ships two kinds of word lists.

## Base — general frequency lists

Top-50k word lists used by `klyrshift dict download <lang>`. Each file keeps
only the word column of the upstream list, one word per line.

Source: [FrequencyWords](https://github.com/hermitdave/FrequencyWords) by Hermit
Dave. The FrequencyWords *code* is MIT, but the generated lists are *content*,
which the project places under
[CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/): a word
frequency list is content, so these files are CC-BY-SA-4.0, not MIT. The lists
are frequency-ordered, so the first lines are the most common words.

| File | Language |
|---|---|
| `ru-50k.txt` | русский |
| `en-50k.txt` | English |
| `uk-50k.txt` | українська |
| `de-50k.txt` | Deutsch |
| `fr-50k.txt` | français |

## Thematic — professional vocabulary

Domain word lists that widen the detector's vocabulary for a field. They are
**not** bundled in the `.deb`; `klyrshift dict install <category>` downloads the
matching archive from the GitHub Release and adds it to the vocabulary on top of
the base list.

| Category | Languages | Files |
|---|---|---|
| `it` | ru, en | `it/ru-it-1k.txt`, `it/en-it-1k.txt` |
| `code` | ru, en | `code/ru-code-1k.txt`, `code/en-code-1k.txt` |
| `names` | ru, en | `names/ru-names-1k.txt`, `names/en-names-1k.txt` |
| `medicine` | ru, en | `medicine/ru-medicine-1k.txt`, `medicine/en-medicine-1k.txt` |
| `legal` | ru, en | `legal/ru-legal-1k.txt`, `legal/en-legal-1k.txt` |
| `finance` | ru, en | `finance/ru-finance-1k.txt`, `finance/en-finance-1k.txt` |
| `engineering` | ru, en | `engineering/ru-engineering-1k.txt`, `engineering/en-engineering-1k.txt` |
| `science` | ru, en | `science/ru-science-1k.txt`, `science/en-science-1k.txt` |
| `business` | ru, en | `business/ru-business-1k.txt`, `business/en-business-1k.txt` |
| `electronics` | ru, en | `electronics/ru-electronics-1k.txt`, `electronics/en-electronics-1k.txt` |
| `media` | ru, en | `media/ru-media-1k.txt`, `media/en-media-1k.txt` |
| `education` | ru, en | `education/ru-education-1k.txt`, `education/en-education-1k.txt` |
| `gaming` | ru, en | `gaming/ru-gaming-1k.txt`, `gaming/en-gaming-1k.txt` |
| `sport` | ru, en | `sport/ru-sport-1k.txt`, `sport/en-sport-1k.txt` |

Every thematic list is curated by hand for this project and released under the
MIT License, like the code (see the repository `LICENSE`); the per-category
`README.md` records the source. The two licences apply to different files: the
base frequency lists above stay CC-BY-SA-4.0. No list with an unclear or proprietary licence is included.

## Installing

```bash
klyrshift dict categories                     # list categories and languages
klyrshift dict install it --lang ru           # download and enable
klyrshift dict list-installed                 # what is enabled
klyrshift dict remove-category it             # disable
```

Detection priority is **user dictionary → thematic → base → T9**: a word the
user taught wins over everything, a thematic word wins over the general list.
