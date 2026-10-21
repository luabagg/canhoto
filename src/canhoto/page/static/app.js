const KINDS = [
  "expense",
  "income",
  "transfer",
  "internal_transfer",
  "self_transfer",
  "card_payment",
];

const VIEWS = {
  overview: { title: "Overview", render: renderOverview },
  review: { title: "Review", render: renderReview },
  manual: { title: "Manual rows", render: renderManual },
  upload: { title: "Upload", render: renderUpload },
  rules: { title: "Rules", render: renderRules },
  export: { title: "Export", render: renderExport },
  settings: { title: "Settings", render: renderSettings },
};

const LAYOUT_KEY = "canhoto.layout";

const state = {
  api: "",
  view: "overview",
  months: [],
  month: "",
  reviewCursor: "",
  layout: localStorage.getItem(LAYOUT_KEY) || "canhoto",
};

document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  document.querySelectorAll(".nav button").forEach((button) => {
    button.addEventListener("click", () => show(button.dataset.view));
  });
  document.querySelector("#month-select").addEventListener("change", (event) => {
    state.month = event.target.value;
    state.reviewCursor = "";
    show(state.view);
  });
  try {
    const cfg = await readJson("/config.json");
    state.api = String(cfg.api_origin || "").replace(/\/$/, "");
    await checkApi();
    await loadMonths();
  } catch (error) {
    flash(error, true);
  }
  const start = location.hash.slice(1);
  await show(VIEWS[start] ? start : "overview");
}

async function checkApi() {
  const dot = document.querySelector("#api-dot");
  const label = document.querySelector("#api-label");
  try {
    const doctor = await api("/doctor");
    dot.className = doctor.ok ? "dot is-ok" : "dot is-bad";
    label.textContent = doctor.ok ? "API connected" : "Data dir needs attention";
  } catch (error) {
    dot.className = "dot is-bad";
    label.textContent = "API offline";
    throw error;
  }
}

async function loadMonths() {
  const payload = await api("/months");
  state.months = payload.months || [];
  if (!state.months.some((row) => row.month === state.month)) {
    state.month = state.months.length ? state.months[0].month : "";
  }
  const select = document.querySelector("#month-select");
  select.replaceChildren(
    ...(state.months.length
      ? state.months.map((row) => option(row.month, monthLabel(row)))
      : [option("", "No months yet")]),
  );
  select.value = state.month;
  select.disabled = !state.months.length;
  setStatus(monthStatus());
}

async function show(view) {
  state.view = view;
  history.replaceState(null, "", `#${view}`);
  document.querySelectorAll(".nav button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
  });
  document.querySelector("#view-title").textContent = VIEWS[view].title;
  const main = document.querySelector("#main");
  main.replaceChildren();
  try {
    await VIEWS[view].render(main);
  } catch (error) {
    flash(error, true);
  }
}

/* Overview */

async function renderOverview(main) {
  if (!state.month) {
    main.append(emptyCard("No ledger months yet. Upload a statement to start.", "Upload", "upload"));
    return;
  }
  const report = await api(`/breakdown?month=${encodeURIComponent(state.month)}`);
  const groups = report.breakdown.by_currency || {};
  const codes = Object.keys(groups);
  main.append(summaryCard(report.breakdown));
  if (!codes.length) {
    main.append(emptyCard("This month has no totals yet."));
    return;
  }
  codes.forEach((code) => main.append(currencyCard(code, groups[code])));
}

function summaryCard(breakdown) {
  const exportButton = button("Export PDF", () => show("export"), "primary");
  return card(`Summary · ${breakdown.month}`, [exportButton],
    el("div", { class: "stats" },
      stat("Rows", String(breakdown.transaction_count)),
      stat("Expense rows", String(breakdown.expense_count)),
      stat("Pending review", String(breakdown.pending_review)),
      stat("Currencies", String(Object.keys(breakdown.by_currency || {}).length)),
    ),
  );
}

function currencyCard(code, group) {
  const categories = Object.entries(group.by_category || {})
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  const bars = el("div", { class: "bars" },
    ...categories.map(([name, amount]) => barRow(name, amount, group.expenses)));
  return card(code, [],
    el("div", { class: "stats" },
      stat("Income", group.income),
      stat("Expenses", group.expenses),
      stat("Net", group.net),
    ),
    categories.length ? bars : el("p", { class: "muted", text: "No expenses this month." }),
  );
}

function barRow(name, amount, total) {
  const fill = el("i");
  fill.style.width = share(amount, total);
  return el("div", { class: "bar-row" },
    el("span", { text: name }),
    el("div", { class: "bar" }, fill),
    el("span", { class: "money", text: amount }),
  );
}

