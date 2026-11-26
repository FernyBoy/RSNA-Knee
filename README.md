Integrantes:
Angel Fernando Bórquez Guerrero: a219108106
Angel Alberto Amaya Soria: albertoamaya
Javier Leonardo Miranda Sánchez: javiermirandasanchez

Secciones:
1. El problema. 
Qué se predice, con qué datos, con qué métrica y por qué esa métrica tiene sentido para ese problema.

2. Los datos. 
Qué encontraron en la exploración que cambió lo que hicieron: distribuciones, faltantes, desbalance, estructura temporal o por grupos, diferencias entre entrenamiento y prueba.

3. La validación. 
Cómo separaron los datos para validar, por qué esa partición imita a la de la competencia, y una tabla que compare la puntuación en validación con la del leaderboard público en varios envíos. Si no se parecen, qué creen que pasa.

4. La línea base y la ruta de mejora. 
El modelo más simple razonable y cada mejora importante después, con su puntuación en validación. Incluye lo que no funcionó.

5. El modelo final. 
Qué es, sus hiperparámetros y cómo se eligieron, y cuánto tarda en entrenar.

6. El resultado. 
Puntuación del envío final (pública y privada, si la hay), lugar en la tabla o lugar equivalente, número de equipos y las capturas correspondientes.

7. Qué harían con más tiempo.

8. Equipo y uso de IA. 
Qué hizo cada integrante y para qué usaron asistentes de IA.

Uso de IA:
- `datos/descargar.py`: Angel Fernando Bórquez Guerrero usó Claude Code (Claude Opus 5.5), que creó el archivo a partir del fragmento de `kagglehub` que proporciona Kaggle; agregó la función `main()` y el docstring con los requisitos de uso.
- Archivos DICOM: Angel Alberto Amaya Soria usó Claude Code (Claude Opus 5.5) para obtener una explicación de qué son los archivos DICOM (imagen y metadatos), cómo se organizan en estudios, series e instancias en los datos de la competencia y qué implica eso para el proyecto.
- Estructura de los datos: Angel Fernando Bórquez Guerrero usó Claude Code (Claude Opus 5.5) para entender mejor cómo se distribuyen los estudios, las series y los archivos DICOM (qué es una rebanada o *slice*, qué identifica cada UID y la relación entre visita, secuencias y cortes).
- Declaración de uso de IA: Angel Fernando Bórquez Guerrero usó Claude Code (Claude Opus 5.5) para redactar y agregar las entradas de esta lista.

9. Cómo reproducirlo. Los comandos, en orden, para pasar de un repositorio recién clonado al archivo submission.csv.
