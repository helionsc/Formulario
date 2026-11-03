import assert from 'node:assert/strict';
import {ambiente,pos,idA,idB,taxas} from './testes.mjs';

let casos=0;
const arred=v=>Math.round((v+Number.EPSILON)*100)/100;
const datas=['2026-10-26','2026-10-27','2026-10-28','2026-10-29','2026-10-30','2026-11-03'];
const taxasFixas=[.05,.04,.06,.045,.05,.055];
const serie=Object.fromEntries(datas.map((d,i)=>[d,taxasFixas[i]]));
function preparar(a){a.set('CDI_MAP',serie);a.run("CDI_DE='2026-10-26';CDI_ATE='2026-11-03';CDI_VER++;");}
function conferir(nome,fn){fn();casos++;console.log('✓ Conferência independente: '+nome);}

conferir('R$ 10.000 a 0,05% no dia da aplicação rende R$ 5,00',()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter'),data:'2026-11-03'}]);taxas(a);a.run('atualizarDiario();');
  assert.equal(a.run('resumoDiario(ontem()).totalBruto'),5);
  assert.equal(arred(a.run('brutoEm(carteira[0],hoje())')),10005);
});

for(const valor of [.5,8,10000,54321.78,1000000]) for(const percentual of [80,100,102,120]){
  conferir(`produto das taxas e soma dos dias: R$ ${valor}, ${percentual}% do CDI`,()=>{
    const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter',valor),taxa:percentual,data:datas[0]}]);preparar(a);
    a.run('ANTECIPA=false;atualizarDiario();');
    // Oráculo usa apenas os dados fixos e a definição de produtório da B3.
    const final=taxasFixas.reduce((saldo,t)=>saldo*(1+t/100*percentual/100),valor);
    assert.ok(Math.abs(a.run('brutoEm(carteira[0],hoje())')-final)<.000001);
    const centavos=a.run('Object.keys(DIARIO).reduce((s,d)=>s+Math.round(resumoDiario(d).totalBruto*100),0)');
    assert.equal(centavos,Math.round((final-valor+Number.EPSILON)*100));
  });
}

conferir('100 aportes de R$ 8 somam R$ 0,40; microganhos não desaparecem',()=>{
  const a=ambiente();a.set('carteira',Array.from({length:100},(_,i)=>({...pos('00000000-0000-4000-8000-'+String(i).padStart(12,'0'),'Banco Inter',8),data:'2026-11-02'})));taxas(a);
  a.run('atualizarDiario();');assert.equal(a.run('resumoDiario(ontem()).totalBruto'),.40);
});

for(const antecipa of [false,true]) conferir(`resgates parciais conciliam com caixa, antecipação ${antecipa}`,()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter'),data:datas[0]}]);preparar(a);a.run('ANTECIPA='+antecipa);
  a.run(`planoResgate('${idA}','2026-10-29',2500,true);planoResgate('${idA}','2026-10-30',1000,true);atualizarDiario();`);
  // Cálculo independente em caixa: cada resgate sai antes do rendimento do dia.
  let saldo=10000;
  for(let i=0;i<datas.length;i++){
    if(datas[i]==='2026-10-29') saldo-=2500;
    if(datas[i]==='2026-10-30') saldo-=1000;
    saldo*=1+taxasFixas[i]/100;
  }
  a.run('ANTECIPA=false;');
  assert.ok(Math.abs(a.run('brutoEm(carteira[0],hoje())')-saldo)<.000001);
  assert.equal(a.run('Object.keys(DIARIO).reduce((s,d)=>s+Math.round(resumoDiario(d).totalBruto*100),0)'),Math.round((saldo+3500-10000)*100));
});

conferir('vencimento exclui o próprio dia e inclui o início',()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter'),data:datas[0],venc:'2026-10-29'}]);preparar(a);a.run('atualizarDiario();');
  const final=taxasFixas.slice(0,3).reduce((s,t)=>s*(1+t/100),10000);
  assert.equal(arred(a.run('brutoEm(carteira[0],hoje())')),arred(final));assert.equal(a.run("resumoDiario('2026-10-29').totalBruto"),0);
});

conferir('lacuna em dia útil é estimativa, sem zerar o rendimento',()=>{
  const a=ambiente();a.clock('2026-11-06T15:00:00Z');a.set('carteira',[{...pos(idA,'Banco Inter'),data:'2026-11-03'}]);
  a.set('CDI_MAP',{'2026-11-03':.05,'2026-11-05':.05});a.run("CDI_DE='2026-11-03';CDI_ATE='2026-11-05';CDI_VER++;atualizarDiario();");
  assert.ok(a.run("resumoDiario('2026-11-04').totalBruto")>0);assert.equal(a.run("resumoDiario('2026-11-04').estimado"),true);
});

conferir('saldo estimado hoje inclui a data inicial; saldo fechado só inclui ontem',()=>{
  const a=ambiente();a.clock('2026-11-03T15:00:00Z');a.set('carteira',[{...pos(idA,'Banco Inter'),data:'2026-11-03'}]);taxas(a);
  a.run('ANTECIPA=false;');assert.equal(a.run('brutoEm(carteira[0],hoje())'),10000);
  a.run('ANTECIPA=true;');assert.equal(arred(a.run('brutoEm(carteira[0],hoje())')),10005);
});

conferir('soma dos bancos coincide com o total em cada data',()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter',10000),data:datas[0]},{...pos(idB,'Itaú Unibanco',54321.78),taxa:102,data:datas[0]}]);preparar(a);a.run('atualizarDiario();');
  for(const ds of datas){
    assert.equal(a.run(`Math.round(resumoDiario('${ds}').totalBruto*100)`),a.run(`resumoDiario('${ds}').bancos.reduce((s,b)=>s+b.brutoCentavos,0)`));
  }
});

console.log(`\n${casos} conferências independentes passaram, além dos 25 testes de regressão.`);
