// En modo Firebase el identificador es el correo electrónico; en modo local
// conserva el nombre de usuario tradicional.
(async () => {
  try {
    const response = await fetch("/api/login-info");
    if (!response.ok) return;
    const { modo } = await response.json();
    if (modo === "firebase") {
      document.getElementById("usuario-label").textContent = "Correo electrónico";
      const input = document.getElementById("usuario");
      input.type = "email";
      input.setAttribute("autocomplete", "email");
      input.setAttribute("placeholder", "nombre@ejemplo.com");
    }
  } catch (_error) {
    // Si falla, se conserva el rótulo por defecto.
  }
})();

document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorElement = document.getElementById("login-error");
  errorElement.textContent = "";
  const usuario = document.getElementById("usuario").value.trim();
  const password = document.getElementById("password").value;
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-EOIR-Request": "1" },
      body: JSON.stringify({ usuario, password }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      errorElement.textContent = data.error || "No se pudo iniciar sesión.";
      return;
    }
    window.location.href = "/";
  } catch (_error) {
    errorElement.textContent = "Error de conexión. Intenta de nuevo.";
  }
});
