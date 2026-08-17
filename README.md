# GSC Auto Indexer

Ferramenta que lê os `sitemap.xml` dos seus blogs e envia automaticamente cada
URL para a **Google Indexing API**, usando o service account já autorizado
como proprietário no Search Console.

> ⚠️ **Sobre a chave que você enviou**: como ela foi colada num chat, trate-a
> como potencialmente exposta. Recomendo revogar essa chave no Google Cloud
> Console (IAM & Admin → Contas de serviço → Chaves → excluir) e gerar uma
> nova, usando **somente** a nova chave no seu servidor.
>
> ⚠️ **Sobre a Indexing API**: ela é destinada oficialmente a páginas de
> vagas de emprego e eventos ao vivo. Funciona na prática para outros tipos
> de conteúdo, mas o Google pode não priorizar essas URLs — não é garantia
> de indexação instantânea.

## 1. Pré-requisitos

- Um servidor/VPS, Raspberry Pi, ou serviço de agendamento (GitHub Actions,
  Google Cloud Scheduler, etc.) — **este chat não mantém processos rodando**,
  então o agendamento de hora em hora precisa ser feito no seu ambiente.
- Python 3.9+
- O e-mail do service account (`rastreador@index-blogger-01.iam.gserviceaccount.com`)
  já precisa estar adicionado como **proprietário** da propriedade no Search
  Console (você disse que isso já foi feito ✅).

## 2. Instalação

```bash
pip install -r requirements.txt
```

Coloque nesta mesma pasta:
- o arquivo da chave (ex: `index-blogger-01-01be6f0eb763.json`, ou a nova
  chave gerada após a rotação)
- um `config.json` baseado em `config.example.json`

```json
{
  "service_account_file": "index-blogger-01-01be6f0eb763.json",
  "sitemaps": [
    "https://seublog1.com/sitemap.xml",
    "https://seublog2.com/sitemap.xml"
  ],
  "state_file": "state.json",
  "daily_quota": 190,
  "resubmit_after_days": 7
}
```

- `sitemaps`: liste quantos blogs quiser. Se um sitemap for do tipo
  "sitemap-index" (aponta para outros sitemaps), o script segue
  automaticamente.
- `daily_quota`: a cota padrão da Indexing API é 200 requisições/dia por
  projeto; deixei uma margem de segurança em 190.
- `resubmit_after_days`: evita reenviar a mesma URL toda hora — só reenvia
  se já passaram N dias desde o último envio (útil pra post editado).

## 3. Testar

```bash
python3 indexer.py --config config.json --dry-run
```

Isso mostra quais URLs seriam enviadas, sem gastar cota de verdade.

Quando estiver ok, rode de verdade:

```bash
python3 indexer.py --config config.json
```

## 4. Agendar de hora em hora

### Opção A — cron (servidor/VPS/Raspberry Pi próprio)

```bash
crontab -e
```

Adicione:

```
0 * * * * cd /caminho/completo/gsc-auto-indexer && /usr/bin/python3 indexer.py --config config.json >> cron.log 2>&1
```

### Opção B — GitHub Actions (sem precisar de servidor) ✅ já configurado

Este pacote já vem com `.github/workflows/indexer.yml` pronto. Ele roda a
cada hora e **commita o `state.json` atualizado de volta no repositório**,
assim o histórico de URLs já enviadas persiste entre execuções (nada de
artifact temporário que expira).

Passo a passo:

1. **Crie um repositório novo no GitHub e deixe-o PRIVADO** (o `config.json`
   com os sitemaps não é segredo, mas mantenha privado por boa prática).

2. Suba estes arquivos para o repositório:
   - `indexer.py`
   - `requirements.txt`
   - `config.json` (já editado com seus sitemaps reais — veja abaixo)
   - `state.json` (vazio, `{"submitted": {}}`)
   - `.gitignore` (garante que `sa.json` nunca seja commitado por acidente)
   - `.github/workflows/indexer.yml`

   ```bash
   git init
   git add .
   git commit -m "setup gsc auto indexer"
   git branch -M main
   git remote add origin https://github.com/SEU_USUARIO/SEU_REPO.git
   git push -u origin main
   ```

3. Edite `config.json` e troque as URLs de exemplo pelos sitemaps reais dos
   seus blogs (o `service_account_file` já está como `"sa.json"`, não mude).

4. **Adicione o secret com a chave do service account (em base64, não o JSON cru):**

   Colar o JSON diretamente costuma quebrar por causa de aspas curvas
   (“ ”) inseridas por alguns editores/navegadores ao colar. Para evitar
   isso, converta o arquivo para base64 (uma única linha, sem caracteres
   especiais) e cole esse texto no secret.

   **No Windows (PowerShell):**
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\caminho\para\sa.json")) | Set-Clipboard
   ```
   Isso já copia o base64 pra área de transferência — é só colar direto no
   campo do secret.

   **No Mac:**
   ```bash
   base64 -i sa.json | pbcopy
   ```

   **No Linux:**
   ```bash
   base64 -w0 sa.json | xclip -selection clipboard
   # ou, se nao tiver xclip:
   base64 -w0 sa.json
   # (copie manualmente a saida, sem quebrar linhas)
   ```

   Depois:
   - No GitHub: **Settings → Secrets and variables → Actions → New repository
     secret**
   - Nome: `GSC_SERVICE_ACCOUNT_JSON_B64`
   - Valor: cole o texto em base64 copiado acima (use a **chave nova**, já
     que a antiga foi exposta neste chat e deve ser revogada)

5. Vá em **Actions** no seu repositório, escolha o workflow "GSC Auto
   Indexer" e clique em **Run workflow** para testar manualmente uma vez.
   Depois disso ele passa a rodar sozinho a cada hora (`cron: "0 * * * *"`,
   horário UTC).

6. Acompanhe os logs em **Actions → GSC Auto Indexer → (execução) → index**.
   Cada execução também deixa um commit automático `chore: atualiza
   state.json` sempre que envia URLs novas.

> O agendamento do GitHub Actions é "best effort": em cargas altas o GitHub
> pode atrasar alguns minutos a execução do cron. Para posts de blog isso é
> irrelevante na prática.

### Opção C — Google Cloud Scheduler + Cloud Function

Se preferir tudo dentro do ecossistema Google (mesmo projeto do service
account), dá pra empacotar `indexer.py` como Cloud Function/Cloud Run e
disparar via Cloud Scheduler a cada hora. Posso montar esse pacote também,
se for a rota que você quer seguir.

## 5. Arquivos

- `indexer.py` — script principal
- `config.example.json` — modelo de configuração (copie para `config.json`)
- `requirements.txt` — dependências Python
- `state.json` — gerado automaticamente, guarda histórico de URLs enviadas
