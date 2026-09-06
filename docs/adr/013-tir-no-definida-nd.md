# ADR 013 · TIR no certificable ⇒ ND explícito que excluye — no MIRR, jamás −100%

fecha: 2026-09-06 · estado: aceptada · tarea: T-943 · origen: verificador §7.6 (03-sep, F5)

## Contexto

`core.tir()` resuelve por bisección y solo puede **certificar** su resultado cuando los
flujos tienen exactamente un cambio de signo (raíz única en (−1, ∞)). El verificador
encontró que `[-100, 230, -132]` tiene raíces en 10% y 20% con VAN negativo en ambos
extremos del intervalo: la bisección lanzaba `ValueError` y `evaluar()` lo guardaba como
`tir_real = −1` — **la peor TIR posible, imputada en silencio sobre el 20% del score**.
Hoy el caso es inalcanzable (los flujos de `evaluar()` tienen un solo cambio de signo:
capital negativo, ATCF constante, venta final positiva), pero se vuelve real si el
modelo agrega capex a mitad de horizonte o refinanciamiento.

## Decisión

1. `tir()` cuenta los cambios de signo **antes** de bisectar y lanza `TirNoDefinida`
   (subclase de `ValueError`) cuando no hay exactamente uno — y también cuando, con uno,
   la raíz cae fuera de `[-0,9999; 10]`. Regla: **toda TIR que la bisección no puede
   certificar es ND, nunca un número.**
2. `evaluar()` propaga el ND: la clave del horizonte queda **ausente** de `tir_real`
   (el indexado directo del score sigue reventando fuerte, F3), el motivo queda en
   `tir_nd_motivo`, y la evaluación se **excluye del ranking** con el motivo a la vista
   — el mismo patrón post-cálculo del filtro de liquidez D-012.

## MIRR: considerada y rechazada

La TIR modificada resolvería la multiplicidad, pero (a) exige una **tasa de reinversión**
— un parámetro `E` nuevo en `params.yml` para un caso que hoy no ocurre —, (b) cambia el
significado de la métrica que el §12 pondera (dejaría de ser comparable entre unidades
según el camino de flujos), y (c) contradice la preferencia del §3.2: ante un valor no
determinable, ND explícito antes que un sustituto modelado. Si el capex/refinanciamiento
entra al modelo y los ND se vuelven frecuentes, se reabre esta ADR con la MIRR y su
tasa de reinversión declarada — decisión §8.4, con el humano.

## Consecuencias

- Ningún consumidor ve un −1: o hay TIR certificada, o la fila está excluida con motivo.
- El golden 5b conserva el fallo ruidoso (`ValueError` sigue atrapando a la subclase).

## Precisiones del verificador §7.6 (06-sep, misma fecha)

El verificador confirmó los números (20.000 vectores diferenciales: cero casos en que
se rechace una TIR única certificable; barrido de 4.000 unidades: el ND es inalcanzable
desde `evaluar()` hoy) y corrigió tres bordes de comportamiento, ya aplicados:

1. **Solo excluye el horizonte que el score consume (10 años).** Un ND en el 20 o el 30
   queda registrado en `tir_nd_motivo` pero no bota del ranking una TIR a 10 certificada.
   Los motivos de varios horizontes se acumulan, no se pisan.
2. **El motivo de D-012 no se borra**: el déficit en pesos es el hecho accionable; si
   coinciden, se muestran los dos motivos juntos.
3. **`saltar_exclusiones=True` se respeta** también en este bloque, y los mensajes van
   sin `:` interno para no partir el bucket de `excluidas_por_regla` del dashboard.
