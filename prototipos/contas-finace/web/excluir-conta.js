'use strict';
const deleteElement=id=>document.getElementById(id);
let deleteConfig=null,webChallenge=null,deleteSession=null;
async function deletionAPI(path,body){
  const response=await fetch('/api/'+path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',
    headers:{'Content-Type':'application/json','X-Prototype':'local','X-CSRF-Token':deleteSession?.csrf||''},
    ...(body?{body:JSON.stringify(body)}:{})});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'Não foi possível concluir. Tente novamente.');
  return data;
}
function deletionStep(id){
  for(const step of ['deleteEmailStep','deleteCodeStep','deleteFinalStep','deleteDoneStep'])deleteElement(step).hidden=step!==id;
  deleteElement('webDeleteMessage').textContent='';
}
function deletionForm(id,handler){
  deleteElement(id).onsubmit=async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    deleteElement('webDeleteMessage').textContent='';
    try{await handler();}catch(error){deleteElement('webDeleteMessage').textContent=error.message;}
    finally{button.disabled=false;}
  };
}
deletionForm('webDeleteRequest',async()=>{
  const result=await deletionAPI('account/deletion/request',{email:deleteElement('webDeleteEmail').value});
  webChallenge=result.challenge;deleteElement('webDeleteCode').value='';
  deleteElement('webDeleteDemo').hidden=!(deleteConfig?.auth_mode==='demo'&&result.simulated);
  deleteElement('webDeleteDemo').textContent=result.simulated?'Código fictício para este teste: '+result.demo_code:'';
  deletionStep('deleteCodeStep');deleteElement('webDeleteCode').focus();
});
deletionForm('webDeleteVerify',async()=>{
  await deletionAPI('account/deletion/verify',{challenge:webChallenge,code:deleteElement('webDeleteCode').value});
  deleteElement('webDeleteCode').value='';deleteElement('webDeleteDemo').textContent='';
  deleteSession=await deletionAPI('session');
  deleteElement('webDeleteOwner').textContent='Você está excluindo a conta '+deleteSession.user.email+'.';
  deletionStep('deleteFinalStep');deleteElement('webDeleteText').focus();
});
deletionForm('webDeleteConfirm',async()=>{
  await deletionAPI('account/delete',{confirmation:deleteElement('webDeleteText').value});
  for(const storage of [localStorage,sessionStorage]){
    for(let i=storage.length-1;i>=0;i--){const key=storage.key(i);if(key?.startsWith('finace-teste:')||key?.startsWith('finace-conta:'))storage.removeItem(key);}
  }
  deleteSession=null;deleteElement('webDeleteText').value='';deletionStep('deleteDoneStep');
  if(typeof BroadcastChannel==='function'){const channel=new BroadcastChannel('finace-prototipo-contas');channel.postMessage({type:'changed'});channel.close();}
});
deleteElement('webDeleteRestart').onclick=()=>{webChallenge=null;deleteElement('webDeleteCode').value='';deletionStep('deleteEmailStep');};
(async()=>{
  try{
    deleteConfig=await deletionAPI('config');
    if(!deleteConfig.account_deletion_available){
      deleteElement('webDeleteRequest').querySelector('button').disabled=true;
      deleteElement('webDeleteMessage').textContent='A exclusão de conta aguarda a configuração deste ambiente. Você pode consultar o suporte abaixo.';
    }
  }catch{deleteElement('webDeleteMessage').textContent='Não foi possível carregar este ambiente. Atualize a página para tentar novamente.';}
})();
