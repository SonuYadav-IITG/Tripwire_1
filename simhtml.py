"""HTML for the simulated Alexa+ experience (served at /sim when TRIPWIRE_SIM=1). All dynamic text uses textContent."""

SIM_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Tripwire: simulated Alexa+</title>
<style>
:root{--bg:#f6f5f1;--card:#fff;--ink:#1c1b19;--mute:#6b6860;--line:#e3e0d8;--acc:#0b6bcb;--ok:#2f7d4f;--warn:#b7791f;--bad:#c0392b;--bub:#eaf2fc;--bar:#e9e6de;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15150f;--card:#1f1f18;--ink:#f1efe8;--mute:#a09d92;--line:#33322a;--acc:#6db1ff;--ok:#6fcf97;--warn:#f2c14e;--bad:#ff7a6b;--bub:#1d2a3a;--bar:#2b2a22;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:env(safe-area-inset-top,0) 0 env(safe-area-inset-bottom,0)}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
.ban{background:color-mix(in srgb,var(--warn) 18%,var(--card));border:1px solid var(--warn);border-radius:10px;padding:8px 12px;font-size:13px;margin-bottom:12px}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-bottom:12px}
h1{font-size:21px;margin:0}.date{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:6px 14px;font-weight:600}
.grid{display:grid;grid-template-columns:1.1fr .9fr;gap:14px}@media(max-width:820px){.grid{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}
h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);margin:0 0 10px}
#log{height:340px;overflow:auto;padding-right:4px}
.b{border-radius:14px;padding:9px 13px;margin:0 0 9px;max-width:92%;white-space:pre-wrap}.me{background:var(--bub);margin-left:auto}.al{border:1px solid var(--line)}
.who{font-size:11px;font-weight:700;color:var(--mute)}.tool{font:12px ui-monospace,Menlo,Consolas,monospace;color:var(--acc);margin:-4px 0 9px}
.in{display:flex;gap:8px;margin-top:10px}input[type=text]{flex:1;font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
button{font:inherit;font-weight:600;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:9px 14px;cursor:pointer}button.p{background:var(--acc);color:#fff;border-color:var(--acc)}
button:focus-visible,input:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.chips button{font-weight:500;font-size:13px;padding:5px 10px}
.opt{font-size:13px;color:var(--mute);margin-top:8px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.dec{border:1px solid var(--line);border-radius:12px;padding:10px;margin-bottom:10px}.dec.revisit{border-color:var(--bad);box-shadow:0 0 0 3px color-mix(in srgb,var(--bad) 18%,transparent)}
.dh{display:flex;justify-content:space-between;font-weight:600;text-transform:capitalize}.badge{font-size:11px;font-weight:700;text-transform:uppercase;border:1px solid currentColor;border-radius:99px;padding:1px 8px}
.active{color:var(--ok)}.revisit{color:var(--bad)}.ch{color:var(--mute);font-size:13px}.tw{margin-top:7px;font-size:14px}.row{display:flex;justify-content:space-between;gap:8px}
.bar{height:8px;border-radius:99px;background:var(--bar);margin-top:4px;overflow:hidden}.fill{height:100%;background:var(--ok);transition:width .6s}.fill.tripped{background:var(--bad)}
.st{font-size:12px;font-weight:700;text-transform:uppercase}.st.armed{color:var(--ok)}.st.tripped,.st.pending{color:var(--bad)}
</style></head><body><div class="wrap">
<div class="ban"><b>Simulated Alexa+ experience.</b> Not a real Alexa device. Simple routing rules stand in for Alexa+'s AI and call the same
Tripwire logic the MCP server exposes; every answer and every saved change comes from the real Tripwire code.</div>
<header><h1>🪤 Tripwire <span class="ch">· simulated Alexa+</span></h1>
<div><span class="date" id="date"></span> <button id="skip" title="Simulate time passing">Skip 7 days ⏩</button></div></header>
<div class="grid">
<section class="panel"><h2>Talk to Alexa+</h2><div id="log" aria-live="polite"></div>
<div class="in"><input id="q" type="text" placeholder="Type, or press 🎤 and speak…" autocomplete="off" aria-label="What you say to Alexa"><button id="mic" title="Speak" aria-label="Speak">🎤</button><button id="go" class="p">Send</button></div>
<div class="opt"><label><input type="checkbox" id="tts"> Speak answers aloud</label><span id="hint"></span></div>
<div class="chips" id="chips"></div></section>
<section class="panel"><h2>What Tripwire remembers</h2><div id="mem"></div></section></div></div>
<script>
const $=id=>document.getElementById(id),fix=s=>String(s).replace(/(\w)'(\w)/g,"$1\u2019$2");
const EX=["Alexa, we're going with the 200 megabit internet plan because it's cheapest. We'd switch if the price goes above $50 or if outages hit more than twice a month. Check back in three months.",
"We're getting the grey sofa because it's comfy. We'd return it if the price drops below $300.",
"The provider emailed that our internet price goes to $48 next month.","The provider just raised our internet price to $55.",
"What should I look at?","Why did we pick that internet plan?","Keep it, but move the price limit to $60.","The sofa is on sale. The price dropped to $250."];
function add(cls,who,text,tool){const d=document.createElement("div");d.className="b "+cls;const w=document.createElement("div");w.className="who";w.textContent=who;
 const t=document.createElement("div");t.textContent=fix(text);d.append(w,t);$("log").append(d);
 if(tool){const x=document.createElement("div");x.className="tool";x.textContent="→ tool: "+tool;$("log").append(x)}$("log").scrollTop=1e9}
function gauge(t){const r=document.createElement("div");r.className="tw";
 const top=document.createElement("div");top.className="row";const a=document.createElement("span");a.textContent=fix(t.d);const s=document.createElement("span");s.className="st "+t.state;s.textContent=t.state;top.append(a,s);r.append(top);
 if(t.v!=null){const b=document.createElement("div");b.className="bar";const f=document.createElement("div");f.className="fill "+(t.state==="tripped"?"tripped":"");
  let p=0;if(t.obs!=null){p=t.op.startsWith(">")?t.obs/t.v:t.v/t.obs}f.style.width=Math.max(0,Math.min(1,p))*100+"%";b.append(f);r.append(b);
  const c=document.createElement("div");c.className="ch";c.textContent="limit "+t.v+(t.obs!=null?" · seen "+t.obs:"");r.append(c)}return r}
async function mem(){const s=await (await fetch("/sim/state")).json();$("date").textContent="📅 "+s.date;const m=$("mem");m.replaceChildren();
 if(!s.decisions.length){const e=document.createElement("div");e.className="ch";e.textContent="Nothing on watch yet.";m.append(e)}
 for(const d of s.decisions){const c=document.createElement("div");c.className="dec "+d.status;const h=document.createElement("div");h.className="dh";
  const n=document.createElement("span");n.textContent=d.title;const bd=document.createElement("span");bd.className="badge "+d.status;bd.textContent=d.status==="revisit"?"needs a look":d.status;h.append(n,bd);
  const ch=document.createElement("div");ch.className="ch";ch.textContent="chose: "+fix(d.choice);c.append(h,ch);d.tripwires.forEach(t=>c.append(gauge(t)));m.append(c)}}
async function post(u,b){const r=await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});return r.json()}
async function send(text){text=(text||$("q").value).trim();if(!text)return;$("q").value="";add("me","YOU",text);
 try{const r=await post("/sim/say",{utterance:text});add("al","ALEXA+",r.spoken||"Sorry, something went wrong.",r.tool);
  if($("tts").checked&&window.speechSynthesis)speechSynthesis.speak(new SpeechSynthesisUtterance(fix(r.spoken||"")))}catch(e){add("al","ALEXA+","I can't reach Tripwire right now.")}await mem()}
$("go").onclick=()=>send();$("q").addEventListener("keydown",e=>{if(e.key==="Enter")send()});
$("skip").onclick=async()=>{await post("/sim/advance",{days:7});await mem()};
EX.forEach(x=>{const b=document.createElement("button");b.textContent=fix(x.length>46?x.slice(0,44)+"…":x);b.title=x;b.onclick=()=>send(x);$("chips").append(b)});
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
if(SR){const r=new SR();r.lang="en-US";r.onresult=e=>{$("q").value=e.results[0][0].transcript;send()};r.onend=()=>$("mic").textContent="🎤";
 $("mic").onclick=()=>{$("mic").textContent="…";try{r.start()}catch(e){}}}else{$("mic").hidden=true;$("hint").textContent="(voice input needs Chrome or Edge)"}
mem();
</script></body></html>"""
