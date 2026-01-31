# testing

## Mapa stránek mmhk.cz

Spusťte skript pro vytvoření detailní mapy webu:

```bash
python3 scripts/build_sitemap.py --output output
```

Výstupy:
- `output/mmhk_sitemap.json`
- `output/mmhk_sitemap.md`

## Webové rozhraní

Spusťte lokální server s jednoduchým UI, které umožňuje zadat libovolnou URL a
průběžně sledovat postup crawleru:

```bash
python3 scripts/web_server.py
```

Poté otevřete `http://localhost:8000`.
