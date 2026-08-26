# Despliegue en la nube — pasos manuales

Este documento cubre **solo lo que no se puede hacer desde el asistente**:
crear cuentas, aprobar accesos, generar secretos y configurarlos. Todo el
código de infraestructura (Dockerfile, docker-compose.yml, Caddyfile,
GitHub Actions, scripts de backup, sistema de login) ya está en el repo,
committeado en la rama de trabajo.

Si en algún paso algo no coincide con lo que ves en pantalla (Oracle Cloud
cambia su UI seguido), no improvises — avisa con una captura y se ajusta la
guía.

---

## 1. Cuenta de Oracle Cloud + VM "Always Free"

Se eligió Oracle Cloud porque es la única nube que da una VM persistente
**gratis para siempre** (no solo un trial) — Render/Railway/Fly.io hoy
piden tarjeta o borran el disco al reiniciar.

1. Crear cuenta en https://www.oracle.com/cloud/free/ (pide tarjeta para
   verificar identidad, pero el tier "Always Free" no cobra mientras te
   quedes dentro de sus límites).
2. Al crear la instancia:
   - **Imagen**: Ubuntu 22.04 (o la LTS más reciente disponible).
   - **Forma (shape)**: `VM.Standard.A1.Flex` (ARM, Ampere) — es la que
     entra en el tier gratis (hasta 4 OCPU / 24 GB RAM sin costo). Si en tu
     región dice "Out of capacity", reintentar más tarde o cambiar de
     región al crear la cuenta — es un problema conocido de Oracle, no
     tuyo.
   - Guardar la clave SSH que genera (o subir tu propia clave pública) —
     la vas a necesitar dos veces: para entrar vos, y para el secret de
     GitHub Actions del paso 5.
3. **Red**: en la lista de seguridad (Security List) del VCN, agregar
   reglas de entrada (Ingress) para los puertos **80** y **443** desde
   `0.0.0.0/0` (además del 22/SSH que ya viene). Sin esto, Caddy no puede
   servir HTTPS aunque el firewall del sistema operativo esté bien.
4. Conectate por SSH y confirmá que entrás:
   ```
   ssh -i tu-clave.pem ubuntu@<IP-de-la-VM>
   ```

## 2. Instalar Docker en la VM

Dentro de la VM (por SSH):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

Verificar: `docker --version` y `docker compose version`.

## 3. Clonar el repo en la VM

```bash
cd ~
git clone https://github.com/byospl1/legal.git
cd legal
```

Si el repo es privado, necesitás autenticarte (token personal de GitHub o
una clave de deploy). La forma más simple: generar un **Personal Access
Token** (Settings → Developer settings → Fine-grained tokens, solo lectura
sobre este repo) y clonar con
`https://<token>@github.com/byospl1/legal.git`.

## 4. Dominio (HTTPS automático)

Caddy pide el certificado solo, pero necesita un dominio real apuntando a
la IP de la VM:

- **Si ya tenés un dominio**: creá un registro A `eoir.tudominio.com` →
  IP de la VM.
