# Pente Fino 3.3 — Publicação na internet (Render + Neon)

## Antes de publicar

- Não inclua a pasta `data`, `.env`, `.venv`, arquivos CSV do Comptar ou senhas no GitHub.
- Esta edição aceita **SQLite local** e **PostgreSQL Neon online** automaticamente.
- O código já usa o `SECRET_KEY` fornecido no Render para manter as sessões após reinícios.
- Os dados do SQLite local **não são migrados automaticamente** para o Neon. Abra uma nova contagem para testar a versão online.
- Configure os controles de acesso e confirme a política de uso dos dados corporativos antes de disponibilizá-lo para operadores.

## 1 — Neon (https://console.neon.tech)

1. Faça login; crie um projeto chamado `pentefino` no plano **Free**.
2. Vá ao painel do projeto e abra **Connect** / **Connection Details**.
3. Copie a **connection string PostgreSQL** completa, com `sslmode=require` (preferencialmente a versão pooled).
4. **Nunca cole a senha nem a conexão completa no GitHub ou em conversas.** Só usaremos no painel de variáveis privadas do Render.

## 2 — GitHub

1. Extraia o ZIP. Abra a pasta `PenteFino_AppWeb` no VS Code.
2. Copie os arquivos de código para a pasta do clone do repositório `ElCarlosPatron/PenteFino`.
3. Não copie a pasta `data` ou `.venv` para o repositório.
4. No terminal dentro do repositório:

```powershell
git status
git add .
git commit -m "Versao online Pente Fino com PostgreSQL Neon"
git push origin main
```

> Se `git push` falhar, confira `git remote -v` e o branch atual em `git branch --show-current`. O repositório precisa estar clonado/autenticado no VS Code.

## 3 — Render (https://dashboard.render.com)

1. Clique **New > Web Service**.
2. Conecte o GitHub e escolha o repositório `ElCarlosPatron/PenteFino`.
3. Selecione linguagem `Python 3`, branch `main`, plano `Free` e a raiz onde `app.py` está.
4. Em Build Command, use `pip install -r requirements.txt`.
5. Em Start Command, use `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 app:app`.
6. Em **Environment**, adicione (segredos):
   - `DATABASE_URL` = connection string do Neon.
   - `SECRET_KEY` = chave aleatória com no mínimo 32 caracteres. Gere localmente com `py -c "import secrets; print(secrets.token_hex(32))"`.
7. Mantenha `PYTHON_VERSION=3.12` via arquivo `.python-version` incluído.
8. Clique para criar/deploy; quando terminar, abra a URL `https://SEU-SERVICO.onrender.com`.

> O aplicativo falha intencionalmente ao iniciar no Render se não houver `DATABASE_URL` e `SECRET_KEY`, para evitar perda de dados acidental.

## 4 — Teste de ponta a ponta

1. Abra a URL pública pelo computador e crie uma contagem com o CSV do Comptar.
2. Guarde em lugar privado o **link de recuperação do responsável**.
3. Em outro aparelho/rede, abra o link de operadores e assuma o celular 1.
4. Faça a contagem de um SKU e confirme, em outro aparelho, que o progresso foi atualizado.
5. Finalize os celulares e valide o CSV/PDF.
6. Faça um **redeploy** no Render e confirme se os dados continuam (estão no Neon).

## Gratuidade e limitações

- Render Free suspende instâncias inativas após 15 minutos. O primeiro acesso pode ser lento.
- Render Free não oferece armazenamento local persistente. É por isso que Neon é obrigatório online.
- Neon Free tem limites de capacidade, armazenamento e tráfego.
- Serviços gratuitos são recomendados para piloto, não são promessa de disponibilidade de operação crítica.
- Mantenha cópias seguras dos relatórios de contagem e das informações essenciais.
