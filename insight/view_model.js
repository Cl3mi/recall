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
const PCACHE = new Map();
function profile(steps) {
  const key = JSON.stringify(steps) + "|" + QSET.n;
  if (PCACHE.has(key)) return PCACHE.get(key);
  if (PCACHE.size > 100000) PCACHE.clear();
  /* a cached entry outlives the tree's step objects, which are edited in place: it keeps its own copy */
  const own = JSON.parse(JSON.stringify(steps)), sc = scopeOf(own), ev = evalScope(sc), fields = {}, known = {};
  const qq = Q ? (sc.empty ? qEmpty() : qOf(sc)) : null;
  GATES.forEach(([f]) => {
    const g = sc.gates.find(x => x.id === f);
    if (qq && QF.includes(f) && !g) { fields[f] = qq.f[f]; known[f] = qq.known; return; }
    fields[f] = g ? (g.neg ? 0 : 1) : (ev.sz.est > 0 ? filledOf(f, sc, ev.sz, false).p : 0);
    known[f] = !!g || (!sc.C && !sc.Y) || (!!sc.Y && f !== "boiler") || (!!sc.C && (f === "solutions" || f === "description"));
  });
  const cb = CUBE && !sc.empty ? cubeOf(own, sc, ev, qq) : null;
  if (cb) {
    const out = { n: cb.n, grade: cb.grade, fields: { ...fields, ...cb.fields }, known, sc, q: cb.q, steps: own, guessed: cb.guessed };
    PCACHE.set(key, out); return out;
  }
  const n = { ...ev.n };
  const upPr = steps.length ? profile(steps.slice(0, -1)) : null;
  if (upPr) { const up = upPr.n; n.hi = Math.min(n.hi, up.hi); n.est = Math.max(Math.min(n.lo, n.hi), Math.min(n.est, up.est, n.hi)); n.lo = Math.min(n.lo, n.est); }
  let q = null;
  if (qq) {
    /* a step can only remove usable tickets, so the estimate never rises above the step before */
    const r = Math.min(n.est * qq.p, upPr && upPr.q ? upPr.q.r : Infinity), all = qRootR();
    q = { p: n.est > 0 ? r / n.est : 0, r, kept: all > 0 ? Math.min(1, r / all) : 0, exact: qq.exact && n.hi - n.lo < 0.5, known: qq.known };
  }
  const grade = n.hi - n.lo < 0.5 ? "exact" : CUBE ? "estimated" : "estimate";
  if (q && CUBE) {
    if (q.exact) { q.rlo = q.r; q.rhi = q.r; }
    else { q.rlo = Math.max(0, qRootR() - (TOTAL - n.lo)); q.rhi = Math.max(q.rlo, Math.min(n.hi, qRootR())); }
  }
  const out = { n, grade, fields, known, sc, q, steps: own, guessed: CUBE ? own.filter(s => !cubeStep(s)) : [] };
  PCACHE.set(key, out); return out;
}
/* a path with cube steps: the cube answers its cube part, the old model corrects for the rest */
function cubeOf(own, sc, ev, qq) {
  const part = own.filter(cubeStep), rest = own.filter(s => !cubeStep(s));
  if (!part.length) return null;
  /* the quality section already answers some paths exactly (a category by year): keep that answer */
  if (ev.n.hi - ev.n.lo < 0.5 && (!qq || qq.exact)) return null;
  const scS = scopeOf(part); if (scS.empty) return null;
  const con = cubeCon(scS); if (!con) return null;
  const iv = cubeAnswer(con); if (!iv) return null;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v)), all = qRootR();
  /* the step above holds every ticket this path holds, and the old model's range is guaranteed too */
  const up = own.length > 1 ? profile(own.slice(0, -1)) : null, cap = Math.min(ev.n.hi, up ? up.n.hi : Infinity);
  const evS = evalScope(scS), cl = Math.max(iv.lo.n, ev.n.lo), ch = Math.max(cl, Math.min(iv.hi.n, cap));
  const cEst = ch - cl < 0.5 ? cl : clamp(evS.n.est, cl, ch);
  let n, grade, rlo, rhi, rEst;
  const rcap = Math.min(ch, up && up.q && up.q.rhi !== undefined ? up.q.rhi : Infinity);
  const qS = qq ? qOf(scS) : null;
  const rl = Math.min(iv.lo.r, ch), rh = Math.max(rl, Math.min(iv.hi.r, rcap)), cR = rh - rl < 0.5 ? rl : clamp(cEst * (qS ? qS.p : 0), rl, rh);
  if (!rest.length) {
    n = { lo: cl, est: cEst, hi: ch }; grade = ch - cl < 0.5 ? "exact" : "bounded";
    rlo = rl; rhi = rh; rEst = cR;
    if (up && grade !== "exact") { n.est = Math.max(n.lo, Math.min(n.est, up.n.est)); if (up.q) rEst = Math.max(rlo, Math.min(rEst, up.q.r)); }
  } else {
    /* the rest keeps the independence estimate: swap the old guess for the cube's part by its true value */
    const restLo = evalScope(scopeOf(rest)).n.lo, ratio = evS.n.est > 0 ? ev.n.est / evS.n.est : 0;
    const lo = Math.max(ev.n.lo, cl + restLo - TOTAL, 0), hi = Math.max(lo, Math.min(ev.n.hi, ch));
    n = { lo, est: clamp(cEst * ratio, lo, hi), hi }; grade = hi - lo < 0.5 ? "exact" : "estimated";
    const cP = cEst > 0 ? cR / cEst : 0;
    const p = qq && qS && qS.p > 0 ? clamp(qq.p * cP / qS.p, 0, 1) : cP;
    rlo = Math.max(0, rl + restLo - TOTAL); rhi = Math.max(rlo, Math.min(rh, hi)); rEst = clamp(n.est * p, rlo, rhi);
    /* an estimate never rises above the step before, as in the model without a cube */
    if (up && grade !== "exact") {
      n.est = Math.max(n.lo, Math.min(n.est, up.n.est));
      if (up.q) rEst = Math.max(rlo, Math.min(rEst, up.q.r));
    }
  }
  rlo = Math.max(rlo, all - (TOTAL - n.lo), 0);
  const fields = {};
  if (qq) QF.forEach(f => { const cf = cEst > 0 ? clamp((iv.lo[f] + iv.hi[f]) / 2 / cEst, 0, 1) : 0; fields[f] = rest.length && qS && qS.f[f] > 0 ? clamp(qq.f[f] * cf / qS.f[f], 0, 1) : cf; });
  sc.gates.forEach(g => { fields[g.id] = g.neg ? 0 : 1; });
  const q = qq ? { p: n.est > 0 ? rEst / n.est : 0, r: rEst, rlo, rhi, kept: all > 0 ? Math.min(1, rEst / all) : 0, exact: grade === "exact" && rhi - rlo < 0.5, known: !rest.length || qq.known, grade: grade === "exact" && rhi - rlo >= 0.5 ? "bounded" : grade } : null;
  return { n, grade, fields, q, guessed: rest };
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

