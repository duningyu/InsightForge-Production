"use strict";
document.querySelector("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const action = event.submitter?.value || "login";
  const message = document.querySelector("#account-message");
  const values = new FormData(form);
  const payload = {username: values.get("username"), password: values.get("password")};
  if (action === "claim") payload.invite = values.get("invite");
  for (const button of form.querySelectorAll("button")) button.disabled = true;
  message.textContent = "正在处理…";
  try {
    const response = await fetch(`/api/auth/${action}`, {method: "POST",
      headers: {"Content-Type": "application/json", "X-InsightForge-Request": "1"}, body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "账号操作未完成");
    if (action === "login") { form.reset(); location.replace("/"); }
    else { form.elements.invite.value = ""; message.textContent = result.message; }
  } catch (error) { message.textContent = error.message; }
  finally { for (const button of form.querySelectorAll("button")) button.disabled = false; }
});
