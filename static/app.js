document.querySelectorAll('input[type="file"]').forEach(input=>input.addEventListener('change',()=>{const label=input.closest('.file-picker');if(label&&input.files.length)label.childNodes[0].textContent='✓  '+input.files[0].name+'  ';}));

const modal=document.getElementById('app-modal');
let pendingForm=null,pendingSubmitter=null,pendingLink=null,pendingQuizStart=false,pendingQuizExit=false,pendingQuizIncomplete=false;
function openModal(title,message,confirmLabel='Xác nhận',danger=false){
  if(!modal)return;
  document.getElementById('modal-title').textContent=title;
  document.getElementById('modal-message').textContent=message;
  const ok=document.getElementById('modal-confirm');
  ok.textContent=confirmLabel;
  ok.classList.toggle('btn-danger-confirm',danger);
  modal.hidden=false;document.body.classList.add('modal-open');
  requestAnimationFrame(()=>modal.classList.add('visible'));
  document.getElementById('modal-cancel').focus();
}
function closeModal(){if(!modal)return;modal.classList.remove('visible');document.body.classList.remove('modal-open');setTimeout(()=>{modal.hidden=true;},160);pendingForm=null;pendingSubmitter=null;pendingLink=null;}
function cancelCurrentModal(){const wasStart=pendingQuizStart;pendingQuizStart=false;pendingQuizExit=false;pendingQuizIncomplete=false;const leaveUrl=document.getElementById('leave-quiz')?.dataset.leaveUrl;closeModal();if(wasStart&&leaveUrl)location.href=leaveUrl;}
document.addEventListener('submit',event=>{
  const form=event.target;
  if(!(form instanceof HTMLFormElement))return;
  if(form.action.endsWith('/admin/support-settings'))return;
  if(form.action.endsWith('/feedback'))return;
  const isAdminForm=location.pathname.startsWith('/admin');
  if(!isAdminForm&& !form.dataset.confirm)return;
  if(form.dataset.modalConfirmed==='1'){delete form.dataset.modalConfirmed;return;}
  event.preventDefault();pendingForm=form;pendingSubmitter=event.submitter;
  const action=event.submitter?.value||'';
  let title=form.dataset.confirmTitle||'Xác nhận thao tác',message=form.dataset.confirm||'Bạn muốn lưu thay đổi này?';
  let label=form.dataset.confirmLabel||'Xác nhận',danger=false;
  if(!form.dataset.confirm){
    if(action==='delete'){title='Xác nhận xóa';message='Dữ liệu đã xóa sẽ không thể khôi phục. Bạn có muốn tiếp tục?';label='Xóa';danger=true;}
    else if(action==='approve'){title='Duyệt tài liệu';message='Tài liệu sẽ được hiển thị cho học viên. Bạn xác nhận duyệt?';label='Duyệt';}
    else if(form.enctype==='multipart/form-data'){title='Tải tài liệu và xử lý';message='Hệ thống sẽ lưu tệp và nhập các câu trắc nghiệm nhận diện được. Tiếp tục?';label='Tải lên';}
    else if(form.querySelector('[name="action"][value="add"]')){title='Tạo mới';message='Xác nhận thêm nội dung mới vào hệ thống?';label='Tạo mới';}
  }
  openModal(title,message,label,danger);
});
document.getElementById('modal-confirm')?.addEventListener('click',()=>{
  const form=pendingForm,submitter=pendingSubmitter,link=pendingLink;
  if(pendingQuizStart){pendingQuizStart=false;quizStarted=true;closeModal();startExamTimer();}
  else if(pendingQuizExit){pendingQuizExit=false;quizSubmitted=true;document.getElementById('exit-early').value='1';closeModal();quizForm.submit();}
  else if(pendingQuizIncomplete){pendingQuizIncomplete=false;quizSubmitted=true;document.getElementById('incomplete-submit').value='1';closeModal();quizForm.submit();}
  else if(form){form.dataset.modalConfirmed='1';closeModal();form.requestSubmit(submitter||undefined);}
  else if(link){if(quizForm)quizSubmitted=true;location.href=link;closeModal();}
  else closeModal();
});
document.getElementById('modal-cancel')?.addEventListener('click',cancelCurrentModal);
modal?.addEventListener('click',event=>{if(event.target===modal)cancelCurrentModal();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&modal&&!modal.hidden)cancelCurrentModal();});
const feedbackModal=document.getElementById('feedback-modal');
const closeFeedback=()=>{if(!feedbackModal)return;feedbackModal.classList.remove('visible');document.body.classList.remove('modal-open');setTimeout(()=>feedbackModal.hidden=true,160);};
document.getElementById('feedback-trigger')?.addEventListener('click',()=>{feedbackModal.hidden=false;requestAnimationFrame(()=>{feedbackModal.classList.add('visible');document.body.classList.add('modal-open');feedbackModal.querySelector('input,textarea')?.focus();});});
document.getElementById('feedback-close')?.addEventListener('click',closeFeedback);
feedbackModal?.addEventListener('click',event=>{if(event.target===feedbackModal)closeFeedback();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&feedbackModal&&!feedbackModal.hidden)closeFeedback();});

