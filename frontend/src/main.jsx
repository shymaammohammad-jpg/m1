import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  Scale,
  LayoutDashboard,
  FolderOpen,
  BookOpen,
  Upload,
  CalendarDays,
  ShieldCheck,
  Landmark,
  Workflow,
  ClipboardCheck,
  Files,
  SearchCheck,
  FileText,
  ArrowLeft,
  ArrowRight,
  Plus,
  X,
  Check,
  ChevronDown,
  ExternalLink,
  Download,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Trash2,
  Eye,
  Pencil,
  Search,
  Menu,
  Info,
  RotateCw,
  Paperclip,
  Building2,
  Sparkles,
  Settings2,
} from "lucide-react";
import "./styles.css";
import { AISettingsDialog, AutoAuditHome, AutoAuditCase } from "./AutoAudit.jsx";
const STEPS = [
  [
    "upload",
    "العقد والأوليات",
    Upload,
    "اجمع مستندات العقد وأولياته في ملف تدقيق واحد.",
  ],
  [
    "year",
    "تعليمات سنة العقد",
    CalendarDays,
    "حدّد التعليمات المرتبطة بتاريخ العقد ووثّق المرجع المعتمد.",
  ],
  [
    "diwan",
    "إعمام ديوان الرقابة",
    ShieldCheck,
    "راجع نطاق إعمام الديوان وملاءمته الزمنية للعقد.",
  ],
  [
    "cabinet",
    "إعمام مجلس الوزراء",
    Landmark,
    "تحقق من القرار الرسمي وسريان أحكامه على الحالة.",
  ],
  [
    "structure",
    "الهيكلية وبرنامج التدقيق",
    Workflow,
    "نفّذ إجراءات البرنامج مع إسناد كل نتيجة إلى دليل.",
  ],
  [
    "quick",
    "استمارة الفحص السريع",
    ClipboardCheck,
    "أكمل الاستمارة الفعلية الواردة في المرجع المرفوع.",
  ],
  [
    "standard",
    "الوثائق القياسية",
    Files,
    "وثّق مراجعة وثائق المناقصة والتعاقد المعتمدة.",
  ],
  [
    "blacklist",
    "القوائم السوداء",
    SearchCheck,
    "راجع اسم المتعاقد في مصدر رسمي لوزارة التخطيط.",
  ],
  [
    "report",
    "التقرير النهائي",
    FileText,
    "راجع النتائج والأدلة ثم أخرج تقرير التدقيق.",
  ],
].map(([id, title, icon, desc]) => ({ id, title, icon, desc }));
const CATS = {
  contract: "ملف العقد",
  supporting: "الأوليات والمستندات",
  instructions: "تعليمات تنفيذ العقود",
  diwan: "إعمام الديوان",
  cabinet: "إعمام مجلس الوزراء",
  structure: "الهيكلية وبرنامج التدقيق",
  standard: "الوثائق القياسية",
  blacklist: "القوائم السوداء",
  report_template: "نموذج التقرير البشري",
};
const STATUS = {
  pending: "بانتظار الفحص",
  pass: "مستوفٍ",
  fail: "ملاحظة / مخالفة",
  not_applicable: "غير منطبق",
};
const BL = {
  pending: "لم يتم الفحص",
  possible_match: "تطابق محتمل — يحتاج مراجعة",
  confirmed_match: "تطابق مؤكد",
  cleared: "لم يظهر إدراج بعد المراجعة",
  unavailable: "المصدر غير متاح",
};
const N = (v) => new Intl.NumberFormat("ar-IQ").format(v || 0),
  D = (v) =>
    v
      ? new Intl.DateTimeFormat("ar-IQ", {
          timeZone: "Asia/Baghdad",
          day: "numeric",
          month: "short",
          year: "numeric",
        }).format(new Date(v))
      : "—";
const SIZE = (n) =>
  n >= 1048576
    ? `${(n / 1048576).toFixed(1)} م.ب`
    : `${Math.max(1, Math.round(n / 1024))} ك.ب`;
