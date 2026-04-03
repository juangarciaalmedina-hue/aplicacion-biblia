import os
import random
import webbrowser

import flet as ft

from biblia_app.idiomas import LANGUAGES, construir_saludo_bienvenida, get_language_config, get_language_theme


TIKTOK_URL = "https://www.tiktok.com/@jmgalmedina"
_RANDOM = random.SystemRandom()
_SALUDOS_PENDIENTES_POR_IDIOMA: dict[str, list[str]] = {}
_ULTIMO_SALUDO_POR_IDIOMA: dict[str, str] = {}


def _obtener_siguiente_saludo(language_code: str) -> str:
    saludos = list(get_language_config(language_code).get("welcome", {}).get("greetings", []))
    if not saludos:
        return construir_saludo_bienvenida(language_code, _RANDOM.randrange(105))

    pendientes = _SALUDOS_PENDIENTES_POR_IDIOMA.get(language_code)
    if not pendientes:
        pendientes = saludos.copy()
        _RANDOM.shuffle(pendientes)
        ultimo_saludo = _ULTIMO_SALUDO_POR_IDIOMA.get(language_code)
        if ultimo_saludo and len(pendientes) > 1 and pendientes[0] == ultimo_saludo:
            pendientes.append(pendientes.pop(0))
        _SALUDOS_PENDIENTES_POR_IDIOMA[language_code] = pendientes

    saludo = pendientes.pop(0)
    _ULTIMO_SALUDO_POR_IDIOMA[language_code] = saludo
    return saludo


