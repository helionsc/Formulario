# Passagem do protótipo para o serviço público

Nenhum passo deste documento foi executado no projeto Supabase ou no GitHub. O protótipo valida a experiência; a produção continua dependendo da configuração e dos testes de infraestrutura.

## Autenticação e isolamento

Usar Supabase Auth com código de confirmação por e-mail, envio real configurado e limites contra abuso. O código só aparece no e-mail do usuário; a caixa de entrada simulada deve ser removida. Os tokens devem ser gerenciados por um cliente apropriado à plataforma, com armazenamento protegido no iOS.

Cada carteira terá proprietário vinculado ao usuário autenticado. Participantes e convites terão tabelas próprias, permissões explícitas e expiração. Habilitar RLS em todas as tabelas expostas e conferir concessões de acesso. As políticas devem consultar o usuário autenticado e a participação na carteira, sem confiar em `x-carteira` ou em filtros enviados pelo navegador. Uma pessoa não deve poder atribuir a si mesma propriedade ou participação por uma chamada direta.

Convites, aceitação, revogação e exclusão de conta precisam de operações transacionais no servidor. Contas A e B, usuário desconectado e participante revogado devem ser testados também pela API direta, incluindo carteiras, posições antigas, históricos, versões, membros e convites. Revisar a segurança das tabelas já existentes antes de liberar novas contas.

Referências: [Supabase Auth por e-mail](https://supabase.com/docs/guides/auth/auth-email-passwordless), [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [segurança em produção](https://supabase.com/docs/guides/security/production-checklist).

## Migração sem perda

Manter a versão antiga funcionando enquanto o novo fluxo é validado em ambiente separado. Exportar uma cópia independente antes de qualquer migração. O JSON é o caminho inicial de migração oferecido nesta prévia: o usuário entra, seleciona a carteira de destino e revisa antes de importar. Preservar IDs, aportes, resgates, histórico diário e premissas, com conferência de quantidades e valores após a restauração.

Para uma futura migração automática de carteiras já na nuvem, implementar uma vinculação única, transacional e auditável. A posse de um link antigo não equivale a uma conta verificada: é necessário definir como comprovar o controle legítimo da carteira, impedir reivindicação por uma segunda conta e encerrar o mecanismo antigo após a migração. Não atribuir proprietários automaticamente com base em um e-mail enviado pelo cliente. Essa estratégia depende da auditoria do banco real e não foi implementada nesta prévia.

## Recuperação

Definir uma rotina de backup independente do banco e uma retenção compatível com o serviço. Testar a restauração em ambiente separado, com verificação de carteiras, histórico e permissões. Versões no mesmo banco ajudam a desfazer uma edição, mas não protegem contra a perda do próprio banco. Documentar como exclusão de contas e retenção de backups se relacionam, incluindo o que acontece após restaurar um backup antigo.

## iOS e publicação

Preparar a versão iOS com armazenamento protegido, comportamento sem conexão definido, biometria adequada e testes em aparelhos. Finalizar a política de privacidade com os dados e fornecedores reais, a declaração de privacidade no App Store Connect e a exclusão de conta. Oferecer acesso de demonstração à análise da Apple e revisar a experiência conforme as regras da loja; a aprovação não é garantida por este protótipo.

Referências: [privacidade da App Store](https://developer.apple.com/app-store/app-privacy-details/), [exclusão de conta](https://developer.apple.com/help/app-review/guideline-reference/5-1-1-account-deletion/), [diretrizes de análise](https://developer.apple.com/app-store/review/guidelines/).