const TODAY = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Baghdad",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
function errorText(d) {
  if (typeof d === "string") return d;
  if (Array.isArray(d))
    return d.map((x) => x.msg || "تحقق من البيانات").join("، ");
  return (
    d?.blockers?.join("، ") ||
    d?.message ||
    "تعذّر تنفيذ العملية. يرجى المحاولة مرة أخرى."
  );
}
async function api(path, opts = {}) {
  opts = { ...opts };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { "Content-Type": "application/json", ...opts.headers };
    opts.body = JSON.stringify(opts.body);
  }
  let r;
  try {
    r = await fetch("/api" + path, opts);
  } catch {
    throw Error("تعذّر الاتصال بالخادم. تحقق من تشغيل الخدمة وأعد المحاولة.");
  }
  if (!r.ok) {
    let d;
    try {
      d = await r.json();
    } catch {}
    throw Error(errorText(d?.detail || d));
  }
  return r.status === 204 ? null : r.json();
}
function IButton({ title, children, ...p }) {
  return (
    <button className="icon-btn" title={title} aria-label={title} {...p}>
      {children}
    </button>
  );
}
function Badge({ status = "pending" }) {
  return (
    <span className={"badge " + status}>
      {status === "pass" ? (
        <Check size={12} />
      ) : status === "fail" ? (
        <AlertCircle size={12} />
      ) : (
        <i />
      )}
      {STATUS[status] || status}
    </span>
  );
}
function Notice({ children, title, tone = "info" }) {
  return (
    <div className={"notice " + tone}>
      <Info size={18} />
      <div>
        {title && <strong>{title}</strong>}
        {children}
      </div>
    </div>
  );
}
function Empty({ icon: Icon = FolderOpen, title, children, action }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={32} strokeWidth={1.3} />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
function Field({ label, required, children, hint }) {
  return (
    <label className="field">
      <span>
        {label}
        {required && <b> *</b>}
      </span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
function Modal({ title, description, onClose, children, wide = false }) {
  const ref = useRef();
  useEffect(() => {
    const prev = document.activeElement;
    ref.current?.focus();
    function key(e) {
      const dialogs = document.querySelectorAll(".modal");
      if (dialogs[dialogs.length - 1] !== ref.current) return;
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const nodes = ref.current?.querySelectorAll(
          "button:not(:disabled),input,textarea,select,a[href]",
        );
        if (!nodes?.length) return;
        let first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow =
        document.querySelectorAll(".modal").length > 1 ? "hidden" : "";
      prev?.focus?.();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => e.currentTarget === e.target && onClose()}
    >
      <section
        className={"modal " + (wide ? "wide" : "")}
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <div>
            <h2>{title}</h2>
            <p>{description}</p>
          </div>
          <IButton title="إغلاق" onClick={onClose}>
            <X size={20} />
          </IButton>
        </header>
        {children}
      </section>
    </div>
  );
}
function CaseForm({ initial, onSave, onClose }) {
  const [v, setV] = useState({
      title: "",
      contract_number: "",
      contractor: "",
      entity: "",
      contract_date: TODAY(),
      amount: "",
      currency: "IQD",
      ...initial,
    }),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      let body = Object.fromEntries(
        [
          "title",
          "contract_number",
          "contractor",
          "entity",
          "contract_date",
          "amount",
          "currency",
        ].map((k) => [k, v[k] || ""]),
      );
      onSave(
        await api(initial ? `/cases/${initial.id}` : "/cases", {
          method: initial ? "PATCH" : "POST",
          body,
        }),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const input = (k, type = "text", req = false) => (
    <input
      type={type}
      required={req}
      value={v[k] || ""}
      onChange={(e) => setV({ ...v, [k]: e.target.value })}
      {...(type === "date" ? { max: TODAY() } : {})}
    />
  );
  return (
    <Modal
      title={initial ? "تعديل بيانات العقد" : "بدء ملف تدقيق جديد"}
      description="أدخل البيانات الأساسية لربط المستندات والإجراءات بالعقد."
      onClose={onClose}
    >
      <form onSubmit={submit}>
        {initial && (
          <Notice tone="warning">
            تغيير البيانات الأساسية قد يعيد إجراءات الفحص إلى الانتظار للحفاظ
            على صلاحية نتائج التدقيق.
          </Notice>
        )}
        <div className="form-grid">
          <div className="span-2">
            <Field label="اسم العقد / المشروع" required>
              {input("title", "text", true)}
            </Field>
          </div>
          <Field label="رقم العقد" required>
            {input("contract_number", "text", true)}
          </Field>
          <Field label="تاريخ العقد" required>
            {input("contract_date", "date", true)}
          </Field>
          <Field label="اسم المتعاقد / الشركة" required>
            {input("contractor", "text", true)}
          </Field>
          <Field label="الجهة المتعاقدة" required>
            {input("entity", "text", true)}
          </Field>
          <Field label="مبلغ العقد" required>
            {input("amount", "text", true)}
          </Field>
          <Field label="العملة">
            <select
              value={v.currency}
              onChange={(e) => setV({ ...v, currency: e.target.value })}
            >
              <option value="IQD">دينار عراقي — IQD</option>
              <option value="USD">دولار أمريكي — USD</option>
              <option value="EUR">يورو — EUR</option>
            </select>
          </Field>
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button className="btn primary" disabled={busy}>
            {busy ? <Loader2 className="spin" size={17} /> : <Plus size={17} />}{" "}
            {initial ? "حفظ التعديلات" : "إنشاء ملف التدقيق"}
          </button>
          <button type="button" className="btn ghost" onClick={onClose}>
            إلغاء
          </button>
        </div>
      </form>
    </Modal>
  );
}
function UploadPanel({
  caseId,
  onUpdate,
  notify,
  category: defaultCat = "supporting",
  reference = false,
  onReference,
}) {
  const [category, setCategory] = useState(
      reference ? "instructions" : defaultCat,
    ),
    [files, setFiles] = useState([]),
    [busy, setBusy] = useState(false),
    [drag, setDrag] = useState(false),
    [year, setYear] = useState(""),
    [title, setTitle] = useState(""),
    [effective, setEffective] = useState(""),
    [sourceNumber, setSourceNumber] = useState("");
  const input = useRef();
  function select(list) {
    let arr = Array.from(list || []);
    if (arr.some((f) => f.size > 100 * 1024 * 1024)) {
      notify("حجم الملف يتجاوز 100 ميغابايت.", "error");
      return;
    }
    setFiles(reference ? arr.slice(0, 1) : arr);
  }
  async function upload() {
    setBusy(true);
    try {
      const f = new FormData();
      f.append("category", category);
      if (reference) {
        f.append("file", files[0]);
        if (year) f.append("reference_year", year);
        if (title) f.append("title", title);
        if (effective) f.append("effective_date", effective);
        if (sourceNumber) f.append("source_number", sourceNumber);
        onReference?.(await api("/references", { method: "POST", body: f }));
      } else {
        files.forEach((x) => f.append("files", x));
        onUpdate(
          await api(`/cases/${caseId}/documents`, { method: "POST", body: f }),
        );
      }
      setFiles([]);
      if (input.current) input.current.value = "";
      notify("تم رفع المستندات وحفظها بنجاح.");
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <div className="upload-options">
        <Field label="تصنيف المستند">
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {Object.entries(CATS)
              .filter(
                ([k]) => !reference || !["contract", "supporting"].includes(k),
              )
              .map(([k, v]) => (
                <option value={k} key={k}>
                  {v}
                </option>
              ))}
          </select>
        </Field>
        {reference && (
          <>
            <Field label="عنوان المرجع">
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="اختياري"
              />
            </Field>
            <Field label="سنة المرجع">
              <input
                type="number"
                min="1900"
                max="2100"
                value={year}
                onChange={(e) => setYear(e.target.value)}
                placeholder="اختياري"
              />
            </Field>
            <Field label="تاريخ النفاذ">
              <input
                type="date"
                value={effective}
                onChange={(e) => setEffective(e.target.value)}
              />
            </Field>
            <Field label="رقم المرجع / الكتاب">
              <input
                value={sourceNumber}
                onChange={(e) => setSourceNumber(e.target.value)}
                placeholder="اختياري"
              />
            </Field>
          </>
        )}
      </div>
      <div
        className={"dropzone " + (drag ? "drag" : "")}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (!busy) select(e.dataTransfer.files);
        }}
      >
        <div className="upload-symbol">
          <Upload size={25} />
        </div>
        <h3>
          {files.length
            ? `${N(files.length)} ملف جاهز للرفع`
            : "اسحب المستندات إلى هنا"}
        </h3>
        <p>أو اختر {reference ? "مرجعًا" : "ملفات العقد"} من جهازك</p>
        <input
          className="sr-only"
          ref={input}
          type="file"
          multiple={!reference}
          accept={
            reference
              ? ".pdf,.docx,.txt,.png,.jpg,.jpeg,.tiff"
              : ".pdf,.docx,.txt,.png,.jpg,.jpeg,.tiff,.zip"
          }
          onChange={(e) => select(e.target.files)}
          aria-label="اختيار المستندات"
          disabled={busy}
        />
        <button
          className="btn outline"
          onClick={() => input.current.click()}
          disabled={busy}
        >
          <Paperclip size={15} /> اختيار {reference ? "المرجع" : "الملفات"}
        </button>
        <small>
          {reference ? "PDF، Word، نصوص، صور" : "PDF، Word، نصوص، صور، ZIP"} ·
          حتى 100 م.ب للملف
        </small>
      </div>
      {files.length > 0 && (
        <div className="selected-files">
          {files.map((f, i) => (
            <div key={i}>
              <FileText size={16} />
              <span>{f.name}</span>
              <small>{SIZE(f.size)}</small>
              <IButton
                title="إزالة الملف"
                onClick={() => setFiles(files.filter((_, j) => j !== i))}
                disabled={busy}
              >
                <X size={13} />
              </IButton>
            </div>
          ))}
          <button className="btn primary" disabled={busy} onClick={upload}>
            {busy ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <Upload size={16} />
            )}{" "}
            {busy ? "جارٍ الرفع واستخراج النص…" : "رفع وحفظ المستندات"}
          </button>
        </div>
      )}
    </div>
  );
}
function Documents({ docs = [], caseId, onUpdate, notify, onText }) {
  async function remove(d) {
    if (
      !window.confirm(
        `هل تريد حذف «${d.name}»؟ ستعاد إجراءات الفحص المرتبطة به إلى الانتظار.`,
      )
    )
      return;
    try {
      onUpdate(
        await api(`/cases/${caseId}/documents/${d.id}`, { method: "DELETE" }),
      );
      notify("حُذف المستند وحُدّثت النتائج المرتبطة.");
    } catch (e) {
      notify(e.message, "error");
    }
  }
  return !docs.length ? (
    <Empty icon={Files} title="لا توجد مستندات بعد">
      ارفع العقد والأوليات لبدء فحص يستند إلى أدلة.
    </Empty>
  ) : (
    <div className="document-list">
      {docs.map((d) => (
        <div className="document-row" key={d.id}>
          <div className="document-icon">
            <FileText size={21} />
            <small>{d.name?.split(".").pop()?.toUpperCase()}</small>
          </div>
          <div className="document-info">
            <a
              href={`/api/documents/${d.id}/file`}
              target="_blank"
              rel="noreferrer"
            >
              {d.name}
            </a>
            <div>
              <span>{CATS[d.category] || d.category}</span>
              <span>·</span>
              <span>{SIZE(d.size || 0)}</span>
              {d.page_count > 0 && (
                <>
                  <span>·</span>
                  <span>{N(d.page_count)} صفحة</span>
                </>
              )}
            </div>
            {d.warnings?.length > 0 && (
              <small className="doc-warning">{d.warnings[0]}</small>
            )}
          </div>
          <span
            className={
              "text-state " +
              (["text", "ocr"].includes(d.extraction_status) ? "readable" : "")
            }
          >
            {d.extraction_status === "text"
              ? "نص متاح"
              : d.extraction_status === "ocr"
                ? "نص بصري"
                : d.extraction_status === "ocr_partial"
                  ? "استخراج جزئي"
                  : "نسخة محفوظة"}
          </span>
          <div className="document-actions">
            <IButton title="عرض النص المستخرج" onClick={() => onText(d)}>
              <Eye size={16} />
            </IButton>
            <a
              href={`/api/documents/${d.id}/file`}
              target="_blank"
              rel="noreferrer"
              className="icon-btn"
              title="فتح المستند"
              aria-label="فتح المستند"
            >
              <ExternalLink size={16} />
            </a>
            {caseId && (
              <IButton title="حذف المستند" onClick={() => remove(d)}>
                <Trash2 size={16} />
              </IButton>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
function CheckEditor({ item, current, references, onUpdate, notify }) {
  const [open, setOpen] = useState(false),
    [v, setV] = useState({ ...item }),
    [busy, setBusy] = useState(false);
  useEffect(() => setV({ ...item }), [item]);
  const change = (k, value) => setV({ ...v, [k]: value });
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      onUpdate(
        await api(`/cases/${current.id}/checks/${item.id}`, {
          method: "PATCH",
          body: Object.fromEntries(
            [
              "status",
              "note",
              "evidence_document_id",
              "evidence_page",
              "reference_id",
              "legal_basis",
            ].map((k) => [k, v[k] || ""]),
          ),
        }),
      );
      notify("تم حفظ نتيجة الفحص.");
      setOpen(false);
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <article
      className={"check-card " + (item.status === "fail" ? "has-finding" : "")}
    >
      <button
        className="check-summary"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className={"check-symbol " + item.status}>
          {item.status === "pass" ? (
            <Check size={18} />
          ) : item.status === "fail" ? (
            <AlertCircle size={18} />
          ) : (
            <ClipboardCheck size={18} />
          )}
        </span>
        <div>
          <h3>{item.title}</h3>
          <p>{item.description}</p>
          {item.source_name && (
            <small>
              المرجع: {item.source_name} · صفحة {item.source_page}
            </small>
          )}
        </div>
        <Badge status={item.status} />
        <ChevronDown size={17} className={open ? "rotate" : ""} />
      </button>
      {open && (
        <form className="check-form" onSubmit={save}>
          <div className="status-options">
            {Object.entries(STATUS).map(([k, label]) => (
              <label
                className={
                  "status-option " + (v.status === k ? "selected " + k : "")
                }
                key={k}
              >
                <input
                  type="radio"
                  name={`status-${item.id}`}
                  checked={v.status === k}
                  onChange={() => change("status", k)}
                />
                {label}
              </label>
            ))}
          </div>
          <Field
            label="نتيجة الفحص والملاحظة"
            required={v.status !== "pending"}
            hint="وثّق ما تم فحصه وسبب النتيجة. مجرد وجود المستند لا يثبت الاستيفاء."
          >
            <textarea
              rows={3}
              value={v.note || ""}
              onChange={(e) => change("note", e.target.value)}
              required={v.status !== "pending"}
            />
          </Field>
          <div className="form-grid">
            <Field label="مستند الإثبات">
              <select
                value={v.evidence_document_id || ""}
                onChange={(e) => change("evidence_document_id", e.target.value)}
              >
                <option value="">اختر مستندًا من ملف العقد</option>
                {current.documents?.map((d) => (
                  <option value={d.id} key={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="صفحة الدليل" hint="رقم صفحة أو نطاق مثل 3-5">
              <input
                value={v.evidence_page || ""}
                onChange={(e) => change("evidence_page", e.target.value)}
                placeholder="مثال: 3 أو 3-5"
              />
            </Field>
            <Field label="المرجع الرقابي / القانوني">
              <select
                value={v.reference_id || ""}
                onChange={(e) => change("reference_id", e.target.value)}
              >
                <option value="">اختر المرجع المعتمد</option>
                {references.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="المادة / الفقرة والصفحة المرجعية">
              <input
                value={v.legal_basis || ""}
                onChange={(e) => change("legal_basis", e.target.value)}
                placeholder="رقم المادة والفقرة وصفحة المرجع"
              />
            </Field>
          </div>
          <div className="check-footer">
            <span>
              <ShieldCheck size={14} /> نتيجة موثّقة بمراجعة المدقق
            </span>
            <button className="btn primary small" disabled={busy}>
              {busy ? (
                <Loader2 className="spin" size={15} />
              ) : (
                <Check size={15} />
              )}{" "}
              حفظ النتيجة
            </button>
          </div>
        </form>
      )}
    </article>
  );
}
function Checks({ step, current, references, onUpdate, notify }) {
  const rows = current.checks?.filter((c) => c.step === step) || [];
  return !rows.length ? null : (
    <div className="checks-area">
      <div className="section-heading">
        <h2>
          إجراءات الفحص <span>{N(rows.length)}</span>
        </h2>
        <small>لكل نتيجة سند ودليل</small>
      </div>
      {rows.map((c) => (
        <CheckEditor
          key={c.id}
          item={c}
          current={current}
          references={references}
          onUpdate={onUpdate}
          notify={notify}
        />
      ))}
    </div>
  );
}
function QuickForm({ current, schema, onUpdate, notify }) {
  const [v, setV] = useState({ ...current.quick_form }),
    [busy, setBusy] = useState(false),
    [active, setActive] = useState("data");
  useEffect(
    () => setV({ ...current.quick_form }),
    [current.id, current.quick_form],
  );
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      onUpdate(
        await api(`/cases/${current.id}/quick-form`, {
          method: "PATCH",
          body: v,
        }),
      );
      notify("تم حفظ استمارة الفحص السريع.");
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  const group = schema.find((g) => g.id === active) || schema[0];
  return (
    <form className="panel quick-form" onSubmit={save}>
      <div className="panel-title">
        <div>
          <h2>استمارة الفحص الأولي للعقد</h2>
          <p>٦ أقسام من المرجع الفعلي · الصفحات ٢٤–٢٩</p>
        </div>
        <ClipboardCheck size={23} />
      </div>
      <div className="form-tabs">
        {schema.map((g, i) => (
          <button
            type="button"
            key={g.id}
            className={active === g.id ? "active" : ""}
            onClick={() => setActive(g.id)}
          >
            {N(i + 1)}. {g.title}
          </button>
        ))}
      </div>
      {group?.description && (
        <Notice tone="warning">{group.description}</Notice>
      )}
      <div className="form-grid">
        {group?.fields?.map((f) => (
          <div
            className={
              f.type === "textarea" ||
              f.key.startsWith("quick_req") ||
              f.key.startsWith("risk")
                ? "span-2"
                : ""
            }
            key={f.key}
          >
            <Field
              label={f.label}
              required={f.required}
              hint={[
                f.description,
                f.source_page ? `المرجع: صفحة ${f.source_page}` : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            >
              {f.type === "textarea" ? (
                <textarea
                  rows={3}
                  value={v[f.key] || ""}
                  onChange={(e) => setV({ ...v, [f.key]: e.target.value })}
                />
              ) : f.type === "select" ? (
                <select
                  value={v[f.key] || ""}
                  onChange={(e) => setV({ ...v, [f.key]: e.target.value })}
                >
                  <option value="">لم يُحدّد بعد</option>
                  {f.options?.map((o) => (
                    <option value={o.value} key={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={f.type || "text"}
                  value={v[f.key] || ""}
                  onChange={(e) => setV({ ...v, [f.key]: e.target.value })}
                />
              )}
            </Field>
          </div>
        ))}
      </div>
      <div className="form-bottom">
        <span>يمكن الحفظ تدريجيًا؛ اكتمال الحقول مطلوب للتقرير النهائي.</span>
        <button className="btn primary" disabled={busy}>
          {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}{" "}
          حفظ الاستمارة
        </button>
      </div>
    </form>
  );
}
function Blacklist({ current, references, onUpdate, notify }) {
  const info = current.blacklist || {};
  const [source, setSource] = useState(
      info.source_url || "https://blacklist.mop.gov.iq/",
    ),
    [ref, setRef] = useState(""),
    [busy, setBusy] = useState(false),
    [open, setOpen] = useState(false),
    [status, setStatus] = useState("pending"),
    [note, setNote] = useState(info.note || ""),
    [evidence, setEvidence] = useState(info.evidence_document_id || ""),
    [confirmed, setConfirmed] = useState(false),
    [reviewed, setReviewed] = useState(false);
  const docs = [...references, ...current.documents],
    blacklists = docs.filter((d) => d.category === "blacklist");
  async function check(e) {
    e.preventDefault();
    setBusy(true);
    try {
      onUpdate(
        await api(`/cases/${current.id}/blacklist/check`, {
          method: "POST",
          body: {
            source_url: source || undefined,
            reference_document_id: ref || undefined,
          },
        }),
      );
      notify("اكتمل البحث المساعد. راجع المصدر والنتيجة قبل الاعتماد.");
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      onUpdate(
        await api(`/cases/${current.id}/blacklist`, {
          method: "PATCH",
          body: {
            status,
            note,
            evidence_document_id: evidence,
            source_url: source,
            human_confirmed: confirmed,
            reviewed_full_document: reviewed,
          },
        }),
      );
      notify("تم حفظ مراجعة القائمة السوداء.");
      setOpen(false);
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Notice tone="warning" title="غياب تطابق نصي لا يثبت عدم الإدراج">
        المنصة الرسمية للقوائم السوداء متاحة على blacklist.mop.gov.iq. البيانات
        المنشورة للعرض، ويلزم تأييد الجهة المختصة للحسم القانوني؛ نتيجة النظام
        مراجعة داخلية موثقة وليست شهادة أهلية. يمكن رفع القائمة الرسمية
        ومراجعتها يدويًا. استخراج جزئي أو اختلاف تهجئة الأسماء لا يكفي لاعتماد
        خلو الشركة.
      </Notice>
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>التحقق من المتعاقد</h2>
            <p>المصدر المعتمد: وزارة التخطيط العراقية</p>
          </div>
          <SearchCheck size={25} />
        </div>
        <div className="contractor-box">
          <Building2 size={25} />
          <div>
            <small>الاسم المطلوب فحصه</small>
            <strong>{current.contractor}</strong>
          </div>
          <a
            href="https://blacklist.mop.gov.iq/"
            target="_blank"
            rel="noreferrer"
            className="btn outline small"
          >
            موقع الوزارة <ExternalLink size={14} />
          </a>
        </div>
        <form onSubmit={check}>
          <div className="form-grid">
            <Field
              label="رابط القائمة الرسمي"
              hint="رابط HTTPS على mop.gov.iq أو www.mop.gov.iq أو blacklist.mop.gov.iq"
            >
              <input
                type="url"
                dir="ltr"
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="https://mop.gov.iq/…"
              />
            </Field>
            <Field label="أو ملف قائمة رسمية مرفوع">
              <select value={ref} onChange={(e) => setRef(e.target.value)}>
                <option value="">اختر ملف القائمة السوداء</option>
                {blacklists.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="form-bottom">
            <button
              className="btn primary"
              disabled={busy || (!source && !ref)}
            >
              {busy ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <Search size={16} />
              )}{" "}
              فحص الاسم في المصدر
            </button>
          </div>
        </form>
      </section>
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>نتيجة الفحص</h2>
            <p>
              {info.checked_at
                ? `آخر فحص: ${D(info.checked_at)}`
                : "لا توجد نتيجة معتمدة بعد"}
            </p>
          </div>
          <span
            className={
              "badge " +
              (info.status === "cleared"
                ? "pass"
                : info.status === "confirmed_match"
                  ? "fail"
                  : "pending")
            }
          >
            {BL[info.status] || BL.pending}
          </span>
        </div>
        {info.note && <p className="body-copy">{info.note}</p>}
        {info.source_url && (
          <a
            className="source-link"
            href={info.source_url}
            target="_blank"
            rel="noreferrer"
          >
            المصدر المستخدم <ExternalLink size={14} />
          </a>
        )}
        {info.matches?.length > 0 && (
          <div className="match-list">
            {info.matches.map((m, i) => (
              <div key={i}>
                <AlertCircle size={16} />
                {typeof m === "string"
                  ? m
                  : m.text || m.name || JSON.stringify(m)}
              </div>
            ))}
          </div>
        )}
        <button className="btn outline" onClick={() => setOpen(!open)}>
          <Pencil size={16} /> توثيق المراجعة البشرية
        </button>
        {open && (
          <form className="manual-review" onSubmit={save}>
            <div className="form-grid">
              <Field label="النتيجة المعتمدة">
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  {Object.entries(BL)
                    .filter(([k]) => k !== "possible_match")
                    .map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label="مستند الإثبات" required>
                <select
                  required
                  value={evidence}
                  onChange={(e) => setEvidence(e.target.value)}
                >
                  <option value="">اختر القائمة الرسمية المحفوظة</option>
                  {docs.map((d) => (
                    <option value={d.id} key={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="span-2">
                <Field label="ملاحظات المراجعة وتاريخ القائمة" required>
                  <textarea
                    rows={3}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    required
                    placeholder="تاريخ المصدر ونطاقه، الاسم القانوني للشركة والأسماء البديلة…"
                  />
                </Field>
              </div>
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              أؤكد أنني راجعت المصدر الرسمي واعتمدت النتيجة بناءً على الدليل
              المحفوظ.
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={reviewed}
                onChange={(e) => setReviewed(e.target.checked)}
              />
              راجعت كامل صفحات المستند الأصلي بصريًا، بما فيها الصفحات غير
              المستخرجة نصيًا.
            </label>
            <button className="btn primary" disabled={busy || !confirmed}>
              {busy ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <Check size={16} />
              )}{" "}
              حفظ المراجعة
            </button>
          </form>
        )}
      </section>
      <section className="panel">
        <h3 className="upload-heading">إضافة قائمة رسمية إلى ملف العقد</h3>
        <UploadPanel
          category="blacklist"
          caseId={current.id}
          onUpdate={onUpdate}
          notify={notify}
        />
      </section>
    </>
  );
}
function YearOverride({ current, onUpdate, notify }) {
  const [value, setValue] = useState(
      current.instruction_year_override
        ? String(current.instruction_year_override)
        : "",
    ),
    [reason, setReason] = useState(current.instruction_override_reason || ""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    setValue(
      current.instruction_year_override
        ? String(current.instruction_year_override)
        : "",
    );
    setReason(current.instruction_override_reason || "");
  }, [
    current.id,
    current.instruction_year_override,
    current.instruction_override_reason,
  ]);
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      onUpdate(
        await api(`/cases/${current.id}`, {
          method: "PATCH",
          body: {
            instruction_year_override: value ? Number(value) : null,
            instruction_override_reason: reason,
          },
        }),
      );
      notify("تم حفظ الأساس المعتمد للتعليمات وإعادة فتح الفحوص المتأثرة.");
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="panel" onSubmit={save}>
      <div className="panel-title">
        <div>
          <h2>تثبيت التعليمات بعد المراجعة القانونية</h2>
          <p>قاعدة السنة نقطة بداية، ويجوز تعديل الاختيار بسند مبرر.</p>
        </div>
        <Scale size={23} />
      </div>
      <Notice tone="warning">
        كتاب وزارة التخطيط 3429 في 3/2/2026 يؤكد بدء تعليمات 2025 والضوابط
        العشرين في 15/2/2026. تنظم المادة 42 النفاذ بعد النشر، والمادة 41
        استمرار تعليمات 2014 للعقود المبرمة بموجبها (النص الرسمي، PDF ص56). لا
        يثبت تاريخ العقد وحده النظام القانوني المنطبق؛ راجع الأصل والأحكام
        الانتقالية.
      </Notice>
      <div className="form-grid">
        <Field label="التعليمات المعتمدة">
          <select value={value} onChange={(e) => setValue(e.target.value)}>
            <option value="">حسب قاعدة السنوات المطلوبة</option>
            <option value="2014">تعليمات 2014 — اختيار المدقق</option>
            <option value="2025">تعليمات 2025 — اختيار المدقق</option>
          </select>
        </Field>
        <Field label="سبب الاختيار والمادة المرجعية" required={!!value}>
          <textarea
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required={!!value}
            placeholder="اشرح السريان والأحكام الانتقالية مع المادة والصفحة…"
          />
        </Field>
      </div>
      <div className="form-bottom">
        <button className="btn primary" disabled={busy}>
          {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}{" "}
          حفظ الأساس المعتمد
        </button>
      </div>
    </form>
  );
}
function SourceGuidance({ guidance }) {
  if (!guidance) return null;
  return (
    <div className="source-guidance">
      <h3>
        <BookOpen size={17} /> أدلة القراءة ونطاق المراجع
      </h3>
      {guidance.notice && <Notice tone="warning">{guidance.notice}</Notice>}
      {[
        ["rules", "بنود الأعمام والقرار"],
        ["document_requirements", "الأوليات المطلوبة في الملاحق"],
        ["guide_rules", "مبادئ دليل التقييم"],
        ["bundle_index", "فهرس الحزمة والقرارات السابقة"],
        ["models", "نماذج الدليل"],
      ].map(
        ([key, title]) =>
          guidance[key]?.length > 0 && (
            <details key={key}>
              <summary>
                {title}
                <span>{N(guidance[key].length)}</span>
              </summary>
              <div>
                {guidance[key].map((r, i) => (
                  <article key={r.id || i}>
                    <p>{r.text || r.label || r.title}</p>
                    <small>
                      صفحة{" "}
                      {Array.isArray(r.pdf_pages)
                        ? r.pdf_pages.join("، ")
                        : r.pdf_page || r.page || "—"}
                      {r.status === "cancelled-by-decision-398"
                        ? " · ملغى بقرار 398"
                        : ""}
                    </small>
                    {r.historical_scope && <small>{r.historical_scope}</small>}
                  </article>
                ))}
              </div>
            </details>
          ),
      )}
    </div>
  );
}
const REPORT_FIELDS = [
  ["issuing_entity", "الجهة المُصدرة"],
  ["department", "الدائرة / القسم"],
  ["recipient", "الجهة الموجّه إليها"],
  ["report_number", "عدد الكتاب"],
  ["report_date", "تاريخ التقرير", "date"],
  ["subject", "موضوع الكتاب"],
  ["clarifications", "الإيضاحات", "textarea"],
  ["closing", "الخاتمة والإجراء المطلوب", "textarea"],
  ["auditor_role", "صفة المدقق"],
  ["copy_to", "نسخة منه إلى", "textarea"],
];
const TABLES = {
  award_recommendations: [
    "موقف التوصية بالإحالة",
    [
      ["number", "ت"],
      ["company", "الشركة"],
      ["schedules", "أرقام الجداول"],
      ["recommendation", "موقف التوصية"],
    ],
  ],
  estimate_market_comparison: [
    "الكلفة التخمينية وأسعار السوق",
    [
      ["details", "التفاصيل"],
      ["estimate", "الكلفة التخمينية"],
      ["market_price", "سعر السوق"],
      ["difference", "الفرق"],
    ],
  ],
  award_market_comparison: [
    "الإحالة وأسعار السوق",
    [
      ["schedule", "الجدول"],
      ["award_amount", "مبلغ الإحالة"],
      ["market_amount", "مبلغ السوق"],
      ["difference", "الفرق"],
      ["difference_percent", "نسبة الفرق"],
    ],
  ],
  similar_works: [
    "الأعمال المماثلة",
    [
      ["number", "ت"],
      ["company", "الشركة"],
      ["estimated_cost", "الكلفة التخمينية"],
      ["similar_amount", "مبلغ الأعمال"],
      ["provided_percent", "النسبة المقدمة"],
      ["required_percent", "النسبة المطلوبة"],
      ["result", "النتيجة"],
    ],
  ],
  financial_capacity: [
    "الكفاءة المالية",
    [
      ["number", "ت"],
      ["company", "الشركة"],
      ["estimated_cost", "الكلفة التخمينية"],
      ["capacity_amount", "الكفاءة المالية"],
      ["provided_percent", "النسبة المقدمة"],
      ["required_percent", "النسبة المطلوبة"],
      ["result", "النتيجة"],
    ],
  ],
  evaluation_notes: [
    "ملاحظات تحليل العطاءات",
    [
      ["company", "الشركة"],
      ["observation", "الملاحظة"],
    ],
  ],
  discount_check: [
    "احتساب التخفيض",
    [
      ["company", "الشركة"],
      ["schedule", "الجدول"],
      ["opening_amount", "مبلغ الفتح"],
      ["discount_percent", "نسبة التخفيض"],
      ["discounted_amount", "بعد التخفيض"],
      ["analysis_amount", "مبلغ التحليل"],
    ],
  ],
  bid_amount_discrepancies: [
    "فروقات الفتح والتحليل",
    [
      ["number", "ت"],
      ["company", "الشركة"],
      ["schedule", "الجدول"],
      ["opening_amount", "مبلغ الفتح"],
      ["discounted_amount", "بعد التخفيض"],
      ["analysis_amount", "مبلغ التحليل"],
    ],
  ],
  missing_decisions: [
    "جداول بلا قرار مثبت",
    [
      ["company", "الشركة"],
      ["schedules", "أرقام الجداول"],
    ],
  ],
  unclassified_bidders: [
    "موقف الشركات والجداول",
    [
      ["number", "ت"],
      ["company", "الشركة"],
      ["schedules", "الجداول"],
    ],
  ],
};
function ReportEditor({ current, onUpdate, notify }) {
  const [v, setV] = useState({ ...current.quick_form }),
    [table, setTable] = useState("award_recommendations"),
    [busy, setBusy] = useState(false);
  useEffect(
    () => setV({ ...current.quick_form }),
    [current.quick_form, current.id],
  );
  const rows = v.report_tables?.[table] || [],
    cols = TABLES[table][1];
  function changeRows(next) {
    setV({ ...v, report_tables: { ...v.report_tables, [table]: next } });
  }
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const body = Object.fromEntries(
        REPORT_FIELDS.map(([k]) => [k, v[k] || ""]),
      );
      body.report_tables = v.report_tables || {};
      onUpdate(
        await api(`/cases/${current.id}/quick-form`, { method: "PATCH", body }),
      );
      notify("تم حفظ بيانات الكتاب وجداول التقرير.");
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="panel" onSubmit={save}>
      <div className="panel-title">
        <div>
          <h2>بيانات كتاب التدقيق وجداوله</h2>
          <p>تُملأ من الحالة الفعلية دون نقل أسماء أو مبالغ النموذج.</p>
        </div>
        <Pencil size={22} />
      </div>
      <div className="form-grid">
        {REPORT_FIELDS.map(([k, label, type]) => (
          <div key={k} className={type === "textarea" ? "span-2" : ""}>
            <Field label={label}>
              {type === "textarea" ? (
                <textarea
                  rows={3}
                  value={v[k] || ""}
                  onChange={(e) => setV({ ...v, [k]: e.target.value })}
                />
              ) : (
                <input
                  type={type || "text"}
                  value={v[k] || ""}
                  onChange={(e) => setV({ ...v, [k]: e.target.value })}
                />
              )}
            </Field>
          </div>
        ))}
      </div>
      <div className="table-editor">
        <Field label="جدول التقرير">
          <select value={table} onChange={(e) => setTable(e.target.value)}>
            {Object.entries(TABLES).map(([k, [title]]) => (
              <option key={k} value={k}>
                {title}
              </option>
            ))}
          </select>
        </Field>
        {rows.length > 0 ? (
          <div className="editor-scroll">
            <table>
              <thead>
                <tr>
                  {cols.map(([k, label]) => (
                    <th key={k}>{label}</th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    {cols.map(([k, label]) => (
                      <td key={k}>
                        <input
                          aria-label={`${label}، الصف ${i + 1}`}
                          value={row[k] || ""}
                          onChange={(e) =>
                            changeRows(
                              rows.map((r, j) =>
                                i === j ? { ...r, [k]: e.target.value } : r,
                              ),
                            )
                          }
                        />
                      </td>
                    ))}
                    <td>
                      <IButton
                        title="حذف الصف"
                        onClick={() =>
                          changeRows(rows.filter((_, j) => i !== j))
                        }
                      >
                        <Trash2 size={15} />
                      </IButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="table-empty">
            لا توجد صفوف. يظهر الجدول في التقرير عند إدخال بياناته.
          </p>
        )}
        <button
          className="btn outline small"
          type="button"
          disabled={rows.length >= 100}
          onClick={() => changeRows([...rows, {}])}
        >
          <Plus size={15} /> إضافة صف
        </button>
      </div>
      <div className="form-bottom">
        <button className="btn primary" disabled={busy}>
          {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}{" "}
          حفظ بيانات التقرير
        </button>
      </div>
    </form>
  );
}
function Report({ current, onUpdate, notify }) {
  const [preview, setPreview] = useState(false),
    [busy, setBusy] = useState(""),
    [edit, setEdit] = useState(false);
  let ready = current.readiness?.ready;
  async function download(final, format = "pdf") {
    setBusy(`${final}-${format}`);
    try {
      const r = await fetch(
        `/api/cases/${current.id}/report?format=${format}&final=${final}`,
      );
      if (!r.ok) {
        let d;
        try {
          d = await r.json();
        } catch {}
        throw Error(errorText(d?.detail));
      }
      const blob = await r.blob(),
        url = URL.createObjectURL(blob),
        a = document.createElement("a");
      a.href = url;
      a.download = `تقرير-${current.contract_number || current.id}-${final ? "نهائي" : "مسودة"}.${format}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <Notice title="بنية مستندة إلى التقرير البشري المرفوع">
        الإيضاحات والملاحظات والجداول مرتبة وفق النموذج. الأصل تقرير ممسوح
        وموقّع؛ لا تُنقل توقيعاته أو بيانات حالته. المطابقة البصرية الكاملة
        تحتاج مراجعة القالب النهائي.
      </Notice>
      <section className="panel report-readiness">
        <div className="report-icon">
          {ready ? <CheckCircle2 size={31} /> : <FileText size={31} />}
        </div>
        <div>
          <h2>{ready ? "ملف التدقيق مكتمل التوثيق" : "التقرير قيد الإعداد"}</h2>
          <p>
            {ready
              ? "راجع المعاينة قبل اعتماد الإخراج."
              : "تتوفر المسودة الآن، ويُتاح الإخراج النهائي بعد استكمال متطلبات التوثيق."}
          </p>
        </div>
        <span className={"badge " + (ready ? "pass" : "pending")}>
          {ready ? "مكتمل" : "مسودة"}
        </span>
      </section>
      {current.readiness?.blockers?.length > 0 && (
        <section className="panel blockers">
          <h3>
            <AlertCircle size={17} /> متطلبات الإخراج النهائي
          </h3>
          <ul>
            {current.readiness.blockers.map((b, i) => (
              <li key={i}>
                {typeof b === "string" ? b : b.message || JSON.stringify(b)}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>إخراج تقرير التدقيق</h2>
            <p>
              العقد {current.contract_number} · {current.contractor}
            </p>
          </div>
          <FileText size={24} />
        </div>
        <div className="report-actions">
          <button className="btn primary" onClick={() => setPreview(!preview)}>
            <Eye size={16} />
            {preview ? "إغلاق المعاينة" : "معاينة المسودة"}
          </button>
          <button
            className="btn outline"
            disabled={!!busy}
            onClick={() => download(false)}
          >
            {busy === "false-pdf" ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <Download size={16} />
            )}{" "}
            مسودة PDF
          </button>
          <button
            className="btn outline"
            disabled={!!busy}
            onClick={() => download(false, "html")}
          >
            <Download size={16} /> HTML للطباعة
          </button>
          <button
            className="btn primary"
            disabled={!ready || !!busy}
            onClick={() => download(true)}
          >
            {busy === "true-pdf" ? (
              <Loader2 className="spin" size={16} />
            ) : (
              <ShieldCheck size={16} />
            )}{" "}
            التقرير النهائي
          </button>
        </div>
        {preview && (
          <iframe
            key={current.updated_at}
            className="report-preview"
            title="معاينة مسودة التقرير"
            src={`/api/cases/${current.id}/report?format=html&final=false`}
          />
        )}
        <div className="report-edit-toggle">
          <button className="text-button" onClick={() => setEdit(!edit)}>
            <Pencil size={15} />{" "}
            {edit
              ? "إخفاء بيانات الكتاب والجداول"
              : "تحرير بيانات كتاب التدقيق والجداول"}
          </button>
        </div>
      </section>
      {edit && (
        <ReportEditor current={current} onUpdate={onUpdate} notify={notify} />
      )}
    </>
  );
}
function Library({ references, guidance, onRefresh, notify, onText, onClose }) {
  return (
    <Modal
      wide
      title="مكتبة المراجع"
      description="راجع تاريخ المصدر ونطاقه قبل ربطه بإجراء الفحص."
      onClose={onClose}
    >
      <div className="library-content">
        <Notice tone="warning">
          أعمام الديوان مؤرخ في 17/8/2026، وكتاب تبليغ قرار مجلس الوزراء
          398/2026 مؤرخ في 10/8/2026. لا تنطبق هذه المراجع تلقائيًا على العقود
          الأقدم. النصان الكاملان لتعليمات 2014 و2025 مطلوبان عند اختيارهما.
        </Notice>
        <Documents docs={references} onText={onText} notify={notify} />
        <SourceGuidance guidance={guidance} />
        <div className="library-upload">
          <h3>
            <Plus size={18} /> إضافة مرجع رسمي
          </h3>
          <UploadPanel reference notify={notify} onReference={onRefresh} />
        </div>
      </div>
    </Modal>
  );
}
function TextPreview({ doc, onClose }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let live = true;
    api(`/documents/${doc.id}/text`)
      .then((d) => live && setState(d))
      .catch((e) => live && setState({ error: e.message }));
    return () => {
      live = false;
    };
  }, [doc.id]);
  return (
    <Modal wide title="النص المستخرج" description={doc.name} onClose={onClose}>
      <div className="text-preview">
        {state.loading ? (
          <div className="loading">
            <Loader2 className="spin" /> جارٍ تحميل النص…
          </div>
        ) : state.error ? (
          <Notice tone="error">{state.error}</Notice>
        ) : (
          <>
            {state.warnings?.length > 0 && (
              <Notice tone="warning">{state.warnings.join(" · ")}</Notice>
            )}
            {state.text ? (
              <pre>{state.text}</pre>
            ) : (
              <Empty icon={FileText} title="لا يوجد نص قابل للبحث">
                راجع النسخة الأصلية بصريًا؛ قد تحتاج الصفحات إلى استخراج بصري.
              </Empty>
            )}
            <a
              className="btn outline"
              href={`/api/documents/${doc.id}/file`}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink size={16} /> فتح المستند الأصلي
            </a>
          </>
        )}
      </div>
    </Modal>
  );
}
function App() {
  const [cases, setCases] = useState([]),
    [current, setCurrent] = useState(null),
    [refs, setRefs] = useState([]),
    [schema, setSchema] = useState([]),
    [guidance, setGuidance] = useState(null),
    [step, setStep] = useState("upload"),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [form, setForm] = useState(null),
    [library, setLibrary] = useState(false),
    [textDoc, setTextDoc] = useState(null),
    [toast, setToast] = useState(null),
    [mobile, setMobile] = useState(false),
    [search, setSearch] = useState(""),
    [reload, setReload] = useState(0),
    [advancedReview, setAdvancedReview] = useState(false),
    [aiSettingsOpen, setAiSettingsOpen] = useState(false),
    [aiSettingsVersion, setAiSettingsVersion] = useState(0);
  const timer = useRef();
  function notify(message, type = "success") {
    setToast({ message, type });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), 7000);
  }
  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all([api("/cases"), api("/bootstrap")])
      .then(([list, b]) => {
        if (!live) return;
        setCases(Array.isArray(list) ? list : list.cases || []);
        setRefs(b.references || []);
        setSchema(b.quick_form_schema || []);
        setGuidance(b.source_guidance || null);
        setError("");
      })
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [reload]);
  async function refreshRefs() {
    try {
      setRefs(await api("/references"));
    } catch (e) {
      notify(e.message, "error");
    }
  }
  function update(c) {
    setCurrent(c);
    setCases((list) => [c, ...list.filter((x) => x.id !== c.id)]);
  }
  async function open(c) {
    try {
      update(await api(`/cases/${c.id}`));
      setAdvancedReview(false);
      setStep("upload");
      setMobile(false);
    } catch (e) {
      notify(e.message, "error");
    }
  }
  async function openAutomaticCase(caseId) {
    update(await api(`/cases/${caseId}`));
    setAdvancedReview(false);
    setStep("upload");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function go(s) {
    setStep(s);
    setMobile(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  const total = current?.checks?.length || 0,
    done = current?.checks?.filter((c) => c.status !== "pending").length || 0,
    pct = total ? Math.round((done / total) * 100) : 0,
    idx = STEPS.findIndex((s) => s.id === step),
    active = STEPS[idx] || STEPS[0],
    filtered = cases.filter((c) =>
      [c.title, c.contractor, c.contract_number, c.entity].some((v) =>
        v?.toLowerCase().includes(search.toLowerCase()),
      ),
    ),
    findings = cases.reduce(
      (n, c) => n + (c.checks?.filter((x) => x.status === "fail").length || 0),
      0,
    );
  const checks = (s) => (
    <Checks
      step={s}
      current={current}
      references={refs}
      onUpdate={update}
      notify={notify}
    />
  );
  const related = refs.filter(
    (r) => r.category === (step === "year" ? "instructions" : step),
  );
  return (
    <div className="app-shell">
      <button
        className="mobile-toggle icon-btn"
        onClick={() => setMobile(!mobile)}
        aria-label="فتح القائمة"
      >
        <Menu size={22} />
      </button>
      {mobile && (
        <div className="sidebar-overlay" onClick={() => setMobile(false)} />
      )}
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setCurrent(null);
            setMobile(false);
          }}
        >
          <span className="brand-mark">
            <Scale size={27} strokeWidth={1.5} />
          </span>
          <div>
            <strong>رَقـيـب</strong>
            <small>تدقيق العقود الحكومية</small>
          </div>
        </a>
        <div className="sidebar-label">مساحة العمل</div>
        <button
          className={"side-link " + (!current ? "active" : "")}
          onClick={() => {
            setCurrent(null);
            setMobile(false);
          }}
        >
          <LayoutDashboard size={18} />
          <span>ملفات التدقيق</span>
          <b>{N(cases.length)}</b>
        </button>
        <button
          className="side-link"
          onClick={() => {
            setLibrary(true);
            setMobile(false);
          }}
        >
          <BookOpen size={18} />
          <span>مكتبة المراجع</span>
          <b>{N(refs.length)}</b>
        </button>
        <button className="side-link" onClick={() => { setAiSettingsOpen(true); setMobile(false); }}><Settings2 size={18} /><span>إعداد الذكاء الاصطناعي</span></button>
        <div className="sidebar-divider" />
        {current && advancedReview ? (
          <>
            <div className="sidebar-label">
              مسار فحص العقد <span>{N(idx + 1)} / ٩</span>
            </div>
            <nav aria-label="خطوات تدقيق العقد">
              {STEPS.map((s, i) => {
                let a = current.checks?.filter((c) => c.step === s.id) || [],
                  complete =
                    a.length > 0 && a.every((c) => c.status !== "pending");
                return (
                  <button
                    key={s.id}
                    className={
                      "step-link " +
                      (step === s.id ? "active " : "") +
                      (complete ? "complete" : "")
                    }
                    onClick={() => go(s.id)}
                    aria-current={step === s.id ? "step" : undefined}
                  >
                    <span className="step-num">
                      {complete ? <Check size={13} /> : N(i + 1)}
                    </span>
                    <span>{s.title}</span>
                    {step === s.id && <i />}
                  </button>
                );
              })}
            </nav>
            <div className="sidebar-progress">
              <div>
                <span>إنجاز إجراءات الفحص</span>
                <strong>{N(pct)}٪</strong>
              </div>
              <div className="progress-track">
                <i style={{ width: pct + "%" }} />
              </div>
              <small>
                {N(done)} من {N(total)} إجراء موثّق
              </small>
            </div>
          </>
        ) : (
          current ? <div className="ai-sidebar-mode">
            <div className="sidebar-label">التدقيق الآلي</div>
            <button className="side-link active" onClick={() => setMobile(false)}><Sparkles size={18} /><span>متابعة الفحص والنتائج</span></button>
            <button className="side-link" onClick={() => { setAdvancedReview(true); setMobile(false); }}><BookOpen size={18} /><span>المراجعة التفصيلية</span></button>
            <p className="ai-sidebar-description">ينفّذ رقيب المراحل التسع تلقائيًا ويعرض الأدلة والنواقص في ملف واحد.</p>
          </div> : <div className="sidebar-guide">
            <span>
              <ShieldCheck size={27} />
            </span>
            <h3>من الوثيقة إلى الدليل</h3>
            <p>ارفع العقد وأولياته، ليقرأها رقيب وينفّذ خطوات التدقيق ويُعدّ التقرير.</p>
            <div>
              {STEPS.map((s) => (
                <i key={s.id} />
              ))}
            </div>
          </div>
        )}
        <div className="sidebar-bottom">
          <i />
          <span>توثيقٌ يحفظ أثر المراجعة</span>
          <ShieldCheck size={16} />
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <span>مساحة العمل</span>
            <ChevronDown size={12} />
            <strong>{current ? "ملف التدقيق" : "ملفات التدقيق"}</strong>
          </div>
          <div className="topbar-meta">
            <span className="today">
              <CalendarDays size={14} />
              {D(new Date())}
            </span>
            <span className="workspace-badge">
              <b>م</b> مساحة المدقق
            </span>
          </div>
        </header>
        <main>
          {error ? (
            <section className="panel startup-error">
              <AlertCircle size={35} />
              <h1>تعذّر تحميل مساحة التدقيق</h1>
              <p>{error}</p>
              <button
                className="btn primary"
                onClick={() => setReload(reload + 1)}
              >
                <RotateCw size={16} /> إعادة المحاولة
              </button>
            </section>
          ) : loading ? (
            <div className="loading app-loading">
              <Loader2 className="spin" size={28} />
              <p>جارٍ تحميل ملفات التدقيق…</p>
            </div>
          ) : !current ? (
            <>
              <div className="page-title">
                <div>
                  <div className="eyebrow">رقيب · التدقيق بالذكاء الاصطناعي</div>
                  <h1>ارفع العقد، وابدأ التدقيق</h1>
                  <p>فحص آلي من الأوليات إلى التقرير، مع الاستشهاد بالمصدر والصفحة.</p>
                </div>
                <div className="ai-dashboard-actions"><button className="btn primary" onClick={() => document.getElementById("automatic-audit-upload")?.scrollIntoView({ behavior: "smooth" })}><Upload size={18} />رفع العقد وأولياته</button><button className="ai-manual-entry" onClick={() => setForm("new")}>إدخال يدوي متقدم</button></div>
              </div>
              <AutoAuditHome onCreated={openAutomaticCase} onSettings={() => setAiSettingsOpen(true)} settingsVersion={aiSettingsVersion} />
              <section className="stats-row">
                {[
                  [FolderOpen, "ملفات التدقيق", cases.length, "teal"],
                  [
                    CheckCircle2,
                    "عمليات تدقيق مكتملة",
                    cases.filter((c) => c.automation?.job?.status === "completed" || c.readiness?.ready).length,
                    "sage",
                  ],
                  [AlertCircle, "ملاحظات مسجّلة", findings, "amber"],
                  [BookOpen, "مراجع في المكتبة", refs.length, "blue"],
                ].map(([Icon, label, value, tone]) => (
                  <div className="stat-card" key={label}>
                    <span className={"stat-icon " + tone}>
                      <Icon size={21} />
                    </span>
                    <div>
                      <span>{label}</span>
                      <strong>{N(value)}</strong>
                    </div>
                  </div>
                ))}
              </section>
              <section className="panel cases-panel">
                <div className="cases-heading">
                  <div>
                    <h2>
                      سجل العقود <span>{N(cases.length)}</span>
                    </h2>
                    <p>اختر ملفًا لمتابعة الفحص أو ابدأ عقدًا جديدًا.</p>
                  </div>
                  <div className="search-box">
                    <Search size={17} />
                    <input
                      placeholder="ابحث باسم العقد أو المتعاقد…"
                      aria-label="بحث في العقود"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </div>
                </div>
                {!cases.length ? (
                  <Empty
                    title="ارفع أول عقد لبدء التدقيق"
                    action={
                      <button
                        className="btn primary"
                        onClick={() => document.getElementById("automatic-audit-upload")?.scrollIntoView({ behavior: "smooth" })}
                      >
                        <Upload size={17} /> رفع العقد والأوليات
                      </button>
                    }
                  >
                    ارفع ملف العقد وأولياته في المنطقة أعلاه. يستخرج رقيب البيانات وينفّذ خطوات الفحص تلقائيًا.
                  </Empty>
                ) : !filtered.length ? (
                  <Empty title="لا توجد نتائج" icon={Search}>
                    جرّب رقم العقد أو اسم الشركة.
                  </Empty>
                ) : (
                  <div className="case-table-wrap">
                    <table className="case-table">
                      <thead>
                        <tr>
                          <th>العقد / المشروع</th>
                          <th>المتعاقد</th>
                          <th>سنة التعليمات</th>
                          <th>حالة التوثيق</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map((c) => (
                          <tr key={c.id}>
                            <td>
                              <button
                                onClick={() => open(c)}
                                className="case-title-button"
                              >
                                <span>
                                  <FileText size={20} />
                                </span>
                                <div>
                                  <strong>{c.title || "جارٍ استخراج بيانات العقد"}</strong>
                                  <small>
                                    {c.contract_number} · {c.entity}
                                  </small>
                                </div>
                              </button>
                            </td>
                            <td>{c.contractor}</td>
                            <td>
                              <span className="year-chip">
                                {c.instruction_year || "لم تحدّد"}
                              </span>
                            </td>
                            <td>
                              <span
                                className={
                                  "badge " +
                                  (!c.automation?.stale && (c.automation?.job?.status === "completed" || c.readiness?.ready) ? "pass" : "pending")
                                }
                              >
                                {c.automation?.stale ? "يلزم إعادة التدقيق" : c.automation?.job?.status === "completed" ? "اكتمل التدقيق الآلي" : ["running", "queued"].includes(c.automation?.job?.status) ? "جارٍ التدقيق الآلي" : c.automation?.job?.status === "failed" ? "تعذّر إكمال التدقيق" : c.automation?.job?.status === "cancelled" ? "أُوقف التدقيق" : c.automation?.job?.status === "interrupted" ? "توقف التشغيل قبل الاكتمال" : c.readiness?.ready ? "مكتمل التوثيق" : "لم يبدأ التدقيق"}
                              </span>
                            </td>
                            <td>
                              <IButton
                                title={`فتح ${c.title}`}
                                onClick={() => open(c)}
                              >
                                <ArrowLeft size={18} />
                              </IButton>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
              <div className="dashboard-footnote">
                <ShieldCheck size={16} />
                <p>
                  ينفّذ رقيب الفحص ويعرض أسانيد النتائج والنواقص بوضوح. يظل اعتماد التقرير الرسمي من اختصاص الجهة المخوّلة.
                </p>
              </div>
            </>
          ) : (
            <>
              <div className="case-topline">
                <button
                  className="text-button"
                  onClick={() => setCurrent(null)}
                >
                  <ArrowRight size={16} /> جميع ملفات التدقيق
                </button>
                <span>
                  ملف العقد <b>{current.contract_number}</b>
                </span>
              </div>
              <div className="page-title case-title">
                <div>
                  <div className="eyebrow">{current.entity}</div>
                  <h1>{current.title || "جارٍ استخراج بيانات العقد"}</h1>
                  <div className="case-subtitle">
                    <span>
                      <Building2 size={15} />
                      {current.contractor}
                    </span>
                    <span>
                      <CalendarDays size={15} />
                      {D(current.contract_date)}
                    </span>
                    {current.instruction_year && (
                      <span className="year-chip">
                        تعليمات {current.instruction_year}
                      </span>
                    )}
                  </div>
                </div>
                {advancedReview && <button className="btn outline" onClick={() => setForm("edit")}><Pencil size={16} /> بيانات العقد</button>}
              </div>
              {!advancedReview ? <AutoAuditCase current={current} references={refs} schema={schema} onUpdate={update} onReview={() => setAdvancedReview(true)} onSettings={() => setAiSettingsOpen(true)} settingsVersion={aiSettingsVersion} /> : <>
              <div className="ai-review-topline"><span>المراجعة التفصيلية للبيانات والأدلة</span><button className="btn outline small" onClick={() => setAdvancedReview(false)}><Sparkles size={16} />العودة للتدقيق الآلي</button></div>
              <section className="case-overview">
                <div className="overview-progress">
                  <div
                    className="progress-circle"
                    style={{ "--progress": pct * 3.6 + "deg" }}
                  >
                    <strong>
                      {N(pct)}
                      <small>٪</small>
                    </strong>
                  </div>
                  <div>
                    <span>تقدّم الفحص</span>
                    <strong>
                      {N(done)} <small>من {N(total)} إجراء</small>
                    </strong>
                  </div>
                </div>
                <div className="overview-stat">
                  <span>المستندات المرفوعة</span>
                  <strong>
                    {N(current.documents?.length)} <small>مستند</small>
                  </strong>
                </div>
                <div className="overview-stat">
                  <span>الملاحظات المسجّلة</span>
                  <strong>
                    {N(
                      current.checks?.filter((c) => c.status === "fail").length,
                    )}{" "}
                    <small>ملاحظة</small>
                  </strong>
                </div>
                <div className="overview-stat">
                  <span>حالة الملف</span>
                  <strong className="file-state">
                    <i />
                    {current.readiness?.ready
                      ? "مكتمل التوثيق"
                      : "قيد المراجعة"}
                  </strong>
                </div>
              </section>
              <div className="stage-heading">
                <span>
                  {React.createElement(active.icon, {
                    size: 25,
                    strokeWidth: 1.6,
                  })}
                </span>
                <div>
                  <small>الخطوة {N(idx + 1)} من ٩</small>
                  <h2>{active.title}</h2>
                  <p>{active.desc}</p>
                </div>
              </div>
              <div className="stage-content">
                {step === "upload" ? (
                  <>
                    <section className="panel">
                      <div className="panel-title">
                        <div>
                          <h2>رفع العقد مع الأوليات</h2>
                          <p>تبقى الأصول محفوظة وترتبط بها نتائج الفحص.</p>
                        </div>
                        <Upload size={22} />
                      </div>
                      <UploadPanel
                        category="contract"
                        caseId={current.id}
                        onUpdate={update}
                        notify={notify}
                      />
                    </section>
                    <section className="panel">
                      <div className="section-heading">
                        <h2>
                          مستندات الملف{" "}
                          <span>{N(current.documents?.length)}</span>
                        </h2>
                        <small>الأصول والأدلة المرتبطة بالعقد</small>
                      </div>
                      <Documents
                        docs={current.documents}
                        caseId={current.id}
                        onUpdate={update}
                        notify={notify}
                        onText={setTextDoc}
                      />
                    </section>
                    {checks(step)}
                  </>
                ) : step === "year" ? (
                  <>
                    <section className="panel year-decision">
                      <span>
                        <CalendarDays size={31} />
                      </span>
                      <div>
                        <small>
                          وفق تاريخ العقد {D(current.contract_date)}
                        </small>
                        <h2>
                          {current.instruction_year
                            ? `تعليمات تنفيذ العقود لسنة ${current.instruction_year}`
                            : "تحتاج سنة العقد إلى تحديد مرجع"}
                        </h2>
                        <p>{current.year_warning}</p>
                      </div>
                    </section>
                    <Notice tone="warning" title="قاعدة تحديد السنة المطلوبة">
                      لعقود 2024 تُختار تعليمات 2014. ومن 2025 حتى السنة الحالية
                      تُختار تعليمات 2025. السنوات الأقدم لا تُحسم تلقائيًا.
                      يلزم فحص السريان والأحكام الانتقالية في النص الرسمي.
                    </Notice>
                    {!refs.some(
                      (r) =>
                        r.category === "instructions" &&
                        Number(r.reference_year) ===
                          Number(current.instruction_year),
                    ) && (
                      <Notice tone="warning">
                        النص الكامل لتعليمات{" "}
                        {current.instruction_year || "السنة المختارة"} غير متاح
                        في المكتبة.{" "}
                        <button
                          className="inline-link"
                          onClick={() => setLibrary(true)}
                        >
                          أضف النسخة الرسمية قبل اعتماد الفحص.
                        </button>
                      </Notice>
                    )}
                    <YearOverride
                      current={current}
                      onUpdate={update}
                      notify={notify}
                    />
                    {checks(step)}
                  </>
                ) : step === "quick" ? (
                  <>
                    <QuickForm
                      current={current}
                      schema={schema}
                      onUpdate={update}
                      notify={notify}
                    />
                    {checks(step)}
                  </>
                ) : step === "blacklist" ? (
                  <>
                    <Blacklist
                      current={current}
                      references={refs}
                      onUpdate={update}
                      notify={notify}
                    />
                    {checks(step)}
                  </>
                ) : step === "report" ? (
                  <Report current={current} onUpdate={update} notify={notify} />
                ) : (
                  <>
                    {["diwan", "cabinet", "structure"].includes(step) && (
                      <Notice tone="warning" title="تحقّق من الملاءمة الزمنية">
                        {step === "diwan"
                          ? "الأعمام المرفق مؤرخ في 17/8/2026 ويشير إلى قرار 398 لسنة 2026؛ لا يُطبق بأثر رجعي تلقائيًا."
                          : step === "cabinet"
                            ? "الدليل يتضمن قرار 398/2026 وكتاب تبليغه 32693 في 10/8/2026، مع مراجع سابقة. حدّد القرار النافذ ونطاقه دون دمج الأحكام."
                            : "برنامج التدقيق المرفق يحيل إلى تعليمات 2025؛ لا تنقل إحالاته إلى عقود 2024 تلقائيًا."}
                      </Notice>
                    )}
                    <section className="panel stage-references">
                      <div>
                        <BookOpen size={20} />
                        <div>
                          <h3>المراجع ذات الصلة</h3>
                          <p>
                            {related.length
                              ? `${N(related.length)} مرجع متاح للمراجعة`
                              : "أضف المرجع الرسمي المعتمد لهذه الخطوة"}
                          </p>
                        </div>
                      </div>
                      <button
                        className="btn outline small"
                        onClick={() => setLibrary(true)}
                      >
                        فتح المكتبة <ArrowLeft size={15} />
                      </button>
                      {related.length > 0 && (
                        <div className="reference-chips">
                          {related.map((r) => (
                            <a
                              key={r.id}
                              href={`/api/documents/${r.id}/file`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <FileText size={15} />
                              {r.name}
                              <ExternalLink size={12} />
                            </a>
                          ))}
                        </div>
                      )}
                    </section>
                    {checks(step)}
                    {step === "standard" && (
                      <section className="panel">
                        <h3 className="upload-heading">
                          إضافة وثائق قياسية لملف العقد
                        </h3>
                        <Notice>
                          اختر الوثيقة القياسية المناسبة لنوع العقد من{" "}
                          <a
                            className="inline-link"
                            href="https://mop.gov.iq/الوثائق-القياسية"
                            target="_blank"
                            rel="noreferrer"
                          >
                            الفهرس الرسمي لوزارة التخطيط{" "}
                            <ExternalLink size={13} />
                          </a>
                          ، وتحقق من الإصدار والسريان قبل رفعها. لا يُختار نموذج
                          تلقائيًا.
                        </Notice>
                        <UploadPanel
                          category="standard"
                          caseId={current.id}
                          onUpdate={update}
                          notify={notify}
                        />
                      </section>
                    )}
                  </>
                )}
              </div>
              <div className="stage-navigation">
                <button
                  className="btn outline"
                  disabled={idx === 0}
                  onClick={() => go(STEPS[idx - 1].id)}
                >
                  <ArrowRight size={16} /> الخطوة السابقة
                </button>
                <span>التعديلات هنا تحتاج إعادة تدقيق آلي قبل إخراج تقرير جديد</span>
                <button
                  className="btn primary"
                  disabled={idx === 8}
                  onClick={() => go(STEPS[idx + 1].id)}
                >
                  الخطوة التالية <ArrowLeft size={16} />
                </button>
              </div>
              </>}
            </>
          )}
        </main>
        <footer className="main-footer">
          <span>رقيب · نظام تدقيق العقود الحكومية</span>
          <span>الدليل أولًا، ثم النتيجة.</span>
        </footer>
      </div>
      {aiSettingsOpen && <AISettingsDialog Modal={Modal} onClose={() => setAiSettingsOpen(false)} onSaved={() => setAiSettingsVersion((version) => version + 1)} notify={notify} />}
      {form && (
        <CaseForm
          initial={form === "edit" ? current : null}
          onClose={() => setForm(null)}
          onSave={(c) => {
            update(c);
            setForm(null);
            setAdvancedReview(true);
            setStep("upload");
            notify("تم حفظ ملف التدقيق.");
          }}
        />
      )}
      {library && (
        <Library
          references={refs}
          guidance={guidance}
          onRefresh={refreshRefs}
          notify={notify}
          onText={setTextDoc}
          onClose={() => setLibrary(false)}
        />
      )}{" "}
      {textDoc && (
        <TextPreview doc={textDoc} onClose={() => setTextDoc(null)} />
      )}{" "}
      {toast && (
        <div
          className={"toast " + toast.type}
          role={toast.type === "error" ? "alert" : "status"}
        >
          {toast.type === "error" ? (
            <AlertCircle size={20} />
          ) : (
            <CheckCircle2 size={20} />
          )}
          <span>{toast.message}</span>
          <IButton title="إغلاق الإشعار" onClick={() => setToast(null)}>
            <X size={16} />
          </IButton>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
