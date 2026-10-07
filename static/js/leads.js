"use strict";

// Сервер остаётся источником проверки данных и допустимых статусов.
const notification = document.querySelector("#notification");
try {
  const message = sessionStorage.getItem("crm-notification");
  if (message && notification) {
    notification.textContent = message;
    notification.hidden = false;
    sessionStorage.removeItem("crm-notification");
  }
} catch (_) { /* Уведомления не должны зависеть от разрешения на хранилище. */ }

async function sendJSON(url, method, data) {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(data),
  });
  let result;
  try { result = await response.json(); }
  catch (_) { throw new Error("Сервер вернул неожиданный ответ. Попробуйте ещё раз."); }
  if (!response.ok) {
    const error = new Error(result.error?.message || "Не удалось сохранить изменения.");
    error.details = result.error?.details || [];
    throw error;
  }
  return result;
}

function showError(form, error) {
  const summary = form.querySelector(".form-error");
  summary.textContent = error instanceof TypeError
    ? "Не удалось связаться с сервером. Проверьте соединение и попробуйте ещё раз."
    : error.message;
  summary.hidden = false;
  let firstInvalid;
  for (const detail of error.details || []) {
    const input = form.elements.namedItem(detail.field);
    const target = form.querySelector(`[id="${detail.field}-error"]`);
    if (input && target) {
      target.textContent = detail.message;
      input.setAttribute("aria-invalid", "true");
      firstInvalid ||= input;
    }
  }
  return firstInvalid;
}

function notifyAfterReload(message) {
  try { sessionStorage.setItem("crm-notification", message); }
  catch (_) { /* Сохранение заявки работает и без sessionStorage. */ }
}

async function refreshLists() {
  const destination = new URL(window.location.href);
  destination.searchParams.delete("offset");
  destination.hash = "";
  const response = await fetch(destination, { headers: { "Accept": "text/html" } });
  if (!response.ok) throw new Error("Не удалось обновить список.");
  const page = new DOMParser().parseFromString(await response.text(), "text/html");
  for (const selector of [".statistics", ".list-panel"]) {
    document.querySelector(selector).replaceWith(page.querySelector(selector));
  }
  history.replaceState(null, "", destination);
}

const leadForm = document.querySelector("#lead-form");
leadForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (leadForm.dataset.busy === "true") return;
  const data = Object.fromEntries(new FormData(leadForm));
  leadForm.querySelectorAll(".field-error").forEach((element) => { element.textContent = ""; });
  leadForm.querySelectorAll("[aria-invalid]").forEach((element) => element.removeAttribute("aria-invalid"));
  leadForm.querySelector(".form-error").hidden = true;
  const fieldset = leadForm.querySelector("fieldset");
  const button = leadForm.querySelector("button[type=submit]");
  const buttonText = button.textContent;
  leadForm.dataset.busy = "true";
  leadForm.setAttribute("aria-busy", "true");
  fieldset.disabled = true;
  button.textContent = "Сохраняем…";
  try {
    const created = await sendJSON(leadForm.action, "POST", data);
    leadForm.reset();
    notification.textContent = `Заявка №${created.id} создана.`;
    notification.hidden = false;
    if (created.telegram_subscription_url) {
      const link = document.createElement("a");
      link.href = created.telegram_subscription_url;
      link.textContent = "Получать уведомления в Telegram";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      notification.append(link);
      // Одноразовый код остаётся только в ответе создания и текущем DOM.
    }
    try { await refreshLists(); }
    catch (_) {
      notification.append(document.createTextNode(" Заявка сохранена; список не обновился. Обновите страницу после подключения уведомлений."));
    }
    fieldset.disabled = false;
    button.textContent = buttonText;
    leadForm.dataset.busy = "false";
    leadForm.removeAttribute("aria-busy");
  } catch (error) {
    const invalid = showError(leadForm, error);
    fieldset.disabled = false;
    button.textContent = buttonText;
    leadForm.dataset.busy = "false";
    leadForm.removeAttribute("aria-busy");
    invalid?.focus();
  }
});

document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form.matches(".status-form")) return;
    event.preventDefault();
    if (form.dataset.busy === "true") return;
    const select = form.querySelector("select");
    const button = form.querySelector("button");
    const status = select.value;
    form.querySelector(".form-error").hidden = true;
    form.dataset.busy = "true";
    form.setAttribute("aria-busy", "true");
    select.disabled = true;
    button.disabled = true;
    button.textContent = "Сохраняем…";
    try {
      await sendJSON(form.action, "PATCH", { status });
      notifyAfterReload("Статус заявки обновлён.");
      window.location.reload();
    } catch (error) {
      showError(form, error);
      select.disabled = false;
      button.disabled = false;
      button.textContent = "Сохранить";
      form.dataset.busy = "false";
      form.removeAttribute("aria-busy");
    }
});
