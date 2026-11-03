import assert from 'node:assert/strict';
import fs from 'node:fs';
import './conferencia-rendimento.mjs';
import {ambiente,pos,idA,idB,taxas} from './testes.mjs';

let casos=0;
function verificar(nome,fn){fn();casos++;console.log('✓ Líquido/calendário: '+nome);}
const fmtcent=v=>Math.round((v+Number.EPSILON)*100);
const dataMenos=(credito,dc)=>new Date(Date.parse(credito+'T12:00:00Z')-dc*864e5).toISOString().slice(0,10);
const iofTabela=[96,93,90,86,83,80,76,73,70,66,63,60,56,53,50,46,43,40,36,33,30,26,23,20,16,13,10,6,3];

for(const [dias,aliquota] of [[1,22.5],[29,22.5],[30,22.5],[180,22.5],[181,20],[360,20],[361,17.5],[720,17.5],[721,15]]){
  verificar(`IR/IOF após ${dias} dias`,()=>{
    const a=ambiente();a.set('fixturePos',{...pos(idA,'Banco Inter'),data:dataMenos('2026-11-04',dias)});
    const r=a.run("tributarGanhoDiario(fixturePos,10,'2026-11-03')");
    const iof=dias<30?10*iofTabela[dias-1]/100:0;
    const ir=(10-iof)*aliquota/100;
    assert.ok(Math.abs(r.iof-iof)<1e-10);assert.ok(Math.abs(r.ir-ir)<1e-10);
    assert.ok(Math.abs(r.liquido-(10-iof-ir))<1e-10);
  });
}
for(const tipo of ['LCI','LCA','CRI','DEB','POUP']) verificar(`Isenção de ${tipo}`,()=>{
  const a=ambiente();a.set('fixturePos',{...pos(idA,'Banco Inter'),tipo,data:'2026-11-03'});
  const r=a.run("tributarGanhoDiario(fixturePos,10,'2026-11-03')");
  assert.equal(r.liquido,10);assert.equal(r.ir,0);assert.equal(r.iof,0);
});

const datas=['2026-10-26','2026-10-27','2026-10-28','2026-10-29','2026-10-30','2026-11-03'];
const t=[.05,.04,.06,.045,.05,.055];
for(const valor of [8,10000,1000000]) for(const percentual of [80,100,102,120]) verificar(`Oráculo líquido R$ ${valor} a ${percentual}% do CDI`,()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter',valor),data:datas[0],taxa:percentual}]);
  a.set('CDI_MAP',Object.fromEntries(datas.map((d,i)=>[d,t[i]])));a.run("CDI_DE='2026-10-26';CDI_ATE='2026-11-03';CDI_VER++;atualizarDiario();");
  let saldo=valor, acumulado=0;
  for(let i=0;i<datas.length;i++){
    const ganho=saldo*t[i]/100*percentual/100;
    saldo+=ganho;
    const prazo=Math.round((Date.parse(datas[i]+'T12:00:00Z')-Date.parse(datas[0]+'T12:00:00Z'))/864e5)+1;
    const iof=ganho*iofTabela[prazo-1]/100;
    const liquido=(ganho-iof)*.775;
    const antes=fmtcent(acumulado);acumulado+=liquido;
    assert.equal(a.run(`Math.round(resumoDiario('${datas[i]}').total*100)`),fmtcent(acumulado)-antes);
  }
  assert.equal(a.run('Object.keys(DIARIO).reduce((s,d)=>s+Math.round(resumoDiario(d).total*100),0)'),fmtcent(acumulado));
});

verificar('Soma do líquido por banco e por aporte fecha com o total',()=>{
  const a=ambiente();a.set('carteira',[
    pos(idA,'Banco Inter',12345.67),
    {...pos(idB,'Itaú Unibanco',9876.54),tipo:'LCI'},
    {...pos('00000000-0000-4000-8000-000000000001','Banco Inter',8),tipo:'LCA'}]);taxas(a);a.run('atualizarDiario();');
  const r=a.run('resumoDiario(ontem())');
  assert.equal(fmtcent(r.total),r.bancos.reduce((s,b)=>s+b.centavos,0));
  assert.equal(fmtcent(r.total),Object.values(r.posicoes).reduce((s,n)=>s+n,0));
  assert.ok(r.total<r.totalBruto);
  assert.equal(a.run('calcular().reduce((s,x)=>s+Math.round(x.delta*100),0)'),fmtcent(r.total));
});

verificar('Primeiro dia com IOF e IR: R$ 5,00 brutos, R$ 0,16 líquidos',()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter'),data:'2026-11-03'}]);taxas(a);a.run('atualizarDiario();');
  assert.equal(a.run('resumoDiario(ontem()).totalBruto'),5);assert.equal(a.run('resumoDiario(ontem()).total'),.16);
});
verificar('Microganhos líquidos não somem ao agregar 100 aportes',()=>{
  const a=ambiente();a.set('carteira',Array.from({length:100},(_,i)=>({...pos('00000000-0000-4000-8000-'+String(i).padStart(12,'0'),'Banco Inter',8),data:'2026-11-03'})));taxas(a);a.run('atualizarDiario();');
  const r=a.run('resumoDiario(ontem())');assert.equal(r.totalBruto,.4);assert.equal(r.total,.01);assert.equal(Object.values(r.posicoes).reduce((s,x)=>s+x,0),1);
});

