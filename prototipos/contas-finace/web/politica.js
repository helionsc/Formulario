'use strict';
(async()=>{
  try{
    const response=await fetch('/api/config',{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw new Error();
    const config=await response.json(),site=config.site||{};
    const local=config.auth_mode==='demo',cloud=!!config.cloud_wallet;
    document.querySelectorAll('[data-local]').forEach(el=>el.hidden=!local);
    document.querySelectorAll('[data-live]').forEach(el=>el.hidden=local);
    document.querySelectorAll('[data-cloud]').forEach(el=>el.hidden=!cloud);
    document.querySelectorAll('[data-device]').forEach(el=>el.hidden=cloud);
    document.querySelectorAll('[data-responsible]').forEach(el=>el.textContent=site.responsible||'Responsável a confirmar antes da publicação');
    document.querySelectorAll('[data-version]').forEach(el=>el.textContent=site.version||'Prévia');
    document.querySelectorAll('[data-support]').forEach(el=>{
      if(site.support_email){el.textContent=site.support_email;el.href='mailto:'+site.support_email;}
      else{el.textContent='E-mail público de suporte a confirmar';el.removeAttribute('href');}
    });
    document.querySelectorAll('[data-contact-pending]').forEach(el=>el.hidden=!!(site.responsible&&site.support_email));
    document.querySelectorAll('[data-mode]').forEach(el=>el.textContent=local?'PRÉVIA LOCAL · CONTAS FICTÍCIAS':config.production_wallet?'CONTA FINACE':'PRÉVIA · CONTA DE TESTE');
    const status=document.getElementById('legalStatus');
    if(status)status.textContent='Informações do ambiente carregadas.';
  }catch{
    const status=document.getElementById('legalStatus');
    if(status)status.textContent='Conecte-se à prévia para conferir as informações deste ambiente.';
  }
})();
