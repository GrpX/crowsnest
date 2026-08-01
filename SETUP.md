# S.I.N.S. — Guía de instalación
## Fedora KDE (principal) y Windows 11 con WSL2

---

## A. FEDORA KDE

### 1. Dependencias del sistema

```bash
# Docker
sudo dnf install -y docker docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
# Cierra sesión y vuelve a entrar para que el grupo tome efecto

# Python y checkdmarc (para ./sins.sh captacion sin Docker)
sudo dnf install -y python3 python3-pip
pip install checkdmarc --user

# Verificar
checkdmarc --version
docker --version
```

### 2. Clonar el proyecto

```bash
git clone https://github.com/tu-usuario/sins-workstation.git
cd sins-workstation
chmod +x sins.sh
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
nano .env   # Agrega tus API keys (Shodan, GitHub, etc.)
```

### 4. Construir el contenedor (una sola vez, ~10 min)

```bash
docker-compose build
```

### 5. Verificar que todo funciona

```bash
# Prueba de captación (sin Docker)
./sins.sh captacion
# Escribe: google.cl → debería dar score 0 (bien configurado)
# Escribe: un dominio .cl que sepas que no tiene DMARC

# Prueba de flash (con Docker)
./sins.sh flash
```

---

## B. WINDOWS 11 CON WSL2

### 1. Instalar WSL2 con Ubuntu 24.04

Abre **PowerShell como Administrador** y ejecuta:

```powershell
wsl --install -d Ubuntu-24.04
```

Reinicia cuando lo pida. Al volver, Ubuntu se abre y pide crear usuario y contraseña.

### 2. Instalar Docker Desktop

- Descarga desde: https://www.docker.com/products/docker-desktop/
- Durante la instalación, marca **"Use WSL2 instead of Hyper-V"**
- Una vez instalado: Settings → Resources → WSL Integration → activa Ubuntu-24.04

### 3. Todo lo demás desde Ubuntu (WSL2)

Abre Ubuntu desde el menú inicio y ejecuta exactamente los mismos comandos de Fedora, **excepto** el bloque de Docker (Docker Desktop lo maneja por ti):

```bash
# Python y checkdmarc
sudo apt update && sudo apt install -y python3 python3-pip
pip install checkdmarc --user --break-system-packages

# Verificar Docker (debe responder sin sudo)
docker --version

# Clonar proyecto
git clone https://github.com/tu-usuario/sins-workstation.git
cd sins-workstation
chmod +x sins.sh

# Configurar .env
cp .env.example .env
nano .env

# Construir contenedor
docker-compose build

# Probar
./sins.sh captacion
```

### Nota sobre archivos en WSL2

Trabaja **siempre dentro de WSL2** (`~/sins-workstation`), no en `/mnt/c/...`.
Los archivos en `/mnt/c/` son lentos y Docker tiene problemas con los permisos.

El PDF generado queda en `~/sins-workstation/reportes/`. Para abrirlo en Windows:

```bash
# Opción 1: abrir el explorador de Windows en la carpeta actual
explorer.exe .

# Opción 2: la ruta en Windows es:
# \\wsl.localhost\Ubuntu-24.04\home\TU_USUARIO\sins-workstation\reportes\
```

---

## C. FLUJO DE USO DIARIO

### Calificar prospectos (Fedora o WSL2, sin Docker)

```bash
cd ~/sins-workstation
./sins.sh captacion
```

El script pregunta si quieres analizar 1 dominio, varios, o un archivo.
Para analizar una lista, ponla en `targets/prospectos.txt`, un dominio por línea:

```
estudiojuridico.cl
clinicadental.cl
contadores-asociados.cl
# Las líneas con # se ignoran
```

### Generar informe flash (Docker debe estar corriendo)

```bash
./sins.sh flash
```

Si corriste captación antes, el script te muestra los prospectos calientes del día
para elegir directamente. El PDF queda en `reportes/`.

---

## D. ESTRUCTURA DE CARPETAS

```
sins-workstation/
├── sins.sh                  ← EL único script que necesitas
├── docker-compose.yml       ← Contenedor de captación
├── docker-compose.work.yml  ← Stack APTRS (trabajo técnico, después)
├── Dockerfile
├── .env                     ← Tus API keys (no subir a Git)
├── .env.example             ← Template seguro
├── .gitignore
├── scripts/
│   ├── audit.sh             ← Corre dentro del contenedor
│   ├── pipeline.sh          ← Fase de trabajo técnico (después)
│   ├── nuclei_to_report.py  ← Convierte JSON → informe estructurado
│   └── generate_pdf.py      ← Genera el PDF de S.I.N.S.
├── targets/
│   └── prospectos.txt       ← Lista de dominios a calificar
├── reportes/                ← Todos los resultados (ignorado por Git)
│   ├── captacion_FECHA.txt
│   ├── prospectos_calientes_FECHA.txt
│   └── dominio_cl_FECHA/
│       ├── SINS_Flash_...pdf
│       └── ...
└── config/
    └── subfinder/
        └── provider-config.yaml
```
