# Finace — protótipo local de contas

Criado em 3 de novembro de 2026 para validar o fluxo antes de alterar o GitHub. O app publicado e o projeto Supabase em uso não foram modificados.

O login por e-mail já foi validado no modo local. A [prévia com carteira na nuvem](PREVIA-NUVEM.md) combina esse fluxo com o armazenamento de teste por conta no Supabase. As instruções de contas `.test` abaixo descrevem o modo fictício, iniciado com `--auth demo`.

## Abrir

Com o servidor ativo, acesse **http://127.0.0.1:8768/** neste computador. O endereço de loopback não abre este servidor em outro celular.

Para iniciar novamente, a partir da pasta Acompanhamento Financeiro:

```sh
python3 prototipos/contas-finace/build.py
PYTHONPYCACHEPREFIX=/private/tmp/finace-proto-pycache python3 prototipos/contas-finace/server.py --port 8768 --auth demo
```

Usa somente Python e Node já instalados, sem pacotes adicionais. O arquivo `web/app.html` é gerado a partir do index aprovado, com adaptações isoladas para o servidor local. Não abra esse arquivo diretamente; o servidor precisa fornecer a conta autenticada. O script de geração não modifica o index original.

## Como testar

1. Escolha **Ana** ou **Bruno**, clique em **Usar código de teste** e depois **Entrar na carteira**. Inicialmente, Ana tem R$ 18 mil aplicados e Bruno R$ 6 mil, em dados fictícios.
2. Use **Conta**, no alto da carteira, para gerenciar acesso e backups. Uma conta terminada em `.test` que ainda não exista cria uma carteira vazia.
3. Na conta Ana, convide `bruno@finace.test`. Saia, entre como Bruno, abra Conta e aceite o convite. Escolha entre a carteira pessoal e a compartilhada. A conta proprietária pode revogar o acesso.
4. Na carteira, toque em **Simular offline**, edite uma aplicação e toque em **Reconectar**. A saída e a troca de carteira são bloqueadas enquanto houver alterações pendentes.
5. Em Dados e backup, importe um JSON fictício. A revisão informa conta, aplicações, dias de histórico e substituição da carteira selecionada. Cancelar não altera os dados. A importação confirmada preserva uma cópia local anterior e uma versão do servidor.
6. Em Conta, use **Restaurar** para recuperar uma versão anterior. O estado substituído também é guardado. A lista mostra as cinco versões mais recentes; o servidor conserva até 20. A exportação JSON continua disponível no aplicativo.
7. A exclusão da conta de teste exige um novo código e digitar **EXCLUIR**. Carteiras próprias, versões, convites, participações e sessões são apagados; carteiras pertencentes a outros usuários continuam existindo.

## O que é real neste protótipo

- Servidor local com banco SQLite persistente e autorização em cada leitura e alteração.
- Sessões com token aleatório, token armazenado por hash no servidor, cookie HttpOnly/SameSite, expiração, proteção contra solicitações de outra origem e CSRF.
- Código de uso único com expiração, limite de tentativas e limitação de solicitações. A caixa de entrada é **simulada** e exibe o código para facilitar o teste; não valida um e-mail real.
- Propriedade das carteiras definida no servidor. Saber o UUID, trocar um filtro ou forjar o cabeçalho da carteira não concede acesso.
- Convites vinculados ao destinatário, aceitação explícita e revogação pelo proprietário.
- Comparação de revisões em uma transação para impedir sobrescrita silenciosa entre aparelhos.
- Cache separado por usuário e carteira. Ao sair pela interface, a prévia limpa seus caches do navegador.
- Backup JSON compatível com o formato anterior, revisão antes de importar e versões recuperáveis.

## Limites deliberados

Esta é uma demonstração funcional local, **não uma implementação de Supabase Auth/RLS já instalada**. Nenhum e-mail real é enviado e nenhuma conexão externa é feita. O CSP restringe conexões à própria origem. O arquivo servido não contém a URL ou a chave do Supabase de produção. Os códigos mostrados na tela e o servidor HTTP de teste não devem ser usados em uma versão pública.

O banco fica em `dados-locais/teste.sqlite3`; ele e os caches não têm criptografia própria. Use somente dados fictícios. A simulação offline exercita edições e sincronização de uma tela já carregada; não implementa instalação PWA ou abertura totalmente offline. Revogar acesso impede novas consultas ao servidor e retira a carteira da interface ativa; não apaga cópias que o participante já tenha exportado.

As versões anteriores ficam no mesmo banco. Não substituem backups independentes. A exclusão de conta elimina também essas versões locais da carteira própria. Uma configuração real de retenção e restauração do serviço ainda precisa ser definida.

O bloqueio biométrico foi desativado nesta prévia, para não registrar credenciais reais de teste. O armazenamento protegido e a integração biométrica do iOS serão parte da versão distribuível. As taxas do protótipo são fictícias e estão identificadas na tela. As fórmulas financeiras e a regra de histórico por dia encerrado são as mesmas do index aprovado; os modelos aproximados de produtos continuam com os limites já documentados na auditoria original.

## Conferência

```sh
PYTHONPYCACHEPREFIX=/private/tmp/finace-proto-pycache python3 -m unittest discover -s prototipos/contas-finace -p 'test_server.py' -v
node prototipos/contas-finace/verificar_app.mjs
```

**164 verificações passaram:** 28 testes HTTP do servidor, 130 verificações anteriores executadas sobre a cópia do protótipo e 6 verificações novas de importação, cache e preservação das fórmulas. O adaptador de testes ajusta apenas o transporte local, a API de leitura de arquivos e a confirmação da importação; não substitui os cálculos. Os testes HTTP usam outro banco temporário, separado do banco da prévia.

No navegador foram verificados login e saída, carteiras diferentes, convite e aceite, revogação, edição offline com bloqueio de saída, reconexão e recarregamento, importação confirmada e recuperação da carteira por uma versão anterior. A tela de conta foi conferida em larguras de 320 e 390 px sem rolagem horizontal. As capturas `previa-*.png` são capturas reais da prévia; não são imagens do app publicado.

## Próxima etapa

Ver [plano-producao.md](plano-producao.md). A aprovação visual desta prévia, por si só, não implanta a infraestrutura nem publica o protótipo no GitHub.
