import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';

const html=fs.readFileSync(new URL('./index.html',import.meta.url),'utf8');
const main=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].at(-1)[1];
const semBoot=main.slice(0,main.indexOf('/* ============================================================\n   14. BOOT'));
const wallet='fd16aef7-d4c4-442b-8594-d36f7f00755b';
const idA='31e16345-3471-4c62-8231-4a717b8d885c',idB='1f34039a-557f-4f34-a1da-943ef98f195f';
const pos=(id,banco,valor=10000)=>({id,banco,valor,tipo:'CDB',index:'cdi',taxa:100,data:'2026-10-30'});

function ambiente(){
  const nodes=new Map(),storage=new Map(),downloads=[];
  let clock='2026-11-04T15:00:00Z';
  const node=()=>({value:'',textContent:'',innerHTML:'',style:{},dataset:{},options:[],offsetHeight:420,scrollTop:0,
    classList:{set:new Set(),add(...a){a.forEach(x=>this.set.add(x));},remove(...a){a.forEach(x=>this.set.delete(x));},contains(x){return this.set.has(x);},toggle(x,v){const n=v??!this.set.has(x);n?this.set.add(x):this.set.delete(x);return n;}},
    addEventListener(){},append(){},appendChild(){},prepend(){},querySelectorAll(){return[];},querySelector(){return node();},
    getBoundingClientRect(){return {width:400,height:200,left:0,top:0};},setAttribute(){},getAttribute(){return 'n1';},removeAttribute(){},
    focus(){},click(){},add(){},parentElement:{getBoundingClientRect:()=>({width:400,left:0})}});
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  class ClockDate extends Date{constructor(...args){super(...(args.length?args:[clock]));}static now(){return Date.parse(clock);}getTimezoneOffset(){return 180;}}
  const ctx=vm.createContext({Date:ClockDate,Intl,Math,JSON,Map,Set,Number,Array,Object,String,Promise,Uint8Array,console,
    crypto:webcrypto,performance:{now:()=>0},scrollY:0,innerWidth:400,matchMedia:()=>({matches:true}),
    localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    sessionStorage:{getItem:()=>null,setItem(){}},
    document:{getElementById:get,querySelector:()=>node(),querySelectorAll:()=>[],createElement:node,createTextNode:s=>s,body:node(),documentElement:node(),addEventListener(){}},
    navigator:{},location:{hash:'',pathname:'/',origin:'http://localhost'},history:{replaceState(){}},
    addEventListener(){},requestAnimationFrame:fn=>fn(0),setTimeout:()=>1,clearTimeout(){},setInterval(){},
    fetch:async()=>{throw new Error('Sem rede no teste');},AbortController,
    btoa:s=>Buffer.from(s,'binary').toString('base64'),atob:s=>Buffer.from(s,'base64').toString('binary'),
    Blob,URL:{createObjectURL:()=>'',revokeObjectURL(){}},Option:class{},window:{},
  });
  vm.runInContext(semBoot,ctx);
  // O contexto original recebe os substitutos diretamente, sem carregar o boot.
  ctx.gravarDownload=(obj,nome)=>downloads.push({obj:JSON.parse(JSON.stringify(obj)),nome});
  vm.runInContext(`CARTEIRA_ID='${wallet}'; render=()=>atualizarDiario(); baixarJSON=(obj,nome)=>gravarDownload(obj,nome);`,ctx);
  return {ctx,storage,nodes,downloads,run:s=>vm.runInContext(s,ctx),set:(k,v)=>{ctx.fixture=v;vm.runInContext(`${k}=JSON.parse(JSON.stringify(fixture));`,ctx);},clock:d=>clock=d};
}
let count=0;
async function teste(nome,fn){await fn();count++;console.log('✓ '+nome);}
function taxas(a){a.run(`CDI_MAP={'2026-10-30':.05,'2026-11-03':.05}; SEL_MAP={};CDI_DE='2026-10-30';CDI_ATE='2026-11-03';CDI_VER++;`);}
function remoto(a,carteira,revision='r1'){
  let row={id:wallet,prefs:{snapshot:2,revision,carteira,diario:{}}};
  const requests=[];let reject=false,casFail=false,patchHook=null;
  a.ctx.server=async(path,opts={})=>{
    requests.push({path,opts});if(reject)throw new Error('offline');
    if(path.startsWith('carteiras?')&&(!opts.method||opts.method==='GET'))return [JSON.parse(JSON.stringify(row))];
    if(path.startsWith('carteiras?')&&opts.method==='PATCH'){
      if(patchHook)await patchHook();
      if(casFail)return [];
      const filter=decodeURIComponent(path.split('prefs->>revision=')[1]);
      assert.equal(filter,row.prefs.revision?'eq.'+row.prefs.revision:'is.null');
      row=JSON.parse(opts.body);return [row];
    }
    if(path.startsWith('posicoes?')) return [];
    if(path==='posicoes') return null;
    throw new Error('Rota inesperada '+path);
  };
  a.run('api=server;');
  return {requests,get row(){return row;},offline(){reject=true;},failCAS(){casFail=true;},hook(fn){patchHook=fn;}};
}

