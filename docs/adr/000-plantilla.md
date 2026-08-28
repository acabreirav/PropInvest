# ADR-000 · Plantilla

**Fuente:** nombre · **URL base:** · **Fecha:** · **Autor:** fuente-scout

## Contexto
Qué capa del pipeline alimenta y qué hueco cubre (referencia a `docs/00-hallazgos.md §13` si aplica).

## robots.txt
SHA256: `...` · snapshot: `data/raw/robots/{host}/{fecha}.txt`
```
<directivas relevantes, VERBATIM>
```

## Términos de servicio
URL · ¿legible? · cláusulas relevantes citadas, o **"no verificado"**.

## legal_tier
`api_oficial` | `json_publico` | `html_permitido` | `html_prohibido`

## Superficie técnica
| Aspecto | Hallazgo | Verificado |
|---|---|---|
| Endpoints | | ✅ / ❓ |
| Autenticación | | |
| Paginación y tope | | |
| Rate limit medido | | |
| JS rendering | | |
| WAF (`cf-ray`, `x-datadome`, `server`) | | |

## Esquema de campos
Campo → tipo → ejemplo → `evidence_level` esperado.

## Riesgo
🟢 / 🟡 / 🔴 y por qué.

## Decisión
**Construir** / **No construir** / **Escalar al humano**. Razón en una frase.

## Entrada para config/fuentes.yml
```yaml
- id:
  capa:
  legal_tier:
  enabled:
```
