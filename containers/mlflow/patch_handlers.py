"""Parche de robustez para MLflow 2.19.0.

La UI de MLflow puede enviar un experiment_id de relleno ("...") mientras
termina de cargar una página. En Postgres eso termina en un error 500
(`invalid input syntax for type integer: "..."`) al consultar datasets.
Este parche filtra IDs no numéricos y devuelve una lista vacía en lugar de
romper la pestaña Models/Datasets.
"""

from pathlib import Path

HANDLERS = Path("/usr/local/lib/python3.12/site-packages/mlflow/server/handlers.py")

OLD = """    experiment_ids = request_message.experiment_ids or []
    if not experiment_ids:
        raise MlflowException(
            message="SearchDatasets request must specify at least one experiment_id.",
            error_code=INVALID_PARAMETER_VALUE,
        )
"""

NEW = """    experiment_ids = request_message.experiment_ids or []
    if not experiment_ids:
        raise MlflowException(
            message="SearchDatasets request must specify at least one experiment_id.",
            error_code=INVALID_PARAMETER_VALUE,
        )
    # GEMACONT: la UI puede enviar un placeholder ("...") antes de cargar el
    # experimento. Postgres lo rechaza como entero; devolvemos vacío.
    experiment_ids = [eid for eid in experiment_ids if str(eid).isdigit()]
    if not experiment_ids:
        return SearchDatasets.Response()
"""

source = HANDLERS.read_text(encoding="utf-8")
if NEW in source:
    print("MLflow handlers already patched")
elif OLD not in source:
    raise SystemExit("No se encontró el bloque esperado en handlers.py")
else:
    HANDLERS.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")
    print("MLflow handlers patched")
