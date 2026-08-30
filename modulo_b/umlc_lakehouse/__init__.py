"""Lakehouse medallion de la UMLC sobre Delta Lake (Ejercicio B-1).

El paquete contiene la logica de las tres capas y del control de calidad; los notebooks
`01_bronze.py`, `02_silver.py` y `03_gold.py` solo orquestan. La separacion existe por una
razon de pruebas: Auto Loader, los volumenes de Unity Catalog y `dbutils` solo existen en
Databricks, pero la limpieza, las reglas de calidad, la agregacion y el `MERGE` son codigo
Spark corriente que se puede ejecutar y probar en local con `pyspark` y `delta-spark`.
"""
