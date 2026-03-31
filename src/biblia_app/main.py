import asyncio
from pathlib import Path
import sys
import traceback

if __package__ in (None, ""):
    ROOT = Path(__file__).resolve().parents[1]
    VENDOR_DIR = ROOT.parent / "vendor_py"
    if str(VENDOR_DIR) not in sys.path:
        sys.path.append(str(VENDOR_DIR))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

import flet as ft

from biblia_app.bienvenida import pantalla_carga_saludo, pantalla_saludos, pantalla_selector_idioma, pantalla_selector_modo
from biblia_app.contenido import pantalla_principal, precalentar_contenido
from biblia_app.idiomas import get_language_theme


def mostrar_error(page: ft.Page, titulo: str, detalle: str):
    theme = get_language_theme("es")
    page.clean()
    page.add(
        ft.SafeArea(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.ERROR_OUTLINE, color=theme["primary"], size=48),
                        ft.Text(titulo, size=22, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            detalle,
                            selectable=True,
                            color=theme["text"],
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                ),
                padding=24,
                expand=True,
                alignment=ft.Alignment(0, 0),
            )
        )
    )
    page.update()


def main(page: ft.Page):
    def titulo_error(clave: str) -> str:
        titulos = {
            "welcome": {"es": "Error en bienvenida", "ca": "Error a la benvinguda", "fr": "Erreur dans l'accueil", "en": "Welcome error"},
            "greetings": {"es": "Error en saludos", "ca": "Error als missatges de salutacio", "fr": "Erreur dans les salutations", "en": "Greetings error"},
            "loading": {"es": "Error en carga", "ca": "Error en la carrega", "fr": "Erreur de chargement", "en": "Loading error"},
            "entry": {"es": "Error en seleccion de entrada", "ca": "Error en la seleccio d'entrada", "fr": "Erreur dans la selection d'entree", "en": "Entry selection error"},
            "content": {"es": "Error en contenido", "ca": "Error en el contingut", "fr": "Erreur dans le contenu", "en": "Content error"},
            "startup": {"es": "Error al iniciar", "ca": "Error en iniciar", "fr": "Erreur au demarrage", "en": "Startup error"},
        }
        return titulos.get(clave, titulos["startup"]).get(idioma_actual["code"], titulos["startup"]["es"])

    def detectar_idioma_dispositivo() -> str:
        try:
            locale_cfg = getattr(page, "locale_configuration", None)
            current_locale = getattr(locale_cfg, "current_locale", None)
            if current_locale is None:
                return "es"
            locale_text = (
                getattr(current_locale, "language_code", None)
                or getattr(current_locale, "value", None)
                or str(current_locale)
            )
            locale_text = (locale_text or "").lower()
            if locale_text.startswith("ca"):
                return "ca"
            if locale_text.startswith("fr"):
                return "fr"
            if locale_text.startswith("en"):
                return "en"
        except Exception:
            pass
        return "es"

    page.title = "Biblia IA"
    page.bgcolor = get_language_theme("es")["page_bg"]
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    idioma_detectado = detectar_idioma_dispositivo()
    idioma_actual = {"code": idioma_detectado}
    precarga_lanzada = {"ok": False}

    async def precalentar_idioma_detectado_async(idioma: str):
        await asyncio.sleep(0.01)
        precalentar_contenido(idioma)

    def mostrar_selector_idioma():
        try:
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_selector_idioma(page, mostrar_saludos),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
            if not precarga_lanzada["ok"]:
                precarga_lanzada["ok"] = True
                page.run_task(precalentar_idioma_detectado_async, idioma_detectado)
        except Exception as exc:
            mostrar_error(page, titulo_error("welcome"), f"{exc}\n\n{traceback.format_exc()}")

    def mostrar_saludos(idioma: str):
        try:
            idioma_actual["code"] = idioma
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_saludos(
                        page,
                        idioma,
                        lambda: mostrar_carga_saludo(idioma),
                        mostrar_selector_idioma,
                    ),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
        except Exception as exc:
            mostrar_error(page, titulo_error("greetings"), f"{exc}\n\n{traceback.format_exc()}")

    def mostrar_carga_saludo(idioma: str):
        try:
            idioma_actual["code"] = idioma
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_carga_saludo(page, idioma),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
            page.run_task(cargar_contenido_async, idioma)
        except Exception as exc:
            mostrar_error(page, titulo_error("loading"), f"{exc}\n\n{traceback.format_exc()}")

    async def cargar_contenido_async(idioma: str):
        await asyncio.sleep(10)
        mostrar_selector_modo_entrada(idioma)

    def mostrar_selector_modo_entrada(idioma: str):
        try:
            idioma_actual["code"] = idioma
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.CENTER
            page.add(
                ft.Container(
                    content=pantalla_selector_modo(
                        page,
                        idioma,
                        lambda modo: mostrar_contenido(idioma, inicio=modo),
                        lambda: mostrar_saludos(idioma),
                    ),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                )
            )
            page.update()
        except Exception as exc:
            mostrar_error(page, "Error en seleccion de entrada", f"{exc}\n\n{traceback.format_exc()}")

    def mostrar_contenido(idioma: str | None = None, inicio: str = "biblia"):
        try:
            page.clean()
            page.vertical_alignment = ft.MainAxisAlignment.START
            pantalla_principal(
                page,
                idioma=idioma or idioma_actual["code"],
                on_volver=lambda: mostrar_saludos(idioma or idioma_actual["code"]),
                inicio=inicio,
                on_volver_inicio=lambda: mostrar_selector_modo_entrada(idioma or idioma_actual["code"]),
            )
            page.update()
        except Exception as exc:
            mostrar_error(page, titulo_error("content"), f"{exc}\n\n{traceback.format_exc()}")

    try:
        mostrar_selector_idioma()
    except Exception as exc:
        mostrar_error(page, titulo_error("startup"), f"{exc}\n\n{traceback.format_exc()}")


if __name__ == "__main__":
    ft.app(target=main)


