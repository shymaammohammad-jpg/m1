import React, { useEffect, useRef, useState } from "react";
import {
  AlertCircle, ArrowLeft, BookOpen, Check, CheckCircle2, ChevronDown,
  Download, ExternalLink, FileText, Loader2, Play, Settings2, ShieldCheck,
  Sparkles, Square, Trash2, Upload, X,
} from "lucide-react";
import "./auto-audit.css";

const STEP_NAMES = [
  ["upload", "قراءة العقد والأوليات"], ["year", "تحديد التعليمات النافذة"],
  ["diwan", "فحص إعمام الديوان"], ["cabinet", "فحص قرارات مجلس الوزراء"],
  ["structure", "تنفيذ برنامج التدقيق"], ["quick", "إعداد الفحص السريع"],
  ["standard", "تدقيق الوثائق القياسية"], ["blacklist", "فحص القوائم السوداء"],
  ["report", "مراجعة الأدلة وإعداد التقرير"],
];
const ACTIVE = new Set(["queued", "running"]);
const TERMINAL = new Set(["completed", "failed", "cancelled", "interrupted"]);
const PROVIDER_NAMES = { ollama: "نموذج محلي", openai: "OpenAI", gemini: "Gemini" };

const DEFAULTS = {
  gemini: { model: "gemini-2.5-flash", base_url: "https://generativelanguage.googleapis.com/v1beta" },
  openai: { model: "gpt-5.2", base_url: "https://api.openai.com/v1" },
  ollama: { model: "qwen2.5:3b", base_url: "http://127.0.0.1:11434" },
};
const NUMBER = (value) => new Intl.NumberFormat("ar-IQ").format(value || 0);
const TEXT = (value) => {
  if (value == null) return "";
  if (typeof value === "object") return String(value.value ?? value.note ?? value.title ?? value.message ?? value.description ?? value.reason ?? value.name ?? "");
  return String(value);
};
async function request(path, options = {}) {
  const settings = { ...options };
  if (settings.body && !(settings.body instanceof FormData)) {
    settings.body = JSON.stringify(settings.body);
    settings.headers = { "Content-Type": "application/json", ...settings.headers };
  }
  let response;
  try { response = await fetch("/api" + path, settings); }
  catch (error) {
    if (error.name === "AbortError") throw error;
    throw Error("تعذّر الاتصال بالخادم. تحقق من تشغيل رقيب.");
  }
  let body = null;
  try { body = await response.json(); } catch { /* A non-JSON failure remains a visible failure. */ }
  if (!response.ok) {
    const detail = body?.detail ?? body?.message;
    const message = Array.isArray(detail) ? detail.map((item) => item.msg || "تحقق من البيانات").join("، ") :
      typeof detail === "string" ? detail : detail?.message || "تعذّر تنفيذ الطلب. أعد المحاولة.";
    const error = Error(message); error.status = response.status; throw error;
  }
  return body;
}

function useSettings(version) {
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    request("/ai/settings", { signal: controller.signal })
      .then((data) => { setSettings(data); setError(""); })
      .catch((failure) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [version]);
  return { settings, error };
}

function ProviderNotice({ settings }) {
  return <p className="ai-provider-notice"><ShieldCheck size={17} />
    {settings?.provider && settings.provider !== "ollama"
      ? `عند بدء التدقيق، تُرسل نصوص العقد وأولياته والمراجع اللازمة، وقد تُرسل صور الصفحات غير المقروءة، إلى ${PROVIDER_NAMES[settings.provider]} باستخدام مفتاحك. تخضع البيانات لشروط المزوّد؛ المعالجة السحابية تحتاج الإنترنت وحصة استخدام متاحة.`
      : "يبقى تحليل العقد وأولياته على الحاسبة عبر Ollama، دون مفتاح API. يحتاج الاستعلام عن القوائم السوداء إلى الاتصال بموقع الوزارة."}
  </p>;
}

function LocalSetupNote({ compact = false }) {
  return <aside className="ai-local-setup">
    <h3>إعداد محلي للحاسبة بذاكرة 8 غيغابايت</h3>
    <p>لأول مرة، ثبّت <a href="https://ollama.com/download/windows" target="_blank" rel="noreferrer">Ollama</a>، ثم شغّل <code dir="ltr">setup_local_ai_windows.bat</code> من مجلد رقيب. يجهّز النموذج الخفيف <code dir="ltr">qwen2.5:3b</code> وقراءة المستندات المصوّرة محليًا.</p>
    {!compact && <p>يتطلب تنزيل النموذج وملفات القراءة الإنترنت أثناء الإعداد. بعد ذلك يجري التحليل على جهازك؛ قد تستغرق العقود الكبيرة وقتًا، وتظل النتائج غير المثبتة غير محسومة.</p>}
  </aside>;
}

