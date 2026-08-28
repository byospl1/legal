// Esta página no carga app.js, así que consulta por separado si debe mostrar
// el cierre de sesión.
(async () => {
  const logoutLink = document.getElementById("logout-link");
  if (!logoutLink) return;
  let loginHabilitado = false;
  try {
    const response = await fetch("/api/init");
    if (response.ok) loginHabilitado = (await response.json()).login_habilitado === true;
  } catch (_error) {
    // Si falla, se oculta el enlace.
  }
  if (!loginHabilitado) {
    logoutLink.style.display = "none";
    return;
  }
  logoutLink.addEventListener("click", async (event) => {
    event.preventDefault();
    await fetch("/api/logout", { method: "POST", headers: { "X-EOIR-Request": "1" } });
    window.location.href = "/login";
  });
})();
