import assert from 'node:assert/strict';
import fs from 'node:fs';
import './conferencia-liquido.mjs';
import {ambiente,pos,idA,idB} from './testes.mjs';

const html=fs.readFileSync(new URL('./index.html',import.meta.url),'utf8');
const renderOriginal=html.match(/function render\(\)\{[\s\S]*?\n\}/)[0];
const cent=v=>Math.round((v+Number.EPSILON)*100);
const iof=[96,93,90,86,83,80,76,73,70,66,63,60,56,53,50,46,43,40,36,33,30,26,23,20,16,13,10,6,3];
const serie={'2026-10-19':.05,'2026-10-20':.04,'2026-10-21':.06,'2026-10-22':.045,'2026-10-23':.055,'2026-10-26':.052};
const carteira=[{...pos(idA,'Itaú Unibanco',10000),taxa:102,data:'2026-10-19'},
  {...pos(idB,'Banco Inter',8000),tipo:'LCI',taxa:95,data:'2026-10-19'}];
let casos=0;
function conferir(nome,fn){fn();casos++;console.log('✓ Virada/bruto: '+nome);}
function preparar(){
  const a=ambiente();a.set('carteira',carteira);
  // Taxas espúrias de fim de semana não devem gerar rendimento.
  a.set('CDI_MAP',{...serie,'2026-10-24':.9,'2026-10-25':1.5});
  a.run("CDI_VER++;CDI_DE='2026-10-19';CDI_ATE='2026-10-26';");
  a.run(renderOriginal);
  // Os gráficos não participam da apuração nem do cabeçalho em teste.
  a.run('listaPosicoes=()=>{};alocacao=()=>{};graficoHist=()=>{};graficoFut=()=>{};cartaoVencimentos=()=>{};');
  return a;
}
function oraculo(credito){
  const ontem=new Date(Date.parse(credito+'T12:00:00Z')-864e5).toISOString().slice(0,10);
  let bruto=0,liquido=0,diarioBruto=0,diarioLiquido=0;
  for(const p of carteira){
    let saldo=p.valor,ganhos=0,ganhosLiquidos=0,antesBruto=0,antesLiquido=0;
    for(const [ds,t] of Object.entries(serie)){
      if(ds>=credito)break;
      if(ds===ontem){antesBruto=ganhos;antesLiquido=ganhosLiquidos;}
      const g=saldo*t/100*p.taxa/100;
      saldo+=g;ganhos+=g;
      const prazo=Math.round((Date.parse(ds+'T12:00:00Z')-Date.parse(p.data+'T12:00:00Z'))/864e5)+1;
      ganhosLiquidos+=p.tipo==='LCI'?g:g*(1-iof[prazo-1]/100)*.775;
    }
    const dc=Math.round((Date.parse(credito+'T12:00:00Z')-Date.parse(p.data+'T12:00:00Z'))/864e5);
    const impostoIOF=p.tipo==='LCI'||dc<1||dc>=30?0:ganhos*iof[dc-1]/100;
    bruto+=saldo;
    liquido+=p.tipo==='LCI'?saldo:saldo-impostoIOF-(ganhos-impostoIOF)*.225;
    if(serie[ontem]!==undefined){
      diarioBruto+=cent(ganhos)-cent(antesBruto);
      diarioLiquido+=cent(ganhosLiquidos)-cent(antesLiquido);
    }
  }
  return {ontem,bruto,liquido,diarioBruto,diarioLiquido};
}
const a=preparar();
for(let dia=19;dia<=27;dia++){
  const credito='2026-10-'+dia;
  conferir(`${credito}: valor de ontem, bruto e líquido conferidos por cálculo independente`,()=>{
    a.clock(credito+'T15:00:00Z');a.run('render();');
    const e=oraculo(credito),r=a.run('resumoDiario(ontem())');
    assert.equal(a.run('ontem()'),e.ontem);
    assert.equal(cent(r.totalBruto),e.diarioBruto);
    assert.equal(cent(r.total),e.diarioLiquido);
    assert.equal(a.nodes.get('saldoBruto').textContent,'R$ '+e.bruto.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2}));
    assert.equal(cent(a.run('calcular().reduce((s,x)=>s+x.bruto,0)')),cent(e.bruto));
    assert.equal(cent(a.run('calcular().reduce((s,x)=>s+x.liquido,0)')),cent(e.liquido));
    assert.equal(a.nodes.get('pillDay').textContent.startsWith(a.run('assinado(resumoDiario(ontem()).total)')+' ontem · líquido'),true);
    assert.equal(a.run('DIARIO[hoje()]'),undefined);
    if(['2026-10-25','2026-10-26'].includes(credito)){
      assert.equal(r.total,0);assert.match(a.nodes.get('pillDay').textContent,/Final de semana/);
    }
  });
}
conferir('Virada de sábado para domingo ocorre à meia-noite local (UTC−3)',()=>{
  const a=preparar();a.clock('2026-10-25T02:59:59Z');a.run('render();');
  assert.equal(a.run('hoje()'),'2026-10-24');assert.ok(a.run('resumoDiario(ontem()).total')>0);
  const bruto=a.nodes.get('saldoBruto').textContent;
  a.clock('2026-10-25T03:00:00Z');a.run('render();');
  assert.equal(a.run('hoje()'),'2026-10-25');assert.equal(a.run('resumoDiario(ontem()).total'),0);
  assert.equal(a.nodes.get('saldoBruto').textContent,bruto);
});
conferir('Virada de segunda para terça libera o ganho da segunda',()=>{
  const a=preparar();a.clock('2026-10-27T02:59:59Z');a.run('render();');
  assert.equal(a.run('hoje()'),'2026-10-26');assert.equal(a.run('resumoDiario(ontem()).total'),0);
  a.clock('2026-10-27T03:00:00Z');a.run('render();');
  assert.equal(a.run('hoje()'),'2026-10-27');assert.equal(cent(a.run('resumoDiario(ontem()).total')),oraculo('2026-10-27').diarioLiquido);
});
conferir('Após Finados, terça mostra zero e quarta mostra o rendimento da terça',()=>{
  const a=preparar();a.set('carteira',[{...pos(idA,'Itaú Unibanco'),data:'2026-10-30'}]);
  a.set('CDI_MAP',{'2026-10-30':.05,'2026-11-02':.9,'2026-11-03':.07});a.run('CDI_VER++;');
  a.clock('2026-11-03T15:00:00Z');a.run('render();');
  assert.equal(a.run('resumoDiario(ontem()).total'),0);assert.match(a.nodes.get('pillDay').textContent,/Feriado/);
  assert.equal(a.nodes.get('saldoBruto').textContent,'R$ 10.005,00');
  a.clock('2026-11-04T15:00:00Z');a.run('render();');
  assert.ok(a.run('resumoDiario(ontem()).total')>0);assert.equal(a.nodes.get('saldoBruto').textContent,'R$ 10.012,00');
});
conferir('Sem aplicações: saldo bruto e líquido permanecem zerados',()=>{
  const a=preparar();a.set('carteira',[]);a.run('render();');
  assert.equal(a.nodes.get('saldoBruto').textContent,'R$ 0,00');assert.equal(a.run('calcular().length'),0);
});
for(const [arquivo,inicio,fim] of [
  ['outubro-2026','2026-10-19','2026-10-27'],
  ['fim-ano-2025','2025-12-22','2026-01-05'],
]) conferir(`Série oficial do BCB: ${inicio} a ${fim}, incluindo dias sem taxa e virada de ano`,()=>{
  const origem=JSON.parse(fs.readFileSync(new URL('./auditoria/'+arquivo+'.json',import.meta.url),'utf8'));
  assert.match(origem.fonte,/^https:\/\/api\.bcb\.gov\.br\/dados\/serie\/bcdata\.sgs\.12\//);
  assert.ok(origem.dados.length>0);
  const taxas=Object.fromEntries(origem.dados.map(x=>{const [d,m,y]=x.data.split('/');return [y+'-'+m+'-'+d,+x.valor];}));
  const a=preparar();a.set('carteira',[{...pos(idA,'Itaú Unibanco'),data:inicio,taxa:102}]);
  a.set('CDI_MAP',taxas);a.run('CDI_VER++;');
  let saldo=10000,acumulado=0,liquido=0;
  for(let tempo=Date.parse(inicio+'T12:00:00Z');tempo<=Date.parse(fim+'T12:00:00Z');tempo+=864e5){
    const ds=new Date(tempo).toISOString().slice(0,10),credito=new Date(tempo+864e5).toISOString().slice(0,10);
    const antes=acumulado,antesL=liquido,ganho=saldo*(taxas[ds]||0)/100*1.02;
    const prazo=Math.round((tempo-Date.parse(inicio+'T12:00:00Z'))/864e5)+1;
    saldo+=ganho;acumulado+=ganho;liquido+=ganho*(1-iof[prazo-1]/100)*.775;
    a.clock(credito+'T15:00:00Z');a.run('render();');
    const r=a.run('resumoDiario(ontem())');
    assert.equal(cent(r.totalBruto),cent(acumulado)-cent(antes),ds+' bruto');
    assert.equal(cent(r.total),cent(liquido)-cent(antesL),ds+' líquido');
    assert.equal(a.nodes.get('saldoBruto').textContent,'R$ '+saldo.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2}),ds+' saldo');
    if(!taxas[ds])assert.equal(r.total,0,ds+' sem taxa');
  }
  console.log(`  CDI oficial: saldo bruto final R$ ${saldo.toFixed(2)}, rendimento bruto R$ ${acumulado.toFixed(2)} (carteira fictícia).`);
});
console.log(`\n${casos} verificações de virada/bruto passaram, além das 97 anteriores.`);
