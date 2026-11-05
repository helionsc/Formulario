"""Gera a cópia isolada sem modificar o index publicado."""
import hashlib
import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--hosted", action="store_true", help="Gera a carteira web com taxas oficiais.")
hosted = parser.parse_args().hosted
PROJECT = ROOT.parent.parent
ASSETS = PROJECT / "github-formulario"
RELEASE = PROJECT / "previas" / "finace-formas-20261104"
SOURCE = RELEASE / "fonte" / "index.html" if RELEASE.is_dir() else PROJECT / "index.html"
if not ASSETS.is_dir():
    ASSETS = PROJECT
PUBLISHED_COMMIT = "9f309e808e03d005bf6ccd7d3f824cdeb050c8af"
PUBLISHED_SHA256 = "223489b6ce9ab75ac2287f037270166812dad066eae4d089ccdd09baf66834da"
WEB = ROOT / "web"
WEB.mkdir(exist_ok=True)
source = SOURCE.read_text()
source_sha256 = hashlib.sha256(source.encode()).hexdigest()
if source_sha256 != PUBLISHED_SHA256:
    raise ValueError("O index da carteira deve corresponder à versão publicada.")
html = source.replace("localStorage", "protoStorage").replace("sessionStorage", "protoSessionStorage")
html = html.replace("Apagar tudo", "Limpar carteira")
html = re.sub(r'<link[^>]+(?:fonts\.googleapis|fonts\.gstatic|rel="manifest")[^>]*>\s*', '', html)
html = re.sub(r"const SB_URL\s*=.*?\nconst KEY_ID\s*=.*?;", "", html, flags=re.S)
start = html.index("async function idCarteira()")
end = html.index("const paraNuvem", start)
html = html[:start] + '''async function idCarteira(){ CARTEIRA_ID=window.FINACE_PROTOTIPO.wallet; return CARTEIRA_ID; }
async function api(caminho, opts={}){
  if(window.PROTO_OFFLINE) throw new Error('Sem conexão na simulação');
  const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),12000);
  try{
    const r=await fetch('/api/app/'+caminho,{
      ...opts,signal:ctrl.signal,credentials:'same-origin',cache:'no-store',
      headers:{...opts.headers,'Content-Type':'application/json','X-Prototype':'local',
        'X-Wallet':window.FINACE_PROTOTIPO.wallet,'X-CSRF-Token':window.FINACE_PROTOTIPO.csrf}
    });
    if(r.status===401||r.status===403){
      document.body.style.visibility='hidden';parent.postMessage({type:'proto:session-ended'},location.origin);
      throw new Error('Sessão encerrada ou acesso revogado');
    }
    if(r.status===204)return null;
    const raw=await r.text(),result=raw?JSON.parse(raw):null;
    if(!r.ok)throw new Error(result?.error||'Falha ao salvar');return result;
  }finally{clearTimeout(timer);}
}

''' + html[end:]
start = html.index("/* cache de taxas compartilhado")
end = html.index("/* ============================================================\n   7.", start)
if hosted:
    html = html[:start] + "async function taxasDaNuvem(){return {n:0};}\nasync function subirTaxas(){}\n" + html[end:]
else:
    html = html[:start] + html[end:]
start = html.index("async function sgs(")
end = html.index("async function cacheTaxas()", start)
if not hosted:
    html = html[:start] + html[end:]
start = html.index("async function sincronizar(silencioso)")
end = html.index("function statusTaxas()", start)
if not hosted:
    html = html[:start] + '''async function sincronizar(silencioso){
  const desde=carteira.length?carteira.reduce((d,p)=>p.data<d?p.data:d,hoje()):iso(addD(D(hoje()),-120));
  for(let d=D(desde);iso(d)<hoje();d=addD(d,1))if(util(d)){CDI_MAP[iso(d)]=.05;SEL_MAP[iso(d)]=.0504;}
  const ks=Object.keys(CDI_MAP).sort();CDI_DE=ks[0]||'';CDI_ATE=ks.at(-1)||'';
  CDI_VER++;cacheB.clear();FONTE_TAXA='Taxas fictícias para testar o protótipo';
  ONLINE=!window.PROTO_OFFLINE;ULTIMA_SYNC=new Date().toISOString();
  await gravarTaxas();atualizarCurva();statusTaxas();render();await persistirLocal();
  if(!silencioso)toast('Prévia local: taxas fictícias; nenhum banco foi consultado');return true;
}
''' + html[end:]
if not hosted:
    html = html.replace("'Salvo na nuvem'", "'Salvo no servidor de teste'")
    html = html.replace('CDI do Banco Central</span>', 'Taxas fictícias da prévia</span>')