/* ---------- usable share: the report's quality section (spec 2026-10-15) ----------
   The report grades every ticket once: noise (blank or templated problem text, or no solution left once
   workflow phrases are stripped), near-duplicate solution, or retrievable at N content words. It splits those
   counts by every dimension, every year, every field and the lifecycle buckets, so a single step is measured
   exactly. Several steps combine the way filledOf combines year and category: the product of their rates over
   the overall rate. A step the report has no split for (repeat ticket, ids in text, a word) leaves the rate
   at what the other steps say and marks the node as not measured. */
const Q = (() => { const q = get(R, "quality"); return q && q.overall && Array.isArray(q.overall.retrievable) ? q : null; })();
const QF = ["description", "solutions", "serial", "model_id", "baugruppe", "fehlercode", "hours", "delivery"];
const QLADDER = Q ? Q.overall.retrievable.map(r => r.min_words) : [];
const QSET = { n: Q ? (QLADDER.includes(Q.default_min_words) ? Q.default_min_words : QLADDER[0]) : 0 };
function setMinWords(n) { if (QLADDER.includes(n)) QSET.n = n; }
const BCACHE = new Map();
const QK = ["n", "r", "z"].concat(QF);
/* a report group as a vector at the current N: tickets, retrievable, noise and one count per field */
function qv(g) {
  if (!g) return null;
  const r = (g.retrievable || []).find(x => x.min_words === QSET.n), v = { n: g.count || 0, r: r ? r.tickets : 0, z: g.noise || 0 };
  QF.forEach(f => { v[f] = (g.fields || {})[f] || 0; }); return v;
}
const vadd = (a, b) => { if (!a) return b ? { ...b } : null; if (!b) return { ...a }; const o = {}; QK.forEach(k => { o[k] = a[k] + b[k]; }); return o; };
const vsub = (a, b) => { const o = {}; QK.forEach(k => { o[k] = Math.max(0, a[k] - (b ? b[k] : 0)); }); return o; };
const QDIM = { cat: "categoryId", status: "statusId", prio: "priorityId", sub: "subStatusString", vstat: "vehicleStatus", show: "showInProteam", model: "model_id", baug: "baugruppe" };
const QLIFE = { warr: ["warranty", "states", "state"], hours: ["hours", "buckets", "bucket"], days: ["days_since_delivery", "buckets", "bucket"] };
const QT = (() => {
  if (!Q) return null;
  const t = { year: new Map((Q.by_year || []).map(g => [String(g.year), g])), dim: {}, cross: {} };
  Object.entries(QDIM).forEach(([k, rk]) => { const d = (Q.by_dimension || {})[rk]; if (!d) return; t.dim[k] = new Map((d.values || []).map(g => [String(g.value), g])); t.cross[k] = new Map((d.by_year || []).map(g => [String(g.value) + "|" + String(g.year), g])); });
  Object.entries(QLIFE).forEach(([k, [rk, list, lab]]) => { const d = (Q.by_lifecycle || {})[rk]; if (d) t.dim[k] = new Map((d[list] || []).map(g => [String(g[lab]), g])); });
  return t;
})();
const qRootR = () => (Q ? qv(Q.overall).r : 0);
/* the sum of every released value of a dimension (in one year, or overall), memoised per word count */
const QREL = new Map();
function qRel(k, y) {
  const key = k + "|" + (y || "") + "|" + QSET.n; if (QREL.has(key)) return QREL.get(key);
  let rel = null; QT.dim[k].forEach((g, x) => { rel = vadd(rel, y ? qv(QT.cross[k].get(x + "|" + y)) : qv(g)); });
  QREL.set(key, rel); return rel;
}
/* the tickets of a dimension's values; "__rest" is everything the released values do not hold */
function qDimVec(k, vals) {
  const m = QT.dim[k]; if (!m) return null;
  let v = null; vals.forEach(x => { v = vadd(v, x === "__rest" ? vsub(qv(Q.overall), qRel(k)) : qv(m.get(x))); });
  return v;
}
/* the same within a set of years, from the value-by-year cells; a cell under the floor is missing, not zero */
function qCrossVec(k, vals, years) {
  const c = QT.cross[k]; if (!c || !c.size) return null;
  let v = null, missing = false;
  years.forEach(y => {
    const yAll = qv(QT.year.get(y)); if (!yAll) { missing = true; return; }
    vals.forEach(x => { if (x === "__rest") v = vadd(v, vsub(yAll, qRel(k, y))); else if (c.has(x + "|" + y)) v = vadd(v, qv(c.get(x + "|" + y))); else missing = true; });
  });
  return v ? { v, missing } : null;
}
const qEmpty = () => ({ p: 0, z: 0, f: Object.fromEntries(QF.map(f => [f, 0])), exact: true, known: true });
function qOf(sc) {
  const all = qv(Q.overall), parts = []; let unknown = false, yUsed = false, approx = false;
  const take = v => { if (v && v.n > 0) parts.push(v); else unknown = true; };
  const dimPart = (k, vals) => {
    if (!QT.dim[k]) { unknown = true; return; }
    if (sc.Y && !yUsed && QT.cross[k] && QT.cross[k].size) { const c = qCrossVec(k, vals, sc.Y); if (c && c.v.n > 0) { yUsed = true; parts.push(c.v); if (c.missing) approx = true; return; } }
    take(qDimVec(k, vals));
  };
  Object.keys(sc.dims).forEach(k => dimPart(k, [...sc.dims[k]]));
  /* a ticket can carry several Baugruppen: values overlap, so an exclusion is one part per value (combined like
     separate steps), and an inclusion of several values sums overlapping groups and is only an estimate */
  sc.multis.forEach(m => {
    if (!QT.dim[m.key]) { unknown = true; return; }
    if (m.neg) { m.vals.forEach(x => { const g = QT.dim[m.key].get(x); if (g) take(vsub(all, qv(g))); }); approx = true; }
    else { dimPart(m.key, m.vals); if (m.vals.length > 1) approx = true; }
  });
  if (sc.Y && !yUsed) { let v = null; sc.Y.forEach(y => { v = vadd(v, qv(QT.year.get(y))); }); take(v); }
  sc.gates.forEach(g => { if (!QF.includes(g.id) || !Q.by_field || !Q.by_field[g.id]) { unknown = true; return; } const fv = qv(Q.by_field[g.id]); take(g.neg ? vsub(all, fv) : fv); });
  if (sc.flags.length || sc.terms.length) unknown = true;
  const rate = k => {
    if (!all.n) return 0;
    const G = all[k] / all.n, rs = parts.map(p => p[k] / p.n);
    if (!rs.length) return G;
    if (G <= 0) return 0;
    return clamp01(rs.reduce((a, b) => a * b, 1) / Math.pow(G, rs.length - 1));
  };
  const f = {}; QF.forEach(x => { f[x] = rate(x); });
  return { p: rate("r"), z: rate("z"), f, exact: !unknown && !approx && parts.length <= 1, known: !unknown };
}
/* models and Baugruppen that still hold at least one usable ticket after these steps */
const BREADTH = [["model", "models", "model"], ["baug", "Baugruppen", "Baugruppe"]];
function breadthOf(steps) {
  if (!Q) return null;
  const key = JSON.stringify(steps) + "|" + QSET.n; if (BCACHE.has(key)) return BCACHE.get(key);
  if (BCACHE.size > 5000) BCACHE.clear();
  const out = {};
  BREADTH.forEach(([k, name, one]) => {
    if (!DIMS[k] || !QT.dim[k]) return;
    const vals = DIMS[k].values.map(x => x.v).filter(v => QT.dim[k].has(v) && qv(QT.dim[k].get(v)).r > 0);
    const kept = new Set(vals.filter(v => { const p = profile(steps.concat({ t: "d", dim: k, mode: "i", vals: [v] })); return p.n.est * p.q.p >= 0.5; }));
    out[k] = { name, one, kept: kept.size, of: vals.length, lost: vals.filter(v => !kept.has(v)) };
  });
  BCACHE.set(key, out); return out;
}
/* ---------- the joint quality cube (spec 2026-10-16, stage 2) ----------
   The report's quality.cube holds every combination of up to three of category, Baugruppe, model and a
   gate pattern (error code, description, serial present), each cell floored at k. The steps of a path
   that are cube axes (category, model, Baugruppe, those three gates, "has a model id", "names a
   Baugruppe") are answered from the one cut that holds exactly those axes: exact when every matching
   cell was released (or the cut withheld nothing), otherwise a guaranteed range. Every other step keeps
   the independence estimate, applied as a correction: new = old(path) * cube(part) / old(part).
   Grades: "exact", "bounded" (a range from withheld cells, no independence assumption) or "estimated".
   A report without a cube gets none of this: the model answers exactly as it did before. */
