# Prévia de carteira na nuvem

O modo de teste usa o login por código e uma carteira pessoal por conta. As tabelas `finace_previa_carteiras` e `finace_previa_versoes` são separadas das carteiras em uso. As políticas do Supabase usam o ID autenticado para permitir leitura e alteração apenas pelo proprietário. O código por e-mail e a sessão do navegador continuam como na prévia de login.

## Abrir e testar

Configure `.env.local` a partir de `.env.example` com a URL e a chave pública do projeto de teste. O projeto precisa ter os dois modelos de e-mail por código, o envio configurado e a migração `carteiras-previa.sql` aplicada uma vez. A partir da raiz do repositório, execute:

```sh
python3 prototipos/contas-finace/build.py
python3 prototipos/contas-finace/server.py --port 8770 --cloud-wallet
```

1. Abra http://127.0.0.1:8770/ e entre com um e-mail real. A primeira entrada cria uma carteira de teste vazia.
2. Na área **Conta**, baixe o JSON fictício e escolha **Importar JSON**. Confirme a conta de destino na revisão e verifique as aplicações.
3. Em outro perfil de navegador neste computador, abra a mesma prévia e confirme o mesmo e-mail. A carteira já gravada deve aparecer. Em outra conta, aparece uma carteira independente.
4. Volte para **Conta** para exportar o JSON ou consultar e restaurar uma versão anterior.

O endereço atual abre neste computador. A hospedagem HTTPS da interface para o teste em celulares é uma etapa separada. Use o exemplo fictício na prévia, que trabalha com taxas simuladas. O compartilhamento de carteira e a exclusão da identidade estão fora do teste de carteira pessoal.

As credenciais de sessão são mantidas em um diretório local privado e nunca vão para o navegador. Cada gravação compara a revisão atual da carteira e o banco guarda até 20 versões. Os dados de sessão e o arquivo `.env.local` devem ficar fora do Git.
