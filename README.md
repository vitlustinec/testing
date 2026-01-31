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
průběžně sledovat postup crawleru. Nejprve se spustí web a **teprve po zadání
adresy a kliknutí na „Spustit crawler“** se spustí samotné procházení:

```bash
python3 scripts/web_server.py
```

Poté otevřete `http://localhost:8000`, zadejte cílovou URL a spusťte crawler.
Pokud otevřete `web/index.html` přímo ze souboru, nastavte v poli backend URL
`http://localhost:8000` (kvůli CORS).