const supportSettingsModal=document.getElementById('support-settings-modal');
const closeSupportSettings=()=>{if(!supportSettingsModal)return;supportSettingsModal.classList.remove('visible');document.body.classList.remove('modal-open');setTimeout(()=>supportSettingsModal.hidden=true,160);};
document.getElementById('help-config-trigger')?.addEventListener('click',()=>{supportSettingsModal.hidden=false;requestAnimationFrame(()=>{supportSettingsModal.classList.add('visible');document.body.classList.add('modal-open');supportSettingsModal.querySelector('input,a')?.focus();});});
document.getElementById('support-settings-close')?.addEventListener('click',closeSupportSettings);
supportSettingsModal?.addEventListener('click',event=>{if(event.target===supportSettingsModal)closeSupportSettings();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&supportSettingsModal&&!supportSettingsModal.hidden)closeSupportSettings();});

const guestThemePanel=document.getElementById('guest-theme-panel');
const guestThemeToggle=document.getElementById('guest-theme-toggle');
const guestAccentNames=['pink','blue','purple','green','orange','teal','red','yellow','indigo','cyan'];
const guestModeNames=['light','dark','auto','pink','blue'];
function applyGuestAppearance(accent,mode){
  const safeAccent=guestAccentNames.includes(accent)?accent:'purple';
  const safeMode=guestModeNames.includes(mode)?mode:'light';
  document.body.classList.remove(...guestAccentNames.map(name=>'accent-'+name),...guestModeNames.map(name=>'mode-'+name));
  document.body.classList.add('accent-'+safeAccent,'mode-'+safeMode);
  document.querySelectorAll('[data-guest-accent]').forEach(button=>button.classList.toggle('active',button.dataset.guestAccent===safeAccent));
  document.querySelectorAll('[data-guest-mode]').forEach(button=>button.classList.toggle('active',button.dataset.guestMode===safeMode));
  try{localStorage.setItem('edunova-appearance',JSON.stringify({accent:safeAccent,mode:safeMode}));}catch(_error){}
}
try{const savedAppearance=JSON.parse(localStorage.getItem('edunova-appearance')||'null');if(savedAppearance)applyGuestAppearance(savedAppearance.accent,savedAppearance.mode);}catch(_error){}
guestThemeToggle?.addEventListener('click',()=>{guestThemePanel.hidden=!guestThemePanel.hidden;guestThemeToggle.setAttribute('aria-expanded',String(!guestThemePanel.hidden));});
document.getElementById('guest-theme-close')?.addEventListener('click',()=>{guestThemePanel.hidden=true;guestThemeToggle?.setAttribute('aria-expanded','false');});
document.getElementById('guest-theme-reset')?.addEventListener('click',()=>{try{localStorage.removeItem('edunova-appearance');}catch(_error){}location.reload();});
document.querySelectorAll('[data-guest-accent]').forEach(button=>button.addEventListener('click',()=>applyGuestAppearance(button.dataset.guestAccent,document.body.className.match(/mode-(light|dark|auto)/)?.[1]||'light')));
document.querySelectorAll('[data-guest-mode]').forEach(button=>button.addEventListener('click',()=>applyGuestAppearance(document.body.className.match(/accent-(pink|blue|purple|green|orange|teal|red|yellow|indigo|cyan)/)?.[1]||'purple',button.dataset.guestMode)));