html = html.replace("$('dLink').onclick = async () => {\n  const url = location.origin + location.pathname + '#c=' + await idCarteira();\n  try{ await navigator.clipboard.writeText(url); toast('Link copiado — abra nele no outro aparelho'); }\n  catch(e){ prompt('Abra este link no outro aparelho:', url); }\n};", "$('dLink').onclick = () => parent.postMessage({type:'proto:account'},location.origin);")
html = html.replace('Copiar link para outro aparelho', 'Conta e acesso em outro aparelho')
html = html.replace('O link da carteira permite acessar os dados em outro aparelho. Compartilhe apenas com quem pode ver sua carteira. O Face ID protege a tela deste aparelho.', 'Para usar em outro aparelho, entre na mesma conta. Para compartilhar a carteira, envie um convite em Conta. Nesta prévia, os dados ficam somente neste computador.')
html = html.replace('<h3>Dados e backup</h3>', '<h3>Dados e backup</h3><p class="diario-intro">Importe um JSON do app anterior para testar a migração nesta conta. O arquivo original permanece no seu aparelho.</p>')
html = html.replace(
    '${assinado(a.liq-a.aplic)} líq.</span></div>',
    '''${assinado(a.liq-a.aplic)} líq.</span>
            <button type="button" class="resg resg-atalho" data-g="${a.gid}" aria-label="Resgatar ${esc(descProduto(p))}">Resgatar</button></div>''',
    1,
)
html = html.replace('<h3>Resgatar</h3>\n  <p class="sheet-sub" id="rSub"></p>',
    '<h3>Registrar resgate</h3>\n  <p class="sheet-sub" id="rSub"></p>\n'
    '  <p class="diario-intro">Registre uma retirada que você já fez no banco.</p>', 1)
html = html.replace('Informe o valor para ver quanto cai na conta.', 'Informe o valor para ver a estimativa líquida.')
html = html.replace('Cai na conta: <b>${fmt(r.liquido)}</b> · IR + IOF retidos',
    'Líquido estimado: <b>${fmt(r.liquido)}</b> · IR + IOF estimados', 1)
html = html.replace('salvar().then(() => toast(`Resgate de ${fmt(r.bruto)} registrado · ${fmt(r.liquido)} na conta`));',
    '''salvar().then(ok => toast(ok ? `Resgate de ${fmt(r.bruto)} registrado`
    : 'Não consegui salvar o resgate neste aparelho. Baixe um backup em Dados.'));''', 1)
if not hosted:
    html = html.replace('CDI até ${CDI_ATE', 'Taxa fictícia até ${CDI_ATE')
