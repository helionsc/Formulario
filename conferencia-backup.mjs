import assert from 'node:assert/strict';
import './conferencia-virada.mjs';
import {ambiente,pos,idA,idB,taxas} from './testes.mjs';

let casos=0;
async function conferir(nome,fn){await fn();casos++;console.log('✓ Backup: '+nome);}
function ambienteImportacao(){
  const a=ambiente();
  a.ctx.FileReader=class {readAsText(file){this.result=file.text;this.onload();}};
  a.run('sincronizar=async()=>{};');
  taxas(a);
  return a;
}
function restaurar(a,obj){
  const text=typeof obj==='string'?obj:JSON.stringify(obj);
  a.set('arquivoBackup',{text,size:Buffer.byteLength(text)});
  a.run('importar(arquivoBackup);');
  return a.run('STORE_FILA');
}
await conferir('Exportar JSON e importar em carteira vazia preserva aplicações, histórico e premissas',async()=>{
  const origem=ambienteImportacao();origem.set('carteira',[pos(idA,'Itaú Unibanco'),{...pos(idB,'Banco Inter',8000),tipo:'LCI'}]);
  origem.run("aplicarPremissas({selic12:12.5,ipca:4.8,atualizado:'2026-11-03'});atualizarDiario();exportar();");
  const {obj,nome}=origem.downloads[0];assert.match(nome,/\.json$/);assert.equal(obj.v,2);assert.equal(obj.sync,undefined);
  const esperado=JSON.parse(origem.run('JSON.stringify(resumoDiario(ontem()))'));
  const destino=ambienteImportacao();assert.equal(destino.run('carteira.length'),0);
  await restaurar(destino,obj);
  assert.deepEqual(JSON.parse(destino.run('JSON.stringify(carteira)')),obj.carteira);
  assert.deepEqual(JSON.parse(destino.run('JSON.stringify(resumoDiario(ontem()))')),esperado);
  assert.deepEqual(JSON.parse(destino.run('JSON.stringify(PREMISSAS)')),obj.premissas);
  assert.equal(destino.run('SYNC.dirty'),true);assert.equal(destino.run('SYNC.replaceHistory'),true);
  destino.run('carteira=[];DIARIO={};');await destino.run('carregar();');
  assert.equal(destino.run('carteira.length'),2);assert.equal(destino.run('carteira[0].id'),idA);
});
await conferir('JSON antigo, sem histórico e com identificadores legados, continua aceito',async()=>{
  const a=ambienteImportacao();await restaurar(a,{carteira:[pos('legado-1','Banco Inter')],selic:14.25});
  assert.equal(a.run('carteira.length'),1);assert.match(a.run('carteira[0].id'),/^[a-f0-9-]{36}$/);
  assert.ok(a.run('resumoDiario(ontem()).total')>0);
});
await conferir('JSON incompleto não substitui a carteira existente',async()=>{
  const a=ambienteImportacao();a.set('carteira',[pos(idA,'Itaú Unibanco')]);
  await restaurar(a,'{"carteira":[');
  assert.equal(a.run('carteira[0].id'),idA);assert.match(a.nodes.get('toast').textContent,/Backup inválido/);
});
await conferir('Aplicação inválida no arquivo não substitui a carteira existente',async()=>{
  const a=ambienteImportacao();a.set('carteira',[pos(idA,'Itaú Unibanco')]);
  await restaurar(a,{carteira:[{...pos(idB,'Banco Inter'),valor:-100}]});
  assert.equal(a.run('carteira[0].id'),idA);assert.match(a.nodes.get('toast').textContent,/Backup inválido/);
});
await conferir('Arquivo grande demais é rejeitado antes de ser lido',()=>{
  const a=ambienteImportacao();let leituras=0;a.ctx.FileReader=class {constructor(){leituras++;}};
  a.set('arquivoBackup',{size:20000001});a.run('importar(arquivoBackup);');
  assert.equal(leituras,0);assert.match(a.nodes.get('toast').textContent,/muito grande/);
});
await conferir('Arrastar para fechar fica na alça, permitindo rolar o conteúdo do painel',()=>{
  const a=ambienteImportacao();
  a.run(`var eventosConteudo={},eventosAlca={},fechamentos=0;
    var painel={scrollTop:0,style:{},classList:{add(){},remove(){}},addEventListener(n,f){eventosConteudo[n]=f;}};
    var alca={addEventListener(n,f){eventosAlca[n]=f;}};
    arrastavel(painel,()=>fechamentos++,alca);`);
  assert.equal(a.run('Object.keys(eventosConteudo).length'),0);
  a.run("eventosAlca.touchstart({touches:[{clientY:100}]});eventosAlca.touchmove({touches:[{clientY:230}]});eventosAlca.touchend();");
  assert.equal(a.run('fechamentos'),1);assert.equal(a.run('painel.style.transform'),'');
});
await conferir('Reabrir Dados volta ao início, onde ficam Exportar JSON e Importar JSON',()=>{
  const a=ambienteImportacao();a.run('abrirDados();');a.nodes.get('sheetDados').scrollTop=900;
  a.run('fecharDados();abrirDados();');assert.equal(a.nodes.get('sheetDados').scrollTop,0);
});
console.log(`\n${casos} verificações de backup passaram, além das 112 anteriores.`);