const AXES = ["cat", "baug", "model", "gates"], GATE_BIT = { fehlercode: 0, description: 1, serial: 2 };
const CUBE = (() => {
  const c = Q && Q.cube;
  if (!c || !Array.isArray(c.cuts)) return null;
  const cuts = new Map();
  c.cuts.forEach(cut => {
    const axes = String(cut.axes).split("+"), w = cut.withheld || {};
    const hidden = ((w.below_floor || {}).rows || 0) + ((w.entity_like || {}).rows || 0);
    /* a cell withheld for its name, not its size, can hold k or more tickets */
    const entity = ((w.entity_like || {}).distinct || 0) > 0;
    cuts.set(cut.axes, { axes, hidden, entity, cells: new Map((cut.cells || []).map(g => [axes.map(a => String(g[a])).join("|"), g])) });
  });
  const released = s => (((Q.by_dimension || {})[s] || {}).values || []).map(e => String(e.value)).filter(v => v !== "_other" && v !== "_none").concat(["_other", "_none"]);
  const U = { cat: released("categoryId"), baug: released("baugruppe"), model: released("model_id"), gates: [] };
  for (let i = 0; i < 8; i++) U.gates.push([4, 2, 1].map(b => (i & b ? "1" : "0")).join(""));
  /* without the floor a missing cell could be anything: a cube that cannot say how small its withheld
     cells are is not used at all (review finding: a floor of 1 made every missing cell empty) */
  const k = N("provenance.min_frequency");
  if (!(k > 0)) return null;
  return { cuts, U, k };
})();
const CUBE_DIMS = new Set(["cat", "model", "baug"]), CUBE_GATES = new Set(["fehlercode", "description", "serial", "model_id", "baugruppe"]);
const cubeStep = s => (s.t === "c" || (s.t === "d" && CUBE_DIMS.has(s.dim)) || (s.t === "g" && CUBE_GATES.has(s.f)));
/* the scope's cube constraints, per axis a set of axis values; null when the scope is not a cube question */
function cubeCon(sc) {
  const con = {}, toAxis = (k, vals) => {
    const out = new Set();
    for (const v of vals) {
      if (v === "__rest") {
        /* the rest is every cube value not named - true only while every named value is a cube value */
        const named = new Set(DIMS[k].values.map(x => x.v));
        if ([...named].some(x => !CUBE.U[k].includes(x))) return null;
        CUBE.U[k].forEach(a => { if (!named.has(a)) out.add(a); });
      }
      else if (CUBE.U[k].includes(v)) out.add(v); else return null;
    }
    return out;
  };
  for (const k of ["cat", "model"]) if (sc.dims[k]) { con[k] = toAxis(k, [...sc.dims[k]]); if (!con[k]) return null; }
  let pats = CUBE.U.gates;
  for (const g of sc.gates) {
    if (g.id in GATE_BIT) pats = pats.filter(p => (p[GATE_BIT[g.id]] === "1") !== g.neg);
    else if (g.id === "model_id") { const m = con.model || new Set(CUBE.U.model); con.model = new Set([...m].filter(v => (v === "_none") === g.neg)); }
  }
  if (pats.length < CUBE.U.gates.length) con.gates = new Set(pats);
  const inc = [], exc = new Set();
  for (const m of sc.multis) {
    if (m.key !== "baug") continue;
    const vals = toAxis("baug", m.vals); if (!vals) return null;
    if (m.neg) vals.forEach(v => exc.add(v)); else inc.push(vals);
  }
  const bg = sc.gates.find(g => g.id === "baugruppe");
  if (bg) { if (bg.neg) inc.push(new Set(["_none"])); else exc.add("_none"); }
  if (inc.length > 1 || (inc.length && exc.size)) return null;
  if (inc.length) con.baug = { inc: inc[0] }; else if (exc.size) con.baug = { exc };
  return con;
}
/* an interval vector: lo and hi per component (tickets, usable at N, noise, field fills) */
const ivZero = () => ({ lo: Object.fromEntries(QK.map(k => [k, 0])), hi: Object.fromEntries(QK.map(k => [k, 0])) });
const ivOf = v => ({ lo: { ...v }, hi: { ...v } });
const ivAdd = (a, b) => ({ lo: Object.fromEntries(QK.map(k => [k, a.lo[k] + b.lo[k]])), hi: Object.fromEntries(QK.map(k => [k, a.hi[k] + b.hi[k]])) });
/* the sum over every combination of the given axis-value sets in one cut; a missing combination is empty
   when the cut withheld nothing, otherwise anything below k, and all of them together at most what the
   cut withheld */
