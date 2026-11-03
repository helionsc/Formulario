import assert from 'node:assert/strict';
import './conferencia-backup.mjs';
import {ambiente} from './testes.mjs';

let casos=0;
const a=ambiente();
const inicial=(y=0,compacto=false)=>({y,direcao:0,trecho:0,compacto});
function rolar(estado,y,limite=2000){a.set('estadoTeste',estado);a.set('posicaoTeste',y);a.set('limiteTeste',limite);return a.run('menuAoRolar(estadoTeste,posicaoTeste,limiteTeste)');}
function conferir(nome,fn){fn();casos++;console.log('✓ Menu: '+nome);}
conferir('No início da página, o menu sempre aparece completo',()=>{
  assert.equal(rolar(inicial(200,true),20).compacto,false);
});
conferir('Rolar para baixo compacta o menu',()=>{
  assert.equal(rolar(inicial(),180).compacto,true);
});
conferir('Pequenos movimentos não fazem o menu mudar de tamanho',()=>{
  const s=rolar(inicial(100),110);assert.equal(s.compacto,false);
  assert.equal(rolar(s,115).compacto,false);
});
conferir('Movimentos contínuos na mesma direção são acumulados',()=>{
  let s=inicial(100);for(const y of [110,120,130])s=rolar(s,y);
  assert.equal(s.compacto,true);
});
conferir('Ao subir a página, o menu volta ao tamanho completo',()=>{
  assert.equal(rolar(inicial(600,true),580).compacto,false);
});
conferir('Uma pequena oscilação para cima mantém o menu compacto',()=>{
  assert.equal(rolar(inicial(600,true),594).compacto,true);
});
conferir('Mudar de direção reinicia a tolerância a movimentos pequenos',()=>{
  const s=rolar(inicial(600,true),594);assert.equal(rolar(s,599).compacto,true);
});
conferir('O elástico no fim da página não produz uma falsa subida',()=>{
  let s=rolar(inicial(800),1000,1000);assert.equal(s.compacto,true);
  s=rolar(s,1050,1000);assert.equal(s.y,1000);
  s=rolar(s,1000,1000);assert.equal(s.compacto,true);
});
conferir('O elástico acima do início é limitado a zero e expande o menu',()=>{
  const s=rolar(inicial(80,true),-35);assert.equal(s.y,0);assert.equal(s.compacto,false);
});
conferir('Páginas sem rolagem mantêm o menu completo',()=>{
  const s=rolar(inicial(),30,0);assert.equal(s.y,0);assert.equal(s.compacto,false);
});
conferir('Sem deslocamento, a direção e o estado permanecem estáveis',()=>{
  const s=rolar(inicial(),150);const proximo=rolar(s,150);
  assert.equal(proximo.compacto,s.compacto);assert.equal(proximo.direcao,s.direcao);assert.equal(proximo.trecho,s.trecho);
});
console.log(`\n${casos} verificações do menu passaram, além das 119 anteriores.`);
