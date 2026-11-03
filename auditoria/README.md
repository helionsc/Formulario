# Conferência do saldo bruto e da virada diária

Revisão de 3 de novembro de 2026. A alteração visual acrescenta o saldo bruto abaixo do líquido, em 11 px. O valor soma os saldos brutos das aplicações consideradas no total da carteira e acompanha o botão de ocultar valores.

## Resultado

Os 112 testes passaram com carteiras fictícias e sem conexão com a carteira de qualquer usuário. Para repetir a conferência na raiz do repositório, execute:

```sh
node conferencia-virada.mjs
```

O comando também executa `testes.mjs`, `conferencia-rendimento.mjs` e `conferencia-liquido.mjs`. Não exige instalação de pacotes.

Foram conferidos saldo bruto, provisão de IR e IOF, líquido por banco, arredondamento em centavos, aportes, resgates, vencimentos e histórico. As novas verificações incluem uma sequência de nove dias com taxas diferentes, a meia-noite local em UTC−3, o feriado de Finados, a carteira vazia e duas séries históricas oficiais de CDI.

O indicador diário usa o dia anterior do calendário: terça mostra segunda; sábado mostra sexta; domingo mostra sábado zerado; segunda mostra domingo zerado. Um feriado no dia de referência também produz zero, com identificação. Não se repete o último rendimento positivo no fim de semana.

Na configuração padrão, o saldo acumula somente dias encerrados. A opção já existente de contar o dia atual acrescenta uma estimativa ao saldo, sem antecipar o histórico diário.

## Dados usados

Os arquivos JSON desta pasta preservam respostas públicas da série 12 do Banco Central, consultadas em 3 de novembro de 2026. Nenhum contém dados financeiros pessoais.

- [CDI diário de 19 a 27/10/2026](https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial=19/10/2026&dataFinal=27/10/2026): R$ 10.000 fictícios a 102% do CDI resultam em R$ 10.036,32 brutos no dia seguinte ao último dia do período.
- [CDI diário de 22/12/2025 a 05/01/2026](https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial=22/12/2025&dataFinal=05/01/2026): o mesmo capital e percentual resultam em R$ 10.050,72 brutos. O teste atravessa Natal, Ano Novo e fins de semana, usando a presença de taxa na série oficial como referência independente.
- [Tabela de renda fixa da Receita Federal para 2026](https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda/tabelas/2026).

## Alcance da conferência

Os testes confirmam a aritmética e a regra de datas dos cenários verificados; não representam conciliação com extratos bancários. Sem taxa publicada, o aplicativo identifica a estimativa. Poupança e IPCA utilizam modelos aproximados; Tesouro não reproduz integralmente preços de mercado, custos e condições de resgate.

O diário provisiona IR e IOF sobre o ganho novo de cada dia, considerando o prazo em D+1. A redução de impostos sobre ganhos antigos pode aumentar o saldo líquido, inclusive no fim de semana, sem constituir rendimento novo. Assim, a soma do diário líquido pode diferir do saldo líquido menos o capital aplicado. Os impostos são efetivamente retidos conforme o evento de resgate ou vencimento.
