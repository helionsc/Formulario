'use strict';
const $=id=>document.getElementById(id);
let session=null,wallet=null,challenge=null,deleteChallenge=null,pendingAction=null,appReady=false;
let config={auth_mode:'supabase',configured:false,resend_seconds:60,account_deletion_available:false},resendUntil=0;
const checkpoints=new Map();
const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('finace-prototipo-contas'):null;

async function api(path,{method='GET',body,scope=wallet}={}){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
  try{
    const r=await fetch(path,{method,credentials:'same-origin',cache:'no-store',signal:controller.signal,
      headers:{'Content-Type':'application/json','X-Prototype':'local','X-CSRF-Token':session?.csrf||'','X-Wallet':scope||''},
      ...(body===undefined?{}:{body:JSON.stringify(body)})});
    const data=await r.json();
    if(!r.ok){const e=new Error(data.error||'Não foi possível concluir.');e.status=r.status;throw e;}
    return data;
  }finally{clearTimeout(timer);}
}
function message(id,text=''){$(id).textContent=text;}
async function action(button,messageId,fn){
  button.disabled=true;message(messageId);
  try{await fn();}catch(e){message(messageId,e.name==='AbortError'?'O servidor local não respondeu. Tente novamente.':e.message);}
  finally{button.disabled=false;updateResend();}
}
function demo(){return config.auth_mode==='demo';}
function updateResend(){
  const seconds=Math.max(0,Math.ceil((resendUntil-Date.now())/1000));
  $('resend').disabled=seconds>0;$('resend').textContent=seconds?`Novo código em ${seconds}s`:'Novo código';
}
function configureAccess(){
  $('testAccounts').hidden=!demo();$('demoCodeBox').hidden=true;
  $('emailForm').querySelector('button[type="submit"]').disabled=!config.configured;
  $('emailLabel').textContent=demo()?'E-mail de teste':'Seu e-mail';
  $('emailHelp').textContent=demo()?'Use um endereço terminado em .test. Nenhum e-mail será enviado.':'Enviaremos um código para confirmar que este e-mail é seu. Não precisa criar uma senha.';
  if(demo()&&!$('email').value)$('email').value='ana@finace.test';
  $('codeDelivery').hidden=demo();$('openDelete').hidden=!config.account_deletion_available;
  document.querySelector('.testing-card').hidden=!demo();
  $('accessPrivacy').firstChild.textContent=demo()?'Esta demonstração usa contas .test e guarda dados neste computador. ':'A confirmação do e-mail usa o Supabase. As aplicações desta prévia ficam neste computador; use valores fictícios. ';
  if(config.cloud_wallet){
    $('accessPrivacy').firstChild.textContent='Sua carteira de teste é salva no Supabase e fica vinculada ao seu e-mail. Use valores fictícios. ';
    $('sharingHelp').closest('.card').hidden=true;
    $('accountEmail').nextElementSibling.textContent='Entre com o mesmo e-mail em outro navegador da prévia para recuperar a carteira de teste.';
  }
  $('inviteEmail').value=demo()?'bruno@finace.test':'';
  $('inviteEmail').placeholder=demo()?'pessoa@finace.test':'pessoa@email.com';
}
function screen(name){
  for(const id of ['login','account','appContainer','loading'])$(id).hidden=id!==name;
  document.body.style.overflow=name==='appContainer'?'hidden':'';
  if(name!=='appContainer')window.scrollTo(0,0);
}
function clearCache(prefix='finace-teste:'){
  for(const storage of [localStorage,sessionStorage]){
    for(let i=storage.length-1;i>=0;i--){const key=storage.key(i);if(key?.startsWith(prefix))storage.removeItem(key);}
  }
}
function resetFrame(){
  $('appFrame').removeAttribute('src');delete $('appFrame').dataset.wallet;pendingAction=null;appReady=false;
}
function loginScreen(note=''){
  resetFrame();session=null;wallet=null;challenge=null;
  $('emailForm').hidden=false;$('codeForm').hidden=true;
  $('stepLabel').textContent='01 / SUA CONTA';$('accessTitle').textContent='Entre no seu ritmo.';
  $('accessSubtitle').textContent=demo()?'Use um e-mail de teste para conhecer a nova experiência.':'Entre ou crie sua conta confirmando seu e-mail.';
  resendUntil=0;updateResend();configureAccess();
  message('loginMessage',note);screen('login');
}
async function refreshSession(){
  const previousUser=session?.user?.id;
  session=await api('/api/session');
  if(previousUser&&previousUser!==session.user.id){resetFrame();clearCache();}
  const remembered=sessionStorage.getItem('finace-teste:selected:'+session.user.id);
  if(!session.wallets.some(w=>w.id===wallet))wallet=session.wallets.find(w=>w.id===remembered)?.id||session.wallets[0]?.id;
  return session;
}
function sendFrame(type,extra={}){
  if($('appFrame').dataset.wallet)$('appFrame').contentWindow.postMessage({type,...extra},location.origin);
}
function checkpoint(){
  if(!$('appFrame').dataset.wallet)return Promise.resolve(false);
  return new Promise(resolve=>{
    const id=crypto.randomUUID();
    const timer=setTimeout(()=>{checkpoints.delete(id);resolve(true);},15000);
    checkpoints.set(id,pending=>{clearTimeout(timer);resolve(pending);});
    sendFrame('proto:checkpoint',{id});
  });
}
async function requireSaved(){
  if(await checkpoint())throw new Error('Há alterações locais aguardando envio. Volte à carteira e toque em Reconectar antes de sair, trocar a carteira ou restaurar dados. Você também pode exportar um JSON.');
}
function showApp(command){
  if(!wallet)return;
  screen('appContainer');
  if($('appFrame').dataset.wallet!==wallet){
    pendingAction=command||null;appReady=false;$('appFrame').dataset.wallet=wallet;
    $('appFrame').src='/app.html?wallet='+encodeURIComponent(wallet);
  }else if(command){if(appReady)sendFrame(command);else pendingAction=command;}
}
function row(title,detail,label,click,{selected=false,remove=false}={}){
  const element=document.createElement('div');element.className='row'+(selected?' selected':'');
  const text=document.createElement('div'),strong=document.createElement('strong'),small=document.createElement('small');
  strong.textContent=title;small.textContent=detail;text.append(strong,small);element.append(text);
  if(label){const button=document.createElement('button');button.textContent=label;if(remove)button.className='remove';
    button.onclick=()=>action(button,'accountMessage',click);element.append(button);}
  return element;
}
async function renderAccount(){
  $('accountEmail').textContent=session.user.email;
  $('avatar').textContent=session.user.email[0].toUpperCase();
  $('walletList').replaceChildren(...session.wallets.map(w=>row(w.name,w.role==='owner'?'Sua carteira pessoal':'De '+w.owner_email,w.id===wallet?'Selecionada':'Selecionar',async()=>{
    await requireSaved();wallet=w.id;sessionStorage.setItem('finace-teste:selected:'+session.user.id,wallet);resetFrame();await renderAccount();
  },{selected:w.id===wallet})));
  $('incomingInvites').replaceChildren(...session.invites.map(i=>row('Convite para '+i.name,'De '+i.sender,'Aceitar',async()=>{
    await requireSaved();const accepted=await api('/api/invites/accept',{method:'POST',body:{invite:i.id}});
    wallet=accepted.wallet;resetFrame();await refreshSession();await renderAccount();
    message('accountMessage','Convite aceito. A carteira compartilhada está selecionada.');
  })));
  const [sharing,versions]=await Promise.all([api('/api/sharing'),api('/api/versions')]);
  $('inviteForm').hidden=sharing.role!=='owner';
  $('sharingHelp').textContent=sharing.role==='owner'?'Convide outra conta para acompanhar e editar a carteira selecionada. Você pode remover o acesso depois.':'Você participa desta carteira. Somente o proprietário pode convidar ou remover pessoas.';
  $('sharingList').replaceChildren(
    ...sharing.members.map(m=>row(m.email,'Pode ver e editar','Remover',async()=>{
      await api('/api/sharing/revoke',{method:'POST',body:{member:m.id}});await renderAccount();message('accountMessage','Acesso removido no servidor. A pessoa não pode mais consultar nem alterar esta carteira.');
    },{remove:true})),
    ...sharing.invites.map(i=>row(i.email,'Convite pendente · válido por 48 h','Cancelar',async()=>{
      await api('/api/sharing/revoke',{method:'POST',body:{invite:i.id}});await renderAccount();
    },{remove:true})));
  if(!sharing.members.length&&!sharing.invites.length&&sharing.role==='owner')$('sharingList').append(row('Só você tem acesso','Nenhum convite pendente.'));
  $('versionList').replaceChildren(...versions.versions.slice(0,5).map(v=>row(
    new Date(v.created*1000).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}),
    v.reason,sharing.role==='owner'?'Restaurar':null,async()=>{
      await requireSaved();
      const modal=$('restoreDialog');modal.returnValue='';modal.showModal();
      const accepted=await new Promise(resolve=>modal.addEventListener('close',()=>resolve(modal.returnValue==='restore'),{once:true}));
      if(!accepted)return;
      const snapshot=await api('/api/app/carteiras?id=eq.'+wallet);
      await api('/api/versions/restore',{method:'POST',body:{version:v.id,revision:snapshot[0].prefs.revision}});
      clearCache('finace-teste:'+session.user.id+':'+wallet+':');resetFrame();await renderAccount();message('accountMessage','Versão restaurada. O estado anterior também foi preservado.');
    })));
  if(!versions.versions.length)$('versionList').append(row('Nenhuma alteração ainda','A primeira edição gera uma versão anterior automaticamente.'));
}
async function showAccount(){
  const pending=await checkpoint();await refreshSession();await renderAccount();screen('account');
  message('accountMessage',pending?'Há alterações locais aguardando sincronização. Volte à carteira e toque em Reconectar.':'');
}
async function requestCode(){
  const result=await api('/api/auth/request',{method:'POST',body:{email:$('email').value}});
  challenge=result.challenge;$('code').value='';
  $('demoCodeBox').hidden=!(demo()&&result.simulated===true);$('shownCode').textContent=demo()&&result.simulated===true?result.demo_code:'';
  resendUntil=Date.now()+config.resend_seconds*1000;updateResend();
  $('emailForm').hidden=true;$('codeForm').hidden=false;
  $('stepLabel').textContent='02 / CONFIRME SEU ACESSO';$('accessTitle').textContent='Um passo e pronto.';
  $('accessSubtitle').textContent=(demo()?'Código de teste para ':'Confira o código enviado para ')+$('email').value.trim().toLowerCase()+'.';
  $('code').focus();
}
$('emailForm').onsubmit=e=>{e.preventDefault();action(e.submitter,'loginMessage',requestCode);};
$('resend').onclick=()=>action($('resend'),'loginMessage',requestCode);
$('fillCode').onclick=()=>{$('code').value=$('shownCode').textContent;$('code').focus();};
$('changeEmail').onclick=()=>{loginScreen();$('email').focus();};
$('codeForm').onsubmit=e=>{e.preventDefault();action(e.submitter,'loginMessage',async()=>{
  await api('/api/auth/verify',{method:'POST',body:{challenge,code:$('code').value}});
  clearCache();await refreshSession();channel?.postMessage({type:'changed'});showApp();
});};
document.querySelectorAll('[data-email]').forEach(button=>button.onclick=()=>action(button,'loginMessage',async()=>{
  $('email').value=button.dataset.email;await requestCode();
}));
$('emptyAccount').onclick=()=>{
  loginScreen();$('email').value='nova-'+crypto.randomUUID().slice(0,6)+'@finace.test';$('email').focus();
  message('loginMessage','Este e-mail fictício vai criar uma carteira vazia. Você poderá importar um JSON depois de entrar.');
};
$('backToApp').onclick=()=>showApp();
$('openImport').onclick=()=>showApp('proto:import');
$('exportBackup').onclick=()=>showApp('proto:backup');
$('logout').onclick=()=>action($('logout'),'accountMessage',async()=>{
  await requireSaved();await api('/api/auth/logout',{method:'POST',body:{}});
  clearCache();channel?.postMessage({type:'changed'});loginScreen('Você saiu da conta. Os dados confirmados continuam no servidor local de teste.');
});
$('inviteForm').onsubmit=e=>{e.preventDefault();action(e.submitter,'accountMessage',async()=>{
  await api('/api/sharing/invite',{method:'POST',body:{email:$('inviteEmail').value}});await renderAccount();
  message('accountMessage',demo()?'Convite criado. Entre com a conta convidada para aceitar. Nenhum e-mail real foi enviado.':'Convite disponível na conta destinatária ao entrar. Este convite não envia uma mensagem de e-mail.');
});};
$('openDelete').onclick=()=>action($('openDelete'),'accountMessage',async()=>{
  await requireSaved();deleteChallenge=null;$('deleteForm').reset();message('deleteMessage');
  $('deleteVerification').hidden=true;$('deleteConfirmation').hidden=true;$('requestDeleteCode').hidden=false;$('deleteDialog').showModal();
});
$('requestDeleteCode').onclick=()=>action($('requestDeleteCode'),'deleteMessage',async()=>{
  const result=await api('/api/auth/request',{method:'POST',body:{email:session.user.email,purpose:'delete'}});
  deleteChallenge=result.challenge;$('deleteDemoCode').textContent='Código da caixa de entrada simulada: '+result.demo_code;
  $('deleteVerification').hidden=false;$('deleteCode').focus();
});
$('verifyDeleteCode').onclick=()=>action($('verifyDeleteCode'),'deleteMessage',async()=>{
  await api('/api/auth/verify',{method:'POST',body:{challenge:deleteChallenge,code:$('deleteCode').value}});
  $('deleteVerification').hidden=true;$('requestDeleteCode').hidden=true;$('deleteConfirmation').hidden=false;$('deleteText').focus();
});
$('deleteForm').onsubmit=e=>{e.preventDefault();action(e.submitter,'deleteMessage',async()=>{
  await requireSaved();await api('/api/account/delete',{method:'POST',body:{confirmation:$('deleteText').value}});
  $('deleteDialog').close();clearCache();channel?.postMessage({type:'changed'});loginScreen('Conta de teste e dados associados excluídos deste servidor local.');
});};
$('cancelDelete').onclick=()=>$('deleteDialog').close();
addEventListener('message',async e=>{
  if(e.origin!==location.origin||e.source!==$('appFrame').contentWindow)return;
  if(e.data?.type==='proto:ready'){
    appReady=true;if(pendingAction){sendFrame(pendingAction);pendingAction=null;}return;
  }
  if(e.data?.type==='proto:checkpoint-result'){
    checkpoints.get(e.data.id)?.(!!e.data.pending);checkpoints.delete(e.data.id);return;
  }
  if(e.data?.type==='proto:account'){
    try{await showAccount();}catch(error){message('accountMessage',error.message);screen('account');}return;
  }
  if(e.data?.type==='proto:session-ended'){
    resetFrame();
    try{await refreshSession();await renderAccount();screen('account');message('accountMessage','O acesso à carteira foi encerrado ou revogado. Selecione uma carteira disponível.');}
    catch{clearCache();loginScreen('Sua sessão terminou. Entre novamente.');}
  }
});
channel?.addEventListener('message',async()=>{
  resetFrame();try{await refreshSession();await renderAccount();screen('account');}
  catch{clearCache();loginScreen('A sessão mudou em outra aba. Entre novamente.');}
});
async function verifyCurrentSession(){
  if(!session||document.hidden)return;
  try{
    const next=await api('/api/session');
    if(next.user.id!==session.user.id){resetFrame();clearCache();session=next;wallet=null;await refreshSession();await renderAccount();screen('account');}
    else if(!next.wallets.some(w=>w.id===wallet)){resetFrame();session=next;wallet=next.wallets[0]?.id;await renderAccount();screen('account');message('accountMessage','O acesso à carteira compartilhada foi removido.');}
  }catch(error){if(error.status===401){clearCache();loginScreen('Sua sessão terminou. Entre novamente.');}}
}
setInterval(verifyCurrentSession,15000);
setInterval(updateResend,1000);
document.addEventListener('visibilitychange',verifyCurrentSession);
addEventListener('pageshow',verifyCurrentSession);
(async()=>{
  try{
    config=await api('/api/config');configureAccess();await refreshSession();showApp();
  }catch(e){
    const note=e.status===401?(config.configured?'':'O login real aguarda a configuração do envio de e-mail. Nenhum código foi enviado.'):e.message;
    loginScreen(note);
  }
})();
