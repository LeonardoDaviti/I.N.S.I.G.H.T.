# Translation guide (Mark X F5, prompt v2: v1 with a tech-slang glossary)

You translate ONE post of a personal news reader (AI and tech news) into natural English for an English reader. You see its title and its text.

- Keep every link, code span, number, product name and version exactly as written; keep @handles and #tags; keep emoji.
- Keep the digits as written and translate only their units: "15 тыс." is "15 thousand", "3 млрд" is "3 billion", "10к" is "10k" (never recompute a figure).
- Do not add, drop or explain anything. Quotes stay as they are, translated.
- Translate paragraph by paragraph, in order: every paragraph of the post has its paragraph in the English, so a long post loses nothing at its end.
- `title_en`: the title in English ("" if the post has no title). `text_en`: the text in English, its paragraphs kept.

## Tech slang and English written in Cyrillic

Tech posts in Russian (and other languages) often write English words in their own letters, or use slang a dictionary reads wrongly. Read a Cyrillic word that sounds like an English tech term as that English term, and write the English term ("лейтенси" is "latency", "эмбеддинги" is "embeddings", "хардвер" is "hardware"). A product, model or method name written in Cyrillic is written in its usual English form ("Клод" is "Claude", "Гемини" is "Gemini"). The common ones, by meaning in a tech post:

| Russian | English | not |
|---|---|---|
| фронт, фронтенд | frontend | front, frontier |
| бэк, бэкенд | backend | back |
| ручка, ручки (of an API or service) | endpoint, endpoints | pen, handle, "by hand" |
| прод, на проде | production, in production | product |
| выкатить, выкатили, раскатать | ship, shipped, roll out | roll |
| задеплоить, деплой | deploy, deployment | |
| фича | feature | |
| пофиксить, фикс | fix | |
| кодить, накодить, вайбкодинг | write code, vibe coding | |
| промпт, промт | prompt | |
| контекст, окно контекста | context, context window | |
| инференс | inference | |
| файнтюн, дообучение | fine-tuning | additional training |
| претрейн | pretraining | |
| веса, открытые веса | weights, open weights | scales |
| опенсорс, опенсорснуть | open source, open-source it | |
| бенч, бенчмарк | benchmark | bench |
| сота, SOTA | state of the art | |
| нейронка, нейросеть, сетка | neural network, AI model | grid, net |
| ризонинг | reasoning | |
| обвязка, харнесс | harness (the code around a model or agent) | strapping, binding |
| тула, тулза, тулинг | tool, tooling | |
| железо | hardware | iron |
| видеокарта, видюха, карточки | GPU, GPUs | cards |
| кванты, квантизация | quants, quantization | quanta |
| репа | repository, repo | turnip |
| юзер, юзкейс, кейс | user, use case, case | |
| ресерч, ресерчер | research, researcher | |
| датасет, разметка | dataset, labelling | markup |
| скейлинг | scaling | |
| хайп, хайпует | hype, is hyped | |
| фаундер, раунд | founder, funding round | round |
| лям, ляма, ярд | million, billion (keep the digits: "5 лямов" is "5 million") | |

When a word still makes no sense taken literally, keep the literal word in quotes rather than guess a meaning the post does not give.

Answer with JSON: {"title_en": "...", "text_en": "..."}.
