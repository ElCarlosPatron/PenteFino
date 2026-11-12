(function(){
  const copyText = async (value) => {
    try { await navigator.clipboard.writeText(value); return true; }
    catch (_) {
      const ta=document.createElement('textarea');ta.value=value;document.body.appendChild(ta);ta.select();
      const worked=document.execCommand('copy');ta.remove();return worked;
    }
  };
  document.querySelectorAll('[data-copy],[data-copy-from]').forEach(button => {
    button.addEventListener('click', async () => {
      const id=button.dataset.copyFrom;
      const value=id ? document.getElementById(id)?.value : button.dataset.copy;
      if(value && await copyText(value)) {const old=button.textContent;button.textContent='Copiado ✓';setTimeout(()=>button.textContent=old,1800);}
    });
  });
  const input=document.querySelector('.quantity-input input');
  if(input){
    document.querySelectorAll('.qty-adjust').forEach(button=>button.addEventListener('click',()=>{
      const value=Number.parseInt(input.value,10)||0;
      input.value=Math.max(0,value+Number(button.dataset.adjust));
    }));
  }
  const panel=document.querySelector('[data-poll-url]');
  if(panel){
    let previouslyReady=panel.dataset.reloadOnReady==='0';
    async function refresh(){
      if(document.hidden)return;
      try{
        const response=await fetch(panel.dataset.pollUrl,{credentials:'same-origin',cache:'no-store'});
        if(!response.ok)return;
        const stats=await response.json();
        if(stats.ready!==previouslyReady){window.location.reload();return;}
        document.getElementById('reviewed-total').textContent=stats.reviewed;
        document.getElementById('finished-total').textContent=stats.finished+'/'+stats.phones.length;
        document.getElementById('overall-percent').textContent=stats.percentage+'%';
        document.getElementById('overall-bar').style.width=stats.percentage+'%';
        stats.phones.forEach(ph=>{
          const node=document.getElementById('phone-'+ph.slot);if(!node)return;
          node.querySelector('[data-count]').textContent=(ph.reviewed||0)+'/'+ph.total;
          node.querySelector('[data-bar]').style.width=(ph.total?100*(ph.reviewed||0)/ph.total:0)+'%';
          const tag=node.querySelector('[data-status]');
          const status=ph.finished_at ? (ph.pending?'Finalizado antecipadamente':'Finalizado') : ph.operator?'Em andamento':'Disponível';
          if(tag.textContent.trim()!==status){window.location.reload();}
        });
      }catch(_){/* conexão instável: mantém o painel renderizado */}
    }
    setInterval(refresh,8000);
  }
})();