# O snapshot completo é a fonte de dados da prévia. Não escreve na tabela antiga.
start = html.index('    /* Compatibilidade com a tabela da versão antiga')
end = html.index('    if(SYNC.dirty)', start)
html = html[:start] + html[end:]
start = html.index('async function suportaBio()')
end = html.index('async function verificarBio()', start)
html = html[:start] + 'async function suportaBio(){return false;}\n' + html[end:]
start = html.index('function importar(file)')
end = html.index('function aplicarPremissas(', start)
html = html[:start] + '''async function importar(file){
  if(file.size>20000000){toast('O arquivo é muito grande');return;}
  try{
    const s=JSON.parse(await file.text()),lista=validarCarteira(s.carteira),diario=validarDiario(s.diario);
    if(s.premissas){
      const p=s.premissas,sel=p.selic12===null||p.selic12===''?null:+p.selic12;
      if((sel!==null&&(!Number.isFinite(sel)||sel<0||sel>60))||!Number.isFinite(+p.ipca)||+p.ipca<0||+p.ipca>50)throw new Error('Premissas inválidas');
    }
    const seguir=await confirmarImportacao(lista.length,Object.keys(diario).length,carteira.length);
    if(!seguir)return;
    await NUVEM_FILA;
    guardarRecuperacao('Antes de importar dados do app anterior');
    carteira=lista;DIARIO=diario;DIARIO_FINGERPRINT='';SYNC.replaceHistory=true;
    if(s.premissas)aplicarPremissas(s.premissas);
    cacheB.clear();render();await salvar();await sincronizar(true);
    toast(`${carteira.length} aplicações importadas nesta conta de teste`);
  }catch(e){toast('Backup inválido: '+e.message);}
}
function confirmarImportacao(aplicacoes,dias,atuais){
  const modal=$('protoImport');
  $('protoImportResumo').textContent=`${aplicacoes} aplicações e ${dias} dias de histórico. Conta: ${window.FINACE_PROTOTIPO.email}.`;
  $('protoImportAviso').textContent=atuais?`As ${atuais} aplicações desta carteira de teste serão substituídas. Uma cópia anterior será preservada.`:'A carteira está vazia. Os dados serão adicionados a esta conta.';
  modal.showModal();return new Promise(resolve=>modal.addEventListener('close',()=>resolve(modal.returnValue==='importar'),{once:true}));
}

''' + html[end:]
bootstrap = '''<script>
window.FINACE_PROTOTIPO=/*__PROTOTYPE_BOOT__*/null;
window.PROTO_OFFLINE=false;
const protoPrefix='finace-teste:'+window.FINACE_PROTOTIPO.user+':'+window.FINACE_PROTOTIPO.wallet+':';
function scopedStorage(storage){return {getItem:k=>storage.getItem(protoPrefix+k),setItem:(k,v)=>storage.setItem(protoPrefix+k,v),removeItem:k=>storage.removeItem(protoPrefix+k)};}
const protoStorage=scopedStorage(localStorage),protoSessionStorage=scopedStorage(sessionStorage);
</script>'''
html = html.replace('<title>Investimentos</title>', '<title>Finace · carteira de teste</title>' + bootstrap)
style = '''
.proto-banner{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px max(16px,env(safe-area-inset-right));background:#e7edf6;color:#354b69;font-size:10px;line-height:1.4}
.proto-banner b{font-weight:600}.proto-banner button{border:0;background:#fff;color:#263a55;padding:8px 12px;border-radius:20px;font:inherit;font-size:11px;font-weight:600;min-height:36px;cursor:pointer}
.proto-toolbar{display:flex;gap:8px}.proto-banner button[aria-pressed="true"]{background:#f9e7c6;color:#78550d}
.proto-identity{background:#e7edf6;color:#627791;padding:0 16px 9px;font-size:10px;line-height:1.5;overflow-wrap:anywhere}
dialog.proto-modal{border:0;border-radius:28px;padding:26px;width:calc(100% - 32px);max-width:420px;color:var(--ink);box-shadow:0 24px 80px #14213d33}
dialog.proto-modal::backdrop{background:#14213d66;backdrop-filter:blur(8px)}
.proto-modal p{font-size:13px;line-height:1.6;color:var(--ink-2);margin:14px 0}.proto-modal h3{font-size:21px}.proto-modal button{width:100%;margin-top:10px}
.apl-end .resg-atalho{display:inline-block;margin-top:4px;min-height:34px;padding:0 10px;border:1px solid var(--line-2);border-radius:999px;background:var(--surface-2);color:var(--ink);font:inherit;font-size:11px;font-weight:600;cursor:pointer}
.apl-end .resg-atalho:focus-visible{outline:2px solid var(--marca);outline-offset:2px}
'''
html = html.replace('</style>', style + '</style>', 1)
banner = '''<div class="proto-banner"><span><b>PRÉVIA LOCAL</b><br>Dados e taxas fictícios</span><div class="proto-toolbar"><button id="protoOffline" aria-pressed="false">Simular offline</button><button id="protoConta">Conta</button></div></div>'''
html = html.replace('<body>', '<body>' + banner + '<div class="proto-identity" id="protoIdentity"></div>', 1)
dialog = '''<dialog id="protoImport" class="proto-modal" aria-labelledby="protoImportTitulo"><form method="dialog"><h3 id="protoImportTitulo">Revisar importação</h3><p id="protoImportResumo"></p><p id="protoImportAviso"></p><button class="cta" value="importar">Importar nesta conta</button><button class="cta ghost" value="cancelar" autofocus>Cancelar</button></form></dialog>'''
html = html.replace('<div class="toast" id="toast"></div>', dialog + '<div class="toast" id="toast"></div>')
extension = '''
$('protoIdentity').textContent='Conta: '+window.FINACE_PROTOTIPO.email+(window.FINACE_PROTOTIPO.role==='editor'?' · Carteira de '+window.FINACE_PROTOTIPO.owner_email:' · Sua carteira pessoal');
$('protoConta').onclick=()=>parent.postMessage({type:'proto:account'},location.origin);
$('protoOffline').onclick=async()=>{
  window.PROTO_OFFLINE=!window.PROTO_OFFLINE;const b=$('protoOffline');
  b.setAttribute('aria-pressed',String(window.PROTO_OFFLINE));b.textContent=window.PROTO_OFFLINE?'Reconectar':'Simular offline';
  if(window.PROTO_OFFLINE){NUVEM_OK=false;NUVEM_MSG='offline simulado · salvo neste aparelho';statusTaxas();}
  else{await puxarNuvem();statusTaxas();render();}
};
addEventListener('message',async e=>{
  if(e.origin!==location.origin||e.source!==parent)return;
  if(e.data?.type==='proto:checkpoint'){
    await persistirLocal();await NUVEM_FILA;
    if(SYNC.dirty&&!window.PROTO_OFFLINE)await empurrarNuvem();
    parent.postMessage({type:'proto:checkpoint-result',id:e.data.id,pending:!!SYNC.dirty},location.origin);
  }
  if(e.data?.type==='proto:backup'){exportar();}
  if(e.data?.type==='proto:import'){abrirDados();}
});
'''
html = html.replace('/* ============================================================\n   14. BOOT', extension + '\n/* ============================================================\n   14. BOOT', 1)
html = html.replace('  /* mantém sempre em dia */', "  parent.postMessage({type:'proto:ready'},location.origin);\n\n  /* mantém sempre em dia */", 1)
assert 'supabase.co' not in html and 'SB_KEY' not in html
assert not re.search(r'fetch\([^\n]*https?:', html)
if hosted:
    html = html.replace("fetch('/api/", "fetch('/conta/api/")
    html = html.replace('<b>PRÉVIA LOCAL</b><br>Dados e taxas fictícios', '<b>FINACE</b><br>Carteira pessoal')
    html = html.replace('<button id="protoOffline" aria-pressed="false">Simular offline</button>', '')
    html = html.replace("$('protoOffline').onclick=", "if($('protoOffline'))$('protoOffline').onclick=")
    html = html.replace('Nesta prévia, os dados ficam somente neste computador.', 'As aplicações ficam vinculadas à sua conta.')
    html = html.replace(' Para compartilhar a carteira, envie um convite em Conta.', '')
    html = html.replace('nesta conta de teste', 'nesta conta').replace('desta carteira de teste', 'desta carteira')
    html = html.replace('para testar a migração nesta conta', 'para transferir suas aplicações para esta conta')
    html = html.replace('finace-teste:', 'finace-conta:')
    (WEB / 'app-online.html').write_text(html)
else:
    (WEB / 'app.html').write_text(html)
for asset in ['favicon.svg', 'apple-touch-icon.png']:
    shutil.copyfile(ASSETS / asset, WEB / asset)
backup = ASSETS / 'backup-teste-ficticio.json'
if backup.is_file():
    shutil.copyfile(backup, WEB / 'exemplo-backup.json')
(ROOT / 'origem.json').write_text(json.dumps({
    'source': SOURCE.relative_to(PROJECT).as_posix(),
    'sha256': source_sha256,
    'commit_publicado': PUBLISHED_COMMIT,
    'github_modificado': False,
    'supabase_conectado': False,
}, indent=2) + '\n')
print('Carteira gerada em', WEB / ('app-online.html' if hosted else 'app.html'))