function cutSum(axes, sets) {
  if (!axes.length) return ivOf(qv(Q.overall));
  const cut = CUBE.cuts.get(axes.join("+")); if (!cut) return null;
  let iv = ivZero(), missing = 0;
  const walk = (i, key) => {
    if (i === axes.length) { const g = cut.cells.get(key.join("|")); if (g) iv = ivAdd(iv, ivOf(qv(g))); else missing += 1; return; }
    sets[i].forEach(v => walk(i + 1, key.concat(v)));
  };
  walk(0, []);
  const slack = cut.entity ? cut.hidden : Math.min(missing * (CUBE.k - 1), cut.hidden);
  if (slack > 0) QK.forEach(k => { iv.hi[k] += slack; });
  return iv;
}
/* the cube's answer for a set of constraints, or null when no cut holds them (four axes) */
function cubeAnswer(con) {
  const plain = AXES.filter(a => a !== "baug" && con[a]), sets = a => [...con[a]];
  if (!con.baug) return plain.length ? cutSum(plain, plain.map(sets)) : null;
  const axes = AXES.filter(a => con[a]); if (axes.length > 3) return null;
  const withB = v => cutSum(axes, axes.map(a => (a === "baug" ? [v] : sets(a))));
  if (con.baug.inc) {
    const parts = [...con.baug.inc].map(withB); if (parts.some(p => !p)) return null;
    if (parts.length === 1) return parts[0];
    /* a ticket can carry several Baugruppen: the union is at least the largest part and at most their sum */
    const cap = cutSum(plain, plain.map(sets)), lo = {}, hi = {};
    QK.forEach(k => { lo[k] = Math.max(...parts.map(p => p.lo[k])); hi[k] = Math.min(sum(parts, p => p.hi[k]), cap ? cap.hi[k] : Infinity); });
    return { lo, hi };
  }
  const all = cutSum(plain, plain.map(sets)), gone = [...con.baug.exc].map(withB); if (!all || gone.some(p => !p)) return null;
  const lo = {}, hi = {};
  QK.forEach(k => { lo[k] = Math.max(0, all.lo[k] - sum(gone, p => p.hi[k])); hi[k] = Math.max(lo[k], all.hi[k] - Math.max(0, ...gone.map(p => p.lo[k]))); });
  return { lo, hi };
}
const RANK = { low: true };
function setRank(low) { RANK.low = !!low; }
/* what verdicts and suggestions rank on: the worst case while there is a cube, the estimate otherwise.
   The worst-case share is the guaranteed usable tickets over the most tickets the path can hold, so it
   never exceeds the true share (a lower bound over a lower bound could). */
function rankOf(pr) {
  if (!(CUBE && RANK.low)) { const n = pr.n.est, r = pr.q ? pr.q.r : 0; return { n, r, p: n > 0 ? r / n : 0 }; }
  const r = pr.q ? pr.q.rlo : 0;
  return { n: pr.n.lo, r, p: pr.n.hi > 0 ? r / pr.n.hi : 0 };
}
/* ---------- (MODEL-END) ---------- */