- **Si no tenés dominio**: usá un subdominio gratis de
  [DuckDNS](https://www.duckdns.org/) (ej. `kostiv-eoir.duckdns.org`) — es
  gratis, sin tarjeta, y Caddy lo acepta igual que un dominio propio.

Mientras el DNS todavía no propaga (puede tardar unos minutos a un par de
horas), podés probar por HTTP plano con `Caddyfile.sin-dominio`:
```bash
cp Caddyfile Caddyfile.con-https        # respaldar el real
cp Caddyfile.sin-dominio Caddyfile
docker compose up -d
# probar por http://<IP-de-la-VM> ...

# una vez que el dominio ya resuelve, volver al Caddyfile con HTTPS:
cp Caddyfile.con-https Caddyfile
docker compose up -d
```

## 5. Variables de entorno (`.env`)

En `~/legal` (la VM), copiar y completar:

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # pegar en SECRET_KEY
nano .env    # completar SECRET_KEY y DOMAIN
```

## 6. Primer arranque

```bash
docker compose up -d --build
docker compose logs -f app       # confirmar que arrancó sin errores, Ctrl+C para salir
```

Probar en el navegador: `https://tu-dominio` — debería redirigir a
`/login`.

## 7. Crear el primer usuario (login)

```bash
docker compose exec app python3 scripts/manage_users.py create hugo "una-contraseña-segura" "Hugo"
```

Repetir por cada persona del despacho que vaya a usar el sistema. Ver
`scripts/manage_users.py` para listar/borrar/cambiar contraseña.

## 8. Subir las firmas escaneadas

Las firmas (PNG de abogados/preparadores) nunca viajan por git — hay que
copiarlas a mano al volumen persistente la primera vez:

```bash
docker cp ./firmas/abogados/. $(docker compose ps -q app):/app/firmas/abogados/
docker cp ./firmas/preparadores/. $(docker compose ps -q app):/app/firmas/preparadores/
```

(si las tenés en tu máquina local y no en la VM, primero hay que subirlas a
la VM con `scp`, en la misma carpeta `firmas/abogados` / `firmas/preparadores`).

## 9. GitHub Actions — deploy automático

En GitHub → repo `byospl1/legal` → Settings → Secrets and variables →
Actions → New repository secret, agregar:

| Secret | Valor |
|---|---|
| `DEPLOY_HOST` | IP o dominio de la VM |
| `DEPLOY_USER` | `ubuntu` (o el usuario que uses por SSH) |
| `DEPLOY_SSH_KEY` | el contenido de la clave PRIVADA SSH que usás para entrar a la VM |

A partir de ahí, cada `git push` a `main` reconstruye y reinicia el
contenedor solo (ver `.github/workflows/deploy.yml`). El primer deploy
automático solo funciona si el clon de `~/legal` en la VM ya existe (paso
3) — el workflow hace `git pull` + `docker compose up --build`, no clona
desde cero.

**Importante**: el workflow hace `git reset --hard origin/main` en la VM
— cualquier cambio hecho a mano directo en el clon de la VM se pierde en
el próximo deploy. Tratá ese clon como un destino de despliegue, no un
lugar para editar código.

## 10. Backups cifrados (Backblaze B2)

1. Crear cuenta gratis en https://www.backblaze.com/cloud-storage (10GB
   gratis, alcanza de sobra para JSON + PNG de firmas).
2. Crear un bucket privado (ej. `kostiv-eoir-backup`) y una **Application
   Key** con acceso solo a ese bucket.
3. Instalar restic en la VM:
   ```bash
   sudo apt-get update && sudo apt-get install -y restic
   ```
4. Crear `/root/.restic-env` (fuera de git, con permisos restringidos):
   ```bash
   sudo tee /root/.restic-env <<'EOF'
   export RESTIC_REPOSITORY=b2:kostiv-eoir-backup:eoir
   export RESTIC_PASSWORD=una-contraseña-distinta-y-larga-que-guardes-aparte
   export B2_ACCOUNT_ID=tu-key-id
   export B2_ACCOUNT_KEY=tu-application-key
   EOF
   sudo chmod 600 /root/.restic-env
   ```
   **Guardá `RESTIC_PASSWORD` en un lugar seguro aparte** (ej. el gestor de
   contraseñas del despacho) — sin ella el backup queda cifrado e
   irrecuperable, ni siquiera Backblaze puede abrirlo.
5. Probar manualmente: `sudo bash ~/legal/scripts/backup.sh`
6. Programar por cron (todas las noches a las 3am):
   ```bash
   sudo crontab -e
   # agregar:
   0 3 * * * /usr/bin/bash /home/ubuntu/legal/scripts/backup.sh >> /var/log/eoir-backup.log 2>&1
   ```

Para restaurar en caso de desastre: `restic restore latest --target /ruta/de/recuperacion`
(con las mismas variables de `/root/.restic-env` cargadas).

## 11. Verificación final

- [ ] `https://tu-dominio` carga y pide login (candado verde, sin
      advertencia de certificado).
- [ ] Login con el usuario creado en el paso 7 funciona.
- [ ] Generar un documento de prueba (caso ficticio, sin datos reales) y
      confirmar que el PDF sale bien formado — esto valida que LibreOffice
      quedó instalado correctamente en el contenedor.
- [ ] `docker compose logs -f app` no muestra errores al generar.
- [ ] El backup manual del paso 10.5 corrió sin errores.
- [ ] Push de prueba a `main` dispara el Action y el sitio sigue
      funcionando después.

Una vez confirmado todo esto, recién ahí cargar datos reales de clientes.
