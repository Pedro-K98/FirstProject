const API_BASE = window.localStorage.getItem("amana_api_base") || "http://127.0.0.1:8000";
const form = document.querySelector("#login-form");
const status = document.querySelector("#form-status");
const submit = form.querySelector(".submit-button");
const password = document.querySelector("#mot-de-passe");
const passwordToggle = document.querySelector("#password-toggle");

passwordToggle.addEventListener("click", () => {
  const visible = password.type === "text";
  password.type = visible ? "password" : "text";
  passwordToggle.setAttribute("aria-label", visible ? "Afficher le mot de passe" : "Masquer le mot de passe");
  passwordToggle.title = visible ? "Afficher le mot de passe" : "Masquer le mot de passe";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  status.textContent = "";
  submit.disabled = true;
  submit.querySelector("span").textContent = "Connexion...";

  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        identifiant: document.querySelector("#identifiant").value.trim(),
        mot_de_passe: password.value,
      }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Identifiant ou mot de passe incorrect.");
    }

    localStorage.setItem("amana_token", data.access_token);
    status.classList.add("success");
    status.textContent = "Connexion réussie.";
  } catch (error) {
    status.classList.remove("success");
    status.textContent = error instanceof TypeError
      ? "API indisponible. Lancez le serveur Amana sur le port 8000."
      : error.message.includes("Identifiants invalides")
        ? "Utilisez un compte résident. Le compte admin se connecte dans l'application desktop."
        : error.message;
  } finally {
    submit.disabled = false;
    submit.querySelector("span").textContent = "Se connecter";
  }
});