function share(amount, total) {
  const value = Number(amount);
  const whole = Number(total);
  if (!Number.isFinite(value) || !Number.isFinite(whole) || whole <= 0) return "0%";
  return `${Math.min(100, (value / whole) * 100)}%`;
}

/* Review */

async function renderReview(main) {
  if (!state.month) {
    main.append(emptyCard("Choose a month after you ingest a statement.", "Upload", "upload"));
    return;
  }
  const params = new URLSearchParams({ month: state.month });
  if (state.reviewCursor) params.set("cursor", state.reviewCursor);
  const batch = await api(`/review?${params}`);
  const items = batch.items || [];
  const runButton = button("Run rules", (event) => runRules(event.currentTarget));
  const body = items.length
    ? reviewTable(items)
    : el("p", { class: "empty", text: "Nothing is waiting in this batch." });
  main.append(card(`Pending review · ${state.month}`, [runButton], body, reviewPager(batch.next_cursor)));
}

function reviewTable(items) {
  return el("table", {},
    el("thead", {}, el("tr", {},
      ...["Date", "Merchant", "Amount", "Category", "Kind", "Keep", ""].map((h) => el("th", { text: h })))),
    el("tbody", {}, ...items.map(reviewRow)),
  );
}

function reviewRow(item) {
  const category = el("input", { type: "text", value: item.current_category || "" });
  const kind = select(KINDS, item.current_kind || "expense");
  const keep = el("input", { type: "checkbox", checked: false, title: "Keep in review" });
  const save = button("Save", () => saveReview(item, category, kind, keep, save), "primary");
  const remember = button("Remember", () => rememberMerchant(item.merchant_display, category.value));
  const merchant = el("td", {}, el("div", { text: item.merchant_display || "Unidentified merchant" }));
  if (item.rule_note) merchant.append(el("p", { class: "muted", text: item.rule_note }));
  return el("tr", {},
    el("td", { text: item.date }),
    merchant,
    el("td", { class: "num", text: `${item.amount || ""} ${item.currency}` }),
    el("td", {}, category),
    el("td", {}, kind),
    el("td", {}, keep),
    el("td", {}, el("div", { class: "actions" }, save, remember)),
  );
}

function reviewPager(nextCursor) {
  const bar = el("div", { class: "actions" });
  if (state.reviewCursor) {
    bar.append(button("First batch", () => {
      state.reviewCursor = "";
      show("review");
    }));
  }
  if (nextCursor) {
    bar.append(button("Next batch", () => {
      state.reviewCursor = nextCursor;
      show("review");
    }));
  }
  return bar;
}

async function saveReview(item, category, kind, keep, saveButton) {
  await busy(saveButton, async () => {
    await api("/categories", jsonBody("POST", {
      patches: [{
        id: item.id,
        category: category.value,
        kind: kind.value,
        is_expense: kind.value === "expense",
        needs_review: keep.checked,
        review_reason: keep.checked ? item.review_reason : null,
      }],
    }));
    await loadMonths();
    await show("review");
  });
}

async function rememberMerchant(merchant, category) {
  try {
    await api("/merchants", jsonBody("POST", { merchant_key: merchant, category }));
    flash(`Stored ${merchant} as ${category}. Run rules to apply it.`);
  } catch (error) {
    flash(error, true);
  }
}

async function runRules(runButton) {
  await busy(runButton, async () => {
    const result = await api("/rules/run", jsonBody("POST", { month: state.month }));
    await loadMonths();
    await show(state.view);
    flash(`Rules updated ${result.applied} rows. ${result.pending_review} still need review.`);
  });
}

/* Manual rows */

async function renderManual(main) {
  main.append(manualForm());
  if (!state.month) return;
  const rows = await api(`/manual?month=${encodeURIComponent(state.month)}`);
  const list = rows.transactions || [];
  const body = list.length
    ? el("table", {},
      el("thead", {}, el("tr", {},
        ...["Date", "Description", "Amount", "Category", ""].map((h) => el("th", { text: h })))),
      el("tbody", {}, ...list.map(manualRow)))
    : el("p", { class: "empty", text: "No manual rows this month." });
  main.append(card(`Manual rows · ${state.month}`, [], body));
}