document.querySelectorAll('.reveal-password').forEach(button=>button.addEventListener('click',()=>{const input=button.parentElement.querySelector('input');input.type=input.type==='password'?'text':'password';button.textContent=input.type==='password'?'◉':'⊙';}));

document.querySelectorAll('[data-question-card][data-multi="1"]').forEach(card=>{const limit=Number(card.dataset.limit);card.querySelectorAll('input[type=checkbox]').forEach(box=>box.addEventListener('change',()=>{if(card.querySelectorAll('input:checked').length>limit){box.checked=false;openModal('Số lựa chọn đã đủ','Câu này yêu cầu chọn '+limit+' đáp án.','Đã hiểu');}}));});
const quizForm=document.getElementById('quiz-form');
if(quizForm)document.body.classList.add('quiz-active');
const quizNavigator=document.getElementById('quiz-navigator');
if(quizForm&&quizNavigator){const toggle=document.getElementById('quiz-nav-toggle'),close=document.getElementById('quiz-nav-close'),cards=[...quizForm.querySelectorAll('[data-question-card]')],answered=document.getElementById('quiz-answered-count'),answeredSummary=document.getElementById('quiz-answered-summary'),unansweredSummary=document.getElementById('quiz-unanswered-summary');const refreshNavigator=()=>{let done=0;cards.forEach((card,index)=>{const complete=card.querySelectorAll('input:checked').length===Number(card.dataset.limit);if(complete)done++;quizNavigator.querySelector('[data-quiz-go="'+index+'"]').classList.toggle('done',complete);});if(answered)answered.textContent=done;if(answeredSummary)answeredSummary.textContent=done;if(unansweredSummary)unansweredSummary.textContent=cards.length-done;};const closeNavigator=()=>{quizNavigator.hidden=true;toggle?.setAttribute('aria-expanded','false');};toggle?.addEventListener('click',()=>{quizNavigator.hidden=!quizNavigator.hidden;toggle.setAttribute('aria-expanded',String(!quizNavigator.hidden));refreshNavigator();});close?.addEventListener('click',closeNavigator);quizNavigator.querySelectorAll('[data-quiz-go]').forEach(button=>button.addEventListener('click',()=>{cards[Number(button.dataset.quizGo)]?.scrollIntoView({behavior:'smooth',block:'center'});closeNavigator();}));quizForm.addEventListener('change',refreshNavigator);refreshNavigator();}
let quizSubmitted=false,quizStarted=false;
if(quizForm)quizForm.addEventListener('submit',event=>{const incomplete=[...quizForm.querySelectorAll('[data-question-card]')].filter(card=>card.querySelectorAll('input:checked').length!==Number(card.dataset.limit));if(incomplete.length){event.preventDefault();const blank=incomplete.filter(card=>card.querySelectorAll('input:checked').length===0).length;const details=blank===incomplete.length?blank+' câu chưa được chọn.':blank+' câu bỏ trống và '+(incomplete.length-blank)+' câu chưa chọn đủ đáp án.';pendingQuizIncomplete=true;openModal('Bạn còn câu chưa trả lời',details+' Nếu nộp lúc này, các câu chưa hoàn tất sẽ tính sai.','Nộp bài');return;}quizSubmitted=true;});
if(quizForm){document.getElementById('leave-quiz')?.addEventListener('click',()=>{pendingQuizExit=true;openModal('Nộp bài và thoát?','Câu bạn đã chọn sẽ được chấm; câu chưa chọn tính sai. Điểm số sẽ hiện ngay sau khi xác nhận.','Nộp bài và xem điểm',true);});document.addEventListener('click',event=>{const link=event.target.closest('a[href]');if(!link||quizSubmitted||modal&&!modal.hidden)return;const url=new URL(link.href,location.href);if(url.href===location.href||url.protocol==='mailto:')return;event.preventDefault();pendingQuizExit=true;openModal('Nộp bài và thoát?','Câu bạn đã chọn sẽ được chấm; câu chưa chọn tính sai. Điểm số sẽ hiện ngay sau khi xác nhận.','Nộp bài và xem điểm',true);});window.addEventListener('beforeunload',event=>{if(quizStarted&&!quizSubmitted){event.preventDefault();event.returnValue='';}});pendingQuizStart=true;openModal('Bắt đầu làm bài?','Khi bắt đầu, đồng hồ sẽ chạy nếu đề có giới hạn thời gian. Bạn có thể nộp sớm để xem điểm.','Bắt đầu làm bài');}

