# Login real por código

O servidor aceita Supabase Auth no modo `--auth supabase`, agora padrão. O fluxo local foi implementado: pedir o código, verificar pelo serviço, confirmar a identidade autenticada e só então vincular a carteira ao ID do usuário. A primeira confirmação cria uma conta local vinculada; as próximas recuperam a mesma carteira.

## Situação da configuração

O projeto `carteira-renda-fixa` foi reativado e está saudável. As configurações públicas foram consultadas: login por e-mail habilitado, criação de conta permitida e confirmação de e-mail obrigatória (`mailer_autoconfirm=false`). A URL e uma chave pública habilitada foram obtidas pela conexão Supabase e gravadas somente em `.env.local`, ignorado pelo Git e com permissão 600. Não foi usada chave administrativa.

O titular configurou o SMTP da Brevo diretamente no Supabase. Os modelos de cadastro e login foram salvos com o código numérico, e o provedor de e-mail foi ajustado para seis dígitos e 300 segundos. Em 04/11/2026, o primeiro acesso com e-mail real confirmou a entrega do código, a criação da conta na prévia e a abertura da sessão. O retorno à mesma conta com um novo código ainda precisa de um teste real.

A sessão local permanece no mesmo navegador e tem seu prazo de 30 dias renovado com o uso. Sair revoga a sessão imediatamente. Os 47 testes locais passaram, incluindo a renovação de uma sessão existente, a rejeição de códigos inválidos e o isolamento das carteiras.

## Configuração e teste

1. Concluir o cadastro gratuito na Brevo, verificar o e-mail e criar um remetente verificado chamado **Finace**. Se houver domínio próprio, autenticá-lo; caso contrário, conferir as condições de remetente da conta antes do teste.
2. Obter em Brevo → SMTP as credenciais de SMTP. Usar a chave **SMTP**, não a chave de API. Configurar diretamente no painel Supabase, sem enviar segredos à conversa ou colocá-los em arquivos do app:
   - Host: `smtp-relay.brevo.com`.
   - Porta: `587`.
   - Usuário: o login SMTP exibido pela Brevo.
   - Senha: a chave SMTP gerada pelo titular.
   - Nome do remetente: `Finace`.
   - E-mail do remetente: o endereço verificado na Brevo.
3. Em Supabase → Authentication → Emails, configurar **Confirm sign up** e **Magic link or OTP** com o assunto **Seu código de acesso ao Finace** e o corpo de `email-codigo.html`. Ambos precisam da variável `{{ .Token }}` para que uma conta nova também receba o código numérico.
4. Em Authentication → Sign In / Providers → Email, ajustar Email OTP length para 6 e Email OTP expiration para 300 segundos. Manter confirmação obrigatória.
5. Somente após validar o SMTP e os modelos, definir `FINACE_EMAIL_OTP_READY=true` no `.env.local` e reiniciar o servidor. Esse bloqueio impede enviar um link padrão que não atende ao fluxo de código.
6. Digitar um e-mail real na prévia, pedir o código e confirmá-lo diretamente no app. Não enviar o código à conversa. Verificar uma nova conta e um novo login na mesma conta, com a carteira preservada.

Referências: [Supabase OTP](https://supabase.com/docs/guides/auth/auth-email-passwordless), [SMTP do Supabase](https://supabase.com/docs/guides/auth/auth-smtp), [SMTP da Brevo](https://help.brevo.com/hc/en-us/articles/7924908994450-Send-transactional-emails-using-Brevo-SMTP), [remetente verificado](https://help.brevo.com/hc/en-us/articles/208836149-Create-a-new-sender-From-name-and-From-email).

## Executar e testar

```sh
PYTHONPYCACHEPREFIX=/private/tmp/finace-proto-pycache python3 prototipos/contas-finace/server.py --port 8768 --auth supabase
```

O modo fictício continua disponível separadamente com `--auth demo`, por exemplo em outra porta. O modo real usa `dados-locais/auth-real.sqlite3`, o fictício usa `dados-locais/teste.sqlite3`; os cookies também são diferentes. Não existe troca de modo por um parâmetro enviado pelo navegador.

```sh
PYTHONPYCACHEPREFIX=/private/tmp/finace-proto-pycache python3 -m unittest discover -s prototipos/contas-finace -p 'test_*.py' -q
node prototipos/contas-finace/verificar_app.mjs
```

As verificações automatizadas do provedor simulam o envio. O teste com um endereço real confirma a entrega na caixa de entrada e o acesso à carteira.

## Limites desta etapa

O GitHub não foi atualizado. O teste real usa o serviço de identidade do projeto existente, mas não acessa nem migra suas tabelas financeiras. A carteira financeira continua no banco local da prévia. A exclusão integral da conta real no provedor ainda não foi conectada; a interface não oferece uma exclusão parcial enganosa. Os demais requisitos de produção estão em `plano-producao.md`.
