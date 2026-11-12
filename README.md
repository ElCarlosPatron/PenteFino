# Pente Fino 3.2 — Contagem final em equipe (celular)

Aplicativo web Flask + SQLite para dividir SKUs de um CSV Comptar entre celulares, conferir fisicamente, salvar correções e exportar ajustes e um relatório PDF auditável.

## Atualizar sem perder os dados

1. **Feche o servidor anterior** (`Ctrl + C` no terminal em que ele está rodando).
2. **Faça backup da pasta inteira do projeto**, principalmente `data/` (banco de contagens e segredo do servidor). Não compartilhe nem publique essa pasta.
3. Extraia o ZIP e **copie os arquivos da pasta `PenteFino_AppWeb` sobre os arquivos do projeto atual**, substituindo `app.py`, `core.py`, `requirements.txt`, `templates/`, `static/` e incluindo o novo `reports.py`. **Não apague** `.venv/` nem `data/`.
4. No VS Code, abra `C:\Users\Wellington\Documents\PenteFino_AppWeb` e execute:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. Inicie o servidor em rede local:

```powershell
.\.venv\Scripts\waitress-serve.exe --listen=0.0.0.0:5050 app:app
```

6. No computador, abra **http://localhost:5050** (não `0.0.0.0`). Nos celulares da mesma rede Wi-Fi, acesse `http://IP_DO_COMPUTADOR:5050`, usando o IP mostrado em `ipconfig` (por exemplo `192.168.1.20`). Mantenha o computador e o terminal ligados durante a contagem.

> O app adiciona automaticamente ao banco antigo os campos e registros de auditoria necessários na primeira execução, inclusive as informações originais de Saldo/C1/C.Dif para o filtro de produtos não encontrados. Os SKUs que já haviam sido conferidos permanecem salvos; registros anteriores à atualização podem não ter nome/hora históricos detalhados. Faça backup antes de atualizar.

## Como funciona

1. Responsável importa um CSV do Comptar (`;`, com `Codigo`, `Descricao`, `Final`, etc.), informa loja, escolhe **Dividir celulares** e cria a contagem.
2. Operadores entram com o código da contagem, seu nome e a posição **Celular 1, 2, 3...**. Cada celular vê apenas os SKUs atribuídos a ele.
3. A quantidade **CONT.FINAL** inicia com o valor da coluna **Final** do Comptar. Ao tocar **Salvar e próximo**, o app registra a conferência física, o operador e a data/hora. Não há marcação de caixinha.
4. É possível **Voltar ao SKU anterior**, ir ao próximo SKU, **buscar por código, descrição ou local**, filtrar SKUs **Conferidos / Não conferidos / Sem localização (não encontrados)** e editar qualquer quantidade já salva antes de finalizar. O filtro **Sem localização** identifica produtos com **Saldo > 0, C1 = 0 e C.Dif = 0** no CSV do Comptar, mesmo em contagens antigas: os campos são recuperados automaticamente do arquivo original armazenado no banco.
5. **Filtro persistente no celular:** ao escolher Não conferidos, Conferidos ou Sem localização, tocar em qualquer SKU abre sua ficha sem perder o filtro. **SKU anterior**, **Próximo SKU** e **Salvar e próximo** seguem a sequência dos resultados filtrados (inclusive quando há busca por código/descrição). O filtro continua ativo até usar **Limpar** ou selecionar outro. No filtro **Não conferidos**, um SKU salvo deixa de ser pendente, e o app avança para o próximo pendente. Se não houver próximo, mostra os resultados do filtro em vez de abrir um SKU de outra categoria.
6. O operador pode tocar **FINALIZAR PENTE FINO** mesmo com pendências. O sistema mostra **quantos SKUs faltam** e pede confirmação explícita. Os pendentes manterão o `Final` original, e o relatório mostrará **“Finalizado antes de conferir”**. A porcentagem continuará refletindo só o que foi conferido.
7. Somente quando **todos os celulares** tiverem finalizado (100% ou antecipadamente) o responsável poderá baixar os arquivos. Se precisar corrigir, pode **Reabrir parte**.

## Exportações (somente pelo responsável)

- **CSV de ajustes**: separado por **ponto e vírgula (`;`)**, codificado em UTF-8 com BOM, com exatamente quatro colunas: `COD;DESC;QUANTIDADE;STATUS`. Para itens conferidos, a quantidade será a última salva; para itens não conferidos, será **o valor original `Final` do Comptar** (não zero, não vazio) e o `STATUS` será **Finalizado antes de conferir**.
- **PDF padronizado**: identificação da loja e arquivo, números gerais, cada celular, operador, início/finalização, quantos SKUs foram conferidos, último SKU salvo, histórico de acessos/trocas e listagem de produtos com situação e quantidade.
- **CSV dos operadores**: separado por **ponto e vírgula (`;`)**, com cabeçalhos por coluna (celular, operador, entrada, finalização, quantidade conferida, faltantes, último SKU e situação). Datas aparecem no formato `DD/MM/AAAA HH:MM:SS`. Ambos os arquivos têm UTF-8 com BOM para acentuação no Excel brasileiro. Se o Excel de outro idioma não reconhecer as colunas automaticamente, use Dados > De Texto/CSV e escolha o delimitador ponto e vírgula.

**Importante:** o app gera os arquivos para download. Não envia e-mail automaticamente. O CSV novo de ajustes **não tem o mesmo formato de importação do Comptar**: ele foi simplificado conforme o pedido para uso pelo responsável. Antes de importar em outro sistema, confirme as colunas exigidas por esse sistema.

## Dados, segurança e implantação

- Banco SQLite: `data/pente_fino.sqlite3`. É único para todos os celulares conectados ao mesmo servidor; não execute cópias independentes do app em vários computadores.
- A identificação é por nome informado + sessão do navegador, **não é autenticação corporativa**. Execute apenas numa **rede local privada e confiável**, não publique na internet sem autenticação, HTTPS, backups e proteção contra CSRF.
- Os links de recuperação do responsável contêm um token privado; guarde-os com segurança.
- Liberação de um celular pelo administrador mantém os SKUs conferidos e as ações históricas de operadores anteriores.
- A atualização não apaga `data/` e `.venv/`. O `.gitignore` evita incluir banco, arquivos de estoque e credenciais no GitHub.
- Testes automatizados: `python -m unittest discover -s tests -v` (com dependências instaladas).

Projeto GitHub: https://github.com/ElCarlosPatron/PenteFino


## Publicação no Render + Neon

Veja `DEPLOY_RENDER_NEON.md`.