const timer=document.getElementById('timer');
let timerInterval=null;
function startExamTimer(){if(!timer||timerInterval)return;let seconds=Number(timer.dataset.minutes)*60;const tick=()=>{const m=Math.floor(seconds/60),s=seconds%60;timer.textContent=String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');if(seconds<=0){quizSubmitted=true;document.getElementById('incomplete-submit').value='1';quizForm.submit();return;}seconds--;};tick();timerInterval=setInterval(tick,1000);}

const settingsForm=document.querySelector('.settings-form');
if(settingsForm){const subject=settingsForm.querySelector('[name="subject_id"]'),week=settingsForm.querySelector('[name="week"]'),minutes=settingsForm.querySelector('[name="minutes"]'),shuffle=settingsForm.querySelector('[name="shuffle"]'),clearPassword=settingsForm.querySelector('[name="clear_password"]');const sync=()=>{const match=[...document.querySelectorAll('.setting-card[data-subject-id]')].find(card=>card.dataset.subjectId===subject.value&&card.dataset.week===week.value);minutes.value=match?match.dataset.minutes:'0';shuffle.checked=!!match&&match.dataset.shuffle==='1';clearPassword.checked=false;};subject.addEventListener('change',sync);week.addEventListener('change',sync);sync();}

document.querySelectorAll('[data-review-filter]').forEach(button=>button.addEventListener('click',()=>{const filter=button.dataset.reviewFilter;document.querySelectorAll('[data-review-filter]').forEach(item=>item.classList.toggle('active',item===button));document.querySelectorAll('#review-list [data-review-status]').forEach(card=>{card.hidden=filter!=='all'&&card.dataset.reviewStatus!==filter;});}));

document.querySelectorAll('[data-subject-icon]').forEach(button=>button.addEventListener('click',()=>{const input=document.getElementById('subject-icon-input');if(!input)return;input.value=button.dataset.subjectIcon;document.querySelectorAll('[data-subject-icon]').forEach(item=>item.classList.toggle('selected',item===button));}));

const bot=document.querySelector('[data-chatbot]');
if(bot){const api=bot.dataset.api,messages=document.getElementById('bot-messages'),form=document.getElementById('bot-form'),input=document.getElementById('bot-input');const add=(text,own=false,link=null,label=null)=>{const row=document.createElement('article');row.className='bot-message'+(own?' own':'');const icon=document.createElement('span');icon.textContent=own?'●':'✦';const body=document.createElement('div');const name=document.createElement('b');name.textContent=own?'Bạn':'EduBot';const paragraph=document.createElement('p');paragraph.textContent=text;body.append(name,paragraph);if(link){const anchor=document.createElement('a');anchor.href=link;anchor.textContent=label||'Mở trang';body.append(anchor);}row.append(icon,body);messages.append(row);messages.scrollTop=messages.scrollHeight;};const ask=async question=>{const value=question.trim();if(!value)return;add(value,true);input.value='';try{const res=await fetch(api,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:value})});const data=await res.json();add(data.answer||data.error||'Mình chưa thể trả lời lúc này.',false,data.link,data.label);}catch(_){add('Không thể kết nối với EduBot. Hãy thử lại sau.',false);}};form?.addEventListener('submit',event=>{event.preventDefault();ask(input.value);});input?.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();form.requestSubmit();}});document.querySelectorAll('.bot-suggestions button').forEach(button=>button.addEventListener('click',()=>ask(button.textContent||'')));}

