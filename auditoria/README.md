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

## Backup JSON no celular

Os botões de exportação e restauração continuavam no código, mas ficavam abaixo das configurações em um painel que bloqueava a rolagem por toque. A correção coloca **Exportar JSON** e **Importar JSON** no início de Dados e backup, permite rolar o conteúdo e limita o gesto de fechar à alça superior. O arquivo continua compatível com o formato anterior.

Para executar também as verificações de backup:

```sh
node conferencia-backup.mjs
```

Os 119 testes passaram. No navegador, foi baixado um JSON com duas aplicações fictícias e cinco dias de histórico, importado em uma carteira vazia de outra origem local e reaberto com os dados preservados. Ambos os ambientes estavam sem acesso à nuvem. Os testes também verificam a aceitação do formato antigo e a rejeição de arquivos malformados, aplicações inválidas e arquivos grandes demais.

## Menu branco em vidro com tamanho adaptável

A navegação inferior usa uma cápsula branca translúcida, com desfoque, destaque da seção ativa e espaço para a área segura do celular. Ao descer a página, a barra se estreita e recolhe as legendas; ao subir, volta ao tamanho completo. Pequenos movimentos e o elástico no início ou no fim da página não alternam o tamanho. Tocar no menu também o expande. Os botões conservam seus nomes para leitores de tela.

Foram conferidas telas de 320 e 390 px de largura, sem rolagem horizontal e com áreas de toque de pelo menos 48 px no modo compacto. Aplicar e Dados continuam acessíveis; Exportar JSON e Importar JSON aparecem no início do painel. Há alternativas sem transparência e com menos animação conforme as preferências do aparelho.

```sh
node conferencia-menu.mjs
```

Os 130 testes passaram. O JavaScript financeiro, de persistência e de backup permanece idêntico ao da versão anterior; as alterações de comportamento se limitam à navegação.

## Atalhos redondos e leitura inicial de três dias

Após aprovação da prévia, os atalhos do saldo mantêm círculos de 48 px, sem contorno branco, com preenchimento suave e ícones finos. O menu inferior recebeu um pouco mais de transparência e mantém o comportamento de reduzir ao descer e expandir ao subir.

A tela inicial apresenta os três últimos dias encerrados, incluindo fins de semana e feriados zerados. **Ver mais dias** abre o histórico completo; os registros anteriores continuam preservados. A conferência da prévia confirmou três linhas iniciais e cinco registros no histórico da carteira fictícia. Os cálculos financeiros e as funções de importar e exportar JSON não foram alterados.