export function AISettingsDialog({ Modal, onClose, onSaved, notify }) {
  const [values, setValues] = useState({ provider: "ollama", ...DEFAULTS.ollama, api_key: "" });
  const [saved, setSaved] = useState(null);
  const [clearKey, setClearKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [test, setTest] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    request("/ai/settings", { signal: controller.signal }).then((data) => {
      setSaved(data); setValues({ ...data, api_key: "" });
    }).catch((failure) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);
  function changeProvider(provider) {
    setValues((current) => ({ ...current, provider, ...DEFAULTS[provider], api_key: "" }));
    setClearKey(false); setTest(null); setError("");
  }
  async function save(runTest) {
    setBusy(true); setError(""); setTest(null);
    const payload = { provider: values.provider, model: values.model.trim(), base_url: values.base_url.trim() };
    if (!clearKey && values.api_key.trim()) payload.api_key = values.api_key.trim();
    if (clearKey) payload.clear_api_key = true;
    try {
      const result = await request("/ai/settings", { method: "PUT", body: payload });
      setSaved(result); setValues({ ...result, api_key: "" }); setClearKey(false); onSaved?.(result);
      if (runTest) {
        const connection = await request("/ai/test", { method: "POST" });
        setTest(connection);
        if (!connection?.ok) setError(connection?.message || "لم ينجح اختبار الاتصال.");
      } else { notify?.("تم حفظ إعدادات الذكاء الاصطناعي."); onClose(); }
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  return <Modal title={values.provider !== "ollama" ? `إعداد خدمة ${PROVIDER_NAMES[values.provider]}` : "إعداد الذكاء الاصطناعي المحلي"} description="يُحفظ الإعداد مرة واحدة، ثم يبدأ التدقيق برفع المستندات." onClose={() => !busy && onClose()}>
    <div className="ai-settings-content">
      {loading ? <div className="ai-loading"><Loader2 className="spin" /> جارٍ قراءة الإعدادات…</div> : <>
        <label className="ai-field">طريقة المعالجة
          <select aria-label="طريقة المعالجة" value={values.provider} onChange={(event) => changeProvider(event.target.value)} disabled={busy}>
            <option value="gemini">Gemini — سحابي، قد تتوفر حصة مجانية</option><option value="openai">OpenAI — سحابي برصيد API</option><option value="ollama">Ollama — نموذج محلي على الحاسبة</option>
          </select>
        </label>
        <label className="ai-field">اسم النموذج
          <input aria-label="اسم النموذج" dir="ltr" value={values.model || ""} onChange={(event) => setValues({ ...values, model: event.target.value })} disabled={busy} placeholder={DEFAULTS[values.provider]?.model} />
        </label>
        {values.provider === "ollama" ? <><label className="ai-field">عنوان Ollama على جهازك
          <input aria-label="عنوان Ollama على جهازك" dir="ltr" value={values.base_url || ""} onChange={(event) => setValues({ ...values, base_url: event.target.value })} disabled={busy} placeholder="http://127.0.0.1:11434" />
          <small>يقبل البرنامج عنوانًا محليًا على الجهاز الذي يشغّل خدمة رقيب. لا يحتاج هذا الخيار إلى مفتاح API.</small>
        </label><LocalSetupNote compact /></> : <>
          <label className="ai-field">مفتاح {PROVIDER_NAMES[values.provider]}
            <input aria-label={`مفتاح ${PROVIDER_NAMES[values.provider]}`} type="password" dir="ltr" autoComplete="new-password" value={values.api_key} onChange={(event) => setValues({ ...values, api_key: event.target.value })} disabled={busy || clearKey} placeholder={saved?.provider === values.provider && saved?.key_configured ? "يوجد مفتاح محفوظ؛ اتركه فارغًا للاحتفاظ به" : "أدخل المفتاح هنا فقط"} />
            <small>لا يظهر المفتاح المحفوظ في الواجهة ولا يُرسل ضمن التقارير. لا تضعه داخل ملفات العقد.</small>
          </label>
          {saved?.provider === values.provider && saved?.key_source === "environment" ? <p className="ai-small-note">المفتاح الحالي مأخوذ من إعدادات الجهاز؛ له الأولوية على المفتاح المحفوظ داخل البرنامج.</p> : saved?.provider === values.provider && saved?.key_configured &&
            <label className="ai-checkbox"><input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} disabled={busy} /> حذف المفتاح المحفوظ عند الحفظ</label>}
        </>}
        {values.provider !== "ollama" && <aside className="ai-local-setup">
          <h3>إعداد API السحابي</h3>
          <p>اختر نموذجًا متاحًا لحسابك، وأدخل مفتاحك ثم اضغط «حفظ واختبار الاتصال». لا تحتاج إلى تشغيل Ollama أو تنزيل نموذج لهذا الخيار. تبقى قراءة المستندات محلية قبل إرسال الأدلة اللازمة للتحليل.</p>
          {values.provider === "gemini" ? <p><a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">إنشاء مفتاح Gemini</a> · <a href="https://ai.google.dev/gemini-api/docs/pricing" target="_blank" rel="noreferrer">الأسعار وحدود الخطة</a> · <a href="https://ai.google.dev/gemini-api/terms" target="_blank" rel="noreferrer">شروط البيانات</a>. قد تتوفر حصة مجانية حسب النموذج والبلد والحساب؛ لا توجد مجانية غير محدودة مضمونة. راجع استخدام البيانات قبل إرسال عقود سرية.</p> : <p><a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">إنشاء مفتاح OpenAI</a>. رصيد API منفصل عن اشتراك تطبيق المحادثة.</p>}
        </aside>}
        <ProviderNotice settings={values} />
        {saved && <p className="ai-settings-status"><span className={test?.ok ? "ai-dot ready" : "ai-dot"} />{saved.configured ? "الإعداد محفوظ؛ نجاح اختبار الاتصال يؤكد أن النموذج يعمل." : "يلزم إكمال إعداد الخدمة قبل بدء التدقيق."}</p>}
      </>}
      {error && <p role="alert" className="ai-error"><AlertCircle size={17} />{error}</p>}
      {test?.ok && <p role="status" className="ai-success"><CheckCircle2 size={17} />{test.message || "نجح الاتصال بالنموذج."}</p>}
      <div className="modal-actions ai-settings-actions">
        <button className="btn outline" onClick={() => save(true)} disabled={loading || busy || !values.model?.trim()}>{busy ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />} حفظ واختبار الاتصال</button>
        <button className="btn primary" onClick={() => save(false)} disabled={loading || busy || !values.model?.trim()}>حفظ الإعدادات</button>
      </div>
    </div>
  </Modal>;
}

export function AutoAuditHome({ onCreated, onSettings, settingsVersion = 0 }) {
  const { settings, error: settingsError } = useSettings(settingsVersion);
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const picker = useRef(null);
  const uploadController = useRef(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; uploadController.current?.abort(); };
  }, []);
  function selectFiles(incoming) {
    setError("");
    const next = [...files];
    for (const file of Array.from(incoming || [])) {
      if (file.size > 100 * 1024 * 1024) { setError(`الملف «${file.name}» يتجاوز 100 ميغابايت.`); return; }
      if (!next.some((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) next.push(file);
    }
    if (next.length > 30) { setError("يمكن رفع 30 ملفًا في الطلب الواحد. يمكنك جمع الأوليات في ZIP."); return; }
    if (next.reduce((sum, file) => sum + file.size, 0) > 250 * 1024 * 1024) { setError("إجمالي الملفات يتجاوز 250 ميغابايت."); return; }
    setFiles(next);
    if (picker.current) picker.current.value = "";
  }
  async function start() {
    if (!files.length || busy || !settings?.configured) return;
    setBusy(true); setError("");
    const body = new FormData(); files.forEach((file) => body.append("files", file));
    uploadController.current = new AbortController();
    try {
      const response = await request("/ai/audits", { method: "POST", body, signal: uploadController.current.signal });
      if (!mounted.current) return;
      if (!response?.case_id) throw Error("لم يُنشأ ملف التدقيق. أعد المحاولة.");
      await onCreated(response.case_id, response.job);
      if (mounted.current) setFiles([]);
    } catch (failure) { if (mounted.current && failure.name !== "AbortError") setError(failure.message); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <section className="panel ai-upload-panel" id="automatic-audit-upload" aria-labelledby="automatic-audit-title">
    <div className="ai-upload-heading"><span className="ai-hero-icon"><Sparkles size={29} /></span><div>
      <div className="eyebrow">التدقيق بالذكاء الاصطناعي</div><h2 id="automatic-audit-title">ارفع العقد وأولياته، ورقيب يتولى الفحص</h2>
      <p>يقرأ المستندات، يستخرج بيانات العقد، ينفّذ خطوات التدقيق التسع ويُعدّ التقرير مع أدلته.</p>
    </div><button type="button" className="btn outline small" onClick={onSettings}><Settings2 size={16} />إعداد الذكاء الاصطناعي</button></div>
    <div className="ai-service-line"><span className="ai-dot" />
      {settings ? settings.configured ? `الإعداد المحفوظ: ${PROVIDER_NAMES[settings.provider] || settings.provider} · ${settings.model}` : "أكمل إعداد الذكاء الاصطناعي مرة واحدة للبدء" : "جارٍ قراءة إعداد الخدمة…"}
    </div>
    {settings?.provider === "ollama" && <aside className="ai-local-setup"><h3>التبديل إلى API سحابي</h3><p>يمكنك اختيار Gemini أو OpenAI بدل النموذج المحلي. تُرسل المستندات اللازمة إلى المزوّد عند بدء التدقيق.</p><button className="btn outline" onClick={onSettings}><Settings2 size={16} /> إعداد API السحابي</button></aside>}
    <div className={"ai-dropzone " + (dragging ? "dragging" : "")} onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); if (!busy) selectFiles(event.dataTransfer.files); }}>
      <Upload size={29} strokeWidth={1.5} /><h3>اسحب ملف العقد وأولياته هنا</h3><p>يمكنك اختيار عدة ملفات أو أرشيف ZIP؛ يصنّف رقيب المستندات تلقائيًا.</p>
      <button type="button" className="btn outline" onClick={() => picker.current?.click()} disabled={busy}><FileText size={16} /> اختيار الملفات</button>
      <input ref={picker} className="ai-file-input" aria-label="ملف العقد والأوليات" type="file" multiple accept=".pdf,.docx,.txt,.csv,.zip,.png,.jpg,.jpeg,.tif,.tiff,.webp" onChange={(event) => selectFiles(event.target.files)} disabled={busy} />
      <small>PDF وWord والصور والنصوص وZIP · حتى 30 ملفًا، و100 ميغابايت للملف</small>
    </div>
    {files.length > 0 && <ul className="ai-upload-files">{files.map((file, index) => <li key={`${file.name}-${file.size}-${file.lastModified}`}><FileText size={17} /><span>{file.name}<small>{NUMBER(Math.max(1, Math.round(file.size / 1024)))} كيلوبايت</small></span><button type="button" className="icon-btn" aria-label={`إزالة ${file.name}`} onClick={() => setFiles((selected) => selected.filter((_, item) => item !== index))} disabled={busy}><X size={17} /></button></li>)}</ul>}
    {(error || settingsError) && <p role="alert" className="ai-error"><AlertCircle size={17} />{error || settingsError}</p>}
    <ProviderNotice settings={settings} />
    <div className="ai-start-line"><p>تظهر النتائج غير المحسومة والمستندات الناقصة صراحةً، ويرتبط كل استنتاج بالمصدر والصفحة.</p>
      <button type="button" className="btn primary ai-start" disabled={busy || !files.length || !settings?.configured} onClick={start}>{busy ? <Loader2 size={19} className="spin" /> : <Sparkles size={19} />}{busy ? "جارٍ رفع المستندات وبدء التدقيق…" : "بدء التدقيق الآلي"}<ArrowLeft size={17} /></button>
    </div>
  </section>;
}

function Citations({ items, documents, title }) {
  if (!Array.isArray(items) || !items.length) return null;
  return <div className="ai-citations"><h4>{title}</h4>{items.map((citation, index) => {
    const id = citation.document_id || citation.reference_id || citation.evidence_document_id;
    const document = documents.find((item) => item.id === id);
    const rawPage = citation.page ?? citation.page_number ?? citation.evidence_page;
    const page = /^\d+$/.test(String(rawPage || "")) && Number(rawPage) > 0 ? Number(rawPage) : null;
    const logical = document?.pagination === "logical";
    return <div className="ai-citation" key={`${id || "source"}-${page || index}-${index}`}>
      <div>{document ? <a href={`/api/documents/${encodeURIComponent(id)}/file${page && !logical ? `#page=${page}` : ""}`} target="_blank" rel="noreferrer"><FileText size={14} />{citation.name || citation.document_name || document.name || "فتح مستند المصدر"}{page ? ` · ${logical ? "مقطع نصي" : "ص"} ${NUMBER(page)}` : ""}<ExternalLink size={12} /></a> : <span>{citation.name || citation.document_name || "مصدر غير محدد"} — الأصل غير متاح ضمن هذا الملف</span>}</div>
      {citation.quote && <blockquote dir="auto">{citation.quote}</blockquote>}
    </div>;
  })}</div>;
}

export function AutoAuditCase({ current, references = [], schema = [], onUpdate, onReview, onSettings, settingsVersion = 0 }) {
  const { settings } = useSettings(settingsVersion);
  const [job, setJob] = useState(current.automation?.job || null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const completed = useRef("");
  const updateRef = useRef(onUpdate);
  useEffect(() => { updateRef.current = onUpdate; }, [onUpdate]);
  useEffect(() => {
    let mounted = true; let timer; const controller = new AbortController();
    completed.current = ""; setJob(current.automation?.job || null); setError("");
    async function poll() {
      try {
        const response = await request(`/cases/${current.id}/ai-audit`, { signal: controller.signal });
        const next = response?.job || response;
        if (!mounted) return;
        setJob(next?.status ? next : null); setError("");
        if (next && TERMINAL.has(next.status) && completed.current !== `${next.id}-${next.status}`) {
          completed.current = `${next.id}-${next.status}`;
          const detail = await request(`/cases/${current.id}`, { signal: controller.signal });
          if (mounted) updateRef.current(detail);
        }
        if (mounted && next && ACTIVE.has(next.status)) timer = setTimeout(poll, 1500);
      } catch (failure) {
        if (!mounted || controller.signal.aborted) return;
        if (failure.status === 404) {
          setJob(null);
          if (current.automation?.job?.id) setError("لم يعد تشغيل التدقيق محفوظًا. أعد التدقيق على مستندات الملف الحالية.");
        } else { setError(failure.message); timer = setTimeout(poll, 4000); }
      }
    }
    poll();
    return () => { mounted = false; clearTimeout(timer); controller.abort(); };
  }, [current.id, current.automation?.job?.id]);
  async function refreshCase() { const value = await request(`/cases/${current.id}`); updateRef.current(value); return value; }
  async function run() {
    setBusy(true); setError("");
    try {
      const response = await request(`/cases/${current.id}/ai-audit`, { method: "POST" });
      const next = response?.job || response; setJob(next); completed.current = "";
      // Refreshing gives the polling effect a new job ID, without overlapping requests.
      await refreshCase();
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  async function cancel() {
    setBusy(true); setError("");
    try { const value = await request(`/cases/${current.id}/ai-audit/cancel`, { method: "POST" }); setJob(value?.job || value); await refreshCase(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  const automation = current.automation || {};
  const currentRun = automation.job?.id === job?.id;
  const running = ACTIVE.has(job?.status);
  const findings = currentRun && Array.isArray(automation.findings) ? automation.findings : [];
  const stages = Array.isArray(job?.stages) ? job.stages : [];
  const documents = [...(current.documents || []), ...references];
  const summary = currentRun ? TEXT(automation.summary) : "";
  const progress = Math.max(0, Math.min(100, Number(job?.progress) || 0));
  const labels = { pass: "مستوفٍ وفق الأدلة", fail: "ملاحظة / مخالفة", not_applicable: "غير منطبق", uncertain: "غير محسوم", pending: "لم يُحسم" };
  const missing = currentRun ? automation.missing_documents || [] : [];
  const conflicts = currentRun ? automation.conflicts || [] : [];
  const facts = currentRun && automation.facts && typeof automation.facts === "object" ? automation.facts : {};
  const factNames = { title: "موضوع العقد", contract_number: "رقم العقد", contractor: "المتعاقد", entity: "الجهة المتعاقدة", contract_date: "تاريخ العقد", amount: "مبلغ العقد", currency: "العملة", contract_type: "نوع العقد" };
  const reportReady = currentRun && job?.status === "completed" && !automation.stale && !job?.stale;
  return <div className="ai-case-view">
    <section className="panel ai-job-panel">
      <div className="ai-job-heading"><span className="ai-hero-icon"><Sparkles size={26} /></span><div><div className="eyebrow">مسار التدقيق التلقائي</div><h2>{running ? "رقيب يفحص المستندات الآن" : job?.status === "completed" ? "اكتمل التدقيق الآلي" : job?.status === "cancelled" ? "أُوقف التدقيق" : job?.status === "interrupted" ? "توقف التشغيل قبل الاكتمال" : job?.status === "failed" ? "تعذّر إكمال التدقيق" : "ابدأ التدقيق بالذكاء الاصطناعي"}</h2><p>{job?.model ? `${PROVIDER_NAMES[job.provider] || job.provider} · ${job.model}` : "ينفّذ الخطوات التسع من المستندات دون تعبئة نتائج الفحص يدويًا."}</p></div>
        <div className="ai-job-actions">{running ? <button className="btn outline small" onClick={cancel} disabled={busy}><Square size={15} />إيقاف التدقيق</button> : <button className="btn primary" onClick={run} disabled={busy || !current.documents?.length || !settings?.configured}>{busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}{job ? "إعادة التدقيق" : "بدء التدقيق الآلي"}</button>}<button className="icon-btn" onClick={onSettings} title="إعداد الذكاء الاصطناعي" aria-label="إعداد الذكاء الاصطناعي"><Settings2 size={19} /></button></div>
      </div>
      {!settings?.configured && <p className="ai-small-note">أكمل <button className="inline-link" onClick={onSettings}>إعداد خدمة الذكاء الاصطناعي</button> قبل بدء التدقيق.</p>}
      {job && <><div className="ai-progress-heading"><span>{running ? "تقدّم المعالجة" : "المعالجة المنجزة"}</span><strong>{NUMBER(progress)}٪</strong></div><div className="ai-progress" role="progressbar" aria-label="تقدم التدقيق الآلي" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${progress}%` }} /></div></>}
      <ol className="ai-stages">{STEP_NAMES.map(([id, title], index) => {
        const stage = stages.find((item) => item.id === id);
        const state = stage?.status || (job?.stage === id && running ? "running" : "pending");
        return <li className={state} key={id}><span className="ai-stage-number">{state === "running" ? <Loader2 className="spin" size={16} /> : state === "completed" ? <Check size={16} /> : ["failed", "warning"].includes(state) ? <AlertCircle size={16} /> : NUMBER(index + 1)}</span><div><strong>{title}</strong><small>{stage?.message || (state === "running" ? "جارٍ الفحص…" : state === "completed" ? "اكتمل" : state === "pending" ? "بانتظار المعالجة" : "راجع نتيجة هذه المرحلة")}</small></div></li>;
      })}</ol>
      {(error || job?.error) && <p role="alert" className="ai-error"><AlertCircle size={17} />{error || TEXT(job.error)}</p>}
      {job?.status === "failed" && settings?.provider === "ollama" && <LocalSetupNote compact />}
      {automation.stale && <p role="alert" className="ai-error"><AlertCircle size={17} />تغيّرت المستندات أو البيانات بعد هذا التدقيق. أعد التدقيق لإصدار تقرير يستند إلى آخر نسخة.</p>}
      {!job && <ProviderNotice settings={settings} />}
    </section>
    {Object.keys(facts).length > 0 && <section className="panel ai-extracted-facts"><h2>بيانات العقد المستخرجة من الأدلة</h2><p>تظهر هنا القيم التي ثبتت في هذا التشغيل، مع اقتباساتها.</p>{Object.entries(facts).filter(([, fact]) => TEXT(fact)).map(([key, fact]) => <details key={key}><summary><span>{factNames[key] || key}</span><strong dir="auto">{TEXT(fact)}</strong><ChevronDown size={15} /></summary><Citations title="مصدر القيمة" items={fact.citations} documents={documents} /></details>)}</section>}
    {(summary || findings.length > 0) && <section className="panel ai-results-panel"><div className="ai-section-title"><div><h2>نتائج التدقيق وأسانيدها</h2><p>تُعرض الملاحظة مع دليلها، وتبقى المسائل غير المثبتة واضحة في التقرير.</p></div><button className="btn outline small" onClick={onReview}><BookOpen size={16} />المراجعة التفصيلية</button></div>
      {summary && <p className="ai-summary">{summary}</p>}
      <div className="ai-finding-stats">{[["pass", "نتائج مسندة"], ["fail", "ملاحظات"], ["uncertain", "مسائل غير محسومة"]].map(([status, title]) => <span key={status}><strong>{NUMBER(findings.filter((finding) => finding.status === status).length)}</strong>{title}</span>)}</div>
      {missing.length > 0 && <div className="ai-issue-box"><h3><AlertCircle size={17} />المستندات أو المعلومات الناقصة</h3><ul>{missing.map((item, index) => <li key={index}>{TEXT(item)}</li>)}</ul></div>}
      {conflicts.length > 0 && <div className="ai-issue-box"><h3><AlertCircle size={17} />تعارضات تستدعي الانتباه</h3><ul>{conflicts.map((item, index) => <li key={index}>{TEXT(item)}</li>)}</ul></div>}
      <div className="ai-findings">{findings.map((finding, index) => <details className={"ai-finding " + finding.status} key={finding.id || index} open={finding.status === "fail" || finding.status === "uncertain"}><summary><span><b>{NUMBER(index + 1)}</b>{finding.title || finding.id || "نتيجة فحص"}</span><span className={"ai-result-badge " + finding.status}>{labels[finding.status] || "غير محسوم"}</span><ChevronDown size={15} /></summary><div className="ai-finding-body"><p>{finding.note || finding.reason || "لم يُوثق تفسير كافٍ لهذه النتيجة."}</p>
        {finding.validation_issues?.length > 0 && <ul className="ai-validation-issues">{finding.validation_issues.map((item, issueIndex) => <li key={issueIndex}>{TEXT(item)}</li>)}</ul>}
        <Citations title="الأدلة من ملف العقد" items={finding.evidence} documents={documents} /><Citations title="السند المرجعي" items={finding.references} documents={documents} />
      </div></details>)}</div>
    </section>}
    {currentRun && automation.quick_form && Object.keys(automation.quick_form).length > 0 && <section className="panel ai-quick-form"><h2>استمارة الفحص السريع — مُعدّة آليًا</h2>{schema.map((section) => <details key={section.id}><summary>{section.title}<ChevronDown size={15} /></summary><dl>{section.fields.filter((field) => TEXT(automation.quick_form[field.key])).map((field) => { const value = TEXT(automation.quick_form[field.key]); return <div key={field.key}><dt>{field.label}</dt><dd>{field.options?.find((option) => option.value === value)?.label || value}</dd></div>; })}</dl></details>)}</section>}
    {currentRun && automation.coverage?.length > 0 && <section className="panel ai-coverage"><h2>تغطية استخراج المستندات</h2><p className="ai-small-note">اكتمال استخراج الصفحات لا يثبت دقة كل رقم أو اكتمال التدقيق القانوني؛ تبقى التحفظات ظاهرة في النتائج.</p><ul>{automation.coverage.map((document, index) => <li key={document.document_id || index}><FileText size={16} /><span>{document.name || documents.find((item) => item.id === document.document_id)?.name || "مستند"}</span><small>{document.complete ? "اكتمل استخراج الصفحات" : "استخراج جزئي"}{document.page_count ? ` · ${NUMBER(document.page_count)} ${document.pagination === "logical" ? "مقطعًا نصيًا" : "صفحة"}` : ""}</small></li>)}</ul></section>}
    {currentRun && automation.limitations?.length > 0 && <section className="panel ai-limitations"><h2>حدود الفحص في هذا الملف</h2><ul>{automation.limitations.map((item, index) => <li key={index}>{TEXT(item)}</li>)}</ul></section>}
    <section className="panel ai-report-actions"><div><FileText size={27} /><div><h2>تقرير التدقيق الآلي</h2><p>{reportReady ? "يتضمن النتائج والأدلة والنواقص والمسائل غير المحسومة في ترتيب التقرير المعتمد." : "يُتاح التقرير بعد اكتمال التشغيل على النسخة الحالية من المستندات."}</p></div></div><div>
      {reportReady ? <><a className="btn outline" href={`/api/cases/${current.id}/ai-report.html`} target="_blank" rel="noreferrer"><ExternalLink size={16} />عرض التقرير</a><a className="btn primary" href={`/api/cases/${current.id}/ai-report.pdf`} target="_blank" rel="noreferrer"><Download size={17} />تنزيل PDF</a></> : <button className="btn primary" disabled><Download size={17} />التقرير قيد الإعداد</button>}
    </div></section>
  </div>;
}