function manualForm() {
  const inputs = {
    date: el("input", { type: "date", required: true }),
    amount: el("input", { type: "text", placeholder: "-12.34", required: true }),
    description: el("input", { type: "text", required: true }),
    currency: el("input", { type: "text", placeholder: "Default" }),
    category: el("input", { type: "text" }),
    merchant: el("input", { type: "text" }),
    account: el("input", { type: "text" }),
    note: el("input", { type: "text" }),
  };
  const submit = button("Add row", null, "primary");
  submit.type = "submit";
  const form = el("form", { class: "grid" },
    ...Object.entries(inputs).map(([key, input]) => labelled(capitalize(key), input)),
    submit,
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    addManual(inputs, submit);
  });
  return card("Add a manual row", [], form);
}

async function addManual(inputs, submit) {
  const payload = {
    date: inputs.date.value,
    amount: inputs.amount.value,
    description: inputs.description.value,
    note: inputs.note.value,
  };
  ["currency", "category", "merchant", "account"].forEach((key) => {
    if (inputs[key].value.trim()) payload[key] = inputs[key].value.trim();
  });
  await busy(submit, async () => {
    const result = await api("/manual", jsonBody("POST", payload));
    state.month = result.transaction.date.slice(0, 7);
    await loadMonths();
    await show("manual");
    flash("Manual row added.");
  });
}

function manualRow(row) {
  const description = el("input", { type: "text", value: row.description });
  const amount = el("input", { type: "text", value: row.amount });
  const category = el("input", { type: "text", value: row.category || "" });
  const save = button("Save", () => editManual(row, { description, amount, category }, save), "primary");
  const remove = button("Remove", () => removeManual(row, remove), "danger");
  return el("tr", {},
    el("td", { text: row.date }),
    el("td", {}, description),
    el("td", {}, el("div", { class: "actions" }, amount, el("span", { class: "muted", text: row.currency }))),
    el("td", {}, category),
    el("td", {}, el("div", { class: "actions" }, save, remove)),
  );
}

async function editManual(row, inputs, saveButton) {
  const body = { description: inputs.description.value, amount: inputs.amount.value };
  if (inputs.category.value.trim()) body.category = inputs.category.value.trim();
  await busy(saveButton, async () => {
    await api(`/manual/${encodeURIComponent(row.id)}`, jsonBody("PATCH", body));
    await loadMonths();
    await show("manual");
    flash("Manual row saved.");
  });
}

async function removeManual(row, removeButton) {
  await busy(removeButton, async () => {
    await api(`/manual/${encodeURIComponent(row.id)}`, { method: "DELETE" });
    await loadMonths();
    await show("manual");
    flash("Manual row removed.");
  });
}

/* Upload */

async function renderUpload(main) {
  const parsers = await api("/parsers");
  const file = el("input", { type: "file", accept: ".pdf,.txt,.text", multiple: true, required: true });
  const password = el("input", { type: "password", autocomplete: "off" });
  const submit = button("Ingest", null, "primary");
  submit.type = "submit";
  const form = el("form", { class: "grid" },
    labelled("Statements (.pdf or .txt)", file),
    labelled("PDF password (optional)", password),
    submit,
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendUpload(file, password, submit);
  });
  main.append(card("Upload statements", [],
    el("p", { class: "muted", text: "Files are saved in the Canhoto home inbox, then ingested by an enabled parser." }),
    form,
  ));
  main.append(parsersCard(parsers.parsers || []));
}

async function sendUpload(fileInput, passwordInput, submit) {
  const body = new FormData();
  Array.from(fileInput.files || []).forEach((file) => body.append("file", file));
  if (passwordInput.value) body.append("pdf_password", passwordInput.value);
  await busy(submit, async () => {
    try {
      const result = await api("/ingest", { method: "POST", body });
      fileInput.value = "";
      await loadMonths();
      flash(`Ingested ${result.transaction_count} rows from ${result.file_count} file(s).`);
    } finally {
      passwordInput.value = "";
    }
  });
}

function parsersCard(parsers) {
  const body = parsers.length
    ? el("table", {},
      el("thead", {}, el("tr", {}, ...["Parser", "Status", "Last test"].map((h) => el("th", { text: h })))),
      el("tbody", {}, ...parsers.map((parser) => el("tr", {},
        el("td", { text: parser.id }),
        el("td", {}, el("span", {
          class: parser.enabled ? "badge ok" : "badge",
          text: parser.enabled ? "enabled" : "disabled",
        })),
        el("td", { class: "muted", text: parser.last_test_at || "never" }),
      ))))
    : el("p", { class: "empty", text: "No parsers registered. Create one with the CLI or an agent." });
  return card("Parsers", [], body);
}

/* Rules */