for(const [ds,motivo] of [['2026-10-31','Final de semana'],['2026-11-01','Final de semana'],['2026-11-02','Feriado'],['2026-02-16','Feriado'],['2026-02-17','Feriado'],['2026-04-03','Feriado'],['2026-06-04','Feriado']]){
  verificar(`${ds}: zero e motivo ${motivo}`,()=>{
    const a=ambiente();const credit=new Date(Date.parse(ds+'T12:00:00Z')+864e5).toISOString().slice(0,10);a.clock(credit+'T15:00:00Z');
    a.set('carteira',[{...pos(idA,'Banco Inter'),data:dataMenos(ds,10)}]);a.set('CDI_MAP',{[ds]:.05});a.run('CDI_VER++;atualizarDiario();');
    const r=a.run(`resumoDiario('${ds}')`);assert.equal(r.total,0);assert.equal(r.totalBruto,0);assert.equal(r.motivo,motivo);
    assert.match(a.run(`linhaDiario('${ds}')`),new RegExp(motivo));
    a.run(`preencherDetalheDia('${ds}')`);assert.match(a.nodes.get('diaEstado').textContent,new RegExp(motivo));
  });
}
verificar('Feriado tem nome no detalhe',()=>{
  const a=ambiente();a.run("preencherDetalheDia('2026-11-02')");assert.match(a.nodes.get('diaEstado').textContent,/Finados/);
});
verificar('Queda do IOF não cria rendimento no domingo',()=>{
  const a=ambiente();a.clock('2026-11-02T15:00:00Z');a.set('carteira',[{...pos(idA,'Banco Inter'),data:'2026-10-03'}]);a.run('atualizarDiario();');
  assert.equal(a.run('resumoDiario(ontem()).total'),0);assert.equal(a.run('resumoDiario(ontem()).motivo'),'Final de semana');
});
verificar('O histórico não muda sua alíquota quando a aplicação envelhece',()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter')]);taxas(a);a.run('atualizarDiario();');const n=a.run("resumoDiario('2026-11-03').total");
  a.clock('2027-02-04T15:00:00Z');a.run('atualizarDiario();');assert.equal(a.run("resumoDiario('2026-11-03').total"),n);
});
verificar('Um bruto legado sem aplicação não é tratado como líquido',()=>{
  const a=ambiente();a.set('DIARIO',{'2026-11-03':{itens:{[idA]:{banco:'Banco Inter',centavos:500,inicio:0,fim:5,estimado:false}}}});
  const r=a.run("resumoDiario('2026-11-03')");assert.equal(r.total,null);assert.equal(r.incompleto,true);
  assert.match(a.run("linhaDiario('2026-11-03')"),/A recalcular/);assert.equal(r.totalBruto,5);
});
verificar('Backups e validação preservam os campos do líquido',()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter')]);taxas(a);a.run('atualizarDiario();exportar();');const n=a.run('resumoDiario(ontem()).total');
  a.set('DIARIO',a.downloads[0].obj.diario);a.run('DIARIO=validarDiario(DIARIO);');assert.equal(a.run('resumoDiario(ontem()).total'),n);
});
verificar('Sugestões foram removidas do HTML, JavaScript e CSS',()=>{
  const html=fs.readFileSync(new URL('./index.html',import.meta.url),'utf8');
  for(const s of ['secSug','sugList','cartaoSugestoes','Onde seu dinheiro renderia mais','.sug-card'])assert.equal(html.includes(s),false);
  assert.match(html,/Rendimento diário líquido/);assert.equal(html.includes('ontem · bruto'),false);
});
for(const antecipar of [false,true]) verificar(`Líquido com dois resgates parciais, antecipação ${antecipar}`,()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter'),data:datas[0]}]);
  a.set('CDI_MAP',Object.fromEntries(datas.map((d,i)=>[d,t[i]])));a.run('ANTECIPA='+antecipar);
  a.run(`planoResgate('${idA}','2026-10-29',2500,true);planoResgate('${idA}','2026-10-30',1000,true);atualizarDiario();`);
  let saldo=10000,liquido=0;
  for(let i=0;i<datas.length;i++){
    if(datas[i]==='2026-10-29')saldo-=2500;
    if(datas[i]==='2026-10-30')saldo-=1000;
    const ganho=saldo*t[i]/100;saldo+=ganho;
    const prazo=Math.round((Date.parse(datas[i]+'T12:00:00Z')-Date.parse(datas[0]+'T12:00:00Z'))/864e5)+1;
    liquido+=ganho*(1-iofTabela[prazo-1]/100)*.775;
  }
  assert.equal(a.run('Object.keys(DIARIO).reduce((s,d)=>s+Math.round(resumoDiario(d).total*100),0)'),fmtcent(liquido));
});

console.log(`\n${casos} verificações de líquido/calendário passaram, além das 53 verificações anteriores.`);
