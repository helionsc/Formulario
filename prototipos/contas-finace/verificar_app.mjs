import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {pathToFileURL,fileURLToPath} from 'node:url';

const root=path.dirname(fileURLToPath(import.meta.url));
const project=path.resolve(root,'../..');
const mirror=path.join(project,'github-formulario');
const original=fs.existsSync(mirror)?mirror:project;
const html=fs.readFileSync(path.join(root,'web/app.html'),'utf8');
const {source}=JSON.parse(fs.readFileSync(path.join(root,'origem.json'),'utf8'));
const published=fs.readFileSync(path.resolve(project,source),'utf8');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'finace-app-test-'));
try{
  fs.writeFileSync(path.join(temporary,'index.html'),html);
  fs.cpSync(path.join(original,'auditoria'),path.join(temporary,'auditoria'),{recursive:true});
  for(const name of ['testes.mjs','conferencia-rendimento.mjs','conferencia-liquido.mjs','conferencia-virada.mjs','conferencia-backup.mjs','conferencia-menu.mjs']){
    let code=fs.readFileSync(path.join(original,name),'utf8');
    if(name==='testes.mjs'){
      code=code.replace('vm.runInContext(semBoot,ctx);',`ctx.protoStorage=ctx.localStorage;ctx.protoSessionStorage=ctx.sessionStorage;ctx.window.FINACE_PROTOTIPO={wallet:'fd16aef7-d4c4-442b-8594-d36f7f00755b',email:'ana@finace.test',user:'test-user',csrf:'test-csrf'};vm.runInContext(semBoot,ctx);`);
      code=code.replace("request.opts.headers['x-carteira']","request.opts.headers['X-Wallet']");
    }
    if(name==='conferencia-backup.mjs'){
      code=code.replace("a.run('sincronizar=async()=>{};');","a.run('sincronizar=async()=>{};confirmarImportacao=async()=>true;');");
      code=code.replace("a.set('arquivoBackup',{text,size:Buffer.byteLength(text)});\n  a.run('importar(arquivoBackup);');\n  return a.run('STORE_FILA');","a.ctx.arquivoBackup={text:async()=>text,size:Buffer.byteLength(text)};\n  return a.run('importar(arquivoBackup);');");
    }
    fs.writeFileSync(path.join(temporary,name),code);
  }
  await import(pathToFileURL(path.join(temporary,'conferencia-menu.mjs')));
  const {ambiente,pos,idA,idB}=await import(pathToFileURL(path.join(temporary,'testes.mjs')));
  let count=0;
  async function test(name,fn){await fn();count++;console.log('✓ Contas e migração: '+name);}
  const setup=()=>{const a=ambiente();a.run('sincronizar=async()=>{};');a.set('carteira',[pos(idA,'Banco Inter')]);return a;};
  const file=obj=>({size:100,text:async()=>JSON.stringify(obj)});
  await test('Cancelar a revisão não altera carteira, histórico ou cópia anterior',async()=>{
    const a=setup(),before=a.run('JSON.stringify(estadoLocal())');a.run('confirmarImportacao=async()=>false;');
    a.ctx.file=file({carteira:[pos(idB,'Itaú Unibanco',8000)]});await a.run('importar(file)');
    assert.equal(a.run('JSON.stringify(estadoLocal())'),before);assert.equal(a.storage.has('carteira-recuperacao-v2'),false);
  });
  await test('Premissas inválidas são recusadas antes de alterar dados ou abrir confirmação',async()=>{
    const a=setup(),before=a.run('JSON.stringify(estadoLocal())');a.ctx.confirmations=0;a.run('confirmarImportacao=async()=>{confirmations++;return true;};');
    a.ctx.file=file({carteira:[pos(idB,'Itaú Unibanco')],premissas:{ipca:9000,selic12:14}});await a.run('importar(file)');
    assert.equal(a.ctx.confirmations,0);assert.equal(a.run('JSON.stringify(estadoLocal())'),before);
  });
  await test('Importação confirmada preserva cópia anterior antes de substituir aplicações',async()=>{
    const a=setup();a.run('confirmarImportacao=async()=>true;');a.ctx.file=file({carteira:[pos(idB,'Itaú Unibanco',8000)]});await a.run('importar(file)');
    assert.equal(a.run('carteira[0].id'),idB);assert.equal(JSON.parse(a.storage.get('carteira-recuperacao-v2')).carteira[0].id,idA);
  });
  await test('Cache de contas e carteiras diferentes usa espaços separados',()=>{
    const script=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)][0][1];
    const map=new Map();
    const storage={getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};
    const make=(user,wallet)=>{
      const ctx=vm.createContext({window:{},localStorage:storage,sessionStorage:storage});
      vm.runInContext(script.replace('/*__PROTOTYPE_BOOT__*/null',JSON.stringify({user,wallet})),ctx);return ctx;
    };
    const a=make('ana','carteira-a'),b=make('bruno','carteira-b'),shared=make('bruno','carteira-a');
    vm.runInContext("protoStorage.setItem('carteira-rf-v1','apenas-ana')",a);
    assert.equal(vm.runInContext("protoStorage.getItem('carteira-rf-v1')",b),null);
    assert.equal(vm.runInContext("protoStorage.getItem('carteira-rf-v1')",shared),null);
    assert.equal(vm.runInContext("protoStorage.getItem('carteira-rf-v1')",make('ana','carteira-a')),'apenas-ana');
    assert.equal(map.has('carteira-rf-v1'),false);
  });
  await test('Código antigo de link de acesso e chaves do Supabase não entram na prévia',()=>{
    assert.ok(!html.includes('supabase.co'));assert.ok(!html.includes('SB_KEY'));
    assert.ok(!html.includes("location.hash.match(/c="));assert.ok(!html.includes("'#c='"));
  });
  await test('Calendário, fator diário, impostos e diário permanecem idênticos à versão publicada',()=>{
    for(const [from,to] of [
      ['const D = s =>','/* ============================================================\n   6.'],
      ['function motivoDiaSemRendimento(','$(\'pillDay\').onclick']
    ]){
      const left=published.indexOf(from),right=published.indexOf(to,left);
      const candidateLeft=html.indexOf(from),candidateRight=html.indexOf(to,candidateLeft);
      assert.ok(left>=0&&right>left&&candidateLeft>=0&&candidateRight>candidateLeft);
      assert.equal(html.slice(candidateLeft,candidateRight),published.slice(left,right));
    }
  });
  console.log(`\n130 verificações anteriores + ${count} verificações novas do app passaram na cópia do protótipo.`);
}finally{fs.rmSync(temporary,{recursive:true,force:true});}
