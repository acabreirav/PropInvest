"""Envía el informe semanal por Gmail, 100% local y sin dependencias externas.

Las credenciales viven en `secrets/smtp.json` (gitignored, nunca se commitea):

    {
      "usuario": "tu.correo@gmail.com",
      "clave_de_aplicacion": "xxxx xxxx xxxx xxxx",
      "destinatario": "tu.correo@gmail.com"
    }

La `clave_de_aplicacion` NO es tu contraseña de Gmail: es una "contraseña de
aplicación" que Google genera para un solo uso/dispositivo (requiere tener
verificación en dos pasos activa). Se crea en https://myaccount.google.com/apppasswords
y se puede revocar en cualquier momento sin tocar tu cuenta.

Sin archivo de credenciales, el script lo dice y termina en éxito: el informe
igual queda en el Escritorio; el correo es un extra, no un requisito.
"""

from __future__ import annotations

import argparse
import json
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SECRETO = RAIZ / "secrets" / "smtp.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Envía el informe semanal por Gmail SMTP")
    parser.add_argument("--adjunto", required=True, help="ruta del PDF (o .txt) a adjuntar")
    parser.add_argument("--fecha", required=True, help="fecha del informe, AAAA-MM-DD")
    args = parser.parse_args()

    if not RUTA_SECRETO.exists():
        print(
            f"  correo: sin credenciales en {RUTA_SECRETO} — no se envía.\n"
            "  Para activarlo: copia secrets/smtp.ejemplo.json a secrets/smtp.json y\n"
            "  pon ahí una contraseña de aplicación de Google "
            "(https://myaccount.google.com/apppasswords)."
        )
        return 0

    secreto = json.loads(RUTA_SECRETO.read_text(encoding="utf-8"))
    adjunto = Path(args.adjunto)
    if not adjunto.exists():
        print(f"  correo: no existe el adjunto {adjunto} — no se envía.")
        return 1

    mensaje = EmailMessage()
    mensaje["From"] = secreto["usuario"]
    mensaje["To"] = secreto.get("destinatario", secreto["usuario"])
    mensaje["Subject"] = f"Flujo Cero — informe semanal {args.fecha}"
    mensaje.set_content(
        "Informe semanal de Flujo Cero adjunto.\n\n"
        "Contiene el ranking top 15 de oportunidades y los cambios de la semana: "
        "bajas de precio (señal de compra), avisos desaparecidos (probablemente "
        "vendidos) y avisos nuevos.\n\n"
        "Generado automáticamente por la tarea programada del domingo."
    )
    tipo = "application/pdf" if adjunto.suffix.lower() == ".pdf" else "text/plain"
    maintype, subtype = tipo.split("/")
    mensaje.add_attachment(
        adjunto.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=adjunto.name,
    )

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as servidor:
        servidor.starttls()
        servidor.login(secreto["usuario"], secreto["clave_de_aplicacion"].replace(" ", ""))
        servidor.send_message(mensaje)
    print(f"  correo: enviado a {mensaje['To']} con {adjunto.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
