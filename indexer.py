#!/usr/bin/env python3
"""
GSC Auto Indexer
-----------------
Le um ou mais sitemap.xml, extrai as URLs e envia cada uma para a
Google Indexing API usando um service account autorizado no Search Console.

Uso:
    python3 indexer.py --config config.json
    python3 indexer.py --config config.json --dry-run   (so mostra o que faria)

Requer:
    pip install google-auth requests

Configuracao: veja config.example.json
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

INDEXING_API_URL = "https://indexing.googleapis.com/v3/urlNotifications:publish"
SCOPES = ["https://www.googleapis.com/auth/indexing"]

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("gsc-auto-indexer")


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"submitted": {}}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def fetch_sitemap_urls(sitemap_url: str, seen: set) -> list:
    """Busca um sitemap.xml e retorna a lista de URLs de conteudo.
    Trata tambem sitemap-index (que aponta para outros sitemaps)."""
    if sitemap_url in seen:
        return []
    seen.add(sitemap_url)

    log.info(f"Buscando sitemap: {sitemap_url}")
    try:
        resp = requests.get(sitemap_url, timeout=30, headers={"User-Agent": "GSC-Auto-Indexer/1.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Falha ao buscar {sitemap_url}: {e}")
        return []

    try:
        root = ElementTree.fromstring(resp.content)
    except ElementTree.ParseError as e:
        log.error(f"XML invalido em {sitemap_url}: {e}")
        return []

    tag = root.tag.lower()
    urls = []

    if tag.endswith("sitemapindex"):
        # sitemap de sitemaps -> segue recursivamente
        for sm in root.findall("sm:sitemap/sm:loc", SITEMAP_NS):
            if sm.text:
                urls.extend(fetch_sitemap_urls(sm.text.strip(), seen))
    elif tag.endswith("urlset"):
        for loc in root.findall("sm:url/sm:loc", SITEMAP_NS):
            if loc.text:
                urls.append(loc.text.strip())
    else:
        log.warning(f"Formato de sitemap nao reconhecido em {sitemap_url}")

    return urls


def get_access_token(service_account_file: str):
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    creds.refresh(Request())
    return creds.token


def submit_url(url: str, token: str, dry_run: bool = False) -> tuple:
    """Envia uma URL para a Indexing API. Retorna (sucesso, mensagem)."""
    if dry_run:
        return True, "dry-run (nao enviado)"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"url": url, "type": "URL_UPDATED"}

    try:
        resp = requests.post(INDEXING_API_URL, headers=headers, json=payload, timeout=30)
    except requests.RequestException as e:
        return False, f"erro de rede: {e}"

    if resp.status_code == 200:
        return True, "ok"
    if resp.status_code == 429:
        return False, "cota excedida (429)"
    return False, f"erro {resp.status_code}: {resp.text[:200]}"


def main():
    parser = argparse.ArgumentParser(description="Auto-indexador de sitemaps no Google Search Console")
    parser.add_argument("--config", default="config.json", help="Caminho do arquivo de configuracao")
    parser.add_argument("--dry-run", action="store_true", help="Nao envia nada, so mostra o que seria feito")
    args = parser.parse_args()

    cfg = load_config(args.config)
    state = load_state(cfg["state_file"])
    quota = cfg.get("daily_quota", 190)
    resubmit_after = timedelta(days=cfg.get("resubmit_after_days", 7))

    # 1. Coleta todas as URLs de todos os sitemaps configurados
    all_urls = []
    seen_sitemaps = set()
    for sm in cfg["sitemaps"]:
        all_urls.extend(fetch_sitemap_urls(sm, seen_sitemaps))

    all_urls = list(dict.fromkeys(all_urls))  # remove duplicadas, preserva ordem
    log.info(f"Total de URLs encontradas nos sitemaps: {len(all_urls)}")

    # 2. Filtra as que ja foram enviadas recentemente
    now = datetime.now(timezone.utc)
    to_submit = []
    for url in all_urls:
        last = state["submitted"].get(url)
        if last:
            last_dt = datetime.fromisoformat(last)
            if now - last_dt < resubmit_after:
                continue
        to_submit.append(url)

    log.info(f"URLs pendentes de envio (novas ou vencidas): {len(to_submit)}")

    if not to_submit:
        log.info("Nada para enviar neste ciclo.")
        return

    # 3. Respeita a cota diaria
    to_submit = to_submit[:quota]

    # 4. Autentica
    if not args.dry_run:
        token = get_access_token(cfg["service_account_file"])
    else:
        token = None

    # 5. Envia cada URL
    ok_count, fail_count = 0, 0
    for url in to_submit:
        success, msg = submit_url(url, token, dry_run=args.dry_run)
        if success:
            ok_count += 1
            state["submitted"][url] = now.isoformat()
            log.info(f"[OK] {url} ({msg})")
        else:
            fail_count += 1
            log.warning(f"[FALHA] {url} -> {msg}")
            if "cota excedida" in msg:
                log.warning("Cota diaria da API atingida, parando por aqui.")
                break
        time.sleep(0.5)  # gentileza com a API

    save_state(cfg["state_file"], state)
    log.info(f"Concluido. Sucesso: {ok_count} | Falhas: {fail_count}")


if __name__ == "__main__":
    main()