await teste('Sintaxe de todos os scripts',()=>{for(const x of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(x[1]);});
await teste('Ontem separado por banco, com soma exata em centavos',()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Itaú Unibanco'),pos(idB,'Banco Inter',8000)]);taxas(a);a.run('atualizarDiario();');
  assert.equal(a.run('resumoDiario(ontem()).ds'),'2026-11-03');
  assert.equal(a.run('resumoDiario(ontem()).totalBruto'),9);
  assert.equal(a.run('resumoDiario(ontem()).bancos.reduce((s,b)=>s+b.brutoCentavos,0)'),900);
  assert.equal(a.run('DIARIO[hoje()]'),undefined);
});
await teste('Sábado, domingo e feriado não repetem o rendimento de sexta',()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter')]);taxas(a);a.run('atualizarDiario();');
  for(const ds of ['2026-10-31','2026-11-01','2026-11-02'])assert.equal(a.run(`resumoDiario('${ds}').totalBruto`),0);
  assert.equal(a.run("resumoDiario('2026-10-30').totalBruto"),5);
});
await teste('Aportes não são contados como lucro',()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter'),{...pos(idB,'Itaú Unibanco',50000),data:'2026-11-03'}]);taxas(a);a.run('atualizarDiario();');
  assert.equal(a.run('resumoDiario(ontem()).totalBruto'),30.00);
});
await teste('Resgate total mantém o histórico anterior e encerra os ganhos',()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter'),resg:[{data:'2026-11-03',f:1,bruto:10005,ir:1}]}]);taxas(a);a.run('atualizarDiario();');
  assert.equal(a.run("resumoDiario('2026-10-30').totalBruto"),5);
  assert.equal(a.run('resumoDiario(ontem()).totalBruto'),0);
});
await teste('Vencimento interrompe a apuração diária',()=>{
  const a=ambiente();a.set('carteira',[{...pos(idA,'Banco Inter'),venc:'2026-11-03'}]);taxas(a);a.run('atualizarDiario();');assert.equal(a.run('resumoDiario(ontem()).totalBruto'),0);
});
await teste('Contar hoje não altera dias encerrados',()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter')]);taxas(a);a.run('ANTECIPA=false;atualizarDiario();');const x=a.run('JSON.stringify(DIARIO)');
  a.run("ANTECIPA=true;DIARIO_FINGERPRINT='';atualizarDiario();");assert.equal(a.run('JSON.stringify(DIARIO)'),x);
});
await teste('Estimativa sem série é corrigida quando a taxa publicada chega',()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter')]);a.run('atualizarDiario();');assert.equal(a.run('resumoDiario(ontem()).estimado'),true);
  taxas(a);a.run('atualizarDiario();');assert.equal(a.run('resumoDiario(ontem()).estimado'),false);
});
await teste('Histórico persiste depois de remover uma aplicação e recarregar',async()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter')]);taxas(a);a.run('atualizarDiario();carteira=[];');await a.run('persistirLocal()');a.run('DIARIO={};');await a.run('carregar()');
  assert.equal(a.run("resumoDiario('2026-10-30').totalBruto"),5);
});
await teste('Virada do dia inclui o novo dia encerrado e nunca inclui hoje',()=>{
  const a=ambiente();a.clock('2026-11-03T15:00:00Z');a.set('carteira',[pos(idA,'Banco Inter')]);taxas(a);a.run('atualizarDiario();');assert.equal(a.run('DIARIO["2026-11-03"]'),undefined);
  a.clock('2026-11-04T15:00:00Z');a.run('atualizarDiario();');assert.equal(a.run('resumoDiario(ontem()).totalBruto'),5);assert.equal(a.run('DIARIO[hoje()]'),undefined);
});
await teste('Backups incluem histórico e premissas, sem metadados de sincronização',()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter')]);taxas(a);a.run('atualizarDiario();exportar();');assert.ok(a.downloads[0].obj.diario);assert.ok(a.downloads[0].obj.premissas);assert.equal(a.downloads[0].obj.sync,undefined);
});
await teste('IDs são migrados uma vez e permanecem estáveis em saves/reloads',async()=>{
  const a=ambiente();a.storage.set('carteira-rf-v1',JSON.stringify({carteira:[{...pos('antigo','Banco Inter')}]}));await a.run('carregar()');const id=a.run('carteira[0].id');assert.match(id,/^[0-9a-f-]{36}$/);
  await a.run('salvar()');await a.run('carregar()');assert.equal(a.run('carteira[0].id'),id);
});
await teste('Offline preserva a edição e a marca para reenvio',async()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter',12000)]);a.run("SYNC={dirty:true,revision:'r1',generation:1};");const s=remoto(a,[pos(idA,'Banco Inter',10000)]);s.offline();
  await a.run('puxarNuvem()');assert.equal(a.run('carteira[0].valor'),12000);assert.equal(a.run('SYNC.dirty'),true);
});
await teste('Envio pendente usa revisão e mantém o ID utilizado pela tela',async()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter',12000)]);a.run("SYNC={dirty:true,revision:'r1',generation:1};");const s=remoto(a,[pos(idA,'Banco Inter',10000)]);
  await a.run('empurrarNuvem()');assert.equal(a.run('carteira[0].id'),idA);assert.equal(s.row.prefs.carteira[0].valor,12000);assert.equal(a.run('SYNC.dirty'),false);
  assert.ok(s.requests.find(r=>r.opts.method==='PATCH').path.includes('prefs->>revision=eq.r1'));
});
await teste('Conflito entre aparelhos não sobrescreve nenhuma das carteiras',async()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter',12000)]);a.run("SYNC={dirty:true,revision:'r1',generation:1};");const s=remoto(a,[pos(idA,'Banco Inter',10000)],'r2');await a.run('puxarNuvem()');
  assert.equal(a.run('carteira[0].valor'),12000);assert.equal(s.row.prefs.carteira[0].valor,10000);assert.equal(s.requests.some(r=>r.opts.method),false);assert.ok(a.run('CONFLITO'));
});
await teste('Mudança remota após a leitura faz o CAS falhar com segurança',async()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter',12000)]);a.run("SYNC={dirty:true,revision:'r1',generation:1};");const s=remoto(a,[pos(idA,'Banco Inter',10000)]);s.failCAS();await a.run('empurrarNuvem()');
  assert.equal(a.run('carteira[0].valor'),12000);assert.equal(a.run('SYNC.dirty'),true);assert.ok(a.run('CONFLITO'));
});
await teste('Duas edições durante um envio mantêm a alteração mais recente',async()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter',12000)]);a.run("SYNC={dirty:true,revision:'r1',generation:1};");const s=remoto(a,[pos(idA,'Banco Inter',10000)]);let once=false;
  s.hook(async()=>{if(!once){once=true;a.run('carteira[0].valor=13000;SYNC.generation++;');}});
  await a.run('empurrarNuvem()');assert.equal(s.row.prefs.carteira[0].valor,13000);assert.equal(a.run('SYNC.dirty'),false);
});
await teste('Leitura da nuvem fica limitada à carteira atual',async()=>{
  const a=ambiente();const s=remoto(a,[pos(idA,'Banco Inter')]);await a.run('puxarNuvem()');assert.ok(s.requests[0].path.includes('id=eq.'+wallet));
});
await teste('Resposta de outra carteira é recusada',async()=>{
  const a=ambiente();a.set('carteira',[pos(idA,'Banco Inter',12000)]);a.ctx.server=async()=>[{id:idB,prefs:{snapshot:2,carteira:[]}}];a.run('api=server;');await a.run('puxarNuvem()');assert.equal(a.run('carteira[0].valor'),12000);
});
await teste('Backup inválido, HTML e identificadores duplicados são rejeitados',()=>{
  const a=ambiente();for(const ps of [[{...pos(idA,'<img onerror=alert(1)>')}],[pos(idA,'Banco Inter'),pos(idA,'Banco Inter')],[{...pos(idA,'Banco Inter'),data:'2027-01-01'}]]){
    a.ctx.fixture=ps;assert.throws(()=>a.run('validarCarteira(fixture)'));
  }
});
await teste('Premissas são editáveis e a curva respeita o cenário escolhido',()=>{
  const a=ambiente();a.run("aplicarPremissas({selic12:10,ipca:4,atualizado:hoje()})");assert.equal(a.run('IPCA_PROJ'),4);assert.equal(a.run("baseSelic('2027-11-04')"),10);assert.match(a.run('notaPremissas()'),/manual/);
});
await teste('Uma limpeza explícita não recupera o histórico antigo da nuvem',async()=>{
  const a=ambiente();const s=remoto(a,[]);s.row.prefs.diario={'2026-10-30':{itens:{[idA]:{banco:'Banco Inter',centavos:500,estimado:false}}}};
  a.run("carteira=[];DIARIO={};SYNC={dirty:true,revision:'r1',generation:1,replaceHistory:true};");await a.run('empurrarNuvem()');
  assert.equal(Object.keys(s.row.prefs.diario).length,0);assert.equal(a.run('SYNC.replaceHistory'),false);
});
await teste('Uma limpeza feita em outro aparelho é respeitada ao baixar',async()=>{
  const a=ambiente();a.run(`DIARIO={'2026-10-30':{itens:{'${idA}':{banco:'Banco Inter',centavos:500,estimado:false}}}};`);remoto(a,[]);await a.run('puxarNuvem()');
  assert.equal(a.run("DIARIO['2026-10-30']"),undefined);
});
await teste('Atualizar cache de taxas não altera o IPCA escolhido pelo usuário',async()=>{
  const a=ambiente();a.run("aplicarPremissas({selic12:10,ipca:4,atualizado:hoje()});");a.storage.set('taxas-bcb-v1',JSON.stringify({cdi:{},sel:{},ipca:5.02}));await a.run('cacheTaxas()');assert.equal(a.run('IPCA_PROJ'),4);
});
await teste('POST sem corpo é aceito pela API; requisição usa a carteira atual',async()=>{
  const a=ambiente();let request;
  a.ctx.fetch=async(url,opts)=>{request={url,opts};return {ok:true,status:201,text:async()=>''};};
  assert.equal(await a.run("api('posicoes',{method:'POST',body:'[]'})"),null);
  assert.equal(request.opts.headers['x-carteira'],wallet);
});
console.log(`\n${count} testes passaram. Nenhuma conexão com a carteira real foi feita.`);
export {ambiente,pos,idA,idB,taxas};