async function renderRules(main) {
  const rules = await api("/rules");
  main.append(ruleForm());
  const list = rules.rules || [];
  const body = list.length
    ? el("table", {},
      el("thead", {}, el("tr", {},
        ...["#", "Pattern", "Match", "Result", "Note", ""].map((h) => el("th", { text: h })))),
      el("tbody", {}, ...list.map(ruleRow)))
    : el("p", { class: "empty", text: "No rules yet." });
  main.append(card("Rules in evaluation order", [], body));
}

function ruleForm() {
  const inputs = {
    pattern: el("input", { type: "text", required: true, placeholder: "Regular expression" }),
    category: el("input", { type: "text", required: true }),
    kind: select(KINDS, "expense"),
    direction: select(["any", "in", "out"], "any"),
    currency: el("input", { type: "text", placeholder: "Any" }),
    min_amount: el("input", { type: "text" }),
    max_amount: el("input", { type: "text" }),
    note: el("input", { type: "text" }),
  };
  const review = el("input", { type: "checkbox" });
  const submit = button("Add rule", null, "primary");
  submit.type = "submit";
  const form = el("form", { class: "grid" },
    ...Object.entries(inputs).map(([key, input]) => labelled(capitalize(key.replace("_", " ")), input)),
    el("label", { class: "check" }, review, el("span", { text: "Keep matches in review" })),
    submit,
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    addRule(inputs, review, submit);
  });
  return card("Add a rule", [], form);
}

async function addRule(inputs, review, submit) {
  const payload = {
    pattern: inputs.pattern.value,
    category: inputs.category.value,
    kind: inputs.kind.value,
    direction: inputs.direction.value,
    note: inputs.note.value,
    needs_review: review.checked,
  };
  ["currency", "min_amount", "max_amount"].forEach((key) => {
    if (inputs[key].value.trim()) payload[key] = inputs[key].value.trim();
  });
  await busy(submit, async () => {
    await api("/rules", jsonBody("POST", payload));
    await show("rules");
    flash("Rule added. Run rules on a month to apply it.");
  });
}

function ruleRow(rule) {
  const bounds = rule.min_amount || rule.max_amount
    ? ` · ${rule.min_amount || "0"} to ${rule.max_amount || "any"}`
    : "";
  const remove = button("Remove", () => removeRule(rule, remove), "danger");
  return el("tr", {},
    el("td", { class: "muted", text: String(rule.priority) }),
    el("td", {}, el("code", { text: rule.pattern })),
    el("td", { class: "muted", text: `${rule.direction} · ${rule.currency || "any currency"}${bounds}` }),
    el("td", { text: `${rule.category} (${rule.kind})${rule.needs_review ? " · review" : ""}` }),
    el("td", { class: "muted", text: rule.note || "" }),
    el("td", {}, remove),
  );
}

async function removeRule(rule, removeButton) {
  await busy(removeButton, async () => {
    await api(`/rules/${rule.id}`, { method: "DELETE" });
    await show("rules");
    flash("Rule removed.");
  });
}

/* Export */

async function renderExport(main) {
  if (!state.month) {
    main.append(emptyCard("Choose a month after you ingest a statement.", "Upload", "upload"));
    return;
  }
  const payload = await api("/export/profiles");
  const profiles = payload.profiles || [];
  if (!profiles.some((profile) => profile.id === state.layout)) state.layout = payload.default;
  const preview = el("div", { class: "preview" });
  const layouts = el("div", { class: "layouts" },
    ...profiles.map((profile) => layoutCard(profile, preview)));
  const download = button("Save and download", (event) => downloadPdf(event.currentTarget), "primary");
  main.append(card(`Layout · ${state.month}`, [download], layouts));
  main.append(card("Preview", [], preview));
  await renderPreview(preview);
}

let previewToken = 0;

async function renderPreview(preview) {
  const token = ++previewToken;
  preview.replaceChildren(el("p", { class: "empty", text: "Rendering preview…" }));
  const params = new URLSearchParams({ month: state.month, profile: state.layout });
  try {
    const payload = await api(`/export/pdf/preview?${params}`);
    if (token !== previewToken) return;
    preview.replaceChildren(...payload.pages.map((png, index) => el("img", {
      class: "preview-page",
      src: `data:image/png;base64,${png}`,
      alt: `Page ${index + 1} of ${payload.page_count}`,
    })));
  } catch (error) {
    if (token !== previewToken) return;
    preview.replaceChildren(el("p", { class: "empty", text: error.message }));
  }
}

function layoutCard(profile, preview) {
  const node = el("button", {
    type: "button",
    class: profile.id === state.layout ? "layout is-selected" : "layout",
  },
  el("strong", { text: profile.id }),
  el("span", { text: profile.summary }));
  node.addEventListener("click", () => {
    state.layout = profile.id;
    localStorage.setItem(LAYOUT_KEY, profile.id);
    node.parentElement.querySelectorAll(".layout").forEach((item) => item.classList.remove("is-selected"));
    node.classList.add("is-selected");
    renderPreview(preview);
  });
  return node;
}

