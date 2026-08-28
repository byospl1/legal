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
  const submitButton = event.currentTarget.querySelector('button[type="submit"]');
  errorElement.classList.remove("update-status");
  errorElement.textContent = "";
  submitButton.disabled = true;
  submitButton.textContent = "Verificando…";
  const usuario = document.getElementById("usuario").value.trim();
  const password = document.getElementById("password").value;
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-EOIR-Request": "1" },
      body: JSON.stringify({ usuario, password }),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 426 && data.actualizando) {
      document.getElementById("password").value = "";
      errorElement.classList.add("update-status");
      errorElement.textContent = data.mensaje || "Actualizando y reiniciando…";
      submitButton.textContent = "Actualizando…";
      await esperarVersion(data.version);
      window.location.reload();
      return;
    }
    if (!response.ok) {
      errorElement.textContent = data.error || "No se pudo iniciar sesión.";
      submitButton.disabled = false;
      submitButton.textContent = "Entrar";
      return;
    }
    window.location.href = "/";
  } catch (_error) {
    errorElement.textContent = "Error de conexión. Intenta de nuevo.";
    submitButton.disabled = false;
    submitButton.textContent = "Entrar";
  }
});

async function esperarVersion(versionEsperada) {
  for (let intento = 0; intento < 120; intento += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    try {
      const response = await fetch(`/healthz?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) continue;
      const data = await response.json();
      if (data.version === versionEsperada) return;
    } catch (_error) {
      // Es normal mientras el servidor anterior se cierra y el nuevo inicia.
    }
  }
  throw new Error("La actualización tardó demasiado");
}
