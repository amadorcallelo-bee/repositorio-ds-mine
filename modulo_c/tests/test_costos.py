"""Fija las cifras que `decisiones_arquitectura.md` publica.

Estas pruebas no verifican que Python sepa multiplicar. Verifican que los numeros impresos
en el documento son los que produce el modelo: si alguien actualiza una tarifa en
`costos.py` y no toca el documento, o al reves, la prueba falla y el desfase se ve antes de
llegar a una defensa tecnica. Es el mecanismo que sustituye a la promesa de mantener el
documento al dia.

Cada aserto lleva en su nombre la seccion del documento que respalda.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from costos import (
    ASISTENTE_UMLC,
    BYTES_POR_LECTURA_ALTO,
    BYTES_POR_LECTURA_BAJO,
    DBU_JOBS,
    ESCENARIO_ALTO,
    ESCENARIO_BAJO,
    LLM_FRONTERA_ENTRADA,
    LLM_FRONTERA_SALIDA,
    VM_SPOT,
    VOLUMETRIA_UMLC,
    Almacenamiento,
    CapacidadFabric,
    ClusterDatabricks,
    Escenario,
    EstimacionAnual,
    FuenteDeSenales,
    IngestaEventHubs,
    Reporte,
    Volumetria,
    main,
)


def redondeado(valor: Decimal, decimales: str = "1") -> Decimal:
    return valor.quantize(Decimal(decimales))


# --- Seccion 1 del documento: dimensionamiento ---


def test_volumetria_publica_760_senales() -> None:
    assert VOLUMETRIA_UMLC.senales_totales == 760


def test_volumetria_publica_798_millones_de_lecturas() -> None:
    assert redondeado(VOLUMETRIA_UMLC.lecturas_por_anio) == Decimal("798912000.0")


def test_telemetria_pesa_entre_30_y_89_gigabytes_por_anio() -> None:
    bajo = VOLUMETRIA_UMLC.gigabytes_por_anio(BYTES_POR_LECTURA_BAJO)
    alto = VOLUMETRIA_UMLC.gigabytes_por_anio(BYTES_POR_LECTURA_ALTO)
    assert redondeado(bajo, "0.1") == Decimal("29.8")
    assert redondeado(alto, "0.1") == Decimal("89.3")


def test_una_fuente_sin_activos_no_aporta_senales() -> None:
    vacia = Volumetria((FuenteDeSenales("planta detenida", activos=0, senales_por_activo=250),))
    assert vacia.senales_totales == 0
    assert vacia.lecturas_por_anio == Decimal("0")


def test_el_periodo_de_muestreo_escala_las_lecturas_de_forma_inversa() -> None:
    cada_minuto = Volumetria(VOLUMETRIA_UMLC.fuentes, periodo_muestreo_seg=60)
    assert cada_minuto.lecturas_por_anio * 2 == VOLUMETRIA_UMLC.lecturas_por_anio


# --- Seccion 7 del documento: capacidad Fabric y punto de indiferencia ---


@pytest.mark.parametrize(
    ("unidades", "pago_por_uso", "reservado"),
    [(2, "263", "156"), (8, "1051", "625"), (16, "2102", "1251"), (64, "8410", "5003")],
)
def test_tabla_de_capacidad_fabric(unidades: int, pago_por_uso: str, reservado: str) -> None:
    capacidad = CapacidadFabric(unidades)
    assert redondeado(capacidad.mensual_pago_por_uso, "1") == Decimal(pago_por_uso)
    assert redondeado(capacidad.mensual_reservado, "1") == Decimal(reservado)


def test_la_reserva_a_un_anio_descuenta_40_5_por_ciento() -> None:
    descuento = CapacidadFabric(8).descuento_reserva * 100
    assert redondeado(descuento, "0.1") == Decimal("40.5")


def test_el_descuento_de_la_reserva_no_depende_del_tamano_de_la_capacidad() -> None:
    pequena = redondeado(CapacidadFabric(2).descuento_reserva, "0.00001")
    grande = redondeado(CapacidadFabric(64).descuento_reserva, "0.00001")
    assert pequena == grande


def test_la_indiferencia_entre_f8_mas_pro_y_f64_esta_en_313_visores() -> None:
    indiferencia = CapacidadFabric(8).visores_de_indiferencia(CapacidadFabric(64))
    assert redondeado(indiferencia, "1") == Decimal("313")


def test_una_capacidad_es_indiferente_consigo_misma_en_cero_visores() -> None:
    assert CapacidadFabric(8).visores_de_indiferencia(CapacidadFabric(8)) == Decimal("0")


# --- Seccion 7 del documento: peso de la maquina sobre el DBU ---


def test_el_nodo_de_jobs_cuesta_0_526_por_hora() -> None:
    assert ClusterDatabricks(nodos=1).costo_por_nodo_hora == Decimal("0.526")


def test_la_maquina_agrega_75_por_ciento_sobre_el_dbu() -> None:
    sobrecosto = ClusterDatabricks(nodos=1).sobrecosto_de_la_maquina * 100
    assert redondeado(sobrecosto, "1") == Decimal("75")


def test_spot_en_los_workers_baja_el_nodo_hora_34_por_ciento() -> None:
    completo = ClusterDatabricks(nodos=1)
    con_spot = ClusterDatabricks(nodos=1, tarifa_vm=VM_SPOT)
    ahorro = (Decimal("1") - con_spot.costo_por_nodo_hora / completo.costo_por_nodo_hora) * 100
    assert redondeado(ahorro, "1") == Decimal("34")


def test_un_cluster_apagado_no_cuesta() -> None:
    assert ClusterDatabricks(nodos=3).costo_anual(Decimal("0")) == Decimal("0")


def test_el_costo_anual_escala_lineal_con_las_horas_diarias() -> None:
    cluster = ClusterDatabricks(nodos=3)
    assert cluster.costo_anual(Decimal("6")) == cluster.costo_anual(Decimal("3")) * 2


# --- Seccion 7 del documento: almacenamiento e ingesta ---


def test_almacenamiento_publica_396_y_1546_por_anio() -> None:
    bajo = Almacenamiento(
        telemetria_gb_anio=ESCENARIO_BAJO.telemetria_gb_anio,
        anios_retenidos=Decimal("5"),
        dron_gb_anio=ESCENARIO_BAJO.dron_gb_anio,
    )
    alto = Almacenamiento(
        telemetria_gb_anio=ESCENARIO_ALTO.telemetria_gb_anio,
        anios_retenidos=Decimal("5"),
        dron_gb_anio=ESCENARIO_ALTO.dron_gb_anio,
    )
    assert redondeado(bajo.costo_anual, "1") == Decimal("396")
    assert redondeado(alto.costo_anual, "1") == Decimal("1546")


def test_un_lago_vacio_no_cuesta_almacenamiento() -> None:
    vacio = Almacenamiento(
        telemetria_gb_anio=Decimal("0"),
        anios_retenidos=Decimal("5"),
        dron_gb_anio=Decimal("0"),
    )
    assert vacio.costo_anual == Decimal("0")


def test_la_ingesta_publica_1161_por_anio() -> None:
    ingesta = IngestaEventHubs(VOLUMETRIA_UMLC.lecturas_por_anio)
    assert redondeado(ingesta.costo_anual, "1") == Decimal("1161")


def test_la_ingesta_esta_dominada_por_la_unidad_y_la_captura_y_no_por_los_eventos() -> None:
    con_trafico = IngestaEventHubs(VOLUMETRIA_UMLC.lecturas_por_anio).costo_anual
    sin_trafico = IngestaEventHubs(Decimal("0")).costo_anual
    assert redondeado(con_trafico - sin_trafico, "1") == Decimal("22")


# --- Seccion 7 del documento: totales y sensibilidad ---


def test_el_total_anual_esta_entre_17962_y_42719() -> None:
    bajo = EstimacionAnual(ESCENARIO_BAJO, VOLUMETRIA_UMLC)
    alto = EstimacionAnual(ESCENARIO_ALTO, VOLUMETRIA_UMLC)
    assert redondeado(bajo.total, "1") == Decimal("17962")
    assert redondeado(alto.total, "1") == Decimal("42719")


def test_fabric_y_licencias_son_la_linea_mas_pesada_en_los_dos_escenarios() -> None:
    for escenario in (ESCENARIO_BAJO, ESCENARIO_ALTO):
        estimacion = EstimacionAnual(escenario, VOLUMETRIA_UMLC)
        rubro_mayor = max(estimacion.rubros, key=lambda nombre: estimacion.rubros[nombre])
        assert rubro_mayor == "Fabric y licencias Power BI"


def test_fabric_pesa_65_2_y_50_9_por_ciento_del_total() -> None:
    bajo = EstimacionAnual(ESCENARIO_BAJO, VOLUMETRIA_UMLC)
    alto = EstimacionAnual(ESCENARIO_ALTO, VOLUMETRIA_UMLC)
    assert redondeado(bajo.participacion("Fabric y licencias Power BI") * 100, "0.1") == Decimal(
        "65.2"
    )
    assert redondeado(alto.participacion("Fabric y licencias Power BI") * 100, "0.1") == Decimal(
        "50.9"
    )


def test_el_almacenamiento_no_llega_al_4_por_ciento_del_total() -> None:
    for escenario in (ESCENARIO_BAJO, ESCENARIO_ALTO):
        estimacion = EstimacionAnual(escenario, VOLUMETRIA_UMLC)
        assert estimacion.participacion("Almacenamiento") < Decimal("0.04")


def test_el_dron_tendria_que_errar_por_diez_para_llegar_al_26_por_ciento() -> None:
    escenario = replace(
        ESCENARIO_ALTO, dron_gb_anio=ESCENARIO_ALTO.dron_gb_anio * Decimal("10")
    )
    estimacion = EstimacionAnual(escenario, VOLUMETRIA_UMLC)
    assert redondeado(estimacion.participacion("Almacenamiento") * 100, "0.1") == Decimal("26.0")


def test_pedir_la_participacion_de_un_rubro_inexistente_falla_donde_se_comete() -> None:
    estimacion = EstimacionAnual(ESCENARIO_BAJO, VOLUMETRIA_UMLC)
    with pytest.raises(KeyError):
        estimacion.participacion("Snowflake")


def test_un_escenario_sin_gasto_da_total_cero() -> None:
    nulo = Escenario(
        nombre="nulo",
        unidades_capacidad=0,
        visores_power_bi=0,
        horas_diarias_de_jobs=Decimal("0"),
        horas_mensuales_interactivas=Decimal("0"),
        telemetria_gb_anio=Decimal("0"),
        dron_gb_anio=Decimal("0"),
        servicios_y_red=Decimal("0"),
        usa_spot_en_jobs=False,
    )
    estimacion = EstimacionAnual(nulo, Volumetria(()))
    assert estimacion.rubros["Fabric y licencias Power BI"] == Decimal("0")
    assert estimacion.rubros["Databricks jobs"] == Decimal("0")


# --- Seccion 7 del documento: costo del asistente RAG ---


def test_indexar_los_800_documentos_cuesta_un_dolar() -> None:
    assert redondeado(ASISTENTE_UMLC.costo_indexacion, "0.01") == Decimal("1.04")


def test_las_consultas_anuales_cuestan_12_48_con_el_modelo_economico() -> None:
    assert redondeado(ASISTENTE_UMLC.costo_anual_consultas(), "0.01") == Decimal("12.48")


def test_un_modelo_de_frontera_multiplica_por_21_y_sigue_siendo_ruido() -> None:
    economico = ASISTENTE_UMLC.costo_anual_consultas()
    frontera = ASISTENTE_UMLC.costo_anual_consultas(LLM_FRONTERA_ENTRADA, LLM_FRONTERA_SALIDA)
    assert redondeado(frontera, "0.01") == Decimal("262.80")
    assert redondeado(frontera / economico, "1") == Decimal("21")
    assert frontera < EstimacionAnual(ESCENARIO_BAJO, VOLUMETRIA_UMLC).total / 50


def test_un_asistente_sin_consultas_solo_paga_la_indexacion() -> None:
    dormido = replace(ASISTENTE_UMLC, consultas_por_dia=0)
    assert dormido.costo_anual_consultas() == Decimal("0")
    assert dormido.costo_indexacion == ASISTENTE_UMLC.costo_indexacion


# --- Toda tarifa declara su procedencia ---


def test_ninguna_tarifa_se_publica_sin_fuente() -> None:
    for tarifa in (DBU_JOBS, VM_SPOT, LLM_FRONTERA_ENTRADA):
        assert tarifa.fuente
        assert tarifa.unidad


# --- El reporte que alimenta al documento corre entero ---


def test_el_reporte_imprime_las_cifras_del_documento(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    salida = capsys.readouterr().out
    assert "760 senales" in salida
    assert "313 visores" in salida
    assert "17,962" in salida
    assert "42,719" in salida


def test_el_reporte_acepta_escenarios_distintos_a_los_del_documento() -> None:
    austero = replace(ESCENARIO_BAJO, unidades_capacidad=4, visores_power_bi=15)
    Reporte(escenarios=(austero, ESCENARIO_ALTO)).imprimir()


# --- Seccion 1 y 4 del documento: cifras que antes se calculaban fuera del modelo ---


def test_las_lecturas_diarias_son_2_188_800() -> None:
    assert redondeado(VOLUMETRIA_UMLC.lecturas_por_dia, "1") == Decimal("2188800")


def test_tres_minas_muestreando_cada_4_horas_dan_6570_analisis() -> None:
    analisis = VOLUMETRIA_UMLC.analisis_de_laboratorio_por_anio(minas=3, cada_horas=4)
    assert analisis == Decimal("6570")


def test_el_mismo_trafico_exige_6_unidades_s1_de_iot_hub() -> None:
    ingesta = IngestaEventHubs(VOLUMETRIA_UMLC.lecturas_por_anio)
    assert ingesta.unidades_s1_de_iot_hub == Decimal("6")
    assert ingesta.costo_anual_iot_hub_s1 == Decimal("1800")
    assert ingesta.costo_anual_iot_hub_s2 == Decimal("3000")


def test_iot_hub_cuesta_entre_639_y_1839_mas_que_event_hubs() -> None:
    ingesta = IngestaEventHubs(VOLUMETRIA_UMLC.lecturas_por_anio)
    assert redondeado(ingesta.costo_anual_iot_hub_s1 - ingesta.costo_anual, "1") == Decimal("639")
    assert redondeado(ingesta.costo_anual_iot_hub_s2 - ingesta.costo_anual, "1") == Decimal("1839")


def test_un_trafico_minimo_exige_al_menos_una_unidad_s1() -> None:
    assert IngestaEventHubs(Decimal("1")).unidades_s1_de_iot_hub == Decimal("1")


def test_f8_mas_40_licencias_ahorra_45808_frente_a_f64() -> None:
    ahorro = CapacidadFabric(8).ahorro_anual_frente_a(CapacidadFabric(64), visores=40)
    assert redondeado(ahorro, "1") == Decimal("45808")


def test_el_ahorro_cambia_de_signo_en_el_punto_de_indiferencia() -> None:
    f8, f64 = CapacidadFabric(8), CapacidadFabric(64)
    assert f8.ahorro_anual_frente_a(f64, visores=312) > Decimal("0")
    assert f8.ahorro_anual_frente_a(f64, visores=313) < Decimal("0")