def _crear_bandera(tipo: str) -> ft.Control:
    if tipo == "spain":
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(height=10, bgcolor="#C60B1E", border_radius=ft.border_radius.only(top_left=6, top_right=6)),
                    ft.Container(height=14, bgcolor="#FFC400"),
                    ft.Container(height=10, bgcolor="#C60B1E", border_radius=ft.border_radius.only(bottom_left=6, bottom_right=6)),
                ],
                spacing=0,
                tight=True,
            ),
            width=34,
            border=ft.border.all(1, "black"),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
    if tipo == "catalonia":
        franjas = []
        colores = ["#F6D04D", "#C8102E"] * 4
        for color in colores:
            franjas.append(ft.Container(height=4, bgcolor=color))
        franjas[0].border_radius = ft.border_radius.only(top_left=6, top_right=6)
        franjas[-1].border_radius = ft.border_radius.only(bottom_left=6, bottom_right=6)
        return ft.Container(
            content=ft.Column(franjas, spacing=0, tight=True),
            width=34,
            border=ft.border.all(1, "black"),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
    if tipo == "france":
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=11, bgcolor="#EF4135"),
                    ft.Container(width=11, bgcolor="#FFFFFF"),
                    ft.Container(width=11, bgcolor="#0055A4"),
                ],
                spacing=0,
                tight=True,
            ),
            height=34,
            border=ft.border.all(1, "black"),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
    if tipo == "uk":
        return ft.Container(
            content=ft.Stack(
                [
                    ft.Container(bgcolor="#012169"),
                    ft.Container(bgcolor="#FFFFFF", rotate=ft.Rotate(angle=0.62), width=46, height=8, left=-6, top=13),
                    ft.Container(bgcolor="#FFFFFF", rotate=ft.Rotate(angle=-0.62), width=46, height=8, left=-6, top=13),
                    ft.Container(bgcolor="#C8102E", rotate=ft.Rotate(angle=0.62), width=46, height=4, left=-6, top=15),
                    ft.Container(bgcolor="#C8102E", rotate=ft.Rotate(angle=-0.62), width=46, height=4, left=-6, top=15),
                    ft.Container(height=10, bgcolor="#FFFFFF", top=12, left=0, right=0),
                    ft.Container(width=10, bgcolor="#FFFFFF", top=0, bottom=0, left=12),
                    ft.Container(height=6, bgcolor="#C8102E", top=14, left=0, right=0),
                    ft.Container(width=6, bgcolor="#C8102E", top=0, bottom=0, left=14),
                ]
            ),
            width=34,
            height=34,
            border=ft.border.all(1, "black"),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
    return ft.Container(
        content=ft.Stack(
            [
                ft.Container(bgcolor="white"),
                ft.Container(height=8, bgcolor="#CE1126", top=13, left=0, right=0),
                ft.Container(width=8, bgcolor="#CE1126", top=0, bottom=0, left=13),
            ]
        ),
        width=34,
        height=34,
        border=ft.border.all(1, "black"),
        border_radius=6,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


def _boton_idioma(language_code: str, on_select_language):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    texto_nombre = ft.Text(cfg["native_name"], weight="bold", size=16, color=theme["text"])
    boton = ft.ElevatedButton(
        content=ft.Row(
            [
                _crear_bandera(cfg["flag"]),
                texto_nombre,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=12,
        ),
        style=ft.ButtonStyle(
            bgcolor=theme["field_bg"],
            color=theme["text"],
            side=ft.BorderSide(4, theme["primary"]),
            shape=ft.RoundedRectangleBorder(radius=14),
            padding=20,
        ),
        width=320,
        height=88,
    )
    boton.data = {
        "language_code": language_code,
        "theme": theme,
        "label": texto_nombre,
    }
    return boton


def pantalla_selector_idioma(page: ft.Page, on_select_language):
    selector = get_language_config("es")["selector"]
    theme = get_language_theme("es")
    botones = [_boton_idioma(language_code, on_select_language) for language_code in LANGUAGES]
    seleccionando = {"code": None}

    def actualizar_estado_botones():
        for boton in botones:
            datos = boton.data
            tema_boton = datos["theme"]
            activo = seleccionando["code"] == datos["language_code"]
            bloqueado = seleccionando["code"] is not None and not activo
            datos["label"].color = "#FFFFFF" if activo else tema_boton["text"]
            boton.disabled = seleccionando["code"] is not None
            boton.style = ft.ButtonStyle(
                bgcolor=(tema_boton["primary"] if activo else ("#E0E0E0" if bloqueado else tema_boton["field_bg"])),
                color=("#FFFFFF" if activo else tema_boton["text"]),
                side=ft.BorderSide(5 if activo else 4, tema_boton["primary"] if not bloqueado else "#BDBDBD"),
                shape=ft.RoundedRectangleBorder(radius=14),
                padding=20,
            )

    def seleccionar_idioma(language_code: str):
        if seleccionando["code"] is not None:
            return
        seleccionando["code"] = language_code
        actualizar_estado_botones()
        page.update()
        on_select_language(language_code)

    for boton in botones:
        language_code = boton.data["language_code"]
        boton.on_click = lambda e, code=language_code: seleccionar_idioma(code)

    actualizar_estado_botones()
    textos_cabecera = [ft.Text("Biblia IA", size=30, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER)]
    if selector.get("title"):
        textos_cabecera.append(ft.Text(selector["title"], size=22, weight="bold", color=theme["text"], text_align=ft.TextAlign.CENTER))
    if selector.get("subtitle"):
        textos_cabecera.append(
            ft.Text(
                selector["subtitle"],
                size=17,
                italic=True,
                weight=ft.FontWeight.W_600,
                color=theme["text"],
                text_align=ft.TextAlign.CENTER,
            )
        )

    return ft.Column(
        controls=[
            ft.Icon(ft.Icons.LANGUAGE, color=theme["primary"], size=54),
            ft.Column(
                textos_cabecera,
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            ft.Divider(height=10, color="transparent"),
            *botones,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=18,
        tight=True,
    )


def pantalla_saludos(page: ft.Page, language_code: str, on_continuar, on_volver=None):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    welcome = cfg["welcome"]
    es_frances = language_code == "fr"
    es_ingles = language_code == "en"

    def mostrar_error(texto: str):
        page.snack_bar = ft.SnackBar(ft.Text(texto))
        page.snack_bar.open = True
        page.update()

    def abrir_tiktok(_):
        ultimo_error = None

        try:
            page.launch_url(TIKTOK_URL)
            return
        except Exception as exc:
            ultimo_error = exc

        try:
            os.startfile(TIKTOK_URL)
            return
        except Exception as exc:
            ultimo_error = exc

        try:
            if webbrowser.open(TIKTOK_URL, new=2):
                return
        except Exception as exc:
            ultimo_error = exc

        mostrar_error(welcome["snackbar_open_error"].format(error=ultimo_error))

    controles = [
        ft.Icon(ft.Icons.AUTO_STORIES, color=theme["primary"], size=54),
        ft.Text(welcome["title"], size=28, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
        ft.Row(
            [
                _crear_bandera(cfg["flag"]),
                ft.Text(cfg["native_name"], size=18, weight="bold", color=theme["text"]),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
        ),
        ft.Text(welcome["subtitle"], size=14, color=theme["muted"], text_align=ft.TextAlign.CENTER),
        ft.Divider(height=20, color="transparent"),
        ft.ElevatedButton(
            welcome["follow"],
            url=TIKTOK_URL,
            on_click=abrir_tiktok,
            style=ft.ButtonStyle(
                bgcolor=("#EF4135" if es_frances else "#012169") if (es_frances or es_ingles) else theme["secondary"],
                color="#FFFFFF" if (es_frances or es_ingles) else theme["secondary_text"],
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            width=300,
            height=60,
        ),
        ft.ElevatedButton(
            welcome["continue"],
            on_click=lambda e: on_continuar(),
            style=ft.ButtonStyle(
                bgcolor="#FFFFFF" if (es_frances or es_ingles) else theme["primary"],
                color="#10233C" if (es_frances or es_ingles) else theme["primary_text"],
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            width=300,
            height=60,
        ),
    ]

    if on_volver is not None:
        controles.append(
            ft.OutlinedButton(
                welcome["back"],
                on_click=lambda e: on_volver(),
                style=ft.ButtonStyle(
                    color="#FFFFFF" if (es_frances or es_ingles) else theme["text"],
                    side=ft.BorderSide(3, theme["primary"]),
                    shape=ft.RoundedRectangleBorder(radius=10),
                    bgcolor=("#0055A4" if es_frances else "#C8102E") if (es_frances or es_ingles) else theme["field_bg"],
                    padding=ft.padding.symmetric(horizontal=18, vertical=12),
                ),
                width=300,
                height=60,
            )
        )

    return ft.Column(
        controls=controles,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=20,
        tight=True,
    )


def pantalla_selector_modo(page: ft.Page, language_code: str, on_select_mode, on_volver=None):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    ui = cfg["ui"]
    titulo_seleccion = {
        "es": "SELECCIÓN",
        "ca": "SELECCIO",
        "fr": "SELECTION",
        "en": "SELECTION",
    }.get(language_code, "SELECCIÓN")
    texto_biblia = {
        "es": ("BIBLIA", "COMENTARIO BÍBLICO"),
        "ca": ("BIBLIA", "COMENTARI BIBLIC"),
        "fr": ("BIBLE", "COMMENTAIRE BIBLIQUE"),
        "en": ("BIBLE", "BIBLICAL COMMENTARY"),
    }.get(language_code, ("BIBLIA", "COMENTARIO BÍBLICO"))
    texto_estudio = {
        "es": ("ESTUDIO BÍBLICO", "TEMAS, PERSONAJES, PUEBLOS, ETC"),
        "ca": ("ESTUDI BIBLIC", "TEMES, PERSONATGES, POBLES, ETC"),
        "fr": ("ETUDE BIBLIQUE", "THEMES, PERSONNAGES, PEUPLES, ETC"),
        "en": ("BIBLICAL STUDY", "TOPICS, CHARACTERS, PEOPLES, ETC"),
    }.get(language_code, ("ESTUDIO BÍBLICO", "TEMAS, PERSONAJES, PUEBLOS, ETC"))
    texto_comportamiento = {
        "es": ("CÓMO COMPORTARME SI...", "CRÍTICAS, ENFADOS, CONFLICTOS, ETC"),
        "ca": ("COM COMPORTAR-ME SI...", "CRITIQUES, ENFADAMENTS, CONFLICTES, ETC"),
        "fr": ("COMMENT ME COMPORTER SI...", "CRITIQUES, COLERES, CONFLITS, ETC"),
        "en": ("HOW SHOULD I RESPOND IF...", "CRITICISM, ANGER, CONFLICTS, ETC"),
    }.get(language_code, ("CÓMO COMPORTARME SI...", "CRÍTICAS, ENFADOS, CONFLICTOS, ETC"))
    texto_incredulo = {
        "es": ("QUÉ RESPONDER A UN INCRÉDULO SI...", "PREGUNTAS DIFÍCILES, FE, BIBLIA, DIOS, ETC"),
        "ca": ("QUE RESPONDRE A UN INCREDUL SI...", "PREGUNTES DIFICILS, FE, BIBLIA, DEU, ETC"),
        "fr": ("QUE REPONDRE A UN INCREDULE SI...", "QUESTIONS DIFFICILES, FOI, BIBLE, DIEU, ETC"),
        "en": ("WHAT TO ANSWER AN UNBELIEVER IF...", "HARD QUESTIONS, FAITH, BIBLE, GOD, ETC"),
    }.get(language_code, ("QUÉ RESPONDER A UN INCRÉDULO SI...", "PREGUNTAS DIFÍCILES, FE, BIBLIA, DIOS, ETC"))
    texto_cristianos = {
        "es": ("PREGUNTAS QUE LOS CRISTIANOS NOS HACEMOS", "DUDAS DE FE, ORACION, PRUEBAS, GUIA DE DIOS, ETC"),
        "ca": ("PREGUNTES QUE ELS CRISTIANS ENS FEM", "DUBTES DE FE, ORACIO, PROVES, GUIA DE DEU, ETC"),
        "fr": ("QUESTIONS QUE LES CHRETIENS SE POSENT", "DOUTES, PRIERE, EPREUVES, DIRECTION DE DIEU, ETC"),
        "en": ("QUESTIONS CHRISTIANS ASK", "FAITH DOUBTS, PRAYER, TRIALS, GOD'S GUIDANCE, ETC"),
    }.get(language_code, ("PREGUNTAS QUE LOS CRISTIANOS NOS HACEMOS", "DUDAS DE FE, ORACION, PRUEBAS, GUIA DE DIOS, ETC"))
    textos = {
        "es": {
            "title": "¿Cómo quieres empezar?",
            "subtitle": "Elige si quieres buscar un pasaje bíblico o hacer un estudio por tema, personaje, lugar y otros filtros.",
            "bible": "BIBLIA",
            "bible_help": "Ir al recuadro de pasaje bíblico",
            "study": "ESTUDIO",
            "study_help": "Ir al recuadro de tema, personaje, lugar y filtros",
            "back": "VOLVER",
        },
        "ca": {
            "title": "Com vols començar?",
            "subtitle": "Tria si vols cercar un passatge bíblic o fer un estudi per tema, personatge, lloc i altres filtres.",
            "bible": "BÍBLIA",
            "bible_help": "Anar al requadre de passatge bíblic",
            "study": "ESTUDI",
            "study_help": "Anar al requadre de tema, personatge, lloc i filtres",
            "back": "TORNAR",
        },
        "fr": {
            "title": "Comment veux-tu commencer ?",
            "subtitle": "Choisis si tu veux chercher un passage biblique ou faire une étude par thème, personnage, lieu et autres filtres.",
            "bible": "BIBLE",
            "bible_help": "Aller au cadre du passage biblique",
            "study": "ETUDE",
            "study_help": "Aller au cadre du thème, personnage, lieu et filtres",
            "back": "RETOUR",
        },
        "en": {
            "title": "How do you want to start?",
            "subtitle": "Choose whether you want to search a Bible passage or start a study by topic, character, place, and other filters.",
            "bible": "BIBLE",
            "bible_help": "Go to the Bible passage panel",
            "study": "STUDY",
            "study_help": "Go to the topic, character, place, and filters panel",
            "back": "BACK",
        },
    }.get(language_code, {
        "title": "¿Cómo quieres empezar?",
        "subtitle": "Elige si quieres buscar un pasaje bíblico o hacer un estudio por tema, personaje, lugar y otros filtros.",
        "bible": "BIBLIA",
        "bible_help": "Ir al recuadro de pasaje bíblico",
        "study": "ESTUDIO",
        "study_help": "Ir al recuadro de tema, personaje, lugar y filtros",
        "back": "VOLVER",
    })

    colores_botones = {
        "es": [
            ("#C60B1E", "#FFFFFF"),
            ("#FFC400", "#2F1B00"),
            ("#C60B1E", "#FFFFFF"),
            ("#FFC400", "#2F1B00"),
            ("#C60B1E", "#FFFFFF"),
        ],
        "ca": [
            ("#C8102E", "#FFFFFF"),
            ("#F6D04D", "#351600"),
            ("#C8102E", "#FFFFFF"),
            ("#F6D04D", "#351600"),
            ("#C8102E", "#FFFFFF"),
        ],
        "fr": [
            ("#0055A4", "#FFFFFF"),
            ("#FFFFFF", "#1A2A44"),
            ("#EF4135", "#FFFFFF"),
            ("#0055A4", "#FFFFFF"),
            ("#0055A4", "#FFFFFF"),
        ],
        "en": [
            ("#012169", "#FFFFFF"),
            ("#FFFFFF", "#12264A"),
            ("#C8102E", "#FFFFFF"),
            ("#012169", "#FFFFFF"),
            ("#012169", "#FFFFFF"),
        ],
    }.get(language_code, [
        (theme["primary"], theme["primary_text"]),
        (theme["secondary"], theme["secondary_text"]),
        (theme["primary"], theme["primary_text"]),
        (theme["secondary"], theme["secondary_text"]),
        (theme["primary"], theme["primary_text"]),
    ])

    def boton_modo(texto, ayuda, icono, color_fondo, color_texto, accion):
        contenido = [
            ft.Icon(icono, size=28, color=color_texto),
            ft.Text(texto, size=16, weight="bold", color=color_texto, text_align=ft.TextAlign.CENTER),
        ]
        if ayuda:
            contenido.append(ft.Text(ayuda, size=11, color=color_texto, text_align=ft.TextAlign.CENTER))
        return ft.ElevatedButton(
            content=ft.Column(
                contenido,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5,
                tight=True,
            ),
            on_click=lambda e: accion(),
            style=ft.ButtonStyle(
                bgcolor=color_fondo,
                color=color_texto,
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=16),
                padding=10,
            ),
            width=286,
            height=92,
        )

    controles = [
        ft.Icon(ft.Icons.EXPLORE, color=theme["primary"], size=44),
        ft.Text(cfg["welcome"]["title"], size=24, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
        ft.Text(titulo_seleccion, size=20, weight="bold", color=theme["text"], text_align=ft.TextAlign.CENTER),
        ft.Divider(height=4, color="transparent"),
        boton_modo(texto_biblia[0], texto_biblia[1], ft.Icons.AUTO_STORIES, colores_botones[0][0], colores_botones[0][1], lambda: on_select_mode("biblia")),
        boton_modo(texto_estudio[0], texto_estudio[1], ft.Icons.FILTER_ALT, colores_botones[1][0], colores_botones[1][1], lambda: on_select_mode("filtros")),
        boton_modo(texto_comportamiento[0], None, ft.Icons.FORUM, colores_botones[2][0], colores_botones[2][1], lambda: on_select_mode("comportamiento")),
        boton_modo(texto_incredulo[0], None, ft.Icons.RECORD_VOICE_OVER, colores_botones[3][0], colores_botones[3][1], lambda: on_select_mode("incredulo")),
        boton_modo(texto_cristianos[0], None, ft.Icons.HELP_OUTLINE, colores_botones[4][0], colores_botones[4][1], lambda: on_select_mode("cristianos")),
    ]

    return ft.Column(
        controls=controles,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=12,
        tight=True,
    )


def pantalla_carga_saludo(page: ft.Page, language_code: str):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    welcome = cfg["welcome"]
    saludo_mostrar = _obtener_siguiente_saludo(language_code)
    aviso_actualizacion = ft.Container(
        content=ft.Text(
            welcome["update_notice"],
            size=18,
            color=theme["text"],
            text_align=ft.TextAlign.CENTER,
        ),
        padding=20,
        bgcolor=theme["accent"],
        border=ft.border.all(4, theme["panel_border"]),
        border_radius=16,
        width=360,
    )

    return ft.Column(
        controls=[
            ft.ProgressRing(width=56, height=56, stroke_width=6, color=theme["primary"]),
            ft.Text(welcome["title"], size=28, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
            ft.Row(
                [
                    _crear_bandera(cfg["flag"]),
                    ft.Text(cfg["native_name"], size=18, weight="bold", color=theme["text"]),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
            ),
            ft.Container(
                content=ft.Text(
                    saludo_mostrar,
                    size=18,
                    color=theme["text"],
                    text_align=ft.TextAlign.CENTER,
                ),
                padding=20,
                bgcolor=theme["field_bg"],
                border=ft.border.all(4, theme["panel_border"]),
                border_radius=16,
                width=360,
            ),
            aviso_actualizacion,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=22,
        tight=True,
    )
