# ai-usage e ai-usage-monitor

Quanto de cada assinatura já foi usado (sessão de 5h, semana), no terminal ou num histórico no navegador.

- **`ai-usage [conta ...] [--json]`**: o retrato de agora. Contas: `claude`, `claude2` (toda `~/.claude*`
  com credencial), `codex`, `agy`, `openrouter`.
- **`ai-usage-monitor`** (opcional): coleta as contas do config a cada N segundos, grava em SQLite e
  serve a página com o histórico em `http://127.0.0.1:49381/`.

## Ligar o monitor

```sh
ai-usage-monitor install   # cria ~/.config/ai-usage/config.toml (se faltar) e liga o serviço systemd de usuário
```

O `install.sh` não liga nada: o monitor só existe em quem roda o comando acima. Depois de mudar o config:
`systemctl --user restart ai-usage-monitor`. Para desligar: `systemctl --user disable --now ai-usage-monitor`.

## nginx

Opcional, para abrir em `http://ai-usage.local/` em vez da porta. O vhost é [`usage/nginx.conf`](../usage/nginx.conf):

```sh
sudo ln -s ~/.ai-setup/usage/nginx.conf /etc/nginx/sites-available/ai-usage.local
sudo ln -s /etc/nginx/sites-available/ai-usage.local /etc/nginx/sites-enabled/
echo '127.0.0.1 ai-usage.local' | sudo tee -a /etc/hosts
sudo nginx -t && sudo systemctl reload nginx
```

Só responde a quem está na própria máquina (`allow 127.0.0.1; deny all`) e reescreve o `Host` para `127.0.0.1:49381`, o único que o servidor aceita.
Se mudar `port` no config, mude também no vhost.

## Config

`~/.config/ai-usage/config.toml` (modelo comentado: [`usage/config.example.toml`](../usage/config.example.toml)):

| Chave | O que faz |
|---|---|
| `interval_seconds` | de quantos em quantos segundos coletar (mínimo 30, padrão 300) |
| `db` | caminho do SQLite (padrão `~/.local/share/ai-usage/usage.db`) |
| `port` | porta da página, só em `127.0.0.1` |
| `[accounts.<nome>]` | uma conta; `type` = `claude` (com `config_dir`), `codex`, `agy` ou `openrouter` |

## Comandos

```sh
ai-usage-monitor collect   # uma coleta agora
ai-usage-monitor run       # coleta no intervalo + página (o que o serviço roda)
ai-usage-monitor serve     # só a página
ai-usage-monitor --config outro.toml run
```

## Dados

Tabela `samples`: uma linha por janela de uso por coleta (`ts` epoch, `account`, `plan`, `window`,
`used` em %, `resets_at` ISO). Uma conta que falhou (token expirado, CLI ausente) vira uma linha com
`error`, e a página mostra o erro na tabela "Agora".

A página filtra por conta, janela e intervalo de datas. As séries se distinguem por traço e marcador, não
só por cor; acima de 80% o valor ganha "!".

## Novo harness

Uma função de coleta em `usage/collectors.py` que devolve `{"plan", "rows": [{"label", "used", "resets_at"}], "notes"}`
e uma entrada no dicionário `TYPES`. O Kiro ainda não tem: falta achar de onde ler a quota dele.

## Testes

```sh
python3 -m unittest discover -s usage/tests -t usage   # da raiz do ai-setup
```
