(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const COLORS = {fm:'#f2b84b', psg:'#68d6c4', drums:'#ed7587', midi:'#8ea6c4'};
  let project, ctx, masterGain, startedAt = 0, pausedAt = 0, playing = false;
  let timer = null, scheduledUntil = 0, activeNodes = [], buffers = {};
  const trackState = new Map();

  const fmt = (s) => `${Math.floor(s/60)}:${(s%60).toFixed(1).padStart(4,'0')}`;
  const midiHz = (n) => 440 * Math.pow(2, (n-69)/12);
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));

  async function init() {
    project = window.SMD_PROJECT;
    if (!project) throw new Error('project.js did not load');
    $('title').textContent = project.title;
    $('engineNote').textContent = `${project.engine.name} · ${project.engine.accuracy} synthesis`;
    $('total').textContent = fmt(project.duration);
    if (project.assets.reference_vgm) {
      $('reference').innerHTML = `<a href="${encodeURI(project.assets.reference_vgm)}">Reference VGZ</a>`;
    }
    project.tracks.forEach((t,i) => trackState.set(i,{mute:false,solo:false,gain:null,next:0}));
    buildTracks(); inspectTrack(project.tracks.findIndex(t => t.kind === 'fm'));
    resizeCanvas(); draw();
    window.addEventListener('resize', () => { resizeCanvas(); draw(); });
    $('play').addEventListener('click', togglePlay);
    $('stop').addEventListener('click', stop);
    $('master').addEventListener('input', e => { if(masterGain) masterGain.gain.value = +e.target.value; });
    $('timeline').addEventListener('click', seekFromCanvas);
  }

  async function ensureAudio() {
    if (ctx) return;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    masterGain = ctx.createGain(); masterGain.gain.value = +$('master').value; masterGain.connect(ctx.destination);
    for (const [i,state] of trackState) {
      state.gain = ctx.createGain(); state.gain.connect(masterGain);
    }
    await Promise.all(Object.values(project.pcm).map(async meta => {
      try {
        let bytes;
        if (meta.data_base64) {
          const raw=atob(meta.data_base64); bytes=new Uint8Array(raw.length); for(let i=0;i<raw.length;i++) bytes[i]=raw.charCodeAt(i);
        } else {
          bytes=new Uint8Array(await fetch(meta.url).then(r=>r.arrayBuffer()));
        }
        buffers[meta.number] = await ctx.decodeAudioData(bytes.buffer.slice(0));
      } catch(e) { console.warn(e); }
    }));
    refreshMix();
  }

  function refreshMix() {
    if(!ctx) return;
    const anySolo = [...trackState.values()].some(s=>s.solo);
    for(const [i,s] of trackState) {
      const audible = anySolo ? s.solo : !s.mute;
      s.gain.gain.setTargetAtTime(audible ? 0.78 : 0, ctx.currentTime, .012);
    }
  }

  async function togglePlay() {
    await ensureAudio();
    if (ctx.state === 'suspended') await ctx.resume();
    if (playing) { pause(); return; }
    playing = true;
    startedAt = ctx.currentTime - pausedAt;
    scheduledUntil = pausedAt;
    resetTrackCursors(pausedAt);
    $('play').textContent = '❚❚';
    scheduler(); timer = setInterval(scheduler, 60);
    requestAnimationFrame(frame);
  }

  function pause() {
    if(!playing) return;
    pausedAt = getTime(); playing = false; $('play').textContent='▶';
    clearInterval(timer); timer=null; stopNodes();
  }
  function stop() { if(ctx && playing) pause(); pausedAt=0; scheduledUntil=0; resetTrackCursors(0); $('now').textContent=fmt(0); draw(); }
  function seek(t) {
    t = clamp(t,0,project.duration);
    const was = playing; if(was) pause(); pausedAt=t; scheduledUntil=t; resetTrackCursors(t); draw();
    if(was) togglePlay(); else $('now').textContent=fmt(t);
  }
  function getTime() { return playing ? clamp(ctx.currentTime - startedAt, 0, project.duration) : pausedAt; }
  function resetTrackCursors(t) {
    project.tracks.forEach((tr,i) => {
      let lo=0, hi=tr.notes.length;
      while(lo<hi){const m=(lo+hi)>>1;if(tr.notes[m].start < t-.02)lo=m+1;else hi=m;}
      trackState.get(i).next=lo;
    });
  }

  function scheduler() {
    if(!playing) return;
    const songNow=getTime(), horizon=Math.min(project.duration,songNow+.28);
    project.tracks.forEach((tr,i)=>{
      const st=trackState.get(i); let n=st.next;
      while(n<tr.notes.length && tr.notes[n].start < horizon){
        const note=tr.notes[n]; if(note.start >= songNow-.03) scheduleNote(tr,i,note,note.start-songNow+ctx.currentTime); n++;
      } st.next=n;
    });
    scheduledUntil=horizon;
    if(songNow>=project.duration-.01) stop();
  }

  function scheduleNote(track, index, note, at) {
    const dest=trackState.get(index).gain, dur=Math.max(.018,note.duration), vel=note.velocity/127;
    if(track.kind==='fm') return fmVoice(project.patches[String(track.program)], note.pitch, vel, at, dur, dest);
    if(track.kind==='psg') return psgVoice(note.pitch,vel,at,dur,dest);
    if(track.kind==='drums') return drumVoice(note.pitch,vel,at,dest);
    return psgVoice(note.pitch,vel*.55,at,dur,dest);
  }

  // Deliberately lightweight FM preview. It uses real operator ratios/TL and
  // envelope-rate data but WebAudio oscillators rather than a YM2612 core.
  function fmVoice(patch, pitch, velocity, at, dur, dest) {
    if(!patch) return psgVoice(pitch,velocity,at,dur,dest);
    const base=midiHz(pitch), ops=patch.operators;
    const carriers=[
      [3],[3],[3],[3],[1,3],[1,2,3],[1,2,3],[0,1,2,3]
    ][patch.algorithm] || [3];
    const carrierSet=new Set(carriers);
    // Build an expressive approximation: every non-carrier modulates every
    // carrier, weighted by TL; exact topology will later be replaced by ymfm.
    const carrierNodes=[];
    ops.forEach((op,idx)=>{
      if(!carrierSet.has(idx)) return;
      const osc=ctx.createOscillator(), amp=ctx.createGain();
      const ratio=op.multiple===0 ? .5 : op.multiple;
      osc.type='sine'; osc.frequency.setValueAtTime(base*ratio,at);
      envelope(amp.gain, op, velocity*(1-op.total_level/140), at, dur);
      osc.connect(amp); amp.connect(dest); osc.start(at); osc.stop(at+dur+.7);
      activeNodes.push(osc); carrierNodes.push({osc,ratio});
    });
    ops.forEach((op,idx)=>{
      if(carrierSet.has(idx)) return;
      const osc=ctx.createOscillator(), depth=ctx.createGain();
      const ratio=op.multiple===0 ? .5 : op.multiple;
      osc.frequency.setValueAtTime(base*ratio,at); osc.type='sine';
      const tl=Math.pow(10,-op.total_level/38); const fb=1+patch.feedback*.08;
      depth.gain.setValueAtTime(base * (0.15+2.8*tl) * fb,at);
      carrierNodes.forEach(c=>depth.connect(c.osc.frequency));
      osc.connect(depth); osc.start(at); osc.stop(at+dur+.4); activeNodes.push(osc);
    });
  }
  function envelope(param,op,level,at,dur) {
    level=clamp(level,0.002,.7);
    const attack=.003 + Math.pow((31-op.attack_rate)/31,2)*.45;
    const decay=.02 + Math.pow((31-op.decay_rate)/31,2)*1.2;
    const sustain=level*(1-op.sustain_level/17)*(.25+.75*(op.sustain_rate<24));
    const release=.025 + Math.pow((15-op.release_rate)/15,2)*.75;
    param.cancelScheduledValues(at); param.setValueAtTime(.0001,at);
    param.exponentialRampToValueAtTime(Math.max(.001,level),at+attack);
    param.exponentialRampToValueAtTime(Math.max(.0007,sustain),Math.min(at+dur,at+attack+decay));
    param.setValueAtTime(Math.max(.0007,sustain),at+dur);
    param.exponentialRampToValueAtTime(.0001,at+dur+release);
  }
  function psgVoice(pitch,vel,at,dur,dest) {
    const osc=ctx.createOscillator(), gain=ctx.createGain(); osc.type='square'; osc.frequency.value=midiHz(pitch);
    gain.gain.setValueAtTime(.0001,at); gain.gain.linearRampToValueAtTime(.045*vel,at+.004); gain.gain.setValueAtTime(.045*vel,at+Math.max(.005,dur-.015)); gain.gain.linearRampToValueAtTime(.0001,at+dur);
    osc.connect(gain); gain.connect(dest); osc.start(at); osc.stop(at+dur+.02); activeNodes.push(osc);
  }
  function drumVoice(note,vel,at,dest) {
    const isKick=[35,36].includes(note), isSnare=[38,40].includes(note);
    const sampleNo=isKick?1:isSnare?2:null;
    if(sampleNo && buffers[sampleNo]){
      const src=ctx.createBufferSource(),g=ctx.createGain(); src.buffer=buffers[sampleNo];g.gain.value=.7*vel;src.connect(g);g.connect(dest);src.start(at);activeNodes.push(src);return;
    }
    if(isKick){
      const o=ctx.createOscillator(),g=ctx.createGain();o.frequency.setValueAtTime(110,at);o.frequency.exponentialRampToValueAtTime(42,at+.16);g.gain.setValueAtTime(.18*vel,at);g.gain.exponentialRampToValueAtTime(.0001,at+.22);o.connect(g);g.connect(dest);o.start(at);o.stop(at+.23);activeNodes.push(o);return;
    }
    const len=note===46?.22:.075, frames=Math.floor(ctx.sampleRate*len), buf=ctx.createBuffer(1,frames,ctx.sampleRate), data=buf.getChannelData(0);
    for(let i=0;i<frames;i++) data[i]=(Math.random()*2-1)*Math.exp(-i/(frames*.25));
    const src=ctx.createBufferSource(), filt=ctx.createBiquadFilter(),g=ctx.createGain(); src.buffer=buf;filt.type='highpass';filt.frequency.value=note===46?5000:2500;g.gain.value=.12*vel;src.connect(filt);filt.connect(g);g.connect(dest);src.start(at);activeNodes.push(src);
  }
  function stopNodes(){ activeNodes.forEach(n=>{try{n.stop();}catch(e){}}); activeNodes=[]; }

  function buildTracks(){
    const root=$('tracks'); root.innerHTML='';
    project.tracks.forEach((tr,i)=>{
      const row=document.createElement('div');row.className='track-row';row.dataset.index=i;
      const color=COLORS[tr.kind]||COLORS.midi; row.innerHTML=`<div class="track-title"><i class="track-color" style="background:${color}"></i><div class="track-copy"><div class="track-name"></div><div class="track-meta">${tr.notes.length} notes · ${tr.kind.toUpperCase()}</div></div></div><button class="mini mute" title="Mute">M</button><button class="mini solo" title="Solo">S</button>`;
      row.querySelector('.track-name').textContent=tr.name;
      row.addEventListener('click',e=>{if(e.target.tagName!=='BUTTON') inspectTrack(i)});
      row.querySelector('.mute').addEventListener('click',e=>{e.stopPropagation();const s=trackState.get(i);s.mute=!s.mute;e.currentTarget.classList.toggle('on',s.mute);refreshMix();});
      row.querySelector('.solo').addEventListener('click',e=>{e.stopPropagation();const s=trackState.get(i);s.solo=!s.solo;e.currentTarget.classList.toggle('on',s.solo);refreshMix();});
      root.appendChild(row);
    });
  }
  function inspectTrack(i){
    document.querySelectorAll('.track-row').forEach((r,n)=>r.classList.toggle('selected',n===i));
    if(i<0) return; const tr=project.tracks[i], patch=tr.program!=null?project.patches[String(tr.program)]:null;
    $('patchEmpty').hidden=!!patch;$('patch').hidden=!patch;
    if(!patch){$('patchTag').textContent=tr.kind==='psg'?'SN76489 / square preview':tr.kind==='drums'?'PCM + synthesized percussion':'No FM patch';return;}
    $('patchTag').textContent=patch.name;$('patchProgram').textContent=`@${String(patch.program).padStart(3,'0')}`;$('patchAlgorithm').textContent=patch.algorithm;$('patchFeedback').textContent=patch.feedback;
    const ops=$('operators');ops.innerHTML='';patch.operators.forEach(op=>{const d=document.createElement('div');d.className='operator';d.innerHTML=`<h3>OP${op.logical_operator}</h3><div class="op-grid"><span>MUL</span><b>${op.multiple}</b><span>DT</span><b>${op.detune}</b><span>TL</span><b>${op.total_level}</b><span>AR</span><b>${op.attack_rate}</b><span>DR</span><b>${op.decay_rate}</b><span>SR</span><b>${op.sustain_rate}</b><span>SL</span><b>${op.sustain_level}</b><span>RR</span><b>${op.release_rate}</b></div>`;ops.appendChild(d);});
  }

  function resizeCanvas(){const c=$('timeline'), dpr=window.devicePixelRatio||1, w=Math.max(1050,$('timelineScroll').clientWidth), h=Math.max(330,project.tracks.length*30+48);c.style.width=w+'px';c.style.height=h+'px';c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);c._w=w;c._h=h;c._dpr=dpr;}
  function draw(){
    if(!project)return;const c=$('timeline'),x=c.getContext('2d'),dpr=c._dpr||1,w=c._w||c.clientWidth,h=c._h||c.clientHeight;x.setTransform(dpr,0,0,dpr,0,0);x.clearRect(0,0,w,h);
    const label=155,top=34,row=30,plotW=w-label-12,dur=project.duration;
    x.fillStyle='#0f141b';x.fillRect(0,0,w,h);x.fillStyle='#141b24';x.fillRect(0,0,label,h);
    x.font='10px ui-monospace, SFMono-Regular, Menlo, monospace';x.textBaseline='middle';
    const bar=2.4;for(let t=0;t<=dur;t+=bar*4){const px=label+(t/dur)*plotW;x.strokeStyle='#26303c';x.beginPath();x.moveTo(px,0);x.lineTo(px,h);x.stroke();x.fillStyle='#7f8e9f';x.fillText(fmt(t),px+4,14);}
    project.tracks.forEach((tr,i)=>{const y=top+i*row;x.strokeStyle='#202a35';x.beginPath();x.moveTo(0,y+row);x.lineTo(w,y+row);x.stroke();x.fillStyle='#c4ced9';x.fillText(tr.name.slice(0,22),10,y+row/2);const color=COLORS[tr.kind]||COLORS.midi;x.fillStyle=color;const pitches=tr.notes.map(n=>n.pitch),min=Math.min(...pitches),max=Math.max(...pitches),span=Math.max(1,max-min);tr.notes.forEach(n=>{const nx=label+n.start/dur*plotW,nw=Math.max(1.3,n.duration/dur*plotW),ny=y+4+(1-(n.pitch-min)/span)*(row-9);x.globalAlpha=.82;x.fillRect(nx,ny,nw,3.2);});x.globalAlpha=1;});
    const time=getTime(),px=label+time/dur*plotW;x.strokeStyle='#ffffff';x.lineWidth=1.25;x.beginPath();x.moveTo(px,0);x.lineTo(px,h);x.stroke();
    c._geometry={label,plotW,dur};
  }
  function seekFromCanvas(e){const c=$('timeline'),r=c.getBoundingClientRect(),g=c._geometry;if(!g)return;const x=e.clientX-r.left;if(x<g.label)return;seek((x-g.label)/g.plotW*g.dur);}
  function frame(){
    const t=getTime();$('now').textContent=fmt(t);let active=0;project.tracks.forEach(tr=>{for(const n of tr.notes){if(n.start>t)break;if(n.start+n.duration>=t)active++;}});$('activeCount').textContent=`${active} active note${active===1?'':'s'}`;draw();if(playing)requestAnimationFrame(frame);
  }
  init().catch(err=>{$('engineNote').textContent=`Failed to load: ${err.message}`;console.error(err);});
})();