document.querySelector('.chat-tool-photo')?.addEventListener('click',()=>document.getElementById('chat-attachment')?.click());
document.querySelector('.chat-tool-emoji')?.addEventListener('click',()=>{const field=document.getElementById('chat-input');if(!field)return;field.value+=' 😊';field.dispatchEvent(new Event('input'));field.focus();});
const chatRoom=document.querySelector('[data-chat-room]');
if(chatRoom){const api=chatRoom.dataset.api,currentUser=chatRoom.dataset.user,messages=document.getElementById('chat-messages'),form=document.getElementById('chat-form'),input=document.getElementById('chat-input'),count=document.getElementById('chat-count'),attachment=document.getElementById('chat-attachment'),fileName=document.getElementById('chat-file-name');let lastId=0;const nearBottom=()=>messages.scrollHeight-messages.scrollTop-messages.clientHeight<100;const renderReactions=(box,item)=>{const reactions=document.createElement('div');reactions.className='chat-reactions';(item.reactions||[]).forEach(reaction=>{const button=document.createElement('button');button.textContent=reaction.emoji+' '+reaction.count;button.className=reaction.mine?'active':'';button.onclick=()=>react(item.id,reaction.emoji);reactions.append(button);});const picker=document.createElement('div');picker.className='reaction-picker';['❤️','👍','😂','🎉','😮'].forEach(emoji=>{const button=document.createElement('button');button.textContent=emoji;button.onclick=()=>react(item.id,emoji);picker.append(button);});reactions.append(picker);box.append(reactions);};const addMessage=item=>{if(item.id<=lastId)return;const shouldScroll=nearBottom();messages.querySelector('.chat-welcome')?.remove();const row=document.createElement('article');row.className='chat-message'+(item.name===currentUser?' own':'');row.dataset.messageId=item.id;const avatar=document.createElement('span');avatar.className='avatar tiny';if(item.avatar_filename){const image=document.createElement('img');image.src='/chat-media/'+encodeURIComponent(item.avatar_filename);image.alt='';avatar.append(image);}else avatar.textContent=(item.name||'?').charAt(0).toUpperCase();const body=document.createElement('div');body.className='chat-bubble';const meta=document.createElement('div');meta.className='chat-meta';const name=document.createElement('b');name.textContent=item.name;const time=document.createElement('small');time.textContent=item.created_at;meta.append(name,time);body.append(meta);if(item.message){const text=document.createElement('p');text.textContent=item.message;body.append(text);}if(item.attachment_url){const ext=(item.attachment_original||'').split('.').pop().toLowerCase();if(['png','jpg','jpeg','gif','webp'].includes(ext)){const image=document.createElement('img');image.className='chat-image';image.src=item.attachment_url;image.alt=item.attachment_original||'Ảnh đính kèm';body.append(image);}else{const link=document.createElement('a');link.className='chat-file';link.href=item.attachment_url;link.target='_blank';link.textContent='📎 '+(item.attachment_original||'Tệp đính kèm');body.append(link);}}renderReactions(body,item);row.append(avatar,body);messages.append(row);lastId=Math.max(lastId,item.id);if(shouldScroll)messages.scrollTop=messages.scrollHeight;};const updateMessage=item=>{const old=messages.querySelector('[data-message-id="'+item.id+'"]');if(old)old.remove();const cached=lastId;lastId=item.id-1;addMessage(item);lastId=Math.max(cached,item.id);};const react=async(id,emoji)=>{try{const response=await fetch(api+'/'+id+'/reaction',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({emoji})});if(response.ok)updateMessage(await response.json());}catch(_error){}};const poll=async()=>{try{const url=new URL(api,location.href);url.searchParams.set('after',lastId);const response=await fetch(url,{headers:{Accept:'application/json'}});if(response.ok)(await response.json()).forEach(addMessage);}catch(_error){}};poll();setInterval(poll,2500);attachment?.addEventListener('change',()=>fileName.textContent=attachment.files[0]?'📎 '+attachment.files[0].name:'');input.addEventListener('input',()=>count.textContent=input.value.length);input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();form.requestSubmit();}});form.addEventListener('submit',async event=>{event.preventDefault();const message=input.value.trim();if(!message&&!attachment?.files.length)return;const button=form.querySelector('button');button.disabled=true;try{const data=new FormData();data.append('message',message);if(attachment?.files[0])data.append('attachment',attachment.files[0]);const response=await fetch(api,{method:'POST',headers:{Accept:'application/json'},body:data});if(response.ok){addMessage(await response.json());input.value='';attachment.value='';fileName.textContent='';count.textContent='0';}else{const data=await response.json();openModal('Chưa gửi được tin nhắn',data.error||'Vui lòng thử lại.','Đã hiểu');}}catch(_error){openModal('Mất kết nối','Kiểm tra kết nối mạng rồi gửi lại tin nhắn.','Đã hiểu');}finally{button.disabled=false;input.focus();}});}
