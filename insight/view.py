# ruff: noqa: E501  (the embedded page template has long CSS and JS lines)
"""Render a guarded `report.json` as ONE self-contained, offline HTML file.

The report holds aggregates derived from NDA data, so the page is a local file and never a hosted
one: no network, no external script, font or style (a CSP meta tag forbids them), and report values
reach the DOM only through `textContent`. The guard runs first, so a report that the builders did not
produce (or a tampered one) is refused and nothing is written.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from insight import guard

_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src 'none'; connect-src 'none'; form-action 'none'"
)

_PAGE = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="__CSP__">
<title>Ticket insight report</title>
<style>
:root{color-scheme:light;--bg:#f1f3f6;--surf:#ffffff;--ink:#22262c;--ink2:#3d4550;--mute:#5f6875;--line:#d9dee5;--hover:#e8ecf1;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;--other:#b9b8b0;
--series:#d2610a;--seq:#d2610a;--on-seq:#1d1c1b;--lo:#f0c9a5;--mid:#d2610a;--hi:#6b2f06;
--accent:#d2610a;--on-accent:#ffffff;--good:#2b8a3e;--on-good:#ffffff;--warn:#c92a2a;--caution:#a67300;
--radius:14px;--shadow:0 1px 2px rgba(60,40,20,.06),0 6px 18px rgba(60,40,20,.06)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#202020;--surf:#292929;--ink:#ececec;--ink2:#cfcfcf;--mute:#aaaaaa;--line:#414141;--hover:#333333;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;--other:#5d5c57;
--series:#ff9a3d;--seq:#ff9a3d;--on-seq:#1d1c1b;--lo:#6a4220;--mid:#ff9a3d;--hi:#ffe2c7;
--accent:#ff9a3d;--on-accent:#1d1c1b;--good:#86d19a;--on-good:#1d1c1b;--warn:#ff8c82;--caution:#e9c75a;
--radius:14px;--shadow:0 1px 0 rgba(255,255,255,.03) inset,0 8px 24px rgba(0,0,0,.25)}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#202020;--surf:#292929;--ink:#ececec;--ink2:#cfcfcf;--mute:#aaaaaa;--line:#414141;--hover:#333333;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;--other:#5d5c57;
--series:#ff9a3d;--seq:#ff9a3d;--on-seq:#1d1c1b;--lo:#6a4220;--mid:#ff9a3d;--hi:#ffe2c7;
--accent:#ff9a3d;--on-accent:#1d1c1b;--good:#86d19a;--on-good:#1d1c1b;--warn:#ff8c82;--caution:#e9c75a;
--radius:14px;--shadow:0 1px 0 rgba(255,255,255,.03) inset,0 8px 24px rgba(0,0,0,.25)}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:calc(var(--fbh,60px) + 12px)}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 "Atkinson Hyperlegible","Segoe UI","Noto Sans","Helvetica Neue",Arial,sans-serif}
button,input,select{font:inherit;color:inherit}
input{accent-color:var(--accent)}
button{cursor:pointer}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
header.top{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;padding:18px 28px 12px;max-width:1480px;margin:0 auto}
header.top h1{font-size:22px;margin:0}
header.top .sub{color:var(--mute);font-size:14px;flex:1}
.ghost{background:none;border:1px solid var(--line);border-radius:8px;padding:6px 14px;color:var(--ink2)}
.ghost:hover{background:var(--hover)}
/* filter bar */
#fbar{position:sticky;top:0;z-index:30;background:var(--surf);border-block:1px solid var(--line)}
#fbar .in{max-width:1480px;margin:0 auto;padding:12px 28px;display:flex;flex-wrap:wrap;gap:12px 12px;align-items:center}
#fbar .lab{font-weight:600;font-size:13px;color:var(--ink2);text-transform:uppercase;letter-spacing:.04em}
details.fc{position:relative}
details.fc>summary{list-style:none;cursor:pointer;border:1px solid var(--line);border-radius:999px;padding:6px 15px;background:var(--surf);color:var(--ink2);white-space:nowrap}
details.fc>summary::-webkit-details-marker{display:none}
details.fc>summary::after{content:" \25BE";color:var(--mute)}
details.fc[open]>summary,details.fc>summary:hover{background:var(--hover)}
details.fc.on>summary{border-color:var(--accent);color:var(--ink);background:color-mix(in srgb,var(--accent) 14%,var(--surf));font-weight:600}
.panel{position:absolute;top:calc(100% + 6px);left:0;min-width:260px;max-height:360px;overflow:auto;background:var(--surf);border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.18);padding:6px;z-index:40}
.panel label{display:flex;gap:10px;align-items:center;padding:7px 8px;border-radius:5px;cursor:pointer}
.panel label:hover{background:var(--hover)}
.panel label .c{margin-left:auto;color:var(--mute);font-variant-numeric:tabular-nums;font-size:13px}
.panel .pf{display:flex;justify-content:space-between;border-top:1px solid var(--line);margin-top:6px;padding:8px 8px 4px;font-size:13px}
.linkbtn{background:none;border:0;color:var(--accent);padding:0;text-decoration:underline}
.fin{display:flex;align-items:center;gap:8px;color:var(--ink2);font-size:14px}
.fin input{border:1px solid var(--line);border-radius:8px;background:var(--surf);padding:6px 10px;width:190px}
.fin input[type=number]{width:84px}
.sp{flex:1}
.pills{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:13.5px;width:100%;padding-top:2px}
.pill{display:inline-flex;gap:6px;align-items:center;border:1px solid var(--accent);background:color-mix(in srgb,var(--accent) 12%,var(--surf));border-radius:999px;padding:3px 6px 3px 12px}
.pill button{border:0;background:none;color:var(--ink2);border-radius:999px;width:22px;height:22px;line-height:20px;padding:0;font-size:16px}
.pill button:hover{background:var(--hover);color:var(--ink)}
#resetall{border-color:var(--accent);color:var(--accent)}
#resetall:disabled{opacity:.4;border-color:var(--line);color:var(--mute);cursor:default}
/* shell */
.shell{display:grid;grid-template-columns:240px minmax(0,1fr);gap:32px;max-width:1480px;margin:0 auto;padding:24px 28px 80px}
aside#side{position:sticky;top:var(--fbh,60px);align-self:start;max-height:calc(100vh - var(--fbh,60px) - 12px);overflow:auto;padding-right:4px}
aside#side h4{margin:22px 0 6px;font-size:12.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}
aside#side h4:first-child{margin-top:0}
aside#side button{display:block;width:100%;text-align:left;background:none;border:0;border-left:3px solid transparent;padding:8px 12px;border-radius:0 8px 8px 0;color:var(--ink2);font-size:15px}
aside#side button:hover{background:var(--hover)}
aside#side button[aria-current=page]{border-left-color:var(--accent);background:var(--hover);color:var(--ink);font-weight:600}
main{min-width:0}
.vh h1{font-size:28px;line-height:1.2;margin:2px 0 8px}
.vh p{margin:0 0 14px;color:var(--ink2);max-width:70ch;font-size:16px}
.respond{font-size:12px;color:var(--mute);margin-bottom:6px}
.jump{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 22px}
.jump a{font-size:14px;border:1px solid var(--line);border-radius:999px;padding:5px 14px;color:var(--ink2);text-decoration:none;background:var(--surf)}
.jump a:hover{background:var(--hover)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,540px),1fr));gap:22px;align-items:start}
.card{background:var(--surf);border:1px solid var(--line);border-radius:var(--radius);padding:22px 24px;min-width:0;box-shadow:var(--shadow)}
.card.wide{grid-column:1/-1}
.chead{display:flex;gap:14px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.card h2{font-size:18px;line-height:1.3;margin:0}
.tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.tools select{background:var(--surf);border:1px solid var(--line);border-radius:8px;padding:5px 10px;font-size:14px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.seg button{border:0;background:none;padding:5px 13px;color:var(--ink2);font-size:14px}
.seg button[aria-pressed=true]{background:var(--accent);color:var(--on-accent);font-weight:600}
.desc strong,details.how strong{color:var(--ink);font-weight:650}
.desc{margin:8px 0 14px;color:var(--ink2);max-width:75ch;font-size:15px}
details.how{margin:0 0 16px;font-size:14px;color:var(--ink2);max-width:75ch}
details.how summary{cursor:pointer;color:var(--accent)}
details.how p{margin:8px 0 0}
.scope{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);font-size:13px;color:var(--mute)}
.scope .on{color:var(--accent);font-weight:600}
.empty{padding:28px;text-align:center;color:var(--mute);border:1px dashed var(--line);border-radius:8px}
.note{font-size:13.5px;color:var(--mute);margin-top:12px}
.warn{color:var(--caution)}
/* tiles */
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin:0 0 26px}
.tile{background:var(--surf);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow)}
.tile b{display:block;font-size:30px;line-height:1.15;font-variant-numeric:tabular-nums}
.tile .tl{color:var(--ink2);font-size:14.5px;margin-top:2px}
.tile .ts{color:var(--mute);font-size:13px;margin-top:4px}
.tile.static{opacity:.62}
.tile.scoped{border-color:var(--accent)}
/* signals + map */
.sig{display:flex;flex-direction:column;gap:10px;margin-top:6px}
.sig button{text-align:left;background:var(--surf);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;padding:12px 16px;color:var(--ink);font-size:15.5px}
.sig button.w{border-left-color:var(--caution)}
.sig button:hover{background:var(--hover)}
.sig small{display:block;color:var(--mute);font-size:13.5px;margin-top:2px}
.map{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-top:6px}
.map button{text-align:left;background:var(--surf);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.map button:hover{background:var(--hover)}
.map b{display:block;font-size:15.5px;margin-bottom:2px}.map span{display:block;color:var(--ink2);font-size:14px}.map small{display:block;margin-top:6px;color:var(--mute);font-size:13px}
/* bars */
.row{display:grid;grid-template-columns:minmax(90px,36%) 1fr 76px;gap:14px;align-items:center;font-size:14.5px;padding:5px 6px}
.row .l{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .t{background:var(--hover);border-radius:5px;height:16px}
.row .t i{display:block;height:100%;background:var(--series);border-radius:0 5px 5px 0;min-width:2px}
.row .n{text-align:right;font-variant-numeric:tabular-nums}
.dim{opacity:.38}
.pick{cursor:pointer;border-radius:5px}
.row.pick:hover,.cell.pick:hover{background:var(--hover)}
[aria-pressed=true].pick{outline:2px solid var(--accent);outline-offset:1px;opacity:1}
/* svg */
svg.chart{width:100%;height:auto;display:block;overflow:visible}
.grid-l{stroke:var(--line);stroke-width:1}
.axis{stroke:var(--mute);stroke-width:1}
.tick,.xlab,.vlab{font-size:13px;fill:var(--mute)}
.vlab{fill:var(--ink2)}
.bar{fill:var(--series)}
.hit{fill:transparent}
g.mark:hover .bar{filter:brightness(1.12)}
svg .pick:focus-visible{outline:none}
svg .pick:focus-visible .bar,svg .pick:focus-visible rect.seg{stroke:var(--accent);stroke-width:2}
.line{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round}
.area{fill:var(--series);opacity:.14}
.veil{fill:var(--surf);opacity:.62;pointer-events:none}
.cross{stroke:var(--ink2);stroke-width:1;stroke-dasharray:3 3}
.dot{fill:var(--series);stroke:var(--surf);stroke-width:2}
rect.segr{stroke:var(--surf);stroke-width:2}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;margin:16px 0 4px;font-size:14px}
.legend button{display:inline-flex;gap:8px;align-items:center;background:none;border:0;padding:3px 6px;font-size:14px;color:var(--ink2);border-radius:4px}
.legend button[aria-pressed=true]{outline:2px solid var(--accent)}
.sw{width:12px;height:4px;border-radius:2px;display:inline-block}
.sw.b{height:12px;width:12px;border-radius:3px}
/* heat */
.heat{display:grid;gap:4px;font-size:14px;overflow-x:auto;padding-bottom:2px}
.heat .hh,.heat .rh{color:var(--ink2);padding:6px 10px;white-space:nowrap;display:flex;align-items:center}
.heat .hh{justify-content:center;font-weight:600}
.cell{padding:9px 6px;text-align:center;border-radius:6px;font-variant-numeric:tabular-nums;min-height:38px}
.cell.na{color:var(--mute);background:repeating-linear-gradient(135deg,transparent 0 5px,var(--line) 5px 6px)}
/* parts */
.part{display:flex;gap:3px;height:38px;border-radius:6px;overflow:hidden}
.part div{min-width:3px}
.facts{display:grid;grid-template-columns:minmax(140px,max-content) 1fr;gap:8px 24px;font-size:15px;margin:14px 0 0}
.facts dt{color:var(--ink2)}.facts dd{margin:0;font-variant-numeric:tabular-nums}
.facts small{color:var(--mute);margin-left:8px;font-size:13px}
.qs{display:flex;flex-wrap:wrap;gap:8px 20px;font-size:14px;margin-top:10px}
.qs span{color:var(--mute)}.qs b{color:var(--ink);margin-left:3px;font-variant-numeric:tabular-nums}
.sub3{font-size:14px;font-weight:600;color:var(--ink2);margin:22px 0 8px}
.cm{display:grid;grid-template-columns:minmax(110px,30%) 1fr 90px;gap:16px;align-items:center;padding:7px 6px;font-size:14.5px}
.cm .tr{position:relative;height:18px;background:var(--hover);border-radius:4px}
.cm .tr i{position:absolute;left:0;top:0;bottom:0;border-radius:0 4px 4px 0}
.cm .n{text-align:right;font-variant-numeric:tabular-nums}
/* tables */
.tw{overflow-x:auto}
table{border-collapse:collapse;font-size:14px;width:100%}
th,td{border-bottom:1px solid var(--line);padding:9px 14px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--ink2);font-weight:600;position:sticky;top:0;background:var(--surf)}
td .mb{display:inline-block;vertical-align:middle;height:8px;border-radius:0 3px 3px 0;background:var(--series);margin-right:6px}
tr.dim{opacity:.38}
.cta{display:block;width:100%;text-align:left;background:color-mix(in srgb,var(--accent) 10%,var(--surf));border:1px solid var(--accent);border-radius:12px;padding:18px 22px;margin:0 0 22px;color:var(--ink)}
.cta b{display:block;font-size:18px}.cta span{color:var(--ink2);font-size:15px}.cta:hover{background:color-mix(in srgb,var(--accent) 18%,var(--surf))}
.presets{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
.preset{text-align:left;background:var(--surf);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.preset:hover{background:var(--hover);border-color:var(--accent)}.preset b{display:block;font-size:15px}.preset span{display:block;margin-top:4px;color:var(--ink2);font-size:13.5px}
.lrow{display:grid;grid-template-columns:30px minmax(260px,1.5fr) minmax(130px,1fr) 190px auto;gap:16px;align-items:center;padding:12px 4px;border-bottom:1px solid var(--line)}
.ll{display:flex;align-items:center;gap:8px;font-size:15px;min-width:0}.ll .tr{color:var(--mute)}
.ltr{display:inline-flex;align-items:center;justify-content:center;min-width:24px;height:24px;border-radius:7px;color:#0b0b0b;font-weight:700;font-size:13px}
.lt2{position:relative;background:var(--hover);border-radius:6px;height:20px}
.lt2 i{display:block;height:100%;background:var(--series);border-radius:0 6px 6px 0;min-width:2px}
.lt2 .whisk{position:absolute;top:50%;height:4px;margin-top:-2px;background:var(--ink2);opacity:.55;border-radius:2px}
.ln{display:flex;flex-direction:column;font-size:13.5px;color:var(--mute)}.ln b{font-size:17px;color:var(--ink);font-variant-numeric:tabular-nums}.ln .lose{color:var(--warn)}
.la{display:flex;gap:8px}
.ladd{margin:8px 0 14px 34px;padding:16px 20px;background:var(--hover);border:1px solid var(--line);border-radius:10px}
.sugg{display:grid;grid-template-columns:minmax(180px,1.4fr) 110px 190px;gap:14px;width:100%;text-align:left;background:var(--surf);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:0 0 8px;font-size:14.5px}
.sugg:hover{border-color:var(--accent)}.sugg .sk,.sugg .sq{color:var(--ink2)}
.lsel{display:flex;flex-wrap:wrap;gap:12px;margin:6px 0 12px}.lsel select{background:var(--surf);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:14.5px}
.wrapcells th:nth-child(2){text-align:left}.wrapcells td{white-space:normal;min-width:90px}.qf{margin:0 0 14px}.qf .qlab{color:var(--ink2);font-size:14px;margin-right:6px;align-self:center}.qf button{border:1px solid var(--line);border-radius:999px;padding:4px 12px}.qf button[aria-pressed=true]{background:color-mix(in srgb,var(--accent) 14%,var(--surf));border-color:var(--accent);outline:none;color:var(--ink);font-weight:600}.wrapcells td:nth-child(2){min-width:260px;text-align:left}
.sdot{stroke:var(--surf);stroke-width:3}.slab{font-size:15px;font-weight:700;fill:var(--ink)}
@media (max-width:900px){.lrow{grid-template-columns:30px 1fr;gap:8px}.lrow .lb,.lrow .ln,.lrow .la{grid-column:2}.sugg{grid-template-columns:1fr}.ladd{margin-left:0}}
.addf{background:var(--accent);color:var(--on-accent);border:1px solid var(--accent);border-radius:999px;padding:6px 16px;font-weight:600}
.addf:hover{filter:brightness(1.1)}
.frow{display:flex;flex-wrap:wrap;gap:10px 28px;align-items:center;width:100%;justify-content:space-between}
.pills{flex:1 1 360px;min-width:0}
.phint{color:var(--mute);font-size:13.5px}
.pill{max-width:100%;flex:none}
.pill .plabel{border:0;background:none;padding:0;text-align:left;max-width:min(340px,60vw);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink);font-size:13.5px}
.pill .plabel:hover{text-decoration:underline}
.pill button.plabel{width:auto;height:auto;line-height:1.4;font-size:13.5px;border-radius:0}
.pill .pdrop{color:var(--warn);font-size:12.5px;white-space:nowrap}
.pill .px{border:0;background:none;color:var(--ink2);border-radius:999px;width:22px;height:22px;line-height:20px;padding:0;font-size:16px}
.pill .px:hover{background:var(--hover);color:var(--ink)}
.impact{display:flex;flex-wrap:wrap;gap:6px 22px;align-items:flex-end;flex:0 1 auto}
.metric{display:flex;flex-direction:column;min-width:74px}
.metric .ml{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em}
.metric .mv{font-size:20px;line-height:1.2;font-variant-numeric:tabular-nums}
.metric .md{font-size:12.5px;color:var(--ink2);min-height:16px}
.mtrack{height:5px;background:var(--hover);border-radius:3px;margin-top:2px;min-width:120px}
.mtrack i{display:block;height:100%;background:var(--accent);border-radius:3px}
/* dialogs: surfaces that clearly sit above the page */
:root{--scrim:rgba(14,14,13,.10);--dlg-shadow:0 18px 48px rgba(0,0,0,.28),0 2px 6px rgba(0,0,0,.12)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){--scrim:rgba(0,0,0,.22);--dlg-shadow:0 18px 48px rgba(0,0,0,.6),0 2px 6px rgba(0,0,0,.4)}}
:root[data-theme="dark"]{--scrim:rgba(0,0,0,.22);--dlg-shadow:0 18px 48px rgba(0,0,0,.6),0 2px 6px rgba(0,0,0,.4)}
.dlg,.panel{background:var(--surf);border:1px solid var(--mute);border-radius:12px;box-shadow:var(--dlg-shadow)}
.dlg{position:fixed;z-index:60;width:min(420px,calc(100vw - 16px));display:flex;flex-direction:column;max-height:min(520px,calc(100vh - 140px))}
.dhead{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:12px 14px;background:var(--hover);border-bottom:1px solid var(--line);border-radius:11px 11px 0 0}
.dtitle,.ptitle{font-size:16px;font-weight:700}.dsub,.psub{font-size:13px;color:var(--ink2);margin-top:2px}
.dx,.pclear{border:0;background:none;color:var(--ink2);border-radius:8px;width:32px;height:32px;font-size:22px;line-height:1;padding:0;flex:none}
.dx:hover,.pclear:hover{background:var(--line);color:var(--ink)}
.dbody{padding:12px 14px;overflow:auto}
.dlab{font-size:12.5px;color:var(--ink2);margin:0 0 6px}
.dtools{display:flex;gap:16px;margin:10px 0 4px;font-size:13px}
.dphrase{margin:12px 0 0;padding:8px 10px;background:var(--hover);border-radius:8px;font-size:14px}
.elist{max-height:260px;overflow:auto;margin:0 -6px}
.erow{display:grid;grid-template-columns:18px minmax(60px,1fr) 56px auto;gap:10px;align-items:center;padding:7px 6px;border-radius:7px;cursor:pointer;font-size:14px}
.panel label.erow{display:grid}
.erow:hover{background:var(--hover)}
.erow .c{color:var(--mute);font-size:13px;font-variant-numeric:tabular-nums;text-align:right}
.emeter,.pmeter{display:block;height:5px;background:var(--line);border-radius:3px;overflow:hidden}
.emeter i,.pmeter i{display:block;height:100%;background:var(--accent);border-radius:3px}
.dfoot{display:flex;justify-content:space-between;gap:10px;padding:10px 14px;border-top:1px solid var(--line);background:var(--hover);border-radius:0 0 11px 11px}
.dbtn{border:1px solid var(--line);background:var(--surf);border-radius:8px;padding:7px 16px;font-size:14px}
.dbtn:hover{border-color:var(--ink2)}
.dbtn.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:600}
.dbtn.danger{color:var(--warn);border-color:transparent;background:none;padding-left:4px}
.dbtn.danger:hover{text-decoration:underline}
.panel{min-width:260px;padding:0;overflow:hidden}
.panel .dhead{padding:10px 12px}.panel .elist{margin:0;max-height:300px;padding:6px}
.panel .dfoot{padding:8px 12px}
/* step search drawer */
#palscrim{position:fixed;z-index:50;left:0;right:0;bottom:0;background:var(--scrim);animation:fadein .15s ease-out}
#pal{position:fixed;z-index:55;right:0;bottom:0;width:min(1100px,100vw);display:flex;flex-direction:column;background:var(--surf);border-left:2px solid var(--mute);box-shadow:-18px 0 48px rgba(0,0,0,.3);animation:slidein .18s ease-out}
@keyframes slidein{from{transform:translateX(28px);opacity:0}to{transform:none;opacity:1}}
@keyframes fadein{from{opacity:0}to{opacity:1}}
@media (prefers-reduced-motion:reduce){#pal,#palscrim{animation:none}}
#pal .phead{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:12px 20px 10px;background:var(--hover);border-bottom:1px solid var(--line)}
.psearch{position:relative;display:flex;align-items:center;margin:12px 20px 0;border:2px solid var(--line);border-radius:10px;background:var(--surf)}
.psearch:focus-within{border-color:var(--accent)}
.psearch .pmag{padding:0 4px 0 12px;color:var(--mute);font-size:20px}
.psearch input{flex:1;border:0;outline:none;background:none;padding:11px 8px;font-size:16px;min-width:0}
.paddmode{display:flex;align-items:center;gap:10px;margin:10px 20px 0;font-size:14px;color:var(--ink2)}
.ptabs{display:flex;gap:4px;margin:14px 20px 0;border-bottom:1px solid var(--line)}
.ptab{border:0;background:none;padding:8px 14px;font-size:14.5px;color:var(--ink2);border-bottom:3px solid transparent;margin-bottom:-1px}
.ptab:hover{color:var(--ink)}.ptab[aria-pressed=true]{color:var(--ink);font-weight:650;border-bottom-color:var(--accent)}
.pnowbox{margin:14px 20px 0;padding:10px 14px;background:var(--hover);border-radius:10px}
.pnowtxt{font-size:14px;color:var(--ink2)}.pnowtxt b{font-size:19px;color:var(--ink);font-variant-numeric:tabular-nums}
.pnowtrack{height:6px;background:var(--line);border-radius:3px;margin-top:6px}.pnowtrack i{display:block;height:100%;background:var(--accent);border-radius:3px}
.plast{margin:10px 20px 0;padding:8px 14px;border:1px solid var(--accent);border-radius:10px;background:color-mix(in srgb,var(--accent) 10%,var(--surf));font-size:14px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.plast[hidden],.paddmode[hidden]{display:none}
.plast .linkbtn{margin-left:auto;font-size:14px}
.plist{flex:1;overflow:auto;padding:12px 20px 16px;min-height:140px}
.phd{font-size:13px;color:var(--mute);margin:2px 0 10px}
.pback{display:flex;gap:10px;align-items:center;border:0;background:none;color:var(--accent);padding:2px 0 12px;font-size:14.5px}.pback b{color:var(--ink)}
.pempty{padding:28px 10px;text-align:center;color:var(--mute);border:1px dashed var(--line);border-radius:10px}
.pcard{display:grid;grid-template-columns:1fr auto 20px;gap:12px;align-items:center;width:100%;text-align:left;border:1px solid var(--line);background:var(--surf);border-radius:10px;padding:12px 14px;margin:0 0 8px;font-size:15px}
.pcard span{color:var(--mute);font-size:13px}.pcard .pgo{font-size:20px;color:var(--ink2)}
.pcard:hover,.pcard.on{border-color:var(--accent);background:var(--hover)}
.prow{padding:12px 14px;border:1px solid var(--line);border-radius:10px;margin:0 0 10px;background:var(--surf)}
.prow.on,.prow:hover{border-color:var(--ink2);background:var(--hover)}
.pmain{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.pmain .pg{font-size:11.5px;color:var(--mute);text-transform:uppercase;letter-spacing:.05em}
.pmain .pl{font-size:15.5px;font-weight:600;overflow-wrap:anywhere}
.pmain .pc{margin-left:auto;font-size:13px;color:var(--mute);font-variant-numeric:tabular-nums}
.pnote{margin-top:2px;font-size:13px;color:var(--ink2)}
.pacts{display:grid;grid-template-columns:1fr;gap:8px;margin-top:10px}
.pinc{display:grid;grid-template-columns:1fr 1fr;margin-top:10px;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--surf)}
.pi{display:grid;grid-template-columns:auto 1fr;grid-template-rows:auto auto auto;column-gap:8px;align-items:center;text-align:left;border:0;background:none;padding:9px 12px;font-size:14px;color:var(--ink)}
.pi+.pi{border-left:1px solid var(--line)}
.pi .pic{grid-row:1;font-size:15px;width:18px;text-align:center}
.pi .pn{font-weight:650}
.pi small,.pi .pmeter{grid-column:1/-1}.pi small{font-size:12.5px;color:var(--ink2);margin-top:2px}
.pi .pmeter{margin-top:5px}
.pi:hover:not(:disabled){background:var(--hover)}
.pi.include:hover:not(.on) .pic,.pi.include .pic{color:var(--accent)}
.pi.ignore .pic{color:var(--ink2)}
.pi.on.include{background:var(--accent);color:var(--on-accent)}.pi.on.include .pic,.pi.on.include small{color:var(--on-accent)}
.pi.on.ignore{background:var(--ink);color:var(--surf)}.pi.on.ignore .pic,.pi.on.ignore small{color:var(--surf)}
.pi.on .pmeter{display:none}
.pi.on:disabled{opacity:1}
.pi.implicit{opacity:.75;background:repeating-linear-gradient(135deg,transparent 0 6px,var(--line) 6px 7px);color:var(--ink2);cursor:default}
.pi.implicit .pic{color:var(--mute)}
.pacts .pi{border:1px solid var(--accent);border-radius:10px;background:color-mix(in srgb,var(--accent) 9%,var(--surf))}
.pact{display:flex;flex-direction:column;gap:3px;align-items:stretch;text-align:left;border:1px solid var(--accent);background:color-mix(in srgb,var(--accent) 9%,var(--surf));border-radius:8px;padding:8px 12px;font-size:14px}
.pact.alt{border-color:var(--line);background:var(--surf)}
.pact:hover:not(:disabled){border-color:var(--ink);box-shadow:0 1px 0 var(--ink2)}
.pact .pn{font-weight:650}.pact small{font-size:12.5px;color:var(--ink2)}
.pact.done{opacity:.6;border-style:dashed}
.pfoot{padding:10px 20px 14px;border-top:1px solid var(--line);font-size:12.5px;color:var(--mute);background:var(--hover)}

#pal .pbody{display:grid;grid-template-columns:230px minmax(0,1fr);flex:1;min-height:0;margin-top:12px;border-top:1px solid var(--line)}
.prail{overflow:auto;padding:10px 10px 14px;border-right:1px solid var(--line);background:var(--hover)}
.prail .prh{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:14px 8px 4px}
.prail .prh:first-child{margin-top:2px}
.pri{display:flex;justify-content:space-between;align-items:center;gap:8px;width:100%;text-align:left;border:0;background:none;border-radius:8px;padding:7px 10px;font-size:14.5px;color:var(--ink2)}
.pri:hover{background:var(--line);color:var(--ink)}
.pri[aria-pressed=true]{background:var(--surf);color:var(--ink);font-weight:650;box-shadow:inset 3px 0 0 var(--accent),0 0 0 1px var(--line)}
.pri .badge{min-width:20px;height:20px;border-radius:10px;background:var(--accent);color:var(--on-accent);font-size:12px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;padding:0 6px}
.ppane{display:flex;flex-direction:column;min-width:0;min-height:0}
.pctx{padding:10px 18px;border-bottom:1px solid var(--line);background:var(--surf)}
.impact.compact{gap:4px 16px;flex-wrap:nowrap}.impact.compact .metric{min-width:0}.impact.compact .mv{font-size:17px}.impact.compact .mtrack{min-width:90px}.impact.compact .ml{font-size:11px;white-space:nowrap}.impact.compact .md{white-space:nowrap}
.pactive{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:10px;font-size:13px}
.pactive .plab{color:var(--mute);margin-right:4px}
.pchip{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--accent);background:color-mix(in srgb,var(--accent) 10%,var(--surf));border-radius:999px;padding:2px 4px 2px 10px;font-size:13px}
.pchip:not(:has(button)){padding-right:10px}
.pchip button{border:0;background:none;color:var(--ink2);width:20px;height:20px;border-radius:50%;padding:0;font-size:15px;line-height:1}
.pchip button:hover{background:var(--line);color:var(--ink)}
#pal .plist{padding:12px 18px 16px}
#pal .plast{margin:10px 0 0}
#pal .prow{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:6px 16px;align-items:center;padding:10px 12px;margin:0 0 8px}
.ptl{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.pcount{display:flex;align-items:center;gap:8px;margin-top:5px;font-size:12.5px;color:var(--mute);white-space:nowrap}
.pcbar{flex:0 0 120px;height:5px;background:var(--line);border-radius:3px;overflow:hidden}.pcbar i{display:block;height:100%;background:var(--mute);border-radius:3px}
#pal .pinc{margin-top:0}#pal .pacts{margin-top:0}
#pal .pi{padding:7px 10px}
#pal .pi small{margin-top:0}
@media (max-width:760px){#pal .pbody{grid-template-columns:1fr}.prail{display:flex;gap:4px;overflow-x:auto;border-right:0;border-bottom:1px solid var(--line)}.prail .prh{display:none}.pri{width:auto;white-space:nowrap}#pal .prow{grid-template-columns:1fr}}
/* three-state control (Include, Ignore, Not set) */
.tri,.ttri{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surf);flex:none}
.tri button{display:flex;gap:6px;align-items:center;border:0;background:none;padding:5px 11px;font-size:13px;color:var(--ink2)}
.tri button+button,.ttri button+button{border-left:1px solid var(--line)}
.tri button:hover:not([aria-pressed=true]),.ttri button:hover:not([aria-pressed=true]){background:var(--hover);color:var(--ink)}
.tri button[aria-pressed=true].inc,.ttri button[aria-pressed=true].inc{background:var(--accent);color:var(--on-accent);font-weight:650}
.tri button[aria-pressed=true].ign,.ttri button[aria-pressed=true].ign{background:var(--ink);color:var(--surf);font-weight:650}
.pactive2{margin-top:10px;max-height:150px;overflow:auto}
.pactive2 .plab{font-size:13px;color:var(--mute);margin-bottom:4px}
.arow{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:5px 0;border-top:1px solid var(--line)}
.asub{font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.pinc3{grid-template-columns:1fr 1fr 100px}
.pi.unset .pn{font-weight:500}
.pi.unset.on{background:var(--hover);color:var(--ink2)}
.pi.unset:disabled{cursor:default}
.pinc .pi.unset{border-left:1px solid var(--line)}
/* the filter tree */
.ttools{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}
.tbtn{border:1px solid var(--line);background:var(--surf);border-radius:8px;padding:5px 12px;font-size:13.5px;color:var(--ink);white-space:nowrap}
.tbtn:hover:not(:disabled){border-color:var(--ink2);background:var(--hover)}
.tbtn:disabled{opacity:.45;cursor:default}
.tbtn.more{padding:5px 11px;font-weight:700;letter-spacing:.05em}
.ltree{overflow-x:auto}
.thead,.trow{display:grid;grid-template-columns:24px 24px minmax(170px,2.2fr) minmax(70px,1fr) 92px 74px 86px auto;gap:10px;align-items:center}
.thead{padding:0 14px 6px 19px;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}
.trow{padding:10px 12px 10px 14px;margin:6px 0;border:1px solid var(--line);border-left:5px solid var(--line);border-radius:12px;background:var(--surf);transition:box-shadow .12s,border-color .12s}
.trow:hover{box-shadow:0 2px 12px rgba(0,0,0,.10);border-color:var(--mute)}
.trow.cmp{border-left-color:var(--nc)}
.trow.troot{background:var(--hover)}
.tkids{position:relative;margin-left:14px;padding-left:20px;border-left:2px solid var(--line)}
.tkids>.tnode{position:relative}
.tkids>.tnode::before{content:"";position:absolute;left:-20px;top:29px;width:18px;border-top:2px solid var(--line)}
.tkids>.tnode:last-child::after{content:"";position:absolute;left:-23px;top:30px;bottom:-8px;width:5px;background:var(--surf)}
.tc,.tk{display:flex;align-items:center;justify-content:center}
.tcaret{border:0;background:none;width:24px;height:24px;border-radius:6px;color:var(--ink2);font-size:14px}
.tcaret:hover{background:var(--line);color:var(--ink)}
.tk input{width:17px;height:17px}
.tlab{display:flex;align-items:center;gap:8px;min-width:0;flex-wrap:wrap}
.tstep{display:flex;flex-wrap:wrap;gap:6px;align-items:center;min-width:0}
.tmode{font-size:12px;font-weight:700;border-radius:6px;padding:2px 8px;white-space:nowrap}
.tmode.inc{background:color-mix(in srgb,var(--accent) 16%,var(--surf));color:var(--accent)}
.tmode.ign{background:var(--ink);color:var(--surf)}
.ttag{font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
.tval{background:var(--hover);border:1px solid var(--line);border-radius:6px;padding:1px 8px;font-size:14px;font-weight:600}
.ttext{font-size:14.5px}
.troottxt{font-weight:700;font-size:15.5px}
.thidden{font-size:12.5px;color:var(--mute)}
.ttrack{position:relative;background:var(--hover);border-radius:6px;height:16px}
.ttrack i{display:block;height:100%;background:var(--series);border-radius:0 6px 6px 0;min-width:2px}
.ttrack .whisk{position:absolute;top:50%;height:4px;margin-top:-2px;background:var(--ink2);opacity:.55;border-radius:2px}
.tn{display:flex;flex-direction:column;font-size:12.5px;color:var(--mute);line-height:1.3}
.tn b{font-size:16px;color:var(--ink);font-variant-numeric:tabular-nums}
.tn b.lose{color:var(--warn)}.tn b.same{color:var(--ink2);font-weight:600}
.tact{display:flex;gap:6px;align-items:center;justify-content:flex-end}
.ttri button{border:0;background:none;width:30px;height:28px;font-size:14px;color:var(--ink2);padding:0}
.nmenu{width:280px;padding:6px;border-radius:12px;max-height:none}
.nmenu .mi{display:flex;flex-direction:column;align-items:flex-start;width:100%;text-align:left;border:0;background:none;border-radius:8px;padding:8px 10px;font-size:14.5px;color:var(--ink)}
.nmenu .mi small{font-size:12px;color:var(--mute)}
.nmenu .mi:hover{background:var(--hover)}.nmenu .mi.warn{color:var(--warn)}
.msep{height:1px;background:var(--line);margin:4px 2px}
@media (max-width:1180px){.thead{display:none}.trow{grid-template-columns:24px 24px minmax(0,1fr) auto}.trow .tbar,.trow .n2,.trow .n3{display:none}}
kbd{display:inline-block;border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;padding:0 6px;font:12px/1.5 inherit;background:var(--surf);color:var(--ink2);margin:0 2px}
@media (max-width:700px){#pal{width:100vw}}
/* slim filter bar and the filters panel */
#fbar .in{align-items:center;gap:12px 14px;padding:10px 28px}
.fbtn{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:999px;padding:6px 14px;background:var(--surf);font-size:14.5px;font-weight:600;color:var(--ink)}
.fbtn:hover,.fbtn[aria-expanded=true]{background:var(--hover);border-color:var(--ink2)}
.fbtn.on{border-color:var(--accent)}
.fbadge{min-width:20px;height:20px;border-radius:10px;background:var(--accent);color:var(--on-accent);font-size:12px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;padding:0 6px}
.fbadge[hidden]{display:none}
#fbar .impact{flex:1;justify-content:flex-end;gap:6px 28px;min-width:0}
.fpanel{width:min(540px,calc(100vw - 16px));max-height:calc(100vh - var(--fbh,76px) - 28px);z-index:58}
.fpanel .fbody{display:flex;flex-direction:column;gap:22px;padding:16px 18px}
.fh{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink2);font-weight:700}
.fnote,.fempty{margin:0 0 10px;font-size:13.5px;color:var(--mute)}
.fempty{padding:12px;border:1px dashed var(--line);border-radius:10px}
.fpanel .arow{padding:8px 0}
.asubwrap{display:flex;flex-direction:column;align-items:flex-start;min-width:0;gap:1px}
.asubwrap .linkbtn{font-size:12.5px}
.qsec{border:1px solid var(--line);border-radius:10px;margin:0 0 10px;overflow:hidden}
.qsec>summary{display:flex;justify-content:space-between;align-items:center;padding:9px 12px;background:var(--hover);cursor:pointer;list-style:none;font-weight:650;font-size:14.5px}
.qsec>summary::-webkit-details-marker{display:none}
.qsec>summary::before{content:"▸";margin-right:8px;color:var(--ink2)}
.qsec[open]>summary::before{content:"▾"}
.qsec>summary .qname{flex:1}.qcount{font-size:12.5px;font-weight:500;color:var(--mute)}
.qrow{display:grid;grid-template-columns:minmax(52px,1fr) 64px 56px auto;gap:10px;align-items:center;padding:7px 12px;border-top:1px solid var(--line);font-size:14px}
.qrow .ql{font-weight:600}.qrow .qc{color:var(--mute);font-size:12.5px;text-align:right;font-variant-numeric:tabular-nums}
.ttri.mini button{width:34px;height:30px;font-size:15px}
.ttri.mini button:disabled{cursor:default}
.ttri.mini button[aria-pressed=true].unset{background:var(--hover);color:var(--ink2)}
.ttri.mini button.implicit{background:repeating-linear-gradient(135deg,transparent 0 5px,var(--line) 5px 6px);color:var(--mute)}
.ttri.mini button:disabled:not([aria-pressed=true]):not(.implicit){opacity:.4}
.fopts{display:flex;gap:16px;flex-wrap:wrap}
.fopts .fin{flex-direction:column;align-items:flex-start;gap:4px;font-size:13px}
.fopts input{border:1px solid var(--line);border-radius:8px;background:var(--surf);padding:7px 10px;font-size:14px;width:210px}
.fopts input[type=number]{width:110px}
@media (max-width:900px){#fbar .impact{flex-basis:100%;justify-content:flex-start}}
/* quality definition, per-field values on nodes, verdicts, guide and ladder */
.qdef{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;background:color-mix(in srgb,var(--accent) 16%,var(--surf));border:2px solid var(--accent);color:var(--ink);font-weight:700;font-size:15px;margin-right:6px}
.qdef .qi{width:20px;height:20px;border-radius:50%;background:var(--accent);color:var(--on-accent);display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
.qhelp{flex-basis:100%;margin:2px 0 0;font-size:13px;color:var(--ink2)}
.legend.qf{align-items:center;margin:0 0 12px}
.trow .tq{grid-column:3 / -1;display:flex;flex-wrap:wrap;gap:6px 8px;margin-top:-2px}
.tqc{display:inline-flex;align-items:baseline;gap:6px;border:1px solid var(--line);border-radius:8px;padding:2px 9px;background:var(--surf);font-size:13px}
.tqc .tqn{color:var(--ink2)}.tqc b{font-variant-numeric:tabular-nums}
.tqc .tqd{font-size:12px;color:var(--ink2)}.tqc .tqd.up{color:var(--good);font-weight:650}.tqc .tqd.dn{color:var(--warn);font-weight:650}
.tqc .tqs{color:var(--mute)}
.tqlink{border:0;background:none;color:var(--accent);font-size:13px;text-decoration:underline;padding:2px 4px}
.trow.focus{box-shadow:0 0 0 2px var(--accent),0 2px 12px rgba(0,0,0,.12)}
.trow{cursor:default}
.tverd{display:inline-flex;align-items:center;gap:5px;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:700;white-space:nowrap;border:1px solid var(--line);background:var(--surf);color:var(--ink2)}
.tverd.big{font-size:14px;padding:3px 12px}
.tverd.v-gain{background:var(--good);border-color:var(--good);color:var(--on-good)}
.tverd.v-fair{border-color:var(--good);color:var(--good)}
.tverd.v-costly{border-color:var(--caution);color:var(--caution)}
.tverd.v-hurt{background:var(--warn);border-color:var(--warn);color:var(--on-good)}
.tverd.v-flat{color:var(--mute)}
.guide .ghead{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:6px}
.gtext{margin:0 0 6px;font-size:15px;color:var(--ink2);max-width:80ch}
.gba{display:grid;grid-template-columns:minmax(120px,1.2fr) 70px 70px 90px minmax(160px,2fr);gap:8px 14px;align-items:center;font-size:14px;max-width:760px}
.gh{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}
.gl.strong,.gn.strong{font-weight:700}
.gn{font-variant-numeric:tabular-nums}
.gd.up{color:var(--good);font-weight:650}.gd.dn{color:var(--warn);font-weight:650}
.dbell{position:relative;display:block;height:14px;background:var(--hover);border-radius:7px}
.dbell i{position:absolute;top:50%;transform:translate(-50%,-50%)}
.dbell .dl{height:4px;background:var(--mute);border-radius:2px;transform:translate(0,-50%);opacity:.6}
.dbell .d0{width:10px;height:10px;border-radius:50%;border:2px solid var(--ink2);background:var(--surf)}
.dbell .d1{width:12px;height:12px;border-radius:50%;background:var(--accent);border:2px solid var(--surf)}
.gval{display:grid;gap:8px 12px;align-items:center;font-size:14px;overflow-x:auto;padding-bottom:4px}
.gval .star{color:var(--mute)}
.gnext{display:grid;grid-template-columns:minmax(200px,2fr) 110px 190px auto;gap:10px;align-items:center;padding:7px 0;border-top:1px solid var(--line);font-size:14px}
.pi small.pq{margin-top:0;color:var(--ink)}
.pi.on.include small.pq{color:var(--on-accent)}
.pi.on.ignore small.pq{color:var(--surf)}
/* tooltip */
#tip{position:fixed;z-index:60;pointer-events:none;background:var(--surf);border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 20px rgba(0,0,0,.22);padding:9px 12px;font-size:14px;max-width:360px}
#tip .tl{display:flex;gap:10px;line-height:1.7;align-items:center;white-space:nowrap}
#tip b{font-variant-numeric:tabular-nums}#tip span{color:var(--ink2);overflow:hidden;text-overflow:ellipsis}
#tip .k{width:10px;height:3px;border-radius:2px;flex:none}
.gl dt{font-weight:600;margin-top:16px;font-size:15.5px}.gl dd{margin:4px 0 0;color:var(--ink2);max-width:75ch;font-size:15px}
@media (max-width:900px){.shell{grid-template-columns:1fr;gap:14px;padding:14px 16px 60px}.card{padding:16px}header.top,#fbar .in{padding-left:16px;padding-right:16px}aside#side{position:static;max-height:none;display:flex;gap:4px;overflow-x:auto;padding-bottom:6px}aside#side h4{display:none}aside#side button{width:auto;white-space:nowrap;border:1px solid var(--line);border-radius:999px}aside#side button[aria-current=page]{border-color:var(--accent)}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
</style>
</head>
<body>
<header class="top"><h1>Ticket insight report</h1><div class="sub" id="sub"></div><button class="ghost" id="theme" type="button" title="Switch between dark, automatic and light">Theme: dark</button></header>
<div id="fbar"><div class="in" id="fin"></div></div>
<div class="shell"><aside id="side" aria-label="Views"></aside><main id="main"></main></div>
<div id="tip" hidden></div>
<script type="application/json" id="data">__DATA__</script>
<script>
"use strict";
window.addEventListener("error", e => { if (/ResizeObserver loop/.test(e.message || "")) { e.stopImmediatePropagation(); return; } const b = document.createElement("pre"); b.style.cssText = "margin:0;padding:10px 16px;background:#7a1f1f;color:#fff;white-space:pre-wrap;font:13px monospace"; b.textContent = "Script error: " + e.message + " (line " + e.lineno + ")"; document.body.prepend(b); });
const R = JSON.parse(document.getElementById("data").textContent);
const NS = "http://www.w3.org/2000/svg";
const $ = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
const S = (tag, a, text) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); if (text !== undefined) e.textContent = text; return e; };
const get = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
const L = p => { const v = get(R, p); return Array.isArray(v) ? v : []; };
const N = p => { const v = get(R, p); return typeof v === "number" ? v : undefined; };
const isObj = v => v && typeof v === "object" && !Array.isArray(v);
const fmt = v => typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString("en") : String(Number(v.toPrecision(4)))) : String(v);
const pct = (v, d = 1) => (v * 100).toFixed(d) + "%";
const cmp = v => v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k" : String(Math.round(v * 100) / 100);
const sum = (a, f) => a.reduce((s, x) => s + f(x), 0);
const K = N("provenance.min_frequency") || 50;
const TOTAL = N("source.row_count") || 0;
const niceMax = v => { const p = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1e-9)))); const m = v / p; return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p; };
const topRound = (x, y, w, h, r) => { r = Math.min(r, h, w / 2); return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`; };

/* ---------- filter model: what survives a chain of steps (MODEL-BEGIN) ---------- */
/* The report holds aggregates, not tickets. A chain of steps is answered as exact where the report holds
   that split, otherwise as a guaranteed range (lo..hi from the released totals) plus a point estimate
   that assumes the steps are independent. Step kinds:
   {t:"y", vals}                         ticket year in the set
   {t:"d", dim, mode:"i"|"o", vals}      a dimension (category, status, model, ...) only / without these values
   {t:"g", f, neg}                       a yes/no fact: field filled, repeat ticket, id in text ... (neg: the opposite)
   {t:"x", src:"title"|"sol", term, neg} the title or solution contains a frequent term */
const GATES = [
  ["solutions", "solution", "has a solution"], ["description", "description", "has a description"],
  ["serial", "vehicle serial", "has a vehicle serial"], ["model_id", "vehicle model id", "has a vehicle model id"],
  ["baugruppe", "Baugruppe", "names a Baugruppe"], ["fehlercode", "error code", "has an error code"],
  ["hours", "operating hours", "has operating hours"], ["delivery", "delivery date", "has a delivery date"],
  ["boiler", "no boilerplate", "is not boilerplate text"],
];
const clamp01 = v => Math.max(0, Math.min(1, v));
const M = (() => {
  const yearsRows = L("timeline.fill_by_year"), perYear = L("timeline.per_year");
  const yearN = new Map(perYear.map(r => [String(r.year), r.count]));
  const yfill = new Map(yearsRows.map(r => [String(r.year), r]));
  const bc = new Map(L("dimensions.by_category").map(r => [String(r.value), r]));
  const cats = L("dimensions.categoryId.values").map(r => { const b = bc.get(String(r.value)) || {}; return { k: String(r.value), n: r.count, sol: b.solution_fill, desc: b.description_fill }; });
  const catN = new Map(cats.map(c => [c.k, c.n]));
  const restN = Math.max(0, TOTAL - sum(cats, c => c.n));
  const cells = new Map(L("dimensions.categoryId.by_year").map(r => [String(r.value) + "|" + String(r.year), r.count]));
  const yearSum = sum(perYear, r => r.count) || 1;
  const wy = f => sum(yearsRows.filter(r => yearN.has(String(r.year))), r => r.tickets * (r[f] || 0)) * TOTAL / yearSum;
  const cov = p => { const c = get(R, p); return c && typeof c.present === "number" ? c.present : undefined; };
  const F = {
    solutions: get(R, "readiness.solution_present.tickets") ?? wy("solutions"),
    description: wy("description"),
    serial: cov("formats.vehicleSerialNo.coverage") ?? wy("serial"),
    model_id: cov("formats.vehicleModelId.coverage") ?? wy("model_id"),
    baugruppe: cov("origin.baugruppe.coverage") ?? wy("baugruppe"),
    fehlercode: cov("formats.fehlercode.coverage") ?? wy("fehlercode"),
    hours: cov("lifecycle.hours.coverage") ?? wy("hours"),
    delivery: cov("formats.deliveryDate.coverage") ?? wy("delivery"),
    boiler: TOTAL - (get(R, "readiness.templated.tickets") ?? 0),
  };
  const catF = { solutions: new Map(), description: new Map() }, restF = {};
  [["solutions", "sol"], ["description", "desc"]].forEach(([f, key]) => {
    cats.forEach(c => catF[f].set(c.k, Math.round((c[key] != null ? c[key] : F[f] / TOTAL) * c.n)));
    restF[f] = Math.max(0, Math.min(restN, F[f] - sum([...catF[f].values()], v => v)));
  });
  return { yearN, yfill, cats, catN, restN, cells, F, catF, restF, yearKeys: [...yearN.keys()] };
})();

/* dimensions: values with ticket counts; single-valued ones partition the tickets (the rest is "__rest") */
const DIMS = {};
(function () {
  const cross = (rows, vf) => new Map(rows.map(r => [String(vf(r)) + "|" + String(r.year), r.count]));
  const add = (key, label, rows, vf, nf, o = {}) => {
    if (!rows.length) return;
    const values = rows.map(r => ({ v: String(vf(r)), n: nf(r) }));
    DIMS[key] = { key, label, values, multi: !!o.multi, restN: o.multi ? 0 : Math.max(0, TOTAL - sum(values, x => x.n)), restLabel: o.restLabel || "other / not set", nOf: new Map(values.map(x => [x.v, x.n])), cross: o.byYear ? cross(o.byYear, vf) : null, pairs: o.pairs || [] };
  };
  const v = r => r.value, n = r => r.count;
  add("cat", "Category", L("dimensions.categoryId.values"), v, n, { byYear: L("dimensions.categoryId.by_year") });
  add("status", "Status", L("dimensions.statusId.values"), v, n, { byYear: L("dimensions.statusId.by_year") });
  add("prio", "Priority", L("dimensions.priorityId.values"), v, n, { byYear: L("dimensions.priorityId.by_year") });
  add("sub", "Sub-status", L("dimensions.subStatusString.values"), v, n, { byYear: L("dimensions.subStatusString.by_year") });
  add("vstat", "Vehicle status", L("dimensions.vehicleStatus.values"), v, n, { byYear: L("dimensions.vehicleStatus.by_year") });
  add("show", "Shown in ProTeam", L("dimensions.showInProteam.values"), v, n, { byYear: L("dimensions.showInProteam.by_year") });
  add("model", "Vehicle model", L("origin.vehicles.models"), r => r.model, n);
  add("baug", "Baugruppe", L("origin.baugruppe.top"), v, n, { multi: true, byYear: L("origin.baugruppe.by_year"), pairs: L("origin.baugruppe.pairs") });
  add("warr", "Warranty", L("lifecycle.warranty.states"), r => r.state, n);
  add("hours", "Operating hours", L("lifecycle.hours.buckets"), r => r.bucket, n, { restLabel: "no value" });
  add("days", "Days since delivery", L("lifecycle.days_since_delivery.buckets"), r => r.bucket, n, { restLabel: "no value" });
})();
const DIM_KEYS = Object.keys(DIMS);

/* yes/no facts and frequent terms */
const BOOL = new Map();
GATES.forEach(([id, short, phrase]) => BOOL.set(id, { id, short, phrase, F: M.F[id], field: true }));
const addFlag = (id, short, phrase, Fv) => { if (typeof Fv === "number" && Fv >= 0) BOOL.set(id, { id, short, phrase, F: Math.round(Fv), field: false }); };
addFlag("repeat", "repeat ticket", "is a repeat ticket (an earlier ticket on the same vehicle)", get(R, "timeline.recurrence.tickets_with_previous"));
[["problem", "ip", "problem text"], ["solutions", "is", "solution text"]].forEach(([k, pre, where]) => {
  (get(R, "text.identifiers." + k + ".by_kind") || []).forEach(b => addFlag(pre + ":" + b.kind, b.kind.replace(/_/g, " ") + " in " + where, "mentions a " + b.kind.replace(/_/g, " ") + " in the " + where, b.tickets_after_cleaning ?? b.tickets));
});
const TERMS_ALL = [], TERMDF = new Map();
[["title", "origin.titles.tokens"], ["title", "origin.titles.bigrams"], ["title", "vocabulary.titles_trigrams.trigrams"], ["sol", "vocabulary.solutions.tokens"], ["sol", "vocabulary.solutions.bigrams"], ["sol", "vocabulary.solutions.trigrams"]].forEach(([src, path]) => {
  L(path).forEach(r => { const key = src + "|" + r.token; if (!TERMDF.has(key)) { TERMDF.set(key, r.count); TERMS_ALL.push({ src, term: r.token, n: r.count }); } });
});

function scopeOf(steps) {
  const sc = { Y: null, dims: {}, multis: [], gates: [], flags: [], terms: [], empty: false };
  const universe = k => new Set(DIMS[k].values.map(x => x.v).concat(DIMS[k].restN > 0 ? ["__rest"] : []));
  steps.forEach(s0 => {
    const s = s0.t === "c" ? { t: "d", dim: "cat", mode: s0.mode, vals: s0.vals } : s0;
    if (s.t === "y") { const base = sc.Y || new Set(M.yearKeys); sc.Y = new Set([...base].filter(y => (s.mode === "o") !== s.vals.includes(y))); if (!sc.Y.size) sc.empty = true; }
    else if (s.t === "d" && DIMS[s.dim]) {
      if (DIMS[s.dim].multi) sc.multis.push({ key: s.dim, vals: s.vals, neg: s.mode === "o" });
      else { const base = sc.dims[s.dim] || universe(s.dim); sc.dims[s.dim] = new Set([...base].filter(v => (s.mode === "i") === s.vals.includes(v))); if (!sc.dims[s.dim].size) sc.empty = true; }
    } else if (s.t === "g" && BOOL.has(s.f)) {
      const list = BOOL.get(s.f).field ? sc.gates : sc.flags, hit = list.find(g => g.id === s.f);
      if (hit) { if (hit.neg !== !!s.neg) sc.empty = true; } else list.push({ id: s.f, neg: !!s.neg });
    } else if (s.t === "x") {
      const hit = sc.terms.find(x => x.src === s.src && x.term === s.term);
      if (hit) { if (hit.neg !== !!s.neg) sc.empty = true; } else sc.terms.push({ src: s.src, term: s.term, neg: !!s.neg });
    }
  });
  if (sc.Y && sc.Y.size === M.yearKeys.length) sc.Y = null;
  Object.keys(sc.dims).forEach(k => { if (sc.dims[k].size === universe(k).size) delete sc.dims[k]; });
  sc.C = sc.dims.cat || null;
  return sc;
}
function sizeOf(sc) {
  const nC = sc.C ? sum([...sc.C], k => k === "__rest" ? M.restN : (M.catN.get(k) || 0)) : undefined;
  const nY = sc.Y ? sum([...sc.Y], y => M.yearN.get(y) || 0) : undefined;
  if (!sc.C && !sc.Y) return { lo: TOTAL, est: TOTAL, hi: TOTAL };
  if (!sc.Y) return { lo: nC, est: nC, hi: nC, nC };
  if (!sc.C) return { lo: nY, est: nY, hi: nY, nY };
  let cell = 0; [...sc.C].forEach(c => { if (c !== "__rest") [...sc.Y].forEach(y => { cell += M.cells.get(c + "|" + y) || 0; }); });
  const hi = Math.min(nC, nY), lo = Math.min(cell, hi);
  return { lo, est: Math.min(hi, Math.max(lo, nC * nY / TOTAL)), hi, nC, nY };
}
/* a yes/no fact about a field within the scope: bounds and a share (neg: the opposite) */
function filledOf(f, sc, sz, neg) {
  const flip = (n, Fv) => (neg ? n - Fv : Fv);
  const sup = [{ n: TOTAL, F: flip(TOTAL, M.F[f]) }], rates = [];
  if (sc.Y && f !== "boiler") { const Fy = sum([...sc.Y], y => (M.yearN.get(y) || 0) * ((M.yfill.get(y) || {})[f] || 0)); sup.push({ n: sz.nY, F: flip(sz.nY, Fy) }); rates.push(sz.nY ? flip(sz.nY, Fy) / sz.nY : 0); }
  if (sc.C && (f === "solutions" || f === "description")) { const Fc = sum([...sc.C], k => k === "__rest" ? M.restF[f] : (M.catF[f].get(k) || 0)); sup.push({ n: sz.nC, F: flip(sz.nC, Fc) }); rates.push(sz.nC ? flip(sz.nC, Fc) / sz.nC : 0); }
  const G = sup[0].F / TOTAL;
  const hi = Math.min(sz.hi, ...sup.map(s => s.F));
  const U = Math.min(sz.hi, ...sup.map(s => s.n - s.F));
  const p = G > 0 ? clamp01(rates.reduce((a, r) => a * r, 1) / Math.pow(G, Math.max(0, rates.length - 1))) : 0;
  return { hi, U, lo: Math.max(0, sz.lo - U), p: rates.length ? p : clamp01(G) };
}
/* every other kind of step is a set of tickets with a known size (and, for some, a known split by year) */
function marginsOf(sc) {
  const out = [];
  DIM_KEYS.forEach(k => {
    const d = DIMS[k], set = sc.dims[k]; if (!set || k === "cat") return;
    const n = sum([...set], v => v === "__rest" ? d.restN : (d.nOf.get(v) || 0));
    out.push({ n, lo: n, hi: n, crossLo: d.cross ? Y => sum([...set], v => v === "__rest" ? 0 : sum([...Y], y => d.cross.get(v + "|" + y) || 0)) : null });
  });
  sc.multis.forEach(m => {
    const d = DIMS[m.key], ids = m.vals.filter(v => d.nOf.has(v)), counts = ids.map(v => d.nOf.get(v));
    const total = sum(counts, c => c), mx = Math.max(0, ...counts), covered = get(R, "origin.baugruppe.coverage.present") ?? total;
    const overlap = sum(d.pairs.filter(p => ids.includes(String(p.value)) && ids.includes(String(p.partner))), p => p.count);
    const uhi = Math.min(total, covered), est = Math.min(uhi, Math.max(mx, total - overlap));
    if (m.neg) out.push({ n: TOTAL - est, lo: TOTAL - uhi, hi: TOTAL - mx, crossLo: null });
    else out.push({ n: est, lo: mx, hi: uhi, crossLo: d.cross ? Y => Math.max(0, ...ids.map(v => sum([...Y], y => d.cross.get(v + "|" + y) || 0))) : null });
  });
  sc.flags.forEach(g => { const Fv = BOOL.get(g.id).F, n = g.neg ? TOTAL - Fv : Fv; out.push({ n, lo: n, hi: n, crossLo: null }); });
  sc.terms.forEach(t => { const Fv = TERMDF.get(t.src + "|" + t.term) || 0, n = t.neg ? TOTAL - Fv : Fv; out.push({ n, lo: n, hi: n, crossLo: null }); });
  return out;
}
function otherOf(m, sc, sz) {
  let c, nS;
  if (sc.Y) {
    nS = sz.nY;
    if (m.crossLo) { const lo = m.crossLo(sc.Y), hi = Math.min(m.hi, nS); c = { lo: Math.min(lo, hi), hi, est: Math.min(hi, Math.max(lo, m.n * nS / TOTAL)) }; }
    else { const lo = Math.max(0, m.lo - (TOTAL - nS)), hi = Math.min(m.hi, nS); c = { lo, hi, est: Math.min(hi, Math.max(lo, m.n * nS / TOTAL)) }; }
  } else { nS = TOTAL; c = { lo: m.lo, hi: m.hi, est: m.n }; }
  const hi = Math.min(sz.hi, c.hi), U = Math.min(sz.hi, nS - c.lo);
  return { hi, U, lo: Math.max(0, sz.lo - U), p: nS > 0 ? clamp01(c.est / nS) : 0 };
}
const KNOWN = (() => {
  const k = {}, tri = get(R, "readiness.complete_triple.tickets"), us = get(R, "readiness.usable.tickets");
  if (typeof tri === "number") k["description|solutions"] = { lo: tri };
  if (typeof us === "number") k["boiler|solutions"] = { exact: us };
  return k;
})();
function evalScope(sc, raw) {
  if (sc.empty) return { sz: { lo: 0, est: 0, hi: 0 }, n: { lo: 0, est: 0, hi: 0 }, grade: "exact" };
  const sz = sizeOf(sc), fb = sc.gates.map(g => filledOf(g.id, sc, sz, g.neg)), om = marginsOf(sc).map(m => otherOf(m, sc, sz)), parts = fb.concat(om);
  if (!parts.length) return { sz, n: { lo: sz.lo, est: sz.est, hi: sz.hi }, grade: sz.hi - sz.lo < 0.5 ? "exact" : "estimate" };
  const hi = Math.min(sz.hi, ...parts.map(b => b.hi)), lo = Math.min(hi, Math.max(0, sz.lo - sum(parts, b => b.U)));
  let est = Math.min(hi, Math.max(lo, sz.est * parts.reduce((a, b) => a * b.p, 1)));
  const kn = !raw && !sc.C && !sc.Y && !om.length && sc.gates.every(g => !g.neg) && KNOWN[sc.gates.map(g => g.id).sort().join("|")];
  if (kn) { const klo = kn.exact !== undefined ? kn.exact : kn.lo, khi = kn.exact !== undefined ? kn.exact : hi; const nlo = Math.max(lo, klo), nhi = Math.max(nlo, Math.min(hi, khi)); return { sz, n: { lo: nlo, est: Math.min(nhi, Math.max(nlo, est)), hi: nhi }, grade: nhi - nlo < 0.5 ? "exact" : "estimate" }; }
  return { sz, n: { lo, est, hi }, grade: hi - lo < 0.5 ? "exact" : "estimate" };
}
function profile(steps) {
  const sc = scopeOf(steps), ev = evalScope(sc), fields = {}, known = {};
  GATES.forEach(([f]) => {
    const g = sc.gates.find(x => x.id === f);
    fields[f] = g ? (g.neg ? 0 : 1) : (ev.sz.est > 0 ? filledOf(f, sc, ev.sz, false).p : 0);
    known[f] = !!g || (!sc.C && !sc.Y) || (!!sc.Y && f !== "boiler") || (!!sc.C && (f === "solutions" || f === "description"));
  });
  const n = { ...ev.n };
  if (steps.length) { const up = profile(steps.slice(0, -1)).n; n.hi = Math.min(n.hi, up.hi); n.est = Math.max(Math.min(n.lo, n.hi), Math.min(n.est, up.est, n.hi)); n.lo = Math.min(n.lo, n.est); }
  return { n, grade: n.hi - n.lo < 0.5 ? "exact" : "estimate", fields, known, sc };
}
const clone = s => JSON.parse(JSON.stringify(s));
/* ---------- Include / Ignore: the state of a row is read from the steps, and every change rewrites them cleanly ---------- */
/* A target is {k:"dim", key, v} (a value of a dimension or "year"), {k:"g", id} (a yes/no fact) or {k:"x", src, term} (a word).
   States: "inc" included, "exc" ignored, "imp" left out because other values are included, "none" untouched. */
const universeOf = k => (k === "year" ? M.yearKeys.slice() : DIMS[k].values.map(x => x.v).concat(DIMS[k].restN > 0 && !DIMS[k].multi ? ["__rest"] : []));
const dimSteps = (steps, k) => steps.filter(s => (k === "year" ? s.t === "y" : s.t === "d" && s.dim === k));
const dmode = s => (s.mode === "o" ? "o" : "i");
const mkDim = (k, mode, vals) => (k === "year" ? { t: "y", mode, vals } : { t: "d", dim: k, mode, vals });
function dimView(steps, k) {
  const mine = dimSteps(steps, k); if (!mine.length) return { type: "none" };
  if (k !== "year" && DIMS[k].multi) return { type: "multi", inc: new Set(mine.filter(s => dmode(s) === "i").flatMap(s => s.vals)), exc: new Set(mine.filter(s => dmode(s) === "o").flatMap(s => s.vals)) };
  const sc = scopeOf(steps), all = universeOf(k), kept = (k === "year" ? sc.Y : sc.dims[k]) || new Set(all);
  return { type: mine.some(s => dmode(s) === "i") ? "include" : "ignore", kept, all };
}
function rowState(steps, t) {
  if (t.k === "g") { const s = steps.find(x => x.t === "g" && x.f === t.id); return s ? (s.neg ? "exc" : "inc") : "none"; }
  if (t.k === "x") { const s = steps.find(x => x.t === "x" && x.src === t.src && x.term === t.term); return s ? (s.neg ? "exc" : "inc") : "none"; }
  const v = dimView(steps, t.key);
  if (v.type === "none") return "none";
  if (v.type === "multi") return v.inc.has(t.v) ? "inc" : v.exc.has(t.v) ? "exc" : "none";
  if (v.type === "include") return v.kept.has(t.v) ? "inc" : "imp";
  return v.kept.has(t.v) ? "none" : "exc";
}
/* the steps after pressing Include or Ignore on a row: pressing the active side clears it, the other side switches */
function choiceSteps(steps0, t, choice) {
  if (choice === "clear") { const st = rowState(steps0, t); if (st === "inc") choice = "include"; else if (st === "exc") choice = "ignore"; else return steps0.map(clone); }
  const steps = steps0.map(clone);
  if (t.k === "g" || t.k === "x") {
    const i = steps.findIndex(s => (t.k === "g" ? s.t === "g" && s.f === t.id : s.t === "x" && s.src === t.src && s.term === t.term)), want = choice === "ignore";
    if (i < 0) steps.push(t.k === "g" ? { t: "g", f: t.id, neg: want } : { t: "x", src: t.src, term: t.term, neg: want });
    else if (!!steps[i].neg === want) steps.splice(i, 1); else steps[i].neg = want;
    return steps;
  }
  const k = t.key, v = t.v, view = dimView(steps, k); let next;
  const toggle = (list, x, add) => (add === undefined ? (list.includes(x) ? list.filter(y => y !== x) : list.concat(x)) : add ? (list.includes(x) ? list : list.concat(x)) : list.filter(y => y !== x));
  if (view.type === "none") next = [mkDim(k, choice === "include" ? "i" : "o", [v])];
  else if (view.type === "multi") {
    let inc = [...view.inc], exc = [...view.exc];
    if (choice === "include") { const had = inc.includes(v); inc = toggle(inc, v); if (!had) exc = toggle(exc, v, false); }
    else { const had = exc.includes(v); exc = toggle(exc, v); if (!had) inc = toggle(inc, v, false); }
    next = [].concat(inc.length ? [mkDim(k, "i", inc)] : [], exc.length ? [mkDim(k, "o", exc)] : []);
  } else if (view.type === "include") {
    let I = view.all.filter(x => view.kept.has(x));
    if (choice === "include") I = toggle(I, v);
    else if (I.includes(v)) { I = toggle(I, v, false); if (!I.length) { next = [mkDim(k, "o", [v])]; I = null; } }
    if (I) next = I.length ? [mkDim(k, "i", I)] : [];
  } else {
    let O = view.all.filter(x => !view.kept.has(x));
    if (choice === "ignore") O = toggle(O, v);
    else { next = [mkDim(k, "i", [v])]; O = null; }
    if (O) next = O.length ? [mkDim(k, "o", O)] : [];
  }
  const at = steps.findIndex(s => dimSteps([s], k).length), rest = steps.filter(s => !dimSteps([s], k).length);
  rest.splice(at < 0 ? rest.length : Math.min(at, rest.length), 0, ...next);
  return rest;
}
/* ---------- (MODEL-END) ---------- */

/* ---------- global filters: one ordered list of steps, the same kind the corpus builder uses ---------- */
const FKEYS = ["year", ...DIM_KEYS];
const FD = { year: { label: "Year", hint: "ticket creation year", opts: () => L("timeline.per_year").map(r => ({ v: String(r.year), n: r.count })) } };
DIM_KEYS.forEach(k => { FD[k] = { label: DIMS[k].label, hint: DIMS[k].label, opts: () => DIMS[k].values.map(x => ({ v: x.v, n: x.n })) }; });
const F = {}; FKEYS.forEach(k => { F[k] = new Set(); });
const G = { steps: [] };
const T = { q: "", min: 0 };
/* F is the set of values each dimension currently allows, derived from the steps; charts read it */
function deriveF() {
  const sc = scopeOf(G.steps);
  FKEYS.forEach(k => { F[k] = new Set(); });
  if (sc.Y) F.year = new Set(sc.Y);
  DIM_KEYS.forEach(k => {
    if (DIMS[k].multi) {
      const ins = new Set(sc.multis.filter(m => m.key === k && !m.neg).flatMap(m => m.vals)), outs = new Set(sc.multis.filter(m => m.key === k && m.neg).flatMap(m => m.vals));
      if (ins.size) F[k] = ins; else if (outs.size) F[k] = new Set(DIMS[k].values.map(x => x.v).filter(v => !outs.has(v)));
    } else if (sc.dims[k]) F[k] = new Set([...sc.dims[k]].filter(v => v !== "__rest"));
  });
}
const active = () => FKEYS.filter(k => F[k].size);
const anyFilter = () => G.steps.length > 0 || T.q !== "" || T.min > 0;
const slice = (rows, g, by) => rows.filter(r => Object.keys(g).every(k => k === by || !F[k].size || F[k].has(String(g[k](r)))));
const sel = (k, v) => !F[k].size || F[k].has(String(v));
const textOk = s => !T.q || String(s).toLowerCase().includes(T.q.toLowerCase());
const minOk = n => n >= T.min;
const group = (rows, keyFn, valFn = r => r.count) => { const m = new Map(); rows.forEach(r => { const k = keyFn(r); m.set(k, (m.get(k) || 0) + valFn(r)); }); return [...m].map(([k, v]) => ({ k, v })); };
const CAT_ORDER = L("dimensions.categoryId.values").map(r => String(r.value));
const catColor = c => { const i = CAT_ORDER.indexOf(String(c)); return i >= 0 && i < 7 ? `var(--s${i + 1})` : "var(--other)"; };

/* ---------- words for a step ---------- */
const boolPhrase = id => (BOOL.get(id) || {}).phrase || id;
const NEG = [[/^has an? /, "has no "], [/^names an? /, "names no "], [/^is not /, "is "], [/^is an? /, "is not a "], [/^mentions a /, "does not mention a "]];
const negPhrase = p => { for (const [re, to] of NEG) if (re.test(p)) return p.replace(re, to); return "not: " + p; };
function stepLabel(s) {
  if (s.t === "c") s = { t: "d", dim: "cat", mode: s.mode, vals: s.vals };
  if (s.t === "y") return (s.mode === "o" ? "ignore " : "include ") + (s.vals.length === 1 ? "year " + s.vals[0] : "years " + s.vals.join(", "));
  if (s.t === "d") { const d = DIMS[s.dim]; return (d ? d.label : s.dim) + ": " + (s.mode === "i" ? "include " : "ignore ") + s.vals.map(v => v === "__rest" ? (d ? d.restLabel : "rest") : v).join(", "); }
  if (s.t === "g") return (s.neg ? "ignore: " : "include: ") + boolPhrase(s.f);
  if (s.t === "x") return (s.neg ? "ignore: " : "include: ") + (s.src === "title" ? "title" : "solution") + " contains “" + s.term + "”";
  return "?";
}
function shortStep(s) {
  if (s.t === "c") s = { t: "d", dim: "cat", mode: s.mode, vals: s.vals };
  if (s.t === "y") return (s.mode === "o" ? "no " : "") + s.vals.join("/");
  if (s.t === "d") return (s.mode === "o" ? "no " : "") + s.dim + " " + s.vals.join("/");
  if (s.t === "g") return (s.neg ? "no " : "+") + ((BOOL.get(s.f) || {}).short || s.f);
  return (s.neg ? "no " : "") + "“" + s.term + "”";
}

/* ---------- steps in the address bar ---------- */
const esc = v => encodeURIComponent(v).replace(/[!'()*~.]/g, c => "%" + c.charCodeAt(0).toString(16).toUpperCase());
const unesc = v => { try { return decodeURIComponent(v); } catch (e) { return v; } };
function stepStr(s) {
  if (s.t === "y") return "y:" + (s.mode === "o" ? "o" : "i") + ":" + s.vals.map(esc).join("~");
  if (s.t === "d") return ["d", s.dim, s.mode, s.vals.map(esc).join("~")].join(":");
  if (s.t === "g") return ["g", esc(s.f), s.neg ? 1 : 0].join(":");
  if (s.t === "x") return ["x", s.src, esc(s.term), s.neg ? 1 : 0].join(":");
  return "";
}
function strStep(str) {
  const p = str.split(":");
  if (p[0] === "y") { const named = p[1] === "i" || p[1] === "o", vals = (named ? p[2] || "" : p[1] || "").split("~").map(unesc); return vals.length && vals.every(v => M.yearKeys.includes(v)) ? { t: "y", mode: named ? p[1] : "i", vals } : null; }
  if (p[0] === "d") { const d = DIMS[p[1]], vals = (p[3] || "").split("~").filter(Boolean).map(unesc); return d && (p[2] === "i" || p[2] === "o") && vals.length && vals.every(v => d.nOf.has(v) || v === "__rest") ? { t: "d", dim: p[1], mode: p[2], vals } : null; }
  if (p[0] === "g") { const f = unesc(p[1] || ""); return BOOL.has(f) ? { t: "g", f, neg: p[2] === "1" } : null; }
  if (p[0] === "x") { const term = unesc(p[2] || ""); return (p[1] === "title" || p[1] === "sol") && TERMDF.has(p[1] + "|" + term) ? { t: "x", src: p[1], term, neg: p[3] === "1" } : null; }
  return null;
}

/* ---------- tooltip ---------- */
const tip = document.getElementById("tip");
function showTip(ev, lines) {
  tip.replaceChildren(...lines.map(([a, b, c]) => {
    const d = $("div", "tl");
    if (c) { const k = $("i", "k"); k.style.background = c; d.append(k); }
    d.append($("b", "", a)); if (b) d.append($("span", "", b));
    return d;
  }));
  tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + 14, y = ev.clientY + 14;
  if (x + w > innerWidth - 8) x = ev.clientX - w - 14;
  if (y + h > innerHeight - 8) y = ev.clientY - h - 14;
  tip.style.left = Math.max(4, x) + "px"; tip.style.top = Math.max(4, y) + "px";
}
const hideTip = () => { tip.hidden = true; };
function hover(el, linesFn) {
  el.addEventListener("pointermove", e => showTip(e, linesFn(e)));
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); showTip({ clientX: r.left + r.width / 2, clientY: r.top }, linesFn({})); });
  el.addEventListener("blur", hideTip);
}
function pick(el, key, val) {
  el.classList.add("pick"); el.setAttribute("tabindex", "0"); el.setAttribute("role", "button");
  el.setAttribute("aria-pressed", String(F[key].has(String(val))));
  el.setAttribute("aria-label", "Filter " + FD[key].label + " " + val);
  el.addEventListener("click", () => toggleF(key, val));
  el.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleF(key, val); } });
}
/* a click that adds or removes some other kind of filter (a term, a field fact) */
function pickAct(el, on, fn, label) {
  el.classList.add("pick"); el.setAttribute("tabindex", "0"); el.setAttribute("role", "button");
  el.setAttribute("aria-pressed", String(!!on)); el.setAttribute("aria-label", label);
  el.addEventListener("click", fn);
  el.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } });
}

/* ---------- building blocks ---------- */
function responsive(draw) {
  const box = $("div", "rs"); let last = 0;
  let queued = false;
  const ro = new ResizeObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; const w = Math.floor(box.clientWidth); if (w > 0 && w !== last) { last = w; box.replaceChildren(draw(w)); } }); });
  ro.observe(box); return box;
}
function seg(opts, cur, on) {
  const d = $("div", "seg"); d.setAttribute("role", "group");
  opts.forEach(([v, label]) => { const b = $("button", "", label); b.type = "button"; b.setAttribute("aria-pressed", String(String(v) === String(cur))); b.onclick = () => on(v); d.append(b); });
  return d;
}
function selectCtl(opts, cur, on, label) {
  const s = $("select"); s.setAttribute("aria-label", label);
  opts.forEach(([v, l]) => { const o = $("option", "", l); o.value = v; if (v === cur) o.selected = true; s.append(o); });
  s.onchange = () => on(s.value); return s;
}
function table(rows, cols) {
  cols = cols || [...new Set(rows.flatMap(r => Object.keys(r)))].filter(c => typeof rows.find(r => c in r)[c] !== "object");
  const w = $("div", "tw"), t = $("table"), h = $("tr");
  cols.forEach(c => h.append($("th", "", c))); const th = $("thead"); th.append(h); t.append(th);
  const tb = $("tbody");
  rows.slice(0, 300).forEach(r => { const tr = $("tr", r._dim ? "dim" : ""); cols.forEach(c => tr.append($("td", "", c in r && r[c] != null ? fmt(r[c]) : ""))); tb.append(tr); });
  t.append(tb); w.append(t);
  if (rows.length > 300) w.append($("div", "note", "+" + (rows.length - 300) + " more rows in report.json"));
  return w;
}
function facts(list) {
  const dl = $("dl", "facts");
  list.filter(Boolean).forEach(([k, v, note]) => { dl.append($("dt", "", k)); const dd = $("dd", "", v); if (note) dd.append($("small", "", note)); dl.append(dd); });
  return dl;
}
function quantStrip(q, keys) {
  const d = $("div", "qs");
  (keys || Object.keys(q)).forEach(k => { if (k in q) { const s = $("span", "", k); s.append($("b", "", fmt(q[k]))); d.append(s); } });
  return d;
}
function barsH(items, st, o = {}) {
  const box = $("div"); const f = o.fmt || fmt;
  const max = o.max !== undefined ? o.max : Math.max(...items.map(i => i.value), 1e-9);
  const limit = st && st.all ? Infinity : (o.limit || 25);
  items.slice(0, limit).forEach(it => {
    const row = $("div", "row" + (it.dim ? " dim" : "")); row.append($("div", "l", it.label));
    const t = $("div", "t"), i = $("i"); i.style.width = Math.max(0.5, 100 * it.value / max) + "%"; if (it.color) i.style.background = it.color; t.append(i);
    row.append(t, $("div", "n", f(it.value)));
    if (it.fk) pick(row, it.fk, it.fv); else if (it.act) pickAct(row, it.on, it.act, it.actLabel || "Filter by " + it.label);
    hover(row, () => it.tip || [[f(it.value), it.label]]);
    box.append(row);
  });
  if (items.length > limit) { const b = $("button", "linkbtn", "Show all " + items.length); b.type = "button"; b.onclick = () => { st.all = true; renderView(); }; box.append(b); }
  else if (st && st.all && items.length > (o.limit || 25)) { const b = $("button", "linkbtn", "Show fewer"); b.type = "button"; b.onclick = () => { st.all = false; renderView(); }; box.append(b); }
  return box;
}
function columns(items, o = {}) { return responsive(W => columnsDraw(items, { ...o, W })); }
function columnsDraw(items, o) {
  const W = o.W, H = 250, ml = 52, mr = 12, mt = 26, mb = 38, pw = W - ml - mr, ph = H - mt - mb;
  const max = niceMax(Math.max(...items.map(i => i.value), 1));
  const svg = S("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": o.label || "Column chart" });
  [0, 0.5, 1].forEach(f => { const y = mt + ph * (1 - f); svg.append(S("line", { x1: ml, x2: W - mr, y1: y, y2: y, class: f ? "grid-l" : "axis" }), S("text", { x: ml - 6, y: y + 4, class: "tick", "text-anchor": "end" }, (o.fmtAxis || cmp)(max * f))); });
  const band = pw / items.length, bw = Math.min(72, band * 0.68);
  items.forEach((it, i) => {
    const x = ml + band * i + (band - bw) / 2, h = Math.max(1, ph * it.value / max), y = mt + ph - h;
    const g = S("g", { class: "mark" + (it.dim ? " dim" : "") });
    const bar = S("path", { d: topRound(x, y, bw, h, 4), class: "bar" }); if (it.color) bar.style.fill = it.color;
    g.append(S("rect", { x: ml + band * i, y: mt, width: band, height: ph, class: "hit" }), bar);
    if (band >= 34) g.append(S("text", { x: x + bw / 2, y: y - 6, class: "vlab", "text-anchor": "middle" }, (o.fmtVal || cmp)(it.value)));
    if (i % Math.max(1, Math.ceil(70 / band)) === 0) g.append(S("text", { x: x + bw / 2, y: H - 12, class: "xlab", "text-anchor": "middle" }, it.label));
    hover(g, () => it.tip || [[fmt(it.value), it.label]]);
    if (it.fk) pick(g, it.fk, it.fv);
    svg.append(g);
  });
  return svg;
}
function lineArea(pts, o = {}) { return responsive(W => lineAreaDraw(pts, { ...o, W })); }
function lineAreaDraw(pts, o) {
  const W = o.W, H = 280, ml = 52, mr = 14, mt = 20, mb = 38, pw = W - ml - mr, ph = H - mt - mb, n = pts.length;
  const max = niceMax(Math.max(...pts.map(p => p.v || 0), 1));
  const X = i => ml + (n > 1 ? pw * i / (n - 1) : pw / 2), Y = v => mt + ph * (1 - v / max);
  const svg = S("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": o.label || "Line chart" });
  [0, 0.5, 1].forEach(f => { const y = mt + ph * (1 - f); svg.append(S("line", { x1: ml, x2: W - mr, y1: y, y2: y, class: f ? "grid-l" : "axis" }), S("text", { x: ml - 6, y: y + 4, class: "tick", "text-anchor": "end" }, cmp(max * f))); });
  const runs = []; let cur = [];
  pts.forEach((p, i) => { if (p.v == null) { if (cur.length) runs.push(cur); cur = []; } else cur.push([X(i), Y(p.v)]); }); if (cur.length) runs.push(cur);
  runs.forEach(r => {
    if (r.length === 1) { svg.append(S("circle", { cx: r[0][0], cy: r[0][1], r: 3, class: "dot" })); return; }
    svg.append(S("path", { d: "M" + r[0][0] + "," + (mt + ph) + "L" + r.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join("L") + "L" + r[r.length - 1][0] + "," + (mt + ph) + "Z", class: "area" }));
    svg.append(S("path", { d: "M" + r.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join("L"), class: "line" }));
  });
  pts.forEach((p, i) => { if ((i === 0 && !(pts.findIndex((q, j) => j > 0 && q.tick) < 8 && pts.findIndex((q, j) => j > 0 && q.tick) > 0)) || p.tick) svg.append(S("line", { x1: X(i), x2: X(i), y1: mt + ph, y2: mt + ph + 4, class: "axis" }), S("text", { x: X(i), y: H - 8, class: "xlab", "text-anchor": "start", dy: 4 }, p.tick || p.label)); });
  if (o.veil) { let s = null; pts.forEach((p, i) => { const off = o.veil(p); if (off && s === null) s = i; if ((!off || i === n - 1) && s !== null) { const e = off ? i : i - 1; svg.append(S("rect", { x: X(s) - (s ? pw / (n - 1) / 2 : 0), y: mt, width: X(e) - X(s) + pw / (n - 1) * (s ? 0.5 : 0) + pw / (n - 1) * 0.5, height: ph, class: "veil" })); s = null; } }); }
  const cross = S("line", { y1: mt, y2: mt + ph, class: "cross", visibility: "hidden" }), dot = S("circle", { r: 4.5, class: "dot", visibility: "hidden" });
  const ov = S("rect", { x: ml, y: mt, width: pw, height: ph, class: "hit" }); ov.style.cursor = o.onPick ? "pointer" : "default";
  const idx = e => { const r = svg.getBoundingClientRect(); const vx = (e.clientX - r.left) / r.width * W; return Math.max(0, Math.min(n - 1, Math.round((vx - ml) / pw * (n - 1)))); };
  ov.addEventListener("pointermove", e => { const i = idx(e), p = pts[i]; cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible"); if (p.v != null) { dot.setAttribute("cx", X(i)); dot.setAttribute("cy", Y(p.v)); dot.setAttribute("visibility", "visible"); } else dot.setAttribute("visibility", "hidden"); showTip(e, p.v == null ? [["withheld", p.label + " (below the floor of " + K + ")"]] : [[fmt(p.v), p.label, "var(--series)"]]); });
  ov.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });
  if (o.onPick) ov.addEventListener("click", e => o.onPick(pts[idx(e)]));
  svg.append(cross, dot, ov); return svg;
}
function stacked(groups, keys, o) { return responsive(W => stackedDraw(groups, keys, { ...o, W })); }
function stackedDraw(groups, keys, o) {
  const W = o.W, H = 300, ml = 52, mr = 12, mt = 20, mb = 40, pw = W - ml - mr, ph = H - mt - mb, share = o.mode === "share";
  const tot = g => sum(keys, k => g.vals[k] || 0);
  const max = share ? 1 : niceMax(Math.max(...groups.map(tot), 1));
  const svg = S("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": o.label });
  [0, 0.5, 1].forEach(f => { const y = mt + ph * (1 - f); svg.append(S("line", { x1: ml, x2: W - mr, y1: y, y2: y, class: f ? "grid-l" : "axis" }), S("text", { x: ml - 6, y: y + 4, class: "tick", "text-anchor": "end" }, share ? pct(f, 0) : cmp(max * f))); });
  const band = pw / groups.length, bw = Math.min(80, band * 0.7);
  groups.forEach((g, gi) => {
    const t = tot(g) || 1, x = ml + band * gi + (band - bw) / 2; let y = mt + ph;
    const gg = S("g", { class: "mark" + (g.dim ? " dim" : "") });
    gg.append(S("rect", { x: ml + band * gi, y: mt, width: band, height: ph, class: "hit" }));
    keys.forEach(k => {
      const v = g.vals[k] || 0; if (!v) return;
      const h = ph * (share ? v / t : v / max); y -= h;
      const r = S("rect", { x, y, width: bw, height: Math.max(h, 0.5), class: "segr", rx: 2 }); r.style.fill = o.colorOf(k);
      if (o.dimKey && o.dimKey(k)) r.style.opacity = 0.35;
      gg.append(r);
    });
    gg.append(S("text", { x: x + bw / 2, y: H - 10, class: "xlab", "text-anchor": "middle" }, g.label));
    hover(gg, () => [[g.label, fmt(sum(keys, k => g.vals[k] || 0)) + " tickets"], ...keys.filter(k => g.vals[k]).map(k => [fmt(g.vals[k]) + " · " + pct(g.vals[k] / t, 1), o.nameOf(k), o.colorOf(k)])]);
    if (o.fkGroup) pick(gg, o.fkGroup, g.key);
    svg.append(gg);
  });
  return svg;
}
function heat(o) {
  const box = $("div", "heat"); box.style.gridTemplateColumns = `minmax(110px,max-content) repeat(${o.cols.length},minmax(46px,1fr))`;
  box.append($("div"));
  o.cols.forEach(c => { const h = $("div", "hh" + (c.dim ? " dim" : ""), c.label); if (o.colF) pick(h, o.colF, c.key); if (c.tip) hover(h, () => c.tip); box.append(h); });
  const all = []; o.rows.forEach(r => o.cols.forEach(c => { const v = o.val(r, c); if (v != null) all.push(v); }));
  const max = o.max || Math.max(...all, 1e-9);
  o.rows.forEach(r => {
    const rh = $("div", "rh" + (r.dim ? " dim" : ""), r.label); if (o.rowF) pick(rh, o.rowF, r.key); box.append(rh);
    o.cols.forEach(c => {
      const v = o.val(r, c), cell = $("div", "cell" + (r.dim || c.dim ? " dim" : ""));
      if (v == null) { cell.textContent = "–"; cell.classList.add("na"); hover(cell, () => [["no value", r.label + " · " + c.label + " (below the floor or empty)"]]); }
      else { const p = 8 + 80 * v / max; cell.style.background = `color-mix(in srgb,var(--seq) ${p.toFixed(0)}%,var(--surf))`; cell.style.color = p > 52 ? "var(--on-seq)" : "var(--ink)"; cell.textContent = (o.fmt || fmt)(v) + (o.mark ? o.mark(r, c) : ""); hover(cell, () => (o.tip ? o.tip(r, c, v) : [[(o.fmt || fmt)(v), r.label + " · " + c.label]])); }
      box.append(cell);
    });
  });
  return box;
}
function boxes(rows) { return responsive(W => boxesDraw(rows, W)); }
function boxesDraw(rows, W) {
  const rh = 52, ml = 130, mr = 24, mt = 10, mb = 30, H = mt + mb + rh * rows.length, pw = W - ml - mr;
  const vmax = Math.max(...rows.map(r => r.q.max || r.q.p99 || 1), 10), lg = v => Math.log10(Math.max(v, 0.5));
  const lo = lg(0.5), hi = lg(vmax), X = v => ml + pw * (lg(v) - lo) / (hi - lo);
  const svg = S("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Distribution of text lengths on a log scale" });
  for (let t = 1; t <= vmax * 1.01; t *= 10) svg.append(S("line", { x1: X(t), x2: X(t), y1: mt, y2: H - mb, class: "grid-l" }), S("text", { x: X(t), y: H - 8, class: "tick", "text-anchor": "middle" }, cmp(t)));
  rows.forEach((r, i) => {
    const y = mt + rh * i + rh / 2, q = r.q, g = S("g", { class: "mark" });
    g.append(S("rect", { x: ml, y: y - rh / 2, width: pw, height: rh, class: "hit" }), S("text", { x: ml - 8, y: y + 4, class: "xlab", "text-anchor": "end" }, r.label),
      S("line", { x1: X(q.p5), x2: X(q.p95), y1: y, y2: y, class: "axis" }));
    const b = S("rect", { x: X(q.p25), y: y - 8, width: Math.max(2, X(q.p75) - X(q.p25)), height: 16, rx: 3, class: "bar" }); g.append(b,
      S("line", { x1: X(q.p50), x2: X(q.p50), y1: y - 10, y2: y + 10, stroke: "var(--surf)", "stroke-width": 3 }),
      S("circle", { cx: X(q.max), cy: y, r: 3.5, fill: "none", stroke: "var(--ink2)", "stroke-width": 1.5 }));
    hover(g, () => Object.entries(q).map(([k, v]) => [fmt(v), k])); svg.append(g);
  });
  return svg;
}
function partWhole(items, colorOf) {
  const tot = sum(items, i => i.value) || 1, box = $("div");
  const bar = $("div", "part"); bar.setAttribute("role", "img");
  items.forEach(i => { const d = $("div", i.dim ? "dim" : ""); d.style.flex = String(i.value); d.style.background = colorOf(i.label); hover(d, () => [[fmt(i.value) + " · " + pct(i.value / tot), i.label, colorOf(i.label)]]); if (i.fk) pick(d, i.fk, i.fv); bar.append(d); });
  const lg = $("div", "legend");
  items.forEach(i => { const s = $("span"); const sw = $("i", "sw b"); sw.style.background = colorOf(i.label); s.append(sw, document.createTextNode(" " + i.label + " " + pct(i.value / tot) + " (" + fmt(i.value) + ")")); lg.append(s); });
  box.append(bar, lg); return box;
}
function legend(keys, o) {
  const d = $("div", "legend");
  keys.forEach(k => { const b = $("button"); b.type = "button"; const sw = $("i", "sw b"); sw.style.background = o.colorOf(k); b.append(sw, document.createTextNode(o.nameOf(k))); if (o.fk && o.canPick(k)) { b.setAttribute("aria-pressed", String(F[o.fk].has(String(k)))); b.onclick = () => toggleF(o.fk, k); } else b.disabled = true; d.append(b); });
  return d;
}

/* ---------- cards ---------- */
/* **word** in a fixed description becomes bold text; built from text nodes, never parsed as HTML */
function rich(text) {
  const f = document.createDocumentFragment();
  String(text).split("**").forEach((part, i) => { if (part) f.append(i % 2 ? $("strong", "", part) : document.createTextNode(part)); });
  return f;
}
const CS = {};
function card(o) {
  const st = CS[o.id] || (CS[o.id] = {});
  const el = $("section", "card" + (o.wide ? " wide" : "")); el.id = "c-" + o.id;
  const head = $("div", "chead"); head.append($("h2", "", o.title));
  const tools = $("div", "tools"); (o.controls || []).forEach(c => tools.append(c));
  if (o.rows && o.rows.length) tools.append(seg([["chart", "Chart"], ["table", "Table"]], st.view || "chart", v => { st.view = v; renderView(); }));
  const dp = $("p", "desc"); dp.append(rich(o.desc)); head.append(tools); el.append(head, dp);
  if (o.how) { const d = $("details", "how"); d.open = !!st.how; d.addEventListener("toggle", () => { st.how = d.open; }); const hp = $("p"); hp.append(rich(o.how)); d.append($("summary", "", "How to read this"), hp); el.append(d); }
  let body = st.view === "table" && o.rows ? table(o.rows, o.cols) : o.body(st);
  if (!body) { body = $("div", "empty", "Nothing left after the current filters. "); const b = $("button", "linkbtn", "Reset all filters"); b.type = "button"; b.onclick = resetAll; body.append(b); }
  el.append(body, scopeLine(o)); return el;
}
function scopeLine(o) {
  const g = o.g || {}, act = active(), d = $("div", "scope");
  if (o.scopeNote) { d.textContent = o.scopeNote; return d; }
  const can = Object.keys(g).filter(k => k !== o.by).map(k => FD[k].label); if (o.search) can.push("Search"); if (o.min) can.push("Min count");
  if (o.by) can.unshift(FD[o.by].label + " (highlight, click to change)");
  const extra = G.steps.some(s => s.t === "g" || s.t === "x");
  if (!anyFilter()) { d.textContent = can.length ? "Responds to: " + can.join(", ") + "." : "No global filter slices this view of the data."; return d; }
  const applied = act.filter(k => k in g && k !== o.by).map(k => FD[k].label); if (T.q && o.search) applied.push("Search"); if (T.min && o.min) applied.push("Min count");
  const hl = act.filter(k => k === o.by).map(k => FD[k].label);
  const ign = act.filter(k => !(k in g) && k !== o.by).map(k => FD[k].label); if (T.q && !o.search) ign.push("Search"); if (T.min && !o.min) ign.push("Min count");
  if (applied.length) d.append($("span", "on", "Filtered by " + applied.join(", ") + ". "));
  if (hl.length) d.append($("span", "on", "Highlighting " + hl.join(", ") + ". "));
  if (ign.length) d.append(document.createTextNode("Not affected by " + ign.join(", ") + " (this data has no such split). "));
  if (extra) d.append(document.createTextNode("Field and text filters change the totals in the filter bar but cannot slice this view."));
  if (!applied.length && !hl.length && !ign.length && !extra) d.textContent = "Responds to: " + can.join(", ") + ".";
  return d;
}
const tile = (label, value, sub, o = {}) => { const t = $("div", "tile" + (o.scoped && anyFilter() ? " scoped" : "") + (!o.scoped && anyFilter() ? " static" : "")); const b = $("b", o.warn ? "warn" : "", value); t.append(b, $("div", "tl", label), $("div", "ts", (o.scoped && anyFilter() ? "in current filter · " : (anyFilter() ? "all data · " : "")) + (sub || ""))); return t; };

const FIELDS = [["description", "Description"], ["solutions", "Solution"], ["serial", "Vehicle serial"], ["model_id", "Vehicle model id"], ["baugruppe", "Baugruppe"], ["fehlercode", "Error code"], ["hours", "Operating hours"], ["delivery", "Delivery date"]];

/* ---------- views ---------- */
const g_year = { year: r => r.year };
function cardMonths() {
  const rows = L("timeline.per_month"); if (!rows.length) return null;
  return card({
    id: "months", wide: true, title: "Tickets per month", by: "year", g: { year: 1 }, rows: rows.map(r => ({ ...r, _dim: !sel("year", r.month.slice(0, 4)) })), cols: ["month", "count"],
    desc: "How many tickets were created each month. Use it to spot growth, seasonality, **backlog imports** and the **partial first and last month**.",
    how: "Hover for a month's value; click anywhere to filter that year. Months under the release floor (" + K + " tickets) are withheld and would show as gaps. The faded area is outside your year filter.",
    body: () => {
      const m = new Map(rows.map(r => [r.month, r.count])), first = rows[0].month, last = rows[rows.length - 1].month; const pts = [];
      let [y, mo] = first.split("-").map(Number); const [ly, lm] = last.split("-").map(Number);
      while (y < ly || (y === ly && mo <= lm)) { const key = y + "-" + String(mo).padStart(2, "0"); pts.push({ label: key, v: m.has(key) ? m.get(key) : null, tick: mo === 1 ? String(y) : null }); mo++; if (mo > 12) { mo = 1; y++; } }
      return lineArea(pts, { label: "Tickets per month", veil: p => !sel("year", p.label.slice(0, 4)), onPick: p => toggleF("year", p.label.slice(0, 4)) });
    }
  });
}
function cardYears() {
  const rows = L("timeline.per_year"); if (!rows.length) return null;
  return card({
    id: "years", title: "Tickets per year", by: "year", g: { year: 1 }, rows: rows.map(r => ({ ...r, _dim: !sel("year", r.year) })), cols: ["year", "count"],
    desc: "Yearly volume. The first and last year are usually partial, so **compare full years only**.",
    how: "Click a column to filter to that year; click again to remove it.",
    body: () => columns(rows.map(r => ({ label: String(r.year), value: r.count, dim: !sel("year", r.year), fk: "year", fv: r.year })), { label: "Tickets per year" })
  });
}
function cardFill() {
  const rows = L("timeline.fill_by_year"); if (!rows.length) return null;
  return card({
    id: "fill", wide: true, title: "How complete each field is, by year", by: "year", g: { year: 1 }, rows: rows.map(r => ({ ...r, _dim: !sel("year", r.year) })),
    desc: "Share of tickets in which a field is filled, per year. Dark cells are well filled, pale cells are mostly empty. A sudden **pale column or row** marks a **change in how tickets were entered**.",
    how: "Compare along a row to see a field's trend (for example the vehicle model id), and down a column to see what a year's tickets look like. The ticket count per year is in the header tooltip. Click a year to filter.",
    body: () => {
      const years = rows.map(r => r.year);
      return heat({ rows: FIELDS.filter(([k]) => rows.some(r => k in r)).map(([k, l]) => ({ label: l, key: k })), cols: years.map(y => ({ label: String(y), key: y, dim: !sel("year", y) })), colF: "year", max: 1, fmt: v => pct(v, 0), val: (r, c) => { const x = rows.find(z => z.year === c.key); return x ? x[r.key] : undefined; } });
    }
  });
}
function cardRecurrence() {
  const r = get(R, "timeline.recurrence"); if (!r) return null;
  const items = [["within 30 days", r.repeat_within_30_share], ["within 90 days", r.repeat_within_90_share], ["within 365 days", r.repeat_within_365_share]].filter(x => x[1] != null).map(([l, v]) => ({ label: l, value: v, tip: [[pct(v), "of tickets with a serial had an earlier ticket on the same vehicle " + l]] }));
  return card({
    id: "recur", title: "Repeat tickets on the same vehicle", g: {},
    desc: "Of the tickets that carry a vehicle serial, the share that follow an earlier ticket on that vehicle within 30, 90 and 365 days. High values mean **a past ticket is a strong hint for the next one**.",
    how: "Bars are cumulative: a ticket that repeats within 30 days also counts in the 90 and 365 bars. The median gap between consecutive tickets of one vehicle is shown below.",
    body: () => { const b = $("div"); b.append(barsH(items, null, { max: 1, fmt: v => pct(v) }), facts([["Vehicles with tickets", fmt(r.vehicles)], ["Tickets with an earlier ticket", fmt(r.tickets_with_previous), pct(r.tickets_with_previous / TOTAL) + " of all tickets"], ["Serial coverage", pct(get(r, "coverage.share"))]]), $("div", "sub3", "Days between consecutive tickets of one vehicle"), quantStrip(r.gap_days_quantiles)); return b; }
  });
}
function cardResolution() {
  const r = get(R, "timeline.resolution"); if (!r) return null;
  return card({
    id: "resol", title: "Days until the first status change", g: {},
    desc: "How long a ticket took to change status, where both dates exist. Only a small part of the tickets has this, so treat it as indicative.",
    body: () => { const b = $("div"); b.append(facts([["Tickets with the data", pct(get(r, "coverage.share")), fmt(get(r, "coverage.present")) + " of " + fmt(get(r, "coverage.total"))], ["Negative gaps", pct(r.negative_share), "status changed before creation"]]), quantStrip(r.days_to_status_change_quantiles)); return b; }
  });
}
function viewTime() { return [cardMonths(), cardYears(), cardRecurrence(), cardFill(), cardResolution()]; }

function catCounts() {
  const rows = L("dimensions.categoryId.by_year");
  if (F.year.size && rows.length) return group(rows.filter(r => F.year.has(String(r.year))), r => String(r.value)).map(x => ({ value: x.k, count: x.v }));
  return L("dimensions.categoryId.values");
}
function viewCategories() {
  const out = [];
  const by = L("dimensions.categoryId.by_year");
  if (by.length) out.push(card({
    id: "catmix", wide: true, title: "Category mix over the years", by: "cat", g: { year: 1, cat: 1 }, rows: by,
    controls: [seg([["count", "Tickets"], ["share", "Share"]], (CS.catmix || {}).mode || "count", v => { CS.catmix.mode = v; renderView(); })],
    desc: "How the ticket categories divide the volume in each year. Use Share to see the mix, Tickets to see absolute volume.",
    how: "Each column is a year, each colour a category (the same colour everywhere). The **grey part** is tickets in categories or cells under the release floor. Click a segment or legend entry to filter by that category, click a year label to filter by year.",
    body: st => {
      const years = L("timeline.per_year").map(r => String(r.year));
      const groups = years.map(y => { const vals = {}; by.filter(r => String(r.year) === y).forEach(r => { vals[String(r.value)] = (vals[String(r.value)] || 0) + r.count; }); const known = sum(Object.values(vals), v => v); const tot = (L("timeline.per_year").find(r => String(r.year) === y) || {}).count || known; vals.__other = Math.max(0, tot - known); return { label: y, key: y, vals, dim: !sel("year", y) }; });
      const keys = [...new Set([...CAT_ORDER, ...by.map(r => String(r.value))])].concat("__other");
      const o = { mode: st.mode || "count", label: "Category mix per year", colorOf: k => k === "__other" ? "var(--other)" : catColor(k), nameOf: k => k === "__other" ? "Other / below floor" : "Category " + k, fkGroup: "year", dimKey: k => F.cat.size && k !== "__other" && !F.cat.has(k) };
      const w = $("div"); w.append(stacked(groups, keys, o), legend(keys, { colorOf: o.colorOf, nameOf: o.nameOf, fk: "cat", canPick: k => k !== "__other" })); return w;
    }
  }));
  const counts = catCounts();
  out.push(card({
    id: "cats", title: "Tickets per category", by: "cat", g: { year: 1, cat: 1 }, min: true, rows: counts.map(r => ({ ...r, _dim: !sel("cat", r.value) })), cols: ["value", "count"],
    desc: "Ticket volume per category id. A single **dominant category** means categories alone will not separate problems for retrieval.",
    how: "Bars show the filtered years only. Click a bar to filter by the category.",
    body: st => { const it = counts.filter(r => minOk(r.count)).map(r => ({ label: "Category " + r.value, value: r.count, color: catColor(r.value), dim: !sel("cat", r.value), fk: "cat", fv: r.value, tip: [[fmt(r.count), "Category " + r.value], [pct(r.count / (profile(G.steps).n.est || TOTAL)), "of tickets in view"]] })); return it.length ? barsH(it, st, { limit: 30 }) : null; }
  }));
  const bc = L("dimensions.by_category");
  if (bc.length) out.push(card({
    id: "catprofile", wide: true, title: "What each category looks like", by: "cat", g: { cat: r => r.value }, rows: bc.map(r => ({ ...r, _dim: !sel("cat", r.value) })),
    desc: "Per category: how often a solution and a description are filled, and how long the problem text is (words). It shows which categories can feed a retrieval index.",
    how: "Bars show fill rates from 0 to 100 percent. Problem text length is the title plus description in whitespace words; p95 marks the long tail.",
    body: () => {
      const w = $("div"); const mx = Math.max(...bc.map(r => r.count), 1);
      bc.forEach(r => {
        const row = $("div", "cm" + (sel("cat", r.value) ? "" : " dim")); row.append($("div", "", "Category " + r.value));
        const t = $("div", "tr"), i = $("i"); i.style.width = (100 * r.count / mx) + "%"; i.style.background = catColor(r.value); t.append(i); row.append(t, $("div", "n", fmt(r.count)));
        pick(row, "cat", r.value); hover(row, () => [[fmt(r.count) + " tickets", "Category " + r.value, catColor(r.value)], [pct(r.solution_fill), "have a solution"], [pct(r.description_fill), "have a description"], [fmt(r.problem_text_length_median) + " / " + fmt(r.problem_text_length_p95), "problem text words, median / p95"]]);
        w.append(row);
      });
      w.append($("div", "sub3", "Fill and length per category"), table(bc.map(r => ({ category: r.value, tickets: r.count, "solution filled": pct(r.solution_fill), "description filled": pct(r.description_fill), "median words": r.problem_text_length_median, "p95 words": r.problem_text_length_p95, _dim: !sel("cat", r.value) }))));
      return w;
    }
  }));
  const DPATH = { status: "statusId", prio: "priorityId", sub: "subStatusString", vstat: "vehicleStatus", show: "showInProteam" };
  const dims = ["status", "prio", "sub", "vstat", "show"].filter(k => DIMS[k]).map(k => [k, DIMS[k].label]);
  if (dims.length) {
    const cur = dims.some(d => d[0] === (CS.dimother || {}).dim) ? CS.dimother.dim : dims[0][0], rowsOf = () => (F.year.size ? group(L("dimensions." + DPATH[cur] + ".by_year").filter(r => F.year.has(String(r.year))), r => r.value).map(x => ({ value: x.k, count: x.v })) : L("dimensions." + DPATH[cur] + ".values"));
    out.push(card({
      id: "dimother", title: "Other ticket attributes", by: cur, g: { year: 1, [cur]: 1 }, min: true, search: true,
      controls: [selectCtl(dims, cur, v => { CS.dimother.dim = v; renderView(); }, "Attribute")],
      rows: rowsOf().map(r => ({ ...r, _dim: !sel(cur, r.value) })),
      desc: "Distribution of the remaining ticket attributes. The coverage line says how many tickets carry the attribute at all.",
      how: "Pick an attribute above, then **click a bar to filter by that value**. With a year filter the bars sum the per-year cells that are above the release floor, so rare values can disappear.",
      body: st => { const it = rowsOf().filter(r => minOk(r.count) && textOk(r.value)).sort((a, b) => b.count - a.count).map(r => ({ label: String(r.value), value: r.count, dim: !sel(cur, r.value), fk: cur, fv: r.value })); const w = $("div"); w.append(it.length ? barsH(it, st) : $("div", "empty", "No values to show.")); w.append($("div", "note", "Coverage " + pct(N("dimensions." + DPATH[cur] + ".coverage.share") || 0) + " of tickets · " + (N("dimensions." + DPATH[cur] + ".distinct") || 0) + " distinct values in total.")); return w; }
    }));
  }
  return out;
}

function viewVehicles() {
  const out = [], models = L("origin.vehicles.models");
  if (models.length) out.push(card({
    id: "models", title: "Vehicle models", by: "model", g: { model: 1 }, min: true, search: true, rows: models.map(r => ({ ...r, _dim: !sel("model", r.model) })),
    desc: "Tickets per vehicle model id. The ids are opaque; a **lookup table from the client** is needed to read them as names.",
    how: "Click a bar to filter by the model. Models under the release floor are withheld, so the list ends at the floor.",
    body: st => { const it = models.filter(r => minOk(r.count) && textOk(r.model)).map(r => ({ label: "Model " + r.model, value: r.count, dim: !sel("model", r.model), fk: "model", fv: r.model, tip: [[fmt(r.count), "Model " + r.model], [pct(r.count / TOTAL), "of all tickets"]] })); return it.length ? barsH(it, st, { limit: 20 }) : null; }
  }));
  const vy = L("origin.vehicles.vehicle_years");
  if (vy.length) out.push(card({
    id: "vyears", title: "Vehicle year", g: {}, rows: vy,
    desc: "Tickets by the year attached to the vehicle (not the year of the ticket). It tells how old the fleet in the data is.",
    body: () => columns(vy.map(r => ({ label: String(r.year), value: r.count })), { label: "Tickets by vehicle year" })
  }));
  const s = get(R, "origin.vehicles.serials");
  if (s) out.push(card({
    id: "serials", title: "Tickets per vehicle", g: {},
    desc: "How the tickets spread over individual vehicles (by serial). A high repeat rate means many vehicles come back more than once.",
    how: "The percentiles say how many tickets one vehicle has: p50 is the typical vehicle, p99 the heavy users, max the single worst vehicle.",
    body: () => { const w = $("div"); w.append(facts([["Serial filled", pct(get(s, "coverage.share")), fmt(get(s, "coverage.present")) + " tickets"], ["Distinct vehicles", fmt(s.distinct)], ["Tickets on a vehicle with another ticket", pct(s.repeat_rate)], ["Top 1% of vehicles hold", pct(s.top_percent_share), "of the tickets"]]), $("div", "sub3", "Tickets per vehicle, percentiles"), quantStrip(s.tickets_per_serial_quantiles)); return w; }
  }));
  return out;
}

function bgCounts() {
  const by = L("origin.baugruppe.by_year");
  if (F.year.size && by.length) return group(by.filter(r => F.year.has(String(r.year))), r => String(r.value)).map(x => ({ value: x.k, count: x.v })).sort((a, b) => b.count - a.count);
  return L("origin.baugruppe.top");
}
function viewBaugruppe() {
  const out = [], b = get(R, "origin.baugruppe"); if (!b) return out;
  const rows = bgCounts();
  out.push(card({
    id: "bgtop", title: "Tickets per Baugruppe", by: "baug", g: { year: 1, baug: 1 }, min: true, search: true, rows: rows.map(r => ({ ...r, _dim: !sel("baug", r.value) })), cols: ["value", "count"],
    desc: "Tickets per Baugruppe id (a component group). Only a quarter of the tickets carry one and the ids are opaque, so it is a **weak signal** until the client's lookup table exists.",
    how: "A ticket can list several Baugruppe ids and then counts once per id. Click a bar to filter by that Baugruppe.",
    body: st => { const it = rows.filter(r => minOk(r.count) && textOk(r.value)).map(r => ({ label: "Baugruppe " + r.value, value: r.count, dim: !sel("baug", r.value), fk: "baug", fv: r.value, tip: [[fmt(r.count), "Baugruppe " + r.value], [pct(r.count / TOTAL), "of all tickets"]] })); return it.length ? barsH(it, st) : null; }
  }));
  const by = L("origin.baugruppe.by_year");
  if (by.length) out.push(card({
    id: "bgyear", title: "Baugruppe by year", by: "baug", g: { year: 1, baug: 1 }, rows: by.map(r => ({ ...r, _dim: !sel("baug", r.value) || !sel("year", r.year) })),
    desc: "Tickets per Baugruppe and year. It shows whether a component group is a long-running theme or a one-year spike.",
    how: "Darker cells are more tickets. Dashes are cells under the release floor. Click a row or column header to filter.",
    body: () => { const vals = [...new Set(by.map(r => String(r.value)))], yrs = [...new Set(by.map(r => String(r.year)))].sort(); return heat({ rows: vals.map(v => ({ label: "Baugruppe " + v, key: v, dim: !sel("baug", v) })), cols: yrs.map(y => ({ label: y, key: y, dim: !sel("year", y) })), rowF: "baug", colF: "year", val: (r, c) => { const x = by.find(z => String(z.value) === r.key && String(z.year) === c.key); return x ? x.count : undefined; } }); }
  }));
  const pairs = L("origin.baugruppe.pairs");
  if (pairs.length) out.push(card({
    id: "bgpairs", title: "Baugruppe ids that appear together", g: { baug: r => r.value }, min: true, rows: pairs,
    desc: "Pairs of Baugruppe ids listed on the same ticket. Frequent pairs hint at related components or at one fault touching two groups.",
    how: "The Baugruppe filter keeps pairs in which either id is selected.",
    body: st => { const it = pairs.filter(r => minOk(r.count) && (!F.baug.size || F.baug.has(String(r.value)) || F.baug.has(String(r.partner)))).map(r => ({ label: r.value + " + " + r.partner, value: r.count })); return it.length ? barsH(it, st) : null; }
  }));
  const cells = L("origin.baugruppe_model_year.cells");
  if (cells.length) out.push(card({
    id: "bgmodel", title: "Baugruppe, model and year together", g: { baug: r => r.value, model: r => r.model, year: r => r.year }, min: true, rows: cells,
    desc: "The few Baugruppe, model and year combinations with enough tickets to be released. Everything below the floor is withheld.",
    how: "Few cells survive because three splits together make each cell small. " + fmt(get(R, "origin.baugruppe_model_year.withheld.below_floor.rows") || 0) + " ticket rows are withheld.",
    body: st => { const it = slice(cells, { baug: r => r.value, model: r => r.model, year: r => r.year }).filter(r => minOk(r.count)).map(r => ({ label: "B" + r.value + " · model " + r.model + " · " + r.year, value: r.count })); return it.length ? barsH(it, st) : null; }
  }));
  out.push(card({
    id: "bgfacts", title: "Baugruppe data quality", g: {},
    desc: "How reliable the Baugruppe field is as a signal.",
    body: () => { const q = b.concentration || {}; return facts([["Filled", pct(get(b, "coverage.share")), fmt(get(b, "coverage.present")) + " of " + fmt(get(b, "coverage.total")) + " tickets"], ["Explicitly empty", pct(get(b, "empty.share"))], ["Distinct ids", fmt(b.distinct)], ["Tickets with several ids", pct(b.multi_share)], ["Top 1 / 5 / 10 ids hold", [q.top1_share, q.top5_share, q.top10_share].map(v => v == null ? "?" : pct(v, 0)).join(" / "), "of the assignments"], ["Concentration (gini)", fmt(q.gini)]]); }
  }));
  return out;
}

function viewLifecycle() {
  const out = [];
  [["hours", "hours", "Operating hours at ticket time", "How many operating hours the machine had when the ticket was created. Few tickets carry the value."], ["days_since_delivery", "days", "Days since delivery", "How long after delivery the ticket arrived. Early tickets point to start-up or delivery problems."]].forEach(([k, dk, title, desc]) => {
    const l = get(R, "lifecycle." + k); if (!l) return;
    out.push(card({
      id: "lc" + k, title, by: dk, g: { [dk]: 1 }, rows: l.buckets, desc,
      how: "Click a column to filter to that range. Buckets are ordered ranges, not categories. Coverage says how many tickets have the value at all, and percentiles describe those that do.",
      body: () => { const w = $("div"); w.append(columns(l.buckets.map(r => ({ label: String(r.bucket), value: r.count, dim: !sel(dk, r.bucket), fk: dk, fv: String(r.bucket) })), { label: title }), facts([["Tickets with a value", pct(get(l, "coverage.share")), fmt(get(l, "coverage.present")) + " of " + fmt(get(l, "coverage.total"))]]), quantStrip(l.quantiles)); return w; }
    }));
  });
  const w = get(R, "lifecycle.warranty");
  if (w) out.push(card({
    id: "warranty", title: "Warranty status", by: "warr", g: { warr: 1 }, rows: w.states,
    desc: "Whether the ticket arrived inside or outside the warranty period. Unknown means the dates were missing.",
    how: "Click a segment to filter by it. Only tickets with both warranty dates can be placed; the rest are unknown. The coverage figure shows how many that is.",
    body: () => { const c = { in: "var(--s3)", out: "var(--s2)", unknown: "var(--other)" }; const x = $("div"); x.append(partWhole(w.states.map(r => ({ label: r.state, value: r.count, dim: !sel("warr", r.state), fk: "warr", fv: r.state })), l => c[l] || "var(--s1)"), $("div", "note", "Warranty dates known for " + pct(get(w, "coverage.share")) + " of tickets.")); return x; }
  }));
  return out;
}

const TERMS = {
  sol: { 1: ["vocabulary.solutions.tokens", "vocabulary.solutions.tokens_omitted"], 2: ["vocabulary.solutions.bigrams", "vocabulary.solutions.bigrams_omitted"], 3: ["vocabulary.solutions.trigrams", "vocabulary.solutions.trigrams_omitted"] },
  title: { 1: ["origin.titles.tokens", "origin.titles.tokens_omitted"], 2: ["origin.titles.bigrams", "origin.titles.bigrams_omitted"], 3: ["vocabulary.titles_trigrams.trigrams", "vocabulary.titles_trigrams.trigrams_omitted"] },
};
function viewText() {
  const out = [], st0 = CS.terms || (CS.terms = {}), src = st0.src || "sol", n = st0.n || 2;
  const [path, omitPath] = TERMS[src][n]; let rows = L(path);
  const catScoped = src === "title" && n === 1 && F.cat.size > 0;
  if (catScoped) rows = group(L("vocabulary.by_category").filter(r => F.cat.has(String(r.value))).flatMap(r => r.title_tokens || []), r => r.token).map(x => ({ token: x.k, count: x.v })).sort((a, b) => b.count - a.count);
  out.push(card({
    id: "terms", wide: true, title: "Frequent terms", g: catScoped ? { cat: 1 } : {}, min: true, search: true, rows,
    controls: [seg([["sol", "Solutions"], ["title", "Ticket titles"]], src, v => { st0.src = v; renderView(); }), seg([[1, "Words"], [2, "2 words"], [3, "3 words"]], n, v => { st0.n = Number(v); renderView(); })],
    desc: "The most frequent words and phrases in solutions or ticket titles. Solutions are mostly **workflow notes** (callbacks, extensions, closings), which is why a plain keyword match on them fits poorly.",
    how: "Longer phrases are more telling: look at 3-word phrases to see the stock sentences. Use the search box above to find a term, and **click a bar to keep only tickets that contain it**. Only terms in at least " + K + " tickets are released. The category filter applies to single title words only.",
    body: st => {
      const it = rows.filter(r => minOk(r.count) && textOk(r.token)).map(r => { const known = TERMDF.has(src + "|" + r.token), o = { label: r.token, value: r.count, tip: [[fmt(r.count), r.token], [pct(r.count / TOTAL), "of all tickets"], known ? ["click to filter", (src === "title" ? "titles" : "solutions") + " containing it"] : ["", ""]] }; if (known) { o.act = () => toggleTerm(src, r.token); o.on = hasTerm(src, r.token); o.actLabel = "Filter " + (src === "title" ? "titles" : "solutions") + " containing " + r.token; } return o; });
      if (!it.length) return null; const w = $("div"); w.append(barsH(it, st, { limit: 30 }));
      const om = N(omitPath); if (om) w.append($("div", "note", fmt(om) + " more terms were left out of the report.")); return w;
    }
  }));
  const len = get(R, "text.lengths");
  if (len) out.push(card({
    id: "lengths", wide: true, title: "How long the texts are", g: {}, rows: ["title", "description", "solutions", "problem_text"].filter(k => len[k]).map(k => ({ field: k, ...len[k] })),
    desc: "Length of each text field in words, on a logarithmic scale. **Short texts need context** to be retrievable; the **long tail needs chunking**.",
    how: "The box spans the middle half of tickets (p25 to p75), the white line is the median, the whisker runs from p5 to p95 and the circle marks the longest text. Hover for all percentiles.",
    body: () => boxes(["title", "description", "solutions", "problem_text"].filter(k => len[k]).map(k => ({ label: k.replace("_", " "), q: len[k] })))
  }));
  const idp = get(R, "text.identifiers");
  if (idp) out.push(card({
    id: "idents", title: "Identifiers written inside the texts", g: {},
    desc: "Share of tickets whose free text contains something that looks like an error code or id. Such tokens are strong exact-match keys for retrieval.",
    how: "Hover for the ticket counts, before and after cleaning obvious noise.",
    body: () => { const w = $("div"); [["problem", "In problem text"], ["solutions", "In solutions"]].forEach(([k, t]) => { const x = get(idp, k); if (!x) return; w.append($("div", "sub3", t + " (any: " + pct(x.any_share_after_cleaning != null ? x.any_share_after_cleaning : x.any_share) + ")")); w.append(barsH((x.by_kind || []).map(r => ({ label: r.kind, value: r.share, tip: [[fmt(r.tickets) + " tickets", r.kind], [fmt(r.tickets_after_cleaning), "after cleaning"]] })), null, { max: Math.max(...(x.by_kind || []).map(r => r.share), 0.01), fmt: v => pct(v) })); }); return w; }
  }));
  const rp = get(R, "text.repetition");
  if (rp) out.push(card({
    id: "repeat", title: "Boilerplate and near-duplicates", g: {},
    desc: "How much of the problem text is repeated. Near-duplicate clusters inflate any index and hide real variety.",
    how: "Tickets are grouped by near-identical problem text. Singletons are unique; a cluster of at least " + K + " tickets counts as templated.",
    body: () => facts([["Clusters", fmt(rp.cluster_count)], ["Unique texts (singletons)", fmt(rp.singleton_count), pct(rp.singleton_count / TOTAL) + " of tickets"], ["Tickets in clusters of at least " + K, pct(rp.share_in_clusters_at_least_k)], ["Largest cluster", pct(rp.largest_cluster_share), "of all tickets"], ["Blank problem text", fmt(rp.blank_problem_text)]])
  }));
  return out;
}

function viewWho() {
  const c = get(R, "concentration"); if (!c) return [];
  const rows = Object.entries(c).map(([k, v]) => ({ entity: k, ...v })).sort((a, b) => (b.top10_share || 0) - (a.top10_share || 0));
  return [card({
    id: "conc", wide: true, title: "How concentrated the tickets are", g: {}, rows: rows.map(r => ({ entity: r.entity, distinct: r.distinct, filled: get(r, "coverage.share"), top1: r.top1_share, top5: r.top5_share, top10: r.top10_share, gini: r.gini })),
    desc: "For each person or entity field: what share of the tickets the single biggest, the top 5 and the top 10 values account for. It shows whether a few people or customers write most of the data.",
    how: "The three overlaid bars are the share of tickets held by the top 1, top 5 and top 10 values, all on one 0 to 100 percent scale. **Gini near 1** means very uneven. A field with **low coverage** says little, so check the right column.",
    body: () => {
      const w = $("div"), lg = $("div", "legend"); [["var(--lo)", "top 10"], ["var(--mid)", "top 5"], ["var(--hi)", "top 1"]].forEach(([c, t]) => { const s = $("span"); const sw = $("i", "sw b"); sw.style.background = c; s.append(sw, document.createTextNode(" " + t)); lg.append(s); }); w.append(lg);
      rows.forEach(r => {
        const row = $("div", "cm"); row.append($("div", "", r.entity + " (" + pct(get(r, "coverage.share") || 0, 0) + " filled)")); const t = $("div", "tr");
        [[r.top10_share, "var(--lo)"], [r.top5_share, "var(--mid)"], [r.top1_share, "var(--hi)"]].forEach(([v, col]) => { const i = $("i"); i.style.width = (100 * (v || 0)) + "%"; i.style.background = col; t.append(i); });
        row.append(t, $("div", "n", "gini " + fmt(r.gini))); row.setAttribute("tabindex", "0");
        hover(row, () => [[pct(r.top1_share), "top 1 value", "var(--hi)"], [pct(r.top5_share), "top 5", "var(--mid)"], [pct(r.top10_share), "top 10", "var(--lo)"], [fmt(r.distinct), "distinct values"], [pct(get(r, "coverage.share")), "of tickets have this field"]]); w.append(row);
      }); return w;
    }
  })];
}

function viewQuality() {
  const out = [], rd = get(R, "readiness");
  if (rd) {
    const RMAP = { solution_present: { id: "solutions", neg: false }, templated: { id: "boiler", neg: true } };
    const defs = [["solution_present", "Has a solution", "the solution field holds text"], ["usable", "Usable", "has a solution and the problem text is not boilerplate"], ["complete_triple", "Title + description + solution", "all three fields hold text"], ["templated", "Boilerplate problem text", "problem text is in a near-duplicate cluster of at least " + K], ["duplicate_solution_share", "Same solution shared", "an identical solution text is used by at least " + K + " tickets"]];
    out.push(card({
      id: "ready", wide: true, title: "How much could a retrieval system use", g: {}, rows: defs.filter(d => rd[d[0]]).map(d => ({ measure: d[1], tickets: rd[d[0]].tickets, share: rd[d[0]].share })),
      desc: "Share of all tickets that meet each readiness test. **Usable** tickets are the realistic candidate pool for the knowledge base.",
      how: "Bars share one scale (0 to 100 percent of all tickets). The tests overlap, so they do not add up. The definition of each test is listed below the chart.",
      body: () => { const w = $("div"); w.append(barsH(defs.filter(d => rd[d[0]]).map(d => ({ label: d[1], value: rd[d[0]].share, tip: [[pct(rd[d[0]].share) + " · " + fmt(rd[d[0]].tickets), d[1]], [d[2], ""]], ...(RMAP[d[0]] ? { act: () => toggleGate(RMAP[d[0]].id, RMAP[d[0]].neg), on: hasGate(RMAP[d[0]].id), actLabel: "Filter: " + d[1] } : {}) })), null, { max: 1, fmt: v => pct(v) })); w.append(facts(defs.filter(d => rd[d[0]]).map(d => [d[1], d[2]]))); return w; }
    }));
  }
  const COVMAP = { vehicleSerialNo: "serial", vehicleModelId: "model_id", baugruppe: "baugruppe", fehlercode: "fehlercode", hours: "hours", deliveryDate: "delivery" };
  const cov = [];
  const add = (name, sec, c) => { if (c && c.share != null) cov.push({ label: name, section: sec, value: c.share, present: c.present, total: c.total }); };
  Object.entries(get(R, "formats") || {}).forEach(([k, v]) => add(k, "format", v.coverage));
  Object.entries(get(R, "dimensions") || {}).forEach(([k, v]) => { if (isObj(v)) add(k, "dimension", v.coverage); });
  Object.entries(get(R, "concentration") || {}).forEach(([k, v]) => add(k, "entity", v.coverage));
  add("baugruppe", "origin", get(R, "origin.baugruppe.coverage"));
  ["hours", "days_since_delivery", "warranty"].forEach(k => add(k, "lifecycle", get(R, "lifecycle." + k + ".coverage")));
  add("first status change", "timeline", get(R, "timeline.resolution.coverage"));
  const seen = new Set(); const covU = cov.filter(c => { if (seen.has(c.label)) return false; seen.add(c.label); return true; }).sort((a, b) => a.value - b.value);
  if (covU.length) out.push(card({
    id: "cover", title: "How often each field is filled", g: {}, min: false, search: true, rows: covU.map(c => ({ field: c.label, kind: c.section, filled: c.present, of: c.total, share: c.value })),
    desc: "Share of all tickets in which each field has a value, least filled first. Fields **near zero** cannot support filtering or retrieval.",
    how: "Sorted ascending, so the weakest fields are on top. **Click a field to keep only tickets where it is filled.** Use the search box to find a field. Fill by year is on the Volume & time view.",
    body: st => { const it = covU.filter(c => textOk(c.label)).map(c => ({ label: c.label, value: c.value, tip: [[pct(c.value), c.label], [fmt(c.present) + " of " + fmt(c.total), c.section]], ...(COVMAP[c.label] ? { act: () => toggleGate(COVMAP[c.label], false), on: hasGate(COVMAP[c.label]), actLabel: "Filter: " + c.label + " is filled" } : {}) })); return it.length ? barsH(it, st, { max: 1, fmt: v => pct(v), limit: 30 }) : null; }
  }));
  const fm = get(R, "formats");
  if (fm) {
    const names = Object.keys(fm).filter(k => (fm[k].shapes || []).length); const cur = (CS.shapes || {}).f && names.includes(CS.shapes.f) ? CS.shapes.f : names[0];
    if (cur) out.push(card({
      id: "shapes", title: "Shapes of the values", g: {}, min: true, search: true, rows: fm[cur].shapes,
      controls: [selectCtl(names.map(n => [n, n]), cur, v => { CS.shapes.f = v; renderView(); }, "Field")],
      desc: "How the values of a field are written, with letters shown as L and digits as D. Several shapes in one field mean mixed or dirty entry.",
      how: "Pick a field above. A field with one shape is clean; many rare shapes show free-text, typos or several formats. Percentiles describe the value length in characters.",
      body: st => { const f = fm[cur], it = f.shapes.filter(r => minOk(r.count) && textOk(r.shape)).map(r => ({ label: r.shape, value: r.count })); const w = $("div"); w.append(it.length ? barsH(it, st) : $("div", "empty", "No shapes to show.")); w.append(facts([["Filled", pct(get(f, "coverage.share"))], ["Distinct values", fmt(f.distinct)], f.multi_code_share != null ? ["Tickets with several codes", pct(f.multi_code_share)] : null]), quantStrip(f.length_quantiles)); return w; }
    }));
    const sv = fm.serial_vehicle_id;
    if (sv) out.push(card({
      id: "consist", title: "Do serial and vehicle id agree", g: {},
      desc: "Consistency between the vehicle serial and the vehicle id on the same ticket. One serial should map to one vehicle.",
      body: () => facts([["Tickets with both", fmt(sv.tickets_with_both)], ["Serials with several vehicle ids", fmt(sv.serials_with_several_vehicle_ids)], ["Vehicle ids with several serials", fmt(sv.vehicle_ids_with_several_serials), "a vehicle id is not a safe key"]])
    }));
  }
  return out;
}

function viewWithheld() {
  const sup = L("suppression"), out = [];
  out.push(card({
    id: "checks", title: "Release checks", g: {},
    desc: "Every value in this report passed the release rules: rare values are withheld, name-like values are dropped and the guard accepted the whole file.",
    body: () => facts([["Self-check", get(R, "selfcheck.passed") ? "passed" : "FAILED"], ["Minimum frequency (floor)", String(K), "values in fewer tickets are not released"], ["Serial prefixes", get(R, "provenance.serial_prefixes_enabled") ? "released" : "off"], ["Code commit", String(get(R, "provenance.code_commit") || "?")], ["Stage", String(get(R, "provenance.stage") || "?")]])
  }));
  const bySec = group(sup, r => r.section, r => r.rows || 0).filter(x => x.v > 0).sort((a, b) => b.v - a.v);
  out.push(card({
    id: "withheld", wide: true, title: "What was held back", g: {}, min: true, search: true, rows: sup,
    desc: "Ticket rows that fell under the floor and were withheld, per report section. Large numbers mean the chart above it shows **only the head of a long tail**.",
    how: "Use this to judge how much of a distribution is hidden. A section with many withheld rows is dominated by rare values, so its charts will not add up to the total.",
    body: st => { const it = bySec.filter(x => minOk(x.v) && textOk(x.k)).map(x => ({ label: x.k, value: x.v })); return it.length ? barsH(it, st, { limit: 20 }) : null; }
  }));
  return out;
}

function viewRaw() {
  const keys = Object.keys(R).filter(k => isObj(R[k]) || Array.isArray(R[k])), st0 = CS.raw || (CS.raw = {}), cur = keys.includes(st0.k) ? st0.k : keys[0];
  const rend = (node) => {
    const f = $("div");
    if (Array.isArray(node)) { if (!node.length) f.append($("div", "note", "(empty)")); else if (isObj(node[0])) f.append(table(node)); else f.append($("div", "", node.map(fmt).join(", "))); return f; }
    if (!isObj(node)) { f.append($("div", "", fmt(node))); return f; }
    if ("p50" in node) { f.append(quantStrip(node)); return f; }
    const sc = Object.entries(node).filter(([, v]) => !v || typeof v !== "object"); if (sc.length) f.append(facts(sc.map(([k, v]) => [k, fmt(v)])));
    Object.entries(node).forEach(([k, v]) => { if (v && typeof v === "object") { f.append($("div", "sub3", k)); f.append(rend(v)); } }); return f;
  };
  return [card({ id: "raw", wide: true, title: "Report data as stored", g: {}, controls: [selectCtl(keys.map(k => [k, k]), cur, v => { st0.k = v; renderView(); }, "Section")], desc: "The raw numbers of one report section, without charts. Everything on the other views is drawn from these.", body: () => rend(R[cur]) })];
}

function viewAbout() {
  const gl = [["Ticket", "One row of the export: a support case with a title, description, solution and a few ids."], ["Floor (minimum frequency)", "A value is only released if at least " + K + " tickets carry it. Anything rarer is withheld, so lists end at the floor and charts may not add up to the total."], ["Fill / coverage", "The share of tickets in which a field has a value."], ["Baugruppe", "A component or assembly group id. Opaque until the client provides a lookup table."], ["Serial and vehicle id", "The serial number identifies a vehicle; vehicle ids are not unique per serial, so the serial is the safer key."], ["Repeat ticket", "A ticket that follows an earlier ticket on the same vehicle (same serial)."], ["Templated", "A ticket whose problem text sits in a near-duplicate cluster of at least " + K + " tickets (boilerplate)."], ["Usable", "A ticket that has a solution and is not templated: the realistic pool for a retrieval system."], ["Gini", "A 0 to 1 measure of inequality: 0 means all values are equally frequent, near 1 means a few dominate."], ["Percentiles", "p50 is the median, p95 means 95 percent of values are at or below it."]];
  const filt = card({ id: "howfilter", title: "How the filters work", g: {}, desc: "The report holds aggregates, not tickets, so a filter can only slice data that the report already split that way.", body: () => { const d = $("div"); d.append(facts([["Slicing filters", "year, category, status, priority, vehicle status, ProTeam, model, Baugruppe, warranty, hours and day buckets slice the charts that carry that split; in their own chart they highlight instead of hiding"], ["Counting filters", "field present or missing, repeat ticket, ids in text and words in the title or solution cannot slice a chart, but change the totals and quality numbers in the filter bar"], ["Search, Min count", "apply to ranked lists of terms, values and fields"], ["Add and change", "click bars, columns, cells and legend entries; press / or + Add filter to search every filter; click a filter pill to edit it"]]), $("div", "note", "Filters combine only where the report itself holds the combination, and those cells obey the floor. Click bars, columns, cells and legend entries to set filters; remove them in the bar at the top. Filters are kept in the address (#) so a view can be shared as a link to the local file.")); return d; } });
  const g = card({ id: "glossary", wide: true, title: "Glossary", g: {}, desc: "Terms used on these views.", body: () => { const dl = $("dl", "gl"); gl.forEach(([t, d]) => { dl.append($("dt", "", t), $("dd", "", d)); }); return dl; } });
  return [filt, g];
}

/* ---------- overview ---------- */
function signals() {
  const out = [], K50 = K, y = L("timeline.fill_by_year").filter(r => r.tickets >= K50);
  const tryAdd = fn => { try { const s = fn(); if (s) out.push(s); } catch (e) { } };
  tryAdd(() => { const v = L("dimensions.categoryId.values")[0]; return v ? { t: "Category " + v.value + " holds " + pct(v.count / TOTAL, 0) + " of the tickets.", s: "Categories alone barely separate problem types.", view: "categories" } : null; });
  tryAdd(() => { if (y.length < 2) return null; let best = null; FIELDS.forEach(([k, l]) => { const a = y[0][k], b = y[y.length - 1][k]; if (a == null || b == null) return; const d = b - a; if (!best || Math.abs(d) > Math.abs(best.d)) best = { d, l, a, b, ya: y[0].year, yb: y[y.length - 1].year }; }); return best && Math.abs(best.d) >= 0.15 ? { t: best.l + " is filled in " + pct(best.a, 0) + " of tickets in " + best.ya + " but " + pct(best.b, 0) + " in " + best.yb + ".", s: "The biggest change of any field between the first and last full year.", view: "time", w: best.d < 0 } : null; });
  tryAdd(() => { const c = get(R, "origin.baugruppe.coverage.share"); return c != null && c < 0.5 ? { t: "Only " + pct(c, 0) + " of the tickets name a Baugruppe.", s: "And its ids are opaque without a lookup table.", view: "baugruppe", w: true } : null; });
  tryAdd(() => { const r = get(R, "timeline.recurrence"); return r ? { t: pct(r.repeat_within_90_share, 0) + " of tickets with a serial repeat an earlier ticket of that vehicle within 90 days.", s: "A vehicle's history is a strong signal for the next ticket.", view: "time" } : null; });
  tryAdd(() => { const r = get(R, "readiness.usable"); return r ? { t: pct(r.share, 0) + " of the tickets are usable (solution present, not boilerplate).", s: pct(get(R, "readiness.complete_triple.share"), 0) + " have title, description and solution.", view: "quality" } : null; });
  tryAdd(() => { const u = get(R, "concentration.userCreatedId"); return u ? { t: "The top 5 of " + u.distinct + " ticket creators wrote " + pct(u.top5_share, 0) + " of the tickets.", s: "Writing style is dominated by a few people.", view: "who" } : null; });
  tryAdd(() => { const c = get(R, "lifecycle.hours.coverage.share"); return c != null && c < 0.2 ? { t: "Operating hours exist on only " + pct(c, 0) + " of the tickets.", s: "Vehicle age is mostly unknown, as is the warranty state.", view: "lifecycle", w: true } : null; });
  return out;
}
function viewOverview() {
  const out = [], pr = profile(G.steps), ex = pr.grade === "exact", t = $("div", "tiles");
  t.append(tile("Tickets", approx(pr.n.est, ex), G.steps.length ? pct(pr.n.est / TOTAL) + " of all" + (ex ? "" : " · estimate") : "in the export", { scoped: true }));
  [["solutions", "have a solution"], ["description", "have a description"], ["serial", "have a vehicle serial"], ["model_id", "have a vehicle model id"], ["baugruppe", "name a Baugruppe"]].forEach(([k, l]) => { const v = pr.fields[k]; if (v != null) t.append(tile("Tickets that " + l, pct(v, 0), (v < 0.5 ? "⚠ under half of tickets" : "share of tickets") + (G.steps.length && !pr.known[k] ? " · overall rate" : ""), { scoped: true, warn: v < 0.5 })); });
  const us = get(R, "readiness.usable"); if (us) t.append(tile("Usable", pct(us.share, 0), "solution present, not boilerplate"));
  const rc = get(R, "timeline.recurrence"); if (rc) t.append(tile("Repeat within 90 days", pct(rc.repeat_within_90_share, 0), "of tickets with a serial"));
  const sv = get(R, "origin.vehicles.serials"); if (sv) t.append(tile("Distinct vehicles", fmt(sv.distinct), pct(sv.repeat_rate, 0) + " have more than one ticket"));
  const tl = $("div"), cta = $("button", "cta"); cta.type = "button"; cta.append($("b", "", "Decide what goes into the RAG corpus"), $("span", "", "Build a filter tree, branch it and compare how many tickets and how much data quality each path keeps.")); cta.onclick = () => go("lab"); tl.append(cta, t);
  const sg = signals(), sgc = $("section", "card wide"); sgc.append($("h2", "", "What stands out"), $("p", "desc", "Facts computed from this report. Click one to open the view behind it."));
  sgc.id = "c-signals"; const sb = $("div", "sig"); sg.forEach(s => { const b = $("button", s.w ? "w" : "", s.t); b.type = "button"; b.append($("small", "", s.s)); b.onclick = () => go(s.view); sb.append(b); }); sgc.append(sb);
  const mp = $("section", "card wide"); mp.id = "c-map"; mp.append($("h2", "", "Where to look"), $("p", "desc", "Every view, and the global filters it responds to."));
  const mg = $("div", "map"); VIEWS.filter(v => v.id !== "overview").forEach(v => { const b = $("button"); b.type = "button"; b.append($("b", "", v.title), $("span", "", v.blurb), $("small", "", v.responds.length ? "Responds to: " + v.responds.join(", ") : "No global filters")); b.onclick = () => go(v.id); mg.append(b); }); mp.append(mg);
  return { before: tl, cards: [cardMonths(), card({ id: "ovcat", title: "Category mix", by: "cat", g: { year: 1, cat: 1 }, rows: catCounts(), body: st => { const c = catCounts(); return c.length ? barsH(c.map(r => ({ label: "Category " + r.value, value: r.count, color: catColor(r.value), dim: !sel("cat", r.value), fk: "cat", fv: r.value })), st) : null; }, desc: "Share of volume per category. Click a bar to filter everything by it." }), cardYears(), sgc, mp] };
}

/* ---------- corpus builder: a tree of steps, compared side by side ---------- */
const TREE = { nodes: [], next: 1, cmp: null, slot: new Map(), last: 0, focus: 0, hist: [], qf: new Set(["solutions", "description", "serial", "model_id"]) };
const qscore = pr => { const fs = [...TREE.qf]; return fs.length ? sum(fs, f => pr.fields[f]) / fs.length : 0; };
const LETTERS = "ABCDEF";
const nodeOf = id => TREE.nodes.find(n => n.id === id);
const kids = id => TREE.nodes.filter(n => n.parent === id);
function pathOf(id) { const out = [], seen = new Set(); let n = nodeOf(id); while (n && !seen.has(n.id)) { seen.add(n.id); out.unshift(n.step); n = nodeOf(n.parent); } return out; }
const pathText = id => pathOf(id).map(stepLabel).join(" → ") || "all tickets";
const exists = id => id === 0 || !!nodeOf(id);
function comparedIds() {
  const ids = TREE.cmp ? [...TREE.cmp].filter(exists) : TREE.nodes.filter(n => !kids(n.id).length).map(n => n.id);
  return ids.filter(i => i !== 0).sort((a, b) => a - b).slice(0, 6);
}
function pruneSlots() { const keep = new Set(comparedIds()); [...TREE.slot.keys()].forEach(k => { if (!keep.has(k)) TREE.slot.delete(k); }); }
function slotOf(id) {
  if (!TREE.slot.has(id)) { const used = new Set([...TREE.slot.values()]); let s = 0; while (used.has(s)) s++; TREE.slot.set(id, s); }
  return TREE.slot.get(id);
}
const colorOfNode = id => "var(--s" + (slotOf(id) + 1) + ")", letterOf = id => LETTERS[slotOf(id)];
function addStep(parent, step, quiet) { if (!exists(parent)) parent = 0; const id = TREE.next++; TREE.nodes.push({ id, parent, step }); if (TREE.cmp) TREE.cmp.add(id); TREE.last = id; if (!quiet) treeChanged(); return id; }
function removeNode(id) {
  pushHist(); const drop = new Set([id]); let grew = true;
  while (grew) { grew = false; TREE.nodes.forEach(n => { if (!drop.has(n.id) && drop.has(n.parent)) { drop.add(n.id); grew = true; } }); }
  TREE.nodes = TREE.nodes.filter(n => !drop.has(n.id)); if (TREE.cmp) drop.forEach(i => TREE.cmp.delete(i));
  if (!exists(TREE.last)) TREE.last = 0;
  if (PAL.el && !exists(PAL.base)) PAL.base = 0;
  treeChanged();
}
function toggleCmp(id) {
  if (!TREE.cmp) TREE.cmp = new Set(comparedIds());
  if (TREE.cmp.has(id)) TREE.cmp.delete(id); else if (comparedIds().length < 6) TREE.cmp.add(id);
  treeChanged();
}
function treeChanged() { writeHash(); renderView(); if (PAL.el) renderPal(); }
function resetTree() { TREE.nodes = []; TREE.next = 1; TREE.cmp = null; TREE.last = 0; TREE.slot.clear(); }
function clearTree() { pushHist(); resetTree(); if (PAL.el && PAL.mode === "tree") PAL.base = 0; treeChanged(); if (PAL.el) renderPal(); }
function seed(spec) { pushHist(); resetTree(); const ids = []; spec((parent, step) => { const id = addStep(parent, step, true); ids.push(id); return id; }); TREE.cmp = null; return ids; }
const gateStep = f => ({ t: "g", f, neg: false });
const PRESETS = [
  ["Compare the biggest category with the rest", "Two branches, each with solution and description required.", () => { const top = M.cats[0] && M.cats[0].k; if (!top) return; seed(add => { const a = add(0, { t: "d", dim: "cat", mode: "i", vals: [top] }), b = add(0, { t: "d", dim: "cat", mode: "o", vals: [top] }); [a, b].forEach(p => { const s = add(p, gateStep("solutions")); add(s, gateStep("description")); }); }); treeChanged(); }],
  ["Layer the quality gates", "One path: solution, description, serial, model id. Shows where tickets drop out.", () => { const ids = seed(add => { let p = 0; ["solutions", "description", "serial", "model_id"].forEach(f => { p = add(p, gateStep(f)); }); }); TREE.cmp = new Set(ids); treeChanged(); }],
  ["Split by year", "One branch per year, each requiring a solution.", () => { pushHist(); resetTree(); splitInto(0, "year", true); TREE.nodes.slice().forEach(n => { addStep(n.id, gateStep("solutions"), true); }); TREE.cmp = null; treeChanged(); }],
];
/* one branch per value of a dimension (the six largest) or per year */
function splitInto(parent, what, quiet) {
  const steps = what === "year" ? M.yearKeys.slice().sort((a, b) => (M.yearN.get(b) || 0) - (M.yearN.get(a) || 0)).slice(0, 6).sort().map(y => ({ t: "y", vals: [y] })) : DIMS[what].values.slice().sort((a, b) => b.n - a.n).slice(0, 6).map(v => ({ t: "d", dim: what, mode: "i", vals: [v.v] }));
  const ids = steps.map(st => addStep(parent, st, true)); TREE.cmp = null; if (!quiet) { treeChanged(); if (PAL.el) renderPal(); }
  return ids;
}
function seedFromGlobal() {
  if (!G.steps.length) return false;
  seed(add => { let p = 0; G.steps.forEach(st => { p = add(p, clone(st)); }); }); treeChanged(); return true;
}
function treeToHash() { return TREE.nodes.map(n => n.id + "." + n.parent + "." + stepStr(n.step)).join("!"); }
function treeFromHash(txt, cmp, qf) {
  resetTree(); const ok = new Set([0]);
  (txt || "").split("!").filter(Boolean).forEach(part => {
    const m = /^(\d+)\.(\d+)\.(.+)$/.exec(part); if (!m) return;
    const i = Number(m[1]), par = Number(m[2]), step = strStep(m[3]); if (!step || !ok.has(par) || ok.has(i)) return;
    TREE.nodes.push({ id: i, parent: par, step }); ok.add(i); TREE.next = Math.max(TREE.next, i + 1); TREE.last = i;
  });
  if (cmp) TREE.cmp = new Set(cmp.split(",").map(Number).filter(i => TREE.nodes.some(n => n.id === i)));
  const fs = (qf || "").split(",").filter(f => GATES.some(g => g[0] === f && f !== "boiler")); if (fs.length) TREE.qf = new Set(fs);
}
const approx = (n, exactly) => (exactly ? "" : "≈ ") + fmt(Math.round(n));
const rangeTxt = n => n.hi - n.lo < 0.5 ? "exact" : "between " + fmt(Math.round(n.lo)) + " and " + fmt(Math.round(n.hi));

function labIntro() {
  return card({
    id: "labintro", wide: true, title: "Build and compare corpus filters", g: {}, scopeNote: "This view has its own steps. Use the buttons to copy the global filters in, or send a path back out with → Filters.",
    desc: "Start from every ticket and add steps that narrow it down: a category, year, status or model, a field that must be filled, a repeat ticket, or a word in the title or solution. Press **/** or **+ Step** to search every step and see its effect before adding it. Add several steps under the same step to **branch**, then tick the branches you want to compare.",
    how: "The report holds totals, not individual tickets, so counts after several steps are **estimates**. A count is **exact** where the report holds that split. Otherwise it lies within the range shown (a guarantee) and the point value assumes the steps are independent.",
    body: () => {
      const w = $("div"), row = $("div", "presets");
      PRESETS.forEach(([t, d, fn]) => { const b = $("button", "preset"); b.type = "button"; b.append($("b", "", t), $("span", "", d)); b.onclick = fn; row.append(b); });
      const cur = $("button", "preset"); cur.type = "button"; cur.append($("b", "", "Use the current global filters"), $("span", "", "Turn every active filter into the first steps of the tree.")); cur.onclick = () => { if (!seedFromGlobal()) { cur.querySelector("span").textContent = "No filter is active. Add one in the bar above first."; } }; row.append(cur);
      w.append(row); return w;
    }
  });
}
/* ---------- tree: history, editing and the connected node design ---------- */
const COLLAPSED = new Set();
const stepMode = s => (s.t === "g" || s.t === "x" ? (s.neg ? "o" : "i") : dmode(s));
function setStepMode(s, m) { if (s.t === "g" || s.t === "x") s.neg = m === "o"; else s.mode = m; }
function stepSubject(s) {
  if (s.t === "y") return "Year " + s.vals.join(", ");
  if (s.t === "d") { const d = DIMS[s.dim]; return (d ? d.label : s.dim) + ": " + s.vals.map(v => (v === "__rest" ? (d ? d.restLabel : "rest") : v)).join(", "); }
  if (s.t === "g") return "Ticket " + boolPhrase(s.f);
  return (s.src === "title" ? "Title" : "Solution") + " contains “" + s.term + "”";
}
function pathIds(id) { const out = [], seen = new Set(); let n = nodeOf(id); while (n && !seen.has(n.id)) { seen.add(n.id); out.unshift(n.id); n = nodeOf(n.parent); } return out; }
const below = id => { let c = 0; const walk = x => kids(x).forEach(k => { c++; walk(k.id); }); walk(id); return c; };
function pushHist() { TREE.hist.push(JSON.stringify({ nodes: TREE.nodes, next: TREE.next, cmp: TREE.cmp ? [...TREE.cmp] : null, last: TREE.last })); if (TREE.hist.length > 50) TREE.hist.shift(); }
function undoTree() {
  const h = TREE.hist.pop(); if (!h) return; const o = JSON.parse(h);
  TREE.nodes = o.nodes; TREE.next = o.next; TREE.cmp = o.cmp ? new Set(o.cmp) : null; TREE.last = o.last; TREE.slot.clear();
  if (PAL.el && !exists(PAL.base)) PAL.base = 0; treeChanged();
}
function setNodeState(id, st) {
  const n = nodeOf(id); if (!n) return; if (st === "x") return removeKeep(id);
  pushHist(); setStepMode(n.step, st === "ignore" ? "o" : "i"); treeChanged();
}
/* remove one step but keep everything below it, which moves up a level */
function removeKeepQuiet(id) {
  const n = nodeOf(id); if (!n) return;
  TREE.nodes.forEach(c => { if (c.parent === id) c.parent = n.parent; });
  TREE.nodes = TREE.nodes.filter(x => x.id !== id); if (TREE.cmp) TREE.cmp.delete(id); COLLAPSED.delete(id);
  if (!exists(TREE.last)) TREE.last = n.parent; if (PAL.el && PAL.base === id) PAL.base = n.parent;
}
function removeKeep(id) { if (!nodeOf(id)) return; pushHist(); removeKeepQuiet(id); treeChanged(); }
function insertAfter(id, step) {
  const nid = TREE.next++; TREE.nodes.forEach(c => { if (c.parent === id) c.parent = nid; });
  TREE.nodes.push({ id: nid, parent: id, step }); if (TREE.cmp) TREE.cmp.add(nid); return nid;
}
/* in the builder a row edits the steps already on the path, so a set value can always be changed or unset */
function treeRowChoose(r, choice) {
  const t = r.t, ids = pathIds(PAL.base), old = ids.map(id => nodeOf(id).step);
  const group = s => (t.k === "g" ? s.t === "g" && s.f === t.id : t.k === "x" ? s.t === "x" && s.src === t.src && s.term === t.term : t.key === "year" ? s.t === "y" : s.t === "d" && s.dim === t.key);
  const gIds = ids.filter((_, i) => group(old[i])); if (!gIds.length) return false;
  if (choice === "ignore" && rowState(old, t) === "imp") return true;
  const next = choiceSteps(old, t, choice).filter(group), keep = Math.min(gIds.length, next.length);
  pushHist();
  for (let i = 0; i < keep; i++) nodeOf(gIds[i]).step = next[i];
  for (let i = keep; i < gIds.length; i++) removeKeepQuiet(gIds[i]);
  let at = gIds[keep - 1]; for (let i = keep; i < next.length; i++) at = insertAfter(at, next[i]);
  PAL.sugg.clear(); PAL.last = null; treeChanged(); return true;
}
function dupNode(id, deep) {
  const n = nodeOf(id); if (!n) return; pushHist();
  const copy = (src, parent) => { const nid = TREE.next++; TREE.nodes.push({ id: nid, parent, step: clone(src.step) }); if (deep) kids(src.id).filter(k => k.id < nid).forEach(k => copy(k, nid)); return nid; };
  const nid = copy(n, n.parent); if (TREE.cmp) TREE.cmp.add(nid); TREE.last = nid; treeChanged();
}
const MENU = { el: null };
function closeMenu() { if (MENU.el) { MENU.el.remove(); MENU.el = null; } }
function openMenu(id, anchor) {
  closeMenu(); const n = nodeOf(id), isRoot = id === 0, hasKids = kids(id).length > 0, m = $("div", "dlg nmenu");
  m.setAttribute("role", "menu"); const r = anchor.getBoundingClientRect(); m.style.left = Math.max(8, Math.min(r.right - 260, innerWidth - 276)) + "px"; m.style.top = (r.bottom + 6) + "px";
  const item = (label, hint, fn, cls) => { const b = $("button", "mi" + (cls ? " " + cls : "")); b.type = "button"; b.setAttribute("role", "menuitem"); b.append($("span", "", label)); if (hint) b.append($("small", "", hint)); b.onclick = () => { closeMenu(); fn(); }; m.append(b); };
  const sep = () => m.append($("div", "msep"));
  item("Add a step below", "search every filter", () => openPalette("tree", id));
  if (!isRoot) item("Add a branch alongside", "same parent, new path", () => { openPalette("tree", n.parent); PAL.add = "branch"; renderPal(); });
  item("Split into branches…", "one per value", () => { openPalette("tree", id); PAL.nav = "split"; renderPal(); });
  if (!isRoot) { sep(); item(stepMode(n.step) === "o" ? "Switch to include" : "Switch to ignore", "flip this step", () => setNodeState(id, stepMode(n.step) === "o" ? "include" : "ignore")); item("Duplicate step", "as a sibling", () => dupNode(id, false)); if (hasKids) item("Duplicate with its branch", below(id) + " steps below", () => dupNode(id, true)); }
  if (hasKids) { sep(); item(COLLAPSED.has(id) ? "Expand branch" : "Collapse branch", "", () => { COLLAPSED.has(id) ? COLLAPSED.delete(id) : COLLAPSED.add(id); renderView(); }); }
  if (!isRoot) { sep(); item("Use this path as global filters", "copies the steps to the filter bar", () => { G.steps = pathOf(id).map(clone); changed(); }); sep(); if (hasKids) item("Remove step, keep what is below", "", () => removeKeep(id), "warn"); item(hasKids ? "Remove step and branch" : "Remove step", "", () => removeNode(id), "warn"); }
  document.body.append(m); MENU.el = m;
}
function stepChips(step) {
  const w = $("span", "tstep"), m = stepMode(step);
  w.append($("span", "tmode " + (m === "o" ? "ign" : "inc"), m === "o" ? "⊘ Ignore" : "✓ Include"));
  if (step.t === "d" || step.t === "y") { const d = step.t === "d" ? DIMS[step.dim] : null; w.append($("span", "ttag", step.t === "y" ? "Year" : d ? d.label : step.dim)); step.vals.forEach(v => w.append($("span", "tval", v === "__rest" && d ? d.restLabel : v))); }
  else if (step.t === "g") w.append($("span", "ttext", boolPhrase(step.f)));
  else { w.append($("span", "ttag", step.src === "title" ? "Title" : "Solution"), $("span", "ttext", "contains"), $("span", "tval", "“" + step.term + "”")); }
  return w;
}
function nodeRow(node, depth, cmpSet) {
  const id = node.id, steps = pathOf(id), pr = profile(steps), par = id ? profile(steps.slice(0, -1)) : null, ex = pr.grade === "exact", isRoot = id === 0;
  const list = kids(id), folded = list.length > 0 && COLLAPSED.has(id), picked = cmpSet.has(id), wrap = $("div", "tnode");
  const row = $("div", "trow" + (picked ? " cmp" : "") + (isRoot ? " troot" : "")); if (picked) row.style.setProperty("--nc", colorOfNode(id));
  const c1 = $("div", "tc");
  if (list.length) { const b = $("button", "tcaret", folded ? "▸" : "▾"); b.type = "button"; b.setAttribute("aria-expanded", String(!folded)); b.setAttribute("aria-label", folded ? "Expand branch" : "Collapse branch"); b.title = folded ? "Expand branch" : "Collapse branch"; b.onclick = () => { if (folded) COLLAPSED.delete(id); else COLLAPSED.add(id); renderView(); }; c1.append(b); }
  const c0 = $("div", "tk");
  if (!isRoot) { const cb = $("input"); cb.type = "checkbox"; cb.checked = picked; cb.disabled = !picked && cmpSet.size >= 6; cb.title = "Compare this path"; cb.setAttribute("aria-label", "Compare this path: " + pathText(id)); cb.onchange = () => toggleCmp(id); c0.append(cb); }
  const lab = $("div", "tlab");
  if (picked) { const sw = $("span", "ltr", letterOf(id)); sw.style.background = colorOfNode(id); lab.append(sw); }
  lab.append(isRoot ? $("span", "troottxt", "All tickets") : stepChips(node.step));
  if (par) { const vd = verdictOf(par, pr), vb = $("span", "tverd v-" + vd.k, vd.icon + " " + vd.label); vb.title = vd.text; lab.append(vb); }
  if (folded) lab.append($("span", "thidden", "+" + below(id) + " below"));
  const bar = $("div", "tbar"), tr = $("div", "ttrack"), fl = $("i"); fl.style.width = Math.max(0.4, 100 * pr.n.est / TOTAL) + "%"; if (picked) fl.style.background = colorOfNode(id); tr.append(fl);
  if (!ex) { const w = $("b", "whisk"); w.style.left = (100 * pr.n.lo / TOTAL) + "%"; w.style.width = Math.max(0.5, 100 * (pr.n.hi - pr.n.lo) / TOTAL) + "%"; tr.append(w); }
  bar.append(tr); hover(bar, () => [[approx(pr.n.est, ex) + " tickets", pathText(id)], [rangeTxt(pr.n), "possible range"], [pct(qscore(pr), 0), "quality score"]]);
  const n1 = $("div", "tn n1"); n1.append($("b", "", approx(pr.n.est, ex)), $("span", "", pct(pr.n.est / TOTAL, 0) + " of all"));
  const n2 = $("div", "tn n2"); if (par) { const d = par.n.est ? 1 - pr.n.est / par.n.est : 0; n2.append($("b", d > 0.005 ? "lose" : "same", d > 0.005 ? "−" + pct(d, 0) : "±0"), $("span", "", "vs. step above")); } else n2.append($("b", "same", "start"), $("span", "", "everything"));
  const n3 = $("div", "tn n3"); n3.append($("b", "", pct(qscore(pr), 0))); n3.append($("span", "", par ? (deltaPts(qscore(pr), qscore(par)) || "same as above") : "quality"));
  const act = $("div", "tact");
  if (!isRoot) {
    const t = $("div", "ttri"); t.setAttribute("role", "group");
    [["i", "✓", "Include"], ["o", "⊘", "Ignore"], ["x", "○", "Not set: remove this step, keep what is below"]].forEach(([m, ic, title]) => { const b = $("button", m === "i" ? "inc" : m === "o" ? "ign" : "unset", ic); b.type = "button"; b.title = title; b.setAttribute("aria-label", title); b.setAttribute("aria-pressed", String(m !== "x" && stepMode(node.step) === m)); b.onclick = () => setNodeState(id, m === "i" ? "include" : m === "o" ? "ignore" : "x"); t.append(b); });
    act.append(t);
  }
  const add = $("button", "tbtn", "+ Step"); add.type = "button"; add.title = "Search every filter and add it below (press / for the same)"; add.onclick = () => openPalette("tree", id);
  const more = $("button", "tbtn more", "⋯"); more.type = "button"; more.title = "More: branch, duplicate, collapse, remove…"; more.setAttribute("aria-label", "More actions"); more.onclick = e => { e.stopPropagation(); openMenu(id, more); };
  act.append(add, more);
  const tq = $("div", "tq");
  qFields().forEach(([f, short]) => {
    const v = pr.fields[f], c = $("span", "tqc"); c.append($("span", "tqn", short), $("b", "", pct(v, 0)));
    if (par) { const d = v - par.fields[f]; if (Math.abs(d) >= 0.005) c.append($("span", "tqd " + (d > 0 ? "up" : "dn"), sgn(d))); }
    if (!isRoot && !pr.known[f]) { c.append($("span", "tqs", "*")); c.title = "Overall rate: the report has no split of this field for these filters"; }
    else c.title = short + " is filled in " + pct(v, 0) + " of these tickets" + (par ? " (" + pct(par.fields[f], 0) + " one step up)" : " (all tickets)");
    tq.append(c);
  });
  if (!isRoot && (node.step.t === "d" || node.step.t === "y") && node.step.vals.length > 1) {
    const lk = $("button", "tqlink", "Each " + (node.step.t === "y" ? "year" : (DIMS[node.step.dim] || { label: "value" }).label.toLowerCase()) + " on its own ▸"); lk.type = "button"; lk.title = "Open the decision guide for this step: size and quality of every value";
    lk.onclick = () => { TREE.focus = id; renderView(); const g = document.getElementById("c-labguide"); if (g) g.scrollIntoView(); }; tq.append(lk);
  }
  row.append(c1, c0, lab, bar, n1, n2, n3, act, tq); wrap.append(row);
  if (!isRoot && focusId() === id) row.classList.add("focus");
  row.addEventListener("click", e => { if (isRoot || e.target.closest("button,input,label,select,a")) return; TREE.focus = id; renderView(); });
  if (list.length && !folded) { const k = $("div", "tkids"); list.forEach(c => k.append(nodeRow(c, depth + 1, cmpSet))); wrap.append(k); }
  return wrap;
}
function labTree() {
  const cmpSet = new Set(comparedIds());
  return card({
    id: "labtree", wide: true, title: "Filter tree", g: {}, scopeNote: "Tick the paths to compare (up to six). The ⋯ menu has branch, duplicate, flip, collapse and remove.",
    desc: "Each node is the set of tickets left after the steps above it. The bar is its share of all tickets; the thin line marks the possible range when the count is estimated. Use ✓ ⊘ ○ on a node to include, ignore or unset its step.",
    body: () => {
      const w = $("div", "ltree"), q = $("div", "legend qf"), qd = $("span", "qdef"); qd.append($("span", "qi", "Q"), document.createTextNode("Quality score = average fill of:")); qd.title = "Every node shows this score and the share of its tickets in which each of these fields is filled. Tick the fields that matter for your corpus."; q.append(qd);
      GATES.filter(g => g[0] !== "boiler").forEach(([f, short]) => { const b = $("button"); b.type = "button"; b.setAttribute("aria-pressed", String(TREE.qf.has(f))); b.textContent = short; b.onclick = () => { if (TREE.qf.has(f)) { if (TREE.qf.size > 1) TREE.qf.delete(f); } else TREE.qf.add(f); treeChanged(); }; q.append(b); });
      const tb = $("div", "ttools"), tool = (label, title, fn, off) => { const b = $("button", "tbtn", label); b.type = "button"; b.title = title; b.disabled = !!off; b.onclick = fn; tb.append(b); };
      tool("↶ Undo", "Undo the last change to the tree", undoTree, !TREE.hist.length);
      tool("Expand all", "Show every branch", () => { COLLAPSED.clear(); renderView(); }, !TREE.nodes.length);
      tool("Collapse all", "Fold every branch", () => { TREE.nodes.forEach(n => { if (kids(n.id).length) COLLAPSED.add(n.id); }); if (kids(0).length) COLLAPSED.add(0); renderView(); }, !TREE.nodes.length);
      tool("Compare all ends", "Compare every path that has no steps below it", () => { TREE.cmp = null; treeChanged(); }, !TREE.nodes.length);
      tool("Compare none", "Untick every path", () => { TREE.cmp = new Set(); treeChanged(); }, !TREE.nodes.length);
      tool("Clear tree", "Remove every step", clearTree, !TREE.nodes.length);
      const hd = $("div", "thead"); ["", "", "Step", "Share of all tickets", "Tickets left", "Change", "Quality", ""].forEach(t => hd.append($("span", "", t)));
      const body = $("div", "tbody"); body.append(nodeRow({ id: 0, step: null }, 0, cmpSet));
      q.append($("p", "qhelp", "Every node shows this score and the fill of each field below. Switch fields on or off to match what a technician needs.")); w.append(q, tb, hd, body); if (!TREE.nodes.length) w.append($("div", "note", "Press + Step on the first node (or / anywhere), or start from one of the examples above."));
      return w;
    }
  });
}
/* ---------- decision support: what each filter does to tickets and quality ---------- */
/* a verdict compares the quality gained with the tickets given up; always icon + words, never colour alone */
function verdictOf(par, pr) {
  const dq = (qscore(pr) - qscore(par)) * 100, lost = par.n.est ? (1 - pr.n.est / par.n.est) * 100 : 0, a = Math.abs(dq).toFixed(0), l = lost.toFixed(0);
  if (lost < 1 && Math.abs(dq) < 0.5) return { k: "flat", icon: "＝", label: "No effect", text: "Changes neither the ticket count nor the quality." };
  if (dq < -0.5) return { k: "hurt", icon: "▼", label: "Lowers quality", text: "Quality falls " + a + " points while " + l + "% of the tickets go." };
  if (Math.abs(dq) < 0.5) return { k: "flat", icon: "◆", label: "Only shrinks", text: "Removes " + l + "% of the tickets without changing the quality score." };
  const e = dq / Math.max(lost, 0.5);
  if (e >= 0.8) return { k: "gain", icon: "▲", label: "Strong gain", text: "Raises quality by " + a + " points and gives up " + l + "% of the tickets: a strong trade." };
  if (e >= 0.25) return { k: "fair", icon: "▲", label: "Good trade", text: "Raises quality by " + a + " points for " + l + "% of the tickets: a reasonable trade." };
  return { k: "costly", icon: "▲", label: "Costly gain", text: "Raises quality by only " + a + " points but gives up " + l + "% of the tickets: probably not worth it." };
}
function focusId() {
  if (TREE.focus && exists(TREE.focus) && TREE.focus !== 0) return TREE.focus;
  const c = comparedIds(); if (c.length) return c[0];
  if (TREE.last && exists(TREE.last) && TREE.last !== 0) return TREE.last;
  return TREE.nodes.length ? TREE.nodes[0].id : 0;
}
const qFields = () => GATES.filter(g => TREE.qf.has(g[0]));
/* a dumbbell: where a value stood before and where it is after */
function dumbbell(a, b) {
  const t = $("span", "dbell"), lo = Math.min(a, b), hi = Math.max(a, b), line = $("i", "dl"), d0 = $("i", "d0"), d1 = $("i", "d1");
  line.style.left = (100 * lo) + "%"; line.style.width = (100 * (hi - lo)) + "%"; d0.style.left = (100 * a) + "%"; d1.style.left = (100 * b) + "%"; t.append(line, d0, d1); return t;
}
const sgn = d => (Math.abs(d) < 0.005 ? "±0" : (d > 0 ? "▲ " : "▼ ") + Math.abs(d * 100).toFixed(0) + " pts");
/* one single-valued copy of a step, to see what each value alone would do */
const oneValue = (st, v) => ({ ...st, vals: [v] });
function compareEachValue(id) {
  const n = nodeOf(id); if (!n || !n.step.vals || n.step.vals.length < 2) return;
  pushHist(); const ids = n.step.vals.map(v => addStep(n.parent, oneValue(n.step, v), true));
  TREE.cmp = new Set(ids); TREE.focus = ids[0]; treeChanged();
}
function labGuide() {
  const id = focusId(); if (!id) return null;
  const node = nodeOf(id), steps = pathOf(id), parSteps = steps.slice(0, -1), pr = profile(steps), par = profile(parSteps), vd = verdictOf(par, pr), fs = qFields();
  return card({
    id: "labguide", wide: true, title: "Decision guide for the selected step", g: {}, scopeNote: "Click any node in the tree to guide it. The estimates follow the same rules as the tree.",
    desc: "What this one filter does to the corpus, field by field, and what to try next. A verdict weighs the **quality gained** against the **tickets given up**.",
    how: "Quality is the average fill of the fields you chose above the tree. A star marks a field for which the report has no split for this filter, so the overall rate is shown: such a filter changes how many tickets are left, but the report cannot say how it changes quality.",
    body: () => {
      const w = $("div", "guide"), hd = $("div", "ghead");
      hd.append(stepChips(node.step), $("span", "tverd big v-" + vd.k, vd.icon + " " + vd.label)); w.append(hd);
      const grade = pr.grade === "exact" ? "" : " The count is an estimate between " + fmt(Math.round(pr.n.lo)) + " and " + fmt(Math.round(pr.n.hi)) + ".";
      w.append($("p", "gtext", vd.text + " Tickets: " + approx(par.n.est, par.grade === "exact") + " → " + approx(pr.n.est, pr.grade === "exact") + "." + grade));
      /* 1. before and after, field by field */
      w.append($("div", "sub3", "Before and after, field by field"));
      const ba = $("div", "gba"); ["Field", "Above", "After", "Change", "0 – 100 %"].forEach(h => ba.append($("span", "gh", h)));
      const row = (label, a, b, strong, star) => { ba.append($("span", "gl" + (strong ? " strong" : ""), label + (star ? " *" : "")), $("span", "gn", pct(a, 0)), $("span", "gn" + (strong ? " strong" : ""), pct(b, 0)), $("span", "gd " + (b > a + 0.004 ? "up" : b < a - 0.004 ? "dn" : ""), sgn(b - a)), dumbbell(a, b)); };
      row("Quality score", qscore(par), qscore(pr), true, false);
      fs.forEach(([f, short]) => row(short, par.fields[f], pr.fields[f], false, !pr.known[f] && !(node.step.t === "g" && node.step.f === f)));
      row("Tickets left", par.n.est / TOTAL, pr.n.est / TOTAL, false, false);
      w.append(ba);
      if (fs.some(([f]) => !pr.known[f])) w.append($("p", "note", "* Overall rate: the report has no split of this field for these filters."));
      /* 2. what each value contributes */
      const st = node.step;
      if ((st.t === "d" || st.t === "y") && st.vals.length) {
        const dimLabel = st.t === "y" ? "Year" : (DIMS[st.dim] || { label: st.dim }).label, known = st.t === "y" || st.dim === "cat";
        w.append($("div", "sub3", "Each " + dimLabel.toLowerCase() + " on its own"));
        const rows = st.vals.map(v => ({ v, pr: profile(parSteps.concat(oneValue(st, v))) })), qs = rows.map(r => qscore(r.pr)), best = Math.max(...qs), worst = Math.min(...qs);
        const tb = $("div", "gval"); const head = ["Value", "Tickets", "Share of step above", "Quality"].concat(fs.map(f => f[1])); tb.style.gridTemplateColumns = "minmax(90px,1.2fr) 90px 120px 80px " + fs.map(() => "78px").join(" ");
        head.forEach(h => tb.append($("span", "gh", h)));
        rows.forEach(r => {
          const q = qscore(r.pr), tag = rows.length > 1 && known && best - worst > 0.01 ? (q === best ? " ▲ best" : q === worst ? " ▼ lowest" : "") : "";
          tb.append($("span", "gl strong", (r.v === "__rest" && DIMS[st.dim] ? DIMS[st.dim].restLabel : r.v) + tag), $("span", "gn", approx(r.pr.n.est, r.pr.grade === "exact")), $("span", "gn", pct(par.n.est ? r.pr.n.est / par.n.est : 0, 0)), $("span", "gn strong", pct(q, 0)));
          fs.forEach(([f]) => tb.append($("span", "gn" + (r.pr.known[f] ? "" : " star"), pct(r.pr.fields[f], 0) + (r.pr.known[f] ? "" : " *"))));
        });
        w.append(tb);
        w.append($("p", "note", known ? "Quality differs between " + dimLabel.toLowerCase() + " values because the report splits " + (st.t === "y" ? "every field" : "solution and description") + " by " + dimLabel.toLowerCase() + ". Fields marked * are overall rates." : "The report has no quality split by " + dimLabel.toLowerCase() + ": values differ in size, but their quality can only be estimated at the overall rate. Choose by ticket volume and by what you know about them, or extend the report with a field-by-" + dimLabel.toLowerCase() + " table."));
        if (st.vals.length > 1) { const b = $("button", "tbtn", "Compare each " + dimLabel.toLowerCase() + " as its own branch"); b.type = "button"; b.title = "Adds one branch per value next to this step and compares them"; b.onclick = () => compareEachValue(id); w.append(b); }
      } else w.append($("p", "note", "This step is a single yes/no condition, so there is no per-value breakdown."));
      /* 3. what to try next */
      const sg = suggest(steps).slice(0, 4);
      w.append($("div", "sub3", "Best next steps from here"));
      if (!sg.length) w.append($("p", "note", "No single step raises quality further without removing most tickets."));
      sg.forEach(c => {
        const r = $("div", "gnext"), b = $("button", "tbtn", "+ Add below"); b.type = "button";
        b.onclick = () => { pushHist(); const nid = addStep(id, clone(c.step), true); TREE.focus = nid; treeChanged(); };
        r.append($("span", "gl strong", stepLabel(c.step)), $("span", "gn", "keeps " + pct(c.keep, 0)), $("span", "gn", "quality " + pct(c.from, 0) + " → " + pct(c.to, 0)), b); w.append(r);
      });
      return w;
    }
  });
}
/* the whole path as a ladder: tickets and every quality field after each step */
function labLadder() {
  const id = focusId(); if (!id) return null;
  const ids = [0].concat(pathIds(id)), fs = qFields(), profs = ids.map(i => profile(pathOf(i)));
  const rows = [{ label: "Tickets left", key: "n" }, { label: "Quality score", key: "q" }].concat(fs.map(([f, short]) => ({ label: short, key: f })));
  const val = (r, c) => { const p = profs[ids.indexOf(c.key)]; return r.key === "n" ? p.n.est / TOTAL : r.key === "q" ? qscore(p) : p.fields[r.key]; };
  return card({
    id: "labladder", wide: true, title: "How quality changes along this path", g: {}, scopeNote: "Follows the node selected in the tree.",
    desc: "Each column is one more step on the path to the selected node. Read **across a row** to see where a field improves or drops, and **down a column** to see what the corpus looks like after that step.",
    how: "Darker cells are higher. Hover a cell for its change against the step before. The first row shows how much of the original export is still in the corpus.",
    body: () => heat({ max: 1, fmt: v => pct(v, 0), rows, cols: ids.map((i, k) => ({ label: k ? shortStep(nodeOf(i).step) : "Start", key: i, tip: [[k ? stepLabel(nodeOf(i).step) : "All tickets", ""]] })),
      val, tip: (r, c, v) => { const k = ids.indexOf(c.key), prev = k ? val(r, { key: ids[k - 1] }) : null; return [[pct(v, 0), r.label + " · " + (k ? shortStep(nodeOf(c.key).step) : "start")], prev == null ? ["", "the baseline"] : [sgn(v - prev), "against the step before"]]; } })
  });
}
function scatterDraw(pts, base, W) {
  const H = 380, ml = 64, mr = 28, mt = 24, mb = 62, pw = W - ml - mr, ph = H - mt - mb;
  const minY = Math.min(base.y, ...pts.map(p => p.y)), y0 = Math.max(0, Math.min(0.9, Math.floor((minY - 0.08) * 10) / 10));
  const X = v => ml + pw * v, Y = v => mt + ph * (1 - (v - y0) / (1 - y0));
  const svg = S("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Tickets kept against complete share, one dot per scenario" });
  for (let v = 0; v <= 1.001; v += 0.25) svg.append(S("line", { x1: X(v), x2: X(v), y1: mt, y2: mt + ph, class: "grid-l" }), S("text", { x: X(v), y: mt + ph + 20, class: "tick", "text-anchor": "middle" }, pct(v, 0)));
  const yt = []; for (let v = Math.ceil(y0 * 10) / 10; v <= 1.001; v += 0.1) yt.push(v);
  yt.forEach(v => svg.append(S("line", { x1: ml, x2: W - mr, y1: Y(v), y2: Y(v), class: "grid-l" }), S("text", { x: ml - 8, y: Y(v) + 4, class: "tick", "text-anchor": "end" }, pct(v, 0))));
  svg.append(S("text", { x: ml + pw / 2, y: H - 10, class: "xlab", "text-anchor": "middle" }, "Tickets kept (share of all) →"), S("text", { x: 14, y: mt + ph / 2, class: "xlab", "text-anchor": "middle", transform: `rotate(-90 14 ${mt + ph / 2})` }, "Quality score →"));
  svg.append(S("text", { x: X(1) - 6, y: Y(1) + 16, class: "xlab", "text-anchor": "end" }, "better ↗"));
  const b = S("g", { class: "mark" }); b.append(S("circle", { cx: X(base.x), cy: Y(base.y), r: 8, fill: "none", stroke: "var(--ink2)", "stroke-width": 2 }), S("text", { x: X(base.x) - 14, y: Y(base.y) + 4, class: "xlab", "text-anchor": "end" }, "All tickets"));
  hover(b, () => [[pct(base.y, 0), "quality score of all tickets"]]); svg.append(b);
  pts.forEach(p => {
    const g = S("g", { class: "mark" }), c = S("circle", { cx: X(p.x), cy: Y(p.y), r: 10, class: "sdot" }); c.style.fill = p.color;
    if (p.xhi - p.xlo > 0.004) g.append(S("line", { x1: X(p.xlo), x2: X(p.xhi), y1: Y(p.y), y2: Y(p.y), stroke: p.color, "stroke-width": 3, opacity: 0.55 }));
    g.append(S("circle", { cx: X(p.x), cy: Y(p.y), r: 22, class: "hit" }), c, S("text", { x: X(p.x) + 15, y: Y(p.y) + 5, class: "slab" }, p.letter));
    g.setAttribute("tabindex", "0"); hover(g, () => p.tip); svg.append(g);
  });
  return svg;
}
function labCompare(ids) {
  const out = [], base = profile([]);
  const prs = ids.map(id => ({ id, pr: profile(pathOf(id)) }));
  out.push(card({
    id: "labscatter", wide: true, title: "Corpus size against data quality", g: {}, scopeNote: "Computed from the tree above.",
    rows: prs.map(({ id, pr }) => ({ scenario: letterOf(id), steps: pathText(id), tickets: Math.round(pr.n.est), "share of all": pr.n.est / TOTAL, "quality score": qscore(pr) })),
    desc: "Each dot is a ticked row. Right means more tickets kept, up means better data in the fields you picked for the quality score. A good filter keeps **many tickets** and sits **high**.",
    how: "The hollow ring is the unfiltered corpus. A thin horizontal line through a dot marks the possible range of its size when it is estimated. Hover a dot for its steps. Letters match the tree and the table below.",
    body: () => { const lg = $("div", "legend"); prs.forEach(({ id }) => { const s = $("span"); const sw = $("i", "sw b"); sw.style.background = colorOfNode(id); s.append(sw, document.createTextNode(" " + letterOf(id) + "  " + pathOf(id).map(shortStep).join(" · "))); lg.append(s); });
      const w = $("div"); w.append(responsive(W => scatterDraw(prs.map(({ id, pr }) => ({ letter: letterOf(id), color: colorOfNode(id), x: pr.n.est / TOTAL, xlo: pr.n.lo / TOTAL, xhi: pr.n.hi / TOTAL, y: qscore(pr), tip: [[approx(pr.n.est, pr.grade === "exact") + " tickets · " + pct(pr.n.est / TOTAL, 0), letterOf(id) + ": " + pathText(id)], [pct(qscore(pr), 0), "quality score"], [rangeTxt(pr.n), "size"]] })), { x: 1, y: qscore(base) }, W)), lg); return w; }
  }));
  const fieldRows = [["score"]].concat(GATES.map(g => [g[0]]));
  const label = { score: "Quality score", solutions: "Solution", description: "Description", serial: "Vehicle serial", model_id: "Vehicle model id", baugruppe: "Baugruppe", fehlercode: "Error code", hours: "Operating hours", delivery: "Delivery date", boiler: "Not boilerplate" };
  out.push(card({
    id: "labquality", wide: true, title: "Data quality of what is left", g: {}, scopeNote: "Computed from the tree above.",
    rows: [{ field: "tickets", All: Math.round(TOTAL), ...Object.fromEntries(prs.map(({ id, pr }) => [letterOf(id), Math.round(pr.n.est)])) }].concat(fieldRows.map(([k]) => ({ field: label[k], All: k === "score" ? qscore(base) : base.fields[k], ...Object.fromEntries(prs.map(({ id, pr }) => [letterOf(id), k === "score" ? qscore(pr) : pr.fields[k]])) }))),
    desc: "For each scenario, the share of its tickets in which a field is filled. A required field is 100 percent by construction. Dark cells are well filled, pale cells are mostly empty.",
    how: "Read down a column to see what a corpus looks like, and along a row to see which scenario fills a field best. A **star** marks a field for which the report has no split by your categories, so the overall rate is shown and cannot tell the scenarios apart.",
    body: () => heat({ max: 1, fmt: v => pct(v, 0), mark: (r, c) => { if (r.key === "score" || c.key === "all") return ""; const pr = prs.find(x => x.id === c.key).pr; return pr.known[r.key] ? "" : "*"; }, rows: fieldRows.map(([k]) => ({ label: label[k], key: k })), cols: [{ label: "All", key: "all", tip: [["All tickets", pct(1, 0)]] }].concat(prs.map(({ id }) => ({ label: letterOf(id), key: id, tip: [[letterOf(id), pathText(id)]] }))), val: (r, c) => { const pr = c.key === "all" ? base : prs.find(x => x.id === c.key).pr; return r.key === "score" ? qscore(pr) : pr.fields[r.key]; } })
  }));
  const txt = () => prs.map(({ id, pr }) => letterOf(id) + ": " + pathText(id) + " | " + approx(pr.n.est, pr.grade === "exact") + " tickets (" + pct(pr.n.est / TOTAL, 0) + " of all, " + rangeTxt(pr.n) + ") | " + pct(qscore(pr), 0) + " quality score").join("\n");
  const copy = $("button", "ghost", "Copy as text"); copy.type = "button";
  copy.onclick = () => { const t = txt(); const done = () => { copy.textContent = "Copied"; setTimeout(() => { copy.textContent = "Copy as text"; }, 1500); }; if (navigator.clipboard) navigator.clipboard.writeText(t).then(done, () => { }); else { const ta = $("textarea"); ta.value = t; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove(); done(); } };
  out.push(card({
    id: "labtable", wide: true, title: "Scenarios side by side", g: {}, scopeNote: "Computed from the tree above.", controls: [copy],
    desc: "The ticked rows with their full path, size and quality score, ready to share as text.",
    body: () => { const t = table(prs.map(({ id, pr }) => ({ scenario: letterOf(id), steps: pathText(id), tickets: approx(pr.n.est, pr.grade === "exact"), "share of all": pct(pr.n.est / TOTAL, 0), range: rangeTxt(pr.n), "quality score": pct(qscore(pr), 0) }))); t.classList.add("wrapcells"); return t; }
  }));
  return out;
}
function viewLab() {
  pruneSlots(); const out = [labIntro(), labTree()], ids = comparedIds();
  if (TREE.nodes.length) out.push(labGuide(), labLadder());
  if (ids.length) out.push(...labCompare(ids));
  return out;
}

const VIEWS = [
  { id: "overview", group: "Start", title: "Overview", blurb: "Headline numbers, what stands out, and a map of the views.", responds: ["Year", "Category"], build: viewOverview },
  { id: "about", group: "Start", title: "How to read this", blurb: "Filters, the release floor and a glossary.", responds: [], build: viewAbout },
  { id: "lab", group: "Decide", title: "Corpus builder", blurb: "Build a filter tree for the RAG corpus, branch it and compare the paths.", responds: [], build: viewLab },
  { id: "time", group: "Tickets", title: "Volume & time", blurb: "Tickets per month and year, field fill by year, repeat tickets.", responds: ["Year"], build: viewTime },
  { id: "categories", group: "Tickets", title: "Categories & status", blurb: "Category mix over time and the other ticket attributes.", responds: ["Year", "Category", "Search", "Min count"], build: viewCategories },
  { id: "vehicles", group: "Vehicles", title: "Vehicles & models", blurb: "Models, vehicle year and how tickets spread over vehicles.", responds: ["Vehicle model", "Search", "Min count"], build: viewVehicles },
  { id: "baugruppe", group: "Vehicles", title: "Baugruppe", blurb: "Component groups: volume, trend, pairs and data quality.", responds: ["Year", "Baugruppe", "Vehicle model", "Search", "Min count"], build: viewBaugruppe },
  { id: "lifecycle", group: "Vehicles", title: "Vehicle age & warranty", blurb: "Operating hours, days since delivery and warranty state.", responds: [], build: viewLifecycle },
  { id: "text", group: "Text", title: "Terms & wording", blurb: "Frequent words and phrases, text length, identifiers, boilerplate.", responds: ["Category", "Search", "Min count"], build: viewText },
  { id: "who", group: "People", title: "Who files & handles", blurb: "How concentrated tickets are on a few people or entities.", responds: [], build: viewWho },
  { id: "quality", group: "Quality", title: "Data quality & readiness", blurb: "How much is usable, how complete each field is, how values look.", responds: ["Search", "Min count"], build: viewQuality },
  { id: "withheld", group: "Reference", title: "Withheld & checks", blurb: "Release checks and what the floor held back.", responds: ["Search", "Min count"], build: viewWithheld },
  { id: "raw", group: "Reference", title: "Report data", blurb: "The stored numbers of every section as tables.", responds: [], build: viewRaw },
];

/* ---------- shell ---------- */
let CUR = "overview";
const main = document.getElementById("main"), side = document.getElementById("side"), fin = document.getElementById("fin");
function viewHead(v, cards) {
  const h = $("div", "vh"); h.append($("h1", "", v.title), $("p", "", v.blurb));
  const cs = cards.filter(Boolean);
  if (cs.length > 2) { const j = $("nav", "jump"); j.setAttribute("aria-label", "On this page"); cs.forEach(c => { const a = $("a", "", c.querySelector("h2").textContent); a.href = "#" + c.id; a.addEventListener("click", e => { e.preventDefault(); c.scrollIntoView(); }); j.append(a); }); h.append(j); }
  return h;
}
function renderView() {
  const v = VIEWS.find(x => x.id === CUR) || VIEWS[0], y = window.scrollY, built = v.build();
  const cards = Array.isArray(built) ? built : built.cards, frag = $("div");
  frag.append(viewHead(v, cards.filter(Boolean)));
  if (built.before) frag.append(built.before);
  const grid = $("div", "grid"); cards.filter(Boolean).forEach(c => grid.append(c)); frag.append(grid);
  main.replaceChildren(frag); hideTip(); window.scrollTo({ top: y, behavior: "instant" });
  [...side.querySelectorAll("button")].forEach(b => b.setAttribute("aria-current", b.dataset.id === CUR ? "page" : "false"));
  document.title = v.title + " · Ticket insight report";
}
function go(id) { CUR = id; writeHash(); renderView(); window.scrollTo({ top: 0, behavior: "instant" }); }
function buildNav() {
  let g = null;
  VIEWS.forEach(v => { if (v.group !== g) { g = v.group; side.append($("h4", "", g)); } const b = $("button", "", v.title); b.type = "button"; b.dataset.id = v.id; b.onclick = () => go(v.id); side.append(b); });
}
/* the global filters change through one door, with an undo for the drawer */
function setGlobal(steps, label) {
  const before = G.steps.map(clone); G.steps = steps;
  if (label && PAL.el) PAL.last = { label, undo: () => { G.steps = before; PAL.last = null; PAL.sugg.clear(); changed(); } };
  PAL.sugg.clear(); changed();
}
const targetLabel = t => (t.k === "g" ? boolPhrase(t.id) : t.k === "x" ? (t.src === "title" ? "title" : "solution") + " contains “" + t.term + "”" : (t.key === "year" ? "year " : DIMS[t.key].label + " ") + t.v);

function toggleF(k, v) { setGlobal(choiceSteps(G.steps, { k: "dim", key: k, v: String(v) }, "include")); }
const hasGate = id => G.steps.some(s => s.t === "g" && s.f === id);
function toggleGate(id, neg) { setGlobal(choiceSteps(G.steps, { k: "g", id }, neg ? "ignore" : "include")); }
const hasTerm = (src, term) => G.steps.some(s => s.t === "x" && s.src === src && s.term === term);
function toggleTerm(src, term) { setGlobal(choiceSteps(G.steps, { k: "x", src, term }, "include")); }
function removeStep(i) { G.steps.splice(i, 1); changed(); }
function resetOne(k) { if (k === "q") T.q = ""; else if (k === "min") T.min = 0; else G.steps = G.steps.filter(s => !(k === "year" ? s.t === "y" : (s.t === "d" && s.dim === k))); changed(); }
function resetAll() { G.steps = []; T.q = ""; T.min = 0; changed(); }
function changed() { deriveF(); syncBar(); writeHash(); renderView(); if (PAL.el) renderPal(); }
function writeHash() {
  const p = new URLSearchParams(); if (G.steps.length) p.set("g", G.steps.map(stepStr).join("!")); if (T.q) p.set("q", T.q); if (T.min) p.set("min", String(T.min));
  if (TREE.nodes.length) { if (TREE.focus) p.set("foc", String(TREE.focus)); p.set("tree", treeToHash()); if (TREE.cmp) p.set("cmp", [...TREE.cmp].join(",")); p.set("qf", [...TREE.qf].join(",")); }
  const s = p.toString(); try { history.replaceState(null, "", "#" + CUR + (s ? "?" + s : "")); } catch (e) { }
}
function readHash() {
  const [v, qs] = location.hash.slice(1).split("?"), p = new URLSearchParams(qs || "");
  (p.get("g") || "").split("!").filter(Boolean).forEach(x => { const st = strStep(x); if (st) G.steps.push(st); });
  [["year", k => ({ t: "y", vals: k })], ["cat", k => ({ t: "d", dim: "cat", mode: "i", vals: k })], ["baug", k => ({ t: "d", dim: "baug", mode: "i", vals: k })], ["model", k => ({ t: "d", dim: "model", mode: "i", vals: k })]].forEach(([key, mk]) => {
    const vals = (p.get(key) || "").split(",").filter(Boolean); if (vals.length && !p.get("g")) { const st = mk(vals); if (strStep(stepStr(st))) G.steps.push(st); }
  });
  T.q = p.get("q") || ""; T.min = Math.max(0, parseInt(p.get("min"), 10) || 0);
  treeFromHash(p.get("tree"), p.get("cmp"), p.get("qf")); TREE.focus = TREE.nodes.some(n => n.id === Number(p.get("foc"))) ? Number(p.get("foc")) : 0;
  if (VIEWS.some(x => x.id === v)) CUR = v;
  deriveF();
}

/* ---------- filter bar: chips, steps with their effect, and the live impact ---------- */
/* the same three-state control wherever a filter is shown */
function tri(cur, on) {
  const d = $("div", "tri"); d.setAttribute("role", "group");
  [["i", "✓", "Include", "inc"], ["o", "⊘", "Ignore", "ign"], ["x", "○", "Not set", "unset"]].forEach(([m, ic, l, c]) => { const b = $("button", c); b.type = "button"; b.append($("span", "pic", ic), document.createTextNode(l)); b.setAttribute("aria-pressed", String(m === cur)); b.title = m === "x" ? "Remove this filter" : l + " this filter"; b.onclick = () => on(m); d.append(b); });
  return d;
}
/* the compact version for one value: include, ignore or not set, read from the steps */
function triValue(t, steps) {
  const st = rowState(steps, t), d = $("div", "ttri mini"); d.setAttribute("role", "group");
  const mk = (cls, ic, title, pressed, disabled, fn) => { const b = $("button", cls, ic); b.type = "button"; b.title = title; b.setAttribute("aria-label", title); b.setAttribute("aria-pressed", String(pressed)); b.disabled = disabled; if (!disabled) b.onclick = fn; d.append(b); return b; };
  mk("inc", "✓", "Include", st === "inc", false, () => setGlobal(choiceSteps(G.steps, t, "include")));
  const ig = mk("ign", "⊘", st === "imp" ? "Left out because other values are included" : "Ignore", st === "exc", st === "imp", () => setGlobal(choiceSteps(G.steps, t, "ignore")));
  if (st === "imp") ig.classList.add("implicit");
  mk("unset", "○", st === "none" ? "Not set" : st === "imp" ? "Not set (use the included values)" : "Not set: remove this value from the filters", st === "none", st === "none" || st === "imp", () => setGlobal(choiceSteps(G.steps, t, "clear")));
  return d;
}
const bar = {}, FP = { el: null, open: false, parts: null };
function buildBar() {
  const fb = $("button", "fbtn"); fb.type = "button"; fb.setAttribute("aria-haspopup", "dialog"); fb.setAttribute("aria-expanded", "false"); fb.title = "Active filters, quick values and list options";
  bar.badge = $("span", "fbadge", "0"); fb.append($("span", "", "Filters"), bar.badge); fb.onclick = e => { e.stopPropagation(); toggleFilterPanel(); }; bar.fbtn = fb;
  const add = $("button", "addf", "+ Add filter"); add.type = "button"; add.title = "Search every filter: categories, status, models, years, fields, text terms (press / anywhere)"; add.onclick = () => { closeFilterPanel(); openPalette("global", 0); };
  bar.impact = $("div", "impact");
  const ra = $("button", "ghost", "Reset all"); ra.id = "resetall"; ra.type = "button"; ra.onclick = resetAll; bar.ra = ra;
  fin.append(fb, add, bar.impact, ra);
  new ResizeObserver(() => requestAnimationFrame(() => document.documentElement.style.setProperty("--fbh", document.getElementById("fbar").offsetHeight + "px"))).observe(document.getElementById("fbar"));
  document.addEventListener("click", e => {
    if (FP.open && e.target.isConnected && !FP.el.contains(e.target) && !e.target.closest(".fbtn")) closeFilterPanel();
    if (MENU.el && e.target.isConnected && !MENU.el.contains(e.target)) closeMenu();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { if (MENU.el) closeMenu(); else if (PAL.el) closePalette(); else if (FP.open) closeFilterPanel(); }
    else if (e.key === "/" && !/^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || "")) { e.preventDefault(); closeFilterPanel(); if (CUR === "lab") openPalette("tree", exists(TREE.last) ? TREE.last : 0); else openPalette("global", 0); }
  });
}
function metric(label, value, base, o = {}) {
  const m = $("div", "metric"); m.append($("span", "ml", label), $("b", "mv", value));
  if (o.delta) m.append($("span", "md", o.delta));
  if (o.tip) hover(m, () => o.tip); return m;
}
const deltaPts = (v, b) => { const d = (v - b) * 100; return Math.abs(d) < 0.5 ? "" : (d > 0 ? "▲ " : "▼ ") + Math.abs(d).toFixed(0) + " pts"; };
function buildImpact(steps) {
  const pr = profile(steps), base = profile([]), ex = pr.grade === "exact", on = steps.length > 0, out = [];
  const left = metric("tickets left", approx(pr.n.est, ex), 0, { delta: on ? pct(pr.n.est / TOTAL, 0) + " of all" : "all tickets", tip: [[approx(pr.n.est, ex) + " of " + fmt(TOTAL), "tickets after all filters"], [rangeTxt(pr.n), "possible range"]] });
  const track = $("div", "mtrack"), fill = $("i"); fill.style.width = Math.max(0.5, 100 * pr.n.est / TOTAL) + "%"; track.append(fill); left.append(track); out.push(left);
  out.push(metric("quality", pct(qscore(pr), 0), 0, { delta: on ? deltaPts(qscore(pr), qscore(base)) : "", tip: [["Average fill of the quality fields", [...TREE.qf].map(f => (BOOL.get(f) || {}).short).join(", ")], ["Change them in the corpus builder", ""]] }));
  [...TREE.qf].slice(0, 4).forEach(f => { const g = BOOL.get(f); out.push(metric(g.short, pct(pr.fields[f], 0), 0, { delta: on ? deltaPts(pr.fields[f], base.fields[f]) : "", tip: [[pct(pr.fields[f], 0), g.short + " filled"], pr.known[f] ? ["", "from the report's split for these filters"] : ["", "overall rate: the report has no split for these filters"]] })); });
  return out;
}
function renderImpact() { bar.impact.replaceChildren(...buildImpact(G.steps).slice(0, 4)); }
function syncBar() {
  const n = G.steps.length + (T.q ? 1 : 0) + (T.min ? 1 : 0);
  bar.badge.textContent = String(n); bar.badge.hidden = n === 0; bar.fbtn.classList.toggle("on", n > 0);
  bar.ra.disabled = !anyFilter(); renderImpact();
  if (FP.open) renderFilterPanel();
  requestAnimationFrame(() => document.documentElement.style.setProperty("--fbh", document.getElementById("fbar").offsetHeight + "px"));
}

/* ---------- the filters panel: what is active, quick values, list options ---------- */
function buildFilterPanel() {
  const el = $("div", "dlg fpanel"); el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Filters");
  const head = $("div", "dhead"), ht = $("div"), x = $("button", "dx", "×"); x.type = "button"; x.setAttribute("aria-label", "Close"); x.onclick = closeFilterPanel;
  ht.append($("div", "dtitle", "Filters"), $("div", "dsub", "Include keeps tickets, Ignore leaves them out, Not set removes the filter.")); head.append(ht, x);
  const body = $("div", "dbody fbody"), activeBox = $("div", "fsec"), quickBox = $("div", "fsec"), opts = $("div", "fsec");
  opts.append($("h3", "fh", "List options"), $("p", "fnote", "These narrow the ranked lists and tables, not the ticket counts."));
  const row = $("div", "fopts"), ql = $("label", "fin"), qi = $("input"), ml = $("label", "fin"), mi = $("input");
  ql.append(document.createTextNode("Search"), qi); qi.type = "search"; qi.placeholder = "terms, values, fields"; qi.setAttribute("aria-label", "Search labels"); qi.oninput = () => { T.q = qi.value.trim(); changed(); };
  ml.append(document.createTextNode("Min count"), mi); mi.type = "number"; mi.min = "0"; mi.step = "10"; mi.setAttribute("aria-label", "Minimum count"); mi.oninput = () => { T.min = Math.max(0, parseInt(mi.value, 10) || 0); changed(); };
  row.append(ql, ml); opts.append(row); body.append(activeBox, quickBox, opts);
  const foot = $("div", "dfoot"), ob = $("button", "dbtn", "Open in builder"), done = $("button", "dbtn primary", "Done");
  ob.type = "button"; ob.title = "Turn these filters into the first steps of a corpus-builder tree"; ob.onclick = () => { closeFilterPanel(); seedFromGlobal(); go("lab"); }; done.type = "button"; done.onclick = closeFilterPanel; foot.append(ob, done);
  el.append(head, body, foot); FP.parts = { activeBox, quickBox, qi, mi }; return el;
}
function renderFilterPanel() {
  const P = FP.parts, steps = G.steps;
  P.activeBox.replaceChildren($("h3", "fh", steps.length ? "Active filters (" + steps.length + ")" : "Active filters"));
  if (!steps.length) P.activeBox.append($("p", "fempty", "No filters yet. Use + Add filter, click a bar in any chart, or set the quick values below."));
  steps.forEach((st, i) => {
    const row = $("div", "arow"), sub = $("div", "asubwrap"); sub.append($("span", "asub", stepSubject(st)));
    const edit = $("button", "linkbtn", "values"); edit.type = "button"; edit.title = "Pick other values for this filter"; edit.onclick = () => { closeFilterPanel(); openPalette("global", 0); PAL.nav = st.t === "y" ? "year" : st.t === "d" ? st.dim : st.t === "g" ? "facts" : "terms"; renderPal(); };
    sub.append(edit);
    row.append(sub, tri(stepMode(st), m => { const next = G.steps.map(clone); if (m === "x") next.splice(i, 1); else setStepMode(next[i], m); setGlobal(next); }));
    P.activeBox.append(row);
  });
  P.quickBox.replaceChildren($("h3", "fh", "Quick values"), $("p", "fnote", "Set a value to Include or Ignore, or clear it with ○."));
  ["cat", "year"].forEach(k => {
    const opts = FD[k].opts(), mx = Math.max(...opts.map(o => o.n), 1), act = opts.filter(o => rowState(steps, { k: "dim", key: k, v: o.v }) !== "none").length;
    const d = $("details", "qsec"); d.open = FP.openSec ? FP.openSec[k] !== false : true; d.addEventListener("toggle", () => { FP.openSec = FP.openSec || {}; FP.openSec[k] = d.open; });
    const sm = $("summary"); sm.append($("span", "qname", FD[k].label), $("span", "qcount", act ? act + " set" : opts.length + " values")); d.append(sm);
    opts.forEach(o => {
      const r = $("div", "qrow"), m = $("span", "emeter"), f = $("i"); f.style.width = (100 * o.n / mx) + "%"; m.append(f);
      r.append($("span", "ql", o.v), m, $("span", "qc", fmt(o.n)), triValue({ k: "dim", key: k, v: o.v }, steps)); d.append(r);
    });
    P.quickBox.append(d);
  });
  const more = $("button", "linkbtn", "More values: status, model, Baugruppe, fields, words…"); more.type = "button"; more.onclick = () => { closeFilterPanel(); openPalette("global", 0); }; P.quickBox.append(more);
  if (document.activeElement !== P.qi) P.qi.value = T.q;
  if (document.activeElement !== P.mi) P.mi.value = T.min ? String(T.min) : "";
}
function openFilterPanel() {
  if (PAL.el) closePalette(true); closeMenu();
  if (!FP.el) FP.el = buildFilterPanel();
  const r = bar.fbtn.getBoundingClientRect(), fb = document.getElementById("fbar").getBoundingClientRect();
  FP.el.style.left = Math.max(8, Math.min(r.left, innerWidth - 560)) + "px"; FP.el.style.top = (fb.bottom + 8) + "px"; FP.el.style.maxHeight = Math.max(240, innerHeight - fb.bottom - 24) + "px";
  document.body.append(FP.el); FP.open = true; bar.fbtn.setAttribute("aria-expanded", "true"); renderFilterPanel();
}
function closeFilterPanel() { if (FP.open) { FP.el.remove(); FP.open = false; bar.fbtn.setAttribute("aria-expanded", "false"); } }
const toggleFilterPanel = () => (FP.open ? closeFilterPanel() : openFilterPanel());

/* ---------- the step search: a side drawer over a dimmed page ---------- */
const PAL = { el: null, scrim: null, mode: "global", base: 0, q: "", nav: "suggested", sel: 0, rows: [], sugg: new Map(), add: "below", last: null, opener: null, parts: null };
const palSteps = () => (PAL.mode === "global" ? G.steps : pathOf(PAL.base));
function openPalette(mode, base) {
  if (PAL.el) closePalette(true);
  closeFilterPanel(); PAL.opener = document.activeElement; PAL.mode = mode; PAL.base = exists(base || 0) ? base || 0 : 0;
  PAL.q = ""; PAL.nav = "suggested"; PAL.sel = 0; PAL.add = "below"; PAL.last = null; buildPalette();
}
function closePalette(quiet) {
  if (!PAL.el) return;
  PAL.el.remove(); PAL.scrim.remove(); PAL.el = PAL.scrim = null;
  if (!quiet && PAL.opener && PAL.opener.focus) PAL.opener.focus();
}
function effectOf(steps, step) { const b = profile(steps), p = profile(steps.concat(step)); return { keep: b.n.est ? p.n.est / b.n.est : 0, n: p.n, grade: p.grade, from: qscore(b), to: qscore(p) }; }
const dStep = (k, mode, v) => ({ t: "d", dim: k, mode, vals: [v] });
function groupRows(group, toks) {
  const hit = s => toks.every(t => s.toLowerCase().includes(t)), rows = [];
  if (!group || DIMS[group]) (group ? [group] : DIM_KEYS).forEach(k => { const d = DIMS[k]; d.values.forEach(v => { if (hit(d.label + " " + v.v)) rows.push({ g: d.label, label: v.v, count: v.n, t: { k: "dim", key: k, v: v.v }, a: { name: "include", step: dStep(k, "i", v.v) }, b: { name: "ignore", step: dStep(k, "o", v.v) } }); }); });
  if (!group || group === "year") M.yearKeys.forEach(y => { if (hit("year " + y)) rows.push({ g: "Year", label: y, count: M.yearN.get(y), t: { k: "dim", key: "year", v: y }, a: { name: "include", step: { t: "y", mode: "i", vals: [y] } }, ...(M.yearKeys.length > 1 ? { b: { name: "ignore", step: { t: "y", mode: "o", vals: [y] } } } : {}) }); });
  if (!group || group === "facts") BOOL.forEach(bv => { if (hit(bv.short + " " + bv.phrase + " field fact")) rows.push({ g: bv.field ? "Field" : "Fact", label: bv.phrase, count: bv.F, t: { k: "g", id: bv.id }, a: { name: "include", step: { t: "g", f: bv.id, neg: false } }, b: { name: "ignore", step: { t: "g", f: bv.id, neg: true } } }); });
  if (group === "terms" || (!group && toks.length && toks.join("").length >= 2)) TERMS_ALL.filter(t => hit(t.term + " " + (t.src === "title" ? "title" : "solution"))).sort((a, b) => b.n - a.n).slice(0, group === "terms" ? 60 : 12).forEach(t => rows.push({ g: t.src === "title" ? "Title word" : "Solution word", label: "“" + t.term + "”", count: t.n, t: { k: "x", src: t.src, term: t.term }, a: { name: "include", step: { t: "x", src: t.src, term: t.term, neg: false } }, b: { name: "ignore", step: { t: "x", src: t.src, term: t.term, neg: true } } }));
  return rows;
}
function splitRows(toks) {
  return DIM_KEYS.map(k => ({ g: "Split", label: "by " + DIMS[k].label.toLowerCase(), split: k })).concat([{ g: "Split", label: "by year", split: "year" }]).filter(r => toks.every(t => ("split branches " + r.label).includes(t)));
}
function suggest(steps) {
  const key = steps.map(stepStr).join("!") + "|" + [...TREE.qf].join(","); if (PAL.sugg.has(key)) return PAL.sugg.get(key);
  const base = profile(steps), cands = [];
  DIM_KEYS.forEach(k => { const d = DIMS[k]; d.values.forEach(v => { cands.push(dStep(k, "i", v.v), dStep(k, "o", v.v)); }); });
  BOOL.forEach(bv => { cands.push({ t: "g", f: bv.id, neg: false }, { t: "g", f: bv.id, neg: true }); });
  TERMS_ALL.slice().sort((a, b) => b.n - a.n).slice(0, 25).forEach(t => { cands.push({ t: "x", src: t.src, term: t.term, neg: false }, { t: "x", src: t.src, term: t.term, neg: true }); });
  const out = cands.map(step => { const p = profile(steps.concat(step)), keep = base.n.est ? p.n.est / base.n.est : 0, from = qscore(base), to = qscore(p); return { step, keep, from, to, eff: (to - from) / Math.max(1 - keep, 0.02), n: p.n }; })
    .filter(c => c.keep > 0.05 && c.keep < 0.995 && c.to > c.from + 0.003).sort((a, b) => b.eff - a.eff).slice(0, 8);
  PAL.sugg.set(key, out); return out;
}
/* which part of the step list belongs to a rail entry (for the badges) */
function stepTarget(st) {
  if (st.t === "d") return { t: { k: "dim", key: st.dim, v: st.vals[0] }, choice: dmode(st) === "i" ? "include" : "ignore" };
  if (st.t === "y") return { t: { k: "dim", key: "year", v: st.vals[0] }, choice: dmode(st) === "i" ? "include" : "ignore" };
  if (st.t === "g") return { t: { k: "g", id: st.f }, choice: st.neg ? "ignore" : "include" };
  return { t: { k: "x", src: st.src, term: st.term }, choice: st.neg ? "ignore" : "include" };
}
const stepNav = s => (s.t === "y" ? "year" : s.t === "d" ? s.dim : s.t === "g" ? "facts" : "terms");
function palRows() {
  const toks = PAL.q.toLowerCase().split(/\s+/).filter(Boolean), n = PAL.nav;
  if (toks.length) return groupRows("", toks).slice(0, 60).concat(PAL.mode === "tree" ? splitRows(toks) : []);
  if (n === "suggested") return suggest(palSteps()).map(c => ({ g: "Suggested", label: stepLabel(c.step), count: null, ...stepTarget(c.step), a: { name: "add", step: c.step }, note: "quality " + pct(c.from, 0) + " → " + pct(c.to, 0) }));
  if (n === "split") return splitRows([]);
  return groupRows(n, []).slice(0, 80);
}
const ACTION = { include: "Include", ignore: "Ignore", add: "Apply", split: "Split" };
const NAVHELP = {
  suggested: "Steps that raise the quality score the most for each ticket they remove.",
  facts: "Yes/no facts about each ticket. Include keeps tickets where it is true, Ignore leaves those out.",
  terms: "The most frequent words and phrases in titles and solutions. Type to find others.",
  split: "Create one branch per value to compare them side by side.",
};
function railItems() {
  const items = [{ h: "" }, { k: "suggested", l: "Suggested" }, { k: "facts", l: "Fields & facts" }, { k: "terms", l: "Words" }];
  if (PAL.mode === "tree") items.push({ k: "split", l: "Split into branches" });
  items.push({ h: "Values" });
  DIM_KEYS.forEach(k => items.push({ k, l: DIMS[k].label })); items.push({ k: "year", l: "Year" });
  return items;
}
function buildPalette() {
  const scrim = $("div"); scrim.id = "palscrim"; scrim.onclick = () => closePalette();
  const el = $("aside"); el.id = "pal"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", PAL.mode === "global" ? "Add a filter" : "Add a step");
  const fb = document.getElementById("fbar").getBoundingClientRect().bottom; scrim.style.top = el.style.top = fb + "px";
  const head = $("div", "phead"), ht = $("div"), title = $("div", "ptitle"), sub = $("div", "psub"), x = $("button", "dx", "×"); x.type = "button"; x.setAttribute("aria-label", "Close"); x.title = "Close (Esc)"; x.onclick = () => closePalette(); ht.append(title, sub); head.append(ht, x);
  const sbox = $("div", "psearch"), mag = $("span", "pmag", "⌕"), inp = $("input"), clr = $("button", "pclear", "×"); inp.type = "text"; inp.placeholder = "Search every value, field and word…"; inp.setAttribute("aria-label", "Search steps"); inp.autocomplete = "off"; clr.type = "button"; clr.setAttribute("aria-label", "Clear search"); clr.hidden = true;
  inp.oninput = () => { PAL.q = inp.value; PAL.sel = 0; clr.hidden = !PAL.q; renderPal(); };
  clr.onclick = () => { PAL.q = ""; inp.value = ""; clr.hidden = true; PAL.sel = 0; renderPal(); inp.focus(); };
  inp.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { e.preventDefault(); PAL.sel = Math.min(PAL.rows.length - 1, PAL.sel + 1); renderPal(true); }
    else if (e.key === "ArrowUp") { e.preventDefault(); PAL.sel = Math.max(0, PAL.sel - 1); renderPal(true); }
    else if (e.key === "Enter") { e.preventDefault(); const r = PAL.rows[PAL.sel]; if (r) rowAct(r, e.altKey && r.b ? r.b : r.a, e.shiftKey); }
  });
  sbox.append(mag, inp, clr);
  const addmode = $("div", "paddmode"), body = $("div", "pbody"), rail = $("nav", "prail"), pane = $("div", "ppane"), ctx = $("div", "pctx"), list = $("div", "plist"), foot = $("div", "pfoot");
  rail.setAttribute("aria-label", "Kinds of filter"); pane.append(ctx, list); body.append(rail, pane);
  el.append(head, sbox, addmode, body, foot);
  document.body.append(scrim, el); PAL.el = el; PAL.scrim = scrim; PAL.parts = { title, sub, inp, clr, addmode, rail, ctx, list, foot }; renderPal(); inp.focus();
}
const kindOf = a => (a.name === "ignore" ? "ignore" : a.name === "include" ? "include" : a.name === "clear" ? "clear" : a.split ? "split" : "apply");
/* one entry for mouse and keyboard: global filters toggle cleanly, builder steps are added */
function rowAct(r, a, branch) {
  if (a.split) return palAct(r, a, branch);
  if (PAL.mode === "tree") {
    const kind = kindOf(a), choice = kind === "apply" ? r.choice : kind;
    if (r.t && rowState(palSteps(), r.t) !== "none" && treeRowChoose(r, choice)) return;
    if (kind === "clear") return;
    return palAct(r, a, branch);
  }
  if (!r.t) return;
  const kind = kindOf(a), choice = kind === "apply" ? r.choice : kind, st = rowState(G.steps, r.t);
  if (choice === "ignore" && st === "imp") return;
  const on = choice === "clear" || (choice === "include" && st === "inc") || (choice === "ignore" && st === "exc");
  setGlobal(choiceSteps(G.steps, r.t, choice), on ? "Cleared " + targetLabel(r.t) : "Added " + targetLabel(r.t) + " (" + choice + ")");
}
function palAct(row, act, branch) {
  if (act.split) { if (PAL.mode === "tree") { pushHist(); const ids = splitInto(PAL.base, act.split, true); PAL.last = { label: "Split " + row.label, undo: () => ids.forEach(id => exists(id) && removeNode(id)) }; treeChanged(); PAL.sugg.clear(); renderPal(); } return; }
  if (PAL.mode === "global") return rowAct(row, act, branch);
  const asBranch = branch || PAL.add === "branch";
  if (act.step && palSteps().some(s => stepStr(s) === stepStr(act.step))) return;
  pushHist(); const prev = PAL.base, id = addStep(PAL.base, clone(act.step), true); if (!asBranch) PAL.base = id;
  PAL.last = { label: "Added " + stepLabel(act.step), undo: () => { removeNode(id); PAL.base = exists(prev) ? prev : 0; renderPal(); } };
  treeChanged(); PAL.sugg.clear(); if (PAL.el) renderPal();
}
function renderPal(keepScroll) {
  const P = PAL.parts, steps = palSteps();
  P.title.textContent = PAL.mode === "global" ? "Add a filter" : "Add a step";
  P.sub.textContent = PAL.mode === "global" ? "Include keeps tickets, Ignore leaves them out. Every button shows how many tickets would be left." : "Adds below: " + (steps.length ? steps.map(shortStep).join(" · ") : "all tickets");
  P.addmode.replaceChildren(); P.addmode.hidden = PAL.mode !== "tree";
  if (PAL.mode === "tree") P.addmode.append($("span", "plab", "Add as"), seg([["below", "Next step below"], ["branch", "New branch here"]], PAL.add, v => { PAL.add = v; renderPal(); PAL.parts.inp.focus(); }));
  /* rail: every kind of filter, with a badge for how many are active */
  P.rail.replaceChildren();
  const counts = {}; steps.forEach(s => { const k = stepNav(s); counts[k] = (counts[k] || 0) + 1; });
  railItems().forEach(it => {
    if (it.h !== undefined) { if (it.h) P.rail.append($("div", "prh", it.h)); return; }
    const b = $("button", "pri"); b.type = "button"; b.setAttribute("aria-pressed", String(PAL.nav === it.k && !PAL.q)); b.append($("span", "", it.l)); if (counts[it.k]) b.append($("span", "badge", String(counts[it.k])));
    b.onclick = () => { PAL.nav = it.k; PAL.q = ""; P.inp.value = ""; P.clr.hidden = true; PAL.sel = 0; renderPal(); P.inp.focus(); }; P.rail.append(b);
  });
  /* context: what is left, what is applied, and the way to undo */
  P.ctx.replaceChildren();
  const imp = $("div", "impact compact"); buildImpact(steps).slice(0, 5).forEach(n => imp.append(n)); P.ctx.append(imp);
  const act = $("div", "pactive2"), ids = PAL.mode === "tree" ? pathIds(PAL.base) : null, items = PAL.mode === "global" ? G.steps : steps;
  act.append($("div", "plab", items.length ? (PAL.mode === "global" ? "Active filters" : "Path to here") : (PAL.mode === "global" ? "No filters yet" : "Start: all tickets")));
  items.forEach((st, i) => {
    const arow = $("div", "arow"); arow.append($("span", "asub", stepSubject(st)), tri(stepMode(st), m => {
      if (PAL.mode === "global") { const next = G.steps.map(clone); if (m === "x") next.splice(i, 1); else setStepMode(next[i], m); setGlobal(next, (m === "x" ? "Removed " : m === "o" ? "Ignoring " : "Including ") + stepSubject(st)); }
      else setNodeState(ids[i], m === "o" ? "ignore" : m === "i" ? "include" : "x");
    }));
    act.append(arow);
  });
  P.ctx.append(act);
  if (PAL.last) { const l = $("div", "plast"), u = $("button", "linkbtn", "Undo"); u.type = "button"; u.onclick = () => { const q = PAL.last; PAL.last = null; q.undo(); PAL.sugg.clear(); if (PAL.el) renderPal(); }; l.append($("b", "", PAL.last.label), u); P.ctx.append(l); }
  PAL.rows = palRows(); PAL.sel = Math.min(PAL.sel, Math.max(0, PAL.rows.length - 1));
  const list = P.list, top = list.scrollTop; list.replaceChildren();
  list.append($("div", "phd", PAL.q ? "Results for “" + PAL.q + "”" : (NAVHELP[PAL.nav] || (PAL.nav === "year" ? "Include years, or Ignore one. The report splits every field by year, so quality differs per year." : DIMS[PAL.nav].label + ": include values to keep them, ignore values to leave them out. " + (PAL.nav === "cat" ? "The report splits solution and description by category, so their quality differs per category." : "The report has no quality split for this: a choice changes how many tickets are left, while quality stays at the overall rate.")))));
  if (!PAL.rows.length) list.append($("div", "pempty", PAL.q ? "Nothing matches. Words need at least " + K + " tickets to be listed." : "No single step improves this any further."));
  const applied = new Set(steps.map(stepStr)), mx = Math.max(...PAL.rows.map(r => r.count || 0), 1);
  PAL.rows.forEach((r, ri) => {
    const row = $("div", "prow" + (ri === PAL.sel ? " on" : "")), main = $("div", "pmain");
    const tl = $("div", "ptl"); if (PAL.q || PAL.nav === "suggested") tl.append($("span", "pg", r.g)); tl.append($("span", "pl", r.label)); main.append(tl);
    if (r.count != null) { const sub = $("div", "pcount"), m = $("span", "pcbar"), f = $("i"); f.style.width = (100 * r.count / mx) + "%"; m.append(f); sub.append(m, $("span", "", fmt(r.count) + " tickets")); main.append(sub); }
    if (r.note) main.append($("div", "pnote", r.note));
    row.append(main);
    const acts = $("div", r.b ? (r.t ? "pinc pinc3" : "pinc") : "pacts"); acts.setAttribute("role", "group");
    const pair = [r.a, r.b].filter(Boolean), st = r.t ? rowState(steps, r.t) : "none";
    pair.forEach(a => {
      const kind = kindOf(a), choice = kind === "apply" ? r.choice : kind;
      const b = $("button", "pi " + kind); b.type = "button";
      b.append($("span", "pic", kind === "ignore" ? "⊘" : "✓"), $("span", "pn", ACTION[a.name] || a.name));
      const on = (choice === "include" && st === "inc") || (choice === "ignore" && st === "exc"), implicit = choice === "ignore" && st === "imp";
      b.setAttribute("aria-pressed", String(on || implicit));
      if (on) { b.classList.add("on"); b.append($("small", "", "Click to clear")); b.title = PAL.mode === "global" ? "Click to remove this filter" : "Click to remove this step from the path"; }
      else if (implicit) { b.classList.add("implicit"); b.append($("small", "", "Left out")); b.title = "Left out because other values are included. Include it to bring it back."; b.disabled = true; }
      else if (a.split) b.title = "One branch per value, compared side by side";
      else {
        const nextSteps = r.t && (PAL.mode === "global" || st !== "none") ? choiceSteps(steps, r.t, choice) : steps.concat(a.step), base = profile(steps), nx = profile(nextSteps);
        b.append($("small", "", approx(nx.n.est, nx.grade === "exact") + " left")); b.append($("small", "pq", "quality " + pct(qscore(nx), 0) + " " + sgn(qscore(nx) - qscore(base))));
        b.title = pct(base.n.est ? nx.n.est / base.n.est : 0, 0) + " of the tickets now in view stay · quality " + pct(qscore(base), 0) + " → " + pct(qscore(nx), 0) + (st === "exc" && choice === "include" ? " · stops ignoring it" : "");
      }
      b.onclick = ev => { if (!b.disabled) rowAct(r, a, ev.shiftKey); }; acts.append(b);
    });
    if (r.t && r.b) {
      const nb = $("button", "pi unset"), none = st === "none"; nb.type = "button"; nb.append($("span", "pic", "○"), $("span", "pn", "Not set")); nb.setAttribute("aria-pressed", String(none)); if (none) nb.classList.add("on");
      nb.disabled = none || st === "imp"; nb.title = none ? "Not part of the filters" : st === "imp" ? "Left out by the included values; unset those instead" : PAL.mode === "global" ? "Take this value out of the filters" : "Take this value out of the path";
      nb.onclick = () => { if (!nb.disabled) rowAct(r, { name: "clear" }, false); }; acts.append(nb);
    }
    row.append(acts); list.append(row);
  });
  P.foot.replaceChildren(); const k = t => $("kbd", "", t);
  P.foot.append(k("↑"), k("↓"), document.createTextNode(" move  "), k("Enter"), document.createTextNode(" include  "), k("Alt+Enter"), document.createTextNode(" ignore  "), k("Esc"), document.createTextNode(" close"));
  list.scrollTop = keepScroll ? top : 0; if (keepScroll) { const on = list.querySelector(".prow.on"); if (on) on.scrollIntoView({ block: "nearest" }); }
}

const themes = ["auto", "light", "dark"]; let ti = 2;
document.getElementById("theme").onclick = e => { ti = (ti + 1) % 3; if (themes[ti] === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", themes[ti]); e.target.textContent = "Theme: " + themes[ti]; };
const p = R.provenance || {};
document.getElementById("sub").textContent = fmt(TOTAL) + " tickets · commit " + (p.code_commit || "?") + " · release floor " + K + " · schema " + R.schema_version;
buildNav(); buildBar(); readHash(); syncBar(); renderView();
{
  const hp = new URLSearchParams(location.hash.split("?")[1] || ""), pm = hp.get("pal");
  if (pm === "global" || pm === "tree") { openPalette(pm, exists(TREE.last) ? TREE.last : 0); PAL.q = hp.get("palq") || ""; PAL.nav = hp.get("palt") || "suggested"; PAL.parts.inp.value = PAL.q; PAL.parts.clr.hidden = !PAL.q; renderPal(); }
}{
  const hp2 = new URLSearchParams(location.hash.split("?")[1] || "");
  if (hp2.get("fp")) openFilterPanel();
  const th = hp2.get("theme"); if (th && themes.includes(th)) { ti = themes.indexOf(th); if (th === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", th); document.getElementById("theme").textContent = "Theme: " + th; }
}

window.addEventListener("resize", () => syncBar());
</script>
</body>
</html>
"""


def render(report: dict) -> str:
    """The page for a report; the JSON cannot close its own script element."""
    data = json.dumps(report, ensure_ascii=False, allow_nan=False)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    data = data.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return _PAGE.replace("__CSP__", _CSP).replace("__DATA__", data)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m insight.view REPORT.json OUT.html", file=sys.stderr)
        return 2
    source, target = Path(args[0]), Path(args[1])
    try:
        report = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("REFUSED: the report cannot be read as JSON", file=sys.stderr)
        return 3
    if not isinstance(report, dict):
        print("REFUSED: the report is not a JSON object", file=sys.stderr)
        return 3
    min_frequency = report.get("provenance", {}).get("min_frequency")
    k = min_frequency if isinstance(min_frequency, int) and min_frequency > 0 else None
    if k is None or guard.unaccounted(report, k):
        print("REFUSED: the guard does not accept this report; nothing written", file=sys.stderr)
        return 2
    if target.exists() and source.exists() and os.path.samefile(source, target):
        print("REFUSED: output would overwrite the report", file=sys.stderr)
        return 2
    partial = target.with_name(target.name + ".tmp")
    partial.write_text(render(report), encoding="utf-8")
    os.replace(partial, target)
    print(f"wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