async function downloadPdf(downloadButton) {
  await busy(downloadButton, async () => {
    const blob = await api("/export/pdf", jsonBody("POST", { month: state.month, profile: state.layout }));
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: `${state.month}-summary.pdf` });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    flash(`Saved ${state.month}-summary.pdf in the Canhoto exports folder.`);
  });
}

/* Settings */

async function renderSettings(main) {
  const [doctor, currency, parsers] = await Promise.all([
    api("/doctor"),
    api("/config/currency"),
    api("/parsers"),
  ]);
  main.append(currencySettingsCard(currency.value || ""));
  main.append(card("Health", [el("span", {
    class: doctor.ok ? "badge ok" : "badge",
    text: doctor.ok ? "ok" : "needs attention",
  })],
  el("p", { class: "muted", text: doctor.data_dir }),
  el("ul", { class: "checks" }, ...(doctor.checks || []).map((line) => el("li", { text: line }))),
  ));
  main.append(parsersCard(parsers.parsers || []));
}

function currencySettingsCard(value) {
  const code = el("input", { type: "text", value, maxlength: "3" });
  const save = button("Save", null, "primary");
  save.type = "submit";
  const inherit = button("Use inherited", () => clearCurrency(inherit));
  const form = el("form", { class: "grid" }, labelled("Default currency for this ledger", code), save, inherit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    saveCurrency(code.value, save);
  });
  return card("Currency", [], form);
}

async function saveCurrency(value, saveButton) {
  await busy(saveButton, async () => {
    await api("/config/currency", jsonBody("PUT", { value }));
    await show("settings");
    flash("Currency saved.");
  });
}

async function clearCurrency(clearButton) {
  await busy(clearButton, async () => {
    await api("/config/currency", { method: "DELETE" });
    await show("settings");
    flash("This ledger now inherits the global currency.");
  });
}

/* Shared helpers */

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([key, value]) => {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key in node && typeof value !== "string") node[key] = value;
    else if (key === "value") node.value = value;
    else node.setAttribute(key, value);
  });
  children.filter(Boolean).forEach((child) => node.append(child));
  return node;
}

function card(title, actions, ...body) {
  return el("section", { class: "card" },
    el("div", { class: "card-head" },
      el("h2", { text: title }),
      actions.length ? el("div", { class: "actions" }, ...actions) : null),
    el("div", { class: "card-body" }, ...body),
  );
}

function emptyCard(message, actionLabel, view) {
  const body = el("div", { class: "empty" }, el("p", { text: message }));
  if (actionLabel) {
    const go = button(actionLabel, () => show(view), "primary");
    body.append(el("div", { class: "actions" }, go));
  }
  return el("section", { class: "card" }, body);
}

function stat(label, value) {
  return el("div", { class: "stat" }, el("span", { text: label }), el("strong", { text: value }));
}

function button(label, onClick, variant) {
  const node = el("button", { type: "button", class: variant ? `btn ${variant}` : "btn", text: label });
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

function labelled(text, input) {
  return el("label", {}, el("span", { text }), input);
}

function select(values, selected) {
  const node = el("select", {}, ...values.map((value) => option(value, value)));
  node.value = selected;
  return node;
}

function option(value, label) {
  return el("option", { value, text: label });
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function monthLabel(row) {
  return row.pending_review ? `${row.month} · ${row.pending_review} to review` : row.month;
}

function monthStatus() {
  if (!state.months.length) return "No ledger months yet.";
  const pending = state.months.reduce((sum, row) => sum + Number(row.pending_review || 0), 0);
  return `${state.months.length} month(s) · ${pending} row(s) need review`;
}

function setStatus(text) {
  document.querySelector("#status-line").textContent = text;
}

function flash(message, isError) {
  const node = document.querySelector("#flash");
  node.textContent = message instanceof Error ? message.message : String(message);
  node.className = isError ? "flash is-error" : "flash";
  node.hidden = false;
}

async function busy(control, work) {
  control.disabled = true;
  try {
    await work();
  } catch (error) {
    flash(error, true);
  } finally {
    control.disabled = false;
  }
}

async function api(path, options) {
  const response = await fetch(state.api + path, options);
  const type = response.headers.get("content-type") || "";
  if (response.ok && type.includes("application/pdf")) return response.blob();
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

async function readJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

function jsonBody(method, body) {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}
